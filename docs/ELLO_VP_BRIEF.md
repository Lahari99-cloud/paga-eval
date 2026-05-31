# paga-eval for Ello: VP Brief

## Why This Exists

Ello's reading coach listens as children read aloud, adapts to their ability and
interests, and supports them when they struggle. Ello describes its mission as
unlocking the potential within all children and identifies child speech
recognition, adaptive instruction, and science-of-reading responses as core
product capabilities:

- [Ello reading coach](https://www.ello.com/)
- [Ello mission and team](https://www.ello.com/about)

`paga-eval` explores one narrow but consequential evaluation question for that
kind of product:

> Did the AI tutor make the right instructional decision after hearing a child's
> reading attempt?

A transcript-only grader can reward the wrong tutor behavior. For example, it
may reward correction when a child reads `rabbit` as `wabbit`, even when the
institution-approved policy treats that attempt as a developmental speech
pattern rather than a decoding error.

## Executive Verdict

`paga-eval` is a **harness-engineered, end-to-end reference service** for
auditing tutor-agent decisions. It is not an Ello-integrated production system,
clinical diagnostic tool, or validated child-speech model.

The repository demonstrates a credible production slice:

- deterministic tutor-decision evaluation;
- versioned and reviewable policy packs;
- explicit human-review escalation;
- acoustic-confidence bypass logic for unreliable ASR hypotheses;
- privacy-by-default audit records;
- tenant-scoped API credentials and encrypted learner profiles;
- retention, deletion, integrity checks, online backup, and key rotation;
- Docker smoke tests, OpenAPI contract checks, dependency audit, CodeQL, and a
  three-version Python CI matrix.

The most important next step is product integration: wire real ASR confidence,
child-speech benchmark cases, and human-review outcomes into the hosted harness.

## 90-Second VP Walkthrough

1. Open the [interactive demo](https://lahari99-cloud.github.io/paga-eval/examples/institution_demo.html).
2. Run `Developmental pattern`: accepting `rabbit -> wabbit` passes.
3. Run `Over-intervention`: correcting the same attempt fails.
4. Run `Human review`: accepting `cat -> bat` escalates rather than silently
   passing.
5. Point to the omitted transcript fields, policy version, applied rule IDs,
   encrypted-profile controls, and operations counters.
6. Open the [architecture diagram](assets/architecture.svg) and explain where
   real ASR confidence and Ello-owned policy review would enter the flow.

## Readiness Matrix

| Capability | Current evidence | Readiness |
| --- | --- | --- |
| Tutor-decision grading | Deterministic pass, over-intervention, under-intervention, and review verdicts | Working reference implementation |
| Policy governance | Versioned `PolicyPack`, bounded rules, round-trip tests, applied rule IDs | Strong foundation; requires Ello-approved policy packs |
| Human oversight | `ESCALATE_REVIEW` verdict and LMS manual-grading mapping | Contract exists; review queue and feedback loop remain integration work |
| Acoustic quality gate | `EnterprisePhonemeEvaluator` bypasses low-confidence ASR hypotheses | Library implementation exists; hosted API wiring remains |
| Privacy-safe audits | Transcript omission by default, encrypted durable records, request correlation | Working reference implementation |
| Learner memory | Pseudonymous encrypted profiles, deletion, retention, tenant isolation | Working reference implementation; Ello data-model alignment remains |
| Operations | Health, readiness, structured privacy-bounded logs, maintenance CLI, Docker smoke | Strong reference deployment controls |
| Evaluation dataset | Five-case starter fixture and benchmark runner | Harness exists; representative child-speech evaluation program remains |
| Fairness and accessibility | Deployment checklist calls for cohort, dialect, multilingual, and accessibility review | Required pre-production work |
| Production platform | Dockerized FastAPI reference service with API-key boundary | Not a substitute for Ello ingress, IdP, secrets, queues, observability, or incident response |

## What Is Real Today

### Decision harness

The core metric evaluates a triple:

```text
target word + recognized attempt + tutor action
```

It records the classification, verdict, policy version, applied rules, edit
distances, and whether a human must review the case.

### Privacy boundary

Durable audits omit transcript text by default. The hosted workflow stores
audits and pseudonymous learner profiles encrypted at rest. It supports deletion,
retention pruning, key rotation, integrity validation, and atomic online backup.

### Release discipline

The repository runs:

- `79` automated tests;
- Python `3.10`, `3.11`, and `3.12` CI;
- deterministic OpenAPI checks against pinned service dependencies;
- Docker health, readiness, non-root, logging, and maintenance smoke checks;
- CodeQL and pinned-dependency auditing.

## What Still Blocks Production Use

### P0: integrate the real tutor event stream

- Send ASR hypotheses, timing, confidence scores, tutor action, locale, policy
  version, and correlation IDs through one hosted evaluation contract.
- Wire `EnterprisePhonemeEvaluator` into `/v1/evaluations`.
- Persist acoustic-bypass events in the same auditable format as normal
  decisions.
- Connect `ESCALATE_REVIEW` to an owned review queue with reviewer outcomes.

### P0: build the child-speech evaluation program

- Create consented, governance-approved evaluation datasets.
- Slice results by age band, reading level, locale, dialect, acoustic condition,
  device, and intervention type.
- Track over-intervention, under-intervention, escalation, reviewer agreement,
  latency, and coverage.
- Add regression thresholds and release-blocking quality budgets.

### P1: align with Ello's platform

- Integrate Ello identity, secrets, queues, observability, and incident-response
  systems.
- Replace the reference SQLite deployment where workload and reliability goals
  require managed storage.
- Exercise restore procedures, load tests, fault injection, and deployment
  rollback.
- Define data retention and secondary-use boundaries with product, privacy, and
  legal owners.

### P1: validate instructional policy

- Review every developmental rule with Ello educators and speech-language
  experts.
- Treat the bundled `en-US` rules only as a transparent starter configuration.
- Preserve policy versions so historical decisions remain interpretable.

## Discussion Questions For Ello

1. Which tutor actions matter most to evaluate: correction, hinting, waiting,
   encouragement, story adaptation, or lesson selection?
2. Which ASR confidence and timing signals are available at decision time?
3. Where should human-review outcomes flow back into product and evaluation?
4. Which learner-memory fields are instructionally useful enough to justify
   retention?
5. What release metrics should block a weekly ship?

## Bottom Line

The value of this project is not that a small heuristic replaces Ello's speech
or instructional systems. It does not.

The value is the harness discipline around a hard product question: evaluate the
tutor's behavior, preserve privacy, escalate uncertainty, version policy, and
make release quality reviewable.
