"""Bound, snapshot-scoped reads. No lower-layer ingestion or operational writes."""
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.academic_cohort.contracts import APPROVED_FINGERPRINT
from app.academic_cohort.models import CohortEvaluation, CohortSnapshot, CohortVehicle
from data_platform.catalog.academic_cohort_v6 import VERSION


@dataclass(frozen=True)
class AcademicFilters:
    profile: str | None = None
    scenario: str = "base"
    fipe_code: str | None = None
    reference_month: str | None = None
    max_purchase_price_brl: Decimal | None = None
    max_monthly_tco_brl: Decimal | None = None


class AcademicRepository:
    def __init__(self, session: Session):
        self.session = session

    def snapshot(self, snapshot_id: UUID | None = None):
        query = select(CohortSnapshot).where(CohortSnapshot.cohort_version == VERSION,
                                            CohortSnapshot.cohort_fingerprint == APPROVED_FINGERPRINT)
        if snapshot_id is not None:
            query = query.where(CohortSnapshot.snapshot_id == snapshot_id)
        return self.session.scalar(query.order_by(CohortSnapshot.created_at.desc(), CohortSnapshot.snapshot_id).limit(1))

    def _query(self, snapshot_id, filters):
        query = select(CohortVehicle).where(CohortVehicle.snapshot_id == snapshot_id)
        if filters.fipe_code is not None:
            query = query.where(CohortVehicle.fipe_code == filters.fipe_code)
        if filters.reference_month is not None:
            query = query.where(CohortVehicle.reference_month == filters.reference_month)
        if filters.max_purchase_price_brl is not None:
            query = query.where(CohortVehicle.purchase_price_brl <= filters.max_purchase_price_brl)
        if filters.profile is not None or filters.max_monthly_tco_brl is not None:
            # One profile/scenario row per vehicle, so this join cannot multiply the page.
            profile = filters.profile or "app"
            query = query.join(CohortEvaluation, (CohortVehicle.snapshot_id == CohortEvaluation.snapshot_id)
                               & (CohortVehicle.catalog_id == CohortEvaluation.catalog_id))
            query = query.where(CohortEvaluation.profile == profile, CohortEvaluation.scenario == filters.scenario,
                                CohortEvaluation.academic_test_ready.is_(True))
            if filters.max_monthly_tco_brl is not None:
                query = query.where(CohortEvaluation.monthly_tco_brl <= filters.max_monthly_tco_brl)
        return query

    def vehicles(self, snapshot_id, filters, limit, offset):
        query = self._query(snapshot_id, filters)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.scalars(query.order_by(CohortVehicle.catalog_id).limit(limit).offset(offset)).all()
        return rows, total

    def vehicle(self, snapshot_id, catalog_id):
        return self.session.get(CohortVehicle, (snapshot_id, catalog_id))

    def evaluations(self, snapshot_id, *, profile=None, scenario=None, catalog_ids=None, ready_only=False):
        query = select(CohortEvaluation).where(CohortEvaluation.snapshot_id == snapshot_id)
        if profile is not None:
            query = query.where(CohortEvaluation.profile == profile)
        if scenario is not None:
            query = query.where(CohortEvaluation.scenario == scenario)
        if catalog_ids is not None:
            query = query.where(CohortEvaluation.catalog_id.in_(catalog_ids))
        if ready_only:
            query = query.where(CohortEvaluation.academic_test_ready.is_(True))
        return self.session.scalars(query.order_by(CohortEvaluation.catalog_id, CohortEvaluation.scenario, CohortEvaluation.profile)).all()
