"""Appendix C/D regression tests. SQLite unit checks are NOT PostgreSQL approval."""
import csv
import io
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app import main, models
from app.study_protocol import QUESTIONS
from backend.tests.test_participant_trials import storage, client, register_and_login, FINANCING, migration_module

BEFORE = {"scenario_id": "A", "familiarity": "low", "priorities": ["total_cost", "efficiency"], "presentation_acknowledged": True}
ANSWERS = dict(zip(QUESTIONS, (5, 4, 3, 2)), comment="Fictício; faltaram explicações")


@pytest.fixture
def enabled(storage, monkeypatch):
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "homologation")
    return storage


def start(http):
    register_and_login(http)
    response = http.post("/api/v1/study-sessions", json=BEFORE)
    assert response.status_code == 201, response.text
    return response.json()


def test_metadata_homologation_is_not_real_consent(enabled):
    result = client().get("/api/v1/study-sessions/metadata").json()
    assert result["mode"] == "homologation" and result["real_collection_enabled"] is False
    assert set(result["questions"]) == set(QUESTIONS)
    assert result["scenarios"] == list("ABCDE")
    assert "consentimento" in " ".join(result["limitations"])


def test_before_ranking_is_required_no_calculation_or_record(enabled):
    http = client()
    register_and_login(http)
    assert http.post("/api/v1/test-runs/financing", json=FINANCING).status_code == 409
    with Session(enabled) as db:
        assert db.query(models.ParticipantTestRun).count() == 0
    assert http.get("/api/v1/study-sessions/current").json() == {"session": None}


@pytest.mark.parametrize("change", [{"scenario_id": "F"}, {"familiarity": "expert"},
    {"priorities": ["safety"] * 2}, {"priorities": list(QUESTIONS)}, {"priorities": ["invented"]},
    {"presentation_acknowledged": False}, {"user_id": 1}, {"auth_session_digest": "invented"}])
def test_invalid_or_spoofed_context(enabled, change):
    http = client()
    register_and_login(http)
    assert http.post("/api/v1/study-sessions", json={**BEFORE, **change}).status_code == 422
    with Session(enabled) as db:
        assert db.query(models.ParticipantStudySession).count() == 0


def test_four_questions_linked_to_server_result_and_pseudonymous_export(enabled):
    http = client()
    context = start(http)
    result = http.post("/api/v1/test-runs/financing", json=FINANCING).json()
    run_id = result["test_run"]["id"]
    assert result["test_run"]["questionnaire_required"] is True
    saved = http.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json=ANSWERS)
    assert saved.status_code == 200, saved.text
    detail = http.get(f"/api/v1/test-runs/{run_id}").json()
    assert detail["study_session"]["id"] == context["id"]
    assert all(detail["questionnaire"][k] == ANSWERS[k] for k in QUESTIONS)
    assert detail["technical_record"]["status"] == "succeeded"
    assert detail["technical_record"]["duration_ms"] >= 0
    assert detail["technical_record"]["environment_tag"] == "homologation_synthetic"
    assert detail["technical_record"]["analysis_ready"] is False  # No invented financing dataset/weights.
    assert detail["study_session"]["created_at"] <= detail["created_at"] <= detail["questionnaire"]["answered_at"]
    assert all(detail["parameters"][k] == v for k, v in FINANCING.items())
    assert detail["technical_record"]["active_parameters"] == detail["parameters"]
    assert http.patch(f"/api/v1/test-runs/{run_id}/feedback", json={"rating": 4}).status_code == 409
    with Session(enabled) as db:
        db.query(models.User).one().role = "admin"
        db.commit()
    exported = http.get("/api/v1/admin/test-runs.csv").text
    row = next(csv.DictReader(io.StringIO(exported.lstrip("\ufeff"))))
    assert row["participant_code"].startswith("P-")
    assert row["scenario_id"] == "A" and row["familiarity"] == "low"
    assert [row[k] for k in QUESTIONS] == ["5", "4", "3", "2"]
    assert "participant@example.test" not in exported and "auth_session_digest" not in exported
    assert http.post("/auth/logout", json={}).status_code == 204
    assert http.get(f"/api/v1/test-runs/{run_id}").status_code == 401


@pytest.mark.parametrize("change", [{"interface_clarity": 0}, {"scenario_coherence": 6},
    {"influential_criteria": True}, {"first_vehicle_explanation": "4"}, {"user_id": 2}, {"rating": 4}])
def test_questionnaire_validation(enabled, change):
    http = client()
    start(http)
    run_id = http.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    assert http.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json={**ANSWERS, **change}).status_code == 422


