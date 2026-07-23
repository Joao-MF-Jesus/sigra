import argparse
import csv
import json
import math
import sys
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.motorcycle_domain import (  # noqa: E402
    COMPLEMENTARY_SOURCE_GROUPS,
    PILOT_REQUIRED_SOURCE_GROUPS,
)


REQUIRED_COLUMNS = {
    "record_key", "brand", "model", "version", "year", "category",
    "engine_displacement_cc", "market_condition", "price_brl",
    "price_reference_date", "power_cv", "torque_nm", "wet_weight_kg",
    "seat_height_mm", "tank_capacity_l", "city_consumption_km_l",
    "road_consumption_km_l", "annual_maintenance_cost_brl",
    "fuel_type", "transmission_type", "gear_count", "final_drive_type", "has_abs",
    "has_cbs", "has_traction_control", "oil_change_interval_km", "data_group",
    "source_type", "source_name", "source_url", "source_reference", "confidence",
    "collected_at", "reference_date", "is_primary", "review_status", "notes",
}
OBJECTIVE_REQUIRED = {
    "brand", "model", "version", "year", "category", "engine_displacement_cc", "fuel_type",
    "market_condition", "price_brl", "price_reference_date", "power_cv",
    "torque_nm", "wet_weight_kg", "seat_height_mm", "tank_capacity_l",
    "city_consumption_km_l", "road_consumption_km_l", "transmission_type",
    "gear_count", "final_drive_type", "has_abs", "has_cbs", "has_traction_control",
}
NUMERIC_POSITIVE = {
    "engine_displacement_cc", "price_brl", "power_cv", "torque_nm",
    "wet_weight_kg", "seat_height_mm", "tank_capacity_l",
    "city_consumption_km_l", "road_consumption_km_l", "gear_count",
}
NUMERIC_OPTIONAL_NONNEGATIVE = {"annual_maintenance_cost_brl", "oil_change_interval_km"}
BOOLEAN_FIELDS = {"has_abs", "has_cbs", "has_traction_control", "is_primary"}
BOOLEAN_TRUE = {"true", "1", "sim", "yes"}
BOOLEAN_FALSE = {"false", "0", "não", "nao", "no"}
CATEGORIES = {"scooter", "underbone", "street", "naked", "trail"}
MARKET_CONDITIONS = {"new", "used"}
FUEL_TYPES = {"gasoline", "flex", "electric", "other"}
TRANSMISSIONS = {"manual", "automatic", "semi_automatic", "cvt", "electric_direct", "other"}
FINAL_DRIVES = {"chain", "belt", "shaft", "direct", "other"}
DATA_GROUPS = {
    "identity", "market_price", "technical_specs", "consumption", "maintenance",
    "reliability", "parts_availability", "safety_equipment", "ergonomics",
    "taxes", "insurance", "derived_metrics",
}
SOURCE_TYPES = {"official", "estimated", "user_reported", "demonstration"}
REVIEW_STATUSES = {"draft", "reviewed", "approved", "rejected"}
PILOT_REQUIRED_GROUPS = set(PILOT_REQUIRED_SOURCE_GROUPS)
COMPLEMENTARY_GROUPS = set(COMPLEMENTARY_SOURCE_GROUPS)

CONSISTENT_RECORD_FIELDS = (
    "brand",
    "model",
    "version",
    "year",
    "manufacture_year",
    "market_condition",
    "category",
    "engine_displacement_cc",
    "fuel_type",
    "price_brl",
    "price_reference_date",
    "power_cv",
    "torque_nm",
    "wet_weight_kg",
    "seat_height_mm",
    "tank_capacity_l",
    "transmission_type",
    "gear_count",
    "final_drive_type",
    "has_abs",
    "has_cbs",
    "has_traction_control",
    "city_consumption_km_l",
    "road_consumption_km_l",
    "annual_maintenance_cost_brl",
)
CONSISTENT_BOOLEAN_FIELDS = {"has_abs", "has_cbs", "has_traction_control"}
CONSISTENT_NUMERIC_FIELDS = {
    "year",
    "manufacture_year",
    "engine_displacement_cc",
    "price_brl",
    "power_cv",
    "torque_nm",
    "wet_weight_kg",
    "seat_height_mm",
    "tank_capacity_l",
    "gear_count",
    "city_consumption_km_l",
    "road_consumption_km_l",
    "annual_maintenance_cost_brl",
}
MONETARY_FIELDS = {"price_brl", "annual_maintenance_cost_brl"}


