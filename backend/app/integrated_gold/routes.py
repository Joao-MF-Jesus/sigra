from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrated_gold.repository import IntegratedGoldFilters
from app.integrated_gold.schemas import (
    IntegratedCostPage,
    IntegratedDatasetMetadata,
    IntegratedVehicleDetail,
)
from app.integrated_gold.service import (
    IntegratedGoldService,
    IntegratedGoldUnavailableError,
    IntegratedVehicleNotFoundError,
    service_for_session,
)
from app.integrated_gold.simulation_schemas import (
    VehicleCostSimulationRequest,
    VehicleCostSimulationResponse,
)
from app.integrated_gold.simulation_service import (
    VehicleCostSimulationConflictError,
    VehicleCostSimulationService,
    VehicleCostSimulationUnavailableError,
    simulation_service_for_session,
)


router = APIRouter(
    prefix="/api/v1/integrated-vehicle-cost",
    tags=["integrated-vehicle-cost"],
)


def get_integrated_gold_service(
    db: Session = Depends(get_db),
) -> IntegratedGoldService:
    return service_for_session(db)


def get_vehicle_cost_simulation_service(
    db: Session = Depends(get_db),
) -> VehicleCostSimulationService:
    return simulation_service_for_session(db)


def _unavailable(exc: IntegratedGoldUnavailableError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "integrated_gold_unavailable",
            "message": str(exc),
        },
    )


def _simulation_unavailable(
    exc: VehicleCostSimulationUnavailableError,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "vehicle_cost_simulation_unavailable",
            "message": str(exc),
        },
    )


def _simulation_conflict(exc: VehicleCostSimulationConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "vehicle_cost_simulation_selection_conflict",
            "message": str(exc),
        },
    )


@router.post("/simulate", response_model=VehicleCostSimulationResponse)
def simulate_vehicle_cost(
    request: VehicleCostSimulationRequest,
    service: VehicleCostSimulationService = Depends(
        get_vehicle_cost_simulation_service
    ),
):
    try:
        result = service.simulate(request.to_contract())
    except VehicleCostSimulationConflictError as exc:
        raise _simulation_conflict(exc) from exc
    except VehicleCostSimulationUnavailableError as exc:
        raise _simulation_unavailable(exc) from exc
    return VehicleCostSimulationResponse.model_validate(result)


@router.get("/metadata", response_model=IntegratedDatasetMetadata)
def metadata(
    service: IntegratedGoldService = Depends(get_integrated_gold_service),
):
    try:
        return service.metadata()
    except IntegratedGoldUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/vehicles", response_model=IntegratedCostPage)
def vehicles(
    brand_name: str | None = Query(default=None, min_length=1, max_length=80),
    model_name: str | None = Query(default=None, min_length=1, max_length=120),
    model_year: int | None = Query(default=None, ge=1900, le=2100),
    fuel_scenario_code: Literal[
        "gasoline_c_common",
        "gasoline_c_additized",
        "ethanol_hydrated",
    ]
    | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal[
        "brand_name",
        "model_name",
        "model_year",
        "vehicle_sk",
        "mixed_cost_per_km_brl",
    ] = "brand_name",
    sort_direction: Literal["asc", "desc"] = "asc",
    service: IntegratedGoldService = Depends(get_integrated_gold_service),
):
    try:
        return service.list_costs(
            IntegratedGoldFilters(
                brand_name=brand_name,
                model_name=model_name,
                model_year=model_year,
                fuel_scenario_code=fuel_scenario_code,
            ),
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    except IntegratedGoldUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("/vehicles/{vehicle_sk}", response_model=IntegratedVehicleDetail)
def vehicle(
    vehicle_sk: int,
    service: IntegratedGoldService = Depends(get_integrated_gold_service),
):
    if vehicle_sk < 1:
        raise HTTPException(status_code=422, detail="vehicle_sk must be positive")
    try:
        return service.vehicle(vehicle_sk)
    except IntegratedGoldUnavailableError as exc:
        raise _unavailable(exc) from exc
    except IntegratedVehicleNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "integrated_vehicle_not_found", "message": str(exc)},
        ) from exc