def test_ownership_login_session_boundary_and_immutable_context(enabled):
    first, second = client(), client()
    original = start(first)
    run_id = first.post("/api/v1/test-runs/financing", json=FINANCING).json()["test_run"]["id"]
    register_and_login(second, "other@example.test")
    assert second.get("/api/v1/study-sessions/current").json()["session"] is None
    assert second.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json=ANSWERS).status_code == 404
    newer = first.post("/api/v1/study-sessions", json={**BEFORE, "scenario_id": "B"}).json()
    assert newer["id"] != original["id"]
    assert first.get(f"/api/v1/test-runs/{run_id}").json()["study_session"]["scenario_id"] == "A"
    first.post("/auth/logout", json={})
    from backend.tests.test_participant_trials import PASSWORD
    first.post("/auth/login", json={"email": "participant@example.test", "password": PASSWORD})
    assert first.get("/api/v1/study-sessions/current").json()["session"] is None


def test_real_collection_blocked_and_missing_key_blocks_context(enabled, monkeypatch):
    http = client()
    register_and_login(http)
    monkeypatch.delenv("SIGRA_RESEARCH_PSEUDONYM_KEY")
    assert http.post("/api/v1/study-sessions", json=BEFORE).status_code == 503
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "real")
    assert http.get("/api/v1/study-sessions/metadata").status_code == 503


def test_one_hundred_synthetic_records_and_owner_pagination(enabled):
    http = client()
    start(http)
    identifiers = set()
    for _ in range(100):
        response = http.post("/api/v1/test-runs/financing", json=FINANCING)
        assert response.status_code == 200
        identifiers.add(response.json()["test_run"]["id"])
    assert len(identifiers) == 100
    page = http.get("/api/v1/test-runs?limit=100").json()
    assert page["total"] == 100 and {v["id"] for v in page["items"]} == identifiers
    assert http.get("/api/v1/test-runs?limit=20&offset=100").json()["items"] == []


def test_appendix_d_indexes_real_motor_output_without_changing_parameters(enabled, monkeypatch):
    from backend.tests.test_academic_recommendation import MemoryRepository, request
    from app.academic_cohort.service import AcademicService
    service = AcademicService(MemoryRepository())
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    monkeypatch.setattr(main, "get_academic_service", lambda _: service)
    # Synthetic schema revision for unit validation only, never a PG result.
    with enabled.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES('20261007_0015')"))
    http = client()
    start(http)
    payload = request(service).model_dump(mode="json")
    response = http.post("/api/v1/test-runs/recommendation", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    run_id = result.pop("test_run")["id"]
    detail = http.get(f"/api/v1/test-runs/{run_id}").json()
    technical = detail["technical_record"]
    assert result["considered_count"] == 60 and result["stored_scores_used"] is False
    assert detail["presented_results"] == result and detail["parameters"] == payload
    assert technical["analysis_ready"] is True and technical["active_parameters"] == payload
    assert technical["eligible_count"] == result["eligible_count"]
    assert technical["eligible_vehicle_ids"] == [v["vehicle"]["catalog_id"] for v in result["recommendations"]]
    assert technical["algorithm_version"] == result["algorithm_version"]
    assert technical["weights_version"] == result["weights_version"]
    assert technical["source_references"]["cohort_fingerprint"] == result["cohort_fingerprint"]
    assert technical["execution_id"] == run_id and technical["participant_code"].startswith("P-")
    assert technical["exclusion_reasons"] == result["excluded"]


def test_failed_execution_is_logged_only_with_protocol_and_no_exception_details(enabled, monkeypatch):
    http = client()
    start(http)
    from app import participant_trials
    from fastapi import HTTPException
    def unavailable(*_):
        raise HTTPException(422, "synthetic-secret-must-not-be-stored")
    monkeypatch.setattr(participant_trials, "financing_simulation", unavailable)
    response = http.post("/api/v1/test-runs/financing", json=FINANCING)
    assert response.status_code == 422
    detail = http.get("/api/v1/test-runs").json()["items"][0]
    assert detail["technical_record"]["status"] == "failed"
    assert detail["technical_record"]["error_code"] == "HTTP_422"
    assert detail["technical_record"]["analysis_ready"] is False
    assert "synthetic-secret" not in str(detail)


def test_instrument_migration_cycle_preserves_legacy_and_blocks_populated_downgrade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'instrument_test.sqlite'}")
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261007_0015_tcc_study_instrument.py"
    spec = importlib.util.spec_from_file_location("instrument_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,email TEXT UNIQUE)"))
        connection.execute(text("INSERT INTO users VALUES(34,'Legacy','legacy@example.test')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration_module().upgrade()
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        assert "participant_questionnaires" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT id,name FROM users")).one() == (34, "Legacy")
        connection.execute(text("INSERT INTO auth_sessions VALUES('digest',34,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL)"))
        connection.execute(text("""INSERT INTO participant_study_sessions
            VALUES('study',34,'digest','A','low','[]','protocol','presentation','homologation_synthetic',CURRENT_TIMESTAMP)"""))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="preserve Appendix"):
                migration.downgrade()
        assert connection.execute(text("SELECT count(*) FROM participant_study_sessions")).scalar_one() == 1
    engine.dispose()
