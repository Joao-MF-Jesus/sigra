"""Opt-in real tests ONLY for the NEW dedicated, already prepared Revision6 DB.

No migration, SQLite fallback, table truncation, cleanup or existing-bank reuse.
This suite is not executed when infrastructure is absent; skips are not approval.
"""
from copy import deepcopy
from pathlib import Path
import os
import secrets
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.academic_cohort import revision6_homologation as h
from app.academic_cohort.contracts import APPROVED_FINGERPRINT
from app.academic_cohort.models import CohortSnapshot, CohortVehicle, CohortEvaluation
from app.academic_cohort.safety_revision6 import _read
from data_platform.catalog.profile_pilot_v4 import fingerprint


@pytest.fixture(scope="module")
def target():
    if os.environ.get("SIGRA_REVISION6_POSTGRESQL_TEST_APPROVAL") != h.DATABASE:
        pytest.skip("Dedicated Revision6 PostgreSQL approval/configuration absent; integration NOT validated")
    if not h.enabled() or len(os.environ.get("SIGRA_RESEARCH_PSEUDONYM_KEY", "").encode()) < 32:
        pytest.fail("Explicit inactive homologation and private pseudonym key required")
    configuration = h.require_runtime()
    proof = _read(os.environ["SIGRA_REVISION6_TARGET_PROOF"])
    plan = h.build_plan(os.environ["SIGRA_REVISION6_BUNDLE"], os.environ["SIGRA_REVISION6_DECISION"])
    runtime = create_engine(configuration.runtime_url, echo=False, pool_pre_ping=True)
    try:
        with runtime.connect() as connection:
            h.check_proof(connection, proof)
            h.audit_runtime_permissions(connection)
        yield configuration, proof, plan, runtime
    finally:
        runtime.dispose()


def test_real_coexistence_exact_snapshots_and_coverage(target):
    _, _, plan, engine = target
    with Session(engine) as session:
        snapshots = session.scalars(select(CohortSnapshot)).all()
        assert {row.cohort_fingerprint for row in snapshots} == {APPROVED_FINGERPRINT, plan.proposal.candidate_fingerprint}
        assert len(snapshots) == 2
        for snapshot in snapshots:
            assert session.scalar(select(func.count()).select_from(CohortVehicle).where(
                CohortVehicle.snapshot_id == snapshot.snapshot_id)) == 60
            assert session.scalar(select(func.count()).select_from(CohortEvaluation).where(
                CohortEvaluation.snapshot_id == snapshot.snapshot_id)) == 1080
            assert not snapshot.operationally_active and not snapshot.recommended
        candidate = h.Revision6Service(h.Revision6Repository(session), plan)
        snapshot = candidate._snapshot()
        for scenario in ("low", "base", "high"):
            for profile, expected in plan.proposal.profile_counts.items():
                rows = candidate.repository.evaluations(snapshot.snapshot_id, profile=profile,
                    scenario=scenario, ready_only=True)
                assert len(rows) == expected


def test_real_idempotent_import_preserves_approved(target):
    configuration, proof, plan, runtime = target
    with Session(runtime) as session:
        before = session.scalar(select(CohortSnapshot).where(CohortSnapshot.cohort_fingerprint == APPROVED_FINGERPRINT))
        preserved = fingerprint(before.inventory_summary)
        previous_id = before.snapshot_id
    owner = create_engine(configuration.migration_url, echo=False)
    try:
        receipt = h.materialize(owner, os.environ["SIGRA_REVISION6_BUNDLE"],
            os.environ["SIGRA_REVISION6_DECISION"], configuration, proof)
        assert receipt.status == "already_materialized" and not receipt.database_modified
    finally:
        owner.dispose()
    with Session(runtime) as session:
        after = session.get(CohortSnapshot, previous_id)
        assert after.cohort_fingerprint == APPROVED_FINGERPRINT
        assert fingerprint(after.inventory_summary) == preserved


def test_real_atomic_rollback_in_dedicated_candidate_only(target):
    configuration, proof, plan, _ = target
    owner = create_engine(configuration.migration_url, echo=False)
    try:
        with pytest.raises(RuntimeError, match="intentional transaction probe"):
            with Session(owner) as session, session.begin():
                h.check_proof(session.connection(), proof, writer=True)
                snapshot = h.Revision6Repository(session).snapshot()
                row = session.get(CohortVehicle, (snapshot.snapshot_id, plan.proposal.transport_vehicles[0]["catalog_id"]))
                payload = deepcopy(row.payload)
                payload["label"] = "intentional transaction probe"
                row.payload = payload
                session.flush()
                raise RuntimeError("intentional transaction probe")
        with Session(owner) as session:
            h.audit_snapshot(session, h.Revision6Repository(session).snapshot(), plan)
    finally:
        owner.dispose()


