"""Synthetic project receipts and SQL-shaped doubles: no database/network."""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import ssl
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL, make_url

from app.academic_cohort import revision6_homologation as h
from app.academic_cohort import revision6_supabase_target as guard
from backend.tests.test_revision6_homologation import ScriptedConnection, configuration

REF = "a" * 20  # Deliberately fictitious, test-only project; never connect.


@pytest.fixture
def remote(tmp_path):
    ca = tmp_path / "test-ca.pem"
    context = ssl.create_default_context()
    certificates = context.get_ca_certs(binary_form=True)
    for cert in certificates:
        ca.write_text(ssl.DER_cert_to_PEM_cert(cert), encoding="ascii")
        try:
            guard.certificate_sha256(str(ca))
            break
        except ValueError:
            continue
    else:
        pytest.fail("A valid system CA is required for the offline certificate parser test")
    project = {"id":REF,"organization_id":guard.ORGANIZATION,"name":guard.PROJECT_NAME,
        "status":"ACTIVE_HEALTHY","database":{"host":f"db.{REF}.supabase.co"}}
    receipt = guard.confirmation(project, str(ca))
    path = tmp_path / "confirmation.json"
    path.write_text(json.dumps(receipt),encoding="utf-8")
    values = configuration()
    values.update(SIGRA_REVISION6_TARGET_KIND="supabase",SIGRA_REVISION6_CONFIRM_PROJECT=REF,
        SIGRA_REVISION6_PROJECT_CONFIRMATION=str(path),
        SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
    for key, role in (("SIGRA_REVISION6_MIGRATION_URL",h.OWNER),("SIGRA_REVISION6_RUNTIME_URL",h.RUNTIME)):
        values[key] = URL.create("postgresql+psycopg",username=role,password="synthetic-test-only",
            host=project["database"]["host"],port=5432,database=h.DATABASE,
            query={"sslmode":"verify-full","sslrootcert":str(ca)}).render_as_string(hide_password=False)
    values["DATABASE_URL"] = values["SIGRA_REVISION6_RUNTIME_URL"]
    return values, path, ca, project


def test_exact_pinned_remote_configuration_and_private_repr(remote):
    values, _, _, _ = remote
    target = h.require_runtime(values)
    assert target.remote_confirmation.project_ref == REF
    assert target.runtime_url.query["sslmode"] == "verify-full"
    assert "synthetic-test-only" not in repr(target)
    assert h.target_configuration(configuration()).remote_confirmation is None


@pytest.mark.parametrize("field,value", [("id","zvuludzvdbxedhtrbqmy"),("id","ibsvxajuyvzszvgluqtx"),
    ("id","[COLE AQUI O REF REAL]"),("ref","b"*20),("name","another-project"),
    ("organization_id","another-org"),("status","INACTIVE"),("database",{"host":"unrelated.test"})])
def test_project_identity_never_accepts_old_placeholder_inactive_other_project(remote,field,value):
    _, _, _, project = remote
    with pytest.raises(ValueError):
        guard.project_identity({**project,field:value})


@pytest.mark.parametrize("field", ["SIGRA_REVISION6_PROJECT_CONFIRMATION","SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256",
    "SIGRA_REVISION6_CONFIRM_PROJECT"])
def test_remote_requires_explicit_confirmation(remote,field):
    values, _, _, _ = remote
    values.pop(field)
    with pytest.raises(ValueError): h.target_configuration(values)


@pytest.mark.parametrize("change", ["host","role","database","port","sslmode","options","duplicate","pooler","password"])
def test_url_cannot_bypass_exact_destination(remote,change):
    values, _, _, _ = remote
    key="SIGRA_REVISION6_RUNTIME_URL"
    url=make_url(values[key])
    if change in {"host","role","database","port","password"}:
        url=url.set(**{"host":{"host":"remote.test"},"role":{"username":h.OWNER},
            "database":{"database":"postgres"},"port":{"port":6543},"password":{"password":""}}[change])
    elif change == "pooler": url=url.set(host="aws-0-sa-east-1.pooler.supabase.com",username=f"{h.RUNTIME}.{REF}")
    else: url=url.update_query_dict({"sslmode":"require"} if change=="sslmode" else
        {"sslmode":("verify-full","disable")} if change=="duplicate" else {"options":"-c role=postgres"})
    values[key]=url.render_as_string(hide_password=False)
    with pytest.raises(ValueError) as error: h.target_configuration(values)
    assert "synthetic-test-only" not in str(error.value)


@pytest.mark.parametrize("mode", ["missing","invalid","changed","path"])
def test_ca_is_real_absolute_valid_and_unchanged(remote,mode):
    values, _, ca, _ = remote
    if mode=="missing": ca.unlink()
    elif mode=="invalid": ca.write_text("not a certificate")
    elif mode=="changed": ca.write_text(ca.read_text()+"\n")
    else:
        values["SIGRA_REVISION6_RUNTIME_URL"]=make_url(values["SIGRA_REVISION6_RUNTIME_URL"]).update_query_dict(
            {"sslrootcert":"relative-ca.pem"}).render_as_string(hide_password=False)
    with pytest.raises(ValueError): h.target_configuration(values)


def test_expired_or_non_ca_material_fails_closed(remote,monkeypatch):
    _, _, ca, _=remote
    monkeypatch.setattr(guard.ssl,"create_default_context",lambda **_:SimpleNamespace(get_ca_certs=lambda:[
        {"notBefore":"Jan  1 00:00:00 2010 GMT","notAfter":"Jan  1 00:00:00 2011 GMT"}]))
    with pytest.raises(ValueError): guard.certificate_sha256(str(ca))
    monkeypatch.setattr(guard.ssl,"create_default_context",lambda **_:SimpleNamespace(get_ca_certs=lambda:[]))
    with pytest.raises(ValueError): guard.certificate_sha256(str(ca))


def test_receipt_tampering_rejected(remote):
    values,path,_,_=remote
    path.write_text(path.read_text()+" ")
    with pytest.raises(ValueError): h.target_configuration(values)


def connected(remote, *, writer=False, tls=True, identity=None):
    values,_,_,_=remote
    target=h.target_configuration(values)
    results=[identity or (h.DATABASE,h.OWNER if writer else h.RUNTIME),(False,False,False,False),
             (tls,"TLSv1.3","TLS_AES_256_GCM_SHA384"),123]
    connection=ScriptedConnection(results)
    connection.engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
        url=target.migration_url if writer else target.runtime_url)
    connection.connection=SimpleNamespace(driver_connection=SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=tls)))
    return target,connection


