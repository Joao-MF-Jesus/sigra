"""Opt-in publication entrypoint. No DDL, imports, seeds or operational activation.

The existing localhost/homologation launchers never enable this module. Research
requires a separate confirmed database AND two explicit release gates. Preparing
or deploying the fictitious smoke configuration does not authorize collection.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.engine import make_url

PROJECT_REF = "tqlufobzzaabakflyxha"
ORGANIZATION = "tzsztlsmvmxwaypzslzr"
PROJECT_NAME = "sigra-tcc-homologacao"
ACCEPTANCE_SHA256 = "e23eb2be3ba98a2520fb87b51c5534271530ccbb8ea1e1c1a9890dbc3cf2914a"
OPINION_SHA256 = "451cd7ff391f99e7132c01aa4eb40112996be43589a154fc8f8a2d86a67c5f18"
CSV_SHA256 = "a8ca17f4658df75ecbc5cb0b7f9a5af6ba69a3e0876de98652743917d49203f5"
ALEMBIC_HEAD = "20261007_0015"
ROOT = Path(__file__).resolve().parents[2]


class DeploymentBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never include connection strings or raw errors.


def enabled(values=None):
    values = os.environ if values is None else values
    return values.get("SIGRA_DEPLOY_ENABLED") == "true"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pinned_json(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise DeploymentBlocked("PIN_REQUIRED")
    try:
        if sha256(path) != expected:
            raise DeploymentBlocked("ARTIFACT_CHANGED")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise DeploymentBlocked("DUPLICATE_JSON_KEY")
                result[key] = value
            return result
        return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)
    except (OSError, TypeError, json.JSONDecodeError):
        raise DeploymentBlocked("PINNED_ARTIFACT_UNREADABLE") from None


def validate_acceptance(value):
    scope = value.get("accepted_caveat_only", {})
    if (value.get("status") != "FUNCTIONAL_HOMOLOGATION_ACCEPTED_WITH_HISTORICAL_CAVEAT"
            or value.get("historical_row_changed") != 1
            or value.get("historical_integrity_fully_preserved") is not False
            or value.get("automatic_real_collection_release") is not False
            or value.get("binding", {}).get("report_sha256") != OPINION_SHA256
            or value.get("binding", {}).get("csv_sha256") != CSV_SHA256
            or scope.get("record_alias") != "RUN-f05b43ca0998deaa"
            or scope.get("field") != "questionnaire_at"
            or scope.get("historical_value_utc") != "2026-10-09T20:22:23.074813+00:00"
            or scope.get("current_value_utc") != "2026-10-10T14:45:56.306172+00:00"
            or scope.get("origin") != "UNKNOWN"):
        raise DeploymentBlocked("FUNCTIONAL_ACCEPTANCE_SCOPE_CHANGED")


@dataclass(frozen=True, repr=False)
class Settings:
    target: dict
    url: object = field(repr=False)
    origin: str
    real_collection: bool
    plan_path: str
    plan_sha256: str


def _supabase_target_url(values, target):
    """Unchanged legacy identity/URL gates, isolated from the opt-in Neon path."""
    if (target.get("schema") != "sigra-deploy-target-v1" or target.get("confirmed") is not True
            or target.get("project_ref") != PROJECT_REF or target.get("organization_id") != ORGANIZATION
            or target.get("project_name") != PROJECT_NAME or target.get("port") != 5432
            or type(target.get("database_oid")) is not int or target["database_oid"] <= 0
            or target.get("alembic_revision") != ALEMBIC_HEAD):
        raise DeploymentBlocked("CONFIRMED_DEDICATED_TARGET_REQUIRED")
    profile = target.get("profile")
    if profile == "homologation":
        if (target.get("database"), target.get("runtime_role")) != (
                "sigra_revision6_homologation_test", "sigra_revision6_runtime"):
            raise DeploymentBlocked("HOMOLOGATION_TARGET_DIFFERS")
    elif profile == "research":
        # Proposed names must be confirmed/provisioned separately; never reuse TLS A/B's DB.
        if (target.get("database"), target.get("runtime_role")) != (
                "sigra_tcc_research", "sigra_research_runtime"):
            raise DeploymentBlocked("RESEARCH_REQUIRES_SEPARATE_DATABASE_AND_ROLE")
    else:
        raise DeploymentBlocked("UNKNOWN_DEPLOY_PROFILE")
    if target.get("endpoint_mode") == "direct":
        if target.get("host") != f"db.{PROJECT_REF}.supabase.co":
            raise DeploymentBlocked("UNCONFIRMED_ENDPOINT")
    elif target.get("endpoint_mode") == "session":
        # Exact endpoint already observed in Connect, not a region-derived wildcard.
        if target.get("host") != "aws-1-sa-east-1.pooler.supabase.com":
            raise DeploymentBlocked("UNCONFIRMED_ENDPOINT")
    else:
        raise DeploymentBlocked("SESSION_OR_DIRECT_ONLY")
    try:
        url = make_url(values.get("DATABASE_URL", ""))
    except Exception:
        raise DeploymentBlocked("PRIVATE_RUNTIME_URL_REQUIRED") from None
    username = target["runtime_role"] + (f".{PROJECT_REF}" if target["endpoint_mode"] == "session" else "")
    if (url.drivername != "postgresql+psycopg" or url.host != target["host"] or url.port != 5432
            or url.database != target["database"] or url.username != username or not url.password
            or set(url.query) != {"sslmode", "sslrootcert"} or url.query["sslmode"] != "verify-full"):
        raise DeploymentBlocked("RUNTIME_IDENTITY_OR_VERIFY_FULL_DIFFERS")
    return profile, url


def settings(values=None):
    """Offline guards. No imports of app.database and no network connection."""
    values = os.environ if values is None else values
    if not enabled(values):
        raise DeploymentBlocked("DEPLOY_ENTRYPOINT_DISABLED")
    for name, required in {"DATABASE_ENV": "homologation", "DATABASE_SSL_REQUIRED": "true",
                           "DATABASE_ECHO": "false", "FIPE_AUTO_REFRESH": "false",
                           "PUBLIC_DEMO_MODE": "false", "ACADEMIC_COHORT_ENABLED": "true",
                           "SIGRA_COOKIE_SECURE": "true", "SIGRA_COOKIE_SAMESITE": "lax",
                           "API_DOCS_ENABLED": "false", "SIGRA_REVISION6_HOMOLOGATION_ENABLED": "false"}.items():
        if values.get(name) != required:
            raise DeploymentBlocked("UNSAFE_RUNTIME_FLAGS")
    if any(values.get(name) for name in ("MIGRATION_DATABASE_URL", "SIGRA_REVISION6_MIGRATION_URL", "SIGRA_RESEARCH_MIGRATION_URL")):
        raise DeploymentBlocked("MIGRATION_CREDENTIAL_FORBIDDEN_IN_WEB")
    target = pinned_json(values.get("SIGRA_DEPLOY_TARGET_FILE"), values.get("SIGRA_DEPLOY_TARGET_SHA256"))
    provider=values.get('SIGRA_DEPLOY_PROVIDER','supabase')
    if provider=='neon':
        from app.neon_target import runtime_url
        url=runtime_url(values,target)
        profile=target['profile']
    elif provider=='supabase' and target.get('provider','supabase')=='supabase':
        profile,url=_supabase_target_url(values,target)
    else:
        raise DeploymentBlocked('EXPLICIT_DATABASE_PROVIDER_DIFFERS')
    from app.academic_cohort.revision6_supabase_target import certificate_sha256
    try:
        if certificate_sha256(url.query["sslrootcert"]) != target.get("ca_sha256"):
            raise DeploymentBlocked("CA_PIN_DIFFERS")
    except ValueError:
        raise DeploymentBlocked("CA_INVALID_OR_PIN_DIFFERS") from None
    acceptance = pinned_json(values.get("SIGRA_FUNCTIONAL_ACCEPTANCE_FILE"), ACCEPTANCE_SHA256)
    validate_acceptance(acceptance)
    origin = values.get("SIGRA_PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port not in (None, 443)
            or parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise DeploymentBlocked("EXACT_HTTPS_ORIGIN_REQUIRED")
    if values.get("CORS_ALLOWED_ORIGINS") != origin or values.get("ALLOWED_HOSTS") != parsed.hostname:
        raise DeploymentBlocked("SAME_ORIGIN_CORS_HOSTS_REQUIRED")
    if len(values.get("SIGRA_RESEARCH_PSEUDONYM_KEY", "").encode()) < 32:
        raise DeploymentBlocked("STABLE_PRIVATE_PSEUDONYM_KEY_REQUIRED")
    if not re.fullmatch(r"sigra-[0-9a-f]{24}", values.get("SIGRA_SYSTEM_VERSION", "")):
        raise DeploymentBlocked("FROZEN_RELEASE_ID_REQUIRED")
    real = values.get("SIGRA_RESEARCH_COLLECTION_ENABLED", "false")
    if real not in {"true", "false"}:
        raise DeploymentBlocked("INVALID_COLLECTION_GATE")
    real = real == "true"
    mode = values.get("SIGRA_TCC_COLLECTION_MODE")
    if real:
        if (profile != "research" or target.get("research_release_authorized") is not True
                or target.get("protocol_version") != "tcc-appendices-cd-v1" or mode != "research"):
            raise DeploymentBlocked("RESEARCH_RELEASE_NOT_EXPLICITLY_AUTHORIZED")
    elif mode != "homologation" or target.get("research_release_authorized") is not False:
        raise DeploymentBlocked("FICTITIOUS_SMOKE_REQUIRED_WHILE_COLLECTION_DISABLED")
    if values.get("SIGRA_DERIVED_PERSONALIZATION_ENABLED") not in {"true", "false"}:
        raise DeploymentBlocked("EXPLICIT_DERIVED_CONFIGURATION_FLAG_REQUIRED")
    plan_path, plan_hash = values.get("SIGRA_DEPLOY_PLAN_FILE"), values.get("SIGRA_DEPLOY_PLAN_SHA256")
    if not plan_path or not re.fullmatch(r"[0-9a-f]{64}", plan_hash or ""):
        raise DeploymentBlocked("PINNED_PLAN_REQUIRED")
    return Settings(target, url, origin, real, plan_path, plan_hash)


def research_collection_allowed():
    return enabled() and settings().real_collection


def require_account(email=None):
    try:
        configured = settings()
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(503, "Configuração de publicação não confirmada") from None
    if not configured.real_collection and email is not None and not email.casefold().endswith((".test", ".invalid")):
        from fastapi import HTTPException
        raise HTTPException(403, "Homologação: use somente uma conta fictícia .test ou .invalid")


@lru_cache(maxsize=1)
def load_plan(path, expected):
    from app.academic_cohort import revision6_homologation as h
    from app.academic_cohort.safety_revision6 import InactiveRevision6Proposal
    item = pinned_json(path, expected)
    proposal = InactiveRevision6Proposal(**{**item["proposal"],
        "transport_vehicles": tuple({**row, "purchase_price_brl": Decimal(row["purchase_price_brl"])}
                                    for row in item["proposal"]["transport_vehicles"]),
        "transport_evaluations": tuple(decode_evaluation(row) for row in item["proposal"]["transport_evaluations"]),
        "limitations": tuple(item["proposal"]["limitations"])})
    plan = h.Revision6Plan(proposal, item["replay"], item["approved_replay"])
    h.validate_plan(plan)  # Existing V6 contract and Revision6 deltas unchanged.
    return plan


def decode_evaluation(row):
    # Canonical JSON carries exact decimal strings; never float or missing -> zero.
    return {**row, "score": None if row["score"] is None else Decimal(row["score"]),
            "monthly_tco_brl": Decimal(row["monthly_tco_brl"])}


def validate_connection_transport(connection, target, backend_tls):
    if target.get('provider')=='neon':
        from app.neon_target import validate_tls
        return validate_tls(connection,target,backend_tls)
    from app.academic_cohort.revision6_supabase_target import ConfirmedTarget, validate_connection_tls
    return validate_connection_tls(ConfirmedTarget(PROJECT_REF,target['host'],target['ca_sha256'],'',target['endpoint_mode']),
                                   connection.connection.driver_connection.pgconn.ssl_in_use, backend_tls)


def database_preflight(connection, configured):
    """Only SELECTs, caller's READ ONLY transaction; never grants/DDL/repair."""
    if connection.engine.url != configured.url:
        raise DeploymentBlocked("ENGINE_TARGET_DIFFERS")
    observed = connection.execute(text("""SELECT current_database(), current_user,
        (SELECT oid FROM pg_database WHERE datname=current_database()), pg_backend_pid(),
        s.pid, s.ssl, s.version, s.cipher FROM (SELECT pg_backend_pid() AS pid) b
        LEFT JOIN pg_stat_ssl s ON s.pid=b.pid""")).one()
    t = configured.target
    if tuple(observed[:3]) != (t["database"], t["runtime_role"], t["database_oid"]):
        raise DeploymentBlocked("DATABASE_ROLE_OR_OID_DIFFERS")
    if observed[4] is None or observed[3] != observed[4]:
        raise DeploymentBlocked("BACKEND_TLS_OBSERVATION_MISSING")
    transport = validate_connection_transport(connection, t, tuple(observed[5:8]))
    if t.get('provider')=='neon':
        from app.neon_target import validate_marker
        validate_marker(connection,t)
    parameters = connection.connection.driver_connection.info.get_parameters()
    if any(parameters.get(key) != expected for key, expected in {
            "host": configured.url.host, "sslmode": "verify-full",
            "sslrootcert": configured.url.query["sslrootcert"]}.items()):
        raise DeploymentBlocked("EFFECTIVE_LIBPQ_TLS_PARAMETERS_DIFFER")
    if connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() != [ALEMBIC_HEAD]:
        raise DeploymentBlocked("ALEMBIC_REVISION_DIFFERS")
    flags = connection.execute(text("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication "
        "FROM pg_roles WHERE rolname=current_user")).one()
    if any(flags):
        raise DeploymentBlocked("PRIVILEGED_RUNTIME_FORBIDDEN")
    invalid = connection.execute(text("""SELECT
        EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))
        OR EXISTS(SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))
        OR has_database_privilege(current_user,current_database(),'CREATE,TEMPORARY')
        OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
            AND nspname <> 'information_schema' AND has_schema_privilege(current_user,oid,'CREATE'))
        OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname IN ('academic','bronze','silver','gold','meta') AND c.relkind IN ('r','p','v','m')
            AND has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'))
        OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace,
            LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a
            LEFT JOIN pg_roles r ON r.oid=a.grantee WHERE n.nspname IN ('public','academic','bronze','silver','gold','meta')
            AND c.relkind IN ('r','p','v','m') AND (a.grantee=0 OR r.rolname IN ('anon','authenticated')))
        """)).scalar_one()
    if invalid:
        raise DeploymentBlocked("RUNTIME_GRANTS_NOT_MINIMAL")
    from app.tcc_supabase import PRIVATE_TABLES
    for name in PRIVATE_TABLES:
        row = connection.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(:r)"),
                                 {"r": f"public.{name}"}).one_or_none()
        policies = connection.execute(text("SELECT p.polroles=ARRAY[r.oid],p.polcmd FROM pg_policy p "
            "JOIN pg_roles r ON r.rolname=current_user WHERE p.polrelid=to_regclass(:r)"), {"r": f"public.{name}"}).all()
        if row is None or tuple(row) != (True, True) or [tuple(p) for p in policies] != [(True, "*")]:
            raise DeploymentBlocked("PRIVATE_RLS_NOT_SERVICE_ROLE_ONLY")
    label = ("client_verified_internal_provider_assurance"
             if t.get('provider') == 'neon' and transport.get('model') == 'neon-managed-preview-v1'
             else "all_observed_links_verified")
    return {"identity": "matched", "tls": label, "transport_evidence": transport,
            "alembic": ALEMBIC_HEAD, "runtime": "least_privilege", "database_modified": False}


