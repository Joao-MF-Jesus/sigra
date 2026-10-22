"""SQL-shaped memory doubles, not SQLite/PostgreSQL integration evidence."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.academic_cohort import revision6_homologation as h
from app.academic_cohort.contracts import APPROVED_FINGERPRINT, PROFILE_COUNTS, validate_replay
from app.academic_cohort.models import CohortSnapshot, CohortVehicle, CohortEvaluation
from app.academic_cohort.repository import AcademicFilters, AcademicRepository
from app.academic_cohort.schemas import AcademicEvaluationRequest
from app.academic_cohort.service import AcademicService, AcademicUnavailable
from app.academic_cohort.recommendation import recommend_academic
from app.academic_cohort.routes import get_academic_service
from data_platform.catalog.profile_pilot_v4 import fingerprint


def configuration():
    # Deliberately fictitious credentials in a test double; never connect.
    return {"DATABASE_ENV": "integration", "SIGRA_REVISION6_CONFIRM_DATABASE": h.DATABASE,
        "SIGRA_REVISION6_PARTICIPANTS": "fictitious_only", "SIGRA_TCC_COLLECTION_MODE": "homologation",
        "SIGRA_REVISION6_MIGRATION_URL": f"postgresql+psycopg://{h.OWNER}:dummy@127.0.0.1:1/{h.DATABASE}",
        "SIGRA_REVISION6_RUNTIME_URL": f"postgresql+psycopg://{h.RUNTIME}:dummy@127.0.0.1:1/{h.DATABASE}",
        "DATABASE_URL": f"postgresql+psycopg://{h.RUNTIME}:dummy@127.0.0.1:1/{h.DATABASE}"}


@pytest.fixture(scope="module")
def plan():
    return h.build_plan(os.environ["SIGRA_REVISION6_BUNDLE"], os.environ["SIGRA_REVISION6_DECISION"])


class MemorySession:
    """Just SQLAlchemy row objects; no engine, connection, persistence or driver."""
    def __init__(self):
        self.rows = {CohortSnapshot: [], CohortVehicle: [], CohortEvaluation: []}
        target = h.target_configuration(configuration())
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), url=target.runtime_url)

    def get_bind(self):
        return self.bind

    def add(self, row):
        if isinstance(row, CohortSnapshot):
            row.created_at = datetime.now(timezone.utc)
        self.rows[type(row)].append(row)

    def add_all(self, rows):
        for row in rows:
            self.add(row)

    def flush(self):
        pass

    def filtered(self, query):
        model = query.column_descriptions[0]["entity"]
        rows = self.rows[model]
        for key, value in query.compile().params.items():
            name = key.rsplit("_", 1)[0]
            if name in {"snapshot_id", "cohort_version", "cohort_fingerprint"}:
                rows = [row for row in rows if getattr(row, name) == value]
        return rows

    def scalar(self, query):
        rows = self.filtered(query)
        return rows[0] if rows else None

    def scalars(self, query):
        return SimpleNamespace(all=lambda: self.filtered(query))


class MemoryRepository(h.Revision6Repository):
    def vehicles(self, snapshot_id, filters, limit, offset):
        rows = [row for row in self.session.rows[CohortVehicle] if row.snapshot_id == snapshot_id]
        if filters.profile:
            ids = {row.catalog_id for row in self.evaluations(snapshot_id, profile=filters.profile,
                scenario=filters.scenario, ready_only=True)}
            rows = [row for row in rows if row.catalog_id in ids]
        if filters.max_purchase_price_brl is not None:
            rows = [row for row in rows if row.purchase_price_brl <= filters.max_purchase_price_brl]
        if filters.max_monthly_tco_brl is not None:
            eligible = {row.catalog_id for row in self.evaluations(snapshot_id, profile=filters.profile or "app",
                scenario=filters.scenario, ready_only=True) if row.monthly_tco_brl <= filters.max_monthly_tco_brl}
            rows = [row for row in rows if row.catalog_id in eligible]
        rows.sort(key=lambda row: row.catalog_id)
        return rows[offset:offset+limit], len(rows)

    def vehicle(self, snapshot_id, catalog_id):
        return next((row for row in self.session.rows[CohortVehicle]
                     if row.snapshot_id == snapshot_id and row.catalog_id == catalog_id), None)

    def evaluations(self, snapshot_id, *, profile=None, scenario=None, catalog_ids=None, ready_only=False):
        return [row for row in self.session.rows[CohortEvaluation] if row.snapshot_id == snapshot_id
                and (profile is None or row.profile == profile) and (scenario is None or row.scenario == scenario)
                and (catalog_ids is None or row.catalog_id in catalog_ids) and (not ready_only or row.academic_test_ready)]


@pytest.fixture
def service(plan):
    session = MemorySession()
    h._materialize_plan(session, plan)
    return h.Revision6Service(MemoryRepository(session), plan)


def test_default_remains_approved_v6(monkeypatch):
    monkeypatch.delenv("SIGRA_REVISION6_HOMOLOGATION_ENABLED", raising=False)
    service = get_academic_service(MemorySession())
    assert type(service) is AcademicService
    assert service.profile_counts == PROFILE_COUNTS and service.profile_counts["familia"] == 1
    assert not h.enabled({})


@pytest.mark.parametrize("field,value", [
    ("DATABASE_ENV", "production"), ("SIGRA_REVISION6_CONFIRM_DATABASE", "sigra_postgresql_demo"),
    ("SIGRA_REVISION6_PARTICIPANTS", "real"), ("SIGRA_TCC_COLLECTION_MODE", "real"),
    ("SIGRA_REVISION6_MIGRATION_URL", ""), ("SIGRA_REVISION6_RUNTIME_URL", ""),
    ("SIGRA_REVISION6_RUNTIME_URL", "sqlite:///should-never-open.db"),
    ("SIGRA_REVISION6_RUNTIME_URL", "postgresql://other:dummy@127.0.0.1:1/sigra_postgresql_demo"),
    ("SIGRA_REVISION6_RUNTIME_URL", f"postgresql://{h.RUNTIME}:dummy@remote.test:1/{h.DATABASE}"),
])
def test_target_rejects_missing_existing_remote_or_real(field, value):
    values = configuration()
    values[field] = value
    with pytest.raises(ValueError):
        h.target_configuration(values)


def test_exact_bind_and_credentials_not_rendered():
    target = h.target_configuration(configuration())
    target.check_bind(MemorySession().bind)
    assert "dummy" not in repr(target)
    wrong = MemorySession().bind
    wrong.url = target.runtime_url.set(password="different-dummy")
    with pytest.raises(ValueError):
        target.check_bind(wrong)


def test_runtime_rejects_a_different_database():
    values = configuration()
    values["DATABASE_URL"] = "postgresql://unknown:dummy@127.0.0.1:1/sigra_postgresql_demo"
    with pytest.raises(ValueError):
        h.require_runtime(values)


def test_enabled_without_configuration_never_connects(monkeypatch):
    monkeypatch.setenv("SIGRA_REVISION6_HOMOLOGATION_ENABLED", "true")
    for name in configuration():
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as error:
        get_academic_service(MemorySession())
    assert error.value.status_code == 503


def test_distinct_version_and_trust_anchor(plan):
    assert plan.proposal.candidate_fingerprint != APPROVED_FINGERPRINT
    assert validate_replay(plan.approved_replay).cohort_fingerprint == APPROVED_FINGERPRINT
    with pytest.raises(ValueError):
        validate_replay(plan.replay)


def test_two_imports_are_idempotent_in_memory(plan):
    session = MemorySession()
    first = h._materialize_plan(session, plan)
    second = h._materialize_plan(session, plan)
    assert first.snapshot_id == second.snapshot_id
    assert first.database_modified and not second.database_modified
    assert len(session.rows[CohortSnapshot]) == 1
    assert len(session.rows[CohortVehicle]) == 60 and len(session.rows[CohortEvaluation]) == 1080


def test_approved_snapshot_is_never_modified(plan):
    session = MemorySession()
    previous = CohortSnapshot(snapshot_id=uuid4(), cohort_version="academic-cohort-v6",
                             cohort_fingerprint=APPROVED_FINGERPRINT, inventory_summary={"untouched": True})
    session.add(previous)
    h._materialize_plan(session, plan)
    assert previous.inventory_summary == {"untouched": True}
    assert previous.cohort_fingerprint == APPROVED_FINGERPRINT
    assert len(session.rows[CohortSnapshot]) == 2


@pytest.mark.parametrize("scenario", ["low", "base", "high"])
@pytest.mark.parametrize("profile,count", [("cidade", 10), ("app", 60), ("trabalho", 10), ("suv", 24), ("familia", 9), ("estrada", 9)])
def test_all_six_profiles_three_scenarios(service, profile, count, scenario):
    response = service.evaluate(AcademicEvaluationRequest(profile=profile, scenario=scenario, limit=60))
    assert response["eligible_count"] == count
    assert len(set(response["eligible_ids"])) == count
    if profile in {"familia", "estrada"}:
        assert sorted(response["eligible_ids"]) == [31, 34, 44, 55, 62, 76, 80, 108, 124]


def test_unknowns_cruze_units_and_fiesta_absence(service):
    for identifier in (70, 102, 123):
        fields = service.vehicle(identifier)["evidence"]["fields"]
        assert fields["airbags"]["value"] is None
    fields = service.vehicle(46)["evidence"]["fields"]
    assert Decimal(fields["width_mm"]["value"]) == 1807
    assert Decimal(fields["width_with_mirrors_mm"]["value"]) == 2042
    assert service.vehicle(44)["evidence"]["fields"]["esc"]["value"] is False


@pytest.mark.parametrize("model,field,value", [
    (CohortVehicle, "fipe_code", "000000-0"),
    (CohortVehicle, "payload_fingerprint", "a" * 64),
    (CohortEvaluation, "academic_test_ready", False),
    (CohortSnapshot, "operationally_active", True),
])
def test_persisted_metadata_tamper_is_rejected(service, model, field, value):
    row = service.repository.session.rows[model][0]
    if getattr(row, field) == value:
        value = not value if isinstance(value, bool) else "tampered"
    setattr(row, field, value)
    with pytest.raises(AcademicUnavailable):
        service.metadata()


def test_nested_evidence_tamper_is_rejected(service):
    row = service.repository.session.rows[CohortVehicle][0]
    row.payload["fields"]["price_brl"]["value"] = "1"
    # Even updating the checksum column must not turn edited data into trusted evidence.
    row.payload_fingerprint = fingerprint(row.payload)
    with pytest.raises(AcademicUnavailable):
        service.metadata()


def test_missing_evaluation_is_rejected(service):
    service.repository.session.rows[CohortEvaluation].pop()
    with pytest.raises(AcademicUnavailable):
        service.metadata()


def test_duplicate_transport_is_rejected(plan):
    proposal = replace(plan.proposal, transport_vehicles=plan.proposal.transport_vehicles[:-1] + (plan.proposal.transport_vehicles[0],))
    with pytest.raises(ValueError):
        h.validate_plan(replace(plan, proposal=proposal))


def test_plan_nested_payload_is_not_implicitly_trusted(plan):
    proposal = replace(plan.proposal, transport_vehicles=deepcopy(plan.proposal.transport_vehicles))
    proposal.transport_vehicles[0]["label"] = "forged identity"
    with pytest.raises(ValueError):
        h.validate_plan(replace(plan, proposal=proposal))


def test_sql_reads_pin_both_fingerprint_and_version():
    session = MemorySession()
    seen = []
    session.scalar = lambda query: seen.append(query.compile().params)
    h.Revision6Repository(session).snapshot()
    assert seen[0]["cohort_fingerprint_1"] == preparation_policy()["candidate_fingerprint"]
    assert seen[0]["cohort_version_1"] == preparation_policy()["candidate_version"]
    AcademicRepository(session).snapshot()
    assert seen[1]["cohort_fingerprint_1"] == APPROVED_FINGERPRINT


def preparation_policy():
    return h.preparation._read(h.preparation.CONTRACT)


def test_no_operational_ids_flags_or_default_replacement(service):
    from app import main
    request = main.RecommendationRequest.model_validate({"budget": 10000000, "monthly_limit": 100000,
        "use_case": "familia", "monthly_mileage": 1000, "fuel_price": 6, "candidate_source": "academic_v6",
        "academic_options": {"snapshot_id": str(service.repository.snapshot(None).snapshot_id)}})
    result = recommend_academic(service, request)
    assert result["considered_count"] == 60 and result["documentary_eligible_count"] == 9
    assert result["eligible_count"] == 9 and not result["stored_scores_used"]
    assert result["homologation_candidate"] == "safety_revision6"
    assert result["real_collection_enabled"] is result["candidate_approved"] is result["default_snapshot_replaced"] is False
    assert not result["operationally_active"] and not result["recommended"]
    assert all(row["vehicle"]["operational_vehicle_id"] is None for row in result["recommendations"])


def test_http_metadata_detail_evaluation_and_live_recommendation(service, monkeypatch):
    from app import main
    monkeypatch.setenv("ACADEMIC_COHORT_ENABLED", "true")
    main.app.dependency_overrides[get_academic_service] = lambda: service
    main.app.dependency_overrides[main.get_db] = lambda: object()
    monkeypatch.setattr(main, "get_academic_service", lambda _: service)
    try:
        client = TestClient(main.app)  # No lifespan, network socket or real DB.
        metadata = client.get("/api/v1/academic-cohort/metadata")
        assert metadata.status_code == 200 and metadata.json()["profile_counts"]["familia"] == 9
        assert client.get("/api/v1/academic-cohort/vehicles?limit=60").json()["total"] == 60
        assert client.get("/api/v1/academic-cohort/vehicles/70").json()["evidence"]["fields"]["airbags"]["value"] is None
        evaluation = client.post("/api/v1/academic-cohort/evaluate", json={"profile": "estrada", "limit": 60})
        assert evaluation.status_code == 200 and evaluation.json()["eligible_count"] == 9
        snapshot_id = metadata.json()["snapshot_id"]
        payload = {"budget": 10000000, "monthly_limit": 100000, "use_case": "app",
            "monthly_mileage": 1000, "fuel_price": 6, "candidate_source": "academic_v6",
            "academic_options": {"snapshot_id": snapshot_id}}
        first = client.post("/recommendations?envelope=true", json=payload)
        assert first.status_code == 200 and first.json()["eligible_count"] == 60
        payload.update(monthly_mileage=2000, fuel_price=9)
        second = client.post("/recommendations?envelope=true", json=payload)
        assert second.status_code == 200
        costs_a = {row["vehicle"]["catalog_id"]: Decimal(row["monthly_total_cost"]) for row in first.json()["recommendations"]}
        costs_b = {row["vehicle"]["catalog_id"]: Decimal(row["monthly_total_cost"]) for row in second.json()["recommendations"]}
        assert set(costs_a) == set(costs_b) and all(costs_b[key] > costs_a[key] for key in costs_a)
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("email,allowed", [("person@example.com", False), ("fiction@example.test", True), ("fiction@example.invalid", True)])
def test_only_fictitious_accounts_when_candidate_enabled(monkeypatch, email, allowed):
    from app.auth import require_homologation_account
    for key, value in configuration().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SIGRA_REVISION6_HOMOLOGATION_ENABLED", "true")
    if allowed:
        require_homologation_account(email)
    else:
        with pytest.raises(HTTPException) as error:
            require_homologation_account(email)
        assert error.value.status_code == 403


def test_real_collection_cannot_be_enabled(monkeypatch):
    from app.study_protocol import collection_mode
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "real")
    with pytest.raises(HTTPException) as error:
        collection_mode()
    assert error.value.status_code == 503


def test_logout_validates_destination_before_any_db_read(monkeypatch):
    from app.auth import logout
    from starlette.requests import Request
    from starlette.responses import Response
    monkeypatch.setenv("SIGRA_REVISION6_HOMOLOGATION_ENABLED", "true")
    monkeypatch.delenv("SIGRA_REVISION6_CONFIRM_DATABASE", raising=False)
    with pytest.raises(HTTPException) as error:
        logout(Request({"type": "http", "method": "POST", "headers": []}), Response(), object())
    assert error.value.status_code == 503


def test_startup_rejects_unconfirmed_target_before_any_connection(monkeypatch):
    from app import main
    monkeypatch.setenv("SIGRA_REVISION6_HOMOLOGATION_ENABLED", "true")
    monkeypatch.delenv("SIGRA_REVISION6_CONFIRM_DATABASE", raising=False)
    monkeypatch.setattr(main, "check_database_connection", lambda: pytest.fail("No database access allowed"))
    generator = main.lifespan.__wrapped__(main.app)
    with pytest.raises(ValueError):
        generator.__anext__().send(None)


class ScriptedConnection:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append((str(query), parameters))
        value = next(self.results)
        return SimpleNamespace(one=lambda: value, one_or_none=lambda: value,
                               scalar_one=lambda: value, all=lambda: value,
                               scalars=lambda: SimpleNamespace(all=lambda: value))


def test_nonempty_target_blocks_before_ddl():
    connection = ScriptedConnection([(h.DATABASE, h.OWNER), (False, False, False, False), 123, [("public", "users")]])
    with pytest.raises(ValueError):
        h.require_empty_target(connection)
    assert not any(sql.startswith(("CREATE", "ALTER", "INSERT")) for sql, _ in connection.calls)


def test_empty_target_produces_nonsecret_proof():
    connection = ScriptedConnection([(h.DATABASE, h.OWNER), (False, False, False, False), 123, []])
    proof = h.require_empty_target(connection)
    assert proof == {"database": h.DATABASE, "database_oid": 123, "initially_empty": True, "alembic_head": h.ALEMBIC_HEAD}


def test_wrong_role_or_privilege_blocks_identity():
    for results in [[("sigra_postgresql_demo", h.OWNER)], [(h.DATABASE, h.OWNER), (True, False, False, False)]]:
        with pytest.raises(ValueError):
            h.require_database_identity(ScriptedConnection(results), writer=True)


def test_reused_database_oid_or_boolean_proof_is_rejected():
    expected = {"database": h.DATABASE, "database_oid": 123, "initially_empty": True, "alembic_head": h.ALEMBIC_HEAD}
    for field, value in [("database_oid", 999), ("initially_empty", 1)]:
        proof = {**expected, field: value}
        connection = ScriptedConnection([(h.DATABASE, h.RUNTIME), (False, False, False, False), 123])
        with pytest.raises(ValueError):
            h.check_proof(connection, proof)


def test_wrong_alembic_head_is_rejected():
    proof = {"database": h.DATABASE, "database_oid": 123, "initially_empty": True, "alembic_head": h.ALEMBIC_HEAD}
    connection = ScriptedConnection([(h.DATABASE, h.RUNTIME), (False, False, False, False), 123, ["20260811_0012"]])
    with pytest.raises(ValueError):
        h.check_proof(connection, proof)


def test_runtime_write_privilege_is_rejected():
    connection = ScriptedConnection([(h.DATABASE, h.RUNTIME), (False, False, False, False), 123, True, True])
    with pytest.raises(ValueError):
        h.audit_runtime_permissions(connection)


@pytest.mark.parametrize("failure", ["rls", "policy", "public_grant", "membership", "owner", "schema_create"])
def test_runtime_permission_audit_is_fail_closed(failure):
    results = [(h.DATABASE, h.RUNTIME), (False, False, False, False), 123]
    for _ in range(3):
        results.extend([True, *[False] * 6])
    for index, _ in enumerate(h.PRIVATE_TABLES):
        results.extend([
            (False, False) if failure == "rls" and index == 0 else (True, True),
            [("unexpected_public_policy", False, "*")] if failure == "policy" and index == 0 else [("revision6_trusted_backend", True, "*")],
            1 if failure == "public_grant" and index == 0 else 0,
        ])
    results.extend([int(failure == "membership"), int(failure == "owner"), failure == "schema_create"])
    with pytest.raises(ValueError):
        h.audit_runtime_permissions(ScriptedConnection(results))


def test_prepare_function_preserves_proof_and_never_opens_engine(tmp_path, plan, monkeypatch):
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "scripts/homologate_safety_revision6.py"
    spec = importlib.util.spec_from_file_location("homologate_safety_revision6", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proof = tmp_path / "existing-proof.json"
    proof.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(module, "create_engine", lambda *args, **kwargs: pytest.fail("No connection allowed"))
    with pytest.raises(ValueError):
        module.prepare_new_database(h.target_configuration(configuration()), plan, proof)
    assert proof.read_text(encoding="utf-8") == "preserve"
