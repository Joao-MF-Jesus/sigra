from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from data_platform.contracts.pbev import ExternalVehicleIdentity
from data_platform.transformation.pbev import normalize_match_text


_CATALOG_CONFLICTS = (
    ("comfort", "vision"),
    ("attractive", "drive"),
)

_MULTIWORD_MODEL_FAMILIES = (
    ("corolla", "cross"),
    ("onix", "plus"),
    ("onix", "joy"),
    ("t", "cross"),
)


def _transmission(model_name: str) -> str | None:
    normalized = normalize_match_text(model_name)
    if "cvt" in normalized:
        return "cvt"
    if re.search(r"\baut\b|automatic", normalized):
        return "automatic_generic"
    if re.search(r"\bmec\b|manual", normalized):
        return "manual"
    return None


def _engine_description(model_name: str) -> str | None:
    decimal = re.search(r"(?<!\d)(\d{1,2}[.,]\d)(?:\s*l)?\b", model_name, re.IGNORECASE)
    if decimal:
        return decimal.group(1).replace(",", ".")
    cubic = re.search(r"(?<!\d)(\d{3,4})\s*(?:cc|cm\s*(?:3|\u00b3))\b", model_name, re.IGNORECASE)
    if cubic:
        return f"{cubic.group(1)} cm3"
    return None


def _door_count(model_name: str) -> int | None:
    normalized = normalize_match_text(model_name)
    match = re.search(r"\b([2345])\s*p\b|\b([2345])\s*portas?\b", normalized)
    return int(match.group(1) or match.group(2)) if match else None


def _body_style(catalog_category: str | None, model_name: str) -> str | None:
    normalized = normalize_match_text(" ".join(item for item in (catalog_category, model_name) if item))
    if "hatch" in normalized:
        return "hatch"
    if re.search(r"\bsedan\b|\bseda\b|\bsed\b", normalized):
        return "sedan"
    if "utilitario esportivo" in normalized or re.search(r"\bsuv\b|\bcrossover\b", normalized):
        return "suv"
    if "picape" in normalized or "pickup" in normalized:
        return "pickup"
    if "minivan" in normalized:
        return "minivan"
    return None


def _catalog_version(catalog_model: str) -> str | None:
    tokens = normalize_match_text(catalog_model).split()
    if not tokens:
        return None
    family_size = 1
    for family in _MULTIWORD_MODEL_FAMILIES:
        if tuple(tokens[: len(family)]) == family:
            family_size = len(family)
            break
    version = tokens[family_size:]
    return " ".join(version) or None


def _target_version(catalog_model: str, model_name: str) -> str | None:
    version = _catalog_version(catalog_model)
    normalized_model = normalize_match_text(model_name)
    if re.search(r"\bcomfor\b|\bcomfortline\b", normalized_model):
        ordered = ["comfortline", *(item for item in (version or "").split() if item != "comfortline")]
        return " ".join(dict.fromkeys(ordered))
    return version


def _fuel_identity_warning(model_name: str, fuel_type: str) -> str | None:
    normalized = normalize_match_text(model_name)
    if "flex" in normalized and normalize_match_text(fuel_type) != "flex":
        return "fipe_description_indicates_flex_but_silver_fuel_differs"
    return None


def _catalog_conflict(catalog_model: str, silver_model: str) -> bool:
    catalog = normalize_match_text(catalog_model)
    silver = normalize_match_text(silver_model)
    return any(
        (left in catalog and right in silver)
        or (right in catalog and left in silver)
        for left, right in _CATALOG_CONFLICTS
    )


def load_current_catalog_targets(engine: Engine) -> tuple[ExternalVehicleIdentity, ...]:
    """Reconcilia IDs externos com a identidade Silver real, sem criar SKs."""
    if engine.dialect.name != "postgresql":
        return ()
    from backend.app.fipe import FIPE_REFERENCE_PROFILES

    cache_path = Path(__file__).resolve().parents[2] / "backend" / "data" / "fipe_cache.json"
    cached = {
        int(item["vehicle_id"]): item
        for item in json.loads(cache_path.read_text(encoding="utf-8"))
        if item.get("vehicle_id") is not None
    }
    targets: list[ExternalVehicleIdentity] = []
    with engine.connect() as connection:
        catalog = {
            int(row["id"]): row
            for row in connection.execute(
                text("SELECT id,brand,model,year,category FROM vehicles WHERE vehicle_type='car' ORDER BY id")
            ).mappings()
        }
        for external_id, profile in sorted(FIPE_REFERENCE_PROFILES.items()):
            cache = cached.get(int(external_id), {})
            year_code = str(cache.get("year_code") or profile.year_code)
            if "-" not in year_code or external_id not in catalog:
                continue
            mapping = connection.execute(
                text(
                    """SELECT identity.vehicle_sk,identity.brand_name,
                              identity.model_name,identity.version_name,
                              identity.model_year,identity.fuel_type,
                              identity.transmission_type,mapping.mapping_id
                       FROM silver.vehicle_source_mapping AS mapping
                       JOIN silver.vehicle_identity AS identity
                         ON identity.vehicle_sk=mapping.vehicle_sk
                        AND identity.is_current
                       WHERE mapping.source_name='Tabela FIPE via API Parallelum'
                         AND mapping.vehicle_type='car'
                         AND mapping.fipe_code=:fipe
                         AND mapping.year_code=:year
                         AND mapping.mapping_status='matched'
                         AND mapping.valid_to IS NULL"""
                ),
                {"fipe": profile.code, "year": year_code},
            ).mappings().one_or_none()
            if mapping is None or mapping["model_year"] is None:
                continue
            catalog_row = catalog[int(external_id)]
            catalog_model = str(catalog_row["model"])
            silver_model = str(mapping["model_name"])
            version_name = (
                str(mapping["version_name"])
                if mapping["version_name"]
                else _target_version(catalog_model, silver_model)
            )
            motor_description = _engine_description(silver_model)
            transmission_type = (
                str(mapping["transmission_type"])
                if mapping["transmission_type"]
                else _transmission(silver_model)
            )
            body_style = _body_style(str(catalog_row["category"]), silver_model)
            door_count = _door_count(silver_model)
            fuel_warning = _fuel_identity_warning(silver_model, str(mapping["fuel_type"]))
            targets.append(
                ExternalVehicleIdentity(
                    vehicle_sk=int(mapping["vehicle_sk"]),
                    brand_name=str(mapping["brand_name"]),
                    model_name=silver_model,
                    model_year=int(mapping["model_year"]),
                    fuel_type=str(mapping["fuel_type"]),
                    version_name=version_name,
                    motor_description=motor_description,
                    transmission_type=transmission_type,
                    body_style=body_style,
                    external_catalog_reference=int(external_id),
                    catalog_model_name=catalog_model,
                    catalog_conflict=_catalog_conflict(catalog_model, silver_model),
                    evidence={
                        "external_reference": int(external_id),
                        "fipe_code": profile.code,
                        "year_code": year_code,
                        "silver_mapping_id": int(mapping["mapping_id"]),
                        "door_count": door_count,
                        "version_source": "silver" if mapping["version_name"] else "catalog",
                        "motor_source": "fipe_description" if motor_description else "unknown",
                        "transmission_source": (
                            "silver"
                            if mapping["transmission_type"]
                            else "fipe_description"
                            if transmission_type
                            else "unknown"
                        ),
                        "body_style_source": "catalog_or_fipe" if body_style else "unknown",
                        "fuel_identity_warning": fuel_warning,
                    },
                )
            )
    return tuple(targets)
