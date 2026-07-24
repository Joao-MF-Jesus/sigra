from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ContinuousIntegrationConfigurationTest(unittest.TestCase):
    def test_quality_workflow_has_required_jobs_and_e2e_environment(self):
        workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
        for job in (
            "  backend-sqlite:\n",
            "  backend-postgresql:\n",
            "  frontend:\n",
            "  e2e:\n",
            "  package-validation:\n",
        ):
            self.assertIn(job, workflow)
        for required in (
            "FIPE_AUTO_REFRESH: \"false\"",
            "CORS_ALLOWED_ORIGINS: \"http://127.0.0.1:4183\"",
            "SIGRA_E2E_RUN_ID:",
            "npx playwright install --with-deps chromium",
            "npm run test:e2e",
            "if: failure()",
            'SIGRA_RUN_POSTGRES_TESTS: "1"',
            "python scripts/wait_for_database.py --require-postgresql",
            "python scripts/validate_postgresql_schema.py",
            "SIGRA_CANONICAL_SQLITE_PATH:",
            "python scripts/bootstrap_ci_sqlite.py",
            "PostgreSQLIntegrationEnvironmentTest",
            "Create isolated PostgreSQL databases",
            "Validate Alembic cycle in disposable database",
            "scripts/export_sqlite_data.py",
            "scripts/validate_database_export.py",
            "scripts/import_postgresql_data.py",
            "--confirm-import",
            "scripts/compare_database_contents.py",
            "env -u DATABASE_URL -u DATABASE_ENV",
            '-p "test_motorcycle_stabilization_v031.py"',
            '-p "test_stabilization_patch.py"',
        ):
            self.assertIn(required, workflow)
        self.assertIn(
            "needs: [backend-sqlite, backend-postgresql, frontend, e2e]",
            workflow,
        )

    def test_playwright_uses_controlled_database_and_single_worker(self):
        config = (ROOT / "frontend" / "playwright.config.js").read_text(encoding="utf-8")
        self.assertIn("workers: 1", config)
        self.assertIn("prepareE2EEnvironment", config)
        self.assertIn('globalTeardown: "./e2e/global-teardown.js"', config)
        self.assertIn("DATABASE_URL: e2eEnvironment.databaseUrl", config)
        self.assertIn('FIPE_AUTO_REFRESH: "false"', config)
        self.assertIn("CORS_ALLOWED_ORIGINS: frontendUrl", config)

    def test_windows_e2e_runner_and_gitignore_are_safe(self):
        runner = (ROOT / "scripts" / "run_e2e_windows.ps1").read_text(
            encoding="utf-8"
        )
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for required in (
            "SIGRA_E2E_RUN_ID",
            "SIGRA_PYTHON_BIN",
            "FIPE_AUTO_REFRESH",
            "Get-CanonicalSnapshot",
            "npm run test:e2e",
            "ports_released",
            "e2e-local-report.json",
        ):
            self.assertIn(required, runner)
        self.assertNotIn("git init", runner)
        self.assertNotIn("git push", runner)
        for required in (
            ".venv-validation/",
            ".npm-cache-validation/",
            "node_modules/",
            "dist/",
            "*.db",
            "*.sqlite",
            "*.zip",
            "frontend/test-results/",
        ):
            self.assertIn(required, gitignore)

    def test_postgresql_compose_uses_isolated_databases_and_healthcheck(self):
        compose = (ROOT / "docker-compose.postgres.yml").read_text(
            encoding="utf-8"
        )
        init_script = (
            ROOT
            / "scripts"
            / "postgres-init"
            / "01-create-validation-databases.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("POSTGRES_INITDB_ARGS", compose)
        self.assertIn("pg_isready", compose)
        self.assertIn("sigra_dev", compose)
        self.assertIn("sigra_integration", init_script)
        self.assertIn("sigra_migration_test", init_script)
