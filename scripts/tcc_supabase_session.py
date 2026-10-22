"""Prompt secrets locally and pass them only to the selected child process."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "prepare", "audit", "test", "serve", "admin"))
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--host", required=True, help="Actual direct/session host from Connect")
    parser.add_argument("--session-pooler", action="store_true")
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--confirm-project")
    parser.add_argument("--admin-email")
    parser.add_argument("--admin-name")
    args = parser.parse_args()
    migration = (getpass("Senha do operador do NOVO projeto (oculta): ")
                 if args.action in {"validate", "prepare", "test"} else "unused-validation-only")
    runtime = getpass("Senha do role sigra_tcc_runtime do NOVO projeto (oculta): ")
    suffix = f".{args.project_ref}" if args.session_pooler else ""
    query = {"sslmode": "verify-full", "sslrootcert": str(args.ca.resolve())}
    def url(user, password):
        return URL.create("postgresql+psycopg", username=user + suffix, password=password,
                          host=args.host, port=5432, database="postgres", query=query).render_as_string(hide_password=False)
    # Never change the parent process environment or write credentials to disk.
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "backend") + os.pathsep + str(ROOT),
        DATABASE_ENV="homologation", DATABASE_ECHO="false", DATABASE_SSL_REQUIRED="true",
        PUBLIC_DEMO_MODE="false", ACADEMIC_COHORT_ENABLED="true", FIPE_AUTO_REFRESH="false",
        SIGRA_TCC_COLLECTION_MODE="homologation",
        SIGRA_TCC_HOMOLOGATION_PROJECT_REF=args.project_ref, SIGRA_TCC_DATABASE_HOST=args.host,
        SIGRA_TCC_HOMOLOGATION_MIGRATION_URL=url("postgres", migration),
        SIGRA_TCC_HOMOLOGATION_RUNTIME_URL=url("sigra_tcc_runtime", runtime),
        SIGRA_ACADEMIC_V6_REPLAY_PATH=str(args.replay.resolve()))
    environment["DATABASE_URL"] = environment["SIGRA_TCC_HOMOLOGATION_RUNTIME_URL"]
    environment["MIGRATION_DATABASE_URL"] = environment["SIGRA_TCC_HOMOLOGATION_MIGRATION_URL"]
    from app.tcc_supabase import target_configuration
    target_configuration(environment)  # Validate even serve/admin before opening a connection.
    if args.action in {"serve", "admin"}:
        environment.pop("MIGRATION_DATABASE_URL", None)
        environment.pop("SIGRA_TCC_HOMOLOGATION_MIGRATION_URL", None)
    if args.action == "audit":
        # Target validator needs both role shapes; operator password here is
        # only the unused placeholder, never requested or connected.
        environment.pop("MIGRATION_DATABASE_URL", None)
    command = [sys.executable]
    if args.action in {"validate", "prepare", "audit"}:
        command += [str(ROOT / "scripts/prepare_tcc_supabase.py"), "--replay", str(args.replay.resolve()),
                    "--validate-only" if args.action == "validate" else "--audit-only" if args.action == "audit" else "--apply"]
        if args.action in {"prepare", "audit"}:
            command += ["--confirm-project", args.confirm_project or ""]
    elif args.action == "test":
        if args.confirm_project != args.project_ref:
            raise ValueError("Confirm the dedicated project before creating synthetic test participants")
        environment["SIGRA_TCC_HOMOLOGATION_TEST_APPROVAL"] = args.project_ref
        command += ["-m", "pytest", "backend/tests/test_tcc_supabase_postgresql.py", "-q", "-rs", "-p", "no:cacheprovider"]
    elif args.action == "admin":
        if not args.admin_email or not args.admin_name or args.confirm_project != args.project_ref:
            raise ValueError("Explicit project/admin identity confirmation is required")
        command += ["-m", "app.provision_admin", "--email", args.admin_email,
                    "--name", args.admin_name, "--confirm-admin"]
    else:
        environment["SIGRA_RESEARCH_PSEUDONYM_KEY"] = getpass("Chave estável de pseudonimização da pesquisa (oculta): ")
        command += ["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8010"]
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        return result.returncode
    finally:
        environment.clear()
        migration = runtime = ""  # Python cannot guarantee zeroization; never persist/print them.


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"TCC_SESSION_BLOCKED: {type(error).__name__}; configuration value not disclosed")
        raise SystemExit(1)
