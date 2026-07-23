from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import (  # noqa: E402
    DATABASE_SETTINGS,
    DATABASE_URL,
    DEFAULT_DATABASE_PATH,
    current_migration_revision,
    engine,
)


IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".npm-cache",
    ".pnpm-store",
    ".venv",
    "node_modules",
    "__pycache__",
}


def sanitized_database_url(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=True)


def find_sqlite_candidates(root: Path = PROJECT_ROOT) -> list[Path]:
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".bak",
            ".db",
            ".sqlite",
            ".sqlite3",
        }:
            continue
        if any(part in IGNORED_DIRECTORY_NAMES for part in path.relative_to(root).parts):
            continue
        candidates.append(path.resolve())
    return sorted(set(candidates), key=lambda item: str(item).casefold())


def classify_sqlite_candidate(path: Path, root: Path = PROJECT_ROOT) -> str:
    path = path.resolve()
    root = root.resolve()
    canonical = (root / "backend" / "sigra.db").resolve()
    if path == canonical:
        return "canonical"
    if path == (root / "sigra.db").resolve():
        return "legacy_root"

    relative_parts = tuple(part.casefold() for part in path.relative_to(root).parts)
    name = path.name.casefold()
    if "backups" in relative_parts or path.suffix.casefold() == ".bak":
        return "backup"
    if "tmp" in relative_parts or any(
        marker in name
        for marker in ("e2e", "test", "validation", "migration-check", "sigra-copy")
    ):
        return "temporary"
    return "unknown"


def database_diagnostic() -> dict:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    counts = {}
    with engine.connect() as connection:
        for label, table in (("cars", "vehicles"), ("motorcycles", "motorcycles")):
            counts[label] = (
                int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
                if table in tables
                else 0
            )
        schema_versions = (
            [
                str(row[0])
                for row in connection.execute(
                    text("SELECT version FROM sigra_schema_migrations ORDER BY applied_at, version")
                ).all()
            ]
            if "sigra_schema_migrations" in tables
            else []
        )

    sqlite_path = None
    exists = None
    canonical_path = DEFAULT_DATABASE_PATH.resolve()
    if engine.dialect.name == "sqlite" and engine.url.database not in {None, ":memory:"}:
        sqlite_path = str(Path(engine.url.database).resolve())
        exists = Path(engine.url.database).exists()
    candidates = find_sqlite_candidates()
    candidate_details = [
        {
            "path": str(path),
            "classification": classify_sqlite_candidate(path),
            "size_bytes": path.stat().st_size,
        }
        for path in candidates
    ]
    duplicates = [
        item["path"]
        for item in candidate_details
        if item["classification"] in {"legacy_root", "unknown"}
    ]
    return {
        "effective_database_url": sanitized_database_url(DATABASE_URL),
        "database_type": engine.dialect.name,
        "database_environment": DATABASE_SETTINGS.environment,
        "bootstrap_schema": DATABASE_SETTINGS.bootstrap_schema,
        "migration_revision": current_migration_revision(engine),
        "resolved_sqlite_path": sqlite_path,
        "sqlite_file_exists": exists,
        "canonical_development_database": str(canonical_path),
        "vehicle_counts": counts,
        "schema_versions": schema_versions,
        "latest_schema_version": schema_versions[-1] if schema_versions else None,
        "duplicate_database_warning": bool(duplicates),
        "duplicate_database_candidates": duplicates,
        "sqlite_artifacts": candidate_details,
        "legacy_root_database_is_used": sqlite_path == str((PROJECT_ROOT / "sigra.db").resolve()),
    }


def main() -> None:
    print(json.dumps(database_diagnostic(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
