from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402
from app.database import (  # noqa: E402
    DATABASE_SETTINGS,
    EXPECTED_ALEMBIC_HEAD,
    SessionLocal,
    current_migration_revision,
    engine,
)
from app.repository import create_motorcycle, ensure_seed_data  # noqa: E402
from app.sample_data import VEHICLES as SAMPLE_VEHICLES  # noqa: E402
from scripts.database_migration_common import (  # noqa: E402
    Base,
    database_snapshot,
    expected_table_order,
    orphan_references,
    safe_database_url,
    table_row_counts,
)
from scripts.seed_motorcycles import (  # noqa: E402
    load_demonstration_payloads,
    logical_identity,
)


BOOTSTRAP_VERSION = "homologation-demo-v1"
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "dist" / "validation" / "homologation-bootstrap-report.json"
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_target(database_url: str) -> dict:
    parsed = make_url(database_url)
    return {
        "dialect": parsed.get_backend_name(),
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
    }


def _reset_postgresql_sequences(connection, table_names: list[str]) -> list[str]:
    reset = []
    for table_name in table_names:
        table = Base.metadata.tables.get(table_name)
        if table is None or "id" not in table.c or not table.c.id.primary_key:
            continue
        quoted_table = connection.dialect.identifier_preparer.quote(table_name)
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        ).scalar_one_or_none()
        if not sequence_name:
            continue
        connection.execute(
            text(
                "SELECT setval("
                "CAST(:sequence_name AS regclass), "
                f"COALESCE((SELECT MAX(id) FROM {quoted_table}), 1), "
                f"(SELECT COUNT(*) > 0 FROM {quoted_table})"
                ")"
            ),
            {"sequence_name": sequence_name},
        )
        reset.append(table_name)
    return reset


def _available_schema(configured_engine: Engine) -> tuple[list[str], list[str]]:
    available = set(inspect(configured_engine).get_table_names())
    expected = expected_table_order()
    missing = [table_name for table_name in expected if table_name not in available]
    return expected, missing


def _bootstrap_marker_exists(db: Session) -> bool:
    return (
        db.get(models.SigraSchemaMigration, BOOTSTRAP_VERSION)
        is not None
    )


def _application_row_total(counts: dict[str, int]) -> int:
    return sum(
        count
        for table_name, count in counts.items()
        if table_name != models.SigraSchemaMigration.__tablename__
    )


def _duplicate_car_ids(db: Session) -> list[int]:
    expected_ids = [vehicle.id for vehicle in SAMPLE_VEHICLES]
    rows = db.execute(
        select(models.Vehicle.id, func.count(models.Vehicle.id))
        .where(models.Vehicle.id.in_(expected_ids))
        .group_by(models.Vehicle.id)
        .having(func.count(models.Vehicle.id) > 1)
    ).all()
    return [int(row[0]) for row in rows]


def _duplicate_motorcycle_identities(db: Session) -> list[dict]:
    identities = [
        logical_identity(record)
        for record in db.query(models.Motorcycle).all()
    ]
    return [
        {
            "brand": identity[0],
            "model": identity[1],
            "version": identity[2],
            "year": identity[3],
            "market_condition": identity[4],
            "count": count,
        }
        for identity, count in Counter(identities).items()
        if count > 1
    ]


def _canonical_data_issues(db: Session) -> list[str]:
    issues = []
    expected_car_ids = {vehicle.id for vehicle in SAMPLE_VEHICLES}
    actual_car_ids = {
        int(vehicle_id)
        for (vehicle_id,) in db.execute(
            select(models.Vehicle.id).where(models.Vehicle.vehicle_type == "car")
        )
    }
    if actual_car_ids != expected_car_ids:
        issues.append(
            "O catalogo de automoveis nao corresponde ao seed demonstrativo versionado."
        )

    expected_motorcycles = {
        logical_identity(payload) for payload in load_demonstration_payloads()
    }
    actual_motorcycles = {
        logical_identity(record)
        for record in db.query(models.Motorcycle).all()
    }
    if actual_motorcycles != expected_motorcycles:
        issues.append(
            "O catalogo de motocicletas nao corresponde ao seed demonstrativo versionado."
        )
    return issues


def inspect_homologation_database(
    configured_engine: Engine,
    session_factory,
) -> dict:
    table_names, missing_tables = _available_schema(configured_engine)
    migration_revision = current_migration_revision(configured_engine)
    counts = (
        table_row_counts(configured_engine)
        if not missing_tables
        else {}
    )
    with session_factory() as db:
        marker_exists = (
            _bootstrap_marker_exists(db)
            if not missing_tables
            else False
        )
    return {
        "database_url": safe_database_url(str(configured_engine.url)),
        "database_target": database_target(str(configured_engine.url)),
        "database_dialect": configured_engine.dialect.name,
        "migration_revision": migration_revision,
        "expected_migration_revision": EXPECTED_ALEMBIC_HEAD,
        "schema_tables_expected": len(table_names),
        "schema_tables_missing": missing_tables,
        "table_counts": counts,
        "application_rows": _application_row_total(counts),
        "bootstrap_version": BOOTSTRAP_VERSION,
        "bootstrap_marker_exists": marker_exists,
    }


