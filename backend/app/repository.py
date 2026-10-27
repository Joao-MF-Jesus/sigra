import logging
from datetime import date
from enum import Enum

from pydantic import ValidationError
from sqlalchemy import delete, insert, text, update
from sqlalchemy.orm import Session

from app import models
from app.fipe import effective_price, price_metadata
from app.motorcycle_audit import audit_motorcycle_record
from app.motorcycle_eligibility import evaluate_motorcycle_eligibility
from app.parts_catalog import get_parts_catalog
from app.recommender import Vehicle as RecommendationVehicle
from app.sample_data import VEHICLES as SAMPLE_VEHICLES
from app.schemas import (
    ExpenseCreate,
    FuelConsumptionReportCreate,
    MaintenanceCreate,
    MotorcycleDataSourceBase,
    MotorcycleDataSourceRead,
    MotorcycleDerivedMetricRead,
    MotorcycleEconomicEstimateRead,
    UserCreate,
    UserVehicleCreate,
    UserVehicleUpdate,
    VehicleCreate,
    VehicleReportCreate,
)
from app.motorcycle_domain import (
    COMPLEMENTARY_SOURCE_GROUPS,
    PILOT_REQUIRED_SOURCE_GROUPS,
    REGISTRATION_REQUIRED_SOURCE_GROUPS,
    MotorcycleDerivedMetricName,
    MotorcycleMetricStatus,
)
from app.vehicle_domain import VehicleType
from app.vehicle_queries import car_query


LOGGER = logging.getLogger(__name__)


MOTORCYCLE_RECORD_SELECT = """
SELECT
    m.id, m.brand, m.model, m.year, m.price, m.city_consumption,
    m.road_consumption, m.annual_maintenance_cost, m.reliability_score,
    m.parts_availability_score, m.depreciation_rate, m.data_source,
    m.data_confidence, m.source_name, m.source_reference, m.source_url,
    CAST(m.source_collected_at AS TEXT) AS source_collected_at,
    CAST(m.source_reference_date AS TEXT) AS source_reference_date,
    CAST(m.last_verified_at AS TEXT) AS last_verified_at,
    m.vehicle_type, m.image_url, m.version, m.market_condition, m.fuel_type, m.is_demonstration,
    CAST(m.price_reference_date AS TEXT) AS price_reference_date,
    COALESCE(o.id, s.id) AS specification_id,
    COALESCE(o.engine_displacement_cc, s.engine_displacement_cc) AS spec_engine_displacement_cc,
    COALESCE(o.motorcycle_category, s.motorcycle_category) AS spec_motorcycle_category,
    COALESCE(o.wet_weight_kg, s.wet_weight_kg) AS spec_wet_weight_kg,
    COALESCE(o.seat_height_mm, s.seat_height_mm) AS spec_seat_height_mm,
    COALESCE(o.tank_capacity_l, s.tank_capacity_l) AS spec_tank_capacity_l,
    COALESCE(o.has_abs, s.has_abs) AS spec_has_abs,
    o.power_cv AS spec_power_cv,
    o.torque_nm AS spec_torque_nm,
    o.transmission_type AS spec_transmission_type,
    o.gear_count AS spec_gear_count,
    o.final_drive_type AS spec_final_drive_type,
    o.payload_capacity_kg AS spec_payload_capacity_kg,
    o.oil_change_interval_km AS spec_oil_change_interval_km,
    o.abs_channels AS spec_abs_channels,
    o.has_cbs AS spec_has_cbs,
    o.has_traction_control AS spec_has_traction_control
FROM motorcycles AS m
LEFT JOIN motorcycle_specifications AS s ON s.motorcycle_id = m.id
LEFT JOIN motorcycle_objective_specifications AS o ON o.motorcycle_id = m.id
"""

MOTORCYCLE_SOURCE_SELECT = """
SELECT id, motorcycle_id, data_group, source_type, source_name, source_reference,
       source_url, CAST(reference_date AS TEXT) AS reference_date,
       CAST(collected_at AS TEXT) AS collected_at,
       CAST(last_verified_at AS TEXT) AS last_verified_at,
       confidence, methodology_notes, is_primary,
       CAST(created_at AS TEXT) AS created_at, CAST(updated_at AS TEXT) AS updated_at
FROM motorcycle_data_sources
"""

MOTORCYCLE_METRIC_SELECT = """
SELECT id, motorcycle_id, metric_name, metric_value, metric_text_value,
       metric_status, method_version, CAST(calculated_at AS TEXT) AS calculated_at,
       confidence, source_group_id, notes
FROM motorcycle_derived_metrics
"""

MOTORCYCLE_ESTIMATE_SELECT = """
SELECT id, motorcycle_id, estimate_name, estimate_value, unit, method_version,
       CAST(reference_date AS TEXT) AS reference_date,
       CAST(calculated_at AS TEXT) AS calculated_at,
       confidence, source_group_id, status, notes
FROM motorcycle_economic_estimates
"""


class InvalidMotorcycleRecordError(ValueError):
    def __init__(self, audit: dict):
        super().__init__("O registro da motocicleta possui dados inválidos ou incompletos.")
        self.audit = audit


def _record_value(record, field, default=None):
    return record.get(field, default) if isinstance(record, dict) else getattr(record, field, default)


def _normalize_database_value(value):
    return value.value if isinstance(value, Enum) else value


def _nullable_bool(value):
    return None if value is None else bool(value)


def _row_to_motorcycle_record(row) -> dict:
    data = dict(row)
    data["is_demonstration"] = bool(data.get("is_demonstration", False))
    specification_id = data.pop("specification_id")
    specifications = None
    if specification_id is not None:
        specifications = {
            "id": specification_id,
            "engine_displacement_cc": data.pop("spec_engine_displacement_cc"),
            "motorcycle_category": data.pop("spec_motorcycle_category"),
            "wet_weight_kg": data.pop("spec_wet_weight_kg"),
            "seat_height_mm": data.pop("spec_seat_height_mm"),
            "tank_capacity_l": data.pop("spec_tank_capacity_l"),
            "has_abs": data.pop("spec_has_abs"),
            "power_cv": data.pop("spec_power_cv"),
            "torque_nm": data.pop("spec_torque_nm"),
            "transmission_type": data.pop("spec_transmission_type"),
            "gear_count": data.pop("spec_gear_count"),
            "final_drive_type": data.pop("spec_final_drive_type"),
            "payload_capacity_kg": data.pop("spec_payload_capacity_kg"),
            "oil_change_interval_km": data.pop("spec_oil_change_interval_km"),
            "abs_channels": data.pop("spec_abs_channels"),
            "has_cbs": data.pop("spec_has_cbs"),
            "has_traction_control": data.pop("spec_has_traction_control"),
            "recommended_experience": None,
            "urban_score": None,
            "road_score": None,
            "passenger_comfort_score": None,
            "luggage_score": None,
        }
    else:
        for field in list(data):
            if field.startswith("spec_"):
                data.pop(field)
    data["specifications"] = specifications
    data["data_sources"] = []
    data["derived_metrics"] = []
    data["economic_estimates"] = []
    return data


