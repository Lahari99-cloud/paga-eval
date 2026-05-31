"""
Demo script showcasing the EnterprisePhonemeEvaluator acoustic gate functionality.

This demonstrates how the acoustic gate prevents low-confidence ASR hypotheses
(from systems like wav2vec) from causing incorrect evaluations and contaminated
audit trails in noisy environments.

Run: python examples/acoustic_gate_demo.py
"""

from paga import EnterprisePhonemeEvaluator, PolicyPack, PatternCategory, Verdict

def demo_acoustic_gate():
    print("=" * 70)
    print("paga-eval Acoustic Gate Demo")
    print("Protecting evaluation integrity from ASR hallucinations")
    print("=" * 70)

    # Create an evaluator with reasonable thresholds for demonstration
    evaluator = EnterprisePhonemeEvaluator(
        min_acoustic_confidence=0.70,   # 70% mean confidence required
        min_phoneme_confidence=0.50,    # 50% confidence per phoneme minimum
        min_phoneme_ratio=0.75          # 75% of phonemes must exceed threshold
    )

    print("\nEvaluator Configuration:")
    print(f"  • Mean confidence threshold: {evaluator.min_acoustic_confidence}")
    print(f"  • Per-phoneme confidence threshold: {evaluator.min_phoneme_confidence}")
    print(f"  • Phoneme ratio threshold: {evaluator.min_phoneme_ratio}")

    test_cases = [
        {
            "name": "Clear Speech - Good ASR Confidence",
            "target": "rabbit",
            "attempt": "wabbit",  # developmental pattern (r->w gliding)
            "action": "accept",
            "confidence_scores": [0.85, 0.92, 0.88, 0.90, 0.87],  # High quality ASR
            "expected_verdict": "PASS",
            "description": "Clear child speech with confident ASR recognition"
        },
        {
            "name": "Noisy Environment - Low Overall Confidence",
            "target": "rabbit",
            "attempt": "wabbit",
            "action": "accept",
            "confidence_scores": [0.30, 0.40, 0.25, 0.35, 0.20],  # Poor ASR (background noise)
            "expected_verdict": "ESCALATE_REVIEW",
            "description": "Noisy classroom causing low ASR confidence overall"
        },
        {
            "name": "Mixed Quality - Some Phonemes Unclear",
            "target": "cat",
            "attempt": "bat",
            "action": "accept",
            "confidence_scores": [0.90, 0.40, 0.85],  # Middle phoneme unclear
            "expected_verdict": "ESCALATE_REVIEW",
            "description": "One unclear phoneme drops ratio below threshold"
        },
        {
            "name": "Silence/Hallucination - Empty-like ASR Output",
            "target": "test",
            "attempt": "test",
            "action": "accept",
            "confidence_scores": [0.10, 0.15, 0.08, 0.12],  # Near-silence hallucinations
            "expected_verdict": "ESCALATE_REVIEW",
            "description": "ASR hallucinating phonemes during silence (common wav2vec issue)"
        },
        {
            "name": "Boundary Case - Just Above Thresholds",
            "target": "rabbit",
            "attempt": "wabbit",  # Valid developmental pattern: gliding r->w
            "action": "accept",
            "confidence_scores": [0.75, 0.60, 0.80, 0.70],  # Well above thresholds
            "expected_verdict": "PASS",  # Should process normally
            "description": "Signal quality well above acceptance thresholds with valid developmental pattern"
        }
    ]

    print("\n" + "=" * 70)
    print("TEST CASES")
    print("=" * 70)

    passed_tests = 0
    total_tests = len(test_cases)

    for i, case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {case['name']}")
        print(f"  Scenario: {case['description']}")
        print(f"  Input: target='{case['target']}', attempt='{case['attempt']}', action='{case['action']}'")
        print(f"  ASR Confidence: {case['confidence_scores']}")
        print(f"    -> Mean: {sum(case['confidence_scores'])/len(case['confidence_scores']):.2f}")

        # Calculate phoneme ratio for display
        phonemes_above = sum(1 for s in case['confidence_scores'] if s >= evaluator.min_phoneme_confidence)
        phoneme_ratio = phonemes_above / len(case['confidence_scores'])
        print(f"    -> Phonemes >= {evaluator.min_phoneme_confidence}: {phonemes_above}/{len(case['confidence_scores'])} ({phoneme_ratio:.0%})")

        # Execute evaluation
        result = evaluator.evaluate_live_turn(
            target=case["target"],
            attempt=case["attempt"],
            agent_action=case["action"],
            acoustic_confidence_scores=case["confidence_scores"]
        )

        verdict = result["verdict"]
        classification = result["classification"]

        # Check if result matches expectation
        success = verdict == case["expected_verdict"]
        status_icon = "PASS" if success else "FAIL"

        print(f"  Expected: {case['expected_verdict']}")
        print(f"  Actual:   {verdict} ({classification})")
        print(f"  Status:   {status_icon}")

        if not success:
            print(f"  Reason:   {result['reason']}")
        elif "acoustic" in result.get("reason", "").lower():
            print(f"  Detail:   {result['reason']}")
        else:
            print(f"  Detail:   {result['reason']}")

        if success:
            passed_tests += 1

        print("-" * 50)

    print(f"\nSUMMARY: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("*** All tests passed! The acoustic gate is working correctly.")
        print("\nKey Benefits Demonstrated:")
        print("  * Prevents low-confidence ASR hallucinations from causing false evaluations")
        print("  * Maintains normal operation for high-confidence speech")
        print("  * Provides detailed audit trail with acoustic metrics")
        print("  * Protects evaluation integrity in noisy real-world environments")
    else:
        print("!!! Some tests failed - review implementation")

    print("\n" + "=" * 70)
    print("Demo Complete")
    print("=" * 70)

def demo_integration_with_existing_api():
    """Show how the EnterprisePhonemeEvaluator integrates with existing paga-eval usage."""
    print("\n" + "=" * 70)
    print("INTEGRATION DEMO: Using EnterprisePhonemeEvaluator with existing code")
    print("=" * 70)

    # Show backward compatibility - existing code still works
    from paga import PhonemeAwareOverInterventionMetric

    print("\n1. Existing paga-eval usage unchanged:")
    metric = PhonemeAwareOverInterventionMetric()
    result = metric.evaluate("rabbit", "wabbit", "accept")
    print(f"   rabbit/wabbit/accept -> {result.verdict.value} ({result.classification.value})")

    print("\n2. New enterprise usage with acoustic awareness:")
    evaluator = EnterprisePhonemeEvaluator()

    # High confidence - behaves like original
    high_conf_result = evaluator.evaluate_live_turn(
        target="rabbit",
        attempt="wabbit",
        agent_action="accept",
        acoustic_confidence_scores=[0.8, 0.9, 0.85, 0.75]
    )
    print(f"   High confidence rabbit/wabbit/accept -> {high_conf_result['verdict']} ({high_conf_result['classification']})")

    # Low confidence - triggers acoustic gate
    low_conf_result = evaluator.evaluate_live_turn(
        target="rabbit",
        attempt="wabbit",
        agent_action="accept",
        acoustic_confidence_scores=[0.3, 0.4, 0.2, 0.1]
    )
    print(f"   Low confidence rabbit/wabbit/accept -> {low_conf_result['verdict']} (acoustic gate triggered)")
    print(f"   Reason: {low_conf_result['reason']}")

    print("\n*** Backward compatibility maintained while adding enterprise features")

if __name__ == "__main__":
    demo_acoustic_gate()
    demo_integration_with_existing_api()