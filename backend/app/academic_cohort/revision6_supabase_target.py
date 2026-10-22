"""Pinned nonsecret identity receipt; never accepts arbitrary remote targets.

The operator must confirm the real Management API project before generating a
receipt. Offline validation is NOT an online project or TLS-handshake audit.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import ssl
import time

ORGANIZATION = "tzsztlsmvmxwaypzslzr"
PROJECT_NAME = "sigra-tcc-homologacao"
FORBIDDEN_REFS = {"zvuludzvdbxedhtrbqmy", "ibsvxajuyvzszvgluqtx"}
VERSION = "revision6-supabase-target-v1"
SESSION_VERSION = "revision6-supabase-session-target-v2"
REPOSITORY = Path(__file__).resolve().parents[3]


def certificate_sha256(path):
    """Parse the CA and check validity; psycopg verifies the server on connect."""
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        raise ValueError("Existing absolute CA certificate required")
    cert = Path(path).resolve()
    if not cert.is_file() or cert.is_relative_to(REPOSITORY):
        raise ValueError("CA certificate must exist outside the checkout")
    try:
        context = ssl.create_default_context(cafile=str(cert))
        authorities = context.get_ca_certs()
        now = time.time()
        if not authorities or any(not (ssl.cert_time_to_seconds(c["notBefore"]) <= now
                < ssl.cert_time_to_seconds(c["notAfter"])) for c in authorities):
            raise ValueError("CA validity period is not current")
        return hashlib.sha256(cert.read_bytes()).hexdigest()
    except (OSError, ssl.SSLError, KeyError, ValueError):
        raise ValueError("CA certificate invalid, expired or unreadable; details withheld") from None


def project_identity(project):
    if not isinstance(project, dict):
        raise ValueError("Real Management API project identity required")
    ref = project.get("id")
    host = project.get("database", {}).get("host") if isinstance(project.get("database"), dict) else None
    if (not isinstance(ref, str) or not re.fullmatch(r"[a-z]{20}", ref)
            or ref in FORBIDDEN_REFS or project.get("ref", ref) != ref
            or project.get("organization_id") != ORGANIZATION
            or project.get("name") != PROJECT_NAME or project.get("status") != "ACTIVE_HEALTHY"
            or host != f"db.{ref}.supabase.co"):
        raise ValueError("BLOCKED_BY_PROJECT_IDENTITY: exact healthy dedicated project not confirmed")
    return {"id": ref, "organization_id": ORGANIZATION, "name": PROJECT_NAME,
            "status": "ACTIVE_HEALTHY", "database": {"host": host}}


def session_connection_identity(connection, project_ref):
    """Validate a Connect/session observation, never construct a host from region.

    Like the Management API identity, this must be observed by the operator.
    Its exact endpoint and tenant-qualified username are pinned in the receipt.
    """
    keys = {"project_ref", "host", "port", "mode", "operator_username",
            "operator_database", "source_url", "observed_at"}
    if not isinstance(connection, dict) or set(connection) != keys:
        raise ValueError("Explicit complete Dashboard session observation required")
    host = connection["host"]
    if (connection["project_ref"] != project_ref or connection["mode"] != "session"
            or type(connection["port"]) is not int or connection["port"] != 5432
            or not isinstance(host, str)
            or not re.fullmatch(r"aws-[0-9]+-[a-z]+-[a-z]+-[0-9]+\.pooler\.supabase\.com", host)
            or connection["operator_username"] != f"postgres.{project_ref}"
            or connection["operator_database"] != "postgres"
            or connection["source_url"] != (f"https://supabase.com/dashboard/project/{project_ref}"
                "?showConnect=true&connectTab=direct&method=session")):
        raise ValueError("Session observation differs from the confirmed project/mode/endpoint")
    try:
        when = datetime.fromisoformat(connection["observed_at"])
        if when.tzinfo is None or when > datetime.now(timezone.utc):
            raise ValueError("Invalid observation time")
    except (TypeError, ValueError):
        raise ValueError("Valid timestamp of the Dashboard session observation required") from None
    return dict(connection)


def confirmation(project, ca_path, *, session_connection=None):
    identity = project_identity(project)
    result = {"version": VERSION, "project": identity, "endpoint_mode": "direct", "port": 5432,
            "database": "sigra_revision6_homologation_test", "owner_role": "sigra_revision6_owner",
            "runtime_role": "sigra_revision6_runtime", "sslmode": "verify-full",
            "ca_sha256": certificate_sha256(ca_path), "confirmed_at": datetime.now(timezone.utc).isoformat()}
    if session_connection is not None:
        result["session_connection"] = session_connection_identity(session_connection, identity["id"])
        result["version"] = SESSION_VERSION
        result["endpoint_mode"] = "session"
    return result


@dataclass(frozen=True)
class ConfirmedTarget:
    project_ref: str
    host: str
    ca_sha256: str
    receipt_sha256: str
    endpoint_mode: str = "direct"

    def username_for(self, role):
        """Wire tenant selector is not the SQL role returned by current_user."""
        return f"{role}.{self.project_ref}" if self.endpoint_mode == "session" else role

    def binding(self):
        result = {"target_kind": "supabase", "organization_id": ORGANIZATION,
                "project_ref": self.project_ref, "endpoint": self.host, "port": 5432,
                "ca_sha256": self.ca_sha256, "confirmation_sha256": self.receipt_sha256}
        if self.endpoint_mode == "session":
            result["endpoint_mode"] = "session"
        return result


def load_confirmation(values):
    raw_path = values.get("SIGRA_REVISION6_PROJECT_CONFIRMATION", "")
    expected = values.get("SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256", "")
    if not raw_path or not Path(raw_path).is_absolute() or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("BLOCKED_BY_PROJECT_IDENTITY: pinned external project confirmation required")
    path = Path(raw_path).resolve()
    if path.is_relative_to(REPOSITORY):
        raise ValueError("Project confirmation must remain outside the checkout")
    try:
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected.lower():
            raise ValueError("Project confirmation checksum mismatch")
        value = json.loads(raw)
        identity = project_identity(value["project"])
        when = datetime.fromisoformat(value["confirmed_at"])
        if when.tzinfo is None or when > datetime.now(timezone.utc):
            raise ValueError("Invalid project confirmation time")
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError):
        raise ValueError("BLOCKED_BY_PROJECT_IDENTITY: invalid or changed project confirmation") from None
    expected_keys = {"version", "project", "endpoint_mode", "port", "database", "owner_role", "runtime_role",
                     "sslmode", "ca_sha256", "confirmed_at"}
    mode = value.get("endpoint_mode")
    host = identity["database"]["host"]
    if mode == "session":
        expected_keys.add("session_connection")
        observed = session_connection_identity(value.get("session_connection"), identity["id"])
        host = observed["host"]
    version = SESSION_VERSION if mode == "session" else VERSION
    if (set(value) != expected_keys or value["version"] != version or mode not in {"direct", "session"}
            or type(value["port"]) is not int or value["port"] != 5432
            or value["database"] != "sigra_revision6_homologation_test"
            or value["owner_role"] != "sigra_revision6_owner" or value["runtime_role"] != "sigra_revision6_runtime"
            or value["sslmode"] != "verify-full" or not isinstance(value["ca_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["ca_sha256"])
            or values.get("SIGRA_REVISION6_CONFIRM_PROJECT") != identity["id"]):
        raise ValueError("Pinned project/database/roles/TLS confirmation differs")
    return ConfirmedTarget(identity["id"], host, value["ca_sha256"], actual, mode)


def validate_url(url, role, confirmed):
    if (url.host != confirmed.host or url.port != 5432
            or url.database != "sigra_revision6_homologation_test" or url.username != confirmed.username_for(role)
            or set(url.query) != {"sslmode", "sslrootcert"} or url.query["sslmode"] != "verify-full"
            or certificate_sha256(url.query["sslrootcert"]) != confirmed.ca_sha256):
        raise ValueError("Remote endpoint/database/role/CA differs from the confirmed dedicated target")


def validate_connection_tls(confirmed, driver_tls, backend_tls):
    """Measure the two session-pooler links separately, never claim end-to-end TLS.

    Called only after the pinned receipt, exact URL and CA have been validated.
    libpq enforces verify-full on the client link. pg_stat_ssl describes the
    database backend link, not that client link when Supavisor terminates TLS.
    Both direct and session connections must satisfy both observations.
    A pinned session endpoint never waives the independent upstream TLS gate.
    """
    mode = confirmed.endpoint_mode
    if mode not in {"direct", "session"} or driver_tls is not True:
        raise ValueError("PostgreSQL client TLS not established for the confirmed mode")
    try:
        backend_tls = tuple(backend_tls)
    except TypeError:
        raise ValueError("PostgreSQL backend TLS observation missing or malformed") from None
    if len(backend_tls) != 3 or type(backend_tls[0]) is not bool:
        raise ValueError("PostgreSQL backend TLS observation missing or malformed")
    secured, version, cipher = backend_tls
    if not secured:
        raise ValueError("PostgreSQL backend TLS not established; client TLS is insufficient")
    if version not in {"TLSv1.2", "TLSv1.3"} or not isinstance(cipher, str) or not cipher:
        raise ValueError("PostgreSQL backend TLS version/cipher not verified")
    return {"endpoint_mode": mode, "client_tls": True,
            "client_tls_scope": "client_to_pooler" if mode == "session" else "client_to_database",
            "backend_tls": secured, "backend_tls_version": version,
            "all_observed_links_tls": secured,
            "end_to_end_tls": mode == "direct" and secured}
