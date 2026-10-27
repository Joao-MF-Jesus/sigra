"""Prepare a NEW exclusive Supabase target; validate-only never opens a connection."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app.tcc_supabase import (audit_participant_access, harden_participant_access,
                            measure_database_size, require_empty_application, settings_for, target_configuration)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--audit-only", action="store_true")
    parser.add_argument("--confirm-project")
    args = parser.parse_args()
    target = target_configuration(os.environ)
    from app.academic_cohort.contracts import validate_replay
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    plan = validate_replay(replay)
    if args.validate_only:
        print(json.dumps({"status": "validated_only", "database_connected": False,
                          "selected_count": len(plan.vehicles), "evaluation_count": len(plan.evaluations),
                          "cohort_fingerprint": plan.cohort_fingerprint}))
        return
    if args.confirm_project != target.project_ref:
        raise ValueError("Explicit confirmation of the dedicated project ref is required")
    from alembic import command
    from alembic.config import Config
    from app.database import create_database_engine, current_migration_revision
    from app.academic_cohort.materialization import materialize
    if args.audit_only:
        from sqlalchemy import select, text
        from sqlalchemy.orm import Session
        from app.academic_cohort.materialization import _audit
        from app.academic_cohort.models import CohortSnapshot
        runtime = create_database_engine(settings_for(target.runtime_url))
        try:
            with runtime.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                if connection.execute(text("SELECT current_user")).scalar_one() != "sigra_tcc_runtime":
                    raise ValueError("Unexpected audit role")
                if current_migration_revision(runtime) != "20261007_0015":
                    raise ValueError("Unexpected Alembic head")
                with Session(bind=connection) as session:
                    snapshot = session.scalar(select(CohortSnapshot).where(CohortSnapshot.cohort_fingerprint == plan.cohort_fingerprint))
                    if snapshot is None:
                        raise ValueError("Approved snapshot is absent")
                    _audit(session, snapshot, plan)
                print(json.dumps({"status": "read_only_database_audit_completed", "migration_head": "20261007_0015",
                                  "database_size": measure_database_size(connection),
                                  "permissions": audit_participant_access(connection),
                                  "selected_count": 60, "evaluation_count": 1080,
                                  "cohort_fingerprint": plan.cohort_fingerprint}, default=str))
        finally:
            runtime.dispose()
        return
    operator = create_database_engine(settings_for(target.migration_url))
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        with operator.connect() as connection:
            require_empty_application(connection)
        os.environ["MIGRATION_DATABASE_URL"] = target.migration_url.render_as_string(hide_password=False)
        config = Config(str(ROOT / "backend/alembic.ini"))
        # Existing Alembic chain, no bootstrap or second migration history.
        command.upgrade(config, "20261005_0013")
        command.upgrade(config, "20261007_0014")
        # Exercise the defensive reversal BEFORE any participant data is collected.
        command.downgrade(config, "20261005_0013")
        command.upgrade(config, "20261007_0014")
        command.upgrade(config, "20261007_0015")
        command.downgrade(config, "20261007_0014")
        command.upgrade(config, "20261007_0015")
        first, second = materialize(operator, replay), materialize(operator, replay)
        if (first.selected_count != 60 or first.evaluation_count != 1080
                or second.status != "already_materialized" or second.database_modified):
            raise ValueError("V6 import/idempotence audit failed")
        with operator.begin() as connection:
            harden_participant_access(connection)
            permissions = audit_participant_access(connection)
            size = measure_database_size(connection)
            if not size["below_conservative_free_limit"]:
                raise ValueError("Dedicated database exceeds the conservative Free database quota")
        if current_migration_revision(operator) != "20261007_0015":
            raise ValueError("Unexpected Alembic head")
        runtime = create_database_engine(settings_for(target.runtime_url))
        try:
            from sqlalchemy import text
            with runtime.connect() as connection:
                assert connection.execute(text("SELECT current_user")).scalar_one() == "sigra_tcc_runtime"
                assert connection.execute(text("SELECT count(*) FROM academic.cohort_vehicle")).scalar_one() == 60
                assert connection.execute(text("SELECT count(*) FROM academic.cohort_evaluation")).scalar_one() == 1080
            # Same materializer performs a payload-level audit without modifying the snapshot.
            print(json.dumps({"status": "database_prepared_not_deploy_approved", "migration_cycle": "0013 -> 0014 -> 0013 -> 0014 -> 0015 -> 0014 -> 0015",
                              "migration_head": "20261007_0015", "materialization": asdict(second), "database_size": size,
                              "permissions": permissions, "participant_http_flow_tested": False}, default=str))
        finally:
            runtime.dispose()
    finally:
        operator.dispose()
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Driver errors can contain URLs; intentionally never serialize exception text.
        print(json.dumps({"status": "blocked", "error_type": type(error).__name__,
                          "message": "Check dedicated project, TLS, replay and operator privileges locally"}))
        raise SystemExit(1)
