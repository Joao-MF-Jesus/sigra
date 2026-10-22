"""Future deployment checks and guarded NEW research materialization, never auto-started."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app import deployment as d
from app.release_manifest import verify_release


def migration_url(values, configured):
    if configured.target["profile"] != "research" or configured.real_collection:
        raise d.DeploymentBlocked("NEW_RESEARCH_TARGET_WITH_COLLECTION_OFF_REQUIRED")
    try:
        url = make_url(values.get("SIGRA_RESEARCH_MIGRATION_URL", ""))
    except Exception:
        raise d.DeploymentBlocked("PRIVATE_RESEARCH_MIGRATION_URL_REQUIRED") from None
    username = "sigra_research_owner" + (f".{d.PROJECT_REF}" if configured.target["endpoint_mode"] == "session" else "")
    if not url.password or url != configured.url.set(username=username, password=url.password):
        raise d.DeploymentBlocked("RESEARCH_OWNER_ENDPOINT_ROLE_OR_TLS_DIFFERS")
    return url


def audit(configured):
    engine = create_engine(configured.url, echo=False, pool_pre_ping=True)
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            result = d.database_preflight(connection, configured)
            with Session(bind=connection) as session:
                service = d.service_for_session(session)
                snapshot = service._snapshot()
            return {"status": "DEPLOY_POSTGRESQL_AUDITED", **result,
                "database": configured.target["database"], "profile": configured.target["profile"],
                "selected_count": 60, "evaluation_count": 1080, "profile_counts": snapshot.profile_counts,
                "database_bytes": connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one(),
                "collection_enabled": configured.real_collection}
    finally:
        engine.dispose()


def migrate_new(configured, owner_url, confirm):
    """Future explicit operator action; validates BOTH roles and emptiness before DDL."""
    if confirm != "sigra_tcc_research" or configured.target["database"] != confirm:
        raise d.DeploymentBlocked("EXACT_NEW_RESEARCH_DATABASE_CONFIRMATION_REQUIRED")
    from app.academic_cohort.revision6_supabase_target import ConfirmedTarget, validate_connection_tls
    t = configured.target
    for url, role in ((configured.url, "sigra_research_runtime"), (owner_url, "sigra_research_owner")):
        engine = create_engine(url, echo=False)
        try:
            with engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                identity = connection.execute(text("SELECT current_database(),current_user,(SELECT oid FROM pg_database WHERE datname=current_database()),"
                    "b.pid,s.pid,s.ssl,s.version,s.cipher FROM (SELECT pg_backend_pid() AS pid)b LEFT JOIN pg_stat_ssl s ON s.pid=b.pid")).one()
                if tuple(identity[:3]) != (confirm, role, t["database_oid"]) or identity[3] != identity[4]:
                    raise d.DeploymentBlocked("NEW_RESEARCH_PREFLIGHT_IDENTITY_OR_TLS_ROW_DIFFERS")
                validate_connection_tls(ConfirmedTarget(d.PROJECT_REF,t["host"],t["ca_sha256"],"",t["endpoint_mode"]),
                    connection.connection.driver_connection.pgconn.ssl_in_use, identity[5:8])
                flags = connection.execute(text("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user")).one()
                if any(flags) or connection.execute(text("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)")).scalar_one():
                    raise d.DeploymentBlocked("NEW_RESEARCH_ROLES_NOT_MINIMAL")
                if connection.execute(text("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_%' AND c.relkind IN ('r','p','v','m','S','f')")).scalar_one():
                    raise d.DeploymentBlocked("RESEARCH_TARGET_NOT_NEW_EMPTY_NO_MIGRATION")
        finally:
            engine.dispose()
    from alembic import command
    from alembic.config import Config
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    try:
        os.environ["MIGRATION_DATABASE_URL"] = owner_url.render_as_string(hide_password=False)
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), d.ALEMBIC_HEAD)
    finally:
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous
    return {"status": "NEW_RESEARCH_EXISTING_ALEMBIC_CHAIN_APPLIED", "alembic_revision": d.ALEMBIC_HEAD,
            "database": confirm, "collection_enabled": False}


def materialize_new(configured, owner_url, confirm):
    if confirm != "sigra_tcc_research" or configured.target["database"] != confirm:
        raise d.DeploymentBlocked("EXACT_NEW_RESEARCH_DATABASE_CONFIRMATION_REQUIRED")
    from app.academic_cohort import revision6_homologation as h
    from app.academic_cohort.materialization import _materialize_plan as original
    from app.academic_cohort.contracts import validate_replay
    from app.tcc_supabase import PRIVATE_TABLES
    # Runtime has service-role RLS visibility, unlike the FORCE-RLS owner.
    engine = create_engine(configured.url, echo=False)
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            d.database_preflight(connection, configured)
            for name in PRIVATE_TABLES:
                if connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one():
                    raise d.DeploymentBlocked("PARTICIPANT_DATA_ALREADY_EXISTS_NO_IMPORT")
            if connection.execute(text("SELECT count(*) FROM academic.cohort_snapshot")).scalar_one():
                raise d.DeploymentBlocked("SNAPSHOTS_ALREADY_EXIST_USE_READONLY_AUDIT")
    finally:
        engine.dispose()
    plan = d.load_plan(configured.plan_path, configured.plan_sha256)
    owner = create_engine(owner_url, echo=False)
    try:
        with Session(owner) as session, session.begin():
            identity = session.execute(text("SELECT current_database(),current_user,(SELECT oid FROM pg_database WHERE datname=current_database())")).one()
            if tuple(identity) != (confirm, "sigra_research_owner", configured.target["database_oid"]):
                raise d.DeploymentBlocked("RESEARCH_OWNER_DATABASE_ROLE_OID_DIFFERS")
            # Owner uses the same verified CA/hostname URL; recheck both TLS observations.
            from app.academic_cohort.revision6_supabase_target import ConfirmedTarget, validate_connection_tls
            driver = session.connection().connection.driver_connection.pgconn
            tls = session.execute(text("SELECT ssl,version,cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid()")).one()
            t = configured.target
            validate_connection_tls(ConfirmedTarget(d.PROJECT_REF, t["host"], t["ca_sha256"], "", t["endpoint_mode"]), driver.ssl_in_use, tls)
            session.execute(text("SELECT pg_advisory_xact_lock(610070015)"))
            if session.execute(text("SELECT count(*) FROM academic.cohort_snapshot")).scalar_one():
                raise d.DeploymentBlocked("CONCURRENT_OR_EXISTING_MATERIALIZATION")
            original(session, validate_replay(plan.approved_replay))
            h._materialize_plan(session, plan)
        return {"status": "NEW_RESEARCH_SNAPSHOTS_MATERIALIZED", "database": confirm,
                "collection_enabled": False, "operational_activation": False}
    finally:
        owner.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify-release", "audit", "migrate-new", "materialize-new"))
    parser.add_argument("--release", type=Path, default=ROOT)
    parser.add_argument("--confirm-database")
    args = parser.parse_args(argv)
    try:
        manifest_path = args.release / "release/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_release(args.release, manifest_path, manifest["release_id"])
        if args.action == "verify-release":
            result = {"status": "RELEASE_CONTENT_VERIFIED_OFFLINE", "release_id": manifest["release_id"],
                      "historical_row_changed": 1, "database_contacted": False, "collection_enabled": False}
        else:
            values = dict(os.environ)
            private_owner = values.pop("SIGRA_RESEARCH_MIGRATION_URL", None)
            configured = d.settings(values)
            if args.action == "audit":
                result = audit(configured)
            elif args.action == "materialize-new":
                result = materialize_new(configured, migration_url({"SIGRA_RESEARCH_MIGRATION_URL": private_owner}, configured), args.confirm_database)
            else:
                result = migrate_new(configured, migration_url({"SIGRA_RESEARCH_MIGRATION_URL": private_owner}, configured), args.confirm_database)
        print(json.dumps(result))
        return 0
    except Exception as error:
        code = error.code if isinstance(error, d.DeploymentBlocked) else "DEPLOY_CHECK_BLOCKED"
        print(json.dumps({"status": "DEPLOY_OPERATION_BLOCKED", "stage": args.action, "code": code,
            "exception_kind": type(error).__name__, "secret_values_reported": False,
            "database_state": "UNDETERMINED_INSPECT_TARGET_NO_RETRY" if args.action in {"migrate-new", "materialize-new"}
                              else "NO_WRITE_COMMANDS", "automatic_retry": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