def _error(errors, row_number, field, code, message):
    errors.append({"row": row_number, "field": field, "code": code, "message": message})


def _parse_number(value):
    number = float(_parse_decimal(value))
    if not math.isfinite(number):
        raise ValueError
    return number


def _parse_decimal(value):
    text_value = str(value).strip().replace(" ", "")
    if "," in text_value and "." in text_value:
        if text_value.rfind(",") > text_value.rfind("."):
            text_value = text_value.replace(".", "").replace(",", ".")
        else:
            text_value = text_value.replace(",", "")
    elif "," in text_value:
        text_value = text_value.replace(",", ".")
    try:
        number = Decimal(text_value)
    except InvalidOperation as error:
        raise ValueError from error
    if not number.is_finite():
        raise ValueError
    return number


def _parse_boolean(value):
    normalized = unicodedata.normalize("NFC", str(value).strip()).casefold()
    if normalized in BOOLEAN_TRUE:
        return True
    if normalized in BOOLEAN_FALSE:
        return False
    raise ValueError


def _is_true(value):
    try:
        return _parse_boolean(value)
    except ValueError:
        return False


def _normalize_record_value(field, value):
    if value is None or str(value).strip() == "":
        return None
    if field in CONSISTENT_BOOLEAN_FIELDS:
        return _parse_boolean(value)
    if field in CONSISTENT_NUMERIC_FIELDS:
        number = _parse_decimal(value)
        if field in MONETARY_FIELDS:
            return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return number.normalize()
    if field.endswith("_date"):
        return date.fromisoformat(str(value).strip())
    return " ".join(unicodedata.normalize("NFC", str(value)).strip().split()).casefold()


def _report_value(field, value):
    if value is None or str(value).strip() == "":
        return None
    normalized = _normalize_record_value(field, value)
    if isinstance(normalized, Decimal):
        return float(normalized)
    if isinstance(normalized, date):
        return normalized.isoformat()
    return normalized


def validate_record_consistency(rows):
    grouped = {}
    for index, row in enumerate(rows, start=2):
        grouped.setdefault(row.get("record_key", ""), []).append((index, row))

    inconsistencies = []
    inconsistent_records = set()
    for record_key, entries in grouped.items():
        for field in CONSISTENT_RECORD_FIELDS:
            if not any(field in row for _, row in entries):
                continue
            normalized_values = {}
            normalization_failed = False
            for row_number, row in entries:
                raw_value = row.get(field, "")
                try:
                    normalized = _normalize_record_value(field, raw_value)
                except (TypeError, ValueError):
                    normalization_failed = True
                    continue
                normalized_values.setdefault(normalized, []).append(
                    {"row": row_number, "value": _report_value(field, raw_value)}
                )
            if normalization_failed or len(normalized_values) <= 1:
                continue
            inconsistent_records.add(record_key)
            values = []
            for occurrences in normalized_values.values():
                values.extend(occurrences)
            inconsistencies.append(
                {
                    "code": "inconsistent_record_data",
                    "record_key": record_key,
                    "field": field,
                    "values": sorted(values, key=lambda item: item["row"]),
                }
            )
    return {
        "records_checked": len(grouped),
        "records_with_inconsistency": len(inconsistent_records),
        "inconsistencies": inconsistencies,
    }


