"""Explicit new-project guard and least-privilege policy; no Supabase Auth."""
from dataclasses import dataclass
from pathlib import Path
import re

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

from app.config import load_database_settings

RUNTIME_ROLE = "sigra_tcc_runtime"
APP_SCHEMAS = ("public", "academic", "bronze", "silver", "gold", "meta")
PRIVATE_TABLES = ("users", "auth_sessions", "participant_test_runs", "participant_study_sessions", "participant_questionnaires", "expenses",
                  "maintenances", "user_vehicles", "vehicle_reports", "fuel_consumption_reports")
PERSONAL_SEQUENCES = ("users", "expenses", "maintenances", "user_vehicles",
                      "vehicle_reports", "fuel_consumption_reports")


@dataclass(frozen=True, repr=False)
class HomologationTarget:
    project_ref: str
    migration_url: URL
    runtime_url: URL


def target_configuration(values) -> HomologationTarget:
    """Offline-only validation. Addresses must come from the project's Connect panel."""
    ref = values.get("SIGRA_TCC_HOMOLOGATION_PROJECT_REF", "")
    if not re.fullmatch(r"[a-z]{20}", ref):
        raise ValueError("SIGRA_TCC_HOMOLOGATION_PROJECT_REF must identify the NEW dedicated project")
    host = values.get("SIGRA_TCC_DATABASE_HOST", "")
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Set SIGRA_TCC_DATABASE_HOST to the actual project Connect host")
    urls = []
    for name, expected_user in (("SIGRA_TCC_HOMOLOGATION_MIGRATION_URL", "postgres"),
                                ("SIGRA_TCC_HOMOLOGATION_RUNTIME_URL", RUNTIME_ROLE)):
        try:
            url = make_url(values.get(name, ""))
        except Exception:
            raise ValueError(f"{name} is missing or invalid; value not disclosed") from None
        if (url.get_backend_name() != "postgresql" or url.host != host or url.database != "postgres"
                or not url.password or url.port not in {None, 5432}
                or url.username not in {expected_user, f"{expected_user}.{ref}"}):
            raise ValueError(f"{name} does not match the pinned dedicated target/role/session port")
        direct = host == f"db.{ref}.supabase.co"
        session = host.endswith(".pooler.supabase.com") and url.username == f"{expected_user}.{ref}"
        if not (direct or session):
            raise ValueError(f"{name} is not a direct or session-pooler URL for the pinned project")
        cert = url.query.get("sslrootcert", "")
        if (url.query.get("sslmode") != "verify-full" or not isinstance(cert, str)
                or not Path(cert).is_absolute() or not Path(cert).is_file()):
            raise ValueError(f"{name} requires verify-full and an existing absolute sslrootcert")
        urls.append(url.set(drivername="postgresql+psycopg"))
    if urls[0].host != urls[1].host or urls[0].port != urls[1].port:
        raise ValueError("Migration and runtime must use the same pinned project endpoint")
    return HomologationTarget(ref, *urls)


def settings_for(url: URL):
    return load_database_settings({"DATABASE_ENV": "homologation", "DATABASE_ECHO": "false",
                                   "DATABASE_SSL_REQUIRED": "true",
                                   "DATABASE_URL": url.render_as_string(hide_password=False)})


def require_empty_application(connection):
    """Managed auth/storage schemas are not SIGRA; any existing app relation blocks."""
    relations = connection.execute(text("""
        SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','academic','bronze','silver','gold','meta')
          AND c.relkind IN ('r','p','v','m','S','f')
    """)).all()
    if relations:
        raise ValueError("Homologation must be a NEW empty SIGRA target; existing relations found")
    if connection.execute(text("SELECT current_database(), current_user")).one() != ("postgres", "postgres"):
        raise ValueError("Unexpected migration database or operator role")


def harden_participant_access(connection):
    """DDL in caller's transaction after Alembic, scoped only to SIGRA objects.

    The runtime is a trusted service identity, NOT an individual Supabase user.
    FastAPI still enforces user ownership. RLS closes anonymous Data API access.
    """
    role = connection.execute(text("""
        SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
        FROM pg_roles WHERE rolname=:role
    """), {"role": RUNTIME_ROLE}).one_or_none()
    if role != (True, False, False, False, False):
        raise ValueError("Provision a dedicated non-privileged sigra_tcc_runtime LOGIN role first")
    memberships = connection.execute(text("""
        SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
        WHERE r.rolname=:role
    """), {"role": RUNTIME_ROLE}).scalar_one()
    ownership = connection.execute(text("""
        SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
        WHERE r.rolname=:role
    """), {"role": RUNTIME_ROLE}).scalar_one()
    if memberships or ownership:
        raise ValueError("Runtime role must not inherit other roles or own relations")
    present = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
    for schema in APP_SCHEMAS:
        if schema not in present:
            continue
        # Names are fixed constants, never received from a request.
        for principal in ("PUBLIC", "anon", "authenticated"):
            connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM {principal}'))
            for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                connection.execute(text(f'REVOKE ALL ON ALL {kind} IN SCHEMA "{schema}" FROM {principal}'))
                connection.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" REVOKE ALL ON {kind} FROM {principal}'))
    connection.execute(text('GRANT USAGE ON SCHEMA public, academic TO sigra_tcc_runtime'))
    for table in PRIVATE_TABLES:
        connection.execute(text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f'ALTER TABLE public."{table}" FORCE ROW LEVEL SECURITY'))
        connection.execute(text(f'DROP POLICY IF EXISTS sigra_trusted_backend ON public."{table}"'))
        connection.execute(text(f'CREATE POLICY sigra_trusted_backend ON public."{table}" '
                                'TO sigra_tcc_runtime USING (true) WITH CHECK (true)'))
        connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON public."{table}" TO sigra_tcc_runtime'))
    # Only known operational read dependencies; never grant writes to Gold/academic.
    for table in ("alembic_version", "vehicles", "motorcycles"):
        connection.execute(text(f'GRANT SELECT ON public."{table}" TO sigra_tcc_runtime'))
    for table in PERSONAL_SEQUENCES:
        connection.execute(text(f'GRANT USAGE, SELECT ON SEQUENCE public."{table}_id_seq" TO sigra_tcc_runtime'))
    connection.execute(text('GRANT SELECT ON ALL TABLES IN SCHEMA academic TO sigra_tcc_runtime'))