def _load_motorcycle_sources(db: Session, motorcycle_id: int) -> list[dict]:
    rows = db.execute(
        text(f"{MOTORCYCLE_SOURCE_SELECT} WHERE motorcycle_id = :motorcycle_id ORDER BY data_group, is_primary DESC, id"),
        {"motorcycle_id": motorcycle_id},
    ).mappings().all()
    valid = []
    for row in rows:
        try:
            source_data = dict(row)
            source_data["is_primary"] = bool(source_data["is_primary"])
            valid.append(MotorcycleDataSourceRead.model_validate(source_data).model_dump(mode="python"))
        except ValidationError as error:
            LOGGER.warning(
                "motorcycle_source_record_invalid",
                extra={"motorcycle_id": motorcycle_id, "source_id": row.get("id"), "errors": error.error_count()},
            )
    return valid


def _load_motorcycle_metrics(db: Session, motorcycle_id: int) -> list[dict]:
    rows = db.execute(
        text(f"{MOTORCYCLE_METRIC_SELECT} WHERE motorcycle_id = :motorcycle_id ORDER BY metric_name, method_version, id"),
        {"motorcycle_id": motorcycle_id},
    ).mappings().all()
    valid = []
    for row in rows:
        try:
            valid.append(MotorcycleDerivedMetricRead.model_validate(dict(row)).model_dump(mode="python"))
        except ValidationError as error:
            LOGGER.warning(
                "motorcycle_metric_record_invalid",
                extra={"motorcycle_id": motorcycle_id, "metric_id": row.get("id"), "errors": error.error_count()},
            )
    return valid


def _load_motorcycle_estimates(db: Session, motorcycle_id: int) -> list[dict]:
    rows = db.execute(
        text(f"{MOTORCYCLE_ESTIMATE_SELECT} WHERE motorcycle_id = :motorcycle_id ORDER BY estimate_name, reference_date DESC, id"),
        {"motorcycle_id": motorcycle_id},
    ).mappings().all()
    valid = []
    for row in rows:
        try:
            valid.append(MotorcycleEconomicEstimateRead.model_validate(dict(row)).model_dump(mode="python"))
        except ValidationError as error:
            LOGGER.warning(
                "motorcycle_economic_estimate_invalid",
                extra={"motorcycle_id": motorcycle_id, "estimate_id": row.get("id"), "errors": error.error_count()},
            )
    return valid


def _attach_motorcycle_relations(db: Session, record: dict) -> dict:
    record["data_sources"] = _load_motorcycle_sources(db, record["id"])
    record["derived_metrics"] = _load_motorcycle_metrics(db, record["id"])
    record["economic_estimates"] = _load_motorcycle_estimates(db, record["id"])
    return record


def get_motorcycle_record(db: Session, motorcycle_id: int) -> dict | None:
    row = db.execute(
        text(f"{MOTORCYCLE_RECORD_SELECT} WHERE m.id = :motorcycle_id"),
        {"motorcycle_id": motorcycle_id},
    ).mappings().first()
    return _attach_motorcycle_relations(db, _row_to_motorcycle_record(row)) if row is not None else None


