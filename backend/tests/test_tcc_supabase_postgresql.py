"""Opt-in REAL new-project homologation; no local test guard is weakened.

Prepare an exclusive project first. Tests persist synthetic participant records
for audit; never drop an existing database or alter the approved V6 payloads.
"""
import os
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.tcc_supabase import audit_participant_access, settings_for, target_configuration


@pytest.mark.skipif(not os.getenv("SIGRA_TCC_HOMOLOGATION_TEST_APPROVAL"),
                    reason="Dedicated Supabase PostgreSQL project/explicit approval not configured")
def test_real_supabase_v6_participants_persistence_isolation_and_permissions(monkeypatch, record_property):
    target = target_configuration(os.environ)
    assert os.environ["SIGRA_TCC_HOMOLOGATION_TEST_APPROVAL"] == target.project_ref
    from app import auth, main, models
    from app.database import create_database_engine, get_db
    from app.academic_cohort.contracts import APPROVED_FINGERPRINT
    from app.academic_cohort.models import CohortSnapshot
    operator = create_database_engine(settings_for(target.migration_url))
    runtime = create_database_engine(settings_for(target.runtime_url))
    previous = dict(main.app.dependency_overrides)
    try:
        with operator.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261007_0015"
            audit_participant_access(connection)
            before = connection.execute(text("SELECT row_to_json(t)::text FROM academic.cohort_vehicle t ORDER BY catalog_id")).scalars().all()
            assert len(before) == 60
            assert connection.execute(text("SELECT count(*) FROM academic.cohort_evaluation")).scalar_one() == 1080
        def database():
            with Session(runtime) as db:
                yield db
        main.app.dependency_overrides[get_db] = database
        monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
        monkeypatch.setenv("SIGRA_COOKIE_SECURE", "false")  # TestClient HTTP only; deployment remains HTTPS.
        monkeypatch.setenv("SIGRA_COOKIE_SAMESITE", "lax")
        monkeypatch.setenv("PUBLIC_DEMO_MODE", "false")
        monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "homologation")
        monkeypatch.setenv("SIGRA_RESEARCH_PSEUDONYM_KEY", "test-only-pseudonym-key-for-disposable-homologation")
        auth._attempts.clear()
        first, second = [TestClient(main.app, headers={"X-SIGRA-CSRF": "1"}) for _ in range(2)]
        accounts = []
        for client in (first, second):
            email = f"pg-trial-{uuid4().hex}@example.test"
            credentials = {"email": email, "password": "Synthetic-postgresql-trial-only-password"}
            created = client.post("/auth/register", json={"name": "Synthetic homol participant", **credentials})
            assert created.status_code == 201
            accounts.append(created.json())
            assert client.post("/auth/login", json=credentials).status_code == 200
            assert client.post("/auth/register", json={"name": "Duplicate", **credentials}).status_code == 409
            assert client.post("/auth/register", json={"name": "Forbidden admin", **credentials, "role": "admin"}).status_code == 422
        with Session(runtime) as db:
            snapshot = db.query(CohortSnapshot).filter_by(cohort_fingerprint=APPROVED_FINGERPRINT).one()
            snapshot_id = str(snapshot.snapshot_id)
        payload = {"budget": 1000000, "monthly_limit": 100000, "use_case": "app",
                   "monthly_mileage": 1000, "fuel_price": 6, "candidate_source": "academic_v6",
                   "academic_options": {"snapshot_id": snapshot_id}}
        from backend.tests.test_study_protocol import BEFORE, ANSWERS
        assert first.post("/api/v1/study-sessions", json=BEFORE).status_code == 201
        response = first.post("/api/v1/test-runs/recommendation", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result["considered_count"] == result["eligible_count"] == 60
        assert result["stored_scores_used"] is False
        run_id = result["test_run"]["id"]
        assert first.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json=ANSWERS).status_code == 200
        assert second.get(f"/api/v1/test-runs/{run_id}").status_code == 404
        assert second.get("/api/v1/test-runs").json()["total"] == 0
        assert second.get("/api/v1/admin/test-runs.csv").status_code == 403
        assert TestClient(main.app).get("/api/v1/test-runs").status_code == 401
        # Dispose/recreate the DB connection pool and API client: no SQLite fallback.
        runtime.dispose()
        restarted = TestClient(main.app, headers={"X-SIGRA-CSRF": "1"})
        restarted.cookies.update(first.cookies)
        persisted = restarted.get(f"/api/v1/test-runs/{run_id}")
        assert persisted.status_code == 200 and persisted.json()["questionnaire"]["interface_clarity"] == 5
        assert persisted.json()["technical_record"]["analysis_ready"] is True
        assert persisted.json()["snapshot_fingerprint"] == APPROVED_FINGERPRINT
        assert persisted.json()["parameters"] == main.RecommendationRequest.model_validate(payload).model_dump(mode="json")
        with Session(operator) as db:
            db.get(models.User, accounts[0]["id"]).role = "admin"  # Only this synthetic test account.
            db.commit()
        export = restarted.get("/api/v1/admin/test-runs.csv")
        assert export.status_code == 200 and "participant_code" in export.text
        assert accounts[0]["email"] not in export.text
        assert restarted.post("/auth/logout", json={}).status_code == 204
        assert restarted.get("/auth/me").status_code == 401
        with operator.connect() as connection:
            assert connection.execute(text("SELECT row_to_json(t)::text FROM academic.cohort_vehicle t ORDER BY catalog_id")).scalars().all() == before
        record_property("postgresql_source", "Supabase dedicated project; approved V6 60/1080")
        record_property("restart_scope", "API client and database pool recreated; separate OS-process restart still required")
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        runtime.dispose()
        operator.dispose()
