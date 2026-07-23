from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import Engine, inspect, text


MOTORCYCLE_FOUNDATION_VERSION = "0.1.0"
MOTORCYCLE_HARDENING_VERSION = "0.1.1"
MOTORCYCLE_SPEC_V1_VERSION = "0.2.0"
MOTORCYCLE_SCHEMA_V03_VERSION = "0.3.0"
MOTORCYCLE_SCHEMA_V031_VERSION = "0.3.1"

MOTORCYCLE_TRACEABILITY_COLUMNS = {
    "source_name": "ALTER TABLE motorcycles ADD COLUMN source_name VARCHAR(160)",
    "source_reference": "ALTER TABLE motorcycles ADD COLUMN source_reference VARCHAR(240)",
    "source_url": "ALTER TABLE motorcycles ADD COLUMN source_url VARCHAR(500)",
    "source_collected_at": "ALTER TABLE motorcycles ADD COLUMN source_collected_at DATETIME",
    "source_reference_date": "ALTER TABLE motorcycles ADD COLUMN source_reference_date DATE",
    "last_verified_at": "ALTER TABLE motorcycles ADD COLUMN last_verified_at DATETIME",
}


def _sqlite_database_path(engine: Engine) -> Path | None:
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        return None
    return Path(engine.url.database).resolve()


def motorcycle_foundation_migration_required(engine: Engine) -> bool:
    inspector = inspect(engine)
    if "vehicles" not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns("vehicles")}
    return "vehicle_type" not in columns


def backup_database_before_motorcycle_migration(engine: Engine) -> Path | None:
    database_path = _sqlite_database_path(engine)
    if database_path is None or not database_path.exists() or not motorcycle_foundation_migration_required(engine):
        return None
    backup_path = database_path.with_suffix(database_path.suffix + ".pre-motorcycles-v0.1.0.bak")
    if not backup_path.exists():
        shutil.copy2(database_path, backup_path)
    return backup_path


def motorcycle_hardening_migration_required(engine: Engine) -> bool:
    inspector = inspect(engine)
    if "motorcycles" not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns("motorcycles")}
    return any(name not in columns for name in MOTORCYCLE_TRACEABILITY_COLUMNS)


def backup_database_before_motorcycle_hardening(engine: Engine) -> Path | None:
    database_path = _sqlite_database_path(engine)
    if database_path is None or not database_path.exists() or not motorcycle_hardening_migration_required(engine):
        return None
    backup_path = database_path.with_suffix(database_path.suffix + ".pre-motorcycles-v0.1.1.bak")
    if not backup_path.exists():
        shutil.copy2(database_path, backup_path)
    return backup_path


