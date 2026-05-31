"""Example: grade a LangGraph reading-tutor agent with paga-eval.

This shows the intended production loop: a tiny LangGraph agent decides whether to
intervene on a child's reading attempt, and paga-eval grades that decision. Each
grade is logged as a score so you can track over-intervention rate over time
(Langfuse shown as an optional sink).

Run:
    pip install -e ".[integrations]"
    python examples/langgraph_tutor_eval.py
"""

from functools import partial
from typing import TypedDict

from paga import (
    LearnerProfileAdapter,
    PatternCategory,
    PhonemeAwareOverInterventionMetric,
)

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # keep the file importable without the extra installed
    StateGraph = None


class AdvancedTutorState(TypedDict):
    target: str
    attempt: str
    action: str
    user_id: str
    learner_profile: dict


def decide_action(state: AdvancedTutorState) -> AdvancedTutorState:
    """A naive baseline policy: intervene on ANY deviation from the target.

    This is exactly the policy paga-eval is designed to catch as over-intervening.
    Swap this node for your real agent.
    """
    state["action"] = "accept" if state["attempt"] == state["target"] else "correct"
    return state


def dynamic_policy_node(
    state: AdvancedTutorState, profile_adapter: LearnerProfileAdapter
) -> AdvancedTutorState:
    """An advanced policy that uses comprehensive learner profiling to make better instructional decisions.

    Analyzes strengths, gaps, pace, and engagement to drive personalized interventions:
    - Systemic gaps → Targeted micro-lessons
    - Consistent strengths → Recognition and advancement
    - Pace trends → Adjust difficulty or provide encouragement
    - Engagement levels → Modify approach to maintain motivation
    """
    profile = state["learner_profile"]

    # Import here to avoid circular imports
    from paga import PhonemeAwareOverInterventionMetric
    metric = PhonemeAwareOverInterventionMetric()

    # Evaluate the current attempt with PAGA
    paga_result = metric.evaluate(state["target"], state["attempt"], "")
    is_valid_or_clean = paga_result.is_valid_phonetic_attempt or paga_result.raw_distance == 0

    # Update comprehensive learner profile
    # For demo purposes, we'll simulate response time and correctness
    # In a real system, these would come from actual measurements
    response_time = 1.2  # Simulated response time in seconds
    # Track speech-pattern observations separately from clean readings. A valid
    # articulation pattern is not a decoding failure, but it should remain visible.
    is_correct_attempt = paga_result.raw_distance == 0

    # Determine phonetic error type for profiling (simplified)
    attempt_n = "".join(c for c in state["attempt"].lower().strip() if c.isalpha())
    target_n = "".join(c for c in state["target"].lower().strip() if c.isalpha())

    phonetic_error_type = "none"
    if paga_result.raw_distance > 0:  # There was some deviation
        if attempt_n == target_n.replace("r", "w") and "w" in attempt_n:
            phonetic_error_type = "gliding_r_w"
        elif attempt_n == target_n.replace("l", "w") and "w" in attempt_n:
            phonetic_error_type = "gliding_l_w"
        elif attempt_n == target_n.replace("th", "f") or attempt_n == target_n.replace("th", "v"):
            phonetic_error_type = "th_fronting"
        elif paga_result.raw_distance > 2:  # Likely genuine error
            phonetic_error_type = "genuine_error"

    # Update the comprehensive profile
    profile = profile_adapter.update_profile(
        user_id=state["user_id"],
        phonetic_error_type=phonetic_error_type,
        is_correct=is_correct_attempt,
        response_time=response_time,
        category=paga_result.classification,
    )

    # Advanced Instructional Decision Making based on Comprehensive Profile

    # 1. Address likely decoding errors immediately. Motivational signals must
    # never override an instructional guardrail.
    systemic_gaps = profile.get("systemic_gaps_identified", [])
    if paga_result.classification is PatternCategory.DECODING_ERROR:
        action_payload = "That was a tricky one! Let's look at the word together and sound it out."
        action = "correct"

    # 2. Check for systemic gaps requiring targeted intervention
    elif systemic_gaps:
        gap = systemic_gaps[0]  # Focus on most prevalent gap
        if "gliding_r_w" in gap:
            action_payload = "I notice we are practicing our /r/ sounds! Let's say it together: Rrr-abbit."
            action = "intervene"
        elif "gliding_l_w" in gap:
            action_payload = "Let's work on our /l/ sounds! Try saying 'lion' with your tongue up: Lll-lion."
            action = "intervene"
        elif "th_fronting" in gap:
            action_payload = "Let's practice our 'th' sounds! Put your tongue between your teeth: Thhh-ink."
            action = "intervene"
        elif "genuine_error" in gap:
            action_payload = "That was a tricky one! Let's look at the word together and sound it out."
            action = "intervene"
        else:
            action_payload = f"Let's focus on improving: {gap}"
            action = "intervene"

    # 3. Check for consistent strengths to reinforce and build confidence
    elif profile.get("consistent_strengths_identified"):
        strengths = profile["consistent_strengths_identified"]
        if "correct_attempt" in strengths:
            action_payload = "Great job! You're really getting the hang of this. Keep up the excellent work!"
            action = "praise"
        else:
            action_payload = f"You're showing strength in: {', '.join(strengths)}. Let's build on that!"
            action = "continue"

    # 4. Check pace and engagement for motivational adjustments
    else:
        pace_info = profile.get("pace_metrics", {})
        engagement_info = profile.get("engagement_indicators", {})

        pace_trend = pace_info.get("pace_trend", "unknown")
        engagement_level = engagement_info.get("consistency", "unknown")

        if pace_trend == "declining" and engagement_level == "low":
            action_payload = "I can see this is getting challenging. Let's take a breath and try again together."
            action = "encourage"
        elif pace_trend == "improving":
            action_payload = "Wow! You're improving so fast! I love seeing your progress!"
            action = "praise"
        elif engagement_level == "high":
            action_payload = "You're really focused today! Let's keep this great momentum going!"
            action = "continue"
        else:
            # Fall back to enhanced PAGA-based decision
            if is_valid_or_clean:
                action_payload = "Nice try! Let's keep going."
                action = "accept"
            else:
                action_payload = "Let's work on this one together."
                action = "correct"

    # Return updated state with action and enriched profile
    return {
        **state,
        "action": action,
        "action_payload": action_payload,
        "learner_profile": profile  # Store the updated profile for next turn
    }


