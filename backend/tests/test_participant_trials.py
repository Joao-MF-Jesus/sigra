"""Authentication, real calculators and restart persistence in disposable databases only."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from app import auth, main, models
from app.database import Base, get_db
from app.participant_trials import fingerprint

HEADERS = {"X-SIGRA-CSRF": "1"}
PASSWORD = "Disposable-test-password-2026"
FINANCING = {"vehicle_type": "car", "vehicle_price": "40000", "down_payment": "10000",
             "term_months": 36, "monthly_interest_rate_percent": "1",
             "upfront_fees": "0", "financed_fees": "0", "financed_insurance": "0", "financed_services": "0"}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'participants_test.sqlite'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    def database():
        with Session(engine) as db:
            yield db
    previous = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[get_db] = database
    monkeypatch.setenv("SIGRA_COOKIE_SECURE", "false")
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "false")
    monkeypatch.setenv("FIPE_AUTO_REFRESH", "false")
    monkeypatch.setenv("SIGRA_RESEARCH_PSEUDONYM_KEY", "test-only-research-pseudonym-key-not-a-deployment-secret")
    auth._attempts.clear()
    yield engine
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(previous)
    engine.dispose()


def client():
    return TestClient(main.app, headers=HEADERS)


def register_and_login(http, email="participant@example.test"):
    response = http.post("/auth/register", json={"name": "Participante", "email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    logged = http.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert logged.status_code == 200, logged.text
    return logged.json()


def test_registration_normalizes_duplicates_and_hashes(storage):
    http = client()
    user = register_and_login(http, "  Participant@Example.Test ")
    assert user["email"] == "participant@example.test" and user["role"] == "participant"
    assert set(user) == {"id", "name", "email", "role"}
    duplicate = http.post("/auth/register", json={"name": "Outro", "email": "PARTICIPANT@example.test", "password": PASSWORD})
    assert duplicate.status_code == 409
    with Session(storage) as db:
        account = db.get(models.User, user["id"])
        assert account.password_hash != PASSWORD
        assert auth.verify_password(PASSWORD, account.password_hash)
        assert not auth.verify_password("wrong-password-long", account.password_hash)
        assert db.query(models.User).count() == 1
        session = db.query(models.AuthSession).one()
        assert session.token_digest != http.cookies[auth.COOKIE_NAME]


def test_system_version_hashes_actual_code_and_timestamps_are_explicit_utc(storage, monkeypatch):
    from app.participant_trials import system_version
    monkeypatch.delenv("SIGRA_SYSTEM_VERSION", raising=False)
    system_version.cache_clear()
    assert system_version().startswith("src-")
    assert system_version() != "src-" + fingerprint({})
    http = client()
    register_and_login(http)
    receipt = http.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]
    assert receipt["created_at"].endswith("+00:00")
    assert http.get(f"/api/v1/test-runs/{receipt['id']}").json()["created_at"].endswith("+00:00")
    system_version.cache_clear()


def test_cookie_security_and_secure_default(storage, monkeypatch):
    http = client()
    register_and_login(http)
    cookie = http.post("/auth/login", json={"email": "participant@example.test", "password": PASSWORD}).headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=28800" in cookie
    monkeypatch.delenv("SIGRA_COOKIE_SECURE", raising=False)
    cookie = http.post("/auth/login", json={"email": "participant@example.test", "password": PASSWORD}).headers["set-cookie"]
    assert "Secure" in cookie


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"id": 99}, {"is_admin": True}])
def test_self_escalation_rejected(storage, extra):
    response = client().post("/auth/register", json={"name": "Participante", "email": "new@example.test", "password": PASSWORD, **extra})
    assert response.status_code == 422
    assert PASSWORD not in response.text
    with Session(storage) as db:
        assert db.query(models.User).count() == 0


def test_invalid_secret_never_in_validation_response(storage):
    password = "tiny-secret"
    response = client().post("/auth/register", json={"name": "Ok", "email": "a@example.test", "password": password})
    assert response.status_code == 422 and password not in response.text


def test_bad_password_logout_and_session_persistence(storage):
    http = client()
    user = register_and_login(http)
    wrong = client().post("/auth/login", json={"email": user["email"], "password": "wrong-password-long"})
    assert wrong.status_code == 401
    # New API client/session factory, same persistent DB and existing opaque session.
    restarted = client()
    restarted.cookies.update(http.cookies)
    assert restarted.get("/auth/me").json()["id"] == user["id"]
    assert http.post("/auth/logout", json={}).status_code == 204
    assert restarted.get("/auth/me").status_code == 401
    assert http.get("/auth/session").json() == {"user": None}


def test_expiry_and_fake_session_fail_closed(storage):
    http = client()
    register_and_login(http)
    with Session(storage) as db:
        db.query(models.AuthSession).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert http.get("/auth/me").status_code == 401
    http.cookies.set(auth.COOKIE_NAME, "A"*43)
    assert http.get("/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/test-runs", "/api/v1/admin/test-runs.csv", "/expenses", "/maintenances", "/user-vehicles", "/reports/financial-summary"])
def test_anonymous_private_access_denied(storage, path):
    assert client().get(path).status_code == 401


def test_csrf_and_untrusted_origin(storage):
    response = TestClient(main.app).post("/auth/register", json={"name": "Test", "email": "a@example.test", "password": PASSWORD})
    assert response.status_code == 403
    http = client()
    register_and_login(http)
    assert http.post("/auth/logout", json={}, headers={"Origin": "https://other.example"}).status_code == 403
    assert TestClient(main.app).get("/auth/session").status_code == 200


def test_financing_is_recorded_from_server_not_browser_and_feedback(storage):
    http = client()
    user = register_and_login(http)
    stateless = http.post("/financing/simulate", json=FINANCING).json()
    response = http.post("/api/v1/test-runs/financing", json=FINANCING)
    assert response.status_code == 200, response.text
    result = response.json()
    run_id = result.pop("test_run")["id"]
    assert result == stateless
    record = http.get(f"/api/v1/test-runs/{run_id}").json()
    assert record["presented_results"] == stateless
    assert record["result_fingerprint"] == fingerprint(stateless)
    with Session(storage) as db:
        assert db.get(models.ParticipantTestRun, run_id).user_id == user["id"]
    response = http.patch(f"/api/v1/test-runs/{run_id}/feedback", json={"rating": 4, "comment": "Muito claro"})
    assert response.status_code == 200
    record = http.get(f"/api/v1/test-runs/{run_id}").json()
    assert record["feedback_rating"] == 4 and record["feedback_comment"] == "Muito claro"
    assert record["presented_results"] == stateless
    restarted = client()
    restarted.cookies.update(http.cookies)
    assert restarted.get("/api/v1/test-runs").json()["total"] == 1
    assert restarted.get(f"/api/v1/test-runs/{run_id}").json()["feedback_comment"] == "Muito claro"


@pytest.mark.parametrize("change", [{"rating": 0}, {"rating": 6}, {"rating": True}, {"rating": 2, "user_id": 2}])
def test_feedback_constraints(storage, change):
    http = client()
    register_and_login(http)
    run_id = http.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    assert http.patch(f"/api/v1/test-runs/{run_id}/feedback", json=change).status_code == 422


def test_other_participant_and_non_admin_cannot_access(storage):
    first, second = client(), client()
    owner = register_and_login(first, "owner@example.test")
    register_and_login(second, "other@example.test")
    run_id = first.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    assert second.get("/api/v1/test-runs").json()["total"] == 0
    assert second.get(f"/api/v1/test-runs/{run_id}").status_code == 404
    assert second.patch(f"/api/v1/test-runs/{run_id}/feedback", json={"rating": 1}).status_code == 404
    assert second.get(f"/reports/financial-summary?user_id={owner['id']}").status_code == 403
    assert second.get("/api/v1/admin/test-runs.csv").status_code == 403
    assert second.post("/users", json={"name": "Admin", "email": "admin@example.test"}).status_code == 403
    assert second.post("/vehicles", json={}).status_code == 403


def test_export_admin_only_no_hashes_or_sessions_and_safe_csv(storage):
    http = client()
    user = register_and_login(http)
    run_id = http.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    http.patch(f"/api/v1/test-runs/{run_id}/feedback", json={"rating": 5, "comment": "=SUM(1,2)"})
    with Session(storage) as db:
        db.get(models.User, user["id"]).role = "admin"  # Operator-only assignment, never a public API.
        db.commit()
    response = http.get("/api/v1/admin/test-runs.csv")
    assert response.status_code == 200 and "'=SUM(1,2)" in response.text
    assert PASSWORD not in response.text and "password_hash" not in response.text and "token_digest" not in response.text
    assert run_id in response.text
    assert "participant_code" in response.text
    assert "participant_email" not in response.text and "participant_name" not in response.text
    assert user["email"] not in response.text and user["name"] not in response.text


def test_export_requires_private_pseudonym_key(storage, monkeypatch):
    http = client()
    user = register_and_login(http)
    with Session(storage) as db:
        db.get(models.User, user["id"]).role = "admin"
        db.commit()
    monkeypatch.delenv("SIGRA_RESEARCH_PSEUDONYM_KEY", raising=False)
    assert http.get("/api/v1/admin/test-runs.csv").status_code == 503


def test_participant_codes_are_stable_distinct_and_keyed():
    from app.participant_trials import participant_code
    key = b"synthetic-test-key-at-least-32-bytes"
    assert participant_code(1, key) == participant_code(1, key)
    assert participant_code(1, key) != participant_code(2, key)
    assert participant_code(1, key) != participant_code(1, b"another-synthetic-key-at-least-32bytes")


def test_real_recommendation_engine_unchanged_and_recorded(storage, monkeypatch):
    from backend.tests.test_academic_recommendation import MemoryRepository, request
    from app.academic_cohort.service import AcademicService
    service = AcademicService(MemoryRepository())
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda db: service)
    http = client()
    register_and_login(http)
    payload = request(service).model_dump(mode="json")
    response = http.post("/api/v1/test-runs/recommendation", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["considered_count"] == 60
    assert result["operationally_active"] is False and result["recommended"] is False
    run_id = result.pop("test_run")["id"]
    saved = http.get(f"/api/v1/test-runs/{run_id}").json()
    assert saved["presented_results"] == result
    assert saved["snapshot_fingerprint"] == service.repository.snapshot(None).cohort_fingerprint
    assert saved["parameters"] == payload
    assert result["stored_scores_used"] is False


def test_failed_calculation_does_not_create_record(storage):
    http = client()
    register_and_login(http)
    assert http.post("/api/v1/test-runs/financing", json={**FINANCING, "down_payment": "999999"}).status_code == 422
    assert http.get("/api/v1/test-runs").json()["total"] == 0


@pytest.mark.parametrize("technical_status", [
    {"status": "succeeded", "analysis_ready": True, "error_code": None},
    {"status": "failed", "analysis_ready": False, "error_code": "HTTP_422"},
    {},
])
def test_compact_history_does_not_load_large_payloads_or_change_details(storage, technical_status):
    import json
    http = client()
    register_and_login(http)
    run_id = http.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    # Explicitly fictitious large evidence; no production records or banks.
    with Session(storage) as db:
        run = db.get(models.ParticipantTestRun, run_id)
        run.technical_record = {**technical_status, "test_only_large_evidence": "x" * 200000}
        run.presented_results = {**run.presented_results, "test_only_large_result": "y" * 200000}
        run.result_fingerprint = fingerprint(run.presented_results)
        db.commit()
    before = http.get(f"/api/v1/test-runs/{run_id}").json()
    statements = []
    def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(storage, "before_cursor_execute", observe)
    try:
        response = http.get("/api/v1/test-runs?compact=true")
    finally:
        event.remove(storage, "before_cursor_execute", observe)
    assert response.status_code == 200
    compact = response.json()
    assert compact["history_view"] == "compact-v1" and compact["total"] == 1
    item = compact["items"][0]
    assert item["technical_record"] == {key: technical_status.get(key) for key in ("status", "error_code", "analysis_ready")}
    assert "presented_results" not in item
    assert "test_only_large_evidence" not in response.text
    assert len(response.content) < 10000
    data_queries = [sql for sql in statements if "participant_test_runs" in sql and "count(" not in sql.lower()]
    assert data_queries
    assert all("participant_test_runs.presented_results AS" not in sql for sql in data_queries)
    assert all("participant_test_runs.technical_record AS" not in sql for sql in data_queries)
    default = http.get("/api/v1/test-runs").json()["items"][0]
    assert default["technical_record"] == before["technical_record"]
    for key in ("parameters", "request_fingerprint", "result_fingerprint", "questionnaire", "study_session"):
        assert item[key] == before[key] == default[key]
    after = http.get(f"/api/v1/test-runs/{run_id}").json()
    assert after == before
    assert fingerprint(after) == fingerprint(before)
    assert json.dumps(before["presented_results"]) == json.dumps(after["presented_results"])


def test_compact_history_preserves_pagination_and_owner_scope(storage):
    first, other = client(), client()
    register_and_login(first, "compact-owner@example.test")
    register_and_login(other, "compact-other@example.test")
    for _ in range(2):
        assert first.post("/api/v1/test-runs/financing", json=FINANCING).status_code == 200
    page_one = first.get("/api/v1/test-runs?compact=true&limit=1&offset=0").json()
    page_two = first.get("/api/v1/test-runs?compact=true&limit=1&offset=1").json()
    assert page_one["total"] == page_two["total"] == 2
    assert page_one["items"][0]["id"] != page_two["items"][0]["id"]
    assert other.get("/api/v1/test-runs?compact=true").json()["items"] == []
    assert other.get("/api/v1/test-runs/" + page_one["items"][0]["id"]).status_code == 404
    assert other.get("/api/v1/admin/test-runs.csv").status_code == 403
    assert client().get("/api/v1/test-runs?compact=true").status_code == 401


def test_legacy_export_excludes_credentials_sessions_and_private_results(storage):
    import sys
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkey_path = str(scripts)
    sys.path.insert(0, monkey_path)
    try:
        from database_migration_common import database_snapshot, expected_schema_contract
        http = client()
        register_and_login(http)
        http.post("/api/v1/test-runs/financing", json=FINANCING)
        snapshot = database_snapshot(storage)
        assert "auth_sessions" not in snapshot
        assert "participant_test_runs" not in snapshot
        assert set(snapshot["users"][0]) == {"id", "name", "email"}
        assert set(expected_schema_contract()["users"]["columns"]) == {"id", "name", "email"}
        assert PASSWORD not in str(snapshot) and "pbkdf2_sha256" not in str(snapshot)
    finally:
        sys.path.remove(monkey_path)


def migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261007_0014_tcc_participant_trials.py"
    spec = importlib.util.spec_from_file_location("participant_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_downgrade_and_preservation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration_test.sqlite'}")
    migration = migration_module()
    with engine.begin() as db:
        db.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, email VARCHAR(160) NOT NULL UNIQUE)"))
        db.execute(text("INSERT INTO users VALUES (34,'Legacy','legacy@example.test')"))
        db.execute(text("CREATE TABLE snapshot_sentinel(id INTEGER PRIMARY KEY, fingerprint TEXT)"))
        db.execute(text("INSERT INTO snapshot_sentinel VALUES (1,'unchanged-v6')"))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert {"auth_sessions", "participant_test_runs"}.issubset(inspect(db).get_table_names())
        assert db.execute(text("SELECT name,email,role,password_hash FROM users")).one() == ("Legacy", "legacy@example.test", "participant", None)
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
            migration.upgrade()
        assert db.execute(text("SELECT fingerprint FROM snapshot_sentinel")).scalar_one() == "unchanged-v6"
        assert db.execute(text("SELECT id FROM users")).scalar_one() == 34
        db.execute(text("UPDATE users SET password_hash='protected-hash' WHERE id=34"))
        with Operations.context(MigrationContext.configure(db)):
            with pytest.raises(RuntimeError, match="preserve participant credentials"):
                migration.downgrade()
        assert "participant_test_runs" in inspect(db).get_table_names()
    engine.dispose()
