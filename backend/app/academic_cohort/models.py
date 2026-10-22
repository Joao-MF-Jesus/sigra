"""Snapshot-local catalogue keys never reference public.vehicles primary keys."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, JSON, Numeric, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AcademicBase(DeclarativeBase):
    # Separate metadata: the operational SQLite bootstrap must never create this schema.
    pass


DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class CohortSnapshot(AcademicBase):
    __tablename__ = "cohort_snapshot"
    __table_args__ = (
        UniqueConstraint("cohort_version", "cohort_fingerprint", name="uq_academic_cohort_version_fingerprint"),
        CheckConstraint("selected_count = 60", name="ck_academic_snapshot_selected"),
        CheckConstraint("NOT operationally_active AND NOT recommended", name="ck_academic_snapshot_no_activation"),
        {"schema": "academic"},
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    cohort_version: Mapped[str] = mapped_column(String(60), nullable=False)
    cohort_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    method_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    inventory_summary: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_counts: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    operationally_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CohortVehicle(AcademicBase):
    __tablename__ = "cohort_vehicle"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id"], ["academic.cohort_snapshot.snapshot_id"]),
        UniqueConstraint("snapshot_id", "fipe_code", name="uq_academic_vehicle_fipe"),
        UniqueConstraint("snapshot_id", "canonical_identity_key", name="uq_academic_vehicle_identity"),
        CheckConstraint("catalog_id > 0 AND purchase_price_brl > 0", name="ck_academic_vehicle_identity_price"),
        CheckConstraint("reference_month IN ('2026-09', '2026-10')", name="ck_academic_vehicle_reference_month"),
        CheckConstraint("NOT operationally_active AND NOT recommended", name="ck_academic_vehicle_no_activation"),
        {"schema": "academic"},
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    catalog_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fipe_code: Mapped[str] = mapped_column(String(8), nullable=False)
    year_code: Mapped[str] = mapped_column(String(12), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    purchase_price_brl: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    reference_month: Mapped[str] = mapped_column(String(7), nullable=False)
    payload: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operationally_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class CohortEvaluation(AcademicBase):
    __tablename__ = "cohort_evaluation"
    __table_args__ = (
        ForeignKeyConstraint(["snapshot_id", "catalog_id"], ["academic.cohort_vehicle.snapshot_id", "academic.cohort_vehicle.catalog_id"]),
        CheckConstraint("profile IN ('cidade','app','trabalho','suv','familia','estrada')", name="ck_academic_evaluation_profile"),
        CheckConstraint("scenario IN ('low','base','high')", name="ck_academic_evaluation_scenario"),
        CheckConstraint("monthly_tco_brl >= 0 AND (score IS NULL OR score BETWEEN 0 AND 100)", name="ck_academic_evaluation_values"),
        CheckConstraint("NOT operationally_active AND NOT recommended", name="ck_academic_evaluation_no_activation"),
        Index("ix_academic_evaluation_filter", "snapshot_id", "profile", "scenario", "academic_test_ready", "catalog_id"),
        {"schema": "academic"},
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    catalog_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(String(16), primary_key=True)
    scenario: Mapped[str] = mapped_column(String(8), primary_key=True)
    academic_test_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    monthly_tco_brl: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    payload: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operationally_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
