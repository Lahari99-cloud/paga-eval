"""Example: produce privacy-safe cohort metrics and append-only audit records."""

from paga import (
    PhonemeAwareOverInterventionMetric,
    audit_records_to_jsonl,
    build_institutional_report,
)


def main() -> None:
    metric = PhonemeAwareOverInterventionMetric()
    evaluated = [
        ("grade-k", metric.evaluate("rabbit", "wabbit", "accept")),
        ("grade-k", metric.evaluate("think", "fink", "correct")),
        ("grade-1", metric.evaluate("cat", "bat", "accept")),
        ("grade-1", metric.evaluate("elephant", "table", "correct")),
    ]
    report = build_institutional_report(evaluated)
    print(report.to_json())
    print("\nAudit JSONL:")
    print(audit_records_to_jsonl(result for _, result in evaluated))


if __name__ == "__main__":
    main()
