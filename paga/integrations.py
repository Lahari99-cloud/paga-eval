"""Transport-neutral integration contracts for institutional adapters.

These helpers produce structured payloads that can sit behind REST endpoints or
buyer-specific LMS and data-platform adapters. They do not claim certification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from paga.metrics import EvalResult, PhonemeAwareOverInterventionMetric


@dataclass(frozen=True)
class StandardsAlignment:
    """Reference to an institution-approved CASE competency or standard."""

    case_item_guid: str
    framework_guid: str | None = None

    def to_dict(self) -> dict[str, str]:
        if not self.case_item_guid.strip():
            raise ValueError("case_item_guid must not be empty.")
        payload = {"caseItemGUID": self.case_item_guid}
        if self.framework_guid:
            payload["caseFrameworkGUID"] = self.framework_guid
        return payload


class EvaluationService:
    """Small facade for web handlers, queues, and batch jobs."""

    def __init__(self, metric: PhonemeAwareOverInterventionMetric | None = None) -> None:
        self.metric = metric or PhonemeAwareOverInterventionMetric()

    def evaluate_payload(self, payload: Mapping[str, str]) -> dict:
        missing = sorted({"target", "attempt", "action"} - payload.keys())
        if missing:
            raise ValueError(f"Missing required evaluation fields: {', '.join(missing)}")
        invalid = sorted(field for field in ("target", "attempt", "action") if not isinstance(payload[field], str))
        if invalid:
            raise ValueError(f"Evaluation fields must be strings: {', '.join(invalid)}")
        result = self.metric.evaluate(
            target=payload["target"],
            attempt=payload["attempt"],
            agent_action=payload["action"],
            evaluation_id=payload.get("evaluation_id"),
        )
        return {
            "verdict": result.verdict.value,
            "score": result.score,
            "classification": result.classification.value,
            "review_required": result.review_required,
            "reason": result.reason,
            "raw_distance": result.raw_distance,
            "phonetic_distance": result.phonetic_distance,
            "applied_rule_ids": result.applied_rule_ids,
            "audit_record": result.audit_record.to_dict() if result.audit_record else None,
        }


def to_lti_ags_score_payload(
    result: EvalResult,
    *,
    lms_user_id: str,
    comment: str | None = None,
) -> dict:
    """Map an evaluation to an LTI Assignment and Grade Services score body.

    The caller owns authentication, endpoint selection, and LMS launch context.
    Human-review cases are marked ``PendingManual``.
    """

    if not lms_user_id.strip():
        raise ValueError("lms_user_id must not be empty.")
    return {
        "userId": lms_user_id,
        "scoreGiven": result.score,
        "scoreMaximum": 1.0,
        "comment": comment or result.reason,
        "activityProgress": "Completed",
        "gradingProgress": "PendingManual" if result.review_required else "FullyGraded",
    }


def to_edfi_assessment_result_payload(
    result: EvalResult,
    *,
    student_unique_id: str,
    assessment_identifier: str,
    namespace: str,
    alignment: StandardsAlignment | None = None,
) -> dict:
    """Build a starter Ed-Fi assessment-result mapping for adapter validation.

    District implementations must validate resource shape and descriptors against
    their deployed Ed-Fi Data Standard and API profile.
    """

    if not student_unique_id.strip() or not assessment_identifier.strip() or not namespace.strip():
        raise ValueError("Ed-Fi mapping requires student ID, assessment identifier, and namespace.")
    payload = {
        "studentReference": {"studentUniqueId": student_unique_id},
        "assessmentReference": {
            "assessmentIdentifier": assessment_identifier,
            "namespace": namespace,
        },
        "results": [
            {
                "resultDatatypeTypeDescriptor": "uri://paga-eval/resultDatatype#Decimal",
                "result": str(result.score),
            }
        ],
        "_ext": {
            "pagaEval": {
                "classification": result.classification.value,
                "verdict": result.verdict.value,
                "reviewRequired": result.review_required,
                "policyId": result.audit_record.policy_id if result.audit_record else None,
                "policyVersion": result.audit_record.policy_version if result.audit_record else None,
            }
        },
    }
    if alignment:
        payload["_ext"]["pagaEval"]["caseAlignment"] = alignment.to_dict()
    return payload
