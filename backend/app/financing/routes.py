from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.fipe import effective_price, price_metadata
from app.financing.comparison import compare_results
from app.financing.domain import (
    CALCULATION_METHOD_VERSION,
    CURRENCY,
    FINANCING_MODULE_VERSION,
    MAX_TERM_MONTHS,
    FinancingDomainError,
    near_limit_percentage,
)
from app.financing.schemas import (
    DirectFinancingRequest,
    FinancingComparisonRequest,
    ReverseFinancingRequest,
)
from app.financing.service import simulate_direct, simulate_reverse
from app.vehicle_domain import VehicleType
from app.vehicle_queries import get_car


router = APIRouter(prefix="/financing", tags=["financing"])


def _decimal_price(value, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"{field_name} não possui valor numérico válido") from error
    if not result.is_finite() or result <= 0:
        raise HTTPException(status_code=422, detail=f"{field_name} deve ser maior que zero")
    return result


def _resolve_price(payload: DirectFinancingRequest, db: Session) -> dict:
    if payload.vehicle_id is None:
        return {
            "used_price": payload.vehicle_price,
            "catalog_price": None,
            "manual_price": payload.vehicle_price,
            "negotiated_price": None,
            "price_source": "manual",
            "vehicle": None,
            "is_demonstration_data": False,
            "warnings": ["Preço informado manualmente pelo usuário."],
        }

    if payload.vehicle_type == VehicleType.CAR:
        record = get_car(db, payload.vehicle_id)
        if record is None:
            if db.query(models.Motorcycle).filter(models.Motorcycle.id == payload.vehicle_id).first():
                raise HTTPException(status_code=422, detail="o ID informado pertence a uma motocicleta")
            raise HTTPException(status_code=404, detail="automóvel não encontrado")
        metadata = price_metadata(record.id)
        catalog_price = _decimal_price(effective_price(record.id, record.price), "preço do automóvel")
        vehicle = {
            "id": record.id,
            "vehicle_type": "car",
            "brand": record.brand,
            "model": record.model,
            "year": record.year,
        }
        demonstration = not bool(metadata.get("is_fipe"))
        warnings = []
        if demonstration:
            warnings.append("O preço do catálogo automotivo é uma referência demonstrativa ou ainda não sincronizada.")
    else:
        record = (
            db.query(models.Motorcycle)
            .filter(
                models.Motorcycle.id == payload.vehicle_id,
                models.Motorcycle.vehicle_type == VehicleType.MOTORCYCLE.value,
            )
            .one_or_none()
        )
        if record is None:
            if get_car(db, payload.vehicle_id) is not None:
                raise HTTPException(status_code=422, detail="o ID informado pertence a um automovel")
            raise HTTPException(status_code=404, detail="motocicleta não encontrada")
        catalog_price = _decimal_price(record.price, "preço da motocicleta")
        vehicle = {
            "id": record.id,
            "vehicle_type": "motorcycle",
            "brand": record.brand,
            "model": record.model,
            "year": record.year,
        }
        demonstration = record.data_source == "demonstration"
        warnings = []
        if demonstration:
            warnings.append("O preço da motocicleta pertence a uma base demonstrativa.")

    used_price = payload.negotiated_price or catalog_price
    return {
        "used_price": used_price,
        "catalog_price": catalog_price,
        "manual_price": None,
        "negotiated_price": payload.negotiated_price,
        "price_source": "negotiated" if payload.negotiated_price is not None else "catalog",
        "vehicle": vehicle,
        "is_demonstration_data": demonstration,
        "warnings": warnings,
    }


@router.get("/metadata")
def financing_metadata():
    return {
        "module_version": FINANCING_MODULE_VERSION,
        "calculation_method_version": CALCULATION_METHOD_VERSION,
        "supported_amortization_methods": ["price"],
        "supported_vehicle_types": ["car", "motorcycle"],
        "supported_rate_modes": ["monthly_interest_rate", "informed_effective_cost_rate"],
        "price_sources": ["catalog", "negotiated", "manual"],
        "currency": CURRENCY,
        "technical_limits": {
            "minimum_term_months": 1,
            "maximum_term_months": MAX_TERM_MONTHS,
            "near_limit_percentage": float(near_limit_percentage()),
        },
        "bank_integration": False,
        "credit_approval_guarantee": False,
        "stateless": True,
    }


@router.post("/simulate")
def financing_simulation(payload: DirectFinancingRequest, db: Session = Depends(get_db)):
    try:
        return simulate_direct(payload, _resolve_price(payload, db))
    except FinancingDomainError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/reverse-simulate")
def reverse_financing_simulation(payload: ReverseFinancingRequest):
    try:
        return simulate_reverse(payload)
    except FinancingDomainError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/compare")
def financing_comparison(payload: FinancingComparisonRequest, db: Session = Depends(get_db)):
    results = []
    try:
        for index, scenario in enumerate(payload.scenarios, start=1):
            result = simulate_direct(scenario, _resolve_price(scenario, db))
            result["scenario_name"] = scenario.offer_name or f"Cenario {index}"
            results.append(result)
    except FinancingDomainError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return compare_results(results)
