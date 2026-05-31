"""Institution-facing aggregate reporting tests."""

import json

from paga import (
    PhonemeAwareOverInterventionMetric,
    audit_records_to_jsonl,
    build_institutional_report,
)


def test_report_aggregates_cohort_quality_rates_without_learner_ids():
    metric = PhonemeAwareOverInterventionMetric()
    report = build_institutional_report([
        ("grade-k", metric.evaluate("rabbit", "wabbit", "accept")),
        ("grade-k", metric.evaluate("rabbit", "wabbit", "correct")),
        ("grade-1", metric.evaluate("cat", "bat", "accept")),
    ])
    payload = report.to_dict()
    assert payload["total_evaluations"] == 3
    assert payload["policy_versions"] == ["1.0.0"]
    assert payload["cohorts"][0]["cohort"] == "grade-1"
    assert payload["cohorts"][0]["review_rate"] == 1.0
    assert payload["cohorts"][1]["over_intervention_rate"] == 0.5
    assert "learner" not in report.to_json()


def test_report_exports_csv_and_audit_jsonl():
    metric = PhonemeAwareOverInterventionMetric()
    result = metric.evaluate("think", "fink", "accept", evaluation_id="eval-export")
    report = build_institutional_report([("pilot-school", result)])
    assert "cohort,evaluations,pass_rate" in report.to_csv()
    records = [json.loads(line) for line in audit_records_to_jsonl([result]).splitlines()]
    assert records[0]["evaluation_id"] == "eval-export"
    assert records[0]["applied_rule_ids"] == ["th-fronting-unvoiced"]
