from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import models
from app.config import cors_allowed_origins, load_runtime_settings
from app.database import (
    DATABASE_SETTINGS,
    SessionLocal,
    check_database_connection,
    create_database,
    current_migration_revision,
    get_db,
    migration_is_up_to_date,
)
from app.fipe import (
    ensure_fipe_prices_current,
    fipe_coverage,
    fipe_sync_status,
    price_metadata,
    refresh_fipe_prices,
)
from app.financing.routes import router as financing_router
from app.integrated_gold.routes import router as integrated_gold_router
from app.integrated_gold.repository import IntegratedGoldStorageError
from app.recommendation_identity_repository import GoldRecommendationIdentityReader
from app.http_middleware import (
    PublicDemoReadOnlyMiddleware,
    RequestLoggingMiddleware,
)
from app.online_search import find_online_matches, search_online_cars
from app.motorcycle_audit import audit_motorcycle_record
from app.parts_analysis import (
    build_recommender_parts_feedback,
    calculate_maintenance_index,
    calculate_part_price_stats,
    calculate_vehicle_parts_summary,
)
from app.parts_catalog import get_parts_catalog
from app.multifactor_recommendation import (
    MULTIFACTOR_POLICY_VERSION,
    apply_multifactor_ranking,
)
from app.multifactor_schemas import MultifactorRecommendationProfile
from app.recommender import RecommendationProfile, recommend
from app.repository import (
    create_consumption_report,
    create_expense,
    create_maintenance,
    create_motorcycle,
    create_motorcycle_derived_metric,
    create_motorcycle_economic_estimate,
    create_motorcycle_source,
    create_user,
    create_user_vehicle,
    create_vehicle,
    create_vehicle_report,
    count_motorcycle_records,
    delete_motorcycle_record,
    delete_motorcycle_source,
    ensure_seed_data,
    get_motorcycle_record,
    InvalidMotorcycleRecordError,
    list_motorcycle_records,
    list_motorcycle_derived_metrics,
    list_motorcycle_economic_estimates,
    list_motorcycle_sources,
    model_to_recommendation_vehicle,
    motorcycle_to_response,
    set_motorcycle_primary_source,
    update_motorcycle,
    update_motorcycle_source,
    update_user_vehicle,
    user_vehicle_to_response,
    vehicle_to_response,
)
from app.schemas import (
    ExpenseCreate,
    ExpenseRead,
    FuelConsumptionReportCreate,
    FuelConsumptionReportRead,
    LoginRequest,
    LoginResponse,
    MaintenanceCreate,
    MaintenanceRead,
    MotorcycleCreate,
    MotorcycleDataSourceCreate,
    MotorcycleDataSourceRead,
    MotorcycleDataSourceUpdate,
    MotorcycleDerivedMetricCreate,
    MotorcycleDerivedMetricRead,
    MotorcycleEconomicEstimateCreate,
    MotorcycleEconomicEstimateRead,
    MotorcycleListEnvelope,
    MotorcycleRead,
    MotorcycleUpdate,
    PartRead,
    SupplierRead,
    UserCreate,
    UserRead,
    UserVehicleCreate,
    UserVehicleUpdate,
    VehicleCreate,
    VehicleReportCreate,
    VehicleReportRead,
)
from app.vehicle_history import build_preventive_alerts, build_recommendation_feedback, calculate_model_statistics
from app.vehicle_domain import CarUseCase, RecommendationStrategy, VehicleType
from app.vehicle_queries import car_query, get_car
from app.integrated_gold.simulation_service import (
    VehicleCostSimulationConflictError,
    VehicleCostSimulationUnavailableError,
    simulation_service_for_session,
)


LOGGER = logging.getLogger(__name__)


DEMO_ACCOUNTS = {
    ("usuario@sigra.local", "user"): {
        "id": 1,
        "name": "Usuário Demonstração",
        "email": "usuario@sigra.local",
        "password": "usuario123",
        "role": "user",
    },
    ("admin@sigra.local", "admin"): {
        "id": 99,
        "name": "Administrador SIGRA",
        "email": "admin@sigra.local",
        "password": "admin123",
        "role": "admin",
    },
}



