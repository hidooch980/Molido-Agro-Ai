# Molido BugHunter & AutoFix Agent

## Purpose
An evidence-first quality agent that discovers backend and Android unit-test runners, executes them with bounded timeouts, classifies common failure signatures, and emits JSON plus Markdown reports.

## Automation
- Nightly scheduled diagnostics, pull-request diagnostics, and manual runs.
- Optional Ruff autofixes are disabled by default and limited to Python files under server/.
- Reports are uploaded as workflow artifacts for 30 days.
- Failures are classified as dependency, assertion, migration, Android build, service/network, permissions, or unclassified.

## Safety boundaries
- Read-only GitHub permissions; checkout credentials are not persisted.
- No LLM/API key, paid service, VPS, external database, or external runtime.
- No database/user-data mutation, secrets or signing-key access, tag creation, release, deployment, or merge.
- No speculative rewriting of business logic. Ambiguous, security-sensitive, financial, migration, agricultural-chemical, and data-integrity issues require human review.
- Ruff autofix is opt-in and does not prove semantic correctness.
- Emulator, APK signing, physical-device, LAN/sensor, and production acceptance remain separate gates.

## Limitation
This first version is a deterministic diagnostic agent with a narrowly scoped optional autofixer, not an unrestricted autonomous AI programmer. General semantic bug repair requires contextual reasoning and must be independently tested and reviewed.

## Local execution
Install server/requirements.txt, then run python scripts/bughunter_agent.py.
To opt in to safe Python lint fixes, install Ruff and pass --apply-safe-fixes.

Reports: artifacts/bughunter/bughunter-report.md and bughunter-report.json.