def service_for_session(session):
    from app.academic_cohort.revision6_homologation import Revision6Repository, Revision6Service
    configured = settings()
    database_preflight(session.connection(), configured)
    result = Revision6Service(Revision6Repository(session), load_plan(configured.plan_path, configured.plan_sha256))
    if configured.real_collection:
        result.limitations[0] = "Pesquisa acadêmica delimitada; não é ativação operacional da Gold."
        result.recommendation_context = {**result.recommendation_context, "real_collection_enabled": True,
                                         "research_protocol_version": "tcc-appendices-cd-v1"}
    return result


def validate_startup():
    configured = settings()
    from app.database import engine
    from sqlalchemy.orm import Session
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        database_preflight(connection, configured)
        with Session(bind=connection) as session:
            service_for_session(session)._snapshot()


def create_app():
    """Uvicorn factory; fail closed before serving. No auto migration/materialization."""
    settings()
    from app.release_manifest import verify_release
    verify_release(ROOT, os.environ.get("SIGRA_RELEASE_MANIFEST_FILE", ""), os.environ["SIGRA_SYSTEM_VERSION"])
    from app.main import app, lifespan
    from fastapi import FastAPI
    from starlette.staticfiles import StaticFiles
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    static = ROOT / "frontend/dist"
    if not (static / "index.html").is_file():
        raise DeploymentBlocked("FRONTEND_BUILD_REQUIRED")
    outer = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    outer.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings().origin).hostname])
    outer.mount("/sigra-api", app)
    outer.mount("/", StaticFiles(directory=static, html=True), name="sigra-built-frontend")
    @outer.middleware("http")
    async def browser_headers(request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/sigra-api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    return outer
