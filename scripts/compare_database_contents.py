from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select, text

from database_migration_common import (
    Base,
    CANONICAL_SQLITE_PATH,
    database_snapshot,
    expected_schema_contract,
    orphan_references,
    safe_database_url,
)


def _primary_key(row: dict, columns: list[str]) -> tuple[str, ...]:
    return tuple(
        json.dumps(row.get(column), ensure_ascii=False, sort_keys=True)
        for column in columns
    )


def _postgresql_sequence_issues(engine) -> list[dict]:
    if engine.dialect.name != "postgresql":
        return []
    issues = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if "id" not in table.c or not table.c.id.primary_key:
                continue
            sequence_name = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                {"table_name": table.name},
            ).scalar_one_or_none()
            if not sequence_name:
                continue
            maximum_id = connection.execute(
                select(table.c.id).order_by(table.c.id.desc()).limit(1)
            ).scalar_one_or_none()
            sequence_value = connection.execute(
                text(
                    "SELECT pg_sequence_last_value("
                    "CAST(:sequence_name AS regclass))"
                ),
                {"sequence_name": sequence_name},
            ).scalar_one_or_none()
            if (
                maximum_id is not None
                and sequence_value is not None
                and int(sequence_value) < int(maximum_id)
            ):
                issues.append(
                    {
                        "table": table.name,
                        "maximum_id": int(maximum_id),
                        "sequence_value": int(sequence_value),
                    }
                )
    return issues


def compare_databases(source_url: str, target_url: str) -> dict:
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url, pool_pre_ping=True)
    try:
        source = database_snapshot(source_engine)
        target = database_snapshot(target_engine)
        contract = expected_schema_contract()
        all_tables = sorted(set(source) | set(target))
        row_count_differences = []
        value_differences = []
        for table_name in all_tables:
            source_rows = source.get(table_name, [])
            target_rows = target.get(table_name, [])
            if len(source_rows) != len(target_rows):
                row_count_differences.append(
                    {
                        "table": table_name,
                        "source": len(source_rows),
                        "target": len(target_rows),
                    }
                )
            primary_key_columns = contract.get(table_name, {}).get(
                "primary_key", []
            )
            source_by_key = {
                _primary_key(row, primary_key_columns): row
                for row in source_rows
            }
            target_by_key = {
                _primary_key(row, primary_key_columns): row
                for row in target_rows
            }
            for key in sorted(set(source_by_key) | set(target_by_key)):
                left = source_by_key.get(key)
                right = target_by_key.get(key)
                if left == right:
                    continue
                if len(value_differences) < 200:
                    value_differences.append(
                        {
                            "table": table_name,
                            "primary_key": list(key),
                            "source": left,
                            "target": right,
                        }
                    )

        source_orphans = orphan_references(source)
        target_orphans = orphan_references(target)
        relation_differences = []
        if source_orphans != target_orphans:
            relation_differences = [
                {"source": source_orphans, "target": target_orphans}
            ]
        source_versions = source.get("sigra_schema_migrations", [])
        target_versions = target.get("sigra_schema_migrations", [])
        version_differences = (
            []
            if source_versions == target_versions
            else [{"source": source_versions, "target": target_versions}]
        )
        sequence_issues = _postgresql_sequence_issues(target_engine)
        equivalent = not any(
            (
                row_count_differences,
                value_differences,
                relation_differences,
                version_differences,
                sequence_issues,
            )
        )
        return {
            "status": "equivalent" if equivalent else "different",
            "source": safe_database_url(source_url),
            "target": safe_database_url(target_url),
            "tables_checked": len(all_tables),
            "source_rows": sum(len(rows) for rows in source.values()),
            "target_rows": sum(len(rows) for rows in target.values()),
            "row_count_differences": row_count_differences,
            "value_differences": value_differences,
            "relation_differences": relation_differences,
            "version_differences": version_differences,
            "sequence_issues": sequence_issues,
        }
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compara o SQLite canonico e o PostgreSQL configurado."
    )
    parser.add_argument(
        "--source-url",
        default=f"sqlite:///{CANONICAL_SQLITE_PATH.as_posix()}",
    )
    parser.add_argument("--target-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/data-migration/database-comparison.json"),
    )
    args = parser.parse_args()
    if not args.target_url:
        parser.error("--target-url ou DATABASE_URL deve ser informado.")
    report = compare_databases(args.source_url, args.target_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "equivalent":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