def motorcycle_spec_v1_migration_required(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "motorcycles" not in tables:
        return False
    required_tables = {
        "motorcycle_objective_specifications",
        "motorcycle_data_sources",
        "motorcycle_derived_metrics",
        "sigra_schema_migrations",
    }
    if not required_tables.issubset(tables):
        return True
    columns = {column["name"]: column for column in inspector.get_columns("motorcycles")}
    if any(name not in columns for name in ("version", "market_condition", "fuel_type", "price_reference_date")):
        return True
    return any(not columns[name].get("nullable", True) for name in ("reliability_score", "parts_availability_score", "depreciation_rate"))


def backup_database_before_motorcycle_spec_v1(engine: Engine) -> Path | None:
    database_path = _sqlite_database_path(engine)
    if database_path is None or not database_path.exists() or not motorcycle_spec_v1_migration_required(engine):
        return None
    backup_path = database_path.with_suffix(database_path.suffix + ".pre-motorcycles-v0.2.0.bak")
    if not backup_path.exists():
        shutil.copy2(database_path, backup_path)
    return backup_path


def motorcycle_schema_v03_migration_required(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "motorcycles" not in tables:
        return False
    if "motorcycle_economic_estimates" not in tables:
        return True
    columns = {column["name"]: column for column in inspector.get_columns("motorcycles")}
    if "is_demonstration" not in columns:
        return True
    if any(
        name not in columns or not columns[name].get("nullable", True)
        for name in ("data_source", "data_confidence", "annual_maintenance_cost")
    ):
        return True
    if "sigra_schema_migrations" not in tables:
        return True
    with engine.connect() as connection:
        registered = connection.execute(
            text("SELECT 1 FROM sigra_schema_migrations WHERE version = :version"),
            {"version": MOTORCYCLE_SCHEMA_V03_VERSION},
        ).first()
    return registered is None


def backup_database_before_motorcycle_schema_v03(engine: Engine) -> Path | None:
    database_path = _sqlite_database_path(engine)
    if database_path is None or not database_path.exists() or not motorcycle_schema_v03_migration_required(engine):
        return None
    backup_path = database_path.with_suffix(database_path.suffix + ".pre-motorcycles-v0.3.0.bak")
    if not backup_path.exists():
        shutil.copy2(database_path, backup_path)
    return backup_path


def apply_motorcycle_foundation_migration(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "vehicles" not in tables:
        return {"version": MOTORCYCLE_FOUNDATION_VERSION, "applied": False, "cars_updated": 0}
    columns = {column["name"] for column in inspector.get_columns("vehicles")}
    applied = False
    with engine.begin() as connection:
        if "vehicle_type" not in columns:
            connection.execute(
                text("ALTER TABLE vehicles ADD COLUMN vehicle_type VARCHAR(20) NOT NULL DEFAULT 'car'")
            )
            applied = True
        result = connection.execute(
            text("UPDATE vehicles SET vehicle_type = 'car' WHERE vehicle_type IS NULL OR vehicle_type = ''")
        )
    return {
        "version": MOTORCYCLE_FOUNDATION_VERSION,
        "applied": applied,
        "cars_updated": max(0, int(result.rowcount or 0)),
    }


def apply_motorcycle_hardening_migration(engine: Engine) -> dict[str, object]:
    inspector = inspect(engine)
    if "motorcycles" not in inspector.get_table_names():
        return {"version": MOTORCYCLE_HARDENING_VERSION, "applied": False, "columns_added": []}
    columns = {column["name"] for column in inspector.get_columns("motorcycles")}
    added = []
    with engine.begin() as connection:
        for name, statement in MOTORCYCLE_TRACEABILITY_COLUMNS.items():
            if name not in columns:
                connection.execute(text(statement))
                added.append(name)
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_motorcycles_brand_model_year ON motorcycles (brand, model, year)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_motorcycles_data_source ON motorcycles (data_source)")
        )
    return {
        "version": MOTORCYCLE_HARDENING_VERSION,
        "applied": bool(added),
        "columns_added": added,
    }


def _rebuild_sqlite_motorcycles_v020(engine: Engine) -> bool:
    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("motorcycles")}
    new_columns = ("version", "market_condition", "fuel_type", "price_reference_date")
    requires_rebuild = any(name not in columns for name in new_columns) or any(
        not columns[name].get("nullable", True)
        for name in ("reliability_score", "parts_availability_score", "depreciation_rate")
    )
    if not requires_rebuild:
        return False

    select_optional = {
        name: name if name in columns else f"NULL AS {name}"
        for name in new_columns
    }
    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute("DROP TABLE IF EXISTS motorcycles_v020")
        cursor.execute(
            """
            CREATE TABLE motorcycles_v020 (
                id INTEGER NOT NULL PRIMARY KEY,
                brand VARCHAR(80) NOT NULL,
                model VARCHAR(120) NOT NULL,
                year INTEGER NOT NULL,
                price FLOAT NOT NULL,
                city_consumption FLOAT NOT NULL,
                road_consumption FLOAT NOT NULL,
                annual_maintenance_cost FLOAT NOT NULL,
                reliability_score FLOAT,
                parts_availability_score FLOAT,
                depreciation_rate FLOAT,
                data_source VARCHAR(30) NOT NULL,
                data_confidence FLOAT NOT NULL,
                source_name VARCHAR(160),
                source_reference VARCHAR(240),
                source_url VARCHAR(500),
                source_collected_at DATETIME,
                source_reference_date DATE,
                last_verified_at DATETIME,
                vehicle_type VARCHAR(20) NOT NULL DEFAULT 'motorcycle',
                image_url VARCHAR(240) NOT NULL DEFAULT '',
                version VARCHAR(120),
                market_condition VARCHAR(20),
                fuel_type VARCHAR(30),
                price_reference_date DATE,
                CONSTRAINT ck_motorcycles_price_positive CHECK (price > 0),
                CONSTRAINT ck_motorcycles_city_consumption_positive CHECK (city_consumption > 0),
                CONSTRAINT ck_motorcycles_road_consumption_positive CHECK (road_consumption > 0),
                CONSTRAINT ck_motorcycles_maintenance_nonnegative CHECK (annual_maintenance_cost >= 0),
                CONSTRAINT ck_motorcycles_reliability_range CHECK (reliability_score IS NULL OR reliability_score BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_parts_range CHECK (parts_availability_score IS NULL OR parts_availability_score BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_depreciation_nonnegative CHECK (depreciation_rate IS NULL OR depreciation_rate >= 0),
                CONSTRAINT ck_motorcycles_confidence_range CHECK (data_confidence BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_vehicle_type CHECK (vehicle_type = 'motorcycle')
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO motorcycles_v020 (
                id, brand, model, year, price, city_consumption, road_consumption,
                annual_maintenance_cost, reliability_score, parts_availability_score,
                depreciation_rate, data_source, data_confidence, source_name,
                source_reference, source_url, source_collected_at, source_reference_date,
                last_verified_at, vehicle_type, image_url, version, market_condition,
                fuel_type, price_reference_date
            )
            SELECT
                id, brand, model, year, price, city_consumption, road_consumption,
                annual_maintenance_cost, reliability_score, parts_availability_score,
                depreciation_rate, data_source, data_confidence, source_name,
                source_reference, source_url, source_collected_at, source_reference_date,
                last_verified_at, vehicle_type, image_url,
                {select_optional['version']}, {select_optional['market_condition']},
                {select_optional['fuel_type']}, {select_optional['price_reference_date']}
            FROM motorcycles
            """
        )
        cursor.execute("DROP TABLE motorcycles")
        cursor.execute("ALTER TABLE motorcycles_v020 RENAME TO motorcycles")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_motorcycles_brand_model_year ON motorcycles (brand, model, year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_motorcycles_data_source ON motorcycles (data_source)")
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        raw_connection.close()
    return True


def apply_motorcycle_spec_v1_migration(engine: Engine) -> dict[str, object]:
    from app import models
    from app.database import Base

    inspector = inspect(engine)
    if "motorcycles" not in inspector.get_table_names():
        return {"version": MOTORCYCLE_SPEC_V1_VERSION, "applied": False, "objective_rows": 0, "demonstration_metrics": 0}

    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.MotorcycleObjectiveSpecification.__table__,
            models.MotorcycleDataSource.__table__,
            models.MotorcycleDerivedMetric.__table__,
        ],
    )

    rebuilt = False
    if engine.dialect.name == "sqlite":
        rebuilt = _rebuild_sqlite_motorcycles_v020(engine)
    else:
        with engine.begin() as connection:
            current_columns = {column["name"] for column in inspect(connection).get_columns("motorcycles")}
            for name, sql_type in (
                ("version", "VARCHAR(120)"),
                ("market_condition", "VARCHAR(20)"),
                ("fuel_type", "VARCHAR(30)"),
                ("price_reference_date", "DATE"),
            ):
                if name not in current_columns:
                    connection.execute(text(f"ALTER TABLE motorcycles ADD COLUMN {name} {sql_type}"))
            for name in ("reliability_score", "parts_availability_score", "depreciation_rate"):
                connection.execute(text(f"ALTER TABLE motorcycles ALTER COLUMN {name} DROP NOT NULL"))
        rebuilt = True

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS sigra_schema_migrations ("
                "version VARCHAR(40) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        objective_result = connection.execute(
            text(
                "INSERT OR IGNORE INTO motorcycle_objective_specifications ("
                "motorcycle_id, engine_displacement_cc, motorcycle_category, wet_weight_kg, "
                "seat_height_mm, tank_capacity_l, has_abs) "
                "SELECT motorcycle_id, engine_displacement_cc, motorcycle_category, wet_weight_kg, "
                "seat_height_mm, tank_capacity_l, has_abs FROM motorcycle_specifications"
            )
        ) if engine.dialect.name == "sqlite" else connection.execute(
            text(
                "INSERT INTO motorcycle_objective_specifications ("
                "motorcycle_id, engine_displacement_cc, motorcycle_category, wet_weight_kg, "
                "seat_height_mm, tank_capacity_l, has_abs) "
                "SELECT motorcycle_id, engine_displacement_cc, motorcycle_category, wet_weight_kg, "
                "seat_height_mm, tank_capacity_l, has_abs FROM motorcycle_specifications "
                "ON CONFLICT (motorcycle_id) DO NOTHING"
            )
        )

        metric_fields = (
            ("reliability_score", "m.reliability_score", False),
            ("parts_availability_score", "m.parts_availability_score", False),
            ("urban_score", "s.urban_score", False),
            ("road_score", "s.road_score", False),
            ("passenger_comfort_score", "s.passenger_comfort_score", False),
            ("luggage_score", "s.luggage_score", False),
            ("recommended_experience", "s.recommended_experience", True),
        )
        demonstration_metrics = 0
        for metric_name, expression, is_text in metric_fields:
            value_column = "metric_text_value" if is_text else "metric_value"
            statement = (
                "INSERT OR IGNORE INTO motorcycle_derived_metrics ("
                f"motorcycle_id, metric_name, {value_column}, metric_status, method_version, notes) "
                f"SELECT m.id, :metric_name, {expression}, 'demonstration', 'demonstration-v0', "
                "'Migrado de campo legado demonstrativo; sem efeito decisório.' "
                "FROM motorcycles m LEFT JOIN motorcycle_specifications s ON s.motorcycle_id = m.id "
                f"WHERE m.data_source = 'demonstration' AND {expression} IS NOT NULL"
            )
            if engine.dialect.name != "sqlite":
                statement = statement.replace("INSERT OR IGNORE", "INSERT").replace(
                    "WHERE m.data_source = 'demonstration'",
                    "WHERE m.data_source = 'demonstration'",
                ) + " ON CONFLICT (motorcycle_id, metric_name, method_version) DO NOTHING"
            result = connection.execute(text(statement), {"metric_name": metric_name})
            demonstration_metrics += max(0, int(result.rowcount or 0))

        migration_result = connection.execute(
            text(
                "INSERT OR IGNORE INTO sigra_schema_migrations (version) VALUES (:version)"
                if engine.dialect.name == "sqlite"
                else "INSERT INTO sigra_schema_migrations (version) VALUES (:version) ON CONFLICT (version) DO NOTHING"
            ),
            {"version": MOTORCYCLE_SPEC_V1_VERSION},
        )

    objective_rows = max(0, int(objective_result.rowcount or 0))
    registered = max(0, int(migration_result.rowcount or 0))
    return {
        "version": MOTORCYCLE_SPEC_V1_VERSION,
        "applied": rebuilt or bool(objective_rows or demonstration_metrics or registered),
        "objective_rows": objective_rows,
        "demonstration_metrics": demonstration_metrics,
    }


