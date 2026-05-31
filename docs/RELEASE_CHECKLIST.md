# Release Checklist

## Automated Gates

1. Run `python -m pytest tests -v`.
2. Run `python -m compileall -q paga examples tests scripts`.
3. Run the starter benchmark and require accuracy `1.0`.
4. Run `python scripts/export_openapi.py` and confirm `openapi.json` has no diff.
5. Build the wheel and smoke-test an isolated installation.
6. Run `docker compose config`.
7. Run `powershell -ExecutionPolicy Bypass -File scripts/docker_smoke.ps1`.
   This verifies health, readiness, non-root execution, and the packaged
   encrypted-store maintenance check. It also asserts correlated JSON request
   logs without transcript text or API-key leakage.
8. Run `powershell -ExecutionPolicy Bypass -File scripts/generate_sbom.ps1`
   and retain the SPDX JSON file with the release record. Use the institution's
   approved scanner when it differs from Docker SBOM.
9. Run `python -m paga.maintenance check` against a release-like encrypted store.
10. Exercise `python -m paga.maintenance backup --output <approved-path>` and
    verify the snapshot through the institution's restoration procedure.
11. Confirm the latest `Security` workflow is green and review unresolved
    CodeQL, `pip-audit`, and Dependabot alerts.

## Institution Approval Gates

1. Record educator and SLP approval for every deployed policy rule.
2. Run institution-approved multilingual, dialect, accessibility, and cohort
   benchmarks.
3. Validate IdP roles, TLS ingress, secrets-manager wiring, retention settings,
   backup restoration, incident response, LMS credentials, and deployed Ed-Fi
   profile mappings.
4. Capture applicable privacy, legal, security, and accessibility approvals.
