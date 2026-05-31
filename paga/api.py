"""Authenticated FastAPI service for institutional PAGA deployments."""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from enum import Enum
from hmac import compare_digest
from time import perf_counter
from typing import Annotated
from uuid import uuid4

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as error:  # pragma: no cover - exercised in minimal installs
    raise ImportError("The hosted API requires: pip install 'paga-eval[service]'") from error

from paga import __version__
from paga.integrations import EvaluationService
from paga.metrics import (
    EnterprisePhonemeEvaluator,
    LearnerProfileAdapter,
    PatternCategory,
    PhonemeAwareOverInterventionMetric,
    PolicyPack,
)
from paga.reporting import build_institutional_report
from paga.storage import EncryptedProfileStore

ACCESS_LOGGER = logging.getLogger("paga.api.access")


def _configure_access_logger() -> None:
    """Emit JSON events directly unless the hosting runtime configured logging."""

    ACCESS_LOGGER.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not ACCESS_LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        ACCESS_LOGGER.addHandler(handler)


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


class RequestBodyLimitMiddleware:
    """Reject oversized requests even when Content-Length is absent."""

    def __init__(self, app, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = dict(scope.get("headers", ())).get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_request_bytes:
                    await self._reject(send, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                    return
            except ValueError:
                await self._reject(send, status.HTTP_400_BAD_REQUEST)
                return

        received = 0
        messages = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    await self._reject(send, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
            else:
                messages.append(message)
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send, status_code: int) -> None:
        await send({"type": "http.response.start", "status": status_code, "headers": []})
        await send({"type": "http.response.body", "body": b""})


class Permission(str, Enum):
    EVALUATE = "evaluate"
    REPORT = "report"
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    OPERATIONS = "operations"


ALL_PERMISSIONS = frozenset(Permission)


@dataclass(frozen=True)
class APIKeyCredential:
    """One tenant-scoped service credential."""

    key: str
    tenant_id: str = "default"
    permissions: frozenset[Permission] = ALL_PERMISSIONS

    def __post_init__(self) -> None:
        if len(self.key) < 24:
            raise ValueError("Service API keys must contain at least 24 characters.")
        EncryptedProfileStore._validate_tenant_id(self.tenant_id)
        object.__setattr__(self, "permissions", frozenset(Permission(permission) for permission in self.permissions))

    @classmethod
    def from_dict(cls, payload: dict) -> APIKeyCredential:
        return cls(
            key=payload["key"],
            tenant_id=payload.get("tenant_id", "default"),
            permissions=frozenset(payload.get("permissions", ALL_PERMISSIONS)),
        )


@dataclass(frozen=True)
class ServiceSettings:
    """Deployment configuration loaded from a secrets-aware environment."""

    api_key: str | None
    profile_salt: str
    encryption_key: str
    api_credentials: tuple[APIKeyCredential, ...] = ()
    decryption_keys: tuple[str, ...] = ()
    database_path: str = "paga_profiles.sqlite3"
    retention_days: int = 30
    max_request_bytes: int = 32_768
    log_requests: bool = True
    min_acoustic_confidence: float = 0.72
    min_phoneme_confidence: float = 0.5
    max_low_confidence_phoneme_ratio: float = 0.3

    def __post_init__(self) -> None:
        if not self.api_key and not self.api_credentials:
            raise ValueError("Configure PAGA_API_KEY or PAGA_API_KEYS_JSON.")
        if self.api_key and len(self.api_key) < 24:
            raise ValueError("PAGA_API_KEY must contain at least 24 characters.")
        if len(self.profile_salt) < 24:
            raise ValueError("PAGA_PROFILE_SALT must contain at least 24 characters.")
        if self.retention_days < 1:
            raise ValueError("PAGA_RETENTION_DAYS must be >= 1.")
        if self.max_request_bytes < 1:
            raise ValueError("PAGA_MAX_REQUEST_BYTES must be >= 1.")
        for name, value in (
            ("PAGA_MIN_ACOUSTIC_CONFIDENCE", self.min_acoustic_confidence),
            ("PAGA_MIN_PHONEME_CONFIDENCE", self.min_phoneme_confidence),
            ("PAGA_MAX_LOW_CONFIDENCE_PHONEME_RATIO", self.max_low_confidence_phoneme_ratio),
        ):
            if value < 0.0 or value > 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0.")
        keys = [credential.key for credential in self.credentials]
        if len(keys) != len(set(keys)):
            raise ValueError("Service API keys must be unique.")

    @property
    def credentials(self) -> tuple[APIKeyCredential, ...]:
        legacy = (APIKeyCredential(self.api_key),) if self.api_key else ()
        return (*legacy, *self.api_credentials)

    @classmethod
    def from_env(cls) -> ServiceSettings:
        legacy_api_key = os.getenv("PAGA_API_KEY")
        credentials_json = os.getenv("PAGA_API_KEYS_JSON", "")
        required = {
            "PAGA_PROFILE_SALT": os.getenv("PAGA_PROFILE_SALT"),
            "PAGA_ENCRYPTION_KEY": os.getenv("PAGA_ENCRYPTION_KEY"),
        }
        missing = [name for name, value in required.items() if not value]
        if not legacy_api_key and not credentials_json:
            missing.append("PAGA_API_KEY or PAGA_API_KEYS_JSON")
        if missing:
            raise ValueError(f"Missing required service environment variables: {', '.join(missing)}")
        try:
            credentials = tuple(APIKeyCredential.from_dict(item) for item in json.loads(credentials_json or "[]"))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("PAGA_API_KEYS_JSON must contain valid scoped credential objects.") from error
        return cls(
            api_key=legacy_api_key,
            profile_salt=required["PAGA_PROFILE_SALT"],
            encryption_key=required["PAGA_ENCRYPTION_KEY"],
            api_credentials=credentials,
            database_path=os.getenv("PAGA_DATABASE_PATH", "paga_profiles.sqlite3"),
            decryption_keys=tuple(filter(None, os.getenv("PAGA_DECRYPTION_KEYS", "").split(","))),
            retention_days=int(os.getenv("PAGA_RETENTION_DAYS", "30")),
            max_request_bytes=int(os.getenv("PAGA_MAX_REQUEST_BYTES", "32768")),
            log_requests=_parse_bool_env("PAGA_LOG_REQUESTS", True),
            min_acoustic_confidence=float(os.getenv("PAGA_MIN_ACOUSTIC_CONFIDENCE", "0.72")),
            min_phoneme_confidence=float(os.getenv("PAGA_MIN_PHONEME_CONFIDENCE", "0.5")),
            max_low_confidence_phoneme_ratio=float(
                os.getenv("PAGA_MAX_LOW_CONFIDENCE_PHONEME_RATIO", "0.3")
            ),
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationRequest(StrictModel):
    target: str = Field(min_length=1, max_length=256)
    attempt: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=64)
    evaluation_id: str | None = Field(default=None, max_length=128)


class HostedEvaluationRequest(EvaluationRequest):
    acoustic_confidence_scores: list[Annotated[float, Field(ge=0.0, le=1.0)]] | None = Field(
        default=None,
        max_length=256,
    )
    comparison_mode: bool = False


class ProfileUpdateRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=256)
    pattern: str = Field(min_length=1, max_length=128)
    category: PatternCategory = PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN
    is_correct: bool = False
    response_time: float | None = Field(default=None, ge=0, le=3600)


class ProfileLookupRequest(StrictModel):
    user_id: str = Field(min_length=1, max_length=256)


class ReportEvaluationRequest(EvaluationRequest):
    cohort: str = Field(min_length=1, max_length=128)


class ReportRequest(StrictModel):
    evaluations: list[ReportEvaluationRequest] = Field(min_length=1, max_length=10_000)


def create_app(
    settings: ServiceSettings | None = None,
    *,
    policy_pack: PolicyPack | None = None,
) -> FastAPI:
    """Build the institutional API application with injected deployment settings."""

    settings = settings or ServiceSettings.from_env()
    if settings.log_requests:
        _configure_access_logger()
    store = EncryptedProfileStore(
        settings.database_path,
        settings.encryption_key,
        decryption_keys=settings.decryption_keys,
        retention_days=settings.retention_days,
    )
    profiles = LearnerProfileAdapter(
        pseudonymization_salt=settings.profile_salt,
        retention_days=settings.retention_days,
        production_mode=True,
    )
    metric = PhonemeAwareOverInterventionMetric(policy_pack=policy_pack)
    enterprise_metric = EnterprisePhonemeEvaluator(
        policy_pack=policy_pack,
        min_acoustic_confidence=settings.min_acoustic_confidence,
        min_phoneme_confidence=settings.min_phoneme_confidence,
        min_phoneme_ratio=1.0 - settings.max_low_confidence_phoneme_ratio,
    )
    evaluation_service = EvaluationService(metric)
    app = FastAPI(title="paga-eval", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(RequestBodyLimitMiddleware, max_request_bytes=settings.max_request_bytes)

    def persist_audit(audit_record: dict, credential: APIKeyCredential, request: Request) -> None:
        persist_audits((audit_record,), credential, request)

    def persist_audits(audit_records, credential: APIKeyCredential, request: Request) -> None:
        try:
            store.append_audits(
                ({**audit_record, "request_id": request.state.request_id} for audit_record in audit_records),
                tenant_id=credential.tenant_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        started = perf_counter()
        supplied_request_id = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied_request_id
            if supplied_request_id and len(supplied_request_id) <= 128
            and all(char.isalnum() or char in "._-" for char in supplied_request_id)
            else str(uuid4())
        )
        request.state.tenant_id = "unauthenticated"
        response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            if settings.log_requests:
                ACCESS_LOGGER.info(
                    json.dumps(
                        {
                            "duration_ms": round((perf_counter() - started) * 1000, 3),
                            "event": "http_request",
                            "method": request.method,
                            "path": request.url.path,
                            "request_id": request.state.request_id,
                            "status_code": response_status,
                            "tenant_id": request.state.tenant_id,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )

    def authenticate_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> APIKeyCredential:
        matched = None
        for credential in settings.credentials:
            if x_api_key and compare_digest(x_api_key, credential.key):
                matched = credential
        if matched is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
        request.state.tenant_id = matched.tenant_id
        return matched

    def authorize(permission: Permission):
        def require_permission(
            credential: APIKeyCredential = Depends(authenticate_api_key),
        ) -> APIKeyCredential:
            if permission not in credential.permissions:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient API-key scope.")
            return credential

        return require_permission

    def tenant_user_id(credential: APIKeyCredential, user_id: str) -> str:
        return f"{credential.tenant_id}:{user_id}"

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz() -> dict:
        store.readiness_check()
        return {"status": "ready"}

    @app.post("/v1/evaluations")
    def evaluate(
        payload: HostedEvaluationRequest,
        request: Request,
        credential: APIKeyCredential = Depends(authorize(Permission.EVALUATE)),
    ) -> dict:
        if payload.comparison_mode and payload.acoustic_confidence_scores is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="comparison_mode requires acoustic_confidence_scores.",
            )
        if payload.acoustic_confidence_scores is None:
            result = evaluation_service.evaluate_payload(payload.model_dump(exclude_none=True))
        else:
            result = enterprise_metric.evaluate_live_turn(
                target=payload.target,
                attempt=payload.attempt,
                agent_action=payload.action,
                acoustic_confidence_scores=payload.acoustic_confidence_scores,
                evaluation_id=payload.evaluation_id,
                comparison_mode=payload.comparison_mode,
            )
        if result.get("review_required"):
            review_queue = result.setdefault(
                "review_queue",
                {
                    "review_required": True,
                    "review_reason": "policy_uncertainty",
                    "confidence": result.get("acoustic_confidence_mean"),
                    "evaluation_id": result["audit_record"]["evaluation_id"],
                    "policy_id": result["audit_record"]["policy_id"],
                    "policy_version": result["audit_record"]["policy_version"],
                    "created_at": result["audit_record"]["evaluated_at"],
                },
            )
            result["audit_record"]["review_queue"] = review_queue
        persist_audit(result["audit_record"], credential, request)
        return result

    @app.post("/v1/reports")
    def report(
        payload: ReportRequest,
        request: Request,
        credential: APIKeyCredential = Depends(authorize(Permission.REPORT)),
    ) -> dict:
        evaluated = [
            (
                case.cohort,
                metric.evaluate(
                    case.target,
                    case.attempt,
                    case.action,
                    evaluation_id=case.evaluation_id,
                ),
            )
            for case in payload.evaluations
        ]
        persist_audits(
            (result.audit_record.to_dict() for _, result in evaluated if result.audit_record),
            credential,
            request,
        )
        return build_institutional_report(evaluated).to_dict()

    @app.post("/v1/profiles")
    def update_profile(
        payload: ProfileUpdateRequest,
        credential: APIKeyCredential = Depends(authorize(Permission.PROFILE_WRITE)),
    ) -> dict:
        scoped_user_id = tenant_user_id(credential, payload.user_id)
        profile_id = profiles.profile_id(scoped_user_id)
        if profiles.export_profile(scoped_user_id) is None:
            stored_profile = store.get(profile_id, tenant_id=credential.tenant_id)
            if stored_profile is not None:
                profiles.restore_profile(stored_profile)
        profile = profiles.update_profile(
            scoped_user_id,
            payload.pattern,
            is_correct=payload.is_correct,
            response_time=payload.response_time,
            category=payload.category,
        )
        store.put(
            profile["user_id"],
            profiles.export_profile(scoped_user_id) or profile,
            tenant_id=credential.tenant_id,
        )
        return profile

    @app.post("/v1/profiles/lookup")
    def get_profile(
        payload: ProfileLookupRequest,
        credential: APIKeyCredential = Depends(authorize(Permission.PROFILE_READ)),
    ) -> dict:
        profile_id = profiles.profile_id(tenant_user_id(credential, payload.user_id))
        profile = store.get(profile_id, tenant_id=credential.tenant_id)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
        return profile

    @app.post("/v1/profiles/delete")
    def delete_profile(
        payload: ProfileLookupRequest,
        credential: APIKeyCredential = Depends(authorize(Permission.PROFILE_WRITE)),
    ) -> dict:
        scoped_user_id = tenant_user_id(credential, payload.user_id)
        profile_id = profiles.profile_id(scoped_user_id)
        profiles.delete_profile(scoped_user_id)
        return {"deleted": store.delete(profile_id, tenant_id=credential.tenant_id)}

    @app.post("/v1/maintenance/prune")
    def prune_profiles(
        credential: APIKeyCredential = Depends(authorize(Permission.OPERATIONS)),
    ) -> dict:
        return {
            "memory_profiles_deleted": profiles.prune_expired_profiles(),
            "stored_profiles_deleted": store.prune_expired(tenant_id=credential.tenant_id),
            "stored_audits_deleted": store.prune_expired_audits(tenant_id=credential.tenant_id),
        }

    @app.get("/v1/operations/stats")
    def operation_stats(
        credential: APIKeyCredential = Depends(authorize(Permission.OPERATIONS)),
    ) -> dict:
        return {
            "stored_profiles": store.count(tenant_id=credential.tenant_id),
            "stored_audits": store.count_audits(tenant_id=credential.tenant_id),
            "stored_acoustic_bypasses": store.count_audits_matching(
                "event_type",
                "acoustic_bypass",
                tenant_id=credential.tenant_id,
            ),
            "stored_review_required": store.count_audits_matching(
                "review_required",
                True,
                tenant_id=credential.tenant_id,
            ),
        }

    return app