def test_server_database_role_tls_are_checked_before_ddl(remote):
    target,conn=connected(remote)
    assert h.require_database_identity(conn,target=target)==123
    assert all(not sql.startswith(("CREATE","ALTER","INSERT")) for sql,_ in conn.calls)
    for tls,identity in [(False,None),(True,("postgres",h.RUNTIME)),(True,(h.DATABASE,h.OWNER))]:
        target,conn=connected(remote,tls=tls,identity=identity)
        with pytest.raises(ValueError): h.require_database_identity(conn,target=target)


def test_remote_new_target_proof_pins_ref_endpoint_ca_and_database_oid(remote):
    target,conn=connected(remote,writer=True)
    conn.results=iter([(h.DATABASE,h.OWNER),(False,False,False,False),(True,"TLSv1.3","cipher"),123,[]])
    proof=h.require_empty_target(conn,target)
    assert proof["remote_target"]==target.remote_confirmation.binding()
    assert proof["initially_empty"] is True and proof["database_oid"]==123


def test_certificate_change_after_target_construction_blocks_bind(remote):
    target,conn=connected(remote)
    remote[2].write_text(remote[2].read_text()+"\n")
    with pytest.raises(ValueError): target.check_bind(conn.engine)


def script_module():
    path=Path(__file__).resolve().parents[2]/"scripts/homologate_safety_revision6.py"
    spec=importlib.util.spec_from_file_location("revision6_commands_under_test",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preparation_checks_both_roles_before_migration_or_engine(tmp_path,monkeypatch):
    module=script_module()
    monkeypatch.setattr(module,"preflight",lambda _:(_ for _ in ()).throw(ValueError("runtime not available")))
    monkeypatch.setattr(module,"create_engine",lambda *a,**k:pytest.fail("No preparation engine before both-role preflight"))
    monkeypatch.setattr(module.command,"upgrade",lambda *a,**k:pytest.fail("No migration before both-role preflight"))
    with pytest.raises(ValueError,match="runtime not available"):
        module.prepare_new_database(h.target_configuration(configuration()),None,tmp_path/"proof.json")


def test_local_guard_not_relaxed_by_remote_receipt(remote):
    values,_,_,_=remote
    values["SIGRA_REVISION6_TARGET_KIND"]="local"
    with pytest.raises(ValueError): h.target_configuration(values)


def test_alternative_disabled_by_default_without_rotating_pseudonym_key(tmp_path,monkeypatch):
    module=script_module()
    for k,v in configuration().items(): monkeypatch.setenv(k,v)
    for k in ("SIGRA_REVISION6_HOMOLOGATION_ENABLED","SIGRA_REVISION6_BUNDLE","SIGRA_REVISION6_DECISION",
            "SIGRA_REVISION6_TARGET_PROOF","ACADEMIC_COHORT_ENABLED","FIPE_AUTO_REFRESH","DATABASE_ECHO",
            "SIGRA_DERIVED_PERSONALIZATION_ENABLED","PUBLIC_DEMO_MODE"):
        monkeypatch.setenv(k,__import__("os").environ.get(k,""))
    key="test-only-pseudonym-key-stable-32-bytes"
    monkeypatch.setenv("SIGRA_RESEARCH_PSEUDONYM_KEY",key)
    args=SimpleNamespace(bundle=tmp_path,decision=tmp_path/"decision",proof=tmp_path/"proof",derived_configurations=False)
    module.configure_runtime(h.target_configuration(configuration()),args)
    assert __import__("os").environ["SIGRA_RESEARCH_PSEUDONYM_KEY"]==key
    assert __import__("os").environ["SIGRA_DERIVED_PERSONALIZATION_ENABLED"]=="false"
    args.derived_configurations=True
    module.configure_runtime(h.target_configuration(configuration()),args)
    assert __import__("os").environ["SIGRA_DERIVED_PERSONALIZATION_ENABLED"]=="true"
    assert __import__("os").environ["SIGRA_TCC_COLLECTION_MODE"]=="homologation"


def test_server_rebinds_validated_runtime_not_the_early_default_engine(monkeypatch):
    from app import database, main
    module=script_module()
    for k,v in configuration().items(): monkeypatch.setenv(k,v)
    target=h.require_runtime(configuration())
    correct=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),url=target.runtime_url)
    for name in ("engine","DATABASE_SETTINGS","DATABASE_URL"):
        monkeypatch.setattr(database,name,getattr(database,name))
    monkeypatch.setattr(main,"DATABASE_SETTINGS",main.DATABASE_SETTINGS)
    monkeypatch.setattr(main,"SessionLocal",main.SessionLocal)
    fake_factory=SimpleNamespace(configure=lambda **kw:assert_runtime_bind(kw,correct))
    monkeypatch.setattr(database,"SessionLocal",fake_factory)
    monkeypatch.setattr(database,"create_database_engine",lambda settings:correct)
    assert module.bind_runtime_engine(target) is correct
    assert database.engine is correct and main.SessionLocal is fake_factory
    assert main.DATABASE_SETTINGS is database.DATABASE_SETTINGS
    assert make_url(database.DATABASE_URL).database==h.DATABASE