def list_motorcycle_records(db: Session, *, limit: int, offset: int) -> list[dict]:
    rows = db.execute(
        text(
            f"{MOTORCYCLE_RECORD_SELECT} "
            "ORDER BY m.brand, m.model, m.id LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    ).mappings().all()
    return [_attach_motorcycle_relations(db, _row_to_motorcycle_record(row)) for row in rows]


def count_motorcycle_records(db: Session) -> int:
    return int(db.execute(text("SELECT COUNT(id) FROM motorcycles")).scalar_one())


def _log_invalid_motorcycle(record: dict, audit: dict) -> None:
    LOGGER.warning(
        "motorcycle_record_invalid",
        extra={
            "motorcycle_id": record.get("id"),
            "issue_count": len(audit["issues"]),
            "issues": [
                {"field": issue["field"], "code": issue["code"]}
                for issue in audit["issues"]
            ],
        },
    )


def split_text(value: str | None) -> list[str]:
    return [item for item in value.split("|") if item] if isinstance(value, str) else []


def join_text(values: list[str] | tuple[str, ...]) -> str:
    return "|".join(values)


def _numeric_boundary_value(value):
    """Converta Decimal valido sem ocultar dados invalidos do validador."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def model_to_recommendation_vehicle(vehicle: models.Vehicle) -> RecommendationVehicle:
    use_cases = split_text(vehicle.use_cases)
    brand = vehicle.brand if isinstance(vehicle.brand, str) else ""
    model = vehicle.model if isinstance(vehicle.model, str) else ""
    if brand.lower() == "renault" and "duster" in model.lower() and "suv" not in use_cases:
        use_cases.append("suv")
    metadata = price_metadata(vehicle.id)
    return RecommendationVehicle(
        id=vehicle.id,
        brand=brand,
        model=model,
        year=vehicle.year,
        price=_numeric_boundary_value(
            effective_price(vehicle.id, vehicle.price)
        ),
        fuel_efficiency_km_l=vehicle.fuel_efficiency_km_l,
        annual_maintenance_cost=_numeric_boundary_value(
            vehicle.annual_maintenance_cost
        ),
        reliability_score=vehicle.reliability_score,
        parts_availability_score=vehicle.parts_availability_score,
        depreciation_rate=vehicle.depreciation_rate,
        use_cases=tuple(use_cases),
        chronic_issues=tuple(split_text(vehicle.chronic_issues)),
        image_url=vehicle.image_url,
        category=vehicle.category,
        segment_level=vehicle.segment_level,
        comfort_score=vehicle.comfort_score,
        space_score=vehicle.space_score,
        safety_score=vehicle.safety_score,
        urban_score=vehicle.urban_score,
        road_score=vehicle.road_score,
        family_score=vehicle.family_score,
        app_score=vehicle.app_score,
        price_reference=str(metadata["label"]),
        price_reference_month=str(metadata.get("reference_month", "")),
        fipe_code=str(metadata.get("code", "")),
        fipe_model=str(metadata.get("model", "")),
        price_is_fipe=bool(metadata["is_fipe"]),
        vehicle_type=getattr(vehicle, "vehicle_type", None),
    )


def vehicle_to_response(vehicle: models.Vehicle) -> dict:
    metadata = price_metadata(vehicle.id)
    return {
        "id": vehicle.id,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "year": vehicle.year,
        "price": effective_price(vehicle.id, vehicle.price),
        "price_reference": metadata,
        "fuel_efficiency_km_l": vehicle.fuel_efficiency_km_l,
        "annual_maintenance_cost": vehicle.annual_maintenance_cost,
        "reliability_score": vehicle.reliability_score,
        "parts_availability_score": vehicle.parts_availability_score,
        "depreciation_rate": vehicle.depreciation_rate,
        "use_cases": split_text(vehicle.use_cases),
        "chronic_issues": split_text(vehicle.chronic_issues),
        "image_url": vehicle.image_url,
        "category": vehicle.category,
        "segment_level": vehicle.segment_level,
        "comfort_score": vehicle.comfort_score,
        "space_score": vehicle.space_score,
        "safety_score": vehicle.safety_score,
        "urban_score": vehicle.urban_score,
        "road_score": vehicle.road_score,
        "family_score": vehicle.family_score,
        "app_score": vehicle.app_score,
        "vehicle_type": getattr(vehicle, "vehicle_type", None),
        "parts_catalog": get_parts_catalog(vehicle.brand, vehicle.model),
    }


def motorcycle_to_response(motorcycle: models.Motorcycle, *, include_legacy: bool = False) -> dict:
    specifications = _record_value(motorcycle, "specifications")
    audit = audit_motorcycle_record(motorcycle)
    if not audit["is_valid"]:
        record = motorcycle if isinstance(motorcycle, dict) else {"id": motorcycle.id}
        _log_invalid_motorcycle(record, audit)
        raise InvalidMotorcycleRecordError(audit)

    has_abs = _record_value(specifications, "has_abs")
    eligibility = evaluate_motorcycle_eligibility(motorcycle)
    grouped_sources = list(_record_value(motorcycle, "data_sources", []) or [])
    primary_identity = next(
        (
            source for source in grouped_sources
            if _record_value(source, "data_group") == "identity" and _record_value(source, "is_primary") is True
        ),
        None,
    )
    legacy_source = _normalize_database_value(_record_value(motorcycle, "data_source"))
    canonical_identity_source = _normalize_database_value(_record_value(primary_identity, "source_type")) if primary_identity else None
    response = {
        "id": _record_value(motorcycle, "id"),
        "brand": _record_value(motorcycle, "brand"),
        "model": _record_value(motorcycle, "model"),
        "year": _record_value(motorcycle, "year"),
        "price": _record_value(motorcycle, "price"),
        "city_consumption": _record_value(motorcycle, "city_consumption"),
        "road_consumption": _record_value(motorcycle, "road_consumption"),
        "annual_maintenance_cost": _record_value(motorcycle, "annual_maintenance_cost"),
        "vehicle_type": _record_value(motorcycle, "vehicle_type"),
        "image_url": _record_value(motorcycle, "image_url"),
        "version": _record_value(motorcycle, "version"),
        "market_condition": _record_value(motorcycle, "market_condition"),
        "fuel_type": _record_value(motorcycle, "fuel_type"),
        "price_reference_date": _record_value(motorcycle, "price_reference_date"),
        "is_demonstration": bool(_record_value(motorcycle, "is_demonstration", False)),
        "record_status": "complete",
        "incomplete_reasons": [],
        "eligibility_status": eligibility["eligibility_status"],
        "eligibility_reasons": eligibility["eligibility_reasons"],
        "blocking_issues": eligibility.get("blocking_issues", []),
        "informational_issues": eligibility.get("informational_issues", []),
        "data_sources": _record_value(motorcycle, "data_sources", []),
        "derived_metrics": _record_value(motorcycle, "derived_metrics", []),
        "economic_estimates": _record_value(motorcycle, "economic_estimates", []),
        "coverage": eligibility.get("coverage", {}),
        "source_contract": {
            "canonical": "motorcycle_data_sources",
            "legacy_fields_deprecated": True,
            "canonical_precedence": bool(grouped_sources),
            "required_for_registration": sorted(REGISTRATION_REQUIRED_SOURCE_GROUPS),
            "required_for_pilot": sorted(PILOT_REQUIRED_SOURCE_GROUPS),
            "complementary": sorted(COMPLEMENTARY_SOURCE_GROUPS),
            "legacy_divergence": bool(
                legacy_source and canonical_identity_source and legacy_source != canonical_identity_source
            ),
        },
        "specifications": {
            "engine_displacement_cc": _record_value(specifications, "engine_displacement_cc"),
            "motorcycle_category": _record_value(specifications, "motorcycle_category"),
            "wet_weight_kg": _record_value(specifications, "wet_weight_kg"),
            "seat_height_mm": _record_value(specifications, "seat_height_mm"),
            "tank_capacity_l": _record_value(specifications, "tank_capacity_l"),
            "has_abs": bool(has_abs),
            "power_cv": _record_value(specifications, "power_cv"),
            "torque_nm": _record_value(specifications, "torque_nm"),
            "transmission_type": _record_value(specifications, "transmission_type"),
            "gear_count": _record_value(specifications, "gear_count"),
            "final_drive_type": _record_value(specifications, "final_drive_type"),
            "payload_capacity_kg": _record_value(specifications, "payload_capacity_kg"),
            "oil_change_interval_km": _record_value(specifications, "oil_change_interval_km"),
            "abs_channels": _record_value(specifications, "abs_channels"),
            "has_cbs": _nullable_bool(_record_value(specifications, "has_cbs")),
            "has_traction_control": _nullable_bool(_record_value(specifications, "has_traction_control")),
            "recommended_experience": None,
            "urban_score": None,
            "road_score": None,
            "passenger_comfort_score": None,
            "luggage_score": None,
        },
    }
    legacy_data = {
        "reliability_score": _record_value(motorcycle, "reliability_score"),
        "parts_availability_score": _record_value(motorcycle, "parts_availability_score"),
        "depreciation_rate": _record_value(motorcycle, "depreciation_rate"),
        "data_source": _record_value(motorcycle, "data_source"),
        "data_confidence": _record_value(motorcycle, "data_confidence"),
        "source_name": _record_value(motorcycle, "source_name"),
        "source_reference": _record_value(motorcycle, "source_reference"),
        "source_url": _record_value(motorcycle, "source_url"),
        "source_collected_at": _record_value(motorcycle, "source_collected_at"),
        "source_reference_date": _record_value(motorcycle, "source_reference_date"),
        "last_verified_at": _record_value(motorcycle, "last_verified_at"),
    }
    if include_legacy:
        response["legacy_data"] = {
            "deprecated": True,
            "removal_target_version": "1.0.0",
            "fields": legacy_data,
        }
    return response


LEGACY_SPEC_METRICS = {
    "urban_score": MotorcycleDerivedMetricName.URBAN_SCORE.value,
    "road_score": MotorcycleDerivedMetricName.ROAD_SCORE.value,
    "passenger_comfort_score": MotorcycleDerivedMetricName.PASSENGER_COMFORT_SCORE.value,
    "luggage_score": MotorcycleDerivedMetricName.LUGGAGE_SCORE.value,
    "recommended_experience": MotorcycleDerivedMetricName.RECOMMENDED_EXPERIENCE.value,
}
LEGACY_ROOT_METRICS = {
    "reliability_score": MotorcycleDerivedMetricName.RELIABILITY_SCORE.value,
    "parts_availability_score": MotorcycleDerivedMetricName.PARTS_AVAILABILITY_SCORE.value,
}


def _legacy_metric_metadata(data_source) -> tuple[str, str]:
    source = _normalize_database_value(data_source)
    if source == "demonstration":
        return MotorcycleMetricStatus.DEMONSTRATION.value, "demonstration-v0"
    return MotorcycleMetricStatus.UNVALIDATED.value, "legacy-unvalidated-v0"


def _upsert_legacy_metric(
    db: Session,
    *,
    motorcycle_id: int,
    metric_name: str,
    value,
    status: str,
    method_version: str,
) -> None:
    if value is None:
        return
    existing = db.query(models.MotorcycleDerivedMetric).filter_by(
        motorcycle_id=motorcycle_id,
        metric_name=metric_name,
        method_version=method_version,
    ).one_or_none()
    is_text = metric_name == MotorcycleDerivedMetricName.RECOMMENDED_EXPERIENCE.value
    values = {
        "metric_value": None if is_text else float(value),
        "metric_text_value": _normalize_database_value(value) if is_text else None,
        "metric_status": status,
        "notes": "Compatibilidade legada; sem efeito decisório.",
    }
    if existing is None:
        db.add(
            models.MotorcycleDerivedMetric(
                motorcycle_id=motorcycle_id,
                metric_name=metric_name,
                method_version=method_version,
                **values,
            )
        )
    else:
        for field, field_value in values.items():
            setattr(existing, field, field_value)


def create_motorcycle(db: Session, payload, *, commit: bool = True) -> dict:
    common_data = payload.model_dump(
        exclude={"specifications", "data_sources", "derived_metrics", "economic_estimates"},
        mode="python",
    )
    legacy_root_values = {field: common_data.pop(field) for field in LEGACY_ROOT_METRICS}
    specification_data = payload.specifications.model_dump(mode="python")
    legacy_spec_values = {field: specification_data.pop(field) for field in LEGACY_SPEC_METRICS}
    common_data = {field: _normalize_database_value(value) for field, value in common_data.items()}
    if common_data.get("data_source") == "demonstration":
        common_data["is_demonstration"] = True
    specification_data = {field: _normalize_database_value(value) for field, value in specification_data.items()}
    motorcycle = models.Motorcycle(
        **common_data,
        reliability_score=None,
        parts_availability_score=None,
        vehicle_type="motorcycle",
    )
    motorcycle.objective_specifications = models.MotorcycleObjectiveSpecification(**specification_data)

    primary_groups = [source.data_group.value for source in payload.data_sources if source.is_primary]
    if len(primary_groups) != len(set(primary_groups)):
        raise ValueError("A criação aceita somente uma fonte principal por grupo.")
    for source in payload.data_sources:
        source_data = {
            field: _normalize_database_value(value)
            for field, value in source.model_dump(mode="python").items()
        }
        motorcycle.data_sources.append(models.MotorcycleDataSource(**source_data))
    for metric in payload.derived_metrics:
        if metric.source_group_id is not None:
            raise ValueError("Cadastre a fonte antes de vinculá-la a uma métrica derivada.")
        metric_data = {
            field: _normalize_database_value(value)
            for field, value in metric.model_dump(mode="python").items()
        }
        motorcycle.derived_metrics.append(models.MotorcycleDerivedMetric(**metric_data))
    for estimate in payload.economic_estimates:
        if estimate.source_group_id is not None:
            raise ValueError("Cadastre a fonte antes de vinculá-la a uma estimativa econômica.")
        estimate_data = {
            field: _normalize_database_value(value)
            for field, value in estimate.model_dump(mode="python").items()
        }
        motorcycle.economic_estimates.append(models.MotorcycleEconomicEstimate(**estimate_data))

    try:
        db.add(motorcycle)
        db.flush()
        motorcycle_id = motorcycle.id
        status, method_version = _legacy_metric_metadata(payload.data_source)
        for field, metric_name in LEGACY_ROOT_METRICS.items():
            _upsert_legacy_metric(
                db,
                motorcycle_id=motorcycle_id,
                metric_name=metric_name,
                value=legacy_root_values[field],
                status=status,
                method_version=method_version,
            )
        for field, metric_name in LEGACY_SPEC_METRICS.items():
            _upsert_legacy_metric(
                db,
                motorcycle_id=motorcycle_id,
                metric_name=metric_name,
                value=legacy_spec_values[field],
                status=status,
                method_version=method_version,
            )
        db.flush()
        persisted = get_motorcycle_record(db, motorcycle_id)
        motorcycle_to_response(persisted)
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    persisted = get_motorcycle_record(db, motorcycle_id)
    if persisted is None:
        raise RuntimeError("A motocicleta criada não pôde ser relida.")
    return persisted


def update_motorcycle(db: Session, motorcycle: dict, payload) -> dict:
    data = payload.model_dump(exclude_unset=True, exclude={"specifications"}, mode="python")
    specification_values: dict | None = None
    if payload.specifications is not None:
        specification_values = payload.specifications.model_dump(exclude_unset=True, mode="python")

    legacy_root_values = {field: data[field] for field in LEGACY_ROOT_METRICS if field in data}
    legacy_spec_values = {}
    if specification_values is not None:
        legacy_spec_values = {
            field: specification_values.pop(field)
            for field in list(specification_values)
            if field in LEGACY_SPEC_METRICS
        }

    candidate = {**motorcycle, **data}
    current_specifications = motorcycle.get("specifications")
    if specification_values is not None:
        candidate["specifications"] = {
            **(current_specifications or {}),
            **specification_values,
        }

    audit = audit_motorcycle_record(candidate)
    if not audit["is_valid"]:
        _log_invalid_motorcycle(candidate, audit)
        db.rollback()
        raise InvalidMotorcycleRecordError(audit)

    try:
        if data:
            normalized_data = {field: _normalize_database_value(value) for field, value in data.items()}
            db.execute(
                update(models.Motorcycle)
                .where(models.Motorcycle.id == motorcycle["id"])
                .values(**normalized_data)
            )
        if specification_values:
            normalized_specifications = {
                field: _normalize_database_value(value)
                for field, value in specification_values.items()
            }
            objective_exists = db.execute(
                text("SELECT id FROM motorcycle_objective_specifications WHERE motorcycle_id = :motorcycle_id"),
                {"motorcycle_id": motorcycle["id"]},
            ).first()
            if objective_exists is None:
                db.execute(
                    insert(models.MotorcycleObjectiveSpecification).values(
                        motorcycle_id=motorcycle["id"],
                        **normalized_specifications,
                    )
                )
            else:
                db.execute(
                    update(models.MotorcycleObjectiveSpecification)
                    .where(models.MotorcycleObjectiveSpecification.motorcycle_id == motorcycle["id"])
                    .values(**normalized_specifications)
                )
        status, method_version = _legacy_metric_metadata(candidate.get("data_source"))
        for field, metric_name in LEGACY_ROOT_METRICS.items():
            if field in legacy_root_values:
                _upsert_legacy_metric(
                    db,
                    motorcycle_id=motorcycle["id"],
                    metric_name=metric_name,
                    value=legacy_root_values[field],
                    status=status,
                    method_version=method_version,
                )
        for field, metric_name in LEGACY_SPEC_METRICS.items():
            if field in legacy_spec_values:
                _upsert_legacy_metric(
                    db,
                    motorcycle_id=motorcycle["id"],
                    metric_name=metric_name,
                    value=legacy_spec_values[field],
                    status=status,
                    method_version=method_version,
                )
        db.flush()
        persisted = get_motorcycle_record(db, motorcycle["id"])
        persisted_audit = audit_motorcycle_record(persisted)
        if not persisted_audit["is_valid"]:
            raise InvalidMotorcycleRecordError(persisted_audit)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_motorcycle_record(db, motorcycle["id"])


def delete_motorcycle_record(db: Session, motorcycle_id: int) -> bool:
    exists = db.execute(
        text("SELECT id FROM motorcycles WHERE id = :motorcycle_id"),
        {"motorcycle_id": motorcycle_id},
    ).first()
    if exists is None:
        return False
    try:
        db.execute(delete(models.Motorcycle).where(models.Motorcycle.id == motorcycle_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def list_motorcycle_sources(db: Session, motorcycle_id: int) -> list[dict]:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    return _load_motorcycle_sources(db, motorcycle_id)


def get_motorcycle_source_record(db: Session, motorcycle_id: int, source_id: int) -> dict | None:
    row = db.execute(
        text(f"{MOTORCYCLE_SOURCE_SELECT} WHERE motorcycle_id = :motorcycle_id AND id = :source_id"),
        {"motorcycle_id": motorcycle_id, "source_id": source_id},
    ).mappings().first()
    if row is None:
        return None
    source_data = dict(row)
    source_data["is_primary"] = bool(source_data["is_primary"])
    return MotorcycleDataSourceRead.model_validate(source_data).model_dump(mode="python")


def _ensure_single_primary_source(
    db: Session,
    *,
    motorcycle_id: int,
    data_group: str,
    is_primary: bool,
    excluded_source_id: int | None = None,
) -> None:
    if not is_primary:
        return
    query = (
        db.query(models.MotorcycleDataSource)
        .filter_by(motorcycle_id=motorcycle_id, data_group=data_group, is_primary=True)
    )
    if excluded_source_id is not None:
        query = query.filter(models.MotorcycleDataSource.id != excluded_source_id)
    if query.first() is not None:
        raise ValueError("Já existe uma fonte principal para este grupo de dados.")


def create_motorcycle_source(db: Session, motorcycle_id: int, payload) -> dict:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    data = {
        field: _normalize_database_value(value)
        for field, value in payload.model_dump(mode="python").items()
    }
    _ensure_single_primary_source(
        db,
        motorcycle_id=motorcycle_id,
        data_group=data["data_group"],
        is_primary=data["is_primary"],
    )
    source = models.MotorcycleDataSource(motorcycle_id=motorcycle_id, **data)
    try:
        db.add(source)
        db.flush()
        source_id = source.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    persisted = get_motorcycle_source_record(db, motorcycle_id, source_id)
    if persisted is None:
        raise RuntimeError("A fonte criada não pôde ser relida.")
    return persisted


def update_motorcycle_source(db: Session, motorcycle_id: int, source_id: int, payload) -> dict | None:
    current = get_motorcycle_source_record(db, motorcycle_id, source_id)
    if current is None:
        return None
    changes = payload.model_dump(exclude_unset=True, mode="python")
    candidate_values = {
        field: current.get(field)
        for field in MotorcycleDataSourceBase.model_fields
    }
    candidate_values.update(changes)
    candidate = MotorcycleDataSourceBase.model_validate(candidate_values)
    normalized = {
        field: _normalize_database_value(value)
        for field, value in candidate.model_dump(mode="python").items()
    }
    _ensure_single_primary_source(
        db,
        motorcycle_id=motorcycle_id,
        data_group=normalized["data_group"],
        is_primary=normalized["is_primary"],
        excluded_source_id=source_id,
    )
    try:
        db.execute(
            update(models.MotorcycleDataSource)
            .where(models.MotorcycleDataSource.id == source_id)
            .values(**normalized)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_motorcycle_source_record(db, motorcycle_id, source_id)


def set_motorcycle_primary_source(db: Session, motorcycle_id: int, source_id: int) -> dict | None:
    source = get_motorcycle_source_record(db, motorcycle_id, source_id)
    if source is None:
        return None
    try:
        db.execute(
            update(models.MotorcycleDataSource)
            .where(
                models.MotorcycleDataSource.motorcycle_id == motorcycle_id,
                models.MotorcycleDataSource.data_group == source["data_group"],
            )
            .values(is_primary=False)
        )
        db.execute(
            update(models.MotorcycleDataSource)
            .where(models.MotorcycleDataSource.id == source_id)
            .values(is_primary=True)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_motorcycle_source_record(db, motorcycle_id, source_id)


def delete_motorcycle_source(db: Session, motorcycle_id: int, source_id: int) -> bool:
    if get_motorcycle_source_record(db, motorcycle_id, source_id) is None:
        return False
    try:
        db.execute(
            delete(models.MotorcycleDataSource).where(
                models.MotorcycleDataSource.id == source_id,
                models.MotorcycleDataSource.motorcycle_id == motorcycle_id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def list_motorcycle_derived_metrics(db: Session, motorcycle_id: int) -> list[dict]:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    return _load_motorcycle_metrics(db, motorcycle_id)


def create_motorcycle_derived_metric(db: Session, motorcycle_id: int, payload) -> dict:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    data = {
        field: _normalize_database_value(value)
        for field, value in payload.model_dump(mode="python").items()
    }
    if data.get("source_group_id") is not None:
        source = get_motorcycle_source_record(db, motorcycle_id, data["source_group_id"])
        if source is None:
            raise ValueError("A fonte vinculada não pertence à motocicleta informada.")
    duplicate = db.query(models.MotorcycleDerivedMetric).filter_by(
        motorcycle_id=motorcycle_id,
        metric_name=data["metric_name"],
        method_version=data["method_version"],
    ).first()
    if duplicate is not None:
        raise ValueError("Já existe esta métrica para a mesma motocicleta e versão de método.")
    metric = models.MotorcycleDerivedMetric(motorcycle_id=motorcycle_id, **data)
    try:
        db.add(metric)
        db.flush()
        metric_id = metric.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    metrics = _load_motorcycle_metrics(db, motorcycle_id)
    persisted = next((item for item in metrics if item["id"] == metric_id), None)
    if persisted is None:
        raise RuntimeError("A métrica criada não pôde ser relida.")
    return persisted


def list_motorcycle_economic_estimates(db: Session, motorcycle_id: int) -> list[dict]:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    return _load_motorcycle_estimates(db, motorcycle_id)


def create_motorcycle_economic_estimate(db: Session, motorcycle_id: int, payload) -> dict:
    if get_motorcycle_record(db, motorcycle_id) is None:
        raise LookupError("Motocicleta não encontrada")
    data = {
        field: _normalize_database_value(value)
        for field, value in payload.model_dump(mode="python").items()
    }
    if data.get("source_group_id") is not None:
        source = get_motorcycle_source_record(db, motorcycle_id, data["source_group_id"])
        if source is None:
            raise ValueError("A fonte vinculada não pertence à motocicleta informada.")
    duplicate = db.query(models.MotorcycleEconomicEstimate).filter_by(
        motorcycle_id=motorcycle_id,
        estimate_name=data["estimate_name"],
        method_version=data["method_version"],
        reference_date=data["reference_date"],
    ).first()
    if duplicate is not None:
        raise ValueError("Já existe esta estimativa para a mesma motocicleta, método e referência.")
    estimate = models.MotorcycleEconomicEstimate(motorcycle_id=motorcycle_id, **data)
    try:
        db.add(estimate)
        db.flush()
        estimate_id = estimate.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    estimates = _load_motorcycle_estimates(db, motorcycle_id)
    persisted = next((item for item in estimates if item["id"] == estimate_id), None)
    if persisted is None:
        raise RuntimeError("A estimativa criada não pôde ser relida.")
    return persisted


def create_vehicle(db: Session, payload: VehicleCreate) -> models.Vehicle:
    vehicle = models.Vehicle(
        brand=payload.brand,
        model=payload.model,
        year=payload.year,
        price=payload.price,
        fuel_efficiency_km_l=payload.fuel_efficiency_km_l,
        annual_maintenance_cost=payload.annual_maintenance_cost,
        reliability_score=payload.reliability_score,
        parts_availability_score=payload.parts_availability_score,
        depreciation_rate=payload.depreciation_rate,
        use_cases=join_text(payload.use_cases),
        chronic_issues=join_text(payload.chronic_issues),
        image_url=payload.image_url,
        category=payload.category,
        segment_level=payload.segment_level,
        comfort_score=payload.comfort_score,
        space_score=payload.space_score,
        safety_score=payload.safety_score,
        urban_score=payload.urban_score,
        road_score=payload.road_score,
        family_score=payload.family_score,
        app_score=payload.app_score,
        vehicle_type=VehicleType.CAR.value,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


def ensure_seed_data(db: Session) -> None:
    demo_user = db.query(models.User).filter(models.User.email == "usuario@sigra.local").first()
    legacy_user = db.get(models.User, 1)
    if demo_user is None and legacy_user is not None:
        legacy_user.name = "Usuário Demonstração"
        legacy_user.email = "usuario@sigra.local"
    elif demo_user is None:
        db.add(models.User(id=1, name="Usuário Demonstração", email="usuario@sigra.local"))

    existing_vehicles = {vehicle.id: vehicle for vehicle in car_query(db).all()}
    for vehicle in SAMPLE_VEHICLES:
        existing_vehicle = existing_vehicles.get(vehicle.id)
        if existing_vehicle is not None:
            existing_vehicle.brand = vehicle.brand
            existing_vehicle.model = vehicle.model
            existing_vehicle.year = vehicle.year
            existing_vehicle.price = vehicle.price
            existing_vehicle.fuel_efficiency_km_l = vehicle.fuel_efficiency_km_l
            existing_vehicle.annual_maintenance_cost = vehicle.annual_maintenance_cost
            existing_vehicle.reliability_score = vehicle.reliability_score
            existing_vehicle.parts_availability_score = vehicle.parts_availability_score
            existing_vehicle.depreciation_rate = vehicle.depreciation_rate
            existing_vehicle.use_cases = join_text(vehicle.use_cases)
            existing_vehicle.chronic_issues = join_text(vehicle.chronic_issues)
            existing_vehicle.image_url = vehicle.image_url
            existing_vehicle.category = vehicle.category
            existing_vehicle.segment_level = vehicle.segment_level
            existing_vehicle.comfort_score = vehicle.comfort_score
            existing_vehicle.space_score = vehicle.space_score
            existing_vehicle.safety_score = vehicle.safety_score
            existing_vehicle.urban_score = vehicle.urban_score
            existing_vehicle.road_score = vehicle.road_score
            existing_vehicle.family_score = vehicle.family_score
            existing_vehicle.app_score = vehicle.app_score
            existing_vehicle.vehicle_type = VehicleType.CAR.value
            continue
        db.add(
            models.Vehicle(
                id=vehicle.id,
                brand=vehicle.brand,
                model=vehicle.model,
                year=vehicle.year,
                price=vehicle.price,
                fuel_efficiency_km_l=vehicle.fuel_efficiency_km_l,
                annual_maintenance_cost=vehicle.annual_maintenance_cost,
                reliability_score=vehicle.reliability_score,
                parts_availability_score=vehicle.parts_availability_score,
                depreciation_rate=vehicle.depreciation_rate,
                use_cases=join_text(vehicle.use_cases),
                chronic_issues=join_text(vehicle.chronic_issues),
                image_url=vehicle.image_url,
                category=vehicle.category,
                segment_level=vehicle.segment_level,
                comfort_score=vehicle.comfort_score,
                space_score=vehicle.space_score,
                safety_score=vehicle.safety_score,
                urban_score=vehicle.urban_score,
                road_score=vehicle.road_score,
                family_score=vehicle.family_score,
                app_score=vehicle.app_score,
                vehicle_type=VehicleType.CAR.value,
            )
        )
    db.commit()
    ensure_parts_seed_data(db)
    ensure_history_seed_data(db)


def ensure_parts_seed_data(db: Session) -> None:
    if db.query(models.Part).count() > 0:
        return

    parts = [
        (1, "Pastilha de freio", "freio", "Item de desgaste do sistema de freio."),
        (2, "Disco de freio", "freio", "Disco dianteiro para frenagem."),
        (3, "Amortecedor dianteiro", "suspensao", "Componente principal da suspensao dianteira."),
        (4, "Bandeja de suspensao", "suspensao", "Braco/bandeja de suspensao."),
        (5, "Bieleta", "suspensao", "Ligacao da barra estabilizadora."),
        (6, "Kit embreagem", "embreagem", "Kit de embreagem completo."),
        (7, "Correia dentada", "correias", "Correia de sincronismo do motor."),
        (8, "Bomba d'agua", "arrefecimento", "Bomba do sistema de arrefecimento."),
        (9, "Radiador", "arrefecimento", "Radiador do motor."),
        (10, "Vela de ignicao", "motor", "Jogo de velas."),
        (11, "Bobina", "eletrica", "Bobina de ignicao."),
        (12, "Filtro de oleo", "filtros", "Filtro para troca de oleo."),
        (13, "Filtro de ar", "filtros", "Filtro de admissao de ar."),
    ]
    db.add_all(
        [
            models.Part(id=id_, name=name, category=category, description=description, original_code=f"SIGRA-{id_:03d}", alternative_codes=f"ALT-{id_:03d}|EQ-{id_:03d}")
            for id_, name, category, description in parts
        ]
    )
    suppliers = [
        (1, "AutoPecas Centro", "https://example.com/autocentro", "Sao Paulo", "SP", "autopecas local", 82),
        (2, "Peças Online Brasil", "https://example.com/pecasonline", "Curitiba", "PR", "loja online", 86),
        (3, "Mercado Auto Demo", "https://example.com/marketauto", "Rio de Janeiro", "RJ", "marketplace", 74),
        (4, "Concessionaria Oficial Demo", "https://example.com/concessionaria", "Sao Paulo", "SP", "concessionaria", 90),
        (5, "Distribuidora Nacional", "https://example.com/distribuidora", "Belo Horizonte", "MG", "distribuidor", 84),
        (6, "Oficina Parceira SIGRA", "https://example.com/oficina", "Campinas", "SP", "oficina parceira", 78),
    ]
    db.add_all(
        [
            models.Supplier(id=id_, name=name, website=website, city=city, state=state, type=type_, reliability_score=score)
            for id_, name, website, city, state, type_, score in suppliers
        ]
    )
    db.flush()

    scenarios = {
        1: {"parts": [1, 2, 3, 5, 7, 10, 12, 13], "factor": 1.00, "suppliers": [1, 2, 3, 5], "variation": {3: 2.2, 7: 1.9}},
        6: {"parts": [1, 2, 3, 5, 10, 12, 13], "factor": 1.03, "suppliers": [1, 2, 3, 5], "variation": {}},
        10: {"parts": [1, 2, 3, 5, 7, 8, 12, 13], "factor": 1.10, "suppliers": [2, 4, 5], "variation": {8: 1.8}},
        13: {"parts": [1, 2, 3, 4, 5, 10, 12, 13], "factor": 1.15, "suppliers": [1, 2, 4, 5], "variation": {3: 1.7}},
        9: {"parts": [1, 2, 3, 4, 8, 9, 10, 12], "factor": 1.45, "suppliers": [2, 4, 5], "variation": {9: 2.0}},
        22: {"parts": [1, 2, 5, 7, 10, 12, 13], "factor": 0.82, "suppliers": [1, 2, 3, 5, 6], "variation": {}},
        29: {"parts": [1, 2, 3, 5, 10, 12, 13], "factor": 1.12, "suppliers": [2, 3, 4], "variation": {3: 1.9}},
        17: {"parts": [1, 2, 3, 4, 5, 6, 7, 10, 12, 13], "factor": 0.88, "suppliers": [1, 2, 3, 5, 6], "variation": {}},
        26: {"parts": [1, 2, 3, 5, 7, 10, 12, 13], "factor": 0.95, "suppliers": [1, 2, 3, 5], "variation": {}},
        33: {"parts": [1, 2, 3, 5, 7, 10, 12, 13], "factor": 1.08, "suppliers": [2, 3, 4], "variation": {3: 2.1, 11: 1.9}},
    }
    base_prices = {1: 180, 2: 260, 3: 420, 4: 360, 5: 95, 6: 850, 7: 140, 8: 220, 9: 520, 10: 120, 11: 250, 12: 45, 13: 55}
    price_id = 1
    for vehicle_id, scenario in scenarios.items():
        for part_id in scenario["parts"]:
            for index, supplier_id in enumerate(scenario["suppliers"][:4]):
                multiplier = 0.88 + (index * 0.18)
                if scenario["variation"].get(part_id) and index == len(scenario["suppliers"][:4]) - 1:
                    multiplier = scenario["variation"][part_id]
                db.add(
                    models.PartPrice(
                        id=price_id,
                        part_id=part_id,
                        supplier_id=supplier_id,
                        vehicle_id=vehicle_id,
                        price=round(base_prices[part_id] * scenario["factor"] * multiplier, 2),
                        brand="DemoParts",
                        condition="novo" if supplier_id != 4 else "original",
                        url=f"https://example.com/parts/{vehicle_id}/{part_id}/{supplier_id}",
                        source="demonstrativo",
                        notes="Preço demonstrativo para MVP acadêmico.",
                    )
                )
                price_id += 1

    compatibility_rows = [
        (1, 1, 2, "mesma plataforma", "Compartilha família de peças Chevrolet.", "alta"),
        (1, 12, 17, "peca equivalente", "Filtro com equivalentes amplos no mercado.", "alta"),
        (6, 1, 7, "mesma peca", "Compartilha itens com HB20S.", "alta"),
        (10, 12, 11, "mesma peca", "Compatibilidade Toyota em filtros.", "media"),
        (13, 5, 14, "peca equivalente", "Componentes equivalentes Honda Fit/City.", "media"),
        (9, 1, 14, "compatibilidade parcial", "Algumas peças de freio requerem validação.", "baixa"),
        (22, 12, 23, "mesma peca", "Filtros compartilhados com Uno.", "alta"),
        (29, 13, 30, "mesma plataforma", "Compatibilidade March/Versa em itens simples.", "media"),
        (17, 1, 20, "mesma peca", "Linha Volkswagen popular com alta reposição.", "alta"),
        (17, 5, 18, "peca equivalente", "Itens de suspensão com equivalentes.", "media"),
        (26, 12, 27, "mesma peca", "Sandero/Logan compartilham filtros.", "alta"),
        (33, 12, 34, "mesma peca", "Compatibilidade parcial na linha Ford.", "media"),
    ]
    db.add_all(
        [
            models.VehiclePartCompatibility(
                vehicle_id=vehicle_id,
                part_id=part_id,
                compatible_vehicle_id=compatible_vehicle_id,
                compatibility_type=compatibility_type,
                notes=notes,
                confidence_level=confidence,
            )
            for vehicle_id, part_id, compatible_vehicle_id, compatibility_type, notes, confidence in compatibility_rows
        ]
    )
    db.commit()


def ensure_history_seed_data(db: Session) -> None:
    if db.query(models.UserVehicle).count() > 0:
        return

    demo_vehicles = [
        models.UserVehicle(
            id=1,
            user_id=1,
            vehicle_id=13,
            year_model=2017,
            current_km=96000,
            purchase_km=52000,
            purchase_date=date(2022, 2, 10),
            main_usage="familia",
            notes="Honda Fit usado para família e cidade.",
        ),
        models.UserVehicle(
            id=2,
            user_id=1,
            vehicle_id=1,
            year_model=2021,
            current_km=72000,
            purchase_km=18000,
            purchase_date=date(2023, 1, 15),
            main_usage="app",
            notes="Onix com uso urbano intenso.",
        ),
        models.UserVehicle(
            id=3,
            user_id=1,
            vehicle_id=9,
            year_model=2018,
            current_km=88000,
            purchase_km=60000,
            purchase_date=date(2021, 7, 3),
            main_usage="estrada",
            notes="Corolla usado em estrada.",
        ),
        models.UserVehicle(
            id=4,
            user_id=1,
            vehicle_id=22,
            year_model=2021,
            current_km=41000,
            purchase_km=12000,
            purchase_date=date(2024, 3, 20),
            main_usage="cidade",
            notes="Mobi economico para deslocamentos curtos.",
        ),
        models.UserVehicle(
            id=5,
            user_id=1,
            vehicle_id=10,
            year_model=2018,
            current_km=83000,
            purchase_km=50000,
            purchase_date=date(2022, 8, 12),
            main_usage="trabalho",
            notes="Etios com foco em confiabilidade.",
        ),
    ]
    db.add_all(demo_vehicles)
    db.flush()

    db.add_all(
        [
            models.VehicleReport(user_vehicle_id=1, vehicle_id=13, problem_category="suspensao", description="Barulho na suspensao dianteira.", occurrence_km=98000, repair_cost=1200, severity="media", occurrence_date=date(2025, 4, 8), resolved=True, notes="Troca de buchas e bieletas."),
            models.VehicleReport(user_vehicle_id=1, vehicle_id=13, problem_category="suspensao", description="Amortecedor com desgaste.", occurrence_km=104000, repair_cost=1800, severity="media", occurrence_date=date(2025, 9, 18), resolved=True, notes="Relato demonstrativo para alerta preventivo."),
            models.VehicleReport(user_vehicle_id=2, vehicle_id=1, problem_category="consumo", description="Consumo urbano abaixo do esperado em uso de aplicativo.", occurrence_km=69000, repair_cost=450, severity="baixa", occurrence_date=date(2026, 1, 12), resolved=True, notes="Limpeza de bicos e revisão."),
            models.VehicleReport(user_vehicle_id=2, vehicle_id=1, problem_category="motor", description="Atraso na troca de óleo gerou alerta de manutenção.", occurrence_km=72000, repair_cost=900, severity="media", occurrence_date=date(2026, 3, 2), resolved=False, notes="Motor turbo exige manutenção preventiva."),
            models.VehicleReport(user_vehicle_id=3, vehicle_id=9, problem_category="seguro", description="Seguro acima da média regional.", occurrence_km=84000, repair_cost=0, severity="baixa", occurrence_date=date(2025, 11, 20), resolved=True, notes="Custo alto, mas baixa frequência de problema mecânico."),
            models.VehicleReport(user_vehicle_id=3, vehicle_id=9, problem_category="freio", description="Troca preventiva de pastilhas e discos.", occurrence_km=90000, repair_cost=2100, severity="media", occurrence_date=date(2026, 2, 14), resolved=True, notes="Manutenção mais cara que compactos."),
            models.VehicleReport(user_vehicle_id=4, vehicle_id=22, problem_category="acabamento", description="Acabamento interno simples e ruido em painel.", occurrence_km=39000, repair_cost=250, severity="baixa", occurrence_date=date(2025, 12, 1), resolved=False, notes="Baixo custo, menor conforto."),
            models.VehicleReport(user_vehicle_id=5, vehicle_id=10, problem_category="acabamento", description="Acabamento simples, sem falha mecanica relevante.", occurrence_km=79000, repair_cost=150, severity="baixa", occurrence_date=date(2025, 10, 6), resolved=True, notes="Boa confiabilidade geral."),
        ]
    )
    db.add_all(
        [
            models.FuelConsumptionReport(user_vehicle_id=1, vehicle_id=13, km_per_liter=11.8, usage_type="urbano", fuel_type="flex", notes="Cidade com ar ligado."),
            models.FuelConsumptionReport(user_vehicle_id=1, vehicle_id=13, km_per_liter=13.4, usage_type="estrada", fuel_type="flex", notes="Viagem em velocidade constante."),
            models.FuelConsumptionReport(user_vehicle_id=2, vehicle_id=1, km_per_liter=9.4, usage_type="urbano", fuel_type="flex", notes="Uso intenso em aplicativo."),
            models.FuelConsumptionReport(user_vehicle_id=2, vehicle_id=1, km_per_liter=10.2, usage_type="urbano", fuel_type="gasolina", notes="Transito pesado."),
            models.FuelConsumptionReport(user_vehicle_id=3, vehicle_id=9, km_per_liter=12.2, usage_type="estrada", fuel_type="flex", notes="Consumo real bom em estrada."),
            models.FuelConsumptionReport(user_vehicle_id=4, vehicle_id=22, km_per_liter=12.9, usage_type="urbano", fuel_type="flex", notes="Economico, mas pouco espaco."),
            models.FuelConsumptionReport(user_vehicle_id=5, vehicle_id=10, km_per_liter=13.5, usage_type="urbano", fuel_type="flex", notes="Consumo real acima do esperado."),
        ]
    )
    db.commit()


def create_user(db: Session, payload: UserCreate) -> models.User:
    user = models.User(name=payload.name, email=payload.email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_expense(db: Session, payload: ExpenseCreate) -> models.Expense:
    expense = models.Expense(**payload.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def create_maintenance(db: Session, payload: MaintenanceCreate) -> models.Maintenance:
    maintenance = models.Maintenance(**payload.model_dump())
    db.add(maintenance)
    db.commit()
    db.refresh(maintenance)
    return maintenance


def user_vehicle_to_response(item: models.UserVehicle) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "vehicle_id": item.vehicle_id,
        "year_model": item.year_model,
        "current_km": item.current_km,
        "purchase_km": item.purchase_km,
        "purchase_date": item.purchase_date,
        "main_usage": item.main_usage,
        "notes": item.notes,
        "vehicle": vehicle_to_response(item.vehicle) if item.vehicle else None,
    }


def create_user_vehicle(db: Session, payload: UserVehicleCreate) -> models.UserVehicle:
    item = models.UserVehicle(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_user_vehicle(db: Session, item: models.UserVehicle, payload: UserVehicleUpdate) -> models.UserVehicle:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def create_vehicle_report(db: Session, payload: VehicleReportCreate) -> models.VehicleReport:
    user_vehicle = db.get(models.UserVehicle, payload.user_vehicle_id)
    report = models.VehicleReport(**payload.model_dump(), vehicle_id=user_vehicle.vehicle_id)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def create_consumption_report(db: Session, payload: FuelConsumptionReportCreate) -> models.FuelConsumptionReport:
    user_vehicle = db.get(models.UserVehicle, payload.user_vehicle_id)
    report = models.FuelConsumptionReport(**payload.model_dump(), vehicle_id=user_vehicle.vehicle_id)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
