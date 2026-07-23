import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, delete, or_, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models
from app.database import SessionLocal, create_database, engine
from app.repository import create_motorcycle
from app.schemas import MotorcycleCreate


DATA_FILE = BACKEND_DIR / "data" / "motorcycles.demo.json"
NORMALIZATION_LOG = PROJECT_ROOT / "tmp" / "motorcycle-demo-normalization.jsonl"
DEMONSTRATION_SOURCE_NAME = "Base demonstrativa SIGRA"


def _demonstration_filter():
    return (models.Motorcycle.is_demonstration.is_(True)) | (
        models.Motorcycle.data_source == "demonstration"
    )


def _real_record_filter():
    return and_(
        models.Motorcycle.is_demonstration.is_not(True),
        or_(
            models.Motorcycle.data_source.is_(None),
            models.Motorcycle.data_source != "demonstration",
        ),
    )


def _normalized_identity_value(value) -> str:
    if value is None:
        return ""
    raw_value = getattr(value, "value", value)
    return re.sub(r"\s+", " ", str(raw_value)).strip().casefold()


def logical_identity(record) -> tuple[str, str, str, int, str]:
    def value(field):
        if isinstance(record, dict):
            return record.get(field)
        return getattr(record, field, None)

    return (
        _normalized_identity_value(value("brand")),
        _normalized_identity_value(value("model")),
        _normalized_identity_value(value("version")),
        int(value("year")),
        _normalized_identity_value(value("market_condition")),
    )


def logical_record_key(record) -> str:
    return "motorcycle:" + "|".join(str(value) for value in logical_identity(record))


def load_demonstration_payloads() -> list[MotorcycleCreate]:
    raw_records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError("O seed demonstrativo deve conter uma lista nao vazia.")

    payloads = [MotorcycleCreate.model_validate(record) for record in raw_records]
    identities = [logical_identity(payload) for payload in payloads]
    duplicate_identities = [
        identity for identity, count in Counter(identities).items() if count > 1
    ]
    if duplicate_identities:
        raise ValueError(
            "O seed demonstrativo possui identidades logicas duplicadas: "
            f"{duplicate_identities}"
        )

    record_keys = [logical_record_key(payload) for payload in payloads]
    if len(record_keys) != len(set(record_keys)):
        raise ValueError("O seed demonstrativo possui record_key duplicado.")

    for payload in payloads:
        if payload.data_source != "demonstration" or not payload.is_demonstration:
            raise ValueError(
                f"{payload.brand} {payload.model} nao esta marcado como demonstrativo."
            )
        primary_groups = [
            source.data_group.value for source in payload.data_sources if source.is_primary
        ]
        if len(primary_groups) != len(set(primary_groups)):
            raise ValueError(
                f"{payload.brand} {payload.model} possui fonte principal duplicada por grupo."
            )
    return payloads


def _record_summary(record: models.Motorcycle) -> dict:
    return {
        "id": record.id,
        "record_key": logical_record_key(record),
        "brand": record.brand,
        "model": record.model,
        "version": record.version,
        "year": record.year,
        "market_condition": record.market_condition,
        "is_demonstration": bool(record.is_demonstration),
        "data_source": record.data_source,
        "related": {
            "sources": len(record.data_sources),
            "derived_metrics": len(record.derived_metrics),
            "economic_estimates": len(record.economic_estimates),
        },
    }


def build_demo_rebuild_plan(db) -> dict:
    payloads = load_demonstration_payloads()
    demo_records = (
        db.query(models.Motorcycle)
        .filter(_demonstration_filter())
        .order_by(models.Motorcycle.id)
        .all()
    )
    real_records = (
        db.query(models.Motorcycle)
        .filter(_real_record_filter())
        .order_by(models.Motorcycle.id)
        .all()
    )

    demo_by_identity = defaultdict(list)
    demo_by_record_key = defaultdict(list)
    duplicate_primary_sources = []
    for record in demo_records:
        demo_by_identity[logical_identity(record)].append(record.id)
        demo_by_record_key[logical_record_key(record)].append(record.id)
        primary_groups = Counter(
            source.data_group for source in record.data_sources if source.is_primary
        )
        for data_group, count in primary_groups.items():
            if count > 1:
                duplicate_primary_sources.append(
                    {
                        "motorcycle_id": record.id,
                        "data_group": data_group,
                        "count": count,
                    }
                )

    canonical_identities = {logical_identity(payload) for payload in payloads}
    identity_conflicts = [
        _record_summary(record)
        for record in real_records
        if logical_identity(record) in canonical_identities
    ]
    related_totals = {
        "sources": sum(len(record.data_sources) for record in demo_records),
        "derived_metrics": sum(len(record.derived_metrics) for record in demo_records),
        "economic_estimates": sum(len(record.economic_estimates) for record in demo_records),
    }
    return {
        "mode": "dry-run",
        "database_modified": False,
        "canonical_seed_count": len(payloads),
        "canonical_records": [
            {
                "record_key": logical_record_key(payload),
                "brand": payload.brand,
                "model": payload.model,
                "version": payload.version,
                "year": payload.year,
                "market_condition": (
                    payload.market_condition.value if payload.market_condition else None
                ),
            }
            for payload in payloads
        ],
        "demonstration_found": len(demo_records),
        "demonstration_records": [_record_summary(record) for record in demo_records],
        "duplicate_identities": [
            {"identity": list(identity), "ids": ids}
            for identity, ids in demo_by_identity.items()
            if len(ids) > 1
        ],
        "duplicate_record_keys": [
            {"record_key": record_key, "ids": ids}
            for record_key, ids in demo_by_record_key.items()
            if len(ids) > 1
        ],
        "duplicate_primary_sources": duplicate_primary_sources,
        "identity_conflicts_with_real_records": identity_conflicts,
        "related_totals": related_totals,
        "would_remove": [_record_summary(record) for record in demo_records],
        "would_insert": [
            {
                "record_key": logical_record_key(payload),
                "brand": payload.brand,
                "model": payload.model,
                "version": payload.version,
                "year": payload.year,
            }
            for payload in payloads
        ],
        "cars_before": db.query(models.Vehicle).count(),
        "real_motorcycles_before": len(real_records),
        "real_motorcycle_ids_before": [record.id for record in real_records],
    }


