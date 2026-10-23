"""ASGI lifecycle adapter, not a Uvicorn launcher. No DB access at import/build.

Only per-instance private CA/receipt copies live in ephemeral scratch space.
The original publication settings, manifest, TLS, OID, grants and snapshot gates
run unchanged before any request is served. A failed lifespan stays closed.
"""
from contextlib import asynccontextmanager
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]


class VercelBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise VercelBlocked(code)


def private_bytes(values, name, maximum):
    try:
        raw = base64.b64decode(values.get(name, ""), validate=True)
    except (ValueError, TypeError):
        raise VercelBlocked("PRIVATE_FILE_ENCODING_INVALID") from None
    require(0 < len(raw) <= maximum, "PRIVATE_FILE_MISSING_OR_TOO_LARGE")
    return raw


def prepare_acceptances(values, directory, manifest):
    """Keep public build identity separate from byte-pinned private decisions.

    Explicit manifest mode only; a failed external pin never falls back to the
    historical embedded files. Existing sealed deployments keep their old mode.
    """
    mode = manifest.get('private_runtime_configuration', 'embedded-acceptances-v1')
    require(mode in {'embedded-acceptances-v1', 'external-acceptances-v1'},
            'EXPLICIT_PRIVATE_CONFIGURATION_MODE_REQUIRED')
    if mode == 'embedded-acceptances-v1':
        values['SIGRA_FUNCTIONAL_ACCEPTANCE_FILE'] = str(ROOT / 'release/functional-acceptance.json')
        return
    from app.deployment import ACCEPTANCE_SHA256 as functional_pin
    from app.neon_transport import ACCEPTANCE_SHA256 as transport_pin
    require(manifest.get('functional_acceptance_sha256') == functional_pin
            and manifest.get('transport_acceptance_sha256') == transport_pin,
            'PRIVATE_ACCEPTANCE_MANIFEST_PINS_DIFFER')
    for variable, filename, pin, key in (
        ('SIGRA_FUNCTIONAL_ACCEPTANCE_B64', 'functional-acceptance.json', functional_pin,
         'SIGRA_FUNCTIONAL_ACCEPTANCE_FILE'),
        ('SIGRA_NEON_TRANSPORT_ACCEPTANCE_B64', 'neon-transport-acceptance.json', transport_pin,
         'SIGRA_NEON_TRANSPORT_ACCEPTANCE_FILE'),
    ):
        raw = private_bytes(values, variable, 20000)
        require(hashlib.sha256(raw).hexdigest() == pin, 'PRIVATE_ACCEPTANCE_CONTENT_CHANGED')
        path = Path(directory) / filename
        with path.open('xb') as stream:
            stream.write(raw)
        os.chmod(path, 0o600)
        values[key] = str(path)


def resolve_origin(values, target):
    """Explicit platform mode resolves ONLY this deployment's system hostname.

    It is not a wildcard request-host policy. Never read request headers here;
    RequestGate still compares every request against one exact HTTPS origin.
    """
    mode = values.get('SIGRA_VERCEL_ORIGIN_MODE', 'explicit-host-v1')
    require(mode in {'explicit-host-v1', 'system-preview-v1'}, 'EXPLICIT_ORIGIN_MODE_REQUIRED')
    if mode == 'system-preview-v1':
        expected = values.get('SIGRA_VERCEL_EXPECTED_PROJECT_ID', '')
        require(values.get('VERCEL') == '1' and values.get('VERCEL_ENV') == 'preview'
                and values.get('VERCEL_TARGET_ENV') == 'preview', 'VERCEL_PREVIEW_SYSTEM_CONTEXT_REQUIRED')
        require(bool(re.fullmatch(r'prj_[A-Za-z0-9]+', expected))
                and values.get('VERCEL_PROJECT_ID') == expected == target.get('vercel_project_id')
                and values.get('SIGRA_VERCEL_EXPECTED_TEAM_ID') == target.get('vercel_team_id')
                and bool(re.fullmatch(r'team_[A-Za-z0-9]+', target.get('vercel_team_id', ''))),
                'PINNED_VERCEL_PROJECT_OR_TEAM_DIFFERS')
        host = values.get('VERCEL_URL', '')
        require(bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.vercel\.app', host)),
                'VERCEL_ASSIGNED_PREVIEW_HOST_REQUIRED')
        origin = 'https://' + host
        for key, expected_value in {'SIGRA_PUBLIC_ORIGIN': origin, 'SIGRA_VERCEL_EXACT_HOST': host,
                                   'CORS_ALLOWED_ORIGINS': origin, 'ALLOWED_HOSTS': host}.items():
            require(values.get(key, '') in {'', expected_value}, 'EXPLICIT_ORIGIN_CONFLICTS_WITH_DEPLOYMENT')
            values[key] = expected_value
    return values.get('SIGRA_PUBLIC_ORIGIN', '')


