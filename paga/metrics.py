"""Auditable, developmentally-aware grading for child-reading tutor agents.

The metric is deliberately text based and deterministic. It is an evaluation
guardrail for tutor decisions, not a diagnostic tool and not a substitute for a
speech-language pathologist.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hmac import new as hmac_new
from hashlib import sha256
from itertools import combinations
from typing import Callable, Iterable, Mapping, Optional
from uuid import uuid4

import Levenshtein

INTERVENING_ACTIONS = frozenset({"intervene", "hint", "correct", "interrupt", "reprompt"})
ACCEPTING_ACTIONS = frozenset({"accept", "continue", "praise", "advance", "encourage", "none"})


class PatternCategory(str, Enum):
    """Interpretation of a child's attempt. These are not clinical diagnoses."""

    CLEAN_READING = "clean_reading"
    DEVELOPMENTAL_SPEECH_PATTERN = "developmental_speech_pattern"
    DECODING_ERROR = "decoding_error"
    UNCERTAIN_REQUIRES_REVIEW = "uncertain_requires_review"


class Verdict(str, Enum):
    """Outcome of grading a single agent decision."""

    PASS = "PASS"
    FAIL_OVER_INTERVENTION = "FAIL_OVER_INTERVENTION"
    UNDER_INTERVENTION = "UNDER_INTERVENTION"
    ESCALATE_REVIEW = "ESCALATE_REVIEW"


class AuditTextMode(str, Enum):
    """How transcript text is stored in durable audit records."""

    HASHED = "hashed"
    PLAINTEXT = "plaintext"
    OMITTED = "omitted"


@dataclass(frozen=True)
class DevelopmentalRule:
    """Versionable policy metadata for one grapheme-level approximation."""

    rule_id: str
    source: str
    replacement: str
    process: str
    category: PatternCategory = PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN
    locale: str = "en-US"
    age_range: str = "clinician_review_required"
    rationale: str = ""
    intervention_guidance: str = "Do not correct automatically; follow educator or SLP policy."
    evidence_reference: str = "Institution-configured policy pack; validate with an SLP before deployment."

    def __post_init__(self) -> None:
        if not self.rule_id.strip() or not self.source or not self.replacement or not self.process.strip():
            raise ValueError("Rules require a non-empty ID, source, replacement, and process.")
        if self.source == self.replacement:
            raise ValueError("Rule source and replacement must differ.")

    def as_pair(self) -> tuple[str, str]:
        return self.source, self.replacement

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["category"] = self.category.value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> DevelopmentalRule:
        data = dict(payload)
        data["category"] = PatternCategory(data.get("category", PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN))
        return cls(**data)


DEFAULT_RULES: tuple[DevelopmentalRule, ...] = (
    DevelopmentalRule("gliding-r-w", "r", "w", "gliding", rationale="rabbit -> wabbit"),
    DevelopmentalRule("gliding-l-w", "l", "w", "gliding", rationale="lion -> wion"),
    DevelopmentalRule("gliding-l-y", "l", "y", "gliding", rationale="yellow -> yeyow"),
    DevelopmentalRule("th-fronting-unvoiced", "th", "f", "th_fronting", rationale="think -> fink"),
    DevelopmentalRule("th-stopping", "th", "d", "th_stopping", rationale="this -> dis"),
    DevelopmentalRule("th-fronting-voiced", "th", "v", "th_fronting", rationale="brother -> bruvver"),
    DevelopmentalRule("interdental-lisp", "s", "th", "interdental_lisp", rationale="sun -> thun"),
    DevelopmentalRule("stopping-ch-t", "ch", "t", "stopping", rationale="chair -> tair"),
    DevelopmentalRule("stopping-v-b", "v", "b", "stopping", rationale="van -> ban"),
)

# Backwards-compatible public constant for callers that inject tuple pairs.
DEVELOPMENTAL_RULES: tuple[tuple[str, str], ...] = tuple(rule.as_pair() for rule in DEFAULT_RULES)


