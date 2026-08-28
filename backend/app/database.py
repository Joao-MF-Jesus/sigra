from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import (
    DEFAULT_DATABASE_PATH,
    DatabaseSettings,
    load_database_settings,
    normalize_database_url,
)

DATABASE_SETTINGS = load_database_settings()
DATABASE_URL = DATABASE_SETTINGS.url
EXPECTED_ALEMBIC_HEAD = "20260811_0011"


def resolve_database_url(configured_url: str | None = None) -> str:
    """Compatibilidade publica para scripts e testes anteriores."""
    return normalize_database_url(configured_url)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_database_engine(settings: DatabaseSettings) -> Engine:
    options: dict[str, object] = {
        "echo": settings.echo,
        "pool_pre_ping": True,
    }
    if settings.is_sqlite:
        options["connect_args"] = {"check_same_thread": False}
        if settings.url.endswith(":memory:"):
            options["poolclass"] = StaticPool
    else:
        connect_args = {"options": "-c timezone=UTC"}
        if settings.ssl_required:
            connect_args["sslmode"] = "require"
        options.update(
            {
                "connect_args": connect_args,
                "pool_size": settings.pool_size,
                "max_overflow": settings.max_overflow,
                "pool_timeout": settings.pool_timeout,
                "pool_recycle": settings.pool_recycle,
            }
        )
    configured_engine = create_engine(settings.url, **options)
    if settings.is_sqlite:
        event.listen(
            configured_engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )
    return configured_engine


engine = create_database_engine(DATABASE_SETTINGS)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_database() -> None:
    if not DATABASE_SETTINGS.bootstrap_schema:
        raise RuntimeError(
            "Criacao automatica do schema esta desativada neste ambiente. "
            "Execute as migrations Alembic."
        )
    from app import models
    from app.migrations import (
        apply_motorcycle_foundation_migration,
        apply_motorcycle_hardening_migration,
        apply_motorcycle_spec_v1_migration,
        apply_motorcycle_schema_v03_migration,
        apply_motorcycle_schema_v031_migration,
        backup_database_before_motorcycle_hardening,
        backup_database_before_motorcycle_migration,
        backup_database_before_motorcycle_spec_v1,
        backup_database_before_motorcycle_schema_v03,
    )

    backup_database_before_motorcycle_migration(engine)
    backup_database_before_motorcycle_hardening(engine)
    backup_database_before_motorcycle_spec_v1(engine)
    backup_database_before_motorcycle_schema_v03(engine)
    Base.metadata.create_all(bind=engine)
    apply_motorcycle_foundation_migration(engine)
    apply_motorcycle_hardening_migration(engine)
    apply_motorcycle_spec_v1_migration(engine)
    apply_motorcycle_schema_v03_migration(engine)
    apply_motorcycle_schema_v031_migration(engine)
    if DATABASE_SETTINGS.is_sqlite:
        with engine.begin() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("vehicles")}
            migrations = {
                "image_url": "ALTER TABLE vehicles ADD COLUMN image_url VARCHAR(240) NOT NULL DEFAULT ''",
                "category": "ALTER TABLE vehicles ADD COLUMN category VARCHAR(60) NOT NULL DEFAULT 'compact'",
                "segment_level": "ALTER TABLE vehicles ADD COLUMN segment_level INTEGER NOT NULL DEFAULT 2",
                "comfort_score": "ALTER TABLE vehicles ADD COLUMN comfort_score FLOAT NOT NULL DEFAULT 60",
                "space_score": "ALTER TABLE vehicles ADD COLUMN space_score FLOAT NOT NULL DEFAULT 60",
                "safety_score": "ALTER TABLE vehicles ADD COLUMN safety_score FLOAT NOT NULL DEFAULT 60",
                "urban_score": "ALTER TABLE vehicles ADD COLUMN urban_score FLOAT NOT NULL DEFAULT 70",
                "road_score": "ALTER TABLE vehicles ADD COLUMN road_score FLOAT NOT NULL DEFAULT 60",
                "family_score": "ALTER TABLE vehicles ADD COLUMN family_score FLOAT NOT NULL DEFAULT 60",
                "app_score": "ALTER TABLE vehicles ADD COLUMN app_score FLOAT NOT NULL DEFAULT 60",
            }
            for column_name, statement in migrations.items():
                if column_name not in columns:
                    connection.execute(text(statement))


def check_database_connection() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def current_migration_revision(
    configured_engine: Engine | None = None,
) -> str | None:
    target_engine = configured_engine or engine
    inspector = inspect(target_engine)
    if "alembic_version" not in inspector.get_table_names():
        return None
    with target_engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


def migration_is_up_to_date(
    configured_engine: Engine | None = None,
) -> bool:
    return (
        current_migration_revision(configured_engine)
        == EXPECTED_ALEMBIC_HEAD
    )