def bootstrap_homologation_data(
    configured_engine: Engine,
    session_factory,
    *,
    confirm: bool = False,
    require_postgresql: bool = True,
) -> dict:
    report = inspect_homologation_database(configured_engine, session_factory)
    report.update(
        {
            "generated_at": utc_timestamp(),
            "confirmed": bool(confirm),
            "database_modified": False,
            "expected_demo_cars": len(SAMPLE_VEHICLES),
            "expected_demo_motorcycles": len(load_demonstration_payloads()),
        }
    )

    if require_postgresql and configured_engine.dialect.name != "postgresql":
        raise ValueError("O bootstrap de homologacao exige PostgreSQL.")
    if report["migration_revision"] != EXPECTED_ALEMBIC_HEAD:
        raise ValueError(
            "O schema nao esta no Alembic head esperado. Execute a migration antes do bootstrap."
        )
    if report["schema_tables_missing"]:
        raise ValueError(
            "O schema esta incompleto: "
            + ", ".join(report["schema_tables_missing"])
        )

    if report["bootstrap_marker_exists"]:
        with session_factory() as db:
            issues = _canonical_data_issues(db)
            duplicate_car_ids = _duplicate_car_ids(db)
            duplicate_motorcycles = _duplicate_motorcycle_identities(db)
        orphan_issues = orphan_references(database_snapshot(configured_engine))
        if duplicate_car_ids:
            issues.append("Foram encontrados IDs de automoveis duplicados.")
        if duplicate_motorcycles:
            issues.append("Foram encontradas identidades de motocicletas duplicadas.")
        if orphan_issues:
            issues.append("Foram encontradas referencias orfas.")
        report.update(
            {
                "status": "already_applied" if not issues else "invalid",
                "validation_issues": issues,
                "duplicate_car_ids": duplicate_car_ids,
                "duplicate_motorcycle_identities": duplicate_motorcycles,
                "orphan_references": orphan_issues,
            }
        )
        if issues:
            raise ValueError("; ".join(issues))
        return report

    if report["application_rows"] > 0:
        raise ValueError(
            "O banco possui dados sem o marcador do bootstrap. "
            "A operacao foi recusada para evitar sobrescrita."
        )

    if not confirm:
        report["status"] = "ready"
        return report

    with session_factory() as db:
        ensure_seed_data(db)
        for payload in load_demonstration_payloads():
            create_motorcycle(db, payload, commit=False)
        db.add(models.SigraSchemaMigration(version=BOOTSTRAP_VERSION))
        db.commit()

    sequences_reset = []
    if configured_engine.dialect.name == "postgresql":
        with configured_engine.begin() as connection:
            sequences_reset = _reset_postgresql_sequences(
                connection,
                expected_table_order(),
            )

    final_counts = table_row_counts(configured_engine)
    with session_factory() as db:
        validation_issues = _canonical_data_issues(db)
        duplicate_car_ids = _duplicate_car_ids(db)
        duplicate_motorcycles = _duplicate_motorcycle_identities(db)
    orphan_issues = orphan_references(database_snapshot(configured_engine))
    if duplicate_car_ids:
        validation_issues.append("Foram encontrados IDs de automoveis duplicados.")
    if duplicate_motorcycles:
        validation_issues.append("Foram encontradas identidades de motocicletas duplicadas.")
    if orphan_issues:
        validation_issues.append("Foram encontradas referencias orfas.")
    if validation_issues:
        raise ValueError("; ".join(validation_issues))

    report.update(
        {
            "status": "applied",
            "database_modified": True,
            "table_counts": final_counts,
            "application_rows": _application_row_total(final_counts),
            "bootstrap_marker_exists": True,
            "sequences_reset": sequences_reset,
            "duplicate_car_ids": duplicate_car_ids,
            "duplicate_motorcycle_identities": duplicate_motorcycles,
            "orphan_references": orphan_issues,
            "validation_issues": validation_issues,
        }
    )
    return report


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida e aplica o seed demonstrativo da homologacao."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida schema e conteudo sem modificar o banco (padrao).",
    )
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Confirma a insercao no banco vazio e migrado.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Caminho do relatorio JSON sem segredos.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if DATABASE_SETTINGS.environment != "homologation":
        raise SystemExit(
            "Defina DATABASE_ENV=homologation antes de executar o bootstrap."
        )
    try:
        report = bootstrap_homologation_data(
            engine,
            SessionLocal,
            confirm=args.confirm,
        )
    except ValueError as error:
        diagnostic = {
            "status": "blocked",
            "generated_at": utc_timestamp(),
            "bootstrap_version": BOOTSTRAP_VERSION,
            "database_url": safe_database_url(str(engine.url)),
            "database_target": database_target(str(engine.url)),
            "error": str(error),
        }
        write_report(diagnostic, args.output.resolve())
        print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
        raise SystemExit(1) from error

    write_report(report, args.output.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
