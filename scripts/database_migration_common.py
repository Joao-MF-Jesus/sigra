from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Connection, Engine, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
CANONICAL_SQLITE_PATH = Path(
    os.getenv("SIGRA_CANONICAL_SQLITE_PATH", str(BACKEND_DIR / "sigra.db"))
).expanduser().resolve()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402,F401
from app.database import Base  # noqa: E402


EXPORT_FORMAT_VERSION = "sqlite-export-v1"
DATABASE_SCHEMA_VERSION = "1.0.0"
FUNCTIONAL_VERSIONS = {
    "cars": {"algorithm_version": "2.1.2", "weights_version": "cars-v1"},
    "financing": {
        "module_version": "1.0.3",
        "calculation_method_version": "price-v1.2",
    },
    "motorcycles": {
        "module_version": "0.3.1",
        "algorithm_version": None,
        "weights_version": None,
    },
}
MONEY_COLUMNS = {
    ("vehicles", "price"),
    ("vehicles", "annual_maintenance_cost"),
    ("motorcycles", "price"),
    ("motorcycles", "annual_maintenance_cost"),
    ("motorcycle_economic_estimates", "estimate_value"),
    ("expenses", "amount"),
    ("maintenances", "cost"),
    ("vehicle_reports", "repair_cost"),
    ("part_prices", "price"),
}
POSITIVE_MONEY_COLUMNS = {
    ("vehicles", "price"),
    ("motorcycles", "price"),
    ("part_prices", "price"),
}
NONNEGATIVE_MONEY_COLUMNS = MONEY_COLUMNS - POSITIVE_MONEY_COLUMNS


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_database_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return "sqlite:///<redacted>"
    return f"{parsed.drivername}://<redacted>"


def expected_table_order() -> list[str]:
    # This is the legacy public-data transfer format, not an authentication backup.
    return [table.name for table in Base.metadata.sorted_tables
            if table.name not in {"auth_sessions", "participant_test_runs", "participant_study_sessions", "participant_questionnaires"}]


def expected_schema_contract() -> dict[str, Any]:
    contract: dict[str, Any] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in expected_table_order():
            continue
        foreign_keys = []
        for constraint in table.foreign_key_constraints:
            for element in constraint.elements:
                foreign_keys.append(
                    {
                        "column": element.parent.name,
                        "target_table": element.column.table.name,
                        "target_column": element.column.name,
                    }
                )
        contract[table.name] = {
            "columns": {
                column.name: {
                    "nullable": bool(column.nullable),
                    "primary_key": bool(column.primary_key),
                    "type": str(column.type),
                    "money": (table.name, column.name) in MONEY_COLUMNS,
                }
                for column in table.columns
                if not (table.name == "users" and column.name in {"password_hash", "normalized_email", "role"})
            },
            "primary_key": [column.name for column in table.primary_key.columns],
            "foreign_keys": foreign_keys,
        }
    return contract


def encode_value(table_name: str, column_name: str, value: Any) -> Any:
    if value is None:
        return None
    if (table_name, column_name) in MONEY_COLUMNS:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(
                f"{table_name}.{column_name} nao possui valor monetario valido."
            ) from error
        if not decimal_value.is_finite():
            raise ValueError(
                f"{table_name}.{column_name} nao possui valor monetario finito."
            )
        return {"$type": "decimal", "value": format(decimal_value, "f")}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": format(value, "f")}
    if isinstance(value, (dict, list)):
        return {"$type": "json", "value": value}
    if isinstance(value, bytes):
        return {"$type": "bytes", "value": value.hex()}
    return value


def decode_value(value: Any) -> Any:
    if not isinstance(value, dict) or "$type" not in value:
        return value
    value_type = value.get("$type")
    raw_value = value.get("value")
    if value_type == "decimal":
        return Decimal(str(raw_value))
    if value_type == "date":
        return date.fromisoformat(str(raw_value))
    if value_type == "datetime":
        parsed = datetime.fromisoformat(str(raw_value))
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    if value_type == "json":
        return raw_value
    if value_type == "bytes":
        return bytes.fromhex(str(raw_value))
    raise ValueError(f"Tipo serializado desconhecido: {value_type}")


def canonical_value(table_name: str, column_name: str, value: Any) -> Any:
    encoded = encode_value(table_name, column_name, value)
    if isinstance(encoded, dict) and encoded.get("$type") == "datetime":
        parsed = decode_value(encoded)
        return {"$type": "datetime", "value": parsed.isoformat()}
    if isinstance(encoded, dict) and encoded.get("$type") == "decimal":
        decimal_value = Decimal(encoded["value"]).normalize()
        return {"$type": "decimal", "value": format(decimal_value, "f")}
    return encoded


def read_export_rows(export_directory: Path, table_name: str) -> list[dict]:
    rows = []
    path = export_directory / f"{table_name}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"JSON invalido em {path.name}:{line_number}."
                ) from error
    return rows


def reflected_tables(engine: Engine) -> dict[str, Table]:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return {
        name: metadata.tables[name]
        for name in expected_table_order()
        if name in metadata.tables
    }


def ordered_rows(connection: Connection, table: Table) -> list[dict]:
    allowed = expected_schema_contract()[table.name]["columns"]
    statement = select(*(column for column in table.columns if column.name in allowed))
    primary_key = list(table.primary_key.columns)
    if primary_key:
        statement = statement.order_by(*primary_key)
    return [dict(row._mapping) for row in connection.execute(statement)]


def database_snapshot(engine: Engine) -> dict[str, list[dict]]:
    tables = reflected_tables(engine)
    snapshot = {}
    with engine.connect() as connection:
        for table_name in expected_table_order():
            table = tables.get(table_name)
            if table is None:
                continue
            snapshot[table_name] = [
                {
                    column: canonical_value(table_name, column, value)
                    for column, value in row.items()
                }
                for row in ordered_rows(connection, table)
            ]
    return snapshot


def orphan_references(snapshot: dict[str, list[dict]]) -> list[dict]:
    contract = expected_schema_contract()
    issues = []
    for table_name, table_contract in contract.items():
        rows = snapshot.get(table_name, [])
        for foreign_key in table_contract["foreign_keys"]:
            targets = {
                row.get(foreign_key["target_column"])
                for row in snapshot.get(foreign_key["target_table"], [])
            }
            for row in rows:
                value = row.get(foreign_key["column"])
                if value is not None and value not in targets:
                    issues.append(
                        {
                            "table": table_name,
                            "column": foreign_key["column"],
                            "value": value,
                            "target_table": foreign_key["target_table"],
                        }
                    )
    return issues


def table_row_counts(engine: Engine) -> dict[str, int]:
    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    tables = reflected_tables(engine)
    counts = {}
    with engine.connect() as connection:
        for name in expected_table_order():
            if name in available and name in tables:
                counts[name] = len(ordered_rows(connection, tables[name]))
    return counts
