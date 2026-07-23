from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_database_settings  # noqa: E402
from app.database import Base  # noqa: E402


def migration_status() -> dict:
    settings = load_database_settings()
    engine = create_engine(settings.url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables)
        current_revision = None
        if "alembic_version" in tables:
            with engine.connect() as connection:
                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            config = Config(str(BACKEND_DIR / "alembic.ini"))
            scripts = ScriptDirectory.from_config(config)
            heads = list(scripts.get_heads())
            alembic_available = True
            alembic_error = None
        except Exception as error:
            heads = []
            alembic_available = False
            alembic_error = f"{type(error).__name__}: {error}"
        pending = (
            [head for head in heads if head != current_revision]
            if heads
            else []
        )
        missing_tables = sorted(expected_tables - tables)
        missing_columns = {}
        for table_name in sorted(expected_tables & tables):
            actual_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            expected_columns = set(Base.metadata.tables[table_name].columns.keys())
            missing = sorted(expected_columns - actual_columns)
            if missing:
                missing_columns[table_name] = missing
        return {
            "engine": settings.backend_name,
            "reachable": True,
            "current_revision": current_revision,
            "expected_heads": heads,
            "pending_migrations": pending,
            "alembic_available": alembic_available,
            "alembic_error": alembic_error,
            "schema_compatible": not missing_tables and not missing_columns,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
        }
    finally:
        engine.dispose()


def main() -> None:
    report = migration_status()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if (
        not report["alembic_available"]
        or not report["schema_compatible"]
        or report["pending_migrations"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