def _create_database_backup() -> Path | None:
    if engine.dialect.name != "sqlite" or engine.url.database in {None, ":memory:"}:
        return None
    source_path = Path(engine.url.database).resolve()
    if not source_path.is_file():
        return None
    backup_directory = source_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_directory / f"pre_demo_rebuild_{timestamp}.db"
    with sqlite3.connect(source_path) as source_connection:
        with sqlite3.connect(backup_path) as backup_connection:
            source_connection.backup(backup_connection)
    return backup_path


def rebuild_demonstration_records(*, persist: bool = False, create_record=None) -> dict:
    create_record = create_record or create_motorcycle
    payloads = load_demonstration_payloads()
    with SessionLocal() as db:
        plan = build_demo_rebuild_plan(db)
        if not persist:
            return plan

        backup_path = _create_database_backup()
        expected_identities = {logical_identity(payload) for payload in payloads}
        real_ids = set(plan["real_motorcycle_ids_before"])
        try:
            for record in db.query(models.Motorcycle).filter(_demonstration_filter()).all():
                db.delete(record)
            db.flush()
            for payload in payloads:
                create_record(db, payload, commit=False)
            db.flush()

            rebuilt_records = (
                db.query(models.Motorcycle)
                .filter(_demonstration_filter())
                .order_by(models.Motorcycle.id)
                .all()
            )
            rebuilt_identities = [logical_identity(record) for record in rebuilt_records]
            if (
                len(rebuilt_records) != len(payloads)
                or len(rebuilt_identities) != len(set(rebuilt_identities))
                or set(rebuilt_identities) != expected_identities
            ):
                raise RuntimeError(
                    "A verificacao final nao encontrou exatamente as quatro identidades canonicas."
                )
            if db.query(models.Vehicle).count() != plan["cars_before"]:
                raise RuntimeError("A quantidade de automoveis mudou durante a reconstrucao.")
            preserved_real_ids = {
                record_id
                for (record_id,) in db.query(models.Motorcycle.id)
                .filter(models.Motorcycle.id.in_(real_ids))
                .all()
            }
            if preserved_real_ids != real_ids:
                raise RuntimeError("Um registro real de motocicleta seria removido.")
            db.commit()
        except Exception:
            db.rollback()
            raise

        rebuilt = build_demo_rebuild_plan(db)
        rebuilt.update(
            {
                "mode": "apply",
                "database_modified": True,
                "backup_path": str(backup_path) if backup_path else None,
                "removed": plan["demonstration_found"],
                "inserted": len(payloads),
                "cars_after": db.query(models.Vehicle).count(),
                "real_motorcycles_after": (
                    db.query(models.Motorcycle).filter(_real_record_filter()).count()
                ),
            }
        )
        return rebuilt


def list_demonstration_records() -> None:
    with SessionLocal() as db:
        records = db.execute(
            text(
                "SELECT id, brand, model, year FROM motorcycles "
                "WHERE is_demonstration = 1 OR data_source = 'demonstration' "
                "ORDER BY brand, model, year"
            )
        ).mappings().all()
    if not records:
        print("Nenhuma motocicleta demonstrativa cadastrada.")
        return
    for record in records:
        print(f"{record['id']}: {record['brand']} {record['model']} ({record['year']})")
    print(f"Total demonstrativo: {len(records)}.")


def insert_demonstration_records() -> None:
    records = load_demonstration_payloads()
    created = 0
    with SessionLocal() as db:
        for payload in records:
            exists = db.execute(
                text(
                    "SELECT id FROM motorcycles "
                    "WHERE lower(trim(brand)) = :brand "
                    "AND lower(trim(model)) = :model "
                    "AND coalesce(lower(trim(version)), '') = :version "
                    "AND year = :year "
                    "AND coalesce(lower(trim(market_condition)), '') = :market_condition"
                ),
                {
                    "brand": _normalized_identity_value(payload.brand),
                    "model": _normalized_identity_value(payload.model),
                    "version": _normalized_identity_value(payload.version),
                    "year": payload.year,
                    "market_condition": _normalized_identity_value(
                        payload.market_condition
                    ),
                },
            ).first()
            if exists is None:
                create_motorcycle(db, payload)
                created += 1
    print(f"Motocicletas demonstrativas criadas: {created}. Total no arquivo: {len(records)}.")