def prepare_environment(values, directory):
    """Offline only; do not infer identity/CA/OID, or change credentials."""
    require(values.get("SIGRA_VERCEL_ENABLED") == "true", "VERCEL_ENTRYPOINT_DISABLED")
    require(values.get("SIGRA_RESEARCH_COLLECTION_ENABLED") == "false"
            and values.get("SIGRA_TCC_COLLECTION_MODE") == "homologation", "FICTITIOUS_ONLY")
    # The adapter trusts no forwarded headers or wildcard proxy network. ASGI
    # scheme/Host must be supplied correctly by Vercel and checked online.
    require(not values.get("SIGRA_TRUSTED_PROXY_IPS"), "NO_INVENTED_PROXY_NETWORK")
    require(values.get("DATABASE_BOOTSTRAP_SCHEMA") == "false", "DDL_AT_STARTUP_FORBIDDEN")
    target_raw = private_bytes(values, "SIGRA_VERCEL_TARGET_B64", 12000)
    ca_raw = private_bytes(values, "SIGRA_VERCEL_CA_B64", 12000)
    require(hashlib.sha256(target_raw).hexdigest() == values.get("SIGRA_DEPLOY_TARGET_SHA256"), "TARGET_PIN_DIFFERS")
    try:
        target = json.loads(target_raw)
    except (ValueError, UnicodeDecodeError):
        raise VercelBlocked("TARGET_JSON_INVALID") from None
    origin = resolve_origin(values, target)
    parsed = urlsplit(origin)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.path
            and not parsed.query and not parsed.fragment and not parsed.username
            and not parsed.password and parsed.port is None
            and parsed.hostname == values.get("SIGRA_VERCEL_EXACT_HOST")
            and parsed.hostname.endswith(".vercel.app"), "EXACT_VERCEL_HOST_REQUIRED")
    # Never read or reuse the populated TLS A/B homologation database. Existing
    # publication contract's separately provisioned target names stay unchanged.
    require(target.get("profile") == "research" and target.get("database") == "sigra_tcc_research"
            and target.get("runtime_role") == "sigra_research_runtime"
            and target.get("research_release_authorized") is False, "SEPARATE_FICTITIOUS_TARGET_REQUIRED")
    require(hashlib.sha256(ca_raw).hexdigest() == target.get("ca_sha256"), "CA_PIN_DIFFERS")
    directory = Path(directory)
    require(directory.is_dir() and not any(directory.iterdir()), "EMPTY_PRIVATE_SCRATCH_REQUIRED")
    os.chmod(directory, 0o700)
    for name, raw in (("target.json", target_raw), ("ca.crt", ca_raw)):
        path = directory / name
        with path.open("xb") as stream:
            stream.write(raw)
        os.chmod(path, 0o600)
    from sqlalchemy.engine import make_url
    try:
        url = make_url(values.get("DATABASE_URL", ""))
    except Exception:
        raise VercelBlocked("PRIVATE_RUNTIME_URL_REQUIRED") from None
    # Only the scratch path changes. All other URL identity/TLS fields are
    # validated below by the original deployment.settings, never normalized away.
    require(url.query.get("sslrootcert") == "SIGRA_CA_FILE", "EXPLICIT_CA_PATH_TOKEN_REQUIRED")
    keys={"sslmode", "sslrootcert"}
    if target.get('provider')=='neon':
        keys.update({'sslsni','channel_binding'})
        require(url.query.get('sslsni')=='1', 'NEON_SNI_REQUIRED')
        require(url.query.get('channel_binding')=='require', 'NEON_CHANNEL_BINDING_REQUIRED')
    require(set(url.query) == keys and url.query["sslmode"] == "verify-full", "VERIFY_FULL_REQUIRED")
    values["DATABASE_URL"] = url.update_query_dict({"sslrootcert": str(directory / "ca.crt")}).render_as_string(hide_password=False)
    values["SIGRA_DEPLOY_TARGET_FILE"] = str(directory / "target.json")
    values["SIGRA_RELEASE_MANIFEST_FILE"] = str(ROOT / "release/manifest.json")
    manifest = json.loads((ROOT / "release/manifest.json").read_text(encoding="utf-8"))
    prepare_acceptances(values, directory, manifest)
    require(values.get("SIGRA_SYSTEM_VERSION") == manifest["release_id"], "RELEASE_VERSION_DIFFERS")
    from app.release_manifest import verify_release
    verify_release(ROOT, values["SIGRA_RELEASE_MANIFEST_FILE"], values["SIGRA_SYSTEM_VERSION"])
    from app.packed_plan import restore_plan, STORAGE_FILE
    plan = restore_plan(ROOT / STORAGE_FILE, directory / "plan.json",
                        manifest.get("runtime_plan_storage"), values.get("SIGRA_DEPLOY_PLAN_SHA256"),
                        manifest["files"].get(STORAGE_FILE))
    values["SIGRA_DEPLOY_PLAN_FILE"] = str(plan)
    from app.deployment import settings
    settings(values)  # Original exhaustive offline gates; no engine import.


