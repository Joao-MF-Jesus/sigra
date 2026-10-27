"""Real PostgreSQL + approved canonical replay. Skips mean integration is PARTIAL."""
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session

from data_platform.tests.postgresql_safety import disposable_postgresql_url

TARGET = disposable_postgresql_url()
REPLAY = os.getenv('SIGRA_ACADEMIC_V6_REPLAY_PATH', '')
pytestmark = pytest.mark.skipif(not TARGET or not REPLAY,
                               reason='Academic v6 requires configured local PostgreSQL _test and approved replay; NOT validated')


@pytest.fixture(scope='module')
def real_snapshot():
    from alembic import command
    from alembic.config import Config
    from app.academic_cohort.contracts import validate_replay
    from app.academic_cohort.materialization import materialize
    from app.academic_cohort.models import CohortSnapshot
    root = Path(__file__).resolve().parents[2]
    replay = json.loads(Path(REPLAY).read_text(encoding='utf-8'))
    plan = validate_replay(replay)  # fail before migration or any database write
    engine = create_engine(TARGET, pool_pre_ping=True)
    prior_environment = os.environ.get('MIGRATION_DATABASE_URL')
    try:
        os.environ['MIGRATION_DATABASE_URL'] = TARGET
        config = Config(str(root/'backend/alembic.ini'))
        command.upgrade(config, '20260811_0012')
        # A real preexisting sentinel in this user-created disposable target proves
        # preservation even when operational tables are otherwise empty.
        probe = 'academic_preservation_probe_' + uuid4().hex
        quote = engine.dialect.identifier_preparer.quote
        with engine.begin() as connection:
            connection.execute(text(f'CREATE TABLE public.{quote(probe)} (id integer PRIMARY KEY, marker text NOT NULL)'))
            connection.execute(text(f'INSERT INTO public.{quote(probe)} (id, marker) VALUES (:id, :marker)'),
                               {'id': 2, 'marker': 'preexisting operational identity must not be overwritten'})
        with engine.connect() as connection:
            inspector = inspect(connection)
            before = {}
            for schema in inspector.get_schema_names():
                if schema == 'academic' or schema == 'information_schema' or schema.startswith('pg_'):
                    continue
                for table in inspector.get_table_names(schema=schema):
                    if table != 'alembic_version':
                        identifier = f'{quote(schema)}.{quote(table)}'
                        before[identifier] = connection.execute(text(f'SELECT row_to_json(t)::text FROM {identifier} t ORDER BY row_to_json(t)::text')).scalars().all()
        command.upgrade(config, '20261005_0013')
        # Refuse reusing a target already containing this snapshot; first-run proof must be real.
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(CohortSnapshot)) == 0, 'Use a fresh dedicated local test database'
        first = materialize(engine, replay)
        second = materialize(engine, replay)
        yield engine, replay, plan, first, second, before
        # No cleanup of database objects here: user-created test DB remains auditable.
        with engine.connect() as connection:
            for table, rows in before.items():
                after = connection.execute(text(f'SELECT row_to_json(t)::text FROM {table} t ORDER BY row_to_json(t)::text')).scalars().all()
                assert after == rows
    finally:
        if prior_environment is None:
            os.environ.pop('MIGRATION_DATABASE_URL', None)
        else:
            os.environ['MIGRATION_DATABASE_URL'] = prior_environment
        engine.dispose()


def test_real_first_second_materialization_and_separate_ids(real_snapshot):
    from app.academic_cohort.models import CohortSnapshot, CohortVehicle, CohortEvaluation
    engine, _, _, first, second, _ = real_snapshot
    assert first.status == 'materialized' and first.database_modified
    assert second.status == 'already_materialized' and not second.database_modified
    assert first.snapshot_id == second.snapshot_id
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CohortSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(CohortVehicle)) == 60
        assert session.scalar(select(func.count()).select_from(CohortEvaluation)) == 1080
        ids = session.scalars(select(CohortVehicle.catalog_id)).all()
        assert len(ids) == len(set(ids)) == 60 and not {1, 101, 103, 111} & set(ids)
    assert not CohortVehicle.__table__.c.catalog_id.foreign_keys