def remove_demonstration_records() -> None:
    with SessionLocal() as db:
        try:
            result = db.execute(
                delete(models.Motorcycle).where(_demonstration_filter())
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    print(f"Motocicletas demonstrativas removidas: {result.rowcount or 0}.")


def _normalized_demo_model(brand: str, model: str) -> str:
    cleaned = re.sub(r"\s+Teste$", "", model, flags=re.IGNORECASE).strip()
    if brand.casefold() == "honda" and cleaned.casefold() == "cb 300f":
        return "CB 300F Twister"
    return cleaned


def build_demonstration_normalization_plan(db) -> list[dict]:
    changes = []
    records = db.query(models.Motorcycle).filter(_demonstration_filter()).all()
    for record in records:
        before = {
            "model": record.model,
            "data_source": record.data_source,
            "source_name": record.source_name,
            "is_demonstration": bool(record.is_demonstration),
            "sources": [
                {"id": source.id, "source_type": source.source_type, "source_name": source.source_name}
                for source in record.data_sources
            ],
        }
        after = {
            "model": _normalized_demo_model(record.brand, record.model),
            "data_source": "demonstration",
            "source_name": "Base demonstrativa SIGRA",
            "is_demonstration": True,
            "sources": [
                {"id": source.id, "source_type": "demonstration", "source_name": "Base demonstrativa SIGRA"}
                for source in record.data_sources
            ],
        }
        if before != after:
            changes.append({"motorcycle_id": record.id, "before": before, "after": after})
    return changes


def normalize_demonstration_records(*, persist: bool = False) -> None:
    with SessionLocal() as db:
        changes = build_demonstration_normalization_plan(db)
        print(json.dumps({"mode": "apply" if persist else "dry-run", "changes": changes}, ensure_ascii=False, indent=2))
        if not persist:
            print(f"Dry-run: {len(changes)} registro(s) demonstrativo(s) seriam normalizados.")
            return
        try:
            for change in changes:
                record = db.get(models.Motorcycle, change["motorcycle_id"])
                record.model = change["after"]["model"]
                record.data_source = "demonstration"
                record.source_name = "Base demonstrativa SIGRA"
                record.is_demonstration = True
                for source in record.data_sources:
                    source.source_type = "demonstration"
                    source.source_name = "Base demonstrativa SIGRA"
            db.commit()
        except Exception:
            db.rollback()
            raise

    if changes:
        NORMALIZATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NORMALIZATION_LOG.open("a", encoding="utf-8") as stream:
            for change in changes:
                stream.write(
                    json.dumps(
                        {"changed_at": datetime.now(timezone.utc).isoformat(), **change},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    print(f"Registros demonstrativos normalizados: {len(changes)}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerencia somente motocicletas demonstrativas do SIGRA.")
    parser.add_argument(
        "action",
        nargs="?",
        choices=("list", "insert", "normalize-demo", "remove"),
        default="insert",
    )
    parser.add_argument(
        "--rebuild-demo",
        action="store_true",
        help="Audita e reconstrói somente os quatro registros demonstrativos canônicos.",
    )
    parser.add_argument(
        "--confirm-demonstration-removal",
        action="store_true",
        help="Confirma a remoção exclusiva de registros data_source=demonstration.",
    )
    normalization_mode = parser.add_mutually_exclusive_group()
    normalization_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista a normalização demonstrativa sem persistir. É o padrão para normalize-demo.",
    )
    normalization_mode.add_argument(
        "--confirm-normalization",
        action="store_true",
        help="Confirma a persistência da normalização apenas em registros demonstrativos.",
    )
    normalization_mode.add_argument(
        "--confirm",
        action="store_true",
        help="Confirma a reconstrução transacional solicitada por --rebuild-demo.",
    )
    args = parser.parse_args()
    create_database()
    if args.rebuild_demo:
        if args.action != "insert":
            parser.error("--rebuild-demo não pode ser combinado com uma ação posicional.")
        report = rebuild_demonstration_records(persist=args.confirm)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not args.confirm:
            print("Dry-run concluído. Use --rebuild-demo --confirm para persistir.")
    elif args.confirm:
        parser.error("--confirm exige --rebuild-demo.")
    elif args.action == "list":
        list_demonstration_records()
    elif args.action == "insert":
        insert_demonstration_records()
    elif args.action == "normalize-demo":
        normalize_demonstration_records(persist=args.confirm_normalization)
    elif not args.confirm_demonstration_removal:
        parser.error("A remoção exige --confirm-demonstration-removal.")
    else:
        remove_demonstration_records()


if __name__ == "__main__":
    main()
