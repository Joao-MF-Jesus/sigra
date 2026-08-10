import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import (
    DEFAULT_CORS_ALLOWED_ORIGINS,
    allowed_hosts,
    cors_allowed_origins,
    load_runtime_settings,
)
from app.fipe import ensure_fipe_prices_current
from app.http_middleware import (
    PublicDemoReadOnlyMiddleware,
    RequestLoggingMiddleware,
)


class CorsConfigurationTest(unittest.TestCase):
    @staticmethod
    def _preflight(origins, origin):
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return TestClient(app).options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    def test_defaults_are_stable_without_environment_variable(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cors_allowed_origins(), list(DEFAULT_CORS_ALLOWED_ORIGINS))
            self.assertNotIn("http://127.0.0.1:4183", cors_allowed_origins())

    def test_extra_origins_trim_empty_values_and_duplicates(self):
        configured = cors_allowed_origins(
            " http://127.0.0.1:4183, ,http://localhost:5173,http://127.0.0.1:4183 "
        )
        self.assertIn("http://127.0.0.1:4183", configured)
        self.assertEqual(configured.count("http://127.0.0.1:4183"), 1)
        self.assertEqual(configured.count("http://localhost:5173"), 1)

    def test_wildcard_is_never_enabled_by_configuration(self):
        self.assertNotIn("*", cors_allowed_origins("*,http://127.0.0.1:4183"))

    def test_e2e_origin_is_allowed_only_when_configured(self):
        origin = "http://127.0.0.1:4183"
        blocked = self._preflight(cors_allowed_origins(""), origin)
        allowed = self._preflight(cors_allowed_origins(origin), origin)
        self.assertNotEqual(blocked.headers.get("access-control-allow-origin"), origin)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), origin)

    def test_published_environment_has_no_local_defaults_and_requires_https(self):
        origin = "https://sigra-homolog.vercel.app"
        self.assertEqual(
            cors_allowed_origins(origin, environment="homologation"),
            [origin],
        )
        with self.assertRaises(ValueError):
            cors_allowed_origins(
                "http://localhost:4173",
                environment="homologation",
            )

    def test_runtime_settings_disable_docs_by_default_in_public_demo(self):
        settings = load_runtime_settings(
            {
                "DATABASE_ENV": "homologation",
                "PUBLIC_DEMO_MODE": "true",
                "ALLOWED_HOSTS": "sigra-api-homolog.onrender.com",
            }
        )
        self.assertTrue(settings.public_demo_mode)
        self.assertFalse(settings.api_docs_enabled)
        self.assertEqual(
            settings.allowed_hosts,
            ("sigra-api-homolog.onrender.com",),
        )

    def test_allowed_hosts_reject_urls_and_wildcard(self):
        self.assertEqual(allowed_hosts("api.example.com,*,api.example.com"), ["api.example.com"])
        with self.assertRaises(ValueError):
            allowed_hosts("https://api.example.com")


class PublicDemoMiddlewareTest(unittest.TestCase):
    @staticmethod
    def _client(enabled):
        app = FastAPI()
        app.add_middleware(PublicDemoReadOnlyMiddleware, enabled=enabled)

        @app.get("/vehicles")
        def vehicles():
            return []

        @app.get("/expenses")
        def expenses():
            return []

        @app.post("/recommendations")
        def recommendations():
            return {"status": "calculated"}

        @app.post("/users")
        def users():
            return {"status": "created"}

        return TestClient(app)

    def test_public_demo_allows_stateless_routes_and_blocks_shared_data(self):
        with self._client(True) as client:
            self.assertEqual(client.get("/vehicles").status_code, 200)
            self.assertEqual(client.post("/recommendations").status_code, 200)
            self.assertEqual(client.get("/expenses").status_code, 403)
            blocked = client.post("/users")
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(
                blocked.json()["detail"]["code"],
                "demo_read_only",
            )

    def test_local_environment_keeps_existing_routes(self):
        with self._client(False) as client:
            self.assertEqual(client.get("/expenses").status_code, 200)
            self.assertEqual(client.post("/users").status_code, 200)

    def test_request_log_has_trace_fields_without_query_or_body(self):
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.post("/recommendations")
        def recommendations():
            return {"status": "ok"}

        with self.assertLogs("sigra.http", level="INFO") as captured:
            response = TestClient(app).post(
                "/recommendations?token=should-not-be-logged",
                json={"password": "should-not-be-logged"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))
        combined = "\n".join(captured.output)
        for required in (
            "timestamp=",
            "request_id=",
            "method=POST",
            "path=/recommendations",
            "status=200",
            "duration_ms=",
        ):
            self.assertIn(required, combined)
        self.assertNotIn("should-not-be-logged", combined)


class FipeE2EIsolationTest(unittest.TestCase):
    def test_disabled_auto_refresh_never_calls_network_refresh(self):
        with patch.dict(os.environ, {"FIPE_AUTO_REFRESH": "false"}, clear=False):
            with patch("app.fipe.refresh_fipe_prices") as refresh:
                ensure_fipe_prices_current()
        refresh.assert_not_called()