def test_real_atomic_rollback_and_constraints(real_snapshot):
    from dataclasses import replace
    from app.academic_cohort.materialization import _materialize_plan
    from app.academic_cohort.models import CohortSnapshot
    from sqlalchemy.exc import IntegrityError
    engine, _, plan, _, _, _ = real_snapshot
    # A distinct test fingerprint reaches insertion, then an actual PK collision rolls back all writes.
    broken = replace(plan, cohort_fingerprint='a'*64, vehicles=(*plan.vehicles[:-1], plan.vehicles[0]))
    with pytest.raises(IntegrityError):
        with Session(engine) as session, session.begin():
            _materialize_plan(session, broken)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CohortSnapshot)) == 1
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text('UPDATE academic.cohort_snapshot SET operationally_active=TRUE'))


def test_real_api_equivalence_all_profiles_all_scenarios_and_no_writes(real_snapshot, monkeypatch):
    from app.academic_cohort.contracts import PROFILE_COUNTS
    from app.academic_cohort.repository import AcademicRepository
    from app.academic_cohort.routes import router, get_academic_service
    from app.academic_cohort.service import AcademicService
    from data_platform.catalog.profile_pilot_v4 import fingerprint
    engine, replay, _, _, _, _ = real_snapshot
    monkeypatch.setenv('ACADEMIC_COHORT_ENABLED', 'true')
    app = FastAPI()
    app.include_router(router)
    def service():
        with Session(engine) as session:
            yield AcademicService(AcademicRepository(session))
    app.dependency_overrides[get_academic_service] = service
    statements = []
    def audit(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.split()[0].upper())
    event.listen(engine, 'before_cursor_execute', audit)
    try:
        with TestClient(app) as client:
            ids = []
            for offset in range(0, 60, 11):
                page = client.get('/api/v1/academic-cohort/vehicles', params={'limit': 11, 'offset': offset})
                assert page.status_code == 200 and page.json()['total'] == 60
                ids += [r['catalog_id'] for r in page.json()['items']]
            assert sorted(ids) == replay['selected_ids'] and len(ids) == len(set(ids))
            expected = {r['vehicle']['id']: r for r in replay['academic_payload']}
            for profile, count in PROFILE_COUNTS.items():
                for scenario in ('low','base','high'):
                    response = client.post('/api/v1/academic-cohort/evaluate', json={'profile': profile, 'scenario': scenario, 'limit': 60})
                    assert response.status_code == 200
                    body = response.json()
                    assert body['eligible_count'] == count
                    if profile == 'app': assert sorted(body['eligible_ids']) == replay['selected_ids']
                    for identifier, result in body['evaluations'].items():
                        assert fingerprint(result) == fingerprint(expected[int(identifier)]['evaluations'][scenario][profile])
            for identifier in (122,123,124,125):
                detail = client.get(f'/api/v1/academic-cohort/vehicles/{identifier}')
                assert detail.status_code == 200 and detail.json()['vehicle']['price_reference_month'] == '2026-10'
            assert client.get('/api/v1/academic-cohort/vehicles/1').status_code == 404
            empty = client.post('/api/v1/academic-cohort/evaluate', json={'profile':'app','max_purchase_price_brl':'1'}).json()
            assert empty['eligible_ids'] == [] and empty['empty_reason']
        assert statements and set(statements) == {'SELECT'}
    finally:
        event.remove(engine, 'before_cursor_execute', audit)


def test_real_migration_defensive_downgrade(real_snapshot):
    from alembic import command
    from alembic.config import Config
    engine = real_snapshot[0]
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261005_0013'
        assert {'cohort_snapshot','cohort_vehicle','cohort_evaluation'} <= set(inspect(connection).get_table_names(schema='academic'))
    config = Config(str(Path(__file__).resolve().parents[2]/'backend/alembic.ini'))
    with pytest.raises(RuntimeError, match='historical snapshots'):
        command.downgrade(config, '20260811_0012')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '20261005_0013'
