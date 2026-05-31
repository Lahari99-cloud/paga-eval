"""Real-service institution demo tests."""

import importlib.util
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from paga.api import ServiceSettings
from paga.storage import EncryptedProfileStore

_DEMO_APP_PATH = Path(__file__).parents[1] / "examples" / "institution_demo_app.py"
_DEMO_APP_SPEC = importlib.util.spec_from_file_location("paga_institution_demo_app", _DEMO_APP_PATH)
assert _DEMO_APP_SPEC is not None and _DEMO_APP_SPEC.loader is not None
_DEMO_APP_MODULE = importlib.util.module_from_spec(_DEMO_APP_SPEC)
_DEMO_APP_SPEC.loader.exec_module(_DEMO_APP_MODULE)
create_demo_app = _DEMO_APP_MODULE.create_demo_app


def _settings(tmp_path):
    return ServiceSettings(
        api_key="local-demo-api-key-at-least-24",
        profile_salt="local-demo-profile-salt-at-least-24",
        encryption_key=EncryptedProfileStore.generate_key(),
        database_path=str(tmp_path / "demo.sqlite3"),
    )


def test_demo_console_is_same_origin_wrapper_around_real_service(tmp_path):
    client = TestClient(create_demo_app(_settings(tmp_path)))
    assert client.get("/", follow_redirects=False).headers["location"] == "/demo"
    page = client.get("/demo")
    assert page.status_code == 200
    assert "paga-eval Educator Console" in page.text
    assert 'api("/v1/evaluations"' in page.text
    assert 'api("/v1/profiles"' in page.text
    assert 'api("/v1/operations/stats"' in page.text
    assert 'window.location.protocol === "file:"' not in page.text
    assert 'audit.target==null&&audit.attempt==null' in page.text
    assert 'role="status" aria-live="polite"' in page.text
    assert 'aria-live="polite"' in page.text
    assert "confirm(" in page.text
    assert "AbortSignal.timeout" in page.text
    assert "withPending" in page.text
    assert 'id="mode-banner"' in page.text
    assert "Connected to the local reference service." in page.text
    assert "evaluateOffline" in page.text
    assert "activateOfflineMode" in page.text
    assert 'data-requires-api="true"' in page.text
    assert "Static portfolio mode" in page.text

    response = client.post(
        "/v1/evaluations",
        headers={"X-API-Key": "local-demo-api-key-at-least-24"},
        json={"target": "rabbit", "attempt": "wabbit", "action": "accept"},
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == "PASS"
    assert response.json()["audit_record"]["target"] == ""


def test_demo_wrapper_does_not_enable_cross_origin_file_preview(tmp_path):
    client = TestClient(create_demo_app(_settings(tmp_path)))
    response = client.options(
        "/healthz",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_demo_profile_storage_is_encrypted_at_rest(tmp_path):
    settings = _settings(tmp_path)
    client = TestClient(create_demo_app(settings))
    response = client.post(
        "/v1/profiles",
        headers={"X-API-Key": "local-demo-api-key-at-least-24"},
        json={
            "user_id": "student-demo-encryption-check",
            "pattern": "gliding_r_w",
            "category": "developmental_speech_pattern",
        },
    )
    assert response.status_code == 200
    with sqlite3.connect(settings.database_path) as connection:
        encrypted = connection.execute("SELECT encrypted_profile FROM learner_profiles").fetchone()[0]
    assert b"student-demo-encryption-check" not in encrypted
    assert b"gliding_r_w" not in encrypted


def test_documented_demo_launcher_imports_when_run_as_script():
    import os
    import subprocess
    import sys
    import time

    environment = {**os.environ, "PAGA_DEMO_PORT": "0"}
    process = subprocess.Popen(
        [
            sys.executable,
            "examples/run_institution_demo.py",
        ],
        env=environment,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(1)
        assert process.poll() is None, process.stderr.read()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_readme_puts_demo_launch_near_the_top():
    from pathlib import Path

    readme = Path("README.md").read_text(encoding="utf-8")
    demo_heading = readme.index("## Run The Demo")
    install_heading = readme.index("## Install")
    assert demo_heading < install_heading
    assert "python examples/run_institution_demo.py" in readme[demo_heading:install_heading]
    assert "http://127.0.0.1:8000/demo" in readme[demo_heading:install_heading]
