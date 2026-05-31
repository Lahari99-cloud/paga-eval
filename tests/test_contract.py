"""Deployment-contract and container health-probe tests."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from paga.healthcheck import main as healthcheck_main


EXPECTED_PATHS = {
    "/healthz",
    "/readyz",
    "/v1/evaluations",
    "/v1/reports",
    "/v1/profiles",
    "/v1/profiles/lookup",
    "/v1/profiles/delete",
    "/v1/maintenance/prune",
    "/v1/operations/stats",
}


def test_checked_in_openapi_contract_contains_expected_routes():
    contract = json.loads(Path("openapi.json").read_text(encoding="ascii"))
    assert contract["info"]["version"] == "0.4.0"
    assert EXPECTED_PATHS <= contract["paths"].keys()


def test_healthcheck_accepts_ready_service(monkeypatch):
    class ReadyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), ReadyHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("PAGA_HEALTHCHECK_URL", f"http://127.0.0.1:{server.server_port}/readyz")
        healthcheck_main()
    finally:
        server.shutdown()
        thread.join()
