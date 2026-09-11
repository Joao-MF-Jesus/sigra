import json
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx


FIPE_API_URL = os.getenv("FIPE_API_URL", "https://fipe.parallelum.com.br/api/v2").rstrip("/")
FIPE_CACHE_TTL_HOURS = max(1, int(os.getenv("FIPE_CACHE_TTL_HOURS", "24")))
FIPE_HTTP_TIMEOUT_SECONDS = max(1.0, float(os.getenv("FIPE_HTTP_TIMEOUT_SECONDS", "5")))
FIPE_CACHE_FILE = Path(os.getenv("FIPE_CACHE_FILE", Path(__file__).resolve().parents[1] / "data" / "fipe_cache.json"))


@dataclass(frozen=True)
class FipeReference:
    vehicle_id: int
    price: float
    code: str
    year_code: str
    model: str
    reference_month: str = ""
    checked_at: str = ""
    retrieved_at: str = ""
    retrieval_status: str = "mapped_pending_sync"
    source_name: str = "Tabela FIPE via API Parallelum"
    source_url: str = "https://fipe.parallelum.com.br/"
    official_source_url: str = "https://veiculos.fipe.org.br/"


# Cada item aponta para uma versao FIPE especifica. O ano fica sem o sufixo de
# combustivel porque a API o resolve a partir da lista oficial daquela versao.
FIPE_REFERENCE_PROFILES = {
    1: FipeReference(1, 62000, "004517-9", "2021", "ONIX HATCH LT 1.0 12V Flex 5p Mec."),
    2: FipeReference(2, 54000, "004436-9", "2018", "PRISMA Sed. LT 1.4 8V FlexPower 4p Aut."),
    3: FipeReference(3, 61000, "004421-0", "2018", "COBALT LTZ 1.8 8V Econo.Flex 4p Aut."),
    4: FipeReference(4, 74000, "004415-6", "2019", "SPIN LT 1.8 8V Econo.Flex 5p Aut."),
    5: FipeReference(5, 92000, "004522-5", "2021", "TRACKER LT 1.0 Turbo 12V Flex Aut."),
    6: FipeReference(6, 59000, "015168-8", "2020", "HB20 Vision 1.0 Flex 12V Mec."),
    7: FipeReference(7, 65000, "015174-2", "2020", "HB20S Vision 1.0 Flex 12V Mec."),
    8: FipeReference(8, 86000, "015157-2", "2019", "Creta Attitude 1.6 16V Flex Aut."),
    9: FipeReference(9, 86000, "002109-1", "2018", "Corolla GLi 1.8 Flex 16V Aut."),
    10: FipeReference(10, 57000, "002150-4", "2018", "ETIOS XLS 1.5 Flex 5p Aut."),
    11: FipeReference(11, 76000, "002172-5", "2020", "YARIS XL 1.3 Flex 16V 5p Aut."),
    12: FipeReference(12, 132000, "002201-2", "2022", "Corolla Cross XR 2.0 16V Flex Aut."),
    13: FipeReference(13, 65000, "014045-7", "2017", "Fit EX/S 1.5 Flex/Flexone 16V 5p Aut."),
    14: FipeReference(14, 72000, "014059-7", "2018", "CITY Sedan LX 1.5 Flex 16V 4p Aut."),
    15: FipeReference(15, 89000, "014091-0", "2017", "Civic Sedan EX 2.0 Flex 16V Aut. 4p"),
    16: FipeReference(16, 88000, "014086-4", "2018", "HR-V LX 1.8 Flexone 16V 5p Aut."),
    17: FipeReference(17, 50000, "005490-9", "2019", "Gol 1.0 Flex 12V 5p"),
    18: FipeReference(18, 68000, "005478-0", "2019", "Polo 1.6 MSI Flex 16V 5p"),
    19: FipeReference(19, 70000, "005486-0", "2019", "Virtus 1.6 MSI Flex 16V 5p Mec."),
    20: FipeReference(20, 56000, "005458-5", "2018", "VOYAGE Comfortline 1.0 T.Flex 12V 4p"),
    21: FipeReference(21, 98000, "005509-3", "2020", "T-Cross Comfortline 200 TSI 1.0 Flex 5p Aut."),
    22: FipeReference(22, 48000, "001461-3", "2021", "MOBI LIKE 1.0 Fire Flex 5p."),
    23: FipeReference(23, 45000, "001486-9", "2018", "UNO DRIVE 1.0 Flex 6V 5p"),
    24: FipeReference(24, 61000, "001494-0", "2020", "ARGO DRIVE 1.0 6V Flex"),
    25: FipeReference(25, 67000, "001505-9", "2020", "CRONOS DRIVE 1.3 8V Flex"),
    26: FipeReference(26, 54000, "025288-3", "2020", "SANDERO Zen Flex 1.0 12V 5p Mec."),
    27: FipeReference(27, 58000, "025290-5", "2020", "LOGAN Zen Flex 1.0 12V 4p Mec."),
    28: FipeReference(28, 78000, "025302-2", "2020", "DUSTER Zen 1.6 16V Flex Aut."),
    29: FipeReference(29, 46000, "023143-6", "2018", "MARCH SV 1.6 16V FlexStart 5p Aut."),
    30: FipeReference(30, 61000, "023144-4", "2019", "VERSA SV 1.6 16V FlexStart 4p Aut."),
    31: FipeReference(31, 85000, "023156-8", "2020", "KICKS S 1.6 16V Flex 5p Aut."),
    32: FipeReference(32, 82000, "017034-8", "2019", "Renegade Sport 1.8 4x2 Flex 16V Aut."),
    33: FipeReference(33, 50000, "003408-8", "2019", "Ka 1.0 SE/SE Plus TiVCT Flex 5p"),
    34: FipeReference(34, 67000, "003440-1", "2018", "EcoSport SE 1.5 12V Flex 5p Aut."),
}

