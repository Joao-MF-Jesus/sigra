from __future__ import annotations

import os

from sqlalchemy.engine import make_url


def disposable_postgresql_url() -> str | None:
    """Return the configured URL only when it names an explicit test database."""
    raw = os.getenv("DATA_PLATFORM_TEST_POSTGRESQL_URL", "").strip()
    if not raw:
        return None
    try:
        parsed = make_url(raw)
    except Exception:
        return None
    database = (parsed.database or "").casefold()
    host = (parsed.host or "").casefold()
    if (
        parsed.get_backend_name() != "postgresql"
        or host not in {"localhost", "127.0.0.1", "::1"}
        or not database.endswith("_test")
    ):
        return None
    return raw
