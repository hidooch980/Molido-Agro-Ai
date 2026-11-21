# Molido BugHunter & AutoFix Agent

## Purpose
An evidence-first quality agent that discovers backend and Android unit-test runners, executes them with bounded timeouts, classifies common failure signatures, and emits JSON plus Markdown reports.

## Automation
- Push, pull-request, and manual diagnostics are active on this feature branch. A nightly schedule is configured, but GitHub only runs scheduled workflows from the repository default branch; it will become active only if the workflow is later integrated there.
- On pushes to the dedicated BugHunter branch, Ruff safe autofixes run automatically and are limited to Python files under server/.
- Every autofix is followed by the Backend pytest suite and Android unit tests; if a check fails, changed Python files are restored from the pre-fix snapshot.
- The diagnostic job has read-only repository permission and does not expose a write token to test code. It exports a patch artifact only after all checks pass and only for Ruff-changed server/*.py files.
- A separate, isolated commit job receives write permission, verifies the report and exact source SHA, applies the patch, rechecks staged paths, and pushes a bot commit only when all gates pass. Bot commits do not trigger another workflow run.
- Manual workflow runs retain an explicit opt-in input; pull-request diagnostics run against foundation/android-release-foundation.
- Reports are uploaded as workflow artifacts for 30 days.
- Failures are classified as dependency, assertion, migration, Android build, service/network, permissions, or unclassified.

## Safety boundaries
- Only the isolated commit job has repository contents write permission, and it can push verified Ruff changes only to the dedicated feature/bughunter-autofix-agent branch. The diagnostic/test job has read-only permission. Neither job can merge pull requests or write releases.
- No LLM/API key, paid service, VPS, external database, or external runtime.
- No database/user-data mutation, secrets or signing-key access, tag creation, release, deployment, or merge.
- No speculative rewriting of business logic. Ambiguous, security-sensitive, financial, migration, agricultural-chemical, and data-integrity issues require human review.
- Ruff autofix is restricted to mechanical lint fixes in server/*.py; tests are mandatory and failed changes are rolled back. Passing tests do not prove full semantic correctness.
- Emulator, APK signing, physical-device, LAN/sensor, and production acceptance remain separate gates.

## Limitation
This first version is a deterministic diagnostic agent with a narrowly scoped optional autofixer, not an unrestricted autonomous AI programmer. General semantic bug repair requires contextual reasoning and must be independently tested and reviewed.

## Local execution
Install server/requirements.txt, then run python scripts/bughunter_agent.py.
To opt in to safe Python lint fixes locally, install Ruff and pass --apply-safe-fixes. In CI, pushes to the dedicated BugHunter branch enable the bounded fixer automatically.

Reports: artifacts/bughunter/bughunter-report.md and bughunter-report.json.