@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_SETTINGS.bootstrap_schema:
        create_database()
        with SessionLocal() as db:
            ensure_seed_data(db)
    else:
        check_database_connection()
        if (
            DATABASE_SETTINGS.is_published_environment
            and not migration_is_up_to_date()
        ):
            raise RuntimeError(
                "Schema remoto desatualizado. Execute Alembic antes do backend."
            )
    ensure_fipe_prices_current()
    yield


RUNTIME_SETTINGS = load_runtime_settings()
app = FastAPI(
    title="SIGRA API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if RUNTIME_SETTINGS.api_docs_enabled else None,
    redoc_url="/redoc" if RUNTIME_SETTINGS.api_docs_enabled else None,
    openapi_url="/openapi.json" if RUNTIME_SETTINGS.api_docs_enabled else None,
)

ALGORITHM_VERSION = "2.1.2"
WEIGHTS_VERSION = "cars-v1"
MOTORCYCLE_MODULE_VERSION = "0.3.1"

app.add_middleware(PublicDemoReadOnlyMiddleware)
app.add_middleware(RequestLoggingMiddleware)
if RUNTIME_SETTINGS.allowed_hosts:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(RUNTIME_SETTINGS.allowed_hosts),
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(
        environment=RUNTIME_SETTINGS.environment,
    ),
    allow_credentials=not RUNTIME_SETTINGS.public_demo_mode,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(financing_router)
app.include_router(integrated_gold_router)


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    vehicle_type: Literal["car"] = "car"
    budget: float = Field(gt=0, examples=[70000])
    monthly_limit: float = Field(gt=0, examples=[1200])
    use_case: CarUseCase = Field(examples=["cidade"])
    monthly_mileage: float = Field(default=1000, ge=0)
    fuel_price: float = Field(default=6.0, gt=0)
    recommendation_strategy: RecommendationStrategy = Field(
        default=RecommendationStrategy.COST_BENEFIT,
        examples=["cost_benefit"],
    )
    multifactor_profile: MultifactorRecommendationProfile | None = None


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    vehicle_count = car_query(db).count()
    motorcycle_count = db.query(models.Motorcycle).count()
    migration_revision = current_migration_revision()
    return {
        "status": "ok",
        "app": "SIGRA API",
        "version": app.version,
        "docs_url": app.docs_url,
        "environment": DATABASE_SETTINGS.environment,
        "public_demo_mode": RUNTIME_SETTINGS.public_demo_mode,
        "database": {
            "engine": DATABASE_SETTINGS.backend_name,
            "reachable": True,
            "migration_revision": migration_revision,
            "migration_up_to_date": migration_is_up_to_date(),
        },
        "vehicles": vehicle_count,
        "motorcycles": motorcycle_count,
        "fipe": fipe_coverage(vehicle_count),
    }


@app.get("/health/database")
def database_health_check():
    try:
        check_database_connection()
        migration_revision = current_migration_revision()
        migration_up_to_date = migration_is_up_to_date()
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unavailable",
                "database": {
                    "engine": DATABASE_SETTINGS.backend_name,
                    "reachable": False,
                    "migration_revision": None,
                    "migration_up_to_date": False,
                },
            },
        ) from None
    return {
        "status": "ok",
        "database": {
            "engine": DATABASE_SETTINGS.backend_name,
            "reachable": True,
            "migration_revision": migration_revision,
            "migration_up_to_date": migration_up_to_date,
        },
    }


@app.get("/motorcycles/module-status")
def motorcycle_module_status():
    return {
        "motorcycle_module_version": MOTORCYCLE_MODULE_VERSION,
        "motorcycle_algorithm_version": None,
        "motorcycle_weights_version": None,
        "derived_metrics_method_version": None,
        "vehicle_type": "motorcycle",
        "status": "in_development",
    }


@app.post("/motorcycles/recommendations", status_code=501)
def motorcycle_recommendations_not_implemented():
    return JSONResponse(
        status_code=501,
        content={
            "detail": "O mecanismo de recomendação de motocicletas ainda não foi implementado.",
            "module_available": True,
            "module_version": MOTORCYCLE_MODULE_VERSION,
            "algorithm_version": None,
            "weights_version": None,
            "derived_metrics_method_version": None,
        },
    )


