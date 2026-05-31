# Security Policy

## Reporting A Vulnerability

Do not open a public issue for suspected vulnerabilities or child-data exposure.
Use the repository's private security-advisory workflow or the private reporting
channel established by your deployment owner.

Include:

- affected version and deployment context;
- reproduction steps;
- whether student data, identifiers, transcripts, or credentials may be exposed;
- any known mitigations.

## Deployment Responsibilities

The SDK is dependency-light and does not persist profiles unless an integrating
application enables the optional encrypted store. The reference service provides
an API-key boundary, encrypted SQLite records, retention pruning, and encryption
rotation primitives. Deployments remain responsible for TLS termination,
identity-provider integration, authorization, secrets-manager integration,
backups, downstream retention enforcement, incident response, and
institution-specific legal review.

## Repository Security Gates

The repository runs CodeQL extended queries and audits pinned hosted-service
dependencies with `pip-audit` on pull requests, changes to `main`, and a weekly
schedule. Dependabot monitors Python, Docker, and GitHub Actions dependencies.
Release owners should review and resolve alerts before publishing or deploying
an image.