@dataclass(frozen=True)
class PolicyPack:
    """A versioned institutional policy boundary for evaluator behavior."""

    policy_id: str = "paga-default-en-us"
    version: str = "1.0.0"
    locale: str = "en-US"
    rules: tuple[DevelopmentalRule, ...] = DEFAULT_RULES
    phonetic_tolerance: int = 0
    decoding_error_threshold: int = 2
    review_ambiguous_attempts: bool = True
    audit_text_mode: AuditTextMode = AuditTextMode.OMITTED

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_text_mode", AuditTextMode(self.audit_text_mode))
        if not self.policy_id.strip() or not self.version.strip() or not self.locale.strip():
            raise ValueError("Policy packs require a non-empty ID, version, and locale.")
        if self.phonetic_tolerance < 0 or self.decoding_error_threshold < 1:
            raise ValueError("Policy thresholds must be non-negative and decoding threshold must be >= 1.")
        if len(self.rules) > 16:
            raise ValueError("Policy packs support at most 16 rules to bound powerset evaluation cost.")
        if any(rule.locale != self.locale for rule in self.rules):
            raise ValueError("All rules must match the policy pack locale.")
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Policy pack rule IDs must be unique.")

    def to_dict(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "locale": self.locale,
            "rules": [rule.to_dict() for rule in self.rules],
            "phonetic_tolerance": self.phonetic_tolerance,
            "decoding_error_threshold": self.decoding_error_threshold,
            "review_ambiguous_attempts": self.review_ambiguous_attempts,
            "audit_text_mode": self.audit_text_mode.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PolicyPack:
        data = dict(payload)
        data["rules"] = tuple(DevelopmentalRule.from_dict(rule) for rule in data.get("rules", ()))
        return cls(**data)


@dataclass(frozen=True)
class AuditRecord:
    """Minimal audit payload suitable for structured logs or institutional export."""

    evaluation_id: str
    evaluated_at: str
    policy_id: str
    policy_version: str
    target: str
    attempt: str
    agent_action: str
    classification: PatternCategory
    verdict: Verdict
    applied_rule_ids: tuple[str, ...]
    raw_distance: int
    phonetic_distance: int
    review_required: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalResult:
    """Structured grade for one target, attempt, and tutor-action triple."""

    verdict: Verdict
    score: float
    raw_distance: int
    phonetic_distance: int
    is_valid_phonetic_attempt: bool
    reason: str
    applied_rules: list[tuple[str, str]] = field(default_factory=list)
    classification: PatternCategory = PatternCategory.UNCERTAIN_REQUIRES_REVIEW
    review_required: bool = False
    applied_rule_ids: list[str] = field(default_factory=list)
    audit_record: AuditRecord | None = None
    # Acoustic confidence fields for ASR integration
    acoustic_confidence_mean: Optional[float] = None
    acoustic_confidence_passed: Optional[bool] = None

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS


def _normalize(text: str) -> str:
    return "".join(c for c in text.lower().strip() if c.isalpha())


def _coerce_rules(rules: Iterable[DevelopmentalRule | tuple[str, str]]) -> tuple[DevelopmentalRule, ...]:
    coerced = []
    for index, rule in enumerate(rules):
        if isinstance(rule, DevelopmentalRule):
            coerced.append(rule)
        else:
            source, replacement = rule
            coerced.append(
                DevelopmentalRule(
                    rule_id=f"custom-{index}-{source}-{replacement}",
                    source=source,
                    replacement=replacement,
                    process="custom",
                )
            )
    return tuple(coerced)


class LearnerProfileAdapter:
    """Privacy-aware session profile for instructional decisions.

    Developmental speech patterns remain visible to educators but do not trigger
    focused reading lessons by default. Decoding errors can trigger lessons after
    the configured persistence threshold.
    """

    def __init__(
        self,
        persistence_threshold: int = 3,
        *,
        pseudonymize_user_ids: bool = True,
        pseudonymization_salt: str = "paga-local-profile",
        intervention_categories: Iterable[PatternCategory] = (PatternCategory.DECODING_ERROR,),
        retention_days: int | None = None,
        production_mode: bool = False,
        clock=None,
    ) -> None:
        if persistence_threshold < 1:
            raise ValueError("persistence_threshold must be >= 1.")
        if retention_days is not None and retention_days < 1:
            raise ValueError("retention_days must be >= 1 when configured.")
        if production_mode and pseudonymize_user_ids and pseudonymization_salt == "paga-local-profile":
            raise ValueError("production_mode requires a deployment-specific pseudonymization_salt.")
        self.persistence_threshold = persistence_threshold
        self.pseudonymize_user_ids = pseudonymize_user_ids
        self.pseudonymization_salt = pseudonymization_salt
        self.intervention_categories = frozenset(intervention_categories)
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.pattern_history: dict[str, dict[str, dict[str, int]]] = {}
        self.success_history: dict[str, dict[str, int]] = {}
        self.attempt_timestamps: dict[str, list[float]] = {}
        self.total_attempts: dict[str, int] = {}
        self.updated_at: dict[str, datetime] = {}

    def _profile_id(self, user_id: str) -> str:
        if not self.pseudonymize_user_ids:
            return user_id
        digest = hmac_new(self.pseudonymization_salt.encode(), user_id.encode(), sha256).hexdigest()
        return f"learner_{digest[:16]}"

    def profile_id(self, user_id: str) -> str:
        """Return the stable pseudonymous identifier for a raw learner ID."""

        if not user_id.strip():
            raise ValueError("user_id must not be empty.")
        return self._profile_id(user_id)

    def update_profile(
        self,
        user_id: str,
        phonetic_error_type: str,
        is_correct: bool = False,
        response_time: float | None = None,
        *,
        category: PatternCategory | str = PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN,
    ) -> dict:
        if not user_id.strip():
            raise ValueError("user_id must not be empty.")
        if response_time is not None and response_time < 0:
            raise ValueError("response_time must be non-negative.")
        self.prune_expired_profiles()
        profile_id = self._profile_id(user_id)
        category = PatternCategory(category)
        self.pattern_history.setdefault(profile_id, {})
        self.success_history.setdefault(profile_id, {})
        self.attempt_timestamps.setdefault(profile_id, [])
        self.total_attempts[profile_id] = self.total_attempts.get(profile_id, 0) + 1
        self.updated_at[profile_id] = self.clock()

        if response_time is not None:
            self.attempt_timestamps[profile_id].append(response_time)
            self.attempt_timestamps[profile_id] = self.attempt_timestamps[profile_id][-10:]

        if phonetic_error_type != "none" and not is_correct:
            category_counts = self.pattern_history[profile_id].setdefault(category.value, {})
            category_counts[phonetic_error_type] = category_counts.get(phonetic_error_type, 0) + 1
        elif is_correct:
            key = phonetic_error_type or "correct_attempt"
            self.success_history[profile_id][key] = self.success_history[profile_id].get(key, 0) + 1

        systemic_gaps = []
        for intervention_category in self.intervention_categories:
            systemic_gaps.extend(
                pattern
                for pattern, count in self.pattern_history[profile_id].get(intervention_category.value, {}).items()
                if count >= self.persistence_threshold
            )
        strengths = [
            pattern
            for pattern, count in self.success_history[profile_id].items()
            if count >= max(2, self.persistence_threshold - 1)
        ]
        recent_times = self.attempt_timestamps[profile_id]
        pace_trend = (
            "improving" if len(recent_times) >= 3 and recent_times[-1] < recent_times[-3]
            else "declining" if len(recent_times) >= 3 and recent_times[-1] > recent_times[-3]
            else "stable" if recent_times else "unknown"
        )
        engagement_score = min(self.total_attempts[profile_id] / 10.0, 1.0)
        return {
            "user_id": profile_id,
            "session_pattern_counts": deepcopy(self.pattern_history[profile_id]),
            "session_error_counts": {
                pattern: count
                for counts in self.pattern_history[profile_id].values()
                for pattern, count in counts.items()
            },
            "session_success_counts": deepcopy(self.success_history[profile_id]),
            "systemic_gaps_identified": systemic_gaps,
            "consistent_strengths_identified": strengths,
            "requires_focused_lesson": bool(systemic_gaps),
            "pace_metrics": {
                "average_response_time": sum(recent_times) / len(recent_times) if recent_times else None,
                "pace_trend": pace_trend,
                "total_attempts": self.total_attempts[profile_id],
            },
            "engagement_indicators": {
                "engagement_score": engagement_score,
                "recent_attempt_count": len(recent_times),
                "consistency": "high" if engagement_score > 0.7 else "medium" if engagement_score > 0.3 else "low",
            },
        }

    def export_profile(self, user_id: str) -> dict | None:
        """Return the latest privacy-safe profile snapshot for a learner."""

        self.prune_expired_profiles()
        profile_id = self._profile_id(user_id)
        if profile_id not in self.pattern_history:
            return None
        recent_times = self.attempt_timestamps[profile_id]
        return {
            "user_id": profile_id,
            "session_pattern_counts": deepcopy(self.pattern_history[profile_id]),
            "session_success_counts": deepcopy(self.success_history[profile_id]),
            "recent_response_times": list(recent_times),
            "total_attempts": self.total_attempts[profile_id],
            "updated_at": self.updated_at[profile_id].isoformat(),
        }

    def delete_profile(self, user_id: str) -> bool:
        """Delete an in-memory learner profile and report whether one existed."""

        profile_id = self._profile_id(user_id)
        existed = profile_id in self.pattern_history
        self.pattern_history.pop(profile_id, None)
        self.success_history.pop(profile_id, None)
        self.attempt_timestamps.pop(profile_id, None)
        self.total_attempts.pop(profile_id, None)
        self.updated_at.pop(profile_id, None)
        return existed

    def restore_profile(self, profile: Mapping[str, object]) -> None:
        """Hydrate a previously exported privacy-safe profile snapshot."""

        profile_id = str(profile.get("user_id", ""))
        if not profile_id.startswith("learner_") and self.pseudonymize_user_ids:
            raise ValueError("Restored profile must use a pseudonymous learner ID.")
        updated_at = datetime.fromisoformat(str(profile["updated_at"]))
        self.pattern_history[profile_id] = deepcopy(profile.get("session_pattern_counts", {}))
        self.success_history[profile_id] = deepcopy(profile.get("session_success_counts", {}))
        self.attempt_timestamps[profile_id] = list(profile.get("recent_response_times", []))
        self.total_attempts[profile_id] = int(profile.get("total_attempts", 0))
        self.updated_at[profile_id] = updated_at

    def prune_expired_profiles(self) -> int:
        """Delete profiles older than the configured retention period."""

        if self.retention_days is None:
            return 0
        cutoff = self.clock() - timedelta(days=self.retention_days)
        expired = [profile_id for profile_id, updated_at in self.updated_at.items() if updated_at < cutoff]
        for profile_id in expired:
            self.pattern_history.pop(profile_id, None)
            self.success_history.pop(profile_id, None)
            self.attempt_timestamps.pop(profile_id, None)
            self.total_attempts.pop(profile_id, None)
            self.updated_at.pop(profile_id, None)
        return len(expired)


class PhonemeAwareOverInterventionMetric:
    """Grade tutor decisions against a versioned, auditable institutional policy."""

    def __init__(
        self,
        phonetic_tolerance: int | None = None,
        error_threshold: int | None = None,
        rules: Iterable[DevelopmentalRule | tuple[str, str]] | None = None,
        *,
        policy_pack: PolicyPack | None = None,
    ) -> None:
        base = policy_pack or PolicyPack()
        effective_rules = _coerce_rules(rules) if rules is not None else base.rules
        self.policy_pack = PolicyPack(
            policy_id=base.policy_id,
            version=base.version,
            locale=base.locale,
            rules=effective_rules,
            phonetic_tolerance=base.phonetic_tolerance if phonetic_tolerance is None else phonetic_tolerance,
            decoding_error_threshold=base.decoding_error_threshold if error_threshold is None else error_threshold,
            review_ambiguous_attempts=base.review_ambiguous_attempts,
            audit_text_mode=base.audit_text_mode,
        )
        self.phonetic_tolerance = self.policy_pack.phonetic_tolerance
        self.error_threshold = self.policy_pack.decoding_error_threshold
        self.rules = tuple(rule.as_pair() for rule in self.policy_pack.rules)

    def _classify_attempt(
        self, target: str, attempt: str
    ) -> tuple[int, int, PatternCategory, list[DevelopmentalRule]]:
        raw = Levenshtein.distance(attempt, target)
        best_dist, best_combo = raw, []
        for size in range(1, len(self.policy_pack.rules) + 1):
            for combo in combinations(self.policy_pack.rules, size):
                variant = target
                for rule in combo:
                    variant = variant.replace(rule.source, rule.replacement)
                distance = Levenshtein.distance(attempt, variant)
                if distance < best_dist:
                    best_dist, best_combo = distance, list(combo)
        if raw == 0:
            return raw, best_dist, PatternCategory.CLEAN_READING, []
        if best_dist <= self.phonetic_tolerance and best_dist < raw:
            return raw, best_dist, PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN, best_combo
        if raw >= self.error_threshold:
            return raw, best_dist, PatternCategory.DECODING_ERROR, best_combo
        if not self.policy_pack.review_ambiguous_attempts:
            return raw, best_dist, PatternCategory.DECODING_ERROR, best_combo
        return raw, best_dist, PatternCategory.UNCERTAIN_REQUIRES_REVIEW, best_combo

    def evaluate(
        self,
        target: str,
        attempt: str,
        agent_action: str,
        *,
        evaluation_id: str | None = None,
    ) -> EvalResult:
        target_n, attempt_n = _normalize(target), _normalize(attempt)
        action = agent_action.lower().strip()
        raw, phon, classification, combo = self._classify_attempt(target_n, attempt_n)
        valid = classification in {PatternCategory.CLEAN_READING, PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN}
        known_action = action in INTERVENING_ACTIONS | ACCEPTING_ACTIONS
        intervened = action in INTERVENING_ACTIONS

        if not target_n or not attempt_n or not known_action:
            verdict, score, review = Verdict.ESCALATE_REVIEW, 0.5, True
            reason = "Evaluation requires human review: target, attempt, or agent action is missing or unsupported."
        elif classification is PatternCategory.UNCERTAIN_REQUIRES_REVIEW:
            verdict, score, review = Verdict.ESCALATE_REVIEW, 0.5, True
            reason = f"Unexplained near-match ('{attempt_n}' vs '{target_n}') requires educator review."
        elif valid and intervened:
            verdict, score, review = Verdict.FAIL_OVER_INTERVENTION, 0.0, False
            reason = f"Agent took '{action}' on a {classification.value} ('{attempt_n}' for '{target_n}')."
        elif valid:
            verdict, score, review = Verdict.PASS, 1.0, False
            reason = f"Agent correctly let the child continue after '{attempt_n}'."
        elif not intervened:
            verdict, score, review = Verdict.UNDER_INTERVENTION, 0.5, False
            reason = f"Likely decoding error ('{attempt_n}' vs '{target_n}') went unaddressed."
        else:
            verdict, score, review = Verdict.PASS, 1.0, False
            reason = f"Agent appropriately intervened on a likely decoding error for '{target_n}'."

        audit = AuditRecord(
            evaluation_id=evaluation_id or str(uuid4()),
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            policy_id=self.policy_pack.policy_id,
            policy_version=self.policy_pack.version,
            target=_audit_text(target_n, self.policy_pack.audit_text_mode),
            attempt=_audit_text(attempt_n, self.policy_pack.audit_text_mode),
            agent_action=action,
            classification=classification,
            verdict=verdict,
            applied_rule_ids=tuple(rule.rule_id for rule in combo),
            raw_distance=raw,
            phonetic_distance=phon,
            review_required=review,
        )
        return EvalResult(
            verdict=verdict,
            score=score,
            raw_distance=raw,
            phonetic_distance=phon,
            is_valid_phonetic_attempt=valid,
            reason=reason,
            applied_rules=[rule.as_pair() for rule in combo],
            classification=classification,
            review_required=review,
            applied_rule_ids=list(audit.applied_rule_ids),
            audit_record=audit,
        )

    def score_batch(self, cases: Iterable[Mapping[str, str]]) -> float:
        results = [self.evaluate(c["target"], c["attempt"], c["action"]) for c in cases]
        return sum(result.score for result in results) / len(results) if results else 0.0


def _audit_text(text: str, mode: AuditTextMode) -> str:
    if mode is AuditTextMode.PLAINTEXT:
        return text
    if mode is AuditTextMode.OMITTED:
        return ""
    return f"sha256:{sha256(text.encode()).hexdigest()}"


class EnterprisePhonemeEvaluator:
    """
    Institution-ready evaluation engine. Features an Acoustic Gate
    to protect audit trails from child ASR hallucination and classroom noise.
    """

    def __init__(
        self,
        policy_pack: PolicyPack | None = None,
        min_acoustic_confidence: float = 0.72,
        min_phoneme_confidence: float = 0.5,
        min_phoneme_ratio: float = 0.7,
        phonetic_tolerance: int | None = None,
        error_threshold: int | None = None,
        rules: Iterable[DevelopmentalRule | tuple[str, str]] | None = None,
        on_acoustic_bypass: Optional[Callable[[dict], None]] = None,
    ):
        """
        Initialize the enterprise evaluator with acoustic gating.

        Args:
            policy_pack: Optional policy pack to use. If None, uses default.
            min_acoustic_confidence: Minimum mean acoustic confidence to proceed (0.0-1.0)
            min_phoneme_confidence: Minimum confidence for individual phonemes (0.0-1.0)
            min_phoneme_ratio: Minimum ratio of phonemes exceeding min_phoneme_confidence (0.0-1.0)
            phonetic_tolerance: Override for phonetic tolerance from policy pack
            error_threshold: Override for error threshold from policy pack
            rules: Optional rules to use instead of policy pack rules
            on_acoustic_bypass: Optional callback for acoustic bypass events (for observability/metrics)
        """
        base = policy_pack or PolicyPack()
        effective_rules = _coerce_rules(rules) if rules is not None else base.rules
        self.policy_pack = PolicyPack(
            policy_id=base.policy_id,
            version=base.version,
            locale=base.locale,
            rules=effective_rules,
            phonetic_tolerance=base.phonetic_tolerance if phonetic_tolerance is None else phonetic_tolerance,
            decoding_error_threshold=base.decoding_error_threshold if error_threshold is None else error_threshold,
            review_ambiguous_attempts=base.review_ambiguous_attempts,
            audit_text_mode=base.audit_text_mode,
        )
        self.min_acoustic_confidence = min_acoustic_confidence
        self.min_phoneme_confidence = min_phoneme_confidence
        self.min_phoneme_ratio = min_phoneme_ratio
        self.on_acoustic_bypass = on_acoustic_bypass
        # Delegate to the core metric for actual classification logic
        self._core_metric = PhonemeAwareOverInterventionMetric(
            phonetic_tolerance=self.policy_pack.phonetic_tolerance,
            error_threshold=self.policy_pack.decoding_error_threshold,
            policy_pack=self.policy_pack
        )

    def evaluate_live_turn(
        self,
        target: str,
        attempt: str,
        agent_action: str,
        acoustic_confidence_scores: list[float],
        *,
        evaluation_id: str | None = None,
        comparison_mode: bool = False,
    ) -> dict:
        """
        Processes acoustic data trails. If global or local ASR signals fall
        below the safety threshold, bypasses heuristics to prevent false audit logs.

        Implements multi-level acoustic validation:
        1. Mean confidence threshold (overall signal quality)
        2. Per-phoneme confidence threshold (individual unit reliability)
        3. Phoneme ratio threshold (consistency across the utterance)

        Args:
            target: Target word/phrase
            attempt: ASR-transcribed attempt
            agent_action: What the tutor agent did
            acoustic_confidence_scores: Per-character/phoneme confidence from ASR (wav2vec, etc)
            evaluation_id: Optional evaluation ID

        Returns:
            Dictionary with evaluation results
        """
        if any(score < 0.0 or score > 1.0 for score in acoustic_confidence_scores):
            raise ValueError("acoustic confidence scores must be between 0.0 and 1.0")

        evaluation_id = evaluation_id or str(uuid4())
        evaluated_at = datetime.now(timezone.utc).isoformat()

        # Handle empty confidence scores
        if not acoustic_confidence_scores:
            mean_confidence = 0.0
            phoneme_pass_ratio = 0.0
        else:
            mean_confidence = sum(acoustic_confidence_scores) / len(acoustic_confidence_scores)
            # Calculate ratio of phonemes exceeding individual confidence threshold
            phonemes_above_threshold = sum(1 for score in acoustic_confidence_scores if score >= self.min_phoneme_confidence)
            phoneme_pass_ratio = phonemes_above_threshold / len(acoustic_confidence_scores)

        low_confidence_phoneme_ratio = 1.0 - phoneme_pass_ratio

        # Multi-level acoustic validation
        mean_confidence_ok = mean_confidence >= self.min_acoustic_confidence
        phoneme_ratio_ok = phoneme_pass_ratio >= self.min_phoneme_ratio

        # CRITICAL ADAPTATION: If the signal fails acoustic validation, halt deterministic classification
        # and trigger an immediate ESCALATE_REVIEW state to avoid scoring penalties.
        if not (mean_confidence_ok and phoneme_ratio_ok):
            review_queue = {
                "review_required": True,
                "review_reason": "acoustic_uncertainty",
                "confidence": mean_confidence,
                "evaluation_id": evaluation_id,
                "policy_id": self.policy_pack.policy_id,
                "policy_version": self.policy_pack.version,
                "created_at": evaluated_at,
            }
            bypass_event = {
                "verdict": Verdict.ESCALATE_REVIEW.value,
                "classification": PatternCategory.UNCERTAIN_REQUIRES_REVIEW.value,
                "reason": f"Acoustic validation failed: mean_confidence={mean_confidence:.2f} (threshold={self.min_acoustic_confidence}), phoneme_ratio={phoneme_pass_ratio:.2f} (threshold={self.min_phoneme_ratio}). Signal contaminated by noise, audio cutoff, or unstable recognition.",
                "review_required": True,
                "review_queue": review_queue,
                "acoustic_confidence_mean": mean_confidence,
                "acoustic_confidence_passed": False,
                "audit_record": {
                    "evaluation_id": evaluation_id,
                    "evaluated_at": evaluated_at,
                    "event_type": "acoustic_bypass",
                    "reason": "low_asr_confidence",
                    "policy_id": self.policy_pack.policy_id,
                    "policy_version": self.policy_pack.version,
                    "target": "",
                    "attempt": "",
                    "agent_action": agent_action.strip().lower(),
                    "classification": PatternCategory.UNCERTAIN_REQUIRES_REVIEW.value,
                    "verdict": Verdict.ESCALATE_REVIEW.value,
                    "applied_rule_ids": [],
                    "raw_distance": None,
                    "phonetic_distance": None,
                    "review_required": True,
                    "action_taken": "BYPASS_METRIC",
                    "requires_human_verification": True,
                    "acoustic_confidence_mean": mean_confidence,
                    "acoustic_confidence_threshold": self.min_acoustic_confidence,
                    "phoneme_confidence_threshold": self.min_phoneme_confidence,
                    "phoneme_pass_ratio": phoneme_pass_ratio,
                    "phoneme_ratio_threshold": self.min_phoneme_ratio,
                    "low_confidence_phoneme_ratio": low_confidence_phoneme_ratio,
                    "review_queue": review_queue,
                },
                "phoneme_pass_ratio": phoneme_pass_ratio,
                "low_confidence_phoneme_ratio": low_confidence_phoneme_ratio,
            }
            if comparison_mode:
                naive_result = self._core_metric.evaluate(
                    target=target,
                    attempt=attempt,
                    agent_action=agent_action,
                    evaluation_id=evaluation_id,
                )
                bypass_event["comparison"] = self._comparison_payload(
                    naive_result=naive_result,
                    governed_verdict=Verdict.ESCALATE_REVIEW.value,
                    governed_classification=PatternCategory.UNCERTAIN_REQUIRES_REVIEW.value,
                    reason="Low ASR confidence prevented automated judgment.",
                )

            # Invoke callback for observability/metrics if provided
            if self.on_acoustic_bypass is not None:
                try:
                    self.on_acoustic_bypass(bypass_event)
                except Exception:
                    # Don't let callback failures interfere with evaluation
                    pass

            return bypass_event

        # Otherwise, safely drop down into your core Levenshtein / Rule Registry pipeline
        result = self._core_metric.evaluate(
            target=target,
            attempt=attempt,
            agent_action=agent_action,
            evaluation_id=evaluation_id
        )

        # Enhance the result with acoustic information by creating a new EvalResult
        enhanced_result = EvalResult(
            verdict=result.verdict,
            score=result.score,
            raw_distance=result.raw_distance,
            phonetic_distance=result.phonetic_distance,
            is_valid_phonetic_attempt=result.is_valid_phonetic_attempt,
            reason=result.reason,
            applied_rules=result.applied_rules,
            classification=result.classification,
            review_required=result.review_required,
            applied_rule_ids=result.applied_rule_ids,
            audit_record=result.audit_record,
            acoustic_confidence_mean=mean_confidence,
            acoustic_confidence_passed=True
        )

        # Return as dict for backward compatibility with existing usage
        payload = {
            "verdict": enhanced_result.verdict.value,
            "score": enhanced_result.score,
            "classification": enhanced_result.classification.value,
            "review_required": enhanced_result.review_required,
            "reason": enhanced_result.reason,
            "raw_distance": enhanced_result.raw_distance,
            "phonetic_distance": enhanced_result.phonetic_distance,
            "applied_rule_ids": enhanced_result.applied_rule_ids,
            "audit_record": enhanced_result.audit_record.to_dict() if enhanced_result.audit_record else None,
            "acoustic_confidence_mean": enhanced_result.acoustic_confidence_mean,
            "acoustic_confidence_passed": enhanced_result.acoustic_confidence_passed,
            "phoneme_pass_ratio": phoneme_pass_ratio,
            "low_confidence_phoneme_ratio": low_confidence_phoneme_ratio,
        }
        payload["audit_record"].update(
            {
                "event_type": "policy_evaluation",
                "acoustic_confidence_mean": mean_confidence,
                "acoustic_confidence_threshold": self.min_acoustic_confidence,
                "phoneme_confidence_threshold": self.min_phoneme_confidence,
                "phoneme_pass_ratio": phoneme_pass_ratio,
                "phoneme_ratio_threshold": self.min_phoneme_ratio,
                "low_confidence_phoneme_ratio": low_confidence_phoneme_ratio,
            }
        )
        if comparison_mode:
            payload["comparison"] = self._comparison_payload(
                naive_result=result,
                governed_verdict=result.verdict.value,
                governed_classification=result.classification.value,
                reason="Acoustic confidence allowed automated policy evaluation.",
            )
        return payload

    @staticmethod
    def _comparison_payload(
        *,
        naive_result: EvalResult,
        governed_verdict: str,
        governed_classification: str,
        reason: str,
    ) -> dict[str, object]:
        return {
            "naive_evaluator": {
                "verdict": naive_result.verdict.value,
                "classification": naive_result.classification.value,
            },
            "paga_eval": {
                "verdict": governed_verdict,
                "classification": governed_classification,
            },
            "reason": reason,
        }

    # Delegate other useful methods to the core metric
    def score_batch(self, cases: Iterable[Mapping[str, str]]) -> float:
        """Score a batch of cases using the core metric (acoustic gate not applied in batch mode)."""
        return self._core_metric.score_batch(cases)
