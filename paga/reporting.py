"""Institution-facing aggregate reports for PAGA evaluation results."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from io import StringIO
from typing import Iterable, Mapping

from paga.metrics import EvalResult, PatternCategory, Verdict


@dataclass(frozen=True)
class CohortMetrics:
    cohort: str
    evaluations: int
    pass_rate: float
    over_intervention_rate: float
    under_intervention_rate: float
    review_rate: float


@dataclass(frozen=True)
class InstitutionalReport:
    """Aggregate operational quality metrics without exposing learner identifiers."""

    cohorts: tuple[CohortMetrics, ...]
    total_evaluations: int
    policy_ids: tuple[str, ...]
    policy_versions: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "total_evaluations": self.total_evaluations,
            "policy_ids": list(self.policy_ids),
            "policy_versions": list(self.policy_versions),
            "cohorts": [asdict(cohort) for cohort in self.cohorts],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_csv(self) -> str:
        output = StringIO()
        fields = list(CohortMetrics.__dataclass_fields__)
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(cohort) for cohort in self.cohorts)
        return output.getvalue()


def build_institutional_report(
    evaluations: Iterable[tuple[str, EvalResult]],
) -> InstitutionalReport:
    """Build cohort metrics from ``(cohort_label, result)`` pairs.

    Cohort labels should be broad, institution-approved reporting dimensions such
    as grade band or deployment site. Do not use this helper to encode sensitive
    learner-level attributes without an approved governance process.
    """

    grouped: dict[str, list[EvalResult]] = {}
    policy_ids, policy_versions = set(), set()
    for cohort, result in evaluations:
        grouped.setdefault(cohort, []).append(result)
        if result.audit_record:
            policy_ids.add(result.audit_record.policy_id)
            policy_versions.add(result.audit_record.policy_version)

    metrics = []
    for cohort, results in sorted(grouped.items()):
        total = len(results)
        metrics.append(
            CohortMetrics(
                cohort=cohort,
                evaluations=total,
                pass_rate=_rate(results, Verdict.PASS),
                over_intervention_rate=_rate(results, Verdict.FAIL_OVER_INTERVENTION),
                under_intervention_rate=_rate(results, Verdict.UNDER_INTERVENTION),
                review_rate=_rate(results, Verdict.ESCALATE_REVIEW),
            )
        )
    return InstitutionalReport(
        cohorts=tuple(metrics),
        total_evaluations=sum(metric.evaluations for metric in metrics),
        policy_ids=tuple(sorted(policy_ids)),
        policy_versions=tuple(sorted(policy_versions)),
    )


def audit_records_to_jsonl(results: Iterable[EvalResult]) -> str:
    """Serialize audit records for append-only logs or data-warehouse ingestion."""

    records = [result.audit_record.to_dict() for result in results if result.audit_record]
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)


def _rate(results: list[EvalResult], verdict: Verdict) -> float:
    return sum(result.verdict is verdict for result in results) / len(results) if results else 0.0
