# paga-eval: 90-Second Executive Demo

Use this script for a short narrated Loom, YouTube, or LinkedIn walkthrough.
The repository also includes a reproducible browser-built showcase with live
console screenshots, an architecture diagram, and an executive dashboard.

## Before Recording

```bash
pip install -e ".[dev,integrations,service]"
python examples/run_institution_demo.py
# open http://127.0.0.1:8000/demo
```

Confirm that the console loads and the API status is healthy. Keep the browser
zoom large enough for the verdict cards to be readable.

For the reproducible browser-built showcase, run:

```bash
node scripts/build_showcase_assets.mjs
```

This refreshes:

- `docs/assets/paga-eval-showcase.webm`
- `docs/assets/architecture.svg`
- `docs/assets/executive-dashboard.svg`
- `docs/assets/screenshots/*.png`

Use the narration below when recording the final public Loom, YouTube, or
LinkedIn version.

## Recording Script

| Time | Screen action | Narration |
| --- | --- | --- |
| 0:00-0:10 | Show the console title and privacy note. | "`paga-eval` is an evaluation guardrail for child-reading tutor agents. It checks whether the tutor responded appropriately, not simply whether two transcripts match." |
| 0:10-0:27 | Run the supportive developmental-pattern scenario: `rabbit`, `wabbit`, `accept`. | "Here, the tutor accepts an age-appropriate developmental speech pattern. The evaluator passes the response and records the applied policy rule." |
| 0:27-0:43 | Run the over-intervention scenario: `rabbit`, `wabbit`, `correct`. | "If the tutor corrects that same pattern, the evaluator flags over-intervention. This is the failure a transcript-only grader can miss." |
| 0:43-0:57 | Run the human-review scenario: `cat`, `bat`, `accept`. | "An ambiguous near-match is not silently accepted. It escalates to human review so uncertain cases remain supervised." |
| 0:57-1:10 | Run the decoding-error scenario: `rabbit`, `zebra`, `accept`. | "A likely decoding error that the tutor accepts is flagged as under-intervention." |
| 1:10-1:23 | Point to policy version, applied rules, and audit transcript status. | "Each decision is explainable and policy-versioned. Audit transcripts are omitted by default to reduce learner-data exposure." |
| 1:23-1:30 | Show profile and operations controls briefly. | "The hosted reference workflow also demonstrates API-key authentication, encrypted profiles, deletion, and operations counts." |

## Publish Checklist

1. Run `node scripts/build_showcase_assets.mjs`.
2. Inspect the generated screenshots and showcase video.
3. Upload a narrated recording to Loom, YouTube, or LinkedIn when needed.
4. Confirm that the GitHub Pages URL in `README.md` opens the static demo.
5. Open the video and demo links in a private browser window before sharing.

## Accuracy Note

Describe this as a working reference service. Do not claim clinical validation,
regulatory certification, or production readiness for a specific institution.