def assert_runtime_bind(arguments, expected):
    assert arguments=={"bind":expected}


def test_preflight_uses_both_readonly_roles_and_disposes(remote, monkeypatch):
    target,_=connected(remote)
    module=script_module()
    connections=[]
    disposed=[]
    def engine(url, **kwargs):
        writer=url==target.migration_url
        replies=[(h.DATABASE,h.OWNER if writer else h.RUNTIME), (False,)*5,
            (True,"TLSv1.3","cipher"),123]
        if writer:
            replies += [(h.DATABASE,h.OWNER),(False,)*5,(True,"TLSv1.3","cipher"),123,[],
                (True,False,False,False,False),True]
        replies += [0]
        class ReadonlyConnection(ScriptedConnection):
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def begin(self): return nullcontext()
            def execute(self,sql,params=None):
                if str(sql)=="SET TRANSACTION READ ONLY":
                    self.calls.append((str(sql),params))
                    return None
                return super().execute(sql,params)
        conn=ReadonlyConnection(replies)
        obj=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),url=url,
            connect=lambda:conn,dispose=lambda:disposed.append(url))
        conn.engine=obj
        conn.connection=SimpleNamespace(driver_connection=SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True)))
        connections.append(conn)
        return obj
    monkeypatch.setattr(module,"create_engine",engine)
    result=module.preflight(target)
    assert result["database_modified"] is False
    assert result["new_target_proof"]["remote_target"]==target.remote_confirmation.binding()
    assert disposed==[target.migration_url,target.runtime_url]
    assert len(connections)==2
    for conn in connections:
        assert conn.calls[0][0]=="SET TRANSACTION READ ONLY"
        assert all(sql.startswith(("SELECT","SET TRANSACTION READ ONLY")) for sql,_ in conn.calls)


