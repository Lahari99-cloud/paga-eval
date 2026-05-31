"""Hosted API authentication, persistence, and operational tests."""

import asyncio
import json
import logging

from fastapi.testclient import TestClient
import pytest

from paga.api import APIKeyCredential, Permission, ServiceSettings, create_app
from paga.storage import EncryptedProfileStore


def _settings(tmp_path, *, max_request_bytes=32_768, log_requests=True):
    return ServiceSettings(
        api_key="api-key-with-at-least-24-characters",
        profile_salt="profile-salt-with-at-least-24-characters",
        encryption_key=EncryptedProfileStore.generate_key(),
        database_path=str(tmp_path / "profiles.sqlite3"),
        retention_days=30,
        max_request_bytes=max_request_bytes,
        log_requests=log_requests,
    )


def _headers():
    return {"X-API-Key": "api-key-with-at-least-24-characters"}


def test_health_and_readiness_are_available_without_auth(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json() == {"status": "ready"}


def test_evaluation_requires_auth_and_omits_transcript_audit_text(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    payload = {"target": "rabbit", "attempt": "wabbit", "action": "accept"}
    assert client.post("/v1/evaluations", json=payload).status_code == 401
    response = client.post("/v1/evaluations", json=payload, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "PASS"
    assert body["audit_record"]["target"] == ""
    assert body["audit_record"]["attempt"] == ""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]
    stats = client.get("/v1/operations/stats", headers=_headers())
    assert stats.json()["stored_audits"] == 1


def test_profiles_persist_across_app_restart_and_can_be_deleted(tmp_path):
    settings = _settings(tmp_path)
    payload = {"user_id": "student-123", "pattern": "word_substitution", "category": "decoding_error"}
    first = TestClient(create_app(settings)).post("/v1/profiles", json=payload, headers=_headers())
    assert first.json()["pace_metrics"]["total_attempts"] == 1

    restarted = TestClient(create_app(settings))
    second = restarted.post("/v1/profiles", json=payload, headers=_headers())
    assert second.json()["pace_metrics"]["total_attempts"] == 2
    lookup = restarted.post("/v1/profiles/lookup", json={"user_id": "student-123"}, headers=_headers())
    assert lookup.json()["total_attempts"] == 2
    deleted = restarted.post("/v1/profiles/delete", json={"user_id": "student-123"}, headers=_headers())
    assert deleted.json() == {"deleted": True}


def test_reports_aggregate_authenticated_cohort_requests(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.post(
        "/v1/reports",
        headers=_headers(),
        json={
            "evaluations": [
                {"cohort": "grade-k", "target": "rabbit", "attempt": "wabbit", "action": "accept"},
                {"cohort": "grade-k", "target": "rabbit", "attempt": "wabbit", "action": "correct"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["cohorts"][0]["over_intervention_rate"] == 0.5


def test_request_size_limit_is_enforced(tmp_path):
    client = TestClient(create_app(_settings(tmp_path, max_request_bytes=16)))
    response = client.post(
        "/v1/evaluations",
        headers={**_headers(), "Content-Length": "100"},
        json={"target": "rabbit", "attempt": "wabbit", "action": "accept"},
    )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_duplicate_evaluation_id_returns_conflict(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    payload = {"evaluation_id": "duplicate", "target": "rabbit", "attempt": "wabbit", "action": "accept"}
    assert client.post("/v1/evaluations", headers=_headers(), json=payload).status_code == 200
    assert client.post("/v1/evaluations", headers=_headers(), json=payload).status_code == 409


def test_report_audits_are_atomic_when_batch_contains_duplicate_evaluation_ids(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.post(
        "/v1/reports",
        headers=_headers(),
        json={
            "evaluations": [
                {
                    "cohort": "grade-k",
                    "evaluation_id": "duplicate-report-id",
                    "target": "rabbit",
                    "attempt": "wabbit",
                    "action": "accept",
                },
                {
                    "cohort": "grade-k",
                    "evaluation_id": "duplicate-report-id",
                    "target": "think",
                    "attempt": "fink",
                    "action": "accept",
                },
            ]
        },
    )
    assert response.status_code == 409
    stats = client.get("/v1/operations/stats", headers=_headers())
    assert stats.json()["stored_audits"] == 0


def test_environment_settings_fail_fast_with_actionable_names(monkeypatch):
    monkeypatch.delenv("PAGA_API_KEY", raising=False)
    monkeypatch.delenv("PAGA_API_KEYS_JSON", raising=False)
    monkeypatch.delenv("PAGA_PROFILE_SALT", raising=False)
    monkeypatch.delenv("PAGA_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValueError, match="PAGA_API_KEY"):
        ServiceSettings.from_env()


def test_streamed_body_limit_does_not_require_content_length(tmp_path):
    app = create_app(_settings(tmp_path, max_request_bytes=8))
    sent = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"0123456789", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/evaluations",
        "raw_path": b"/v1/evaluations",
        "query_string": b"",
        "headers": [
            (b"x-api-key", b"api-key-with-at-least-24-characters"),
            (b"content-type", b"application/json"),
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert starts[-1]["status"] == 413


def test_scoped_credentials_enforce_permissions_and_tenant_audit_isolation(tmp_path):
    credentials = (
        APIKeyCredential(
            "district-a-key-with-at-least-24-characters",
            tenant_id="district-a",
            permissions=frozenset({Permission.EVALUATE, Permission.OPERATIONS}),
        ),
        APIKeyCredential(
            "district-b-key-with-at-least-24-characters",
            tenant_id="district-b",
            permissions=frozenset({Permission.EVALUATE, Permission.OPERATIONS}),
        ),
    )
    settings = _settings(tmp_path)
    settings = ServiceSettings(
        api_key=None,
        api_credentials=credentials,
        profile_salt=settings.profile_salt,
        encryption_key=settings.encryption_key,
        database_path=settings.database_path,
    )
    client = TestClient(create_app(settings))
    payload = {"evaluation_id": "same-id", "target": "rabbit", "attempt": "wabbit", "action": "accept"}
    headers_a = {"X-API-Key": credentials[0].key}
    headers_b = {"X-API-Key": credentials[1].key}
    assert client.post("/v1/evaluations", headers=headers_a, json=payload).status_code == 200
    assert client.post("/v1/evaluations", headers=headers_b, json=payload).status_code == 200
    assert client.get("/v1/operations/stats", headers=headers_a).json()["stored_audits"] == 1
    assert client.get("/v1/operations/stats", headers=headers_b).json()["stored_audits"] == 1
    assert client.post("/v1/profiles/lookup", headers=headers_a, json={"user_id": "student"}).status_code == 403


def test_profile_storage_is_isolated_between_tenants(tmp_path):
    credentials = tuple(
        APIKeyCredential(
            f"district-{suffix}-key-with-at-least-24-characters",
            tenant_id=f"district-{suffix}",
            permissions=frozenset({Permission.PROFILE_READ, Permission.PROFILE_WRITE}),
        )
        for suffix in ("a", "b")
    )
    base = _settings(tmp_path)
    client = TestClient(create_app(ServiceSettings(
        api_key=None,
        api_credentials=credentials,
        profile_salt=base.profile_salt,
        encryption_key=base.encryption_key,
        database_path=base.database_path,
    )))
    payload = {"user_id": "same-student", "pattern": "gliding_r_w"}
    profile_a = client.post("/v1/profiles", headers={"X-API-Key": credentials[0].key}, json=payload).json()
    profile_b = client.post("/v1/profiles", headers={"X-API-Key": credentials[1].key}, json=payload).json()
    assert profile_a["user_id"] != profile_b["user_id"]


def test_request_id_is_preserved_when_valid(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/healthz", headers={"X-Request-ID": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"


def test_environment_settings_load_scoped_credentials(monkeypatch):
    monkeypatch.delenv("PAGA_API_KEY", raising=False)
    monkeypatch.setenv("PAGA_PROFILE_SALT", "environment-profile-salt-at-least-24")
    monkeypatch.setenv("PAGA_ENCRYPTION_KEY", EncryptedProfileStore.generate_key())
    monkeypatch.setenv("PAGA_API_KEYS_JSON", json.dumps([
        {
            "key": "environment-api-key-at-least-24",
            "tenant_id": "district-a",
            "permissions": ["evaluate", "operations"],
        }
    ]))
    settings = ServiceSettings.from_env()
    assert settings.credentials[0].tenant_id == "district-a"
    assert settings.credentials[0].permissions == frozenset({Permission.EVALUATE, Permission.OPERATIONS})


def test_structured_request_logs_correlate_tenant_without_payload_data(tmp_path, caplog):
    client = TestClient(create_app(_settings(tmp_path)))
    caplog.set_level(logging.INFO, logger="paga.api.access")
    response = client.post(
        "/v1/evaluations",
        headers={**_headers(), "X-Request-ID": "trace-log-123"},
        json={"target": "rabbit", "attempt": "wabbit", "action": "accept"},
    )
    assert response.status_code == 200
    event = json.loads(caplog.records[-1].message)
    assert event["event"] == "http_request"
    assert event["method"] == "POST"
    assert event["path"] == "/v1/evaluations"
    assert event["request_id"] == "trace-log-123"
    assert event["status_code"] == 200
    assert event["tenant_id"] == "default"
    assert event["duration_ms"] >= 0
    assert "rabbit" not in caplog.records[-1].message
    assert "wabbit" not in caplog.records[-1].message
    assert _headers()["X-API-Key"] not in caplog.records[-1].message


def test_structured_request_logs_mark_unauthorized_requests(tmp_path, caplog):
    client = TestClient(create_app(_settings(tmp_path)))
    caplog.set_level(logging.INFO, logger="paga.api.access")
    response = client.get("/v1/operations/stats", headers={"X-API-Key": "incorrect"})
    assert response.status_code == 401
    event = json.loads(caplog.records[-1].message)
    assert event["status_code"] == 401
    assert event["tenant_id"] == "unauthenticated"


def test_environment_settings_reject_invalid_log_request_flag(monkeypatch):
    monkeypatch.setenv("PAGA_API_KEY", "environment-api-key-at-least-24")
    monkeypatch.setenv("PAGA_PROFILE_SALT", "environment-profile-salt-at-least-24")
    monkeypatch.setenv("PAGA_ENCRYPTION_KEY", EncryptedProfileStore.generate_key())
    monkeypatch.setenv("PAGA_LOG_REQUESTS", "sometimes")
    with pytest.raises(ValueError, match="PAGA_LOG_REQUESTS"):
        ServiceSettings.from_env()
