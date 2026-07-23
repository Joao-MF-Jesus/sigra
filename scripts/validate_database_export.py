from __future__ import annotations

import argparse
import json
from pathlib import Path

from database_migration_common import (
    DATABASE_SCHEMA_VERSION,
    EXPORT_FORMAT_VERSION,
    FUNCTIONAL_VERSIONS,
    NONNEGATIVE_MONEY_COLUMNS,
    POSITIVE_MONEY_COLUMNS,
    decode_value,
    expected_schema_contract,
    orphan_references,
    read_export_rows,
    sha256_file,
)


def validate_database_export(
    export_directory: Path,
    *,
    require_canonical_baseline: bool = True,
) -> dict:
    export_directory = export_directory.resolve()
    manifest_path = export_directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("manifest.json nao encontrado.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
        errors.append("format_version inesperada")
    if manifest.get("database_schema_version") != DATABASE_SCHEMA_VERSION:
        errors.append("database_schema_version inesperada")
    if manifest.get("functional_versions") != FUNCTIONAL_VERSIONS:
        errors.append("versoes funcionais divergentes")

    expected_contract = expected_schema_contract()
    snapshot = {}
    counts = {}
    for table_name in manifest.get("table_order", []):
        details = manifest.get("tables", {}).get(table_name, {})
        path = export_directory / str(details.get("file", ""))
        if not path.is_file():
            errors.append(f"{table_name}: arquivo ausente")
            continue
        if sha256_file(path) != details.get("sha256"):
            errors.append(f"{table_name}: checksum divergente")
        rows = read_export_rows(export_directory, table_name)
        snapshot[table_name] = rows
        counts[table_name] = len(rows)
        if len(rows) != details.get("rows"):
            errors.append(f"{table_name}: contagem divergente")

        contract = expected_contract.get(table_name)
        if contract is None:
            errors.append(f"{table_name}: tabela nao reconhecida")
            continue
        seen_primary_keys = set()
        for row_number, row in enumerate(rows, start=1):
            unknown_columns = set(row) - set(contract["columns"])
            if unknown_columns:
                errors.append(
                    f"{table_name}:{row_number}: colunas desconhecidas "
                    + ", ".join(sorted(unknown_columns))
                )
            for column_name, column_contract in contract["columns"].items():
                value = row.get(column_name)
                if value is None and not column_contract["nullable"]:
                    errors.append(
                        f"{table_name}:{row_number}:{column_name}: nulo invalido"
                    )
                if column_contract["money"] and value is not None:
                    if (
                        not isinstance(value, dict)
                        or value.get("$type") != "decimal"
                    ):
                        errors.append(
                            f"{table_name}:{row_number}:{column_name}: "
                            "valor monetario sem Decimal"
                        )
                    else:
                        try:
                            decimal_value = decode_value(value)
                        except (ArithmeticError, TypeError, ValueError):
                            errors.append(
                                f"{table_name}:{row_number}:{column_name}: "
                                "Decimal invalido"
                            )
                        else:
                            money_column = (table_name, column_name)
                            if (
                                money_column in POSITIVE_MONEY_COLUMNS
                                and decimal_value <= 0
                            ):
                                errors.append(
                                    f"{table_name}:{row_number}:{column_name}: "
                                    "valor monetario deve ser positivo"
                                )
                            elif (
                                money_column in NONNEGATIVE_MONEY_COLUMNS
                                and decimal_value < 0
                            ):
                                errors.append(
                                    f"{table_name}:{row_number}:{column_name}: "
                                    "valor monetario deve ser nao negativo"
                                )
            primary_key = tuple(
                json.dumps(row.get(column), sort_keys=True)
                for column in contract["primary_key"]
            )
            if primary_key in seen_primary_keys:
                errors.append(
                    f"{table_name}:{row_number}: chave primaria duplicada"
                )
            seen_primary_keys.add(primary_key)

    orphan_issues = orphan_references(snapshot)
    if orphan_issues:
        errors.extend(
            f"{item['table']}.{item['column']}: referencia orfa"
            for item in orphan_issues
        )

    decoded_vehicles = [
        {key: decode_value(value) for key, value in row.items()}
        for row in snapshot.get("vehicles", [])
    ]
    decoded_motorcycles = [
        {key: decode_value(value) for key, value in row.items()}
        for row in snapshot.get("motorcycles", [])
    ]
    baseline = {
        "cars": len(
            [
                row
                for row in decoded_vehicles
                if row.get("vehicle_type") == "car"
            ]
        ),
        "motorcycles": len(decoded_motorcycles),
        "demonstration_motorcycles": len(
            [row for row in decoded_motorcycles if row.get("is_demonstration")]
        ),
        "real_motorcycles": len(
            [row for row in decoded_motorcycles if not row.get("is_demonstration")]
        ),
        "users": len(snapshot.get("users", [])),
    }
    if require_canonical_baseline:
        expected_baseline = {
            "cars": 34,
            "motorcycles": 5,
            "demonstration_motorcycles": 4,
            "real_motorcycles": 1,
        }
        for key, expected in expected_baseline.items():
            if baseline[key] != expected:
                errors.append(
                    f"baseline {key}: esperado {expected}, obtido {baseline[key]}"
                )
        if baseline["users"] < 1:
            errors.append("baseline users: nenhum usuario exportado")

    report = {
        "status": "valid" if not errors else "invalid",
        "format_version": manifest.get("format_version"),
        "tables_checked": len(snapshot),
        "counts": counts,
        "baseline": baseline,
        "orphan_references": orphan_issues,
        "errors": errors,
    }
    report_path = export_directory / "validation-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida estrutura, tipos, hashes e relacoes de um export SIGRA."
    )
    parser.add_argument("export_directory", type=Path)
    parser.add_argument(
        "--skip-canonical-baseline",
        action="store_true",
        help="Uso exclusivo em fixtures reduzidos de teste.",
    )
    args = parser.parse_args()
    report = validate_database_export(
        args.export_directory,
        require_canonical_baseline=not args.skip_canonical_baseline,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "valid":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