def build_agent(profile_adapter: LearnerProfileAdapter | None = None):
    if StateGraph is None:
        raise RuntimeError('Install integrations: pip install -e ".[integrations]"')
    g = StateGraph(AdvancedTutorState)
    g.add_node("decide", decide_action)
    profile_adapter = profile_adapter or LearnerProfileAdapter(persistence_threshold=3)
    g.add_node("policy", partial(dynamic_policy_node, profile_adapter=profile_adapter))
    g.add_edge(START, "decide")
    g.add_edge("decide", "policy")
    g.add_edge("policy", END)
    return g.compile()


# Optional: log scores to Langfuse if configured. No-op otherwise.
import os
import logging

# Force Langfuse to be quiet if keys aren't set
logging.getLogger("langfuse").setLevel(logging.ERROR)

def log_score(name: str, value: float, comment: str) -> None:
    try:
        from langfuse import Langfuse

        # Check if Langfuse credentials are available
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")

        # If keys are missing, initialize with dummy values to avoid errors
        if not public_key or not secret_key:
            langfuse = Langfuse(
                public_key="pk-lf-mock",
                secret_key="sk-lf-mock",
                host="https://langfuse.com"
            )
            # Don't actually send data with mock keys
            return
        else:
            langfuse = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=os.getenv("LANGFUSE_HOST", "https://langfuse.com")
            )

        langfuse.score(name=name, value=value, comment=comment)
    except Exception:
        pass


def main() -> None:
    # Simulate a session with a child who struggles with /r/ sounds
    transcript = [
        {"target": "rabbit", "attempt": "wabbit"},   # developmental: gliding r->w
        {"target": "rain", "attempt": "wain"},       # developmental: gliding r->w
        {"target": "run", "attempt": "wun"},         # developmental: gliding r->w
        {"target": "rat", "attempt": "wat"},         # developmental: gliding r->w (should trigger intervention now!)
        {"target": "think", "attempt": "fink"},      # developmental: th-fronting
        {"target": "bath", "attempt": "baf"},        # developmental: final th-fronting
        {"target": "cat", "attempt": "cat"},         # clean read
        {"target": "elephant", "attempt": "table"},  # genuine misread: SHOULD correct
    ]

    metric = PhonemeAwareOverInterventionMetric()
    profile_adapter = LearnerProfileAdapter(persistence_threshold=3)
    agent = build_agent(profile_adapter)

    # User ID for tracking this child's session
    user_id = "child_user_123"

    cases, fails = [], 0
    print("Multi-turn session with learner profiling:")
    print("=" * 50)

    for i, turn in enumerate(transcript):
        # Get agent decision
        out = agent.invoke({
            "target": turn["target"],
            "attempt": turn["attempt"],
            "action": "",
            "user_id": user_id,
            "learner_profile": {}  # Will be populated by policy node
        })

        # Evaluate the agent's decision with paga-eval
        result = metric.evaluate(out["target"], out["attempt"], out["action"])

        profile = out["learner_profile"]

        cases.append({"target": out["target"], "attempt": out["attempt"], "action": out["action"]})
        fails += 0 if result.passed else 1
        log_score("over_intervention", result.score, result.reason)

        # Display turn information
        print(f"Turn {i+1}: {out['target']:>9} -> {out['attempt']:<8}")
        print(f"  Action: {out['action']:<8} | PAGA Verdict: {result.verdict.value}")
        print(f"  Profile: {profile['systemic_gaps_identified']} "
              f"(requires lesson: {profile['requires_focused_lesson']})")
        if out.get("action_payload"):
            print(f"  Feedback: {out['action_payload']}")
        print()

    print(f"\nFinal batch score: {metric.score_batch(cases):.2f}  |  failures: {fails}/{len(cases)}")
    print("\nThis demonstrates privacy-safe learner profiling without automatic diagnosis.")
    print("Developmental speech patterns stay visible to educators without becoming reading deficits.")


if __name__ == "__main__":
    main()
