"""Starter benchmark runner tests."""

from pathlib import Path

import pytest

from paga import load_benchmark, run_benchmark


def test_starter_benchmark_matches_default_policy():
    cases = load_benchmark(Path("benchmarks") / "starter_en_us.json")
    outcome = run_benchmark(cases)
    assert outcome.cases == 5
    assert outcome.expected_verdict_accuracy == 1.0
    assert outcome.mismatches == ()
    assert outcome.report.total_evaluations == 5


def test_benchmark_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="expected_verdict"):
        run_benchmark([{"target": "cat", "attempt": "cat", "action": "accept"}])


def test_benchmark_rejects_unknown_expected_verdict():
    with pytest.raises(ValueError, match="unsupported"):
        run_benchmark([
            {
                "target": "cat",
                "attempt": "cat",
                "action": "accept",
                "expected_verdict": "MAYBE",
            }
        ])
