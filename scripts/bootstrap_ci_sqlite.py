from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_OUTPUT = PROJECT_ROOT / "tmp" / "sigra-ci-source.db"


def bootstrap_ci_sqlite(output: Path) -> dict:
    output = output.expanduser().resolve()
    canonical_local_database = (BACKEND_DIR / "sigra.db").resolve()
    if output == canonical_local_database:
        raise ValueError(
            "O bootstrap de CI nao pode escrever sobre o SQLite canonico local."
        )
    if output.exists():
        raise FileExistsError(
            f"A fonte SQLite descartavel ja existe: {output}. "
            "Remova-a conscientemente antes de gerar outra."
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{output.as_posix()}"
    os.environ["DATABASE_ENV"] = "development"
    os.environ["FIPE_AUTO_REFRESH"] = "false"
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from app.database import SessionLocal, create_database, engine
    from app.repository import create_motorcycle, ensure_seed_data
    from app.schemas import MotorcycleCreate
    from backend.tests.test_motorcycle_schema_v03 import canonical_payload
    from scripts.seed_motorcycles import insert_demonstration_records

    try:
        create_database()
        with SessionLocal() as db:
            ensure_seed_data(db)
        insert_demonstration_records()
        with SessionLocal() as db:
            create_motorcycle(
                db,
                MotorcycleCreate.model_validate(canonical_payload()),
            )
    finally:
        engine.dispose()

    with sqlite3.connect(output) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        counts = {
            table_name: connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            for table_name in tables
        }

    expected = {
        "vehicles": 34,
        "motorcycles": 5,
        "users": 1,
    }
    mismatches = {
        table_name: {"expected": expected_count, "actual": counts.get(table_name)}
        for table_name, expected_count in expected.items()
        if counts.get(table_name) != expected_count
    }
    if mismatches:
        raise RuntimeError(
            "A fonte SQLite descartavel nao corresponde ao seed versionado: "
            + json.dumps(mismatches, sort_keys=True)
        )

    return {
        "status": "created",
        "purpose": "ci_migration_fixture",
        "database": str(output),
        "tables": len(counts),
        "rows": sum(counts.values()),
        "counts": counts,
        "canonical_local_database_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cria uma fonte SQLite descartavel e reprodutivel para testes de CI."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = bootstrap_ci_sqlite(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