def _valid_date(value):
    date.fromisoformat(value)


def _valid_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError


def _valid_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError


def validate_pilot_file(path: str | Path):
    source_path = Path(path)
    errors = []
    warnings = []
    rows = []
    if not source_path.is_file():
        return {"valid": False, "file": str(source_path), "errors": [{"row": 0, "field": "file", "code": "not_found", "message": "Arquivo não encontrado."}], "warnings": [], "record_count": 0, "source_count": 0, "coverage": []}, []

    with source_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - columns)
        for column in missing_columns:
            _error(errors, 1, column, "missing_column", "Coluna obrigatória ausente no template.")
        if missing_columns:
            return {"valid": False, "file": str(source_path), "errors": errors, "warnings": [], "record_count": 0, "source_count": 0, "coverage": []}, []
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]

    seen_sources = set()
    primary_by_record_group = set()
    grouped = {}
    for index, row in enumerate(rows, start=2):
        key = row["record_key"]
        if not key:
            _error(errors, index, "record_key", "required", "Identificador estável da motocicleta é obrigatório.")
        grouped.setdefault(key, []).append((index, row))
        for field in OBJECTIVE_REQUIRED:
            if not row[field]:
                _error(errors, index, field, "required", "Campo objetivo obrigatório ausente.")
        for field in NUMERIC_POSITIVE:
            if row[field]:
                try:
                    if _parse_number(row[field]) <= 0:
                        raise ValueError
                except ValueError:
                    _error(errors, index, field, "invalid_number", "Informe um número finito maior que zero.")
        for field in NUMERIC_OPTIONAL_NONNEGATIVE:
            if row[field]:
                try:
                    if _parse_number(row[field]) < 0:
                        raise ValueError
                except ValueError:
                    _error(errors, index, field, "invalid_number", "Informe um número finito não negativo.")
        if row["confidence"]:
            try:
                confidence = _parse_number(row["confidence"])
                if not 0 <= confidence <= 100:
                    raise ValueError
            except ValueError:
                _error(errors, index, "confidence", "out_of_range", "Confiança deve estar entre 0 e 100.")
        else:
            _error(errors, index, "confidence", "required", "Confiança da fonte é obrigatória.")
        try:
            year = int(row["year"])
            if not 1990 <= year <= 2035:
                raise ValueError
        except ValueError:
            _error(errors, index, "year", "invalid_year", "Ano deve ser inteiro entre 1990 e 2035.")
        for field in BOOLEAN_FIELDS:
            try:
                _parse_boolean(row[field])
            except ValueError:
                _error(errors, index, field, "invalid_boolean", "Use true ou false.")
        for field in ("price_reference_date", "reference_date"):
            try:
                _valid_date(row[field])
            except ValueError:
                _error(errors, index, field, "invalid_date", "Use uma data ISO 8601 no formato AAAA-MM-DD.")
        try:
            _valid_datetime(row["collected_at"])
        except ValueError:
            _error(errors, index, "collected_at", "invalid_datetime", "Use data/hora ISO 8601 com fuso horário.")
        if row["source_url"]:
            try:
                _valid_url(row["source_url"])
            except ValueError:
                _error(errors, index, "source_url", "invalid_url", "URL deve usar http ou https e possuir domínio.")
        elif not row["source_reference"]:
            _error(errors, index, "source_reference", "missing_traceability", "Informe URL ou referência textual da fonte.")
        for field, allowed in (
            ("category", CATEGORIES), ("market_condition", MARKET_CONDITIONS),
            ("fuel_type", FUEL_TYPES),
            ("transmission_type", TRANSMISSIONS), ("final_drive_type", FINAL_DRIVES),
            ("data_group", DATA_GROUPS), ("source_type", SOURCE_TYPES),
            ("review_status", REVIEW_STATUSES),
        ):
            if row[field] not in allowed:
                _error(errors, index, field, "invalid_enum", f"Valor fora do domínio permitido: {', '.join(sorted(allowed))}.")
        if not row["source_name"]:
            _error(errors, index, "source_name", "required", "Nome identificável da fonte é obrigatório.")

        source_identity = (key, row["data_group"], row["source_name"], row["source_url"], row["source_reference"])
        if source_identity in seen_sources:
            _error(errors, index, "data_group", "duplicate_source", "Fonte duplicada para o mesmo registro e grupo.")
        seen_sources.add(source_identity)
        if _is_true(row["is_primary"]):
            primary_key = (key, row["data_group"])
            if primary_key in primary_by_record_group:
                _error(errors, index, "is_primary", "duplicate_primary", "Há mais de uma fonte principal no grupo.")
            primary_by_record_group.add(primary_key)

    consistency = validate_record_consistency(rows)
    for inconsistency in consistency["inconsistencies"]:
        first_row = inconsistency["values"][0]["row"]
        _error(
            errors,
            first_row,
            inconsistency["field"],
            inconsistency["code"],
            f"Linhas do record_key {inconsistency['record_key']} possuem valores objetivos divergentes.",
        )

    coverage = []
    for key, entries in grouped.items():
        first = entries[0][1]
        objective_present = sum(bool(first[field]) for field in OBJECTIVE_REQUIRED)
        primary_groups = {row["data_group"] for _, row in entries if _is_true(row["is_primary"])}
        missing_pilot_groups = sorted(PILOT_REQUIRED_GROUPS - primary_groups)
        missing_complementary_groups = sorted(COMPLEMENTARY_GROUPS - primary_groups)
        for group in missing_pilot_groups:
            _error(errors, entries[0][0], "data_group", "missing_primary_source", f"Falta fonte principal para {group}.")
        required_confidences = [
            float(row["confidence"])
            for _, row in entries
            if row["data_group"] in PILOT_REQUIRED_GROUPS and _is_true(row["is_primary"])
        ]
        if any(row["source_type"] == "demonstration" and _is_true(row["is_primary"]) for _, row in entries):
            readiness = "demonstration_only"
        elif missing_pilot_groups:
            readiness = "not_ready"
        elif any(confidence < 60 for confidence in required_confidences):
            readiness = "insufficient_source_confidence"
        else:
            # The pilot template does not yet collect versioned depreciation,
            # taxes or insurance, so TCO readiness remains explicitly pending.
            readiness = "missing_economic_data"
        coverage.append({
            "record_key": key,
            "objective_field_coverage_percent": round(100 * objective_present / len(OBJECTIVE_REQUIRED), 2),
            "pilot_required_source_coverage_percent": round(100 * (len(PILOT_REQUIRED_GROUPS) - len(missing_pilot_groups)) / len(PILOT_REQUIRED_GROUPS), 2),
            "pilot_required_source_groups": sorted(PILOT_REQUIRED_GROUPS),
            "missing_pilot_source_groups": missing_pilot_groups,
            "complementary_source_coverage_percent": round(100 * (len(COMPLEMENTARY_GROUPS) - len(missing_complementary_groups)) / len(COMPLEMENTARY_GROUPS), 2),
            "missing_complementary_source_groups": missing_complementary_groups,
            "future_recommendation_readiness": readiness,
        })
        if first["annual_maintenance_cost_brl"] == "":
            warnings.append({"record_key": key, "field": "annual_maintenance_cost_brl", "message": "Manutenção estimada não informada; será mantida ausente."})

    report = {
        "valid": not errors,
        "file": str(source_path.resolve()),
        "record_count": len(grouped),
        "source_count": len(rows),
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage,
        "record_consistency": consistency,
    }
    return report, rows


def main():
    parser = argparse.ArgumentParser(description="Valida coleta piloto de motocicletas sem acessar rede ou banco.")
    parser.add_argument("file")
    args = parser.parse_args()
    report, _ = validate_pilot_file(args.file)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
