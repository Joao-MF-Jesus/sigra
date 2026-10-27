"""Transport and target guards without network, credentials or Supabase side effects."""
from pathlib import Path
from unittest.mock import Mock

from fastapi import HTTPException
import pytest
from sqlalchemy.engine import URL

from app.config import database_connect_args, load_database_settings
from app.tcc_supabase import target_configuration


REF = "a" * 20


def configuration(tmp_path, pooler=False):
    certificate = tmp_path / "ca.pem"
    certificate.write_text("synthetic-certificate-only-for-offline-path-validation")
    host = "aws-0.example.pooler.supabase.com" if pooler else f"db.{REF}.supabase.co"
    result = {"SIGRA_TCC_HOMOLOGATION_PROJECT_REF": REF, "SIGRA_TCC_DATABASE_HOST": host}
    for name, user in (("MIGRATION", "postgres"), ("RUNTIME", "sigra_tcc_runtime")):
        url = URL.create("postgresql+psycopg", username=user + (f".{REF}" if pooler else ""),
                         password="synthetic-test-only", host=host, port=5432, database="postgres",
                         query={"sslmode": "verify-full", "sslrootcert": str(certificate)})
        result[f"SIGRA_TCC_HOMOLOGATION_{name}_URL"] = url.render_as_string(hide_password=False)
    return result


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_tls_explicit_mode_never_downgraded(mode):
    url = URL.create("postgresql+psycopg", host="example.test", database="test", query={"sslmode": mode})
    settings = load_database_settings({"DATABASE_ENV": "homologation", "DATABASE_URL": str(url)})
    assert database_connect_args(settings) == {"options": "-c timezone=UTC"}


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "not-a-mode"])
def test_weak_tls_fails_closed(mode):
    settings = load_database_settings({"DATABASE_ENV": "homologation", "DATABASE_URL":
                                      f"postgresql+psycopg://example.test/test?sslmode={mode}"})
    with pytest.raises(ValueError, match="required TLS"):
        database_connect_args(settings)


@pytest.mark.parametrize("pooler", [False, True])
def test_real_endpoint_is_pinned_and_no_secret_in_target_repr(tmp_path, pooler):
    target = target_configuration(configuration(tmp_path, pooler))
    assert target.project_ref == REF
    assert "synthetic-test-only" not in repr(target)
    assert target.migration_url.query["sslmode"] == "verify-full"


@pytest.mark.parametrize("change", ["host", "port", "role", "database", "ssl", "cert", "ref"])
def test_invalid_target_is_rejected_without_exposing_url(tmp_path, change):
    values = configuration(tmp_path)
    from sqlalchemy.engine import make_url
    key = "SIGRA_TCC_HOMOLOGATION_MIGRATION_URL"
    url = make_url(values[key])
    if change == "host":
        url = url.set(host="db.another-project.supabase.co")
    elif change == "port":
        url = url.set(port=6543)
    elif change == "role":
        url = url.set(username="sigra_demo")
    elif change == "database":
        url = url.set(database="sigra_postgresql_demo")
    elif change == "ssl":
        url = url.update_query_dict({"sslmode": "require"})
    elif change == "cert":
        url = url.update_query_dict({"sslrootcert": "not-an-absolute-certificate.pem"})
    else:
        values["SIGRA_TCC_HOMOLOGATION_PROJECT_REF"] = "invalid"
    values[key] = url.render_as_string(hide_password=False)
    with pytest.raises(ValueError) as error:
        target_configuration(values)
    assert "synthetic-test-only" not in str(error.value)


def test_duplicate_tls_parameter_rejected():
    settings = load_database_settings({"DATABASE_ENV": "homologation", "DATABASE_URL":
                                      "postgresql+psycopg://example.test/test?sslmode=require&sslmode=disable"})
    with pytest.raises(ValueError, match="exactly once"):
        database_connect_args(settings)


def test_migrations_use_same_transport_policy():
    source = Path(__file__).resolve().parents[1].joinpath("alembic/env.py").read_text()
    assert "connect_args=database_connect_args(settings)" in source