def _rebuild_sqlite_motorcycles_v030(engine: Engine) -> bool:
    columns = {column["name"]: column for column in inspect(engine).get_columns("motorcycles")}
    requires_rebuild = (
        "is_demonstration" not in columns
        or any(
            name not in columns or not columns[name].get("nullable", True)
            for name in ("data_source", "data_confidence", "annual_maintenance_cost")
        )
    )
    if not requires_rebuild:
        return False

    is_demonstration_expression = (
        "is_demonstration"
        if "is_demonstration" in columns
        else "CASE WHEN data_source = 'demonstration' THEN 1 ELSE 0 END"
    )
    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute("DROP TABLE IF EXISTS motorcycles_v030")
        cursor.execute(
            """
            CREATE TABLE motorcycles_v030 (
                id INTEGER NOT NULL PRIMARY KEY,
                brand VARCHAR(80) NOT NULL,
                model VARCHAR(120) NOT NULL,
                year INTEGER NOT NULL,
                price FLOAT NOT NULL,
                city_consumption FLOAT NOT NULL,
                road_consumption FLOAT NOT NULL,
                annual_maintenance_cost FLOAT,
                reliability_score FLOAT,
                parts_availability_score FLOAT,
                depreciation_rate FLOAT,
                data_source VARCHAR(30),
                data_confidence FLOAT,
                source_name VARCHAR(160),
                source_reference VARCHAR(240),
                source_url VARCHAR(500),
                source_collected_at DATETIME,
                source_reference_date DATE,
                last_verified_at DATETIME,
                vehicle_type VARCHAR(20) NOT NULL DEFAULT 'motorcycle',
                image_url VARCHAR(240) NOT NULL DEFAULT '',
                version VARCHAR(120),
                market_condition VARCHAR(20),
                fuel_type VARCHAR(30),
                price_reference_date DATE,
                is_demonstration BOOLEAN NOT NULL DEFAULT 0,
                CONSTRAINT ck_motorcycles_price_positive CHECK (price > 0),
                CONSTRAINT ck_motorcycles_city_consumption_positive CHECK (city_consumption > 0),
                CONSTRAINT ck_motorcycles_road_consumption_positive CHECK (road_consumption > 0),
                CONSTRAINT ck_motorcycles_maintenance_nonnegative CHECK (annual_maintenance_cost IS NULL OR annual_maintenance_cost >= 0),
                CONSTRAINT ck_motorcycles_reliability_range CHECK (reliability_score IS NULL OR reliability_score BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_parts_range CHECK (parts_availability_score IS NULL OR parts_availability_score BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_depreciation_nonnegative CHECK (depreciation_rate IS NULL OR depreciation_rate >= 0),
                CONSTRAINT ck_motorcycles_confidence_range CHECK (data_confidence IS NULL OR data_confidence BETWEEN 0 AND 100),
                CONSTRAINT ck_motorcycles_vehicle_type CHECK (vehicle_type = 'motorcycle')
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO motorcycles_v030 (
                id, brand, model, year, price, city_consumption, road_consumption,
                annual_maintenance_cost, reliability_score, parts_availability_score,
                depreciation_rate, data_source, data_confidence, source_name,
                source_reference, source_url, source_collected_at, source_reference_date,
                last_verified_at, vehicle_type, image_url, version, market_condition,
                fuel_type, price_reference_date, is_demonstration
            )
            SELECT
                id, brand, model, year, price, city_consumption, road_consumption,
                annual_maintenance_cost, reliability_score, parts_availability_score,
                depreciation_rate, data_source, data_confidence, source_name,
                source_reference, source_url, source_collected_at, source_reference_date,
                last_verified_at, vehicle_type, image_url, version, market_condition,
                fuel_type, price_reference_date, {is_demonstration_expression}
            FROM motorcycles
            """
        )
        cursor.execute("DROP TABLE motorcycles")
        cursor.execute("ALTER TABLE motorcycles_v030 RENAME TO motorcycles")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_motorcycles_brand_model_year ON motorcycles (brand, model, year)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_motorcycles_data_source ON motorcycles (data_source)")
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        raw_connection.close()
    return True


