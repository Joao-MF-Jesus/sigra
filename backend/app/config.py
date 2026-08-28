from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
)
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DATABASE_PATH = (BACKEND_DIR / "sigra.db").resolve()
DATABASE_ENVIRONMENTS = {
    "development",
    "test",
    "integration",
    "homologation",
    "production",
}
PUBLISHED_DATABASE_ENVIRONMENTS = {"homologation", "production"}


def _boolean(
    value: str | bool | None,
    *,
    default: bool,
    variable_name: str,
) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{variable_name} deve ser true ou false.")


def _positive_integer(
    value: str | int | None,
    *,
    default: int,
    variable_name: str,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{variable_name} deve ser um inteiro.") from error
    if parsed <= 0:
        raise ValueError(f"{variable_name} deve ser maior que zero.")
    return parsed


def _nonnegative_integer(
    value: str | int | None,
    *,
    default: int,
    variable_name: str,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{variable_name} deve ser um inteiro.") from error
    if parsed < 0:
        raise ValueError(f"{variable_name} deve ser maior ou igual a zero.")
    return parsed


def normalize_database_url(
    configured_url: str | None,
    *,
    backend_dir: Path = BACKEND_DIR,
) -> str:
    raw_url = (configured_url or "").strip()
    if not raw_url:
        raw_url = f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"
    try:
        url = make_url(raw_url)
    except ArgumentError as error:
        raise ValueError("DATABASE_URL invalida.") from error

    if url.drivername in {"postgres", "postgresql", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("DATABASE_URL deve usar SQLite ou PostgreSQL.")

    if url.get_backend_name() == "sqlite":
        database = url.database
        if not database:
            raise ValueError("DATABASE_URL SQLite deve informar o banco.")
        if database != ":memory:":
            database_path = Path(database)
            if not database_path.is_absolute():
                first_part = (
                    database_path.parts[0].casefold()
                    if database_path.parts
                    else ""
                )
                base = (
                    backend_dir.parent
                    if first_part == backend_dir.name.casefold()
                    else backend_dir
                )
                database_path = (base / database_path).resolve()
            url = URL.create("sqlite", database=database_path.as_posix())
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    environment: str
    echo: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    allow_sqlite_in_production: bool
    ssl_required: bool = False

    @property
    def backend_name(self) -> str:
        return make_url(self.url).get_backend_name()

    @property
    def is_sqlite(self) -> bool:
        return self.backend_name == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        return self.backend_name == "postgresql"

    @property
    def bootstrap_schema(self) -> bool:
        return self.is_sqlite and self.environment in {"development", "test"}

    @property
    def is_published_environment(self) -> bool:
        return self.environment in PUBLISHED_DATABASE_ENVIRONMENTS

    @property
    def safe_url(self) -> str:
        return make_url(self.url).render_as_string(hide_password=True)


def load_database_settings(
    environ: Mapping[str, str] | None = None,
) -> DatabaseSettings:
    values = os.environ if environ is None else environ
    environment = values.get("DATABASE_ENV", "development").strip().casefold()
    if environment not in DATABASE_ENVIRONMENTS:
        allowed = ", ".join(sorted(DATABASE_ENVIRONMENTS))
        raise ValueError(f"DATABASE_ENV invalido. Valores aceitos: {allowed}.")

    settings = DatabaseSettings(
        url=normalize_database_url(values.get("DATABASE_URL")),
        environment=environment,
        echo=_boolean(
            values.get("DATABASE_ECHO"),
            default=False,
            variable_name="DATABASE_ECHO",
        ),
        pool_size=_positive_integer(
            values.get("DATABASE_POOL_SIZE"),
            default=5,
            variable_name="DATABASE_POOL_SIZE",
        ),
        max_overflow=_nonnegative_integer(
            values.get("DATABASE_MAX_OVERFLOW"),
            default=10,
            variable_name="DATABASE_MAX_OVERFLOW",
        ),
        pool_timeout=_positive_integer(
            values.get("DATABASE_POOL_TIMEOUT"),
            default=30,
            variable_name="DATABASE_POOL_TIMEOUT",
        ),
        pool_recycle=_positive_integer(
            values.get("DATABASE_POOL_RECYCLE"),
            default=1800,
            variable_name="DATABASE_POOL_RECYCLE",
        ),
        allow_sqlite_in_production=_boolean(
            values.get("ALLOW_SQLITE_IN_PRODUCTION"),
            default=False,
            variable_name="ALLOW_SQLITE_IN_PRODUCTION",
        ),
        ssl_required=_boolean(
            values.get("DATABASE_SSL_REQUIRED"),
            default=environment in PUBLISHED_DATABASE_ENVIRONMENTS,
            variable_name="DATABASE_SSL_REQUIRED",
        ),
    )
    if (
        settings.is_published_environment
        and settings.is_sqlite
        and not settings.allow_sqlite_in_production
    ):
        raise RuntimeError(
            "SQLite nao e permitido em ambiente publicado. Configure PostgreSQL em "
            "DATABASE_URL ou use o override emergencial documentado."
        )
    return settings


@dataclass(frozen=True)
class RuntimeSettings:
    environment: str
    public_demo_mode: bool
    api_docs_enabled: bool
    allowed_hosts: tuple[str, ...]

    @property
    def is_published_environment(self) -> bool:
        return self.environment in PUBLISHED_DATABASE_ENVIRONMENTS


def _comma_separated_values(raw_value: str | None) -> list[str]:
    return [
        value.strip()
        for value in (raw_value or "").split(",")
        if value.strip()
    ]


def allowed_hosts(raw_hosts: str | None = None) -> list[str]:
    raw_value = os.getenv("ALLOWED_HOSTS", "") if raw_hosts is None else raw_hosts
    hosts = []
    for host in _comma_separated_values(raw_value):
        if host == "*":
            continue
        if "://" in host or "/" in host:
            raise ValueError("ALLOWED_HOSTS deve conter somente nomes de host.")
        hosts.append(host)
    return list(dict.fromkeys(hosts))


def load_runtime_settings(
    environ: Mapping[str, str] | None = None,
) -> RuntimeSettings:
    values = os.environ if environ is None else environ
    environment = values.get("DATABASE_ENV", "development").strip().casefold()
    if environment not in DATABASE_ENVIRONMENTS:
        allowed = ", ".join(sorted(DATABASE_ENVIRONMENTS))
        raise ValueError(f"DATABASE_ENV invalido. Valores aceitos: {allowed}.")
    public_demo = _boolean(
        values.get("PUBLIC_DEMO_MODE"),
        default=False,
        variable_name="PUBLIC_DEMO_MODE",
    )
    return RuntimeSettings(
        environment=environment,
        public_demo_mode=public_demo,
        api_docs_enabled=_boolean(
            values.get("API_DOCS_ENABLED"),
            default=not public_demo,
            variable_name="API_DOCS_ENABLED",
        ),
        allowed_hosts=tuple(allowed_hosts(values.get("ALLOWED_HOSTS", ""))),
    )


def public_demo_mode() -> bool:
    return _boolean(
        os.getenv("PUBLIC_DEMO_MODE"),
        default=False,
        variable_name="PUBLIC_DEMO_MODE",
    )


def cors_allowed_origins(
    raw_extra_origins: str | None = None,
    *,
    environment: str | None = None,
) -> list[str]:
    """Return explicit CORS origins without enabling a wildcard implicitly."""
    raw_value = os.getenv("CORS_ALLOWED_ORIGINS", "") if raw_extra_origins is None else raw_extra_origins
    active_environment = (
        environment or os.getenv("DATABASE_ENV", "development")
    ).strip().casefold()
    published = active_environment in PUBLISHED_DATABASE_ENVIRONMENTS
    extras = []
    for origin in _comma_separated_values(raw_value):
        if origin == "*":
            continue
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Origem CORS invalida: {origin}")
        if published and parsed.scheme != "https":
            raise ValueError(
                "CORS em ambiente publicado aceita somente origens HTTPS."
            )
        extras.append(origin.rstrip("/"))
    defaults = [] if published else list(DEFAULT_CORS_ALLOWED_ORIGINS)
    configured = [*defaults, *extras]
    return list(dict.fromkeys(configured))
