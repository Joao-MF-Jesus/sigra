"""Explicit PostgreSQL-only import of the approved offline v6 replay."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.academic_cohort.materialization import materialize
from app.academic_cohort.contracts import validate_replay
from app.database import create_database_engine, current_migration_revision
from app.config import load_database_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True, help="Approved offline replay JSON, outside Git")
    parser.add_argument("--allow-local-test", action="store_true", help="Explicitly authorize a local database ending in _test")
    parser.add_argument("--validate-only", action="store_true", help="Check local target and replay without connecting or writing")
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    raw = os.getenv("DATA_PLATFORM_TEST_POSTGRESQL_URL", "")
    if not raw or not args.allow_local_test:
        raise ValueError("Explicit local test target and --allow-local-test are required")
    target = make_url(raw)
    if (target.get_backend_name() != "postgresql" or target.host not in {"127.0.0.1", "localhost", "::1"}
            or not (target.database or "").endswith("_test")):
        raise ValueError("Only an explicitly configured local PostgreSQL test database is authorized")
    settings = load_database_settings({"DATABASE_URL": raw, "DATABASE_ENV": "test", "DATABASE_ECHO": "false"})
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    plan = validate_replay(replay)
    if args.validate_only:
        print(json.dumps({"status": "validated_only", "cohort_fingerprint": plan.cohort_fingerprint,
                          "selected_count": len(plan.vehicles), "evaluation_count": len(plan.evaluations),
                          "database_connected": False, "database_modified": False}))
        return
    engine = create_database_engine(settings)
    try:
        if current_migration_revision(engine) != "20261005_0013":
            raise ValueError("Apply additive migration 20261005_0013 to the test target first")
        receipt = materialize(engine, replay)
        print(json.dumps(asdict(receipt), default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Exception class is safe; database driver messages may contain credentials.
        print(json.dumps({"status": "blocked", "error_type": type(error).__name__,
                          "message": "Materialization not completed; verify local target, migration and approved replay"}))
        raise SystemExit(1)
