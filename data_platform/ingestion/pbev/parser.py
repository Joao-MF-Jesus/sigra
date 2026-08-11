from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

from data_platform.contracts.pbev import (
    PBEV_PARSER_VERSION,
    AuditedAsset,
    PbevAssetParseResult,
    PbevRawRow,
    ParsedPbevRow,
    SourceAsset,
)


NULL_SENTINELS = frozenset({"", "-", "\\", "ND", "N/D"})
OFFICIAL_HOST = "www.gov.br"
TWO_PLACES = Decimal("0.01")


class PbevValidationError(ValueError):
    """Ativo PBEV invalido e nao elegivel para Bronze aceita."""


class PbevQuarantineError(PbevValidationError):
    """Ativo preservavel como evidencia, mas bloqueado para Silver e Gold."""


def sanitize_official_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or parsed.hostname != OFFICIAL_HOST:
        raise PbevValidationError("PBEV source must use official HTTPS gov.br host")
    if parsed.username or parsed.password:
        raise PbevValidationError("authenticated PBEV URLs are forbidden")
    return urlunsplit(("https", parsed.hostname, parsed.path, "", ""))


def normalize_cell(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).replace("\u00ad", "-").replace("\n", " ")
    normalized = " ".join(normalized.split())
    if normalized in NULL_SENTINELS:
        return None
    return normalized or None


def decimal_from_cell(value: object) -> Decimal | None:
    normalized = normalize_cell(value)
    if normalized is None:
        return None
    candidate = normalized.replace(".", "").replace(",", ".")
    try:
        return Decimal(candidate)
    except InvalidOperation as exc:
        raise PbevValidationError(f"invalid PBEV decimal: {normalized!r}") from exc


def _multiply(value: Decimal | None, factor: str) -> Decimal | None:
    return value * Decimal(factor) if value is not None else None


def _seal(value: object) -> bool | None:
    normalized = (normalize_cell(value) or "").casefold()
    if normalized in {"sim", "s", "yes"}:
        return True
    if normalized in {"nao", "não", "n", "no"}:
        return False
    return None


def _fuel(value: object) -> str | None:
    normalized = (normalize_cell(value) or "").casefold()
    return {
        "f": "flex",
        "g": "gasoline",
        "d": "diesel",
        "e": "electric",
    }.get(normalized)


