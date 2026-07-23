from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import EXPECTED_ALEMBIC_HEAD, current_migration_revision
from database_migration_common import (
    Base,
    decode_value,
    expected_table_order,
    read_export_rows,
    safe_database_url,
    utc_timestamp,
)
from validate_database_export import validate_database_export


def _target_counts(connection, table_names: list[str]) -> dict[str, int]:
    metadata_tables = {table.name: table for table in Base.metadata.sorted_tables}
    return {
        name: int(
            connection.execute(
                select(func.count()).select_from(metadata_tables[name])
            ).scalar_one()
        )
        for name in table_names
    }


def _reset_postgresql_sequences(connection, table_names: list[str]) -> list[str]:
    reset = []
    for table_name in table_names:
        table = Base.metadata.tables[table_name]
        if "id" not in table.c or not table.c.id.primary_key:
            continue
        quoted_table = connection.dialect.identifier_preparer.quote(table_name)
        connection.execute(
            text(
                "SELECT setval("
                "pg_get_serial_sequence(:table_name, 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {quoted_table}), 1), "
                f"(SELECT COUNT(*) > 0 FROM {quoted_table})"
                ")"
            ),
            {"table_name": table_name},
        )
        reset.append(table_name)
    return reset


def import_database_export(
    export_directory: Path,
    target_url: str,
    *,
    confirm_import: bool = False,
    allow_non_empty_target: bool = False,
    confirm_non_empty_target: bool = False,
    require_postgresql: bool = True,
    require_canonical_baseline: bool = True,
) -> dict:
    validation = validate_database_export(
        export_directory,
        require_canonical_baseline=require_canonical_baseline,
    )
    if validation["status"] != "valid":
        raise ValueError("Exportacao invalida; importacao recusada.")
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        if require_postgresql and engine.dialect.name != "postgresql":
            raise ValueError("O importador oficial exige um destino PostgreSQL.")
        table_names = expected_table_order()
        available = set(inspect(engine).get_table_names())
        missing = [name for name in table_names if name not in available]
        if missing:
            raise ValueError(
                "Schema de destino incompleto. Execute Alembic: "
                + ", ".join(missing)
            )
        migration_revision = current_migration_revision(engine)
        if (
            require_postgresql
            and migration_revision != EXPECTED_ALEMBIC_HEAD
        ):
            raise ValueError(
                "Revision Alembic do destino nao corresponde ao head esperado."
            )
        with engine.connect() as connection:
            before_counts = _target_counts(connection, table_names)
        non_empty = {name: count for name, count in before_counts.items() if count}
        if non_empty and not (
            allow_non_empty_target and confirm_non_empty_target
        ):
            raise ValueError(
                "Destino nao vazio. Use --allow-non-empty-target e "
                "--confirm-non-empty-target, sem sobrescrita automatica."
            )

        report = {
            "status": "dry-run" if not confirm_import else "imported",
            "generated_at": utc_timestamp(),
            "target": {
                "engine": engine.dialect.name,
                "url": safe_database_url(target_url),
            },
            "target_counts_before": before_counts,
            "destination_empty": not bool(non_empty),
            "table_order": table_names,
            "rows_planned": sum(validation["counts"].values()),
            "counts_planned": validation["counts"],
            "conflicts": [],
            "alembic_revision": migration_revision,
            "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
            "transaction_strategy": "single_transaction",
            "sequences_reset": [],
        }
        if not confirm_import:
            return report

        metadata = Base.metadata
        with engine.begin() as connection:
            for table_name in table_names:
                table = metadata.tables[table_name]
                rows = [
                    {
                        key: decode_value(value)
                        for key, value in row.items()
                    }
                    for row in read_export_rows(export_directory, table_name)
                ]
                if not rows:
                    continue
                primary_keys = list(table.primary_key.columns)
                if non_empty and primary_keys:
                    for row in rows:
                        conditions = [
                            column == row[column.name]
                            for column in primary_keys
                        ]
                        if connection.execute(
                            select(table).where(*conditions).limit(1)
                        ).first():
                            raise ValueError(
                                f"Duplicidade detectada em {table_name}; "
                                "nenhum dado foi sobrescrito."
                            )
                connection.execute(table.insert(), rows)
            if engine.dialect.name == "postgresql":
                report["sequences_reset"] = _reset_postgresql_sequences(
                    connection, table_names
                )
            after_counts = _target_counts(connection, table_names)
            for table_name, imported_count in validation["counts"].items():
                expected = before_counts[table_name] + imported_count
                if after_counts[table_name] != expected:
                    raise RuntimeError(
                        f"Contagem divergente em {table_name}: "
                        f"{after_counts[table_name]} != {expected}"
                    )
        report["target_counts_after"] = after_counts
        return report
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa um export validado no PostgreSQL em transacao unica."
    )
    parser.add_argument("export_directory", type=Path)
    parser.add_argument("--confirm-import", action="store_true")
    parser.add_argument("--allow-non-empty-target", action="store_true")
    parser.add_argument("--confirm-non-empty-target", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.confirm_non_empty_target and not args.allow_non_empty_target:
        parser.error(
            "--confirm-non-empty-target exige --allow-non-empty-target."
        )
    target_url = os.getenv("DATABASE_URL", "").strip()
    if not target_url:
        parser.error("DATABASE_URL PostgreSQL deve ser configurada.")
    report = import_database_export(
        args.export_directory,
        target_url,
        confirm_import=args.confirm_import,
        allow_non_empty_target=args.allow_non_empty_target,
        confirm_non_empty_target=args.confirm_non_empty_target,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
