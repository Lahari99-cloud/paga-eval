"""Transport-neutral institutional integration contract tests."""

import pytest

from paga import (
    EvaluationService,
    PhonemeAwareOverInterventionMetric,
    StandardsAlignment,
    to_edfi_assessment_result_payload,
    to_lti_ags_score_payload,
)


def test_service_facade_returns_json_serializable_contract():
    response = EvaluationService().evaluate_payload({
        "target": "rabbit",
        "attempt": "wabbit",
        "action": "accept",
        "evaluation_id": "api-eval",
    })
    assert response["verdict"] == "PASS"
    assert response["classification"] == "developmental_speech_pattern"
    assert response["audit_record"]["evaluation_id"] == "api-eval"


def test_service_facade_validates_required_fields():
    with pytest.raises(ValueError, match="attempt"):
        EvaluationService().evaluate_payload({"target": "rabbit", "action": "accept"})


def test_service_facade_rejects_non_string_contract_fields():
    with pytest.raises(ValueError, match="attempt"):
        EvaluationService().evaluate_payload({"target": "rabbit", "attempt": 123, "action": "accept"})


def test_lti_payload_routes_review_cases_to_manual_grading():
    result = PhonemeAwareOverInterventionMetric().evaluate("cat", "bat", "accept")
    payload = to_lti_ags_score_payload(result, lms_user_id="lms-subject")
    assert payload["gradingProgress"] == "PendingManual"
    assert payload["scoreMaximum"] == 1.0


def test_edfi_starter_mapping_includes_case_alignment_and_policy():
    result = PhonemeAwareOverInterventionMetric().evaluate("think", "fink", "accept")
    payload = to_edfi_assessment_result_payload(
        result,
        student_unique_id="district-student-id",
        assessment_identifier="oral-reading-check",
        namespace="uri://district.example/assessments",
        alignment=StandardsAlignment("case-item-guid", "case-framework-guid"),
    )
    extension = payload["_ext"]["pagaEval"]
    assert extension["caseAlignment"]["caseItemGUID"] == "case-item-guid"
    assert extension["policyVersion"] == "1.0.0"


def test_integration_mappers_reject_empty_identifiers():
    result = PhonemeAwareOverInterventionMetric().evaluate("rabbit", "wabbit", "accept")
    with pytest.raises(ValueError, match="lms_user_id"):
        to_lti_ags_score_payload(result, lms_user_id="")
    with pytest.raises(ValueError, match="student ID"):
        to_edfi_assessment_result_payload(
            result,
            student_unique_id="",
            assessment_identifier="oral-reading-check",
            namespace="uri://district.example/assessments",
        )
