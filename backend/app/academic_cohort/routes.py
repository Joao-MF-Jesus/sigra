import os
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.academic_cohort.repository import AcademicFilters, AcademicRepository
from app.academic_cohort.schemas import AcademicEvaluationRequest, AcademicEvaluationResponse, AcademicMetadata, AcademicVehicleDetail, AcademicVehiclePage, Profile, Scenario
from app.academic_cohort.service import AcademicNotFound, AcademicService, AcademicUnavailable
from app.config import _boolean
from app.database import get_db

router = APIRouter(prefix="/api/v1/academic-cohort", tags=["academic-cohort"])


def academic_mode_enabled():
    if not _boolean(os.getenv("ACADEMIC_COHORT_ENABLED"), default=False, variable_name="ACADEMIC_COHORT_ENABLED"):
        raise HTTPException(404, detail={"code": "academic_mode_disabled"})


def get_academic_service(db: Session = Depends(get_db)):
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(503, detail={"code": "academic_postgresql_required"})
    from app import deployment
    if deployment.enabled():
        try:
            return deployment.service_for_session(db)
        except (ValueError, OSError, SQLAlchemyError):
            raise HTTPException(503, detail={"code": "pinned_deployment_unavailable"}) from None
    from app.academic_cohort.revision6_homologation import enabled, service_for_session
    if enabled():
        try:
            return service_for_session(db)
        except (ValueError, OSError, SQLAlchemyError):
            raise HTTPException(503, detail={"code": "revision6_homologation_unavailable"}) from None
    return AcademicService(AcademicRepository(db))


def invoke(call):
    try:
        return call()
    except AcademicNotFound:
        raise HTTPException(404, detail={"code": "academic_not_found"}) from None
    except (AcademicUnavailable, SQLAlchemyError):
        # Do not expose SQL, parameters, connection URLs or evidence content on failure.
        raise HTTPException(503, detail={"code": "academic_cohort_unavailable"}) from None


@router.get("/metadata", response_model=AcademicMetadata, dependencies=[Depends(academic_mode_enabled)])
def metadata(snapshot_id: UUID | None = None, service: AcademicService = Depends(get_academic_service)):
    return invoke(lambda: service.metadata(snapshot_id))


@router.get("/recommendation-method", dependencies=[Depends(academic_mode_enabled)])
def live_recommendation_method():
    from app.academic_cohort.recommendation import recommendation_method
    return recommendation_method()


@router.get("/vehicles", response_model=AcademicVehiclePage, dependencies=[Depends(academic_mode_enabled)])
def vehicles(profile: Profile | None = None, scenario: Scenario = "base",
             fipe_code: str | None = Query(default=None, pattern=r"^\d{6}-\d$"),
             reference_month: Literal["2026-09", "2026-10"] | None = None,
             max_purchase_price_brl: Decimal | None = Query(default=None, gt=0),
             max_monthly_tco_brl: Decimal | None = Query(default=None, gt=0),
             limit: int = Query(default=20, ge=1, le=60), offset: int = Query(default=0, ge=0),
             snapshot_id: UUID | None = None, service: AcademicService = Depends(get_academic_service)):
    filters = AcademicFilters(profile, scenario, fipe_code, reference_month, max_purchase_price_brl, max_monthly_tco_brl)
    return invoke(lambda: service.vehicles(filters, limit, offset, snapshot_id))


@router.get("/vehicles/{catalog_id}", response_model=AcademicVehicleDetail, dependencies=[Depends(academic_mode_enabled)])
def vehicle(catalog_id: int, snapshot_id: UUID | None = None, service: AcademicService = Depends(get_academic_service)):
    if catalog_id <= 0:
        raise HTTPException(422, detail={"code": "invalid_catalog_id"})
    return invoke(lambda: service.vehicle(catalog_id, snapshot_id))


@router.post("/evaluate", response_model=AcademicEvaluationResponse, dependencies=[Depends(academic_mode_enabled)])
def evaluate(request: AcademicEvaluationRequest, service: AcademicService = Depends(get_academic_service)):
    return invoke(lambda: service.evaluate(request))