def test_remote_grants_are_limited_to_dedicated_database_and_sigra_schemas(remote,monkeypatch):
    target,_=connected(remote)
    monkeypatch.setattr(h,"require_database_identity",lambda *a,**kw:123)
    monkeypatch.setattr(h,"_connection_target",lambda *a,**kw:target)
    class GrantRecorder(ScriptedConnection):
        def execute(self,sql,params=None):
            if not str(sql).startswith("SELECT"):
                self.calls.append((str(sql),params))
                return None
            return super().execute(sql,params)
    conn=GrantRecorder([(True,False,False,False,False),0,["anon","authenticated"],
        [*h.APP_SCHEMAS,"auth","storage"]])
    h.grant_runtime(conn)
    commands=[sql for sql,_ in conn.calls if not sql.startswith("SELECT")]
    assert f'REVOKE ALL ON DATABASE "{h.DATABASE}" FROM PUBLIC, {h.RUNTIME}' in commands
    assert f'GRANT CONNECT ON DATABASE "{h.DATABASE}" TO {h.OWNER}, {h.RUNTIME}' in commands
    assert not any('SCHEMA "auth"' in sql or 'SCHEMA "storage"' in sql for sql in commands)
    for table in h.PRIVATE_TABLES:
        assert f'ALTER TABLE public."{table}" FORCE ROW LEVEL SECURITY' in commands
    assert f"GRANT SELECT ON ALL TABLES IN SCHEMA academic TO {h.RUNTIME}" in commands
    assert not any("GRANT INSERT" in sql and "academic" in sql for sql in commands)


def test_replication_role_is_rejected(remote):
    target,conn=connected(remote)
    conn.results=iter([(h.DATABASE,h.RUNTIME),(False,False,False,False,True)])
    with pytest.raises(ValueError,match="must not be privileged"):
        h.require_database_identity(conn,target=target)