_references = dict(FIPE_REFERENCE_PROFILES)
_refresh_lock = threading.Lock()
_last_refresh_attempt: datetime | None = None
_last_refresh_error: str | None = None


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _parse_brl_price(value: str | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    normalized = value.replace("R$", "").replace(".", "").replace(",", ".").strip()
    return float(normalized)


def _load_cache() -> None:
    if not FIPE_CACHE_FILE.exists():
        return
    try:
        entries = json.loads(FIPE_CACHE_FILE.read_text(encoding="utf-8"))
        for entry in entries:
            reference = FipeReference(**entry)
            profile = FIPE_REFERENCE_PROFILES.get(reference.vehicle_id)
            if (
                profile
                and reference.retrieval_status in {"live", "cached"}
                and reference.code == profile.code
            ):
                _references[reference.vehicle_id] = reference
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # Cache corrompido nunca impede a API de iniciar; o valor validado local
        # continua disponivel como fallback.
        return


def _save_cache() -> None:
    FIPE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(reference) for reference in sorted(_references.values(), key=lambda item: item.vehicle_id)]
    temporary = FIPE_CACHE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(FIPE_CACHE_FILE)


def _is_fresh(reference: FipeReference, now: datetime) -> bool:
    retrieved_at = _parse_datetime(reference.retrieved_at)
    return bool(retrieved_at and now - retrieved_at < timedelta(hours=FIPE_CACHE_TTL_HOURS))


def _is_synchronized(reference: FipeReference | None) -> bool:
    return bool(reference and reference.retrieval_status in {"live", "cached"})


def _resolve_year_code(client: httpx.Client, profile: FipeReference) -> str:
    if "-" in profile.year_code:
        return profile.year_code
    response = client.get(f"/cars/{profile.code}/years")
    response.raise_for_status()
    candidates = [
        item
        for item in response.json()
        if str(item.get("code", "")).startswith(f"{profile.year_code}-")
    ]
    if not candidates:
        raise ValueError(f"Ano {profile.year_code} não disponível para o código {profile.code}")
    candidates.sort(
        key=lambda item: (
            "flex" not in str(item.get("name", "")).lower(),
            "gasolina" not in str(item.get("name", "")).lower(),
            str(item.get("code", "")),
        )
    )
    return str(candidates[0]["code"])


def _fetch_reference(client: httpx.Client, profile: FipeReference, now: datetime) -> FipeReference:
    year_code = _resolve_year_code(client, profile)
    endpoint = f"/cars/{profile.code}/years/{year_code}"
    response = client.get(endpoint)
    response.raise_for_status()
    data = response.json()
    returned_code = str(data.get("codeFipe", "")).strip()
    returned_year = int(data.get("modelYear", 0))
    if returned_code != profile.code or returned_year != int(profile.year_code.split("-")[0]):
        raise ValueError("Resposta FIPE não corresponde ao código e ano validados")
    return replace(
        profile,
        year_code=year_code,
        price=_parse_brl_price(data["price"]),
        model=str(data.get("model") or profile.model),
        reference_month=str(data.get("referenceMonth") or profile.reference_month),
        checked_at=now.date().isoformat(),
        retrieved_at=now.isoformat(),
        retrieval_status="live",
    )


