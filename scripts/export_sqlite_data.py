from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sqlalchemy import create_engine

from database_migration_common import (
    CANONICAL_SQLITE_PATH,
    DATABASE_SCHEMA_VERSION,
    EXPORT_FORMAT_VERSION,
    FUNCTIONAL_VERSIONS,
    database_snapshot,
    expected_schema_contract,
    expected_table_order,
    sha256_file,
    utc_timestamp,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "data-migration" / EXPORT_FORMAT_VERSION


def export_sqlite_database(
    database_path: Path,
    output_directory: Path,
    *,
    require_canonical: bool = True,
    overwrite: bool = False,
) -> dict:
    database_path = database_path.resolve()
    output_directory = output_directory.resolve()
    if require_canonical and database_path != CANONICAL_SQLITE_PATH:
        raise ValueError("A exportacao oficial aceita somente o SQLite canonico.")
    if not database_path.is_file():
        raise FileNotFoundError(f"Banco SQLite nao encontrado: {database_path}")
    if output_directory.exists():
        if not overwrite:
            raise FileExistsError(
                "Diretorio de exportacao ja existe. Use --overwrite conscientemente."
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True)

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        snapshot = database_snapshot(engine)
    finally:
        engine.dispose()

    expected = expected_table_order()
    missing_tables = [name for name in expected if name not in snapshot]
    if missing_tables:
        raise ValueError(
            "Schema SQLite incompleto: " + ", ".join(missing_tables)
        )

    table_files = {}
    for table_name in expected:
        output_path = output_directory / f"{table_name}.jsonl"
        with output_path.open("w", encoding="utf-8", newline="\n") as stream:
            for row in snapshot[table_name]:
                stream.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
        table_files[table_name] = {
            "file": output_path.name,
            "rows": len(snapshot[table_name]),
            "sha256": sha256_file(output_path),
        }

    manifest = {
        "format_version": EXPORT_FORMAT_VERSION,
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "generated_at": utc_timestamp(),
        "source": {
            "engine": "sqlite",
            "canonical": database_path == CANONICAL_SQLITE_PATH,
            "database_sha256": sha256_file(database_path),
        },
        "functional_versions": FUNCTIONAL_VERSIONS,
        "table_order": expected,
        "schema": expected_schema_contract(),
        "tables": table_files,
    }
    manifest_path = output_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "exported",
        "output_directory": str(output_directory),
        "manifest": str(manifest_path),
        "tables_exported": len(table_files),
        "rows_exported": sum(item["rows"] for item in table_files.values()),
        "counts": {
            name: details["rows"] for name, details in table_files.items()
        },
    }
    (output_directory / "export-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta o SQLite canonico para o formato intermediario versionado."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = export_sqlite_database(
        CANONICAL_SQLITE_PATH,
        args.output,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