def test_real_accounts_trial_questionnaire_privacy_logout_and_reconnect(target, monkeypatch):
    _, _, plan, engine = target
    from app import main, models
    from app.auth import hash_password
    # Mirror the explicit homologation CLI; the production endpoint stays off by default.
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    csrf = {"X-SIGRA-CSRF": "1"}
    # Secure cookies must be sent over HTTPS by the test client, as in deployment.
    a, b = TestClient(main.app, headers=csrf, base_url="https://testserver"), TestClient(main.app, headers=csrf, base_url="https://testserver")
    password = secrets.token_urlsafe(24)
    email_a, email_b = f"participant-{uuid4().hex}@example.test", f"participant-{uuid4().hex}@example.test"

    def login(client, email):
        registration = {"name": "Participante fictício", "email": email, "password": password}
        assert client.post("/auth/register", json=registration).status_code == 201
        assert client.post("/auth/register", json=registration).status_code == 409
        assert client.post("/auth/login", json={"email": email, "password": "incorrect-fictitious-password"}).status_code == 401
        assert client.post("/auth/login", json={"email": email, "password": password}).status_code == 200

    login(a, email_a)
    login(b, email_b)
    assert a.post("/auth/register", json={"name": "Fictício", "email": f"x-{uuid4().hex}@example.test",
        "password": password, "role": "admin"}).status_code == 422
    assert a.post("/api/v1/study-sessions", json={"scenario_id": "A", "familiarity": "low",
        "priorities": ["safety"], "presentation_acknowledged": True}).status_code == 201
    metadata = a.get("/api/v1/academic-cohort/metadata")
    assert metadata.status_code == 200, metadata.json()
    snapshot = metadata.json()["snapshot_id"]
    parameters = {"budget": 10000000, "monthly_limit": 100000, "use_case": "familia", "monthly_mileage": 1000,
        "fuel_price": 6, "candidate_source": "academic_v6", "academic_options": {"snapshot_id": snapshot}}
    response = a.post("/api/v1/test-runs/recommendation", json=parameters)
    assert response.status_code == 200
    run_id = response.json()["test_run"]["id"]
    assert response.json()["documentary_eligible_count"] == 9
    assert response.json()["cohort_fingerprint"] == plan.proposal.candidate_fingerprint
    assert b.get(f"/api/v1/test-runs/{run_id}").status_code == 404
    answers = {"interface_clarity": 5, "first_vehicle_explanation": 4, "scenario_coherence": 4,
               "influential_criteria": 3, "comment": "Teste fictício de homologação"}
    assert a.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json=answers).status_code == 200
    assert b.patch(f"/api/v1/test-runs/{run_id}/questionnaire", json=answers).status_code == 404
    saved = a.get(f"/api/v1/test-runs/{run_id}").json()
    # The server stores the validated request including its explicit defaults,
    # not a lossy copy of the raw client's partial JSON object.
    assert saved["parameters"] == main.RecommendationRequest.model_validate(parameters).model_dump(mode="json")
    assert saved["snapshot_fingerprint"] == plan.proposal.candidate_fingerprint
    assert saved["presented_results"]["real_collection_enabled"] is False
    assert saved["questionnaire"]["comment"] == answers["comment"]
    assert a.get("/api/v1/admin/test-runs.csv").status_code == 403
    # A trusted operator test provisions an isolated fictitious admin, never via registration.
    admin_email = f"admin-{uuid4().hex}@example.test"
    with Session(engine) as session:
        session.add(models.User(name="Administrador fictício", email=admin_email, normalized_email=admin_email,
            password_hash=hash_password(password), role="admin"))
        session.commit()
    admin = TestClient(main.app, headers=csrf, base_url="https://testserver")
    assert admin.post("/auth/login", json={"email": admin_email, "password": password}).status_code == 200
    export = admin.get("/api/v1/admin/test-runs.csv")
    assert export.status_code == 200 and "participant_code" in export.text
    assert email_a not in export.text and email_b not in export.text and "auth_session_digest" not in export.text
    engine.dispose()  # PostgreSQL reconnection; explicitly NOT a real API process restart.
    with Session(engine) as session:
        record = session.get(models.ParticipantTestRun, run_id)
        assert record.snapshot_fingerprint == plan.proposal.candidate_fingerprint
        assert record.presented_results["documentary_eligible_count"] == 9
    assert a.post("/auth/logout").status_code == 204
    assert a.get(f"/api/v1/test-runs/{run_id}").status_code == 401
