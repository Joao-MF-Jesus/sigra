import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smoke_test_homologation import (
    contains_sensitive_response_data,
    smoke_checks,
    validate_public_url,
)


class SmokeHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def _send(self, status, payload, *, content_type="application/json"):
        body = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else json.dumps(payload).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(200, "<html><title>SIGRA</title></html>", content_type="text/html")
        elif self.path == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "public_demo_mode": True,
                    "database": {
                        "reachable": True,
                        "migration_up_to_date": True,
                    },
                },
            )
        elif self.path == "/health/database":
            self._send(
                200,
                {
                    "status": "ok",
                    "database": {
                        "reachable": True,
                        "migration_up_to_date": True,
                    },
                },
            )
        elif self.path == "/vehicles":
            self._send(200, [{"id": 1}])
        elif self.path == "/motorcycles":
            self._send(200, [{"id": 1}])
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)
        if self.path == "/recommendations":
            self._send(200, [{"vehicle": {"id": 1}}])
        elif self.path == "/financing/simulate":
            self._send(200, {"regular_installment": 700})
        elif self.path == "/motorcycles/recommendations":
            self._send(
                501,
                {
                    "algorithm_version": None,
                    "weights_version": None,
                },
            )
        elif self.path == "/users":
            self._send(
                403,
                {
                    "detail": {
                        "code": "demo_read_only",
                        "message": "read only",
                    }
                },
            )
        else:
            self._send(404, {"detail": "not found"})


class HomologationSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_reproducible_smoke_checks_cover_safe_homologation_contract(self):
        report = smoke_checks(
            self.base_url,
            self.base_url,
            require_https=False,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checks_total"], 10)
        self.assertEqual(report["checks_failed"], 0)
        self.assertTrue(
            any(
                check["name"] == "persistent_write_blocked"
                for check in report["checks"]
            )
        )

    def test_public_urls_require_https_and_reject_embedded_credentials(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_public_url("http://example.test", "backend")
        with self.assertRaisesRegex(ValueError, "credenciais"):
            validate_public_url(
                "https://user:secret@example.test",
                "backend",
            )

    def test_sensitive_response_markers_are_detected(self):
        markers = contains_sensitive_response_data(
            '{"DATABASE_URL":"postgresql://user:'
            + 'secret@host/database"}'
        )
        self.assertIn("database_url", markers)
        self.assertIn("postgresql://", markers)


if __name__ == "__main__":
    unittest.main()