@pytest.mark.parametrize("command",["preflight","prepare-new-database","materialize","audit","serve"])
def test_missing_project_blocks_commands_before_replay_or_connection(command,remote,monkeypatch):
    values,_,_,_=remote
    for k,v in values.items(): monkeypatch.setenv(k,v)
    monkeypatch.delenv("SIGRA_REVISION6_PROJECT_CONFIRMATION")
    module=script_module()
    monkeypatch.setattr(module.h,"build_plan",lambda *a:pytest.fail("Missing target must block before replay"))
    monkeypatch.setattr(module,"create_engine",lambda *a,**k:pytest.fail("No database engine allowed"))
    with pytest.raises(ValueError,match="BLOCKED_BY_PROJECT_IDENTITY"):
        module.main([command,"--bundle","unused-test-only","--decision","unused-test-only","--proof","unused-test-only"])


@pytest.mark.parametrize("failure",[None,"temporary_or_create","data_api_grant","immutable_write"])
def test_remote_runtime_audit_rejects_excess_privileges(remote,monkeypatch,failure):
    target,_=connected(remote)
    monkeypatch.setattr(h,"require_database_identity",lambda *a,**kw:123)
    monkeypatch.setattr(h,"_connection_target",lambda *a,**kw:target)
    replies=[]
    for _ in range(3): replies.extend([True,*([False]*6)])
    for _ in h.PRIVATE_TABLES:
        replies.extend([(True,True),[("revision6_trusted_backend",True,"*")],0])
    replies.extend([0,0,False,failure=="temporary_or_create",
        [("public","users","SELECT")] if failure=="data_api_grant" else [],
        [("academic","cohort_vehicle")] if failure=="immutable_write" else []])
    conn=ScriptedConnection(replies)
    if failure:
        with pytest.raises(ValueError): h.audit_runtime_permissions(conn)
    else:
        assert h.audit_runtime_permissions(conn)["academic_runtime_read_only"] is True
    assert all(sql.strip().startswith("SELECT") for sql,_ in conn.calls)


def session_observation():
    # Deliberately fictitious tenant/endpoint in offline fixtures; never connect.
    return {"project_ref": REF, "host": "aws-9-sa-east-1.pooler.supabase.com",
        "port": 5432, "mode": "session", "operator_username": f"postgres.{REF}",
        "operator_database": "postgres", "source_url":
        f"https://supabase.com/dashboard/project/{REF}?showConnect=true&connectTab=direct&method=session",
        "observed_at": datetime.now(timezone.utc).isoformat()}