class RequestGate:
    """Keep HTTPS/Host checks local to ASGI, not unverified proxy headers."""
    def __init__(self, app, origin):
        self.app, self.origin = app, urlsplit(origin)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        host = dict(scope.get("headers", [])).get(b"host", b"").decode("ascii", errors="replace")
        if scope.get("scheme") != "https" or host != self.origin.netloc:
            return await JSONResponse({"detail": "Origem HTTPS da publicação não confirmada"}, status_code=400)(scope, receive, send)
        await self.app(scope, receive, send)


def create_vercel_app(factory=None, preparer=None):
    """The runtime drives lifespan. No lazy per-request initialization/DDL."""
    @asynccontextmanager
    async def lifespan(shell):
        with tempfile.TemporaryDirectory(prefix="sigra-vercel-") as private:
            (preparer or prepare_environment)(os.environ, private)
            if factory is None:
                from app.deployment import create_app
                inner = create_app()
            else:
                inner = factory()
            if os.environ.get('SIGRA_NEON_PREVIEW_METRICS') == 'true':
                from app import deployment
                from app.neon_transport import MANAGED
                configured = deployment.settings()
                require(configured.target.get('provider') == 'neon'
                        and configured.target.get('transport_model') == MANAGED
                        and configured.real_collection is False, 'FICTITIOUS_NEON_METRICS_ONLY')
                from app.preview_metrics import PreviewMetrics
                instrumented = PreviewMetrics(inner)
            else:
                instrumented = inner
            wrapped = RequestGate(instrumented, os.environ["SIGRA_PUBLIC_ORIGIN"])
            async with inner.router.lifespan_context(inner):
                shell.state.runtime = wrapped
                try:
                    yield
                finally:
                    shell.state.runtime = None
        # No secrets printed on shutdown; temporary private files removed.
    shell = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @shell.middleware("http")
    async def dispatch(request, call_next):
        runtime = getattr(shell.state, "runtime", None)
        if runtime is None:
            return JSONResponse({"detail": "Inicialização protegida incompleta"}, status_code=503)
        # A mount keeps the original /sigra-api prefix and request path intact.
        return await call_next(request)

    async def delegate(scope, receive, send):
        runtime = getattr(shell.state, "runtime", None)
        if runtime is None:
            return await JSONResponse({"detail": "Inicialização protegida incompleta"}, status_code=503)(scope, receive, send)
        await runtime(scope, receive, send)
    shell.mount("/", delegate)
    return shell