def refresh_fipe_prices(force: bool = False) -> dict[str, object]:
    global _last_refresh_attempt, _last_refresh_error
    now = datetime.now(UTC)
    with _refresh_lock:
        if not force and _last_refresh_attempt and now - _last_refresh_attempt < timedelta(minutes=15):
            return fipe_sync_status()
        pending = [
            _references.get(vehicle_id, profile)
            for vehicle_id, profile in FIPE_REFERENCE_PROFILES.items()
            if force or not _is_fresh(_references.get(vehicle_id, profile), now)
        ]
        if not pending:
            return fipe_sync_status()
        _last_refresh_attempt = now
        errors = []
        updated = 0
        try:
            with httpx.Client(base_url=FIPE_API_URL, timeout=FIPE_HTTP_TIMEOUT_SECONDS) as client:
                for profile in pending:
                    try:
                        _references[profile.vehicle_id] = _fetch_reference(client, profile, now)
                        updated += 1
                    except (httpx.ConnectError, httpx.TimeoutException) as exc:
                        errors.append(f"provedor indisponível: {exc}")
                        break
                    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                        errors.append(f"veículo {profile.vehicle_id}: {exc}")
            if updated:
                _save_cache()
        except httpx.HTTPError as exc:
            errors.append(str(exc))
        _last_refresh_error = "; ".join(errors) if errors else None
        status = fipe_sync_status()
        status["updated_now"] = updated
        return status


def ensure_fipe_prices_current() -> None:
    if os.getenv("FIPE_AUTO_REFRESH", "true").lower() not in {"1", "true", "yes", "on"}:
        return
    refresh_fipe_prices(force=False)


def get_fipe_reference(vehicle_id: int) -> FipeReference | None:
    return _references.get(vehicle_id)


def effective_price(vehicle_id: int, demonstrative_price: float) -> float:
    reference = get_fipe_reference(vehicle_id)
    return reference.price if _is_synchronized(reference) else demonstrative_price


def price_metadata(vehicle_id: int) -> dict[str, object]:
    reference = get_fipe_reference(vehicle_id)
    if reference is None:
        return {
            "type": "demonstrative",
            "is_fipe": False,
            "label": "Referencia demonstrativa SIGRA",
            "validation_status": "pending_version_match",
        }
    metadata = asdict(reference)
    if not _is_synchronized(reference):
        metadata.update(
            {
                "type": "fipe_mapping",
                "is_fipe": False,
                "label": "FIPE mapeada - aguardando sincronizacao",
                "validation_status": "mapped_pending_sync",
                "cache_is_fresh": False,
            }
        )
        return metadata
    metadata.update(
        {
            "type": "fipe",
            "is_fipe": True,
            "label": f"FIPE - {reference.reference_month}",
            "validation_status": "verified",
            "cache_is_fresh": _is_fresh(reference, datetime.now(UTC)),
        }
    )
    return metadata


def fipe_coverage(total_vehicles: int) -> dict[str, object]:
    mapped = len(FIPE_REFERENCE_PROFILES)
    synchronized = sum(_is_synchronized(item) for item in _references.values())
    return {
        "mapped_vehicles": mapped,
        "synchronized_vehicles": synchronized,
        "verified_vehicles": synchronized,
        "total_vehicles": total_vehicles,
        "mapping_coverage_percent": round((mapped / total_vehicles) * 100, 2) if total_vehicles else 0.0,
        "coverage_percent": round((synchronized / total_vehicles) * 100, 2) if total_vehicles else 0.0,
        "reference_months": sorted({item.reference_month for item in _references.values() if item.reference_month}),
    }


def fipe_sync_status() -> dict[str, object]:
    return {
        "provider": "API Parallelum",
        "official_table": "Tabela FIPE",
        "cache_ttl_hours": FIPE_CACHE_TTL_HOURS,
        "last_attempt": _last_refresh_attempt.isoformat() if _last_refresh_attempt else None,
        "last_error": _last_refresh_error,
        "references": [price_metadata(vehicle_id) for vehicle_id in sorted(FIPE_REFERENCE_PROFILES)],
    }


_load_cache()
