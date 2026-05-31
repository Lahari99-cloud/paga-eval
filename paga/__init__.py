"""paga: Phoneme-Aware Grading for child-reading tutor agents."""

from paga.metrics import (
    AuditRecord,
    AuditTextMode,
    DEVELOPMENTAL_RULES,
    DEFAULT_RULES,
    DevelopmentalRule,
    EvalResult,
    EnterprisePhonemeEvaluator,
    LearnerProfileAdapter,
    PatternCategory,
    PhonemeAwareOverInterventionMetric,
    PolicyPack,
    Verdict,
)
from paga.reporting import (
    CohortMetrics,
    InstitutionalReport,
    audit_records_to_jsonl,
    build_institutional_report,
)
from paga.benchmark import BenchmarkOutcome, load_benchmark, run_benchmark
from paga.integrations import (
    EvaluationService,
    StandardsAlignment,
    to_edfi_assessment_result_payload,
    to_lti_ags_score_payload,
)

__all__ = [
    "PhonemeAwareOverInterventionMetric",
    "EnterprisePhonemeEvaluator",
    "EvalResult",
    "Verdict",
    "PatternCategory",
    "DEVELOPMENTAL_RULES",
    "DEFAULT_RULES",
    "DevelopmentalRule",
    "PolicyPack",
    "AuditRecord",
    "AuditTextMode",
    "LearnerProfileAdapter",
    "CohortMetrics",
    "InstitutionalReport",
    "build_institutional_report",
    "audit_records_to_jsonl",
    "BenchmarkOutcome",
    "load_benchmark",
    "run_benchmark",
    "EvaluationService",
    "StandardsAlignment",
    "to_lti_ags_score_payload",
    "to_edfi_assessment_result_payload",
]

__version__ = "0.4.0"
