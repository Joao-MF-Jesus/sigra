"""Opt-in migration/auth check: only a fresh, local sigra_tcc_*_test database.

No demo database, migrations or snapshots are accessed implicitly. The caller
creates the empty disposable target and removes it after inspecting the result.
"""
import os
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def target_url():
    raw = os.getenv("SIGRA_TCC_TEST_DATABASE_URL", "")
    if not raw:
        return None
    try:
        url = make_url(raw)
    except Exception:
        raise RuntimeError("SIGRA_TCC_TEST_DATABASE_URL is invalid; value not disclosed") from None
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not (url.database or "").startswith("sigra_tcc_") or not url.database.endswith("_test")):
        raise RuntimeError("SIGRA_TCC_TEST_DATABASE_URL must name a dedicated local sigra_tcc_*_test database")
    return raw


@pytest.mark.skipif(not os.getenv("SIGRA_TCC_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL test target not configured; not validated on PostgreSQL")
def test_postgresql_migration_auth_restart_and_defensive_downgrade(monkeypatch, record_property):
    from app import auth, main, models
    from app.database import get_db
    from backend.tests.test_participant_trials import FINANCING

    url = target_url()
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as connection:
        inspector = inspect(connection)
        schemas = [schema for schema in inspector.get_schema_names()
                   if schema != "information_schema" and not schema.startswith("pg_")]
        assert all(not inspector.get_table_names(schema=schema) for schema in schemas), "Use a NEW empty test database; no existing target is modified"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    monkeypatch.setenv("SIGRA_COOKIE_SECURE", "false")
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "false")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    previous = dict(main.app.dependency_overrides)
    def database():
        with Session(engine) as session:
            yield session
    try:
        command.upgrade(config, "20261005_0013")
        snapshots_before = None
        replay_path = os.getenv("SIGRA_ACADEMIC_V6_REPLAY_PATH")
        if replay_path:
            from app.academic_cohort.materialization import materialize
            replay = json.loads(Path(replay_path).read_text(encoding="utf-8"))
            materialize(engine, replay)  # ONLY this new, empty test target.
            with engine.connect() as connection:
                snapshots_before = connection.execute(text("SELECT row_to_json(t)::text FROM academic.cohort_snapshot t ORDER BY snapshot_id")).scalars().all()
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users(id,name,email) VALUES (34,'Preserved legacy','legacy@example.test')"))
            connection.execute(text("CREATE TABLE tcc_snapshot_preservation_probe(id integer PRIMARY KEY, fingerprint text NOT NULL)"))
            connection.execute(text("INSERT INTO tcc_snapshot_preservation_probe VALUES (1,'unchanged-v6')"))
        command.upgrade(config, "20261007_0014")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261007_0014"
            assert connection.execute(text("SELECT name,password_hash FROM users WHERE id=34")).one() == ("Preserved legacy", None)
            if snapshots_before is not None:
                assert connection.execute(text("SELECT row_to_json(t)::text FROM academic.cohort_snapshot t ORDER BY snapshot_id")).scalars().all() == snapshots_before
                assert connection.execute(text("SELECT count(*) FROM academic.cohort_vehicle")).scalar_one() == 60
                assert connection.execute(text("SELECT count(*) FROM academic.cohort_evaluation")).scalar_one() == 1080
        command.downgrade(config, "20261005_0013")
        command.upgrade(config, "20261007_0014")
        main.app.dependency_overrides[get_db] = database
        command.upgrade(config, "20261007_0015")
        auth._attempts.clear()
        headers = {"X-SIGRA-CSRF": "1"}
        password = "Disposable-postgresql-test-password"
        first = TestClient(main.app, headers=headers)
        assert first.post("/auth/register", json={"name": "Participant", "email": "pg@example.test", "password": password}).status_code == 201
        assert first.post("/auth/login", json={"email": "pg@example.test", "password": password}).status_code == 200
        response = first.post("/api/v1/test-runs/financing", json=FINANCING)
        assert response.status_code == 200
        run_id = response.json()["test_run"]["id"]
        restarted = TestClient(main.app, headers=headers)
        restarted.cookies.update(first.cookies)
        assert restarted.get(f"/api/v1/test-runs/{run_id}").status_code == 200
        with pytest.raises(RuntimeError, match="preserve participant"):
            command.downgrade(config, "20261005_0013")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT fingerprint FROM tcc_snapshot_preservation_probe")).scalar_one() == "unchanged-v6"
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261007_0015"
        with Session(engine) as session:
            assert session.query(models.ParticipantTestRun).count() == 1
        record_property("migration_cycle", "0013 -> 0014 -> 0013 -> 0014; populated downgrade rejected")
        record_property("v6_snapshot_preserved", snapshots_before is not None)
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        engine.dispose()  # Leave this caller-created test DB auditable; never drop a database implicitly.