def test_cross_site_cookie_requires_secure_and_logout_uses_same_policy(monkeypatch):
    from app.auth import cookie_options
    monkeypatch.setenv("SIGRA_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("SIGRA_COOKIE_SECURE", "false")
    with pytest.raises(HTTPException) as error:
        cookie_options()
    assert error.value.status_code == 503
    monkeypatch.setenv("SIGRA_COOKIE_SECURE", "true")
    assert cookie_options() == {"secure": True, "samesite": "none", "httponly": True, "path": "/"}


def test_empty_target_and_permissions_functions_do_not_run_in_validate_only():
    # Execution is below the early return; this test never opens a database.
    source = Path(__file__).resolve().parents[2].joinpath("scripts/prepare_tcc_supabase.py").read_text()
    assert source.index("if args.validate_only:") < source.index("create_database_engine(settings_for")
    assert "--confirm-project" in source and "require_empty_application(connection)" in source


def test_role_permissions_are_fixed_and_never_use_supabase_auth():
    from app.tcc_supabase import PRIVATE_TABLES, harden_participant_access
    connection = Mock()
    def execute(statement, parameters=None):
        sql = str(statement)
        result = Mock()
        result.one_or_none.return_value = (True, False, False, False, False)
        result.scalar_one.return_value = 0
        result.scalars.return_value = ["public", "academic", "bronze", "silver", "gold", "meta", "auth", "storage"]
        return result
    connection.execute.side_effect = execute
    harden_participant_access(connection)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert sum("FORCE ROW LEVEL SECURITY" in statement for statement in statements) == len(PRIVATE_TABLES)
    assert sum("CREATE POLICY" in statement for statement in statements) == len(PRIVATE_TABLES)
    assert any('public."expenses"' in statement and "GRANT" in statement for statement in statements)
    assert all("auth.uid" not in statement for statement in statements)
    assert all('SCHEMA "auth"' not in statement and 'SCHEMA "storage"' not in statement for statement in statements)
    assert not any("GRANT INSERT" in statement and "academic" in statement for statement in statements)


@pytest.mark.parametrize("role", [(True, True, False, False, False), (True, False, True, False, False), None])
def test_privileged_or_absent_runtime_role_rejected_before_ddl(role):
    from app.tcc_supabase import harden_participant_access
    connection = Mock()
    connection.execute.return_value.one_or_none.return_value = role
    with pytest.raises(ValueError, match="non-privileged"):
        harden_participant_access(connection)
    assert connection.execute.call_count == 1


def test_research_export_key_not_provided_to_migration_script():
    # No hardcoded deployment secrets, no URL/secret output, and operator URL
    # explicitly stripped from runtime/admin child environment.
    source = Path(__file__).resolve().parents[2].joinpath("scripts/tcc_supabase_session.py").read_text()
    assert 'environment.pop("MIGRATION_DATABASE_URL", None)' in source
    assert 'environment.pop("SIGRA_TCC_HOMOLOGATION_MIGRATION_URL", None)' in source
    assert "getpass(" in source and "environment.clear()" in source


@pytest.mark.parametrize("records,bytes_total,projected", [(0, 0, None), (2, 24000, 1200000)])
def test_size_measurement_is_full_database_not_replay_and_projection_is_explicit(records, bytes_total, projected):
    from app.tcc_supabase import measure_database_size
    connection = Mock()
    def execute(statement):
        result = Mock()
        sql = str(statement)
        if "pg_database_size" in sql:
            result.scalar_one.return_value = 42_000_000
        elif "pg_total_relation_size" in sql:
            result.all.return_value = [("academic", 15_000_000), ("public", 120000)]
        else:
            result.one.return_value = (records, bytes_total)
        assert sql.lstrip().startswith("SELECT")
        return result
    connection.execute.side_effect = execute
    result = measure_database_size(connection)
    assert result["database_bytes"] == 42_000_000
    assert result["estimated_payload_bytes_for_100_runs"] == projected
    assert result["quota_dashboard_confirmation_required"] is True


def test_audit_only_never_creates_or_materializes():
    source = Path(__file__).resolve().parents[2].joinpath("scripts/prepare_tcc_supabase.py").read_text()
    audit = source[source.index("if args.audit_only:"):source.index("operator = create_database_engine")]
    assert "SET TRANSACTION READ ONLY" in audit and "_audit(session, snapshot, plan)" in audit
    assert "harden_participant_access" not in audit and "materialize(" not in audit and "command.upgrade" not in audit
