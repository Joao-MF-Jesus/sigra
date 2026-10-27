from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json

from data_platform.anp.sources import (
    ANP_EXPECTED_HEADER,
    ANP_EXPECTED_LAYOUT_FINGERPRINT,
    layout_fingerprint,
)
from data_platform.contracts.anp_fuel_prices import (
    ANP_PARSER_VERSION,
    AnpRawRow,
    DownloadedAnpAsset,
    ParsedAnpAsset,
)


class AnpLayoutDriftError(ValueError):
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        super().__init__("ANP CSV layout drift: header differs from the audited schema")


class AnpCsvParser:
    def parse(self, asset: DownloadedAnpAsset) -> ParsedAnpAsset:
        try:
            with asset.path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
                reader = csv.DictReader(stream, delimiter=";", quotechar='"', strict=True)
                header = tuple(reader.fieldnames or ())
                fingerprint = layout_fingerprint(header)
                if header != ANP_EXPECTED_HEADER or fingerprint != ANP_EXPECTED_LAYOUT_FINGERPRINT:
                    raise AnpLayoutDriftError(fingerprint)
                rows: list[AnpRawRow] = []
                dates = []
                products: set[str] = set()
                units: set[str] = set()
                for line_number, source_row in enumerate(reader, start=2):
                    if None in source_row or set(source_row) != set(ANP_EXPECTED_HEADER):
                        raise ValueError("ANP CSV layout drift: row has an unexpected column count")
                    payload = {column: source_row[column] or "" for column in ANP_EXPECTED_HEADER}
                    encoded = json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    rows.append(
                        AnpRawRow(
                            line_number=line_number,
                            payload=payload,
                            row_hash=hashlib.sha256(encoded).hexdigest(),
                        )
                    )
                    try:
                        dates.append(datetime.strptime(payload["Data da Coleta"].strip(), "%d/%m/%Y").date())
                    except ValueError as exc:
                        raise ValueError(f"ANP CSV has an invalid collection date at line {line_number}") from exc
                    products.add(payload["Produto"].strip())
                    units.add(payload["Unidade de Medida"].strip())
        except UnicodeDecodeError as exc:
            raise ValueError("ANP CSV encoding is not an audited UTF-8 variant") from exc
        if not rows:
            raise ValueError("ANP CSV has no data rows")
        return ParsedAnpAsset(
            asset=asset,
            layout_fingerprint=fingerprint,
            period_start=min(dates),
            period_end=max(dates),
            rows=tuple(rows),
            technical_metadata={
                "encoding": "utf-8-sig",
                "delimiter": ";",
                "parser_version": ANP_PARSER_VERSION,
                "row_count": len(rows),
                "products": sorted(products),
                "units": sorted(units),
            },
        )
