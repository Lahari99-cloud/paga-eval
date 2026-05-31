"""Benchmark runner for policy-pack quality evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from paga.metrics import PhonemeAwareOverInterventionMetric, Verdict
from paga.reporting import InstitutionalReport, build_institutional_report


@dataclass(frozen=True)
class BenchmarkOutcome:
    cases: int
    expected_verdict_accuracy: float
    report: InstitutionalReport
    mismatches: tuple[dict, ...]


def load_benchmark(path: str | Path) -> list[dict]:
    """Load a JSON list of institution-reviewed benchmark cases."""

    with Path(path).open(encoding="utf-8") as benchmark_file:
        cases = json.load(benchmark_file)
    if not isinstance(cases, list):
        raise ValueError("Benchmark file must contain a JSON list.")
    return cases


def run_benchmark(
    cases: Iterable[Mapping[str, str]],
    *,
    metric: PhonemeAwareOverInterventionMetric | None = None,
) -> BenchmarkOutcome:
    """Evaluate labeled cases and produce cohort metrics plus mismatches."""

    metric = metric or PhonemeAwareOverInterventionMetric()
    evaluated, mismatches = [], []
    total = 0
    for case in cases:
        total += 1
        missing = sorted({"target", "attempt", "action", "expected_verdict"} - case.keys())
        if missing:
            raise ValueError(f"Benchmark case {total} is missing fields: {', '.join(missing)}")
        try:
            expected_verdict = Verdict(case["expected_verdict"])
        except ValueError as error:
            raise ValueError(f"Benchmark case {total} has an unsupported expected_verdict.") from error
        result = metric.evaluate(case["target"], case["attempt"], case["action"])
        evaluated.append((case.get("cohort", "all"), result))
        if result.verdict is not expected_verdict:
            mismatches.append(
                {
                    "case_id": case.get("case_id", f"case-{total}"),
                    "expected_verdict": case["expected_verdict"],
                    "actual_verdict": result.verdict.value,
                }
            )
    accuracy = (total - len(mismatches)) / total if total else 0.0
    return BenchmarkOutcome(
        cases=total,
        expected_verdict_accuracy=accuracy,
        report=build_institutional_report(evaluated),
        mismatches=tuple(mismatches),
    )
