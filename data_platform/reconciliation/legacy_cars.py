from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class LegacyCoverageRow:
    legacy_vehicle_id: int
    fipe_code: str
    year_code: str | None
    mapping_status: str
    vehicle_sk: int | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_legacy_vehicles(
    profiles: Mapping[int, Any],
    cached_items: Iterable[Mapping[str, Any]],
    current_mappings: Iterable[Mapping[str, Any]],
) -> tuple[LegacyCoverageRow, ...]:
    """Classifica cobertura sem escrever ou completar qualquer linha Silver."""
    cache_by_id = {
        int(item["vehicle_id"]): item
        for item in cached_items
        if item.get("vehicle_id") is not None
    }
    mappings_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for mapping in current_mappings:
        key = (str(mapping["fipe_code"]), str(mapping["year_code"]))
        mappings_by_key.setdefault(key, []).append(mapping)

    rows: list[LegacyCoverageRow] = []
    for legacy_id in sorted(profiles):
        profile = profiles[legacy_id]
        cached = cache_by_id.get(legacy_id, {})
        fipe_code = str(getattr(profile, "code"))
        raw_year_code = cached.get("year_code") or getattr(profile, "year_code", None)
        year_code = str(raw_year_code) if raw_year_code is not None else None

        if not year_code or "-" not in year_code:
            rows.append(
                LegacyCoverageRow(
                    legacy_vehicle_id=legacy_id,
                    fipe_code=fipe_code,
                    year_code=year_code,
                    mapping_status="rejected",
                    vehicle_sk=None,
                    note="Full FIPE year_code is unavailable; legacy ID remains external only.",
                )
            )
            continue

        candidates = mappings_by_key.get((fipe_code, year_code), [])
        if not candidates:
            rows.append(
                LegacyCoverageRow(
                    legacy_vehicle_id=legacy_id,
                    fipe_code=fipe_code,
                    year_code=year_code,
                    mapping_status="pending",
                    vehicle_sk=None,
                    note="No current Silver FIPE mapping was found.",
                )
            )
            continue
        if len(candidates) > 1:
            rows.append(
                LegacyCoverageRow(
                    legacy_vehicle_id=legacy_id,
                    fipe_code=fipe_code,
                    year_code=year_code,
                    mapping_status="ambiguous",
                    vehicle_sk=None,
                    note="More than one current mapping candidate was found.",
                )
            )
            continue

        candidate = candidates[0]
        status = str(candidate["mapping_status"])
        vehicle_sk = (
            int(candidate["vehicle_sk"])
            if status == "matched" and candidate.get("vehicle_sk") is not None
            else None
        )
        rows.append(
            LegacyCoverageRow(
                legacy_vehicle_id=legacy_id,
                fipe_code=fipe_code,
                year_code=year_code,
                mapping_status=status,
                vehicle_sk=vehicle_sk,
                note=(
                    "Read-only coverage through FIPE code and full year_code."
                    if status == "matched"
                    else "Silver mapping is not eligible for price publication."
                ),
            )
        )
    return tuple(rows)


def generate_legacy_coverage(engine: Engine) -> tuple[LegacyCoverageRow, ...]:
    if engine.dialect.name != "postgresql":
        return ()

    from backend.app.fipe import FIPE_REFERENCE_PROFILES

    cache_path = Path(__file__).resolve().parents[2] / "backend" / "data" / "fipe_cache.json"
    cached_items = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else []
    )
    with engine.connect() as connection:
        mappings = connection.execute(
            text(
                """SELECT vehicle_sk,fipe_code,year_code,mapping_status
                FROM silver.vehicle_source_mapping
                WHERE valid_to IS NULL"""
            )
        ).mappings().all()
    return reconcile_legacy_vehicles(
        FIPE_REFERENCE_PROFILES,
        cached_items,
        mappings,
    )
