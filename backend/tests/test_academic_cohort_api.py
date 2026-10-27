"""Synthetic fixtures here only; production admission always pins the real replay."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.academic_cohort.contracts import APPROVED_FINGERPRINT, MaterializationPlan, PROFILE_COUNTS, PROFILES, SCENARIOS, json_document, method_manifest, validate_replay
from app.academic_cohort.materialization import _materialize_plan, materialize
from app.academic_cohort.models import AcademicBase, CohortEvaluation, CohortSnapshot, CohortVehicle
from app.academic_cohort.repository import AcademicRepository
from app.academic_cohort.routes import get_academic_service, router
from app.academic_cohort.service import AcademicService
from app.http_middleware import PublicDemoReadOnlyMiddleware
from data_platform.catalog import academic_cohort_v6 as v6
from data_platform.catalog.profile_pilot_v4 import fingerprint, rankings


def fixture_plan():
    config = v6.configuration()
    ids = sorted(config['baseline_ready_ids'] + config['additional_selected_ids'])
    vehicles, evaluations = [], []
    for index, identifier in enumerate(ids):
        code = f'{index:06d}-1'
        price = Decimal('50000.00') + index
        month = '2026-10' if identifier in (122, 123, 124, 125) else '2026-09'
        payload = {'id': identifier, 'label': 'Synthetic unit fixture', 'fields': {
            'fipe_code': {'value': code}, 'year_code': {'value': '2020-1'},
            'price_brl': {'value': str(price)}, 'reference_month': {'value': month}}}
        vehicles.append({'catalog_id': identifier, 'canonical_identity_key': fingerprint([code, '2020-1']),
                         'fipe_code': code, 'year_code': '2020-1', 'label': payload['label'],
                         'purchase_price_brl': price, 'reference_month': month, 'payload': payload,
                         'payload_fingerprint': fingerprint(payload)})
        for scenario in SCENARIOS:
            for profile in PROFILES:
                ready = index < PROFILE_COUNTS[profile]
                total = Decimal({'low': '1000.00', 'base': '1500.00', 'high': '2000.00'}[scenario]) + index
                score = Decimal('90.0000') - index
                result = {'id': identifier, 'vehicle': payload['label'], 'profile': profile, 'scenario': scenario,
                          'academic_test_ready': ready, 'preview_score': str(score),
                          'scenario_monthly_tco_brl': str(total), 'comparison_group': 'synthetic-unit-group',
                          'criteria': {'passenger_space': {'nature': 'derived_academic', 'path': 'academic_habitability_proxy'}},
                          'scenario_costs': {'scenario_total': {'nature': 'scenario_estimate'}},
                          'price_reference_month': month, 'operationally_active': False, 'recommended': False}
                evaluations.append({'catalog_id': identifier, 'profile': profile, 'scenario': scenario,
                                    'academic_test_ready': ready, 'score': score, 'monthly_tco_brl': total,
                                    'payload': result, 'payload_fingerprint': fingerprint(result)})
    summary = {'inventory_count': 81, 'selected_ids': ids, 'holdout_ids': list(v6.HOLDOUTS),
               'outside_selection': [{'id': i} for i in (*v6.HOLDOUTS, 35, 101, 103, 111)]}
    return MaterializationPlan(APPROVED_FINGERPRINT, method_manifest(), summary, tuple(vehicles), tuple(evaluations))


@pytest.fixture
def persisted():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool,
                           execution_options={'schema_translate_map': {'academic': None}})
    AcademicBase.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE vehicles (id integer PRIMARY KEY, marker varchar(40))'))
        connection.execute(text("INSERT INTO vehicles VALUES (2,'preexisting operational vehicle')"))
    plan = fixture_plan()
    with Session(engine) as session, session.begin():
        receipt = _materialize_plan(session, plan)
    yield engine, plan, receipt
    engine.dispose()


@pytest.fixture
def client(persisted, monkeypatch):
    engine, _, _ = persisted
    monkeypatch.setenv('ACADEMIC_COHORT_ENABLED', 'true')
    application = FastAPI()
    application.include_router(router)
    def service():
        with Session(engine) as session:
            yield AcademicService(AcademicRepository(session))
    application.dependency_overrides[get_academic_service] = service
    with TestClient(application) as client:
        yield client


def test_default_disabled_mode_does_not_read_database(monkeypatch):
    monkeypatch.delenv('ACADEMIC_COHORT_ENABLED', raising=False)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_academic_service] = lambda: pytest.fail('Disabled mode consulted database')
    with TestClient(app) as client:
        response = client.get('/api/v1/academic-cohort/metadata')
    assert response.status_code == 404


def test_idempotent_materialization_keeps_operational_catalog(persisted):
    engine, plan, first = persisted
    with Session(engine) as session, session.begin():
        second = _materialize_plan(session, plan)
    assert second.snapshot_id == first.snapshot_id and not second.database_modified
    assert first.selected_count == 60 and first.evaluation_count == 1080
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id,marker FROM vehicles')).one() == (2, 'preexisting operational vehicle')


def test_atomic_rollback_on_failure_after_snapshot_insert():
    engine = create_engine('sqlite://', execution_options={'schema_translate_map': {'academic': None}})
    AcademicBase.metadata.create_all(engine)
    plan = fixture_plan()
    broken = deepcopy(plan.vehicles[0])
    rows = (*plan.vehicles[:-1], broken)  # exact primary key collision after first flush
    bad = MaterializationPlan(plan.cohort_fingerprint, plan.source_manifest, plan.summary, rows, plan.evaluations)
    with pytest.raises(IntegrityError):
        with Session(engine) as session, session.begin():
            _materialize_plan(session, bad)
    with Session(engine) as session:
        assert session.scalars(select(CohortSnapshot)).all() == []
    engine.dispose()


def test_materialization_rejects_sqlite_without_fallback(persisted):
    with pytest.raises(ValueError, match='no SQLite fallback'):
        materialize(persisted[0], {})


def test_whole_replay_fingerprint_rejects_synthetic_or_edited_payload():
    with pytest.raises(ValueError, match='approved v6 fingerprint'):
        validate_replay({'version': v6.VERSION, 'academic_payload': []})


def test_pagination_is_stable_complete_and_empty_page_keeps_total(client):
    ids = []
    for offset in range(0, 60, 7):
        page = client.get('/api/v1/academic-cohort/vehicles', params={'limit': 7, 'offset': offset})
        assert page.status_code == 200 and page.json()['total'] == 60
        ids += [row['catalog_id'] for row in page.json()['items']]
    assert len(ids) == len(set(ids)) == 60
    response = client.get('/api/v1/academic-cohort/vehicles?offset=999')
    assert response.json()['items'] == [] and response.json()['total'] == 60
    assert not set(v6.HOLDOUTS) & set(ids) and not {101, 103, 111} & set(ids)


@pytest.mark.parametrize('profile,count', list(PROFILE_COUNTS.items()))
def test_six_profile_coverage_and_existing_ranking_function(client, profile, count):
    response = client.post('/api/v1/academic-cohort/evaluate', json={'profile': profile, 'limit': 60})
    assert response.status_code == 200
    result = response.json()
    assert result['eligible_count'] == len(result['eligible_ids']) == count
    assert result['mode'] == 'academic_only' and result['operationally_active'] is False and result['recommended'] is False
    rows = [{**r, 'preview_score': Decimal(r['preview_score'])} for r in result['evaluations'].values()]
    assert result['groups'] == json_document(rankings(rows))


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_three_cost_scenarios_keep_their_nature(client, scenario):
    result = client.post('/api/v1/academic-cohort/evaluate', json={'profile': 'app', 'scenario': scenario}).json()
    assert result['eligible_count'] == 60 and len(result['returned_ids']) == 10
    for item in result['evaluations'].values():
        assert item['scenario_costs']['scenario_total']['nature'] == 'scenario_estimate'
        assert item['criteria']['passenger_space']['path'] == 'academic_habitability_proxy'


def test_purchase_budget_is_not_monthly_budget_and_empty_filter_has_no_fallback(client):
    all_rows = client.post('/api/v1/academic-cohort/evaluate', json={'profile': 'app', 'max_purchase_price_brl': '60000'}).json()
    empty = client.post('/api/v1/academic-cohort/evaluate', json={'profile': 'app', 'max_monthly_tco_brl': '100'}).json()
    assert all_rows['eligible_count'] == 60
    assert empty['eligible_count'] == 0 and empty['eligible_ids'] == [] and empty['groups'] == {} and empty['empty_reason']


@pytest.mark.parametrize('body', [
    {'profile': 'unknown'}, {'profile': 'app', 'scenario': 'observed'},
    {'profile': 'app', 'limit': 0}, {'profile': 'app', 'limit': 61},
    {'profile': 'app', 'limit': True}, {'profile': 'app', 'max_purchase_price_brl': -1},
    {'profile': 'app', 'max_monthly_tco_brl': 'NaN'}, {'profile': 'app', 'monthly_km': 1200},
    {'profile': 'app', 'weights': {}}, {'profile': 'app', 'operationally_active': True},
])
def test_unsupported_parameters_fail_closed(client, body):
    assert client.post('/api/v1/academic-cohort/evaluate', json=body).status_code == 422


@pytest.mark.parametrize('parameters', [
    {'offset': -1}, {'limit': 61}, {'fipe_code': 'approximately matching name'},
    {'max_purchase_price_brl': 'NaN'}, {'max_monthly_tco_brl': 'Infinity'},
    {'reference_month': '2026-08'},
])
def test_invalid_listing_filters_fail_closed(client, parameters):
    assert client.get('/api/v1/academic-cohort/vehicles', params=parameters).status_code == 422


def test_persisted_coverage_tampering_fails_closed(persisted, client):
    engine, _, receipt = persisted
    with Session(engine) as session, session.begin():
        snapshot = session.get(CohortSnapshot, receipt.snapshot_id)
        snapshot.profile_counts = {**snapshot.profile_counts, 'familia': 60}
    assert client.get('/api/v1/academic-cohort/metadata').status_code == 503


def test_persisted_identity_metadata_tampering_fails_closed(persisted, client):
    engine, _, receipt = persisted
    with Session(engine) as session, session.begin():
        vehicle = session.get(CohortVehicle, (receipt.snapshot_id, 2))
        vehicle.year_code = '2030-1'
    assert client.get('/api/v1/academic-cohort/vehicles/2').status_code == 503


def test_production_dependency_rejects_sqlite(persisted, monkeypatch):
    from app.database import get_db
    monkeypatch.setenv('ACADEMIC_COHORT_ENABLED', 'true')
    app = FastAPI()
    app.include_router(router)
    def database():
        with Session(persisted[0]) as session:
            yield session
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        response = client.get('/api/v1/academic-cohort/metadata')
    assert response.status_code == 503 and response.json()['detail']['code'] == 'academic_postgresql_required'


def test_identity_detail_reference_month_and_holdouts(client):
    detail = client.get('/api/v1/academic-cohort/vehicles/122')
    assert detail.status_code == 200 and detail.json()['vehicle']['price_reference_month'] == '2026-10'
    assert detail.json()['evidence']['id'] == 122
    for identifier in (1, 101, 103, 111):
        assert client.get(f'/api/v1/academic-cohort/vehicles/{identifier}').status_code == 404
    for month in ('2026-09', '2026-10'):
        page = client.get('/api/v1/academic-cohort/vehicles', params={'reference_month': month, 'limit': 60})
        assert all(row['price_reference_month'] == month for row in page.json()['items'])


def test_missing_or_foreign_snapshot_does_not_fall_back(client):
    response = client.get('/api/v1/academic-cohort/metadata', params={'snapshot_id': str(uuid4())})
    assert response.status_code == 404


def test_changed_payload_fails_read_and_idempotence_closed(persisted, client):
    engine, plan, receipt = persisted
    with Session(engine) as session, session.begin():
        evaluation = session.get(CohortEvaluation, (receipt.snapshot_id, 2, 'app', 'base'))
        evaluation.payload = {**evaluation.payload, 'preview_score': '0'}
    assert client.post('/api/v1/academic-cohort/evaluate', json={'profile': 'app'}).status_code == 503
    with pytest.raises(ValueError, match='evaluation changed'):
        with Session(engine) as session, session.begin():
            _materialize_plan(session, plan)


def test_read_only_public_demo_allows_academic_evaluation_but_not_mutation(persisted, monkeypatch):
    monkeypatch.setenv('ACADEMIC_COHORT_ENABLED', 'true')
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(PublicDemoReadOnlyMiddleware, enabled=True)
    def service():
        with Session(persisted[0]) as session:
            yield AcademicService(AcademicRepository(session))
    app.dependency_overrides[get_academic_service] = service
    with TestClient(app) as client:
        assert client.post('/api/v1/academic-cohort/evaluate', json={'profile': 'app'}).status_code == 200
        assert client.post('/api/v1/academic-cohort/materialize').status_code == 403
