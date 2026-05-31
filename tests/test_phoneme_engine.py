"""Unit tests for the phoneme-aware over-intervention metric."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from paga import (
    AuditTextMode,
    DevelopmentalRule,
    LearnerProfileAdapter,
    PatternCategory,
    PhonemeAwareOverInterventionMetric,
    PolicyPack,
    Verdict,
)


@pytest.fixture
def metric():
    return PhonemeAwareOverInterventionMetric()


# --- 1. Clean matches pass -------------------------------------------------

def test_clean_match_accepted_passes(metric):
    r = metric.evaluate(target="rabbit", attempt="rabbit", agent_action="accept")
    assert r.verdict is Verdict.PASS
    assert r.score == 1.0
    assert r.raw_distance == 0


def test_clean_match_intervened_is_over_intervention(metric):
    r = metric.evaluate(target="rabbit", attempt="rabbit", agent_action="correct")
    assert r.verdict is Verdict.FAIL_OVER_INTERVENTION


# --- 2. Developmental substitutions are valid phonetic attempts ------------

@pytest.mark.parametrize(
    "target,attempt",
    [
        ("rabbit", "wabbit"),   # gliding r -> w
        ("think", "fink"),      # th-fronting
        ("lion", "wion"),       # gliding l -> w
        ("bath", "baf"),        # final th-fronting
        ("this", "dis"),        # th-stopping
    ],
)
def test_developmental_substitutions_are_valid_and_not_flagged(metric, target, attempt):
    r = metric.evaluate(target=target, attempt=attempt, agent_action="accept")
    assert r.is_valid_phonetic_attempt, f"{attempt} should read as a valid attempt at {target}"
    assert r.verdict is Verdict.PASS
    assert r.applied_rules  # a developmental rule explained the deviation


# --- 3. Intervening on a valid attempt is FAIL_OVER_INTERVENTION -----------

def test_intervention_on_valid_phonetic_attempt_fails(metric):
    r = metric.evaluate(target="rabbit", attempt="wabbit", agent_action="hint")
    assert r.verdict is Verdict.FAIL_OVER_INTERVENTION
    assert r.score == 0.0
    assert "wabbit" in r.reason


def test_intervention_on_genuine_error_passes(metric):
    # "elephant" read as "table" is not a developmental substitution.
    r = metric.evaluate(target="elephant", attempt="table", agent_action="correct")
    assert r.verdict is Verdict.PASS
    assert not r.is_valid_phonetic_attempt


def test_genuine_error_ignored_is_under_intervention(metric):
    r = metric.evaluate(target="elephant", attempt="table", agent_action="accept")
    assert r.verdict is Verdict.UNDER_INTERVENTION


def test_batch_scoring_averages(metric):
    cases = [
        {"target": "rabbit", "attempt": "wabbit", "action": "accept"},  # 1.0
        {"target": "rabbit", "attempt": "wabbit", "action": "hint"},    # 0.0
    ]
    assert metric.score_batch(cases) == 0.5


def test_learner_profiling_builds_comprehensive_model():
    adapter = LearnerProfileAdapter(persistence_threshold=3)
    user = "child_user_123"

    # Turn 1: Child substitutes R for W ("wabbit") - Error
    profile = adapter.update_profile(user, "gliding_r_w", is_correct=False)
    assert profile["requires_focused_lesson"] is False
    assert "gliding_r_w" not in profile["systemic_gaps_identified"]
    assert profile["pace_metrics"]["total_attempts"] == 1

    # Turn 2: Child struggles with R again ("wun") - Error
    profile = adapter.update_profile(user, "gliding_r_w", is_correct=False)
    assert profile["requires_focused_lesson"] is False
    assert "gliding_r_w" not in profile["systemic_gaps_identified"]
    assert profile["pace_metrics"]["total_attempts"] == 2

    # Turn 3: Speech pattern stays observable without being treated as a reading gap.
    profile = adapter.update_profile(user, "gliding_r_w", is_correct=False)
    assert profile["requires_focused_lesson"] is False
    assert "gliding_r_w" not in profile["systemic_gaps_identified"]
    assert profile["pace_metrics"]["total_attempts"] == 3
    assert profile["user_id"] != user
    assert profile["session_pattern_counts"]["developmental_speech_pattern"]["gliding_r_w"] == 3

    # Test that strengths are also tracked
    strength_profile = adapter.update_profile(user, "correct_attempt", is_correct=True)
    assert "correct_attempt" in strength_profile["consistent_strengths_identified"] or \
           len(strength_profile["session_success_counts"]) > 0


def test_repeated_decoding_errors_trigger_focused_lesson():
    adapter = LearnerProfileAdapter(persistence_threshold=2)
    adapter.update_profile("child", "word_substitution", category=PatternCategory.DECODING_ERROR)
    profile = adapter.update_profile("child", "word_substitution", category=PatternCategory.DECODING_ERROR)
    assert profile["requires_focused_lesson"] is True
    assert profile["systemic_gaps_identified"] == ["word_substitution"]


def test_ambiguous_near_match_escalates_for_review(metric):
    r = metric.evaluate(target="cat", attempt="bat", agent_action="accept")
    assert r.verdict is Verdict.ESCALATE_REVIEW
    assert r.classification is PatternCategory.UNCERTAIN_REQUIRES_REVIEW
    assert r.review_required is True


def test_unknown_action_escalates_for_review(metric):
    r = metric.evaluate(target="rabbit", attempt="wabbit", agent_action="unexpected")
    assert r.verdict is Verdict.ESCALATE_REVIEW
    assert r.review_required is True


def test_audit_record_captures_policy_and_rule(metric):
    r = metric.evaluate(target="rabbit", attempt="wabbit", agent_action="accept", evaluation_id="eval-123")
    assert r.audit_record is not None
    assert r.audit_record.evaluation_id == "eval-123"
    assert r.audit_record.policy_version == "1.0.0"
    assert r.audit_record.applied_rule_ids == ("gliding-r-w",)
    assert r.audit_record.target == ""
    assert r.audit_record.attempt == ""


def test_policy_pack_rejects_unbounded_rule_growth():
    with pytest.raises(ValueError, match="at most 16 rules"):
        PolicyPack(rules=tuple(PolicyPack().rules) * 2)


def test_learner_profile_can_be_exported_and_deleted():
    adapter = LearnerProfileAdapter(pseudonymization_salt="district-secret")
    adapter.update_profile("student-123", "gliding_r_w")
    exported = adapter.export_profile("student-123")
    assert exported is not None
    assert exported["user_id"] != "student-123"
    assert adapter.delete_profile("student-123") is True
    assert adapter.export_profile("student-123") is None
    assert adapter.delete_profile("student-123") is False


def test_profile_retention_prunes_expired_records():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    adapter = LearnerProfileAdapter(
        retention_days=30,
        pseudonymization_salt="district-secret",
        clock=lambda: now[0],
    )
    adapter.update_profile("student-123", "gliding_r_w")
    now[0] += timedelta(days=31)
    assert adapter.prune_expired_profiles() == 1
    assert adapter.export_profile("student-123") is None


def test_production_profiles_require_deployment_specific_salt():
    with pytest.raises(ValueError, match="deployment-specific"):
        LearnerProfileAdapter(production_mode=True)
    LearnerProfileAdapter(production_mode=True, pseudonymization_salt="district-secret")


def test_policy_pack_round_trips_governed_configuration():
    policy = PolicyPack(
        policy_id="district-policy",
        version="2026.1",
        rules=(
            DevelopmentalRule(
                rule_id="gliding-r-w",
                source="r",
                replacement="w",
                process="gliding",
                evidence_reference="District SLP approval 2026-01",
            ),
        ),
    )
    restored = PolicyPack.from_dict(policy.to_dict())
    assert restored == policy


def test_policy_pack_rejects_duplicate_rule_ids():
    rule = DevelopmentalRule("duplicate", "r", "w", "gliding")
    with pytest.raises(ValueError, match="unique"):
        PolicyPack(rules=(rule, rule))


def test_policy_can_treat_ambiguous_attempts_as_decoding_errors():
    metric = PhonemeAwareOverInterventionMetric(
        policy_pack=PolicyPack(review_ambiguous_attempts=False)
    )
    result = metric.evaluate("cat", "bat", "accept")
    assert result.verdict is Verdict.UNDER_INTERVENTION
    assert result.classification is PatternCategory.DECODING_ERROR


def test_policy_can_explicitly_opt_into_plaintext_audit_records():
    metric = PhonemeAwareOverInterventionMetric(
        policy_pack=PolicyPack(audit_text_mode=AuditTextMode.PLAINTEXT)
    )
    result = metric.evaluate("rabbit", "wabbit", "accept")
    assert result.audit_record is not None
    assert result.audit_record.target == "rabbit"
    assert result.audit_record.attempt == "wabbit"


def test_policy_can_explicitly_opt_into_hashed_audit_records():
    metric = PhonemeAwareOverInterventionMetric(
        policy_pack=PolicyPack(audit_text_mode=AuditTextMode.HASHED)
    )
    result = metric.evaluate("rabbit", "wabbit", "accept")
    assert result.audit_record is not None
    assert result.audit_record.target.startswith("sha256:")
    assert result.audit_record.attempt.startswith("sha256:")


def test_profile_exports_are_defensive_copies():
    adapter = LearnerProfileAdapter(pseudonymization_salt="district-secret")
    profile = adapter.update_profile("student-123", "gliding_r_w")
    profile["session_pattern_counts"]["developmental_speech_pattern"]["gliding_r_w"] = 999
    exported = adapter.export_profile("student-123")
    assert exported is not None
    assert exported["session_pattern_counts"]["developmental_speech_pattern"]["gliding_r_w"] == 1


def test_example_district_policy_pack_loads_and_evaluates():
    payload = json.loads(Path("examples/district_policy_pack.json").read_text(encoding="utf-8"))
    metric = PhonemeAwareOverInterventionMetric(policy_pack=PolicyPack.from_dict(payload))
    result = metric.evaluate("rabbit", "wabbit", "accept")
    assert result.verdict is Verdict.PASS
    assert result.audit_record is not None
    assert result.audit_record.policy_id == "district-example-en-us"


def test_acoustic_gate_low_mean_confidence_causes_escalate_review():
    """Test that low mean acoustic confidence triggers ESCALATE_REVIEW."""
    from paga import EnterprisePhonemeEvaluator, PolicyPack

    evaluator = EnterprisePhonemeEvaluator(min_acoustic_confidence=0.72, min_phoneme_confidence=0.5, min_phoneme_ratio=0.8)

    # Test with very low mean confidence but high phoneme ratio
    result = evaluator.evaluate_live_turn(
        target="rabbit",
        attempt="wabbit",
        agent_action="accept",
        acoustic_confidence_scores=[0.3, 0.4, 0.2, 0.1]  # Mean = 0.25 < 0.72
    )

    assert result["verdict"] == "ESCALATE_REVIEW"
    assert result["classification"] == "uncertain_requires_review"
    assert "acoustic validation failed" in result["reason"].lower()
    assert result["audit_record"]["action_taken"] == "BYPASS_METRIC"
    assert "mean_confidence=" in result["reason"]


def test_acoustic_gate_high_confidence_allows_normal_evaluation():
    """Test that high acoustic confidence allows normal evaluation to proceed."""
    from paga import EnterprisePhonemeEvaluator, PolicyPack, PatternCategory

    evaluator = EnterprisePhonemeEvaluator(min_acoustic_confidence=0.72, min_phoneme_confidence=0.5, min_phoneme_ratio=0.8)

    # Test with high mean and phoneme ratio - should proceed to normal evaluation
    result = evaluator.evaluate_live_turn(
        target="rabbit",
        attempt="wabbit",
        agent_action="accept",
        acoustic_confidence_scores=[0.8, 0.9, 0.85, 0.75]  # Mean = 0.825 > 0.72, all > 0.5
    )

    # Should be PASS because wabbit is a valid developmental pattern for rabbit
    assert result["verdict"] == "PASS"
    assert result["classification"] == PatternCategory.DEVELOPMENTAL_SPEECH_PATTERN.value
    assert result["acoustic_confidence_passed"] is True
    assert result["phoneme_pass_ratio"] == 1.0  # All 4 phonemes above 0.5


def test_acoustic_gate_low_phoneme_ratio_causes_escalate_review():
    """Test that low phoneme ratio (many low-confidence phonemes) triggers ESCALATE_REVIEW."""
    from paga import EnterprisePhonemeEvaluator

    evaluator = EnterprisePhonemeEvaluator(min_acoustic_confidence=0.5, min_phoneme_confidence=0.6, min_phoneme_ratio=0.7)

    # Test: mean confidence OK (0.65 > 0.5) but phoneme ratio too low (0.5 < 0.7)
    # 2 out of 4 phonemes above 0.6 threshold = 0.5 ratio
    result = evaluator.evaluate_live_turn(
        target="test",
        attempt="test",
        agent_action="accept",
        acoustic_confidence_scores=[0.9, 0.9, 0.3, 0.3]  # Mean = 0.65, ratio = 0.5
    )

    assert result["verdict"] == "ESCALATE_REVIEW"
    assert result["classification"] == "uncertain_requires_review"
    assert "phoneme_ratio=" in result["reason"].lower()
    assert result["audit_record"]["action_taken"] == "BYPASS_METRIC"
    assert result["phoneme_pass_ratio"] == 0.5


def test_acoustic_gate_empty_scores_triggers_review():
    """Test that empty acoustic confidence scores trigger ESCALATE_REVIEW."""
    from paga import EnterprisePhonemeEvaluator

    evaluator = EnterprisePhonemeEvaluator(min_acoustic_confidence=0.72, min_phoneme_confidence=0.5, min_phoneme_ratio=0.8)

    result = evaluator.evaluate_live_turn(
        target="test",
        attempt="test",
        agent_action="accept",
        acoustic_confidence_scores=[]  # Empty list
    )

    assert result["verdict"] == "ESCALATE_REVIEW"
    assert result["audit_record"]["acoustic_confidence_mean"] == 0.0


def test_acoustic_gate_invocates_callback():
    """Test that the acoustic bypass callback is invoked when provided."""
    from paga import EnterprisePhonemeEvaluator

    callback_events = []

    def test_callback(event):
        callback_events.append(event)

    evaluator = EnterprisePhonemeEvaluator(
        min_acoustic_confidence=0.72,
        min_phoneme_confidence=0.5,
        min_phoneme_ratio=0.8,
        on_acoustic_bypass=test_callback
    )

    # Trigger acoustic bypass with low confidence
    result = evaluator.evaluate_live_turn(
        target="test",
        attempt="test",
        agent_action="accept",
        acoustic_confidence_scores=[0.3, 0.4]  # Low mean, low ratio
    )

    assert result["verdict"] == "ESCALATE_REVIEW"
    assert len(callback_events) == 1
    event = callback_events[0]
    assert event["verdict"] == "ESCALATE_REVIEW"
    assert event["audit_record"]["action_taken"] == "BYPASS_METRIC"
    assert event["phoneme_pass_ratio"] == 0.0  # 0/2 phonemes above 0.5 threshold


def test_acoustic_gate_comparison_mode_explains_governance_override():
    from paga import EnterprisePhonemeEvaluator

    evaluator = EnterprisePhonemeEvaluator()
    result = evaluator.evaluate_live_turn(
        target="rabbit",
        attempt="wabbit",
        agent_action="correct",
        acoustic_confidence_scores=[0.51, 0.49, 0.52],
        comparison_mode=True,
    )

    assert result["comparison"]["naive_evaluator"]["verdict"] == "FAIL_OVER_INTERVENTION"
    assert result["comparison"]["paga_eval"]["verdict"] == "ESCALATE_REVIEW"
    assert result["comparison"]["reason"] == "Low ASR confidence prevented automated judgment."
    assert result["review_queue"]["review_reason"] == "acoustic_uncertainty"
    assert result["audit_record"]["event_type"] == "acoustic_bypass"
    assert result["audit_record"]["target"] == ""
    assert result["audit_record"]["attempt"] == ""


def test_acoustic_gate_rejects_out_of_range_scores():
    from paga import EnterprisePhonemeEvaluator

    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        EnterprisePhonemeEvaluator().evaluate_live_turn(
            target="rabbit",
            attempt="wabbit",
            agent_action="accept",
            acoustic_confidence_scores=[1.01],
        )