@pytest.fixture
def session_remote(remote):
    values, path, ca, project = remote
    observed = session_observation()
    receipt = guard.confirmation(project, str(ca), session_connection=observed)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    values["SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    for key, role in (("SIGRA_REVISION6_MIGRATION_URL", h.OWNER), ("SIGRA_REVISION6_RUNTIME_URL", h.RUNTIME)):
        values[key] = make_url(values[key]).set(host=observed["host"],
            username=f"{role}.{REF}").render_as_string(hide_password=False)
    values["DATABASE_URL"] = values["SIGRA_REVISION6_RUNTIME_URL"]
    return values, path, ca, project


def test_session_receipt_pins_observed_endpoint_and_wire_usernames(session_remote):
    target = h.require_runtime(session_remote[0])
    confirmed = target.remote_confirmation
    assert confirmed.host == session_observation()["host"]
    assert confirmed.endpoint_mode == "session"
    assert confirmed.username_for(h.OWNER) == f"{h.OWNER}.{REF}"
    assert target.runtime_url.username == f"{h.RUNTIME}.{REF}"
    assert confirmed.binding()["endpoint_mode"] == "session"
    assert target.runtime_url.port == 5432
    assert target.runtime_url.query["sslmode"] == "verify-full"
    assert "synthetic-test-only" not in repr(target)


def test_historical_direct_receipt_and_binding_are_unchanged(remote):
    confirmed = h.target_configuration(remote[0]).remote_confirmation
    assert confirmed.endpoint_mode == "direct"
    assert "endpoint_mode" not in confirmed.binding()
    assert confirmed.username_for(h.RUNTIME) == h.RUNTIME
    assert json.loads(remote[1].read_text())["version"] == guard.VERSION


@pytest.mark.parametrize("field,value", [
    ("project_ref", "b" * 20), ("mode", "transaction"), ("mode", "direct"),
    ("port", 6543), ("port", "5432"), ("port", True),
    ("host", "unrelated.test"), ("host", "aws-9-sa-east-1.pooler.supabase.com.attacker.test"),
    ("host", f"db.{REF}.supabase.co"), ("operator_username", "postgres"),
    ("operator_username", "postgres." + "b" * 20), ("operator_database", h.DATABASE),
    ("source_url", "https://supabase.com/dashboard/project/" + "b" * 20),
    ("observed_at", "invalid"), ("observed_at", "2099-01-01T00:00:00+00:00"),
    ("observed_at", "2026-01-01T00:00:00"),
])
def test_session_observation_rejects_unconfirmed_mode_tenant_source(remote, field, value):
    observed = {**session_observation(), field: value}
    with pytest.raises(ValueError):
        guard.confirmation(remote[3], str(remote[2]), session_connection=observed)


@pytest.mark.parametrize("field", list(session_observation()))
def test_session_observation_requires_all_fields(remote, field):
    observed = session_observation()
    observed.pop(field)
    with pytest.raises(ValueError):
        guard.confirmation(remote[3], str(remote[2]), session_connection=observed)


@pytest.mark.parametrize("changes", [
    {"host": "aws-0-sa-east-1.pooler.supabase.com"}, {"host": f"db.{REF}.supabase.co"},
    {"port": 6543}, {"username": h.RUNTIME}, {"username": f"{h.RUNTIME}." + "b" * 20},
    {"username": f"{h.OWNER}.{REF}"}, {"database": "postgres"}, {"database": "sigra_postgresql_demo"},
])
def test_session_does_not_allow_other_poolers_roles_databases_or_transaction(session_remote, changes):
    values = session_remote[0]
    key = "SIGRA_REVISION6_RUNTIME_URL"
    values[key] = make_url(values[key]).set(**changes).render_as_string(hide_password=False)
    with pytest.raises(ValueError):
        h.target_configuration(values)


@pytest.mark.parametrize("query", [
    {"sslmode": "require"}, {"sslmode": "verify-ca"}, {"sslmode": "disable"},
    {"sslmode": ("verify-full", "require")}, {"hostaddr": "127.0.0.1"},
    {"options": "-c role=postgres"},
])
def test_session_tls_and_options_cannot_bypass_exact_host(session_remote, query):
    values = session_remote[0]
    key = "SIGRA_REVISION6_RUNTIME_URL"
    values[key] = make_url(values[key]).update_query_dict(query).render_as_string(hide_password=False)
    with pytest.raises(ValueError):
        h.target_configuration(values)


def test_session_database_identity_is_the_plain_sql_role_not_wire_selector(session_remote):
    target, connection = connected(session_remote)
    assert h.require_database_identity(connection, target=target) == 123
    target, connection = connected(session_remote, identity=(h.DATABASE, f"{h.RUNTIME}.{REF}"))
    with pytest.raises(ValueError, match="database/role differs"):
        h.require_database_identity(connection, target=target)


def test_session_invalidated_receipt_and_ca_block_bind(session_remote):
    target, connection = connected(session_remote)
    session_remote[2].write_text(session_remote[2].read_text() + "\n")
    with pytest.raises(ValueError):
        target.check_bind(connection.engine)


@pytest.mark.parametrize("change", ["missing_observation", "version", "observation_tenant", "receipt_bytes"])
def test_session_receipt_cannot_be_downgraded_or_rebound(session_remote, change):
    values, path, _, _ = session_remote
    receipt = json.loads(path.read_text())
    if change == "missing_observation": receipt.pop("session_connection")
    elif change == "version": receipt["version"] = guard.VERSION
    elif change == "observation_tenant": receipt["session_connection"]["project_ref"] = "b" * 20
    path.write_text(json.dumps(receipt) + (" " if change == "receipt_bytes" else ""))
    if change != "receipt_bytes":
        values["SIGRA_REVISION6_PROJECT_CONFIRMATION_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        h.target_configuration(values)


def test_confirmation_cli_records_session_separately_without_secrets(remote, tmp_path, capsys):
    path = Path(__file__).resolve().parents[2] / "scripts/confirm_revision6_supabase_target.py"
    spec = importlib.util.spec_from_file_location("confirm_session_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project_path = tmp_path / "project.json"
    project_path.write_text(json.dumps(remote[3]), encoding="utf-8")
    observation_path = tmp_path / "session.json"
    observation_path.write_text(json.dumps(session_observation()), encoding="utf-8")
    new_receipt = tmp_path / "new-session-confirmation.json"
    original_bytes = remote[1].read_bytes()
    arguments = ["--project-response", str(project_path), "--confirm-project", REF,
        "--ca", str(remote[2]), "--session-connection", str(observation_path),
        "--output", str(new_receipt)]
    module.main(arguments)
    assert json.loads(new_receipt.read_text())["version"] == guard.SESSION_VERSION
    assert remote[1].read_bytes() == original_bytes
    report = json.loads(capsys.readouterr().out)
    assert report["database_connected"] is False and report["database_modified"] is False
    assert "synthetic-test-only" not in json.dumps(report)
    with pytest.raises(ValueError, match="NEW and outside"):
        module.main(arguments)


@pytest.mark.parametrize("mode,driver_tls,backend_tls,accepted", [
    ("session", True, (False, None, None), False),
    ("session", True, (True, "TLSv1.3", "cipher"), True),
    ("direct", True, (True, "TLSv1.2", "cipher"), True),
    ("direct", True, (False, None, None), False),
    ("session", False, (True, "TLSv1.3", "cipher"), False),
    ("session", False, (False, None, None), False),
    ("transaction", True, (False, None, None), False),
    ("session", True, None, False),
    ("session", True, 1, False),
    ("session", True, (1, None, None), False),
    ("session", True, (False, "TLSv1.3", None), False),
    ("session", True, (False, None, "cipher"), False),
    ("session", True, (True, "TLSv1.1", "cipher"), False),
    ("session", True, (True, "TLSv1.3", None), False),
])
def test_pooler_client_and_backend_tls_are_distinct_not_bypassed(mode, driver_tls, backend_tls, accepted):
    confirmed = SimpleNamespace(endpoint_mode=mode)
    if not accepted:
        with pytest.raises(ValueError):
            guard.validate_connection_tls(confirmed, driver_tls, backend_tls)
    else:
        result = guard.validate_connection_tls(confirmed, driver_tls, backend_tls)
        assert result["client_tls"] is True
        assert result["backend_tls"] is backend_tls[0]
        assert result["all_observed_links_tls"] is backend_tls[0]
        assert result["end_to_end_tls"] is (mode == "direct" and backend_tls[0])


def test_pinned_session_identity_rejects_unencrypted_supavisor_backend(session_remote):
    target, connection = connected(session_remote)
    connection.results = iter([(h.DATABASE, h.RUNTIME), (False,) * 5, (False, None, None), 123])
    with pytest.raises(ValueError, match="backend TLS not established"):
        h.require_database_identity(connection, target=target)
    assert all(sql.startswith("SELECT") for sql, _ in connection.calls)


def test_direct_tls_cannot_be_bypassed_with_pooler_link_observation(remote):
    target, connection = connected(remote)
    connection.results = iter([(h.DATABASE, h.RUNTIME), (False,) * 5, (False, None, None), 123])
    with pytest.raises(ValueError):
        h.require_database_identity(connection, target=target)