@app.get(
    "/motorcycles",
    response_model=list[MotorcycleRead] | MotorcycleListEnvelope,
    response_model_exclude_none=True,
)
def list_motorcycles(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    envelope: bool = Query(default=False),
    include_legacy: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    total_found = count_motorcycle_records(db)
    records = list_motorcycle_records(db, limit=limit, offset=offset)
    payload = []
    invalid_record_summary = []
    for record in records:
        audit = audit_motorcycle_record(record)
        if audit["is_valid"]:
            payload.append(motorcycle_to_response(record, include_legacy=include_legacy))
            continue
        LOGGER.warning(
            "motorcycle_record_omitted",
            extra={
                "motorcycle_id": record.get("id"),
                "issue_count": len(audit["issues"]),
                "issues": [
                    {"field": issue["field"], "code": issue["code"]}
                    for issue in audit["issues"]
                ],
            },
        )
        invalid_record_summary.append(
            {
                "id": record.get("id") if isinstance(record.get("id"), int) else None,
                "brand": record.get("brand") if isinstance(record.get("brand"), str) else None,
                "model": record.get("model") if isinstance(record.get("model"), str) else None,
                "issue_count": len(audit["issues"]),
            }
        )
    if not envelope:
        return payload
    return {
        "module_version": MOTORCYCLE_MODULE_VERSION,
        "algorithm_version": None,
        "weights_version": None,
        "derived_metrics_method_version": None,
        "total_found": total_found,
        "returned": len(records),
        "valid_records": len(payload),
        "invalid_records": len(invalid_record_summary),
        "motorcycles": payload,
        "invalid_record_summary": invalid_record_summary,
    }


@app.post("/motorcycles", response_model=MotorcycleRead, response_model_exclude_none=True, status_code=201)
def add_motorcycle(
    payload: MotorcycleCreate,
    include_legacy: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    try:
        return motorcycle_to_response(create_motorcycle(db, payload), include_legacy=include_legacy)
    except InvalidMotorcycleRecordError as error:
        raise HTTPException(status_code=422, detail=_invalid_motorcycle_detail(error.audit)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/motorcycles/{motorcycle_id}", response_model=MotorcycleRead, response_model_exclude_none=True)
def get_motorcycle(
    motorcycle_id: int,
    include_legacy: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    motorcycle = get_motorcycle_record(db, motorcycle_id)
    if motorcycle is None:
        raise HTTPException(status_code=404, detail="Motocicleta não encontrada")
    audit = audit_motorcycle_record(motorcycle)
    if not audit["is_valid"]:
        raise HTTPException(status_code=409, detail=_invalid_motorcycle_detail(audit))
    return motorcycle_to_response(motorcycle, include_legacy=include_legacy)


@app.patch("/motorcycles/{motorcycle_id}", response_model=MotorcycleRead, response_model_exclude_none=True)
def edit_motorcycle(
    motorcycle_id: int,
    payload: MotorcycleUpdate,
    include_legacy: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    motorcycle = get_motorcycle_record(db, motorcycle_id)
    if motorcycle is None:
        raise HTTPException(status_code=404, detail="Motocicleta não encontrada")
    try:
        updated = update_motorcycle(db, motorcycle, payload)
    except InvalidMotorcycleRecordError as error:
        raise HTTPException(status_code=422, detail=_invalid_motorcycle_detail(error.audit)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return motorcycle_to_response(updated, include_legacy=include_legacy)


@app.delete("/motorcycles/{motorcycle_id}", status_code=204)
def delete_motorcycle(motorcycle_id: int, db: Session = Depends(get_db)):
    if not delete_motorcycle_record(db, motorcycle_id):
        raise HTTPException(status_code=404, detail="Motocicleta não encontrada")


@app.get("/motorcycles/{motorcycle_id}/sources", response_model=list[MotorcycleDataSourceRead])
def get_motorcycle_sources(motorcycle_id: int, db: Session = Depends(get_db)):
    try:
        return list_motorcycle_sources(db, motorcycle_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/motorcycles/{motorcycle_id}/sources", response_model=MotorcycleDataSourceRead, status_code=201)
def add_motorcycle_source(
    motorcycle_id: int,
    payload: MotorcycleDataSourceCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_motorcycle_source(db, motorcycle_id, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.patch("/motorcycles/{motorcycle_id}/sources/{source_id}", response_model=MotorcycleDataSourceRead)
def edit_motorcycle_source(
    motorcycle_id: int,
    source_id: int,
    payload: MotorcycleDataSourceUpdate,
    db: Session = Depends(get_db),
):
    try:
        source = update_motorcycle_source(db, motorcycle_id, source_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if source is None:
        raise HTTPException(status_code=404, detail="Fonte da motocicleta não encontrada")
    return source


@app.delete("/motorcycles/{motorcycle_id}/sources/{source_id}", status_code=204)
def remove_motorcycle_source(motorcycle_id: int, source_id: int, db: Session = Depends(get_db)):
    if not delete_motorcycle_source(db, motorcycle_id, source_id):
        raise HTTPException(status_code=404, detail="Fonte da motocicleta não encontrada")


@app.post(
    "/motorcycles/{motorcycle_id}/sources/{source_id}/set-primary",
    response_model=MotorcycleDataSourceRead,
)
def make_motorcycle_source_primary(motorcycle_id: int, source_id: int, db: Session = Depends(get_db)):
    source = set_motorcycle_primary_source(db, motorcycle_id, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fonte da motocicleta não encontrada")
    return source


@app.get("/motorcycles/{motorcycle_id}/derived-metrics", response_model=list[MotorcycleDerivedMetricRead])
def get_motorcycle_metrics(motorcycle_id: int, db: Session = Depends(get_db)):
    try:
        return list_motorcycle_derived_metrics(db, motorcycle_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post(
    "/motorcycles/{motorcycle_id}/derived-metrics",
    response_model=MotorcycleDerivedMetricRead,
    status_code=201,
)
def add_motorcycle_metric(
    motorcycle_id: int,
    payload: MotorcycleDerivedMetricCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_motorcycle_derived_metric(db, motorcycle_id, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/motorcycles/{motorcycle_id}/economic-estimates",
    response_model=list[MotorcycleEconomicEstimateRead],
)
def get_motorcycle_estimates(motorcycle_id: int, db: Session = Depends(get_db)):
    try:
        return list_motorcycle_economic_estimates(db, motorcycle_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post(
    "/motorcycles/{motorcycle_id}/economic-estimates",
    response_model=MotorcycleEconomicEstimateRead,
    status_code=201,
)
def add_motorcycle_estimate(
    motorcycle_id: int,
    payload: MotorcycleEconomicEstimateCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_motorcycle_economic_estimate(db, motorcycle_id, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _invalid_motorcycle_detail(audit: dict) -> dict:
    return {
        "code": "motorcycle_record_invalid",
        "message": "O registro existe, mas possui dados inválidos ou incompletos.",
        "issues": audit["issues"],
    }


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    account = DEMO_ACCOUNTS.get((payload.email.lower(), payload.role))
    if account is None or payload.password != account["password"]:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return {
        "id": account["id"],
        "name": account["name"],
        "email": account["email"],
        "role": account["role"],
    }


@app.get("/vehicles")
def list_vehicles(db: Session = Depends(get_db)):
    ensure_fipe_prices_current()
    vehicles = car_query(db).order_by(models.Vehicle.brand, models.Vehicle.model).all()
    return [vehicle_to_response(vehicle) for vehicle in vehicles]


@app.post("/vehicles", status_code=201)
def add_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)):
    return vehicle_to_response(create_vehicle(db, payload))


@app.get("/vehicles/compare")
def compare_vehicles(ids: list[int] = Query(default=[]), db: Session = Depends(get_db)):
    ensure_fipe_prices_current()
    selected_ids = set(ids)
    query = car_query(db)
    if selected_ids:
        query = query.filter(models.Vehicle.id.in_(selected_ids))
    vehicles = query.order_by(models.Vehicle.brand, models.Vehicle.model).all()
    return [vehicle_to_response(vehicle) for vehicle in vehicles]


@app.get("/vehicles/{vehicle_id}/price-reference")
def vehicle_price_reference(vehicle_id: int, db: Session = Depends(get_db)):
    ensure_fipe_prices_current()
    vehicle = get_car(db, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return {
        "vehicle_id": vehicle.id,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "year": vehicle.year,
        "price": vehicle_to_response(vehicle)["price"],
        "price_reference": price_metadata(vehicle.id),
    }


@app.get("/prices/fipe/status")
def fipe_price_status():
    return fipe_sync_status()


@app.post("/prices/fipe/refresh")
def force_fipe_price_refresh():
    return refresh_fipe_prices(force=True)


@app.post("/recommendations")
def create_recommendations(
    request: RecommendationRequest,
    envelope: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    ensure_fipe_prices_current()
    profile = RecommendationProfile(
        budget=request.budget,
        monthly_limit=request.monthly_limit,
        use_case=request.use_case.value,
        monthly_mileage=request.monthly_mileage,
        fuel_price=request.fuel_price,
        recommendation_strategy=request.recommendation_strategy.value,
    )
    database_vehicles = car_query(db).order_by(models.Vehicle.id).all()
    vehicles = [
        model_to_recommendation_vehicle(vehicle)
        for vehicle in database_vehicles
    ]
    feedback = build_recommendation_feedback(db)
    parts_feedback = build_recommender_parts_feedback(db)
    vehicle_processing: dict[str, object] = {}
    results = recommend(vehicles, profile, feedback, parts_feedback, vehicle_processing)
    has_viable_options = any(item["score_components"].get("fully_viable") for item in results)
    best_recommendation_id = next(
        (
            item["vehicle"].id
            for item in results
            if item["score_components"].get("fully_viable")
        ),
        None,
    )
    best_available_reference_id = results[0]["vehicle"].id if results and not has_viable_options else None
    payload = [
        {
            "vehicle": item["vehicle"].__dict__,
            "parts_catalog": get_parts_catalog(item["vehicle"].brand, item["vehicle"].model),
            "online_matches": find_online_matches(
                item["vehicle"].brand,
                item["vehicle"].model,
                item["vehicle"].year,
            ),
            "score": item["score"],
            "final_score": item["final_score"],
            "value_score": item["value_score"],
            "decision_score": item["decision_score"],
            "has_viable_options": has_viable_options,
            "is_best_choice": has_viable_options and item["vehicle"].id == best_recommendation_id,
            "is_best_available_reference": (
                not has_viable_options and item["vehicle"].id == best_available_reference_id
            ),
            "recommendation_status": item["recommendation_status"],
            "recommendation_strategy": item["recommendation_strategy"],
            "monthly_cost": item["monthly_cost"],
            "tco": item["tco"],
            "components": item["components"],
            "score_components": item["score_components"],
            "penalties": item["penalties"],
            "feedback_adjustment": item["feedback_adjustment"],
            "parts_feedback": item["parts_feedback"],
            "score_breakdown": item["score_breakdown"],
            "confidence": item["confidence"],
            "category_awards": item["category_awards"],
            "recommendation_summary": item["recommendation_summary"],
            "explanations": item["explanations"],
        }
        for item in results
    ]
    multifactor_metadata = None
    if request.multifactor_profile is not None:
        try:
            simulation = simulation_service_for_session(db).simulate(
                request.multifactor_profile.scenario.to_contract()
            )
            payload = apply_multifactor_ranking(
                payload,
                simulation,
                request.multifactor_profile.weights.as_mapping(),
                gold_identities=GoldRecommendationIdentityReader(db).recommendation_identities(),
                catalog_references={item["vehicle"]["id"]: price_metadata(item["vehicle"]["id"])
                                    for item in payload},
            )
        except VehicleCostSimulationConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "multifactor_gold_identity_conflict",
                    "message": "multifactor recommendation found conflicting Gold evidence",
                },
            ) from exc
        except (VehicleCostSimulationUnavailableError, IntegratedGoldStorageError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "multifactor_gold_unavailable",
                    "message": "eligible integrated Gold is unavailable for multifactor recommendation",
                },
            ) from exc
        multifactor_metadata = {
            "enabled": True,
            "policy_version": MULTIFACTOR_POLICY_VERSION,
            "scenario": request.multifactor_profile.scenario.model_dump(),
            "weights": request.multifactor_profile.weights.model_dump(),
            "simulation_fingerprint": simulation.fingerprint,
            "ranked_count": len(
                [
                    item
                    for item in payload
                    if item.get("multifactor", {}).get("status") == "ranked"
                ]
            ),
            "unavailable_count": len(
                [
                    item
                    for item in payload
                    if item.get("multifactor", {}).get("status") == "unavailable"
                ]
            ),
            "stateless": True,
            "active_gold_unchanged": True,
        }
    if not envelope:
        return payload
    response = {
        "algorithm_version": ALGORITHM_VERSION,
        "weights_version": WEIGHTS_VERSION,
        "vehicle_type": "car",
        "data_reference": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "has_viable_options": has_viable_options,
        "vehicle_processing": vehicle_processing,
        "recommendations": payload,
    }
    if multifactor_metadata is not None:
        response["multifactor_profile"] = multifactor_metadata
    return response


@app.get("/parts", response_model=list[PartRead])
def list_parts(db: Session = Depends(get_db)):
    return db.query(models.Part).order_by(models.Part.category, models.Part.name).all()


@app.get("/suppliers", response_model=list[SupplierRead])
def list_suppliers(db: Session = Depends(get_db)):
    return db.query(models.Supplier).order_by(models.Supplier.name).all()


@app.get("/parts/{part_id}/prices")
def part_prices(part_id: int, vehicle_id: int | None = None, db: Session = Depends(get_db)):
    if db.get(models.Part, part_id) is None:
        raise HTTPException(status_code=404, detail="Peça não encontrada")
    if vehicle_id is not None:
        if get_car(db, vehicle_id) is None:
            raise HTTPException(status_code=404, detail="Veículo não encontrado")
        return calculate_part_price_stats(db, vehicle_id, part_id)
    return db.query(models.PartPrice).filter(models.PartPrice.part_id == part_id).order_by(models.PartPrice.price).all()


@app.get("/vehicles/{vehicle_id}/parts")
def vehicle_parts(vehicle_id: int, db: Session = Depends(get_db)):
    if get_car(db, vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    part_ids = [item[0] for item in db.query(models.PartPrice.part_id).filter(models.PartPrice.vehicle_id == vehicle_id).distinct()]
    return [db.get(models.Part, part_id) for part_id in part_ids]


@app.get("/vehicles/{vehicle_id}/maintenance-index")
def vehicle_maintenance_index(vehicle_id: int, db: Session = Depends(get_db)):
    if get_car(db, vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return {"vehicle_id": vehicle_id, "maintenance_index": calculate_maintenance_index(db, vehicle_id)}


@app.get("/vehicles/{vehicle_id}/parts-analysis")
def vehicle_parts_analysis(vehicle_id: int, db: Session = Depends(get_db)):
    if get_car(db, vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return calculate_vehicle_parts_summary(db, vehicle_id)


@app.get("/online-car-search")
def online_car_search(query: str = ""):
    return search_online_cars(query)


@app.post("/users", response_model=UserRead, status_code=201)
def add_user(payload: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, payload)


@app.get("/expenses", response_model=list[ExpenseRead])
def list_expenses(db: Session = Depends(get_db)):
    return (
        db.query(models.Expense)
        .join(models.Vehicle, models.Expense.vehicle_id == models.Vehicle.id)
        .filter(models.Vehicle.vehicle_type == VehicleType.CAR.value)
        .order_by(models.Expense.expense_date.desc())
        .all()
    )


@app.post("/expenses", response_model=ExpenseRead, status_code=201)
def add_expense(payload: ExpenseCreate, db: Session = Depends(get_db)):
    ensure_related_records(db, payload.user_id, payload.vehicle_id)
    return create_expense(db, payload)


@app.get("/maintenances", response_model=list[MaintenanceRead])
def list_maintenances(db: Session = Depends(get_db)):
    return (
        db.query(models.Maintenance)
        .join(models.Vehicle, models.Maintenance.vehicle_id == models.Vehicle.id)
        .filter(models.Vehicle.vehicle_type == VehicleType.CAR.value)
        .order_by(models.Maintenance.scheduled_date.desc())
        .all()
    )


@app.post("/maintenances", response_model=MaintenanceRead, status_code=201)
def add_maintenance(payload: MaintenanceCreate, db: Session = Depends(get_db)):
    ensure_related_records(db, payload.user_id, payload.vehicle_id)
    return create_maintenance(db, payload)


@app.get("/user-vehicles")
def list_user_vehicles(user_id: int = 1, db: Session = Depends(get_db)):
    if db.get(models.User, user_id) is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    items = (
        db.query(models.UserVehicle)
        .join(models.Vehicle, models.UserVehicle.vehicle_id == models.Vehicle.id)
        .filter(
            models.UserVehicle.user_id == user_id,
            models.Vehicle.vehicle_type == VehicleType.CAR.value,
        )
        .order_by(models.UserVehicle.updated_at.desc())
        .all()
    )
    return [user_vehicle_to_response(item) for item in items]


@app.post("/user-vehicles", status_code=201)
def add_user_vehicle(payload: UserVehicleCreate, db: Session = Depends(get_db)):
    ensure_related_records(db, payload.user_id, payload.vehicle_id)
    if payload.purchase_km > payload.current_km:
        raise HTTPException(status_code=422, detail="Km de compra não pode ser maior que o km atual")
    return user_vehicle_to_response(create_user_vehicle(db, payload))


@app.patch("/user-vehicles/{user_vehicle_id}")
def edit_user_vehicle(user_vehicle_id: int, payload: UserVehicleUpdate, db: Session = Depends(get_db)):
    item = db.get(models.UserVehicle, user_vehicle_id)
    if item is None or item.vehicle is None or item.vehicle.vehicle_type != VehicleType.CAR.value:
        raise HTTPException(status_code=404, detail="Veículo do usuário não encontrado")
    next_values = {
        "purchase_km": payload.purchase_km if payload.purchase_km is not None else item.purchase_km,
        "current_km": payload.current_km if payload.current_km is not None else item.current_km,
    }
    if next_values["purchase_km"] > next_values["current_km"]:
        raise HTTPException(status_code=422, detail="Km de compra não pode ser maior que o km atual")
    updated = update_user_vehicle(db, item, payload)
    return user_vehicle_to_response(updated)


@app.delete("/user-vehicles/{user_vehicle_id}", status_code=204)
def delete_user_vehicle(user_vehicle_id: int, db: Session = Depends(get_db)):
    item = db.get(models.UserVehicle, user_vehicle_id)
    if item is None or item.vehicle is None or item.vehicle.vehicle_type != VehicleType.CAR.value:
        raise HTTPException(status_code=404, detail="Veículo do usuário não encontrado")
    db.delete(item)
    db.commit()
    return None


@app.get("/user-vehicles/{user_vehicle_id}/history")
def user_vehicle_history(user_vehicle_id: int, db: Session = Depends(get_db)):
    item = db.get(models.UserVehicle, user_vehicle_id)
    if item is None or item.vehicle is None or item.vehicle.vehicle_type != VehicleType.CAR.value:
        raise HTTPException(status_code=404, detail="Veículo do usuário não encontrado")
    reports = (
        db.query(models.VehicleReport)
        .filter(models.VehicleReport.user_vehicle_id == user_vehicle_id)
        .order_by(models.VehicleReport.occurrence_date.desc())
        .all()
    )
    consumptions = (
        db.query(models.FuelConsumptionReport)
        .filter(models.FuelConsumptionReport.user_vehicle_id == user_vehicle_id)
        .order_by(models.FuelConsumptionReport.created_at.desc())
        .all()
    )
    return {
        "user_vehicle": user_vehicle_to_response(item),
        "reports": [vehicle_report_to_response(report) for report in reports],
        "consumption_reports": [consumption_report_to_response(report) for report in consumptions],
        "alerts": build_preventive_alerts(db, item),
        "model_statistics": calculate_model_statistics(db, item.vehicle_id).get(item.vehicle_id),
    }


@app.post("/vehicle-reports", response_model=VehicleReportRead, status_code=201)
def add_vehicle_report(payload: VehicleReportCreate, db: Session = Depends(get_db)):
    ensure_user_vehicle_exists(db, payload.user_vehicle_id)
    return create_vehicle_report(db, payload)


@app.get("/vehicle-reports", response_model=list[VehicleReportRead])
def list_vehicle_reports(vehicle_id: int | None = None, db: Session = Depends(get_db)):
    query = (
        db.query(models.VehicleReport)
        .join(models.Vehicle, models.VehicleReport.vehicle_id == models.Vehicle.id)
        .filter(models.Vehicle.vehicle_type == VehicleType.CAR.value)
    )
    if vehicle_id is not None:
        query = query.filter(models.VehicleReport.vehicle_id == vehicle_id)
    return query.order_by(models.VehicleReport.occurrence_date.desc()).all()


@app.delete("/vehicle-reports/{report_id}", status_code=204)
def delete_vehicle_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(models.VehicleReport, report_id)
    if report is None or get_car(db, report.vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Relato não encontrado")
    db.delete(report)
    db.commit()
    return None


@app.post("/fuel-consumption-reports", response_model=FuelConsumptionReportRead, status_code=201)
def add_consumption_report(payload: FuelConsumptionReportCreate, db: Session = Depends(get_db)):
    ensure_user_vehicle_exists(db, payload.user_vehicle_id)
    return create_consumption_report(db, payload)


@app.get("/fuel-consumption-reports", response_model=list[FuelConsumptionReportRead])
def list_consumption_reports(vehicle_id: int | None = None, db: Session = Depends(get_db)):
    query = (
        db.query(models.FuelConsumptionReport)
        .join(models.Vehicle, models.FuelConsumptionReport.vehicle_id == models.Vehicle.id)
        .filter(models.Vehicle.vehicle_type == VehicleType.CAR.value)
    )
    if vehicle_id is not None:
        query = query.filter(models.FuelConsumptionReport.vehicle_id == vehicle_id)
    return query.order_by(models.FuelConsumptionReport.created_at.desc()).all()


@app.get("/vehicle-statistics")
def vehicle_statistics(vehicle_id: int | None = None, db: Session = Depends(get_db)):
    stats = calculate_model_statistics(db, vehicle_id)
    return list(stats.values()) if vehicle_id is None else stats.get(vehicle_id, {})


@app.get("/user-vehicles/{user_vehicle_id}/alerts")
def preventive_alerts(user_vehicle_id: int, db: Session = Depends(get_db)):
    item = db.get(models.UserVehicle, user_vehicle_id)
    if item is None or item.vehicle is None or item.vehicle.vehicle_type != VehicleType.CAR.value:
        raise HTTPException(status_code=404, detail="Veículo do usuário não encontrado")
    return build_preventive_alerts(db, item)


@app.get("/reports/financial-summary")
def financial_summary(user_id: int = 1, db: Session = Depends(get_db)):
    if db.get(models.User, user_id) is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    expenses = (
        db.query(models.Expense)
        .join(models.Vehicle, models.Expense.vehicle_id == models.Vehicle.id)
        .filter(models.Expense.user_id == user_id, models.Vehicle.vehicle_type == VehicleType.CAR.value)
        .all()
    )
    maintenances = (
        db.query(models.Maintenance)
        .join(models.Vehicle, models.Maintenance.vehicle_id == models.Vehicle.id)
        .filter(models.Maintenance.user_id == user_id, models.Vehicle.vehicle_type == VehicleType.CAR.value)
        .all()
    )

    total_expenses = sum(expense.amount for expense in expenses)
    total_maintenance = sum(maintenance.cost for maintenance in maintenances)
    by_category: dict[str, float] = {}
    for expense in expenses:
        by_category[expense.category] = by_category.get(expense.category, 0) + expense.amount

    return {
        "user_id": user_id,
        "total_expenses": round(total_expenses, 2),
        "total_maintenance": round(total_maintenance, 2),
        "total_cost": round(total_expenses + total_maintenance, 2),
        "expenses_by_category": {key: round(value, 2) for key, value in by_category.items()},
        "pending_maintenances": len([maintenance for maintenance in maintenances if maintenance.status != "completed"]),
    }


def ensure_related_records(db: Session, user_id: int, vehicle_id: int) -> None:
    if db.get(models.User, user_id) is None:
        raise HTTPException(status_code=404, detail="Usuário informado não existe")
    if get_car(db, vehicle_id) is None:
        raise HTTPException(status_code=404, detail="Veículo informado não existe")


def ensure_user_vehicle_exists(db: Session, user_vehicle_id: int) -> None:
    item = db.get(models.UserVehicle, user_vehicle_id)
    if item is None or item.vehicle is None or item.vehicle.vehicle_type != VehicleType.CAR.value:
        raise HTTPException(status_code=404, detail="Veículo do usuário não existe")


def vehicle_report_to_response(report: models.VehicleReport) -> dict:
    return {
        "id": report.id,
        "user_vehicle_id": report.user_vehicle_id,
        "vehicle_id": report.vehicle_id,
        "problem_category": report.problem_category,
        "description": report.description,
        "occurrence_km": report.occurrence_km,
        "repair_cost": report.repair_cost,
        "severity": report.severity,
        "occurrence_date": report.occurrence_date,
        "resolved": report.resolved,
        "notes": report.notes,
    }


def consumption_report_to_response(report: models.FuelConsumptionReport) -> dict:
    return {
        "id": report.id,
        "user_vehicle_id": report.user_vehicle_id,
        "vehicle_id": report.vehicle_id,
        "km_per_liter": report.km_per_liter,
        "usage_type": report.usage_type,
        "fuel_type": report.fuel_type,
        "notes": report.notes,
    }
