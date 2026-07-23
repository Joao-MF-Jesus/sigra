import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import DEFAULT_CORS_ALLOWED_ORIGINS, cors_allowed_origins
from app.fipe import ensure_fipe_prices_current


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


class FipeE2EIsolationTest(unittest.TestCase):
    def test_disabled_auto_refresh_never_calls_network_refresh(self):
        with patch.dict(os.environ, {"FIPE_AUTO_REFRESH": "false"}, clear=False):
            with patch("app.fipe.refresh_fipe_prices") as refresh:
                ensure_fipe_prices_current()
        refresh.assert_not_called()
