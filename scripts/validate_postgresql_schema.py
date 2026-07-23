from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import Numeric, create_engine, inspect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_database_settings  # noqa: E402
from app import models  # noqa: E402,F401
from app.database import (  # noqa: E402
    Base,
    EXPECTED_ALEMBIC_HEAD,
    current_migration_revision,
)


def validate_postgresql_schema() -> dict:
    settings = load_database_settings()
    if not settings.is_postgresql:
        raise RuntimeError("A validacao de schema exige PostgreSQL.")

    engine = create_engine(settings.url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        available_tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables)
        if not expected_tables:
            raise RuntimeError(
                "Contrato de schema vazio; models nao foram carregados."
            )
        missing_tables = sorted(expected_tables - available_tables)
        errors = [
            f"tabela ausente: {table_name}"
            for table_name in missing_tables
        ]
        constraints_checked = 0
        indexes_checked = 0
        numeric_columns_checked = 0
        for table_name in sorted(expected_tables & available_tables):
            constraints_checked += int(
                bool(inspector.get_pk_constraint(table_name).get("constrained_columns"))
            )
            constraints_checked += len(
                inspector.get_foreign_keys(table_name)
            )
            constraints_checked += len(
                inspector.get_unique_constraints(table_name)
            )
            constraints_checked += len(
                inspector.get_check_constraints(table_name)
            )
            indexes_checked += len(inspector.get_indexes(table_name))

            reflected_columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            for column in Base.metadata.tables[table_name].columns:
                reflected = reflected_columns.get(column.name)
                if reflected is None:
                    errors.append(
                        f"coluna ausente: {table_name}.{column.name}"
                    )
                    continue
                if isinstance(column.type, Numeric):
                    numeric_columns_checked += 1
                    if not isinstance(reflected["type"], Numeric):
                        errors.append(
                            f"tipo monetario invalido: "
                            f"{table_name}.{column.name}"
                        )
                if bool(reflected["nullable"]) != bool(column.nullable):
                    errors.append(
                        f"nullability divergente: "
                        f"{table_name}.{column.name}"
                    )

        revision = current_migration_revision(engine)
        if revision != EXPECTED_ALEMBIC_HEAD:
            errors.append(
                "revision Alembic divergente do head esperado"
            )
        return {
            "database_engine": engine.dialect.name,
            "status": "passed" if not errors else "failed",
            "current_revision": revision,
            "expected_head": EXPECTED_ALEMBIC_HEAD,
            "migration_up_to_date": revision == EXPECTED_ALEMBIC_HEAD,
            "tables_found": len(expected_tables & available_tables),
            "tables_expected": len(expected_tables),
            "constraints_checked": constraints_checked,
            "indexes_checked": indexes_checked,
            "numeric_columns_checked": numeric_columns_checked,
            "errors": errors,
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida o schema PostgreSQL criado pelo Alembic."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "dist/data-migration/postgresql-schema-report.json"
        ),
    )
    args = parser.parse_args()
    try:
        report = validate_postgresql_schema()
    except Exception as error:
        report = {
            "database_engine": "unknown",
            "status": "failed",
            "error_type": type(error).__name__,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
