from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import load_database_settings  # noqa: E402


def wait_for_database(
    *,
    timeout_seconds: float = 60,
    require_postgresql: bool = False,
) -> dict:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds deve ser maior que zero.")

    settings = load_database_settings()
    if require_postgresql and not settings.is_postgresql:
        raise RuntimeError(
            "A validacao exige PostgreSQL, mas outra engine foi configurada."
        )

    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    attempts = 0
    last_error_type = None
    while time.monotonic() < deadline:
        attempts += 1
        engine = create_engine(
            settings.url,
            pool_pre_ping=True,
            connect_args=(
                {
                    "connect_timeout": max(
                        1,
                        min(5, int(timeout_seconds)),
                    ),
                    "options": "-c timezone=UTC",
                }
                if settings.is_postgresql
                else {}
            ),
        )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            elapsed = round(time.monotonic() - started_at, 3)
            return {
                "status": "ready",
                "engine": settings.backend_name,
                "attempts": attempts,
                "elapsed_seconds": elapsed,
            }
        except Exception as error:
            last_error_type = type(error).__name__
        finally:
            engine.dispose()

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        backoff = min(5.0, 0.25 * (2 ** min(attempts - 1, 5)))
        time.sleep(min(backoff, remaining))

    return {
        "status": "unavailable",
        "engine": settings.backend_name,
        "attempts": attempts,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "error_type": last_error_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aguarda o banco configurado responder sem expor credenciais."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("DATABASE_WAIT_TIMEOUT_SECONDS", "60")),
    )
    parser.add_argument("--require-postgresql", action="store_true")
    args = parser.parse_args()
    try:
        report = wait_for_database(
            timeout_seconds=args.timeout_seconds,
            require_postgresql=args.require_postgresql,
        )
    except Exception as error:
        report = {
            "status": "configuration-error",
            "error_type": type(error).__name__,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "ready":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
