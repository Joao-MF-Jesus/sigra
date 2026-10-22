"""Ponte transitoria para os perfis legados; remover apos a Silver de identidade.

Este modulo apenas descobre endpoints. A ingestao nao depende dos IDs internos
1-34: deduplicacao e identidade usam codigo FIPE, ano e hash do payload.
"""
import json
from pathlib import Path

from data_platform.contracts.fipe import FipeTarget


def legacy_car_targets() -> list[FipeTarget]:
    from backend.app.fipe import FIPE_REFERENCE_PROFILES

    cache_path = Path(__file__).resolve().parents[3] / "backend" / "data" / "fipe_cache.json"
    cached = {}
    if cache_path.exists():
        cached = {str(item.get("code")): str(item.get("year_code")) for item in json.loads(cache_path.read_text(encoding="utf-8"))}
    targets = []
    for item in FIPE_REFERENCE_PROFILES.values():
        year_code = cached.get(item.code, item.year_code)
        if "-" in year_code:
            targets.append(FipeTarget("car", item.code, year_code))
    return targets