def audit_participant_access(connection):
    for table in PRIVATE_TABLES:
        flags = connection.execute(text("""
            SELECT relrowsecurity, relforcerowsecurity FROM pg_class
            WHERE oid=to_regclass(:table)
        """), {"table": f"public.{table}"}).one()
        if flags != (True, True):
            raise ValueError("Participant table RLS is not enforced")
        policies = connection.execute(text("""
            SELECT p.polname, p.polroles = ARRAY[r.oid], p.polcmd
            FROM pg_policy p JOIN pg_roles r ON r.rolname=:role
            WHERE p.polrelid=to_regclass(:table)
        """), {"role": RUNTIME_ROLE, "table": f"public.{table}"}).all()
        if policies != [("sigra_trusted_backend", True, "*")]:
            raise ValueError("Unexpected participant-table policy or policy grantee")
        for principal in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if connection.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                                      {"role": principal, "table": f"public.{table}",
                                       "privilege": privilege}).scalar_one():
                    raise ValueError("Data API role still has participant-table privileges")
    # Audit all application relations, including previously granted academic data.
    relations = connection.execute(text("""
        SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','academic','bronze','silver','gold','meta')
          AND c.relkind IN ('r','p','v','m')
    """)).all()
    for schema, table in relations:
        for principal in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                if connection.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                    {"role": principal, "table": f'"{schema}"."{table}"', "privilege": privilege}).scalar_one():
                    raise ValueError("Data API role still has application-table privileges")
        if schema != "public" or table not in PRIVATE_TABLES:
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
                if connection.execute(text("SELECT has_table_privilege(:role,:table,:privilege)"),
                    {"role": RUNTIME_ROLE, "table": f'"{schema}"."{table}"', "privilege": privilege}).scalar_one():
                    raise ValueError("Runtime can modify immutable application data")
    for schema in APP_SCHEMAS:
        exists = connection.execute(text("SELECT to_regnamespace(:schema) IS NOT NULL"), {"schema": schema}).scalar_one()
        if exists and connection.execute(text("SELECT has_schema_privilege(:role,:schema,'CREATE')"),
            {"role": RUNTIME_ROLE, "schema": schema}).scalar_one():
            raise ValueError("Runtime has schema CREATE privileges")
    return {"participant_rls": True, "anonymous_table_privileges": False, "runtime_immutable_writes": False,
            "auth_provider": "FastAPI opaque sessions", "supabase_auth_used": False}


def measure_database_size(connection):
    """Real read-only measurements, not a ZIP/replay size or a quota claim."""
    total = int(connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
    schemas = connection.execute(text("""
        SELECT n.nspname, COALESCE(sum(pg_total_relation_size(c.oid)),0)::bigint
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('public','academic','bronze','silver','gold','meta')
          AND c.relkind IN ('r','p','m') GROUP BY n.nspname ORDER BY n.nspname
    """)).all()
    payload = connection.execute(text("""
        SELECT count(*), COALESCE(sum(pg_column_size(parameters) + pg_column_size(presented_results)
               + COALESCE(pg_column_size(technical_record),0)),0)
        FROM public.participant_test_runs
    """)).one()
    # Pricing advertises 500 MB. Decimal threshold is deliberately conservative;
    # Supabase dashboard's quota accounting remains authoritative.
    limit = 500_000_000
    return {"database_bytes": total, "free_database_limit_conservative_bytes": limit,
            "below_conservative_free_limit": total < limit,
            "application_relations_including_indexes_toast_bytes": dict(schemas),
            "record_count": int(payload[0]), "record_payload_bytes": int(payload[1]),
            "estimated_payload_bytes_for_100_runs": round(int(payload[1]) / int(payload[0]) * 100) if payload[0] else None,
            "projection_limitation": "Payload only; indexes/TOAST/DB growth and network egress require real measurements.",
            "quota_dashboard_confirmation_required": True}
