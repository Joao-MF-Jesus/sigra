"""Opt-in pinned homologation; no existing/demo database or SQLite fallback."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from alembic import command
from alembic.config import Config

from app.academic_cohort import revision6_homologation as h
from app.academic_cohort.materialization import _materialize_plan as materialize_approved
from app.academic_cohort.contracts import validate_replay
from app.academic_cohort.safety_revision6 import _read
from sqlalchemy import text


def preflight(target):
    """Read-only identity, TLS, role and emptiness audit; no migrations or DDL."""
    result = {"database": h.DATABASE, "owner_role": h.OWNER, "runtime_role": h.RUNTIME,
              "alembic_target": h.ALEMBIC_HEAD, "database_modified": False}
    for writer, url in ((True, target.migration_url), (False, target.runtime_url)):
        engine = create_engine(url, echo=False, pool_pre_ping=True)
        try:
            with engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                h.require_database_identity(connection, writer=writer, target=target)
                if writer:
                    proof = h.require_empty_target(connection, target)
                    flags = connection.execute(text("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole "
                        "FROM pg_roles WHERE rolname=:role"), {"role":h.RUNTIME}).one_or_none()
                    if flags is None or tuple(flags) != (True,False,False,False,False):
                        raise ValueError("Nonprivileged runtime LOGIN role required before migrations")
                    owner_can_create = connection.execute(text("SELECT has_database_privilege(current_user,current_database(),'CREATE') "
                        "AND has_schema_privilege(current_user,'public','CREATE')")).scalar_one()
                    if not owner_can_create:
                        raise ValueError("Owner lacks required dedicated database/schema CREATE privileges")
                    result["new_target_proof"] = proof
                memberships = connection.execute(text("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r "
                    "ON r.oid=m.member WHERE r.rolname=current_user")).scalar_one()
                if memberships:
                    raise ValueError("Dedicated role memberships must be absent")
        finally:
            engine.dispose()
    result["status"] = "NEW_DEDICATED_TARGET_PREFLIGHT_PASSED"
    return result


def audit(target, plan, proof_path):
    """Post-preparation read-only audit, including full database size."""
    engine = create_engine(target.runtime_url, echo=False, pool_pre_ping=True)
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            h.check_proof(connection, _read(proof_path))
            permissions = h.audit_runtime_permissions(connection)
            with Session(bind=connection) as session:
                snapshot = h.Revision6Repository(session).snapshot()
                if snapshot is None:
                    raise ValueError("Dedicated Revision6 snapshot absent")
                h.audit_snapshot(session, snapshot, plan)
            size = int(connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
            return {"status":"REVISION6_DATABASE_AUDITED", "database":h.DATABASE,
                "alembic_head":h.ALEMBIC_HEAD, "database_bytes":size, "permissions":permissions,
                "candidate_profile_counts":plan.proposal.profile_counts, "selected_count":60,"evaluation_count":1080,
                "candidate_fingerprint":plan.proposal.candidate_fingerprint,
                "approved_fingerprint":plan.proposal.approved_reference_fingerprint,
                "database_modified":False, "participant_browser_validated":False}
    finally:
        engine.dispose()


def prepare_new_database(target, plan, proof_path):
    """Never called by validate/serve; refuses nonempty destinations before DDL."""
    if proof_path.exists():
        raise ValueError("Preparation proof already exists; inspect it, do not overwrite")
    if proof_path.resolve().is_relative_to(ROOT):
        raise ValueError("The nonsecret preparation receipt must remain outside the checkout")
    preflight(target)  # BOTH roles must work before the first migration.
    owner = create_engine(target.migration_url, echo=False, pool_pre_ping=True)
    try:
        with owner.connect() as connection:
            proof = h.require_empty_target(connection)
        previous = {name: os.environ.get(name) for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL")}
        try:
            os.environ["DATABASE_URL"] = target.runtime_url.render_as_string(hide_password=False)
            os.environ["MIGRATION_DATABASE_URL"] = target.migration_url.render_as_string(hide_password=False)
            command.upgrade(Config(str(ROOT / "backend/alembic.ini")), h.ALEMBIC_HEAD)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        with owner.begin() as connection:
            h.check_proof(connection, proof, writer=True)
            h.grant_runtime(connection)
        # Persist the historical V6 and the candidate separately, atomically.
        with Session(owner) as session, session.begin():
            h.check_proof(session.connection(), proof, writer=True)
            original = materialize_approved(session, validate_replay(plan.approved_replay))
            candidate = h._materialize_plan(session, plan)
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        with proof_path.open("x", encoding="utf-8") as stream:
            json.dump(proof, stream, indent=2)
            stream.write("\n")
        return {"approved": asdict(original), "candidate": asdict(candidate),
                "proof_path": str(proof_path), "candidate_active": False}
    finally:
        owner.dispose()


def configure_runtime(target, args):
    if len(os.environ.get("SIGRA_RESEARCH_PSEUDONYM_KEY", "").encode("utf-8")) < 32:
        raise ValueError("SIGRA_RESEARCH_PSEUDONYM_KEY must be provided privately for fictitious trials")
    alternatives = bool(getattr(args, "derived_configurations", False))
    os.environ.update({
        "DATABASE_URL": target.runtime_url.render_as_string(hide_password=False),
        "SIGRA_REVISION6_HOMOLOGATION_ENABLED": "true",
        "SIGRA_REVISION6_BUNDLE": str(args.bundle.resolve()),
        "SIGRA_REVISION6_DECISION": str(args.decision.resolve()),
        "SIGRA_REVISION6_TARGET_PROOF": str(args.proof.resolve()),
        "ACADEMIC_COHORT_ENABLED": "true", "SIGRA_TCC_COLLECTION_MODE": "homologation",
        "FIPE_AUTO_REFRESH": "false", "DATABASE_ECHO": "false",
        "SIGRA_DERIVED_PERSONALIZATION_ENABLED": "true" if alternatives else "false",
        "PUBLIC_DEMO_MODE": "false",
    })
    h.require_runtime()


def bind_runtime_engine(target):
    """Bind this NEW CLI process before importing FastAPI, without connecting.