def _propulsion(value: object) -> str | None:
    normalized = (normalize_cell(value) or "").casefold()
    if "plug" in normalized:
        return "plug_in_hybrid"
    if "hibr" in normalized or "híbr" in normalized:
        return "hybrid"
    if "eletr" in normalized:
        return "electric"
    if "combust" in normalized:
        return "combustion"
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_fingerprint(
    asset: AuditedAsset,
    *,
    width: Decimal | float,
    height: Decimal | float,
) -> str:
    payload = {
        "layout_family": asset.layout_family,
        "cycle_year": asset.cycle_year,
        "columns": 24 if asset.cycle_year == 2022 else 23,
        "orientation": "portrait" if height > width else "landscape",
        "emissions": "nmog_nox_co_cho_mg_km" if asset.cycle_year == 2022 else "nmhc_co_nox_g_km",
        "propulsion": asset.cycle_year >= 2021,
        "conpet": asset.cycle_year != 2021,
        "parser_version": PBEV_PARSER_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _row_hash(cells: Sequence[str | None]) -> str:
    canonical = json.dumps(cells, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _candidate_table(tables: Iterable[Sequence[Sequence[Any]]], expected_columns: int):
    candidates = [
        table
        for table in tables
        if table and max((len(row) for row in table), default=0) == expected_columns
    ]
    return max(candidates, key=len) if candidates else None


def _extract_table(page: Any, expected_columns: int):
    table = _candidate_table(page.extract_tables(), expected_columns)
    if table is not None:
        return table, "vector_grid"
    # Fallback restrito ao mesmo layout conhecido. As estrategias textuais do
    # pdfplumber usam coordenadas dos caracteres e nao executam OCR.
    settings = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "min_words_vertical": 2,
        "min_words_horizontal": 1,
        "intersection_tolerance": 5,
    }
    table = _candidate_table(page.extract_tables(settings), expected_columns)
    if table is not None:
        return table, "positioned_text"
    raise PbevQuarantineError("known PBEV layout could not produce a complete table")


def _parse_row(
    asset: AuditedAsset,
    raw: PbevRawRow,
    cells: Sequence[str | None],
) -> ParsedPbevRow:
    year = asset.cycle_year
    if year <= 2019:
        category, brand, model, version, motor, transmission = cells[:6]
        air, steering, fuel_raw = cells[6:9]
        propulsion_raw = None
        emissions = tuple(cells[9:15])
        consumption = tuple(cells[15:19])
        energy, pbe_relative, pbe_absolute, conpet = cells[19:23]
    elif year == 2020:
        category, brand, model, motor, version, transmission = cells[:6]
        air, steering, fuel_raw = cells[6:9]
        propulsion_raw = None
        emissions = tuple(cells[9:15])
        consumption = tuple(cells[15:19])
        energy, pbe_relative, pbe_absolute, conpet = cells[19:23]
    elif year == 2021:
        category, brand, model, version, motor, transmission = cells[:6]
        air, steering, propulsion_raw, fuel_raw = cells[6:10]
        emissions = tuple(cells[10:16])
        consumption = tuple(cells[16:20])
        energy, pbe_relative, pbe_absolute = cells[20:23]
        conpet = None
    else:
        category, brand, model, version, motor, propulsion_raw = cells[:6]
        transmission, air, steering, fuel_raw = cells[6:10]
        emissions = tuple(cells[10:16])
        consumption = tuple(cells[16:20])
        energy, pbe_relative, pbe_absolute, conpet = cells[20:24]

    if not category or not brand or not model:
        raise PbevValidationError("PBEV data row has incomplete identity")

    fuel_type = _fuel(fuel_raw)
    decimals = tuple(decimal_from_cell(value) for value in consumption)
    ethanol_city = decimals[0]
    ethanol_highway = decimals[1]
    fossil_city = decimals[2]
    fossil_highway = decimals[3]
    electric_city = fossil_city if fuel_type == "electric" else None
    electric_highway = fossil_highway if fuel_type == "electric" else None
    if fuel_type == "electric":
        fossil_city = fossil_highway = None

    emission_values = tuple(decimal_from_cell(value) for value in emissions[:3])
    if year == 2022:
        nmhc = nox = None
        nmog_nox, co, cho = emission_values
        schema = "pbev-emissions-2022-mg-v1"
    else:
        nmhc, co_g, nox = emission_values
        nmhc = _multiply(nmhc, "1000")
        co = _multiply(co_g, "1000")
        nox = _multiply(nox, "1000")
        nmog_nox = cho = None
        schema = "pbev-emissions-2017-2021-g-v1"

    return ParsedPbevRow(
        raw=raw,
        category_name=category,
        brand_name=brand,
        model_name=model,
        version_name=version,
        motor_description=motor,
        transmission_code=transmission,
        propulsion_type=_propulsion(propulsion_raw),
        fuel_type=fuel_type,
        air_conditioning_code=air,
        steering_assistance_code=steering,
        emission_schema_version=schema,
        emission_raw=emissions,
        consumption_raw=consumption,
        nmhc_mg_km=nmhc,
        nox_mg_km=nox,
        nmog_nox_mg_km=nmog_nox,
        co_mg_km=co,
        cho_mg_km=cho,
        co2_ethanol_g_km=decimal_from_cell(emissions[4]),
        co2_fossil_g_km=decimal_from_cell(emissions[5]),
        pollutant_reduction_class=normalize_cell(emissions[3]),
        ethanol_city_km_l=ethanol_city,
        ethanol_highway_km_l=ethanol_highway,
        fossil_city_km_l=fossil_city,
        fossil_highway_km_l=fossil_highway,
        electric_city_km_l_equivalent=electric_city,
        electric_highway_km_l_equivalent=electric_highway,
        energy_mj_km=decimal_from_cell(energy),
        pbe_relative_class=normalize_cell(pbe_relative),
        pbe_absolute_class=normalize_cell(pbe_absolute),
        conpet_seal=_seal(conpet),
    )


class PbevPdfParser:
    def __init__(self, *, accessed_at: datetime | None = None):
        self.accessed_at = accessed_at or datetime.now(UTC)

    @staticmethod
    def _pdfplumber():
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "pdfplumber is required for official PBEV asset processing"
            ) from exc
        return pdfplumber

    def parse(self, path: Path, audited: AuditedAsset) -> PbevAssetParseResult:
        resolved = path.resolve(strict=True)
        official_page = sanitize_official_url(audited.official_page_url)
        download_url = sanitize_official_url(audited.download_url)
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type != "application/pdf":
            raise PbevValidationError("PBEV asset MIME must be application/pdf")
        with resolved.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise PbevValidationError("PBEV asset does not have a PDF signature")
        byte_length = resolved.stat().st_size
        digest = _hash_file(resolved)
        if digest != audited.sha256:
            raise PbevQuarantineError("PBEV asset hash differs from the audited asset")
        if byte_length != audited.byte_length:
            raise PbevQuarantineError("PBEV asset size differs from the audited asset")

        pdfplumber = self._pdfplumber()
        rows: list[ParsedPbevRow] = []
        rejected = tables_found = 0
        fallback_pages: list[int] = []
        with pdfplumber.open(resolved) as document:
            if len(document.pages) != audited.page_count:
                raise PbevQuarantineError("PBEV asset page count differs from the audit")
            first = document.pages[0]
            fingerprint = _schema_fingerprint(
                audited,
                width=first.width,
                height=first.height,
            )
            expected_columns = 24 if audited.cycle_year == 2022 else 23
            for page_number, page in enumerate(document.pages, 1):
                table, extraction_method = _extract_table(page, expected_columns)
                tables_found += 1
                if extraction_method == "positioned_text":
                    fallback_pages.append(page_number)
                carry: list[str | None] = [None, None, None]
                for row_number, source_cells in enumerate(table, 1):
                    cells = [normalize_cell(value) for value in source_cells]
                    cells.extend([None] * (expected_columns - len(cells)))
                    cells = cells[:expected_columns]
                    for index in range(3):
                        header = (cells[index] or "").casefold()
                        if cells[index] and header not in {"categoria", "marca(?)", "modelo(?)", "marca", "modelo"}:
                            carry[index] = cells[index]
                        elif cells[index] is None:
                            cells[index] = carry[index]
                    energy_index = 20 if audited.cycle_year >= 2021 else 19
                    try:
                        energy = decimal_from_cell(cells[energy_index])
                    except PbevValidationError:
                        energy = None
                    motor_index = 4 if audited.cycle_year != 2020 else 3
                    transmission_index = 6 if audited.cycle_year == 2022 else 5
                    looks_like_data = bool(
                        all(cells[index] for index in (0, 1, 2))
                        and cells[motor_index]
                        and cells[transmission_index]
                    )
                    if not looks_like_data:
                        continue
                    row_hash = _row_hash(cells)
                    extraction_status = "parsed" if energy is not None else "invalid_row"
                    raw = PbevRawRow(
                        cycle_year=audited.cycle_year,
                        page_number=page_number,
                        row_number=row_number,
                        parser_version=PBEV_PARSER_VERSION,
                        layout_family=audited.layout_family,
                        schema_fingerprint=fingerprint,
                        raw_cells=tuple(cells),
                        raw_text=" | ".join(value or "" for value in cells),
                        row_hash=row_hash,
                        extraction_status=extraction_status,
                        extraction_method=extraction_method,
                        source_record_key=f"{audited.cycle_year}:{page_number}:{row_number}:{row_hash[:16]}",
                    )
                    try:
                        rows.append(_parse_row(audited, raw, cells))
                        if extraction_status == "invalid_row":
                            rejected += 1
                    except PbevValidationError:
                        rejected += 1
            if fallback_pages:
                raise PbevQuarantineError(
                    "positioned-text fallback requires explicit visual review before acceptance"
                )

        if len(rows) != audited.expected_row_count:
            raise PbevQuarantineError(
                f"PBEV audited row count changed: expected {audited.expected_row_count}, got {len(rows)}"
            )
        asset = SourceAsset(
            pipeline_run_id=None,
            cycle_year=audited.cycle_year,
            official_page_url=official_page,
            download_url_sanitized=download_url,
            document_title=audited.document_title,
            accessed_at=self.accessed_at,
            content_type=content_type,
            byte_length=byte_length,
            page_count=audited.page_count,
            sha256=digest,
            layout_family=audited.layout_family,
            document_metadata={
                "parser_version": PBEV_PARSER_VERSION,
                "expected_row_count": audited.expected_row_count,
                "schema_fingerprint": rows[0].raw.schema_fingerprint if rows else None,
            },
            storage_mode="metadata_only",
            document_bytes=None,
            validation_details={
                "signature_valid": True,
                "mime_valid": True,
                "hash_valid": True,
                "page_count_valid": True,
                "layout_valid": True,
                "unit_schema_valid": True,
            },
        )
        return PbevAssetParseResult(
            asset=asset,
            rows=tuple(rows),
            pages_processed=audited.page_count,
            tables_found=tables_found,
            rows_rejected=rejected,
            fallback_pages=tuple(fallback_pages),
        )

    def inspect_hash_drift(self, path: Path, audited: AuditedAsset) -> SourceAsset:
        """Create metadata-only quarantine evidence without parsing source rows."""
        resolved = path.resolve(strict=True)
        official_page = sanitize_official_url(audited.official_page_url)
        download_url = sanitize_official_url(audited.download_url)
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type != "application/pdf":
            raise PbevValidationError("PBEV asset MIME must be application/pdf")
        with resolved.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise PbevValidationError("PBEV asset does not have a PDF signature")
        digest = _hash_file(resolved)
        if digest == audited.sha256:
            raise PbevValidationError("PBEV asset does not represent hash drift")
        byte_length = resolved.stat().st_size
        pdfplumber = self._pdfplumber()
        with pdfplumber.open(resolved) as document:
            page_count = len(document.pages)
        return SourceAsset(
            pipeline_run_id=None,
            cycle_year=audited.cycle_year,
            official_page_url=official_page,
            download_url_sanitized=download_url,
            document_title=audited.document_title,
            accessed_at=self.accessed_at,
            content_type=content_type,
            byte_length=byte_length,
            page_count=page_count,
            sha256=digest,
            layout_family=f"unvalidated:{audited.layout_family}",
            document_metadata={
                "parser_version": PBEV_PARSER_VERSION,
                "expected_sha256": audited.sha256,
            },
            storage_mode="metadata_only",
            document_bytes=None,
            asset_status="quarantined",
            validation_details={
                "signature_valid": True,
                "mime_valid": True,
                "hash_valid": False,
                "size_valid": byte_length == audited.byte_length,
                "page_count_valid": page_count == audited.page_count,
                "layout_valid": False,
                "requires_layout_validation": True,
            },
        )


def validate_synthetic_table(
    audited: AuditedAsset,
    cells: Sequence[object],
    *,
    page_number: int = 1,
    row_number: int = 1,
) -> ParsedPbevRow:
    """Entrada minima para testes; nao aceita nem incorpora linhas oficiais."""
    expected = 24 if audited.cycle_year == 2022 else 23
    normalized = tuple(normalize_cell(value) for value in cells)
    if len(normalized) != expected:
        raise PbevValidationError("synthetic PBEV row has unexpected column count")
    fingerprint = _schema_fingerprint(audited, width=842, height=595 if audited.cycle_year < 2022 else 842)
    raw = PbevRawRow(
        cycle_year=audited.cycle_year,
        page_number=page_number,
        row_number=row_number,
        parser_version=PBEV_PARSER_VERSION,
        layout_family=audited.layout_family,
        schema_fingerprint=fingerprint,
        raw_cells=normalized,
        raw_text=" | ".join(value or "" for value in normalized),
        row_hash=_row_hash(normalized),
        source_record_key=f"synthetic:{audited.cycle_year}:{page_number}:{row_number}",
    )
    return _parse_row(audited, raw, normalized)
