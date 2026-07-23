import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from validate_motorcycle_pilot_data import (
    _parse_boolean,
    _parse_number,
    validate_pilot_file,
    validate_record_consistency,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"


def _optional_number(value, cast=float):
    if value == "":
        return None
    return cast(_parse_number(value))


def _boolean(value):
    return _parse_boolean(value)


def _build_payload(rows):
    first = rows[0]
    sources = [
        {
            "data_group": row["data_group"],
            "source_type": row["source_type"],
            "source_name": row["source_name"],
            "source_url": row["source_url"] or None,
            "source_reference": row["source_reference"] or None,
            "confidence": _parse_number(row["confidence"]),
            "collected_at": row["collected_at"],
            "reference_date": row["reference_date"],
            "is_primary": _boolean(row["is_primary"]),
            "methodology_notes": row["notes"] or None,
        }
        for row in rows
    ]
    return {
        "brand": first["brand"],
        "model": first["model"],
        "version": first["version"],
        "year": int(first["year"]),
        "price": _parse_number(first["price_brl"]),
        "price_reference_date": first["price_reference_date"],
        "market_condition": first["market_condition"],
        "fuel_type": first["fuel_type"],
        "city_consumption": _parse_number(first["city_consumption_km_l"]),
        "road_consumption": _parse_number(first["road_consumption_km_l"]),
        "annual_maintenance_cost": _optional_number(first["annual_maintenance_cost_brl"]),
        "data_sources": sources,
        "derived_metrics": [],
        "economic_estimates": [],
        "specifications": {
            "engine_displacement_cc": _parse_number(first["engine_displacement_cc"]),
            "motorcycle_category": first["category"],
            "power_cv": _parse_number(first["power_cv"]),
            "torque_nm": _parse_number(first["torque_nm"]),
            "wet_weight_kg": _parse_number(first["wet_weight_kg"]),
            "seat_height_mm": _parse_number(first["seat_height_mm"]),
            "tank_capacity_l": _parse_number(first["tank_capacity_l"]),
            "transmission_type": first["transmission_type"],
            "gear_count": int(first["gear_count"]),
            "final_drive_type": first["final_drive_type"],
            "has_abs": _boolean(first["has_abs"]),
            "has_cbs": _boolean(first["has_cbs"]),
            "has_traction_control": _boolean(first["has_traction_control"]),
            "oil_change_interval_km": _optional_number(first["oil_change_interval_km"], int),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Importa coleta piloto validada de motocicletas.")
    parser.add_argument("file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-import", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.confirm_import:
        parser.error("A persistência exige --confirm-import; use --dry-run para apenas inspecionar.")

    report, rows = validate_pilot_file(args.file)
    consistency = validate_record_consistency(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["record_key"]].append(row)
    summary = {
        "mode": "dry-run" if args.dry_run else "import",
        "would_create": len(grouped),
        "sources": len(rows),
        "errors": report["errors"],
        "warnings": report["warnings"],
        "record_consistency": consistency,
        "database_modified": False,
    }
    if not report["valid"] or consistency["records_with_inconsistency"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.database import SessionLocal, create_database
    from app.models import Motorcycle
    from app.repository import create_motorcycle
    from app.schemas import MotorcycleCreate

    create_database()
    created = 0
    with SessionLocal() as db:
        try:
            for record_rows in grouped.values():
                payload = MotorcycleCreate.model_validate(_build_payload(record_rows))
                duplicate = db.query(Motorcycle.id).filter_by(
                    brand=payload.brand,
                    model=payload.model,
                    version=payload.version,
                    year=payload.year,
                    market_condition=payload.market_condition.value,
                ).first()
                if duplicate is not None:
                    raise ValueError(f"Motocicleta duplicada: {payload.brand} {payload.model} {payload.version} {payload.year}.")
                create_motorcycle(db, payload, commit=False)
                created += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
    summary.update({"created": created, "database_modified": True})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