Model imports initialize app.database before configure_runtime. Changing the
environment alone cannot retarget that already constructed engine.
"""
    from app import database
    from app.config import load_database_settings
    h.require_runtime()
    settings = load_database_settings()
    engine = database.create_database_engine(settings)
    try:
        target.check_bind(engine)
    except Exception:
        engine.dispose()
        raise
    database.DATABASE_SETTINGS = settings
    database.DATABASE_URL = settings.url
    database.engine = engine
    database.SessionLocal.configure(bind=engine)
    if "app.main" in sys.modules:
        sys.modules["app.main"].DATABASE_SETTINGS = settings
        sys.modules["app.main"].SessionLocal = database.SessionLocal
    return engine


def main(argv=None):
    parser = argparse.ArgumentParser(description="Revision6 inactive pinned PostgreSQL homologation")
    parser.add_argument("command", choices=("validate", "preflight", "prepare-new-database", "materialize", "audit", "serve"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--derived-configurations", action="store_true",
                        help="Enable Base/Expanded only in the fictitious dedicated API process")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        raise ValueError("Invalid local port")
    # Reject unconfigured operational commands before loading a large replay.
    # validate remains independently usable without remote infrastructure.
    target = h.target_configuration() if args.command != "validate" else None
    plan = h.build_plan(args.bundle, args.decision)
    if args.command == "validate":
        try:
            h.target_configuration()  # Offline; no connection or credentials printed.
            configured = True
        except ValueError:
            configured = False
        print(json.dumps({"status": "REVISION6_HOMOLOGATION_CODE_VALIDATED",
            "selected_count": 60, "evaluation_count": 1080, "profile_counts": plan.proposal.profile_counts,
            "candidate_fingerprint": plan.proposal.candidate_fingerprint,
            "candidate_active": False, "real_collection_enabled": False,
            "target_configuration_valid": configured,
            "postgresql_validated": False, "database_connected": False, "database_modified": False}))
        return
    if args.command == "preflight":
        result = preflight(target)
    elif args.command == "audit":
        result = audit(target, plan, args.proof)
    elif args.command == "prepare-new-database":
        result = prepare_new_database(target, plan, args.proof)
    elif args.command == "materialize":
        engine = create_engine(target.migration_url, echo=False, pool_pre_ping=True)
        try:
            result = asdict(h.materialize(engine, args.bundle, args.decision, target, _read(args.proof)))
        finally:
            engine.dispose()
    else:
        configure_runtime(target, args)
        # Audit permissions/snapshot before opening an HTTP listener. No DDL.
        engine = create_engine(target.runtime_url, echo=False, pool_pre_ping=True)
        try:
            with Session(engine) as session:
                h.service_for_session(session)._snapshot()
        finally:
            engine.dispose()
        bind_runtime_engine(target)
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
        return
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Driver exceptions may contain passwords or authenticated URLs.
        print(json.dumps({"status": "BLOCKED", "error_type": type(error).__name__,
            "message": "Revision6 homologation not completed; inspect the dedicated target, proof and bundle configuration. Credentials withheld."}))
        raise SystemExit(1)