def apply_motorcycle_schema_v03_migration(engine: Engine) -> dict[str, object]:
    from app import models
    from app.database import Base

    if "motorcycles" not in inspect(engine).get_table_names():
        return {"version": MOTORCYCLE_SCHEMA_V03_VERSION, "applied": False, "rebuilt": False}

    rebuilt = False
    if engine.dialect.name == "sqlite":
        rebuilt = _rebuild_sqlite_motorcycles_v030(engine)
    else:
        columns = {column["name"] for column in inspect(engine).get_columns("motorcycles")}
        with engine.begin() as connection:
            if "is_demonstration" not in columns:
                connection.execute(text("ALTER TABLE motorcycles ADD COLUMN is_demonstration BOOLEAN NOT NULL DEFAULT false"))
            connection.execute(text("ALTER TABLE motorcycles ALTER COLUMN data_source DROP NOT NULL"))
            connection.execute(text("ALTER TABLE motorcycles ALTER COLUMN data_confidence DROP NOT NULL"))
            connection.execute(text("ALTER TABLE motorcycles ALTER COLUMN annual_maintenance_cost DROP NOT NULL"))
        rebuilt = True

    Base.metadata.create_all(bind=engine, tables=[models.MotorcycleEconomicEstimate.__table__])
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS sigra_schema_migrations ("
                "version VARCHAR(40) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        registration = connection.execute(
            text(
                "INSERT OR IGNORE INTO sigra_schema_migrations (version) VALUES (:version)"
                if engine.dialect.name == "sqlite"
                else "INSERT INTO sigra_schema_migrations (version) VALUES (:version) ON CONFLICT (version) DO NOTHING"
            ),
            {"version": MOTORCYCLE_SCHEMA_V03_VERSION},
        )
    return {
        "version": MOTORCYCLE_SCHEMA_V03_VERSION,
        "applied": rebuilt or max(0, int(registration.rowcount or 0)) > 0,
        "rebuilt": rebuilt,
        "sources_created": 0,
        "metrics_created": 0,
        "estimates_created": 0,
    }


def apply_motorcycle_schema_v031_migration(engine: Engine) -> dict[str, object]:
    """Register the 0.3.1 contract-only migration without fabricating data."""
    if "motorcycles" not in inspect(engine).get_table_names():
        return {"version": MOTORCYCLE_SCHEMA_V031_VERSION, "applied": False}
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS sigra_schema_migrations ("
                "version VARCHAR(40) PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        registration = connection.execute(
            text(
                "INSERT OR IGNORE INTO sigra_schema_migrations (version) VALUES (:version)"
                if engine.dialect.name == "sqlite"
                else "INSERT INTO sigra_schema_migrations (version) VALUES (:version) ON CONFLICT (version) DO NOTHING"
            ),
            {"version": MOTORCYCLE_SCHEMA_V031_VERSION},
        )
    return {
        "version": MOTORCYCLE_SCHEMA_V031_VERSION,
        "applied": max(0, int(registration.rowcount or 0)) > 0,
    }
