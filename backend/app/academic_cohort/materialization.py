"""Explicit atomic import; never seed, upsert operational IDs, or activate Gold."""
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.academic_cohort.contracts import MaterializationPlan, PROFILE_COUNTS, validate_replay
from app.academic_cohort.models import CohortEvaluation, CohortSnapshot, CohortVehicle
from data_platform.catalog.academic_cohort_v6 import VERSION
from data_platform.catalog.profile_pilot_v4 import fingerprint


@dataclass(frozen=True)
class MaterializationReceipt:
    status: str
    snapshot_id: UUID
    cohort_fingerprint: str
    selected_count: int
    evaluation_count: int
    database_modified: bool


def _audit(session: Session, snapshot: CohortSnapshot, plan: MaterializationPlan):
    if (snapshot.selected_count != 60 or snapshot.profile_counts != PROFILE_COUNTS
            or snapshot.method_fingerprint != fingerprint(plan.source_manifest)
            or snapshot.source_manifest != plan.source_manifest or snapshot.inventory_summary != plan.summary
            or snapshot.operationally_active or snapshot.recommended):
        raise ValueError("Stored snapshot differs from the validated replay")
    # Read actual payloads, not only stored checksum columns: detect tampering.
    vehicles = session.scalars(select(CohortVehicle).where(CohortVehicle.snapshot_id == snapshot.snapshot_id)).all()
    evaluations = session.scalars(select(CohortEvaluation).where(CohortEvaluation.snapshot_id == snapshot.snapshot_id)).all()
    expected_vehicles = {r["catalog_id"]: r for r in plan.vehicles}
    expected_evaluations = {(r["catalog_id"], r["profile"], r["scenario"]): r for r in plan.evaluations}
    if len(vehicles) != 60 or len(evaluations) != 1080:
        raise ValueError("Incomplete persisted snapshot")
    for vehicle in vehicles:
        expected = expected_vehicles[vehicle.catalog_id]
        if fingerprint(vehicle.payload) != expected["payload_fingerprint"]:
            raise ValueError("Persisted vehicle evidence changed")
        for field in expected:
            if getattr(vehicle, field) != expected[field]:
                raise ValueError("Persisted vehicle identity changed")
        if vehicle.operationally_active or vehicle.recommended:
            raise ValueError("Operational activation forbidden")
    for evaluation in evaluations:
        expected = expected_evaluations[(evaluation.catalog_id, evaluation.profile, evaluation.scenario)]
        if fingerprint(evaluation.payload) != expected["payload_fingerprint"]:
            raise ValueError("Persisted evaluation changed")
        for field in expected:
            if getattr(evaluation, field) != expected[field]:
                raise ValueError("Persisted evaluation metadata changed")
        if evaluation.operationally_active or evaluation.recommended:
            raise ValueError("Operational activation forbidden")


def _materialize_plan(session: Session, plan: MaterializationPlan) -> MaterializationReceipt:
    """Caller owns the transaction. Also used by complementary in-memory tests."""
    existing = session.scalar(select(CohortSnapshot).where(
        CohortSnapshot.cohort_version == VERSION, CohortSnapshot.cohort_fingerprint == plan.cohort_fingerprint))
    if existing is not None:
        _audit(session, existing, plan)
        return MaterializationReceipt("already_materialized", existing.snapshot_id, plan.cohort_fingerprint, 60, 1080, False)
    snapshot_id = uuid4()
    snapshot = CohortSnapshot(snapshot_id=snapshot_id, cohort_version=VERSION,
                              cohort_fingerprint=plan.cohort_fingerprint,
                              method_fingerprint=fingerprint(plan.source_manifest), source_manifest=plan.source_manifest,
                              inventory_summary=plan.summary, selected_count=60, profile_counts={
                                  p: sum(r["academic_test_ready"] for r in plan.evaluations if r["profile"] == p and r["scenario"] == "base")
                                  for p in ("cidade", "app", "trabalho", "suv", "familia", "estrada")},
                              operationally_active=False, recommended=False)
    session.add(snapshot)
    session.flush()
    session.add_all(CohortVehicle(snapshot_id=snapshot_id, **row, operationally_active=False, recommended=False) for row in plan.vehicles)
    session.flush()
    session.add_all(CohortEvaluation(snapshot_id=snapshot_id, **row, operationally_active=False, recommended=False) for row in plan.evaluations)
    session.flush()
    _audit(session, snapshot, plan)
    return MaterializationReceipt("materialized", snapshot_id, plan.cohort_fingerprint, 60, 1080, True)


def materialize(engine: Engine, replay: dict) -> MaterializationReceipt:
    if engine.dialect.name != "postgresql":
        raise ValueError("Academic materialization requires PostgreSQL; no SQLite fallback")
    # Validate expensive replay/evidence before opening a database transaction.
    plan = validate_replay(replay)
    with Session(engine) as session, session.begin():
        # Serialize concurrent imports of this immutable version/fingerprint.
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                        {"key": int(plan.cohort_fingerprint[:15], 16)})
        return _materialize_plan(session, plan)
