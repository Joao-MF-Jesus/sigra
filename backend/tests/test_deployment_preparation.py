"""Synthetic offline fixtures only. No existing database, credentials or servers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException, Response
import pytest

from app import deployment as d
from app.release_manifest import release_id, verify_release
from backend.tests.test_participant_trials import storage


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return d.sha256(path)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    from app.academic_cohort import revision6_supabase_target as pins
    monkeypatch.setattr(pins, "certificate_sha256", lambda _: "a" * 64)
    acceptance = {"status": "FUNCTIONAL_HOMOLOGATION_ACCEPTED_WITH_HISTORICAL_CAVEAT", "historical_row_changed": 1,
        "historical_integrity_fully_preserved": False, "automatic_real_collection_release": False,
        "binding": {"report_sha256": d.OPINION_SHA256, "csv_sha256": d.CSV_SHA256},
        "accepted_caveat_only": {"record_alias": "RUN-f05b43ca0998deaa", "field": "questionnaire_at",
            "historical_value_utc": "2026-10-09T20:22:23.074813+00:00",
            "current_value_utc": "2026-10-10T14:45:56.306172+00:00", "origin": "UNKNOWN"}}
    acceptance_path = tmp_path / "acceptance.json"
    monkeypatch.setattr(d, "ACCEPTANCE_SHA256", write_json(acceptance_path, acceptance))
    target = {"schema": "sigra-deploy-target-v1", "confirmed": True, "profile": "homologation",
        "project_ref": d.PROJECT_REF, "organization_id": d.ORGANIZATION, "project_name": d.PROJECT_NAME,
        "port": 5432, "database_oid": 1234, "alembic_revision": d.ALEMBIC_HEAD,
        "database": "sigra_revision6_homologation_test", "runtime_role": "sigra_revision6_runtime",
        "endpoint_mode": "session", "host": "aws-1-sa-east-1.pooler.supabase.com",
        "ca_sha256": "a" * 64, "protocol_version": "tcc-appendices-cd-v1", "research_release_authorized": False}
    target_path = tmp_path / "target.json"
    values = {"SIGRA_DEPLOY_ENABLED": "true", "DATABASE_ENV": "homologation", "DATABASE_SSL_REQUIRED": "true",
        "DATABASE_ECHO": "false", "FIPE_AUTO_REFRESH": "false", "PUBLIC_DEMO_MODE": "false",
        "ACADEMIC_COHORT_ENABLED": "true", "SIGRA_COOKIE_SECURE": "true", "SIGRA_COOKIE_SAMESITE": "lax",
        "API_DOCS_ENABLED": "false", "SIGRA_REVISION6_HOMOLOGATION_ENABLED": "false",
        "SIGRA_DEPLOY_TARGET_FILE": str(target_path), "SIGRA_DEPLOY_TARGET_SHA256": write_json(target_path, target),
        "DATABASE_URL": "postgresql+psycopg://sigra_revision6_runtime.tqlufobzzaabakflyxha:synthetic-only@aws-1-sa-east-1.pooler.supabase.com:5432/sigra_revision6_homologation_test?sslmode=verify-full&sslrootcert=/synthetic/ca.crt",
        "SIGRA_FUNCTIONAL_ACCEPTANCE_FILE": str(acceptance_path), "SIGRA_PUBLIC_ORIGIN": "https://sigra.example.test",
        "CORS_ALLOWED_ORIGINS": "https://sigra.example.test", "ALLOWED_HOSTS": "sigra.example.test",
        "SIGRA_RESEARCH_PSEUDONYM_KEY": "SYNTHETIC-ONLY-TEST-KEY-" * 2,
        "SIGRA_SYSTEM_VERSION": "sigra-" + "a" * 24, "SIGRA_RESEARCH_COLLECTION_ENABLED": "false",
        "SIGRA_TCC_COLLECTION_MODE": "homologation", "SIGRA_DERIVED_PERSONALIZATION_ENABLED": "true",
        "SIGRA_DEPLOY_PLAN_FILE": "/synthetic/plan.json", "SIGRA_DEPLOY_PLAN_SHA256": "b" * 64}
    return values, target, target_path


def repin(values, target, path):
    values["SIGRA_DEPLOY_TARGET_SHA256"] = write_json(path, target)


def test_existing_launcher_unaffected_and_default_off():
    assert d.enabled({}) is False
    with pytest.raises(d.DeploymentBlocked, match="DISABLED"):
        d.settings({})


def test_fictitious_deploy_validated_without_connection(configured):
    values, _, _ = configured
    result = d.settings(values)
    assert result.real_collection is False
    assert "synthetic-only" not in repr(result)


@pytest.mark.parametrize("change", [
    {"DATABASE_ENV": "integration"}, {"DATABASE_URL": "sqlite:///legacy.db"},
    {"SIGRA_COOKIE_SECURE": "false"}, {"CORS_ALLOWED_ORIGINS": "*"},
    {"ALLOWED_HOSTS": "*"}, {"PUBLIC_DEMO_MODE": "true"}, {"FIPE_AUTO_REFRESH": "true"},
    {"SIGRA_REVISION6_HOMOLOGATION_ENABLED": "true"}, {"MIGRATION_DATABASE_URL": "private-fixture"},
    {"SIGRA_REVISION6_MIGRATION_URL": "private-fixture"}, {"SIGRA_RESEARCH_COLLECTION_ENABLED": "true"},
    {"SIGRA_PUBLIC_ORIGIN": "http://sigra.example.test"}, {"SIGRA_SYSTEM_VERSION": "unfrozen"},
    {"SIGRA_RESEARCH_PSEUDONYM_KEY": "short"}, {"SIGRA_DERIVED_PERSONALIZATION_ENABLED": ""},
])
def test_unsafe_or_unarmed_settings_rejected(configured, change):
    values, _, _ = configured
    with pytest.raises(ValueError):
        d.settings({**values, **change})


@pytest.mark.parametrize("field,value", [("project_ref", "zvuludzvdbxedhtrbqmy"),
    ("organization_id", "other"), ("confirmed", False), ("port", 6543), ("database_oid", None),
    ("host", "aws-0-sa-east-1.pooler.supabase.com"), ("runtime_role", "postgres"),
    ("database", "postgres"), ("alembic_revision", "20261007_0014")])
def test_different_identity_cannot_be_relabelled(configured, field, value):
    values, target, path = configured
    target[field] = value
    repin(values, target, path)
    with pytest.raises(ValueError):
        d.settings(values)


def test_verify_full_not_downgraded(configured):
    values, _, _ = configured
    for url in (values["DATABASE_URL"].replace("verify-full", "require"),
                values["DATABASE_URL"].replace("&sslrootcert=/synthetic/ca.crt", ""),
                values["DATABASE_URL"].replace("5432", "6543")):
        with pytest.raises(ValueError):
            d.settings({**values, "DATABASE_URL": url})


def test_research_needs_separate_database_role_and_two_explicit_gates(configured):
    values, target, path = configured
    target.update(profile="research", database="sigra_tcc_research", runtime_role="sigra_research_runtime")
    repin(values, target, path)
    values["DATABASE_URL"] = values["DATABASE_URL"].replace("sigra_revision6_runtime", "sigra_research_runtime").replace(
        "sigra_revision6_homologation_test", "sigra_tcc_research")
    assert not d.settings(values).real_collection  # Fictitious smoke in new target first.
    values.update(SIGRA_TCC_COLLECTION_MODE="research", SIGRA_RESEARCH_COLLECTION_ENABLED="true")
    with pytest.raises(ValueError, match="NOT_EXPLICITLY_AUTHORIZED"):
        d.settings(values)
    target["research_release_authorized"] = True
    repin(values, target, path)
    assert d.settings(values).real_collection
    target["database"] = "sigra_revision6_homologation_test"
    repin(values, target, path)
    with pytest.raises(ValueError):
        d.settings(values)


def test_collection_labels_and_guards_preserve_unknowns(monkeypatch):
    from app.study_protocol import collection_mode, metadata
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "research")
    monkeypatch.setattr(d, "research_collection_allowed", lambda: False)
    with pytest.raises(HTTPException) as error:
        collection_mode()
    assert error.value.status_code == 503
    monkeypatch.setattr(d, "research_collection_allowed", lambda: True)
    assert metadata(Response())["real_collection_enabled"] is True
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "homologation")
    assert metadata(Response())["real_collection_enabled"] is False


def test_research_context_is_distinct_without_rewriting_old_synthetic_rows(storage, monkeypatch):
    from backend.tests.test_participant_trials import client, register_and_login, FINANCING
    from backend.tests.test_study_protocol import BEFORE, ANSWERS
    from sqlalchemy.orm import Session
    from app import models
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "homologation")
    http = client()
    register_and_login(http)
    old = http.post("/api/v1/study-sessions", json=BEFORE).json()
    assert old["environment_tag"] == "homologation_synthetic"
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "research")
    monkeypatch.setattr(d, "research_collection_allowed", lambda: True)  # Synthetic guard fixture only.
    assert http.get("/api/v1/study-sessions/current").json() == {"session": None}
    new = http.post("/api/v1/study-sessions", json={**BEFORE, "scenario_id": "E"}).json()
    assert new["environment_tag"] == "research_participant" and new["id"] != old["id"]
    result = http.post("/api/v1/test-runs/financing", json=FINANCING)
    assert result.status_code == 200
    identifier = result.json()["test_run"]["id"]
    assert http.patch(f"/api/v1/test-runs/{identifier}/questionnaire", json=ANSWERS).status_code == 200
    detail = http.get(f"/api/v1/test-runs/{identifier}").json()
    assert detail["technical_record"]["environment_tag"] == "research_participant"
    monkeypatch.setenv("SIGRA_TCC_COLLECTION_MODE", "homologation")
    assert http.get("/api/v1/study-sessions/current").json()["session"]["id"] == old["id"]
    with Session(storage) as db:
        assert db.get(models.ParticipantStudySession, old["id"]).environment_tag == "homologation_synthetic"


def test_built_frontend_and_api_share_origin_without_touching_local_servers(tmp_path, monkeypatch):
    from app import main
    from fastapi.testclient import TestClient
    root = tmp_path / "release"
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("<html>SIGRA synthetic build fixture</html>", encoding="utf-8")
    monkeypatch.setattr(d, "ROOT", root)
    monkeypatch.setattr(d, "settings", lambda: SimpleNamespace(origin="https://sigra.example.test"))
    monkeypatch.setenv("SIGRA_SYSTEM_VERSION", "sigra-" + "a" * 24)
    from app import release_manifest
    monkeypatch.setattr(release_manifest, "verify_release", lambda *args: {})
    # TestClient without a lifespan context: no startup DB access, no server process.
    http = TestClient(d.create_app(), base_url="https://sigra.example.test")
    page = http.get("/")
    assert page.status_code == 200 and "SIGRA synthetic" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    session = http.get("/sigra-api/auth/session")
    assert session.status_code == 200 and session.json() == {"user": None}
    assert session.headers["cache-control"] == "no-store"
    assert http.get("/", headers={"Host": "untrusted.example.test"}).status_code == 400


def test_acceptance_cannot_be_extended_or_historical_issue_erased():
    with pytest.raises(ValueError):
        d.validate_acceptance({})


def test_runtime_decimal_transport_roundtrip_preserves_null_zero_and_precision():
    from decimal import Decimal
    from app.academic_cohort.contracts import json_document
    row = {"score": Decimal("72.123456"), "monthly_tco_brl": Decimal("1477.96"), "payload": {"abs": None}}
    encoded = json_document(row)
    assert encoded["score"] == "72.123456"
    assert d.decode_evaluation(encoded) == row
    unknown = d.decode_evaluation({"score": None, "monthly_tco_brl": "0.00"})
    assert unknown["score"] is None and unknown["monthly_tco_brl"] == Decimal("0.00")


def test_manifest_roundtrip_numeric_paths_and_real_mutation(tmp_path):
    (tmp_path / "backend").mkdir()
    source = tmp_path / "backend/file.py"
    source.write_text("# synthetic fixture\n", encoding="utf-8")
    files = {"backend/file.py": d.sha256(source)}
    manifest = {"schema": "sigra-source-release-v1", "files": files, "release_id": release_id(files)}
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    assert verify_release(tmp_path, path, manifest["release_id"]) == manifest
    source.write_text("# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FILE_CHANGED"):
        verify_release(tmp_path, path, manifest["release_id"])
    source.write_text("# synthetic fixture\n", encoding="utf-8")
    (tmp_path / "backend/unexpected.py").write_text("# extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FILE_SET_DIFFERS"):
        verify_release(tmp_path, path, manifest["release_id"])


def test_proxy_does_not_trust_arbitrary_forwarded_headers():
    path = Path(__file__).resolve().parents[2] / "deploy/start_tcc.py"
    spec = importlib.util.spec_from_file_location("tcc_start", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.trusted_proxies("10.20.0.0/16,127.0.0.1") == "10.20.0.0/16,127.0.0.1"
    for value in ("", "*", "0.0.0.0/0", "::/0", "10.0.0.1,"):
        with pytest.raises(ValueError):
            module.trusted_proxies(value)


def test_future_materializer_rejects_homologation_and_mismatched_owner_before_connect(configured):
    from scripts.manage_tcc_deploy import migration_url, migrate_new
    values, target, path = configured
    conf = d.settings(values)
    with pytest.raises(ValueError, match="NEW_RESEARCH_TARGET"):
        migration_url({}, conf)
    with pytest.raises(ValueError, match="EXACT_NEW_RESEARCH_DATABASE_CONFIRMATION"):
        migrate_new(conf, None, "sigra_revision6_homologation_test")
    target.update(profile="research", database="sigra_tcc_research", runtime_role="sigra_research_runtime")
    repin(values, target, path)
    values["DATABASE_URL"] = values["DATABASE_URL"].replace("sigra_revision6_runtime", "sigra_research_runtime").replace(
        "sigra_revision6_homologation_test", "sigra_tcc_research")
    conf = d.settings(values)
    with pytest.raises(ValueError):
        migration_url({}, conf)
    owner = values["DATABASE_URL"].replace("sigra_research_runtime", "sigra_research_owner")
    assert migration_url({"SIGRA_RESEARCH_MIGRATION_URL": owner}, conf).database == "sigra_tcc_research"
    for bad in (owner.replace("verify-full", "require"), owner.replace("5432", "6543"),
                owner.replace("sigra_tcc_research", "sigra_revision6_homologation_test")):
        with pytest.raises(ValueError):
            migration_url({"SIGRA_RESEARCH_MIGRATION_URL": bad}, conf)


def test_grants_preparation_has_database_owner_empty_and_revision_gates():
    sql = (Path(__file__).resolve().parents[2] / "deploy/research-grants.sql").read_text()
    assert "current_database() <> 'sigra_tcc_research'" in sql
    assert "current_user <> 'sigra_research_owner'" in sql
    assert "IS DISTINCT FROM ARRAY['20261007_0015']" in sql
    assert "IF n <> 0" in sql and "ALREADY_HARDENED_INSPECT_DO_NOT_REPLAY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "DROP " not in sql and "TRUNCATE " not in sql


@pytest.mark.parametrize("already_populated", [False, True])
def test_future_migration_preflight_both_roles_before_alembic(configured, monkeypatch, already_populated):
    from scripts import manage_tcc_deploy as tool
    from alembic import command
    values, target, path = configured
    target.update(profile="research", database="sigra_tcc_research", runtime_role="sigra_research_runtime")
    repin(values, target, path)
    values["DATABASE_URL"] = values["DATABASE_URL"].replace("sigra_revision6_runtime", "sigra_research_runtime").replace(
        "sigra_revision6_homologation_test", "sigra_tcc_research")
    conf = d.settings(values)
    owner = tool.migration_url({"SIGRA_RESEARCH_MIGRATION_URL": values["DATABASE_URL"].replace(
        "sigra_research_runtime", "sigra_research_owner")}, conf)
    opened, upgrades = [], []
    class Connection:
        def __init__(self, url):
            self.url = url
            self.connection = SimpleNamespace(driver_connection=SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True)))
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def begin(self): return self
        def execute(self, statement):
            query = str(statement)
            assert query.startswith(("SELECT", "SET TRANSACTION READ ONLY"))
            if "current_database(),current_user" in query:
                return Result(("sigra_tcc_research", self.url.username.split(".")[0], 1234, 10, 10, True, "TLSv1.3", "synthetic-cipher"))
            if "rolsuper" in query: return Result((False,) * 5)
            if "pg_auth_members" in query: return Result(0)
            if "pg_class" in query: return Result(1 if already_populated else 0)
            return Result(None)
    class Engine:
        def __init__(self, url): self.url = url
        def connect(self):
            opened.append(self.url.username)
            return Connection(self.url)
        def dispose(self): pass
    monkeypatch.setattr(tool, "create_engine", lambda url, **kwargs: Engine(url))
    monkeypatch.setattr(command, "upgrade", lambda config, head: upgrades.append(head))
    previous = __import__("os").environ.get("MIGRATION_DATABASE_URL")
    if already_populated:
        with pytest.raises(ValueError, match="NOT_NEW_EMPTY"):
            tool.migrate_new(conf, owner, "sigra_tcc_research")
        assert upgrades == [] and len(opened) == 1
    else:
        assert tool.migrate_new(conf, owner, "sigra_tcc_research")["collection_enabled"] is False
        assert upgrades == [d.ALEMBIC_HEAD] and len(opened) == 2
    assert __import__("os").environ.get("MIGRATION_DATABASE_URL") == previous


class Result:
    def __init__(self, row): self.row = row
    def one(self): return self.row
    def one_or_none(self): return self.row
    def scalar_one(self): return self.row
    def all(self): return self.row
    def scalars(self): return self


def test_database_preflight_distinguishes_backend_false_missing_and_true(configured):
    values, target, _ = configured
    conf = d.settings(values)
    class Connection:
        engine = SimpleNamespace(url=conf.url)
        connection = SimpleNamespace(driver_connection=SimpleNamespace(
            pgconn=SimpleNamespace(ssl_in_use=True), info=SimpleNamespace(get_parameters=lambda: {
                "host": conf.url.host, "sslmode": "verify-full", "sslrootcert": "/synthetic/ca.crt"})))
        backend = (66, True, "TLSv1.3", "synthetic-cipher")
        queries = []
        def execute(self, statement, params=None):
            query = str(statement)
            self.queries.append(query)
            assert query.strip().startswith("SELECT")
            if "pg_backend_pid() AS pid" in query:
                return Result((target["database"], target["runtime_role"], 1234, 66, *self.backend))
            if "version_num" in query: return Result([d.ALEMBIC_HEAD])
            if "rolsuper" in query: return Result((False,) * 5)
            if "EXISTS(SELECT" in query: return Result(False)
            if "relrowsecurity" in query: return Result((True, True))
            if "p.polroles" in query: return Result([(True, "*")])
            raise AssertionError("Unexpected query")
    connection = Connection()
    assert d.database_preflight(connection, conf)["database_modified"] is False
    connection.backend = (66, False, None, None)
    with pytest.raises(ValueError, match="backend TLS not established"):
        d.database_preflight(connection, conf)
    connection.backend = (None, None, None, None)
    with pytest.raises(ValueError, match="OBSERVATION_MISSING"):
        d.database_preflight(connection, conf)
    assert all("UPDATE " not in q for q in connection.queries)
