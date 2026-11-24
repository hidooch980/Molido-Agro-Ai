# Security, sync and release readiness

## Implemented in source (not yet production-certified)

- WorkManager periodic sync scheduling (15-minute minimum) and immediate work after local outbox writes.
- HTTPS-only Android sync URL gate; configure Gradle property `SYNC_BASE_URL=https://host.example`.
- Self-hosted FastAPI service under `server/`: account registration/login, scrypt password hashes, signed bearer tokens with a unique `jti`, user-scoped records, idempotent push and monotonic change-log pull cursor.
- Token lifecycle: `POST /v1/auth/logout` revokes the presented token, `POST /v1/auth/refresh` rotates it and retires the old one. Revoked ids are pruned once they expire. Covered by `server/test_auth_hardening.py`.
- Brute-force protection: per-account login lockout with `Retry-After`, plus fixed-window per-IP rate limiting on register/login. Limits are environment-configurable.
- Structured JSON access log (method, path, status, latency only) for every request.
- Offline-sync bridge that projects pushed customers, suppliers and products into the CRM/ERP read models without a second plaintext copy; projection failures never fail the sync batch.
- Android Keystore AES-GCM protection for bearer token, local account ID, outbound outbox payloads and inbound review payloads.
- Server-side AES-256-GCM encryption for record/change-log payloads; the operator must supply and safely back up `MOLIDO_DATA_KEY`.
- One-account-per-local-database binding. A second account is blocked to prevent one device's unpartitioned local records from being exposed to another account.
- Optimistic server version checks, conflict inbox, and explicit user choice to accept server data or re-submit local data against the current server version. Pulled changes for greenhouses, crop cycles, farm activities, inventory items and financial entries are applied to Room when the record has no pending local operation; every applied change keeps its server version for the next `baseVersion`.
- Additive Room migrations through version 7; the instrumentation test exercises the migration chain and the 6→7 business-record step, checking preservation of a legacy observation and outbox row.
- Backend tests cover account isolation, idempotency, stale-version conflicts and change-log pagination.
- Transactional helpers exist for CREATE, UPDATE and DELETE/tombstone outbox operations.

## Still required before production

- Create, edit and delete controls for all five record categories are connected to transactional outbox operations. Delete is represented as a versioned server tombstone.
- Inbound changes for the five farm record types are applied automatically when no local edit is pending; conflicts and CRM/ERP records remain staged for the review panel.
- Main Room business tables remain ordinary Room/SQLite storage. Android Keystore encryption currently protects session material and sync payloads, not the entire local database or every sensitive field. Full database-at-rest encryption and key-loss recovery remain open.
- The backend is source-only and has not been deployed. Docker image build is included in CI. Set a strong unique `MOLIDO_JWT_SECRET`, persistent database path, TLS reverse proxy, firewall, backups and monitoring before connecting devices. Set `MOLIDO_ADMIN_TOKEN` only when account management is needed.
- Account recovery, in-app account switching and a complete write-audit trail are not implemented. Roles (OWNER/OPERATOR/ACCOUNTANT) exist with an admin API, and the rate limiter stores counters in SQLite so several worker processes share one window; a reverse-proxy limiter is still recommended for public deployments.
- `/metrics` exposes process counters and database gauges. Keep it behind the reverse proxy and set `MOLIDO_METRICS_TOKEN` when it must be reachable.
- Android release builds trust only the platform system CA store and never cleartext HTTP (`res/xml/network_security_config.xml`). Debug builds may also trust a user-installed CA for LAN testing; a private CA therefore must not be shipped inside the APK.
- Local database is bound to one account rather than partitioned by ownerId. Account switching requires a reviewed export/reset flow; do not manually delete the database.
- Emulator instrumentation is not a substitute for testing on a physical Android device; see `docs/PHYSICAL_DEVICE_ACCEPTANCE.md`.
- A signed APK is not approved until the configured keystore is validated, apksigner succeeds, signer fingerprint continuity is checked and an upgrade install is tested.

## Deployment/configuration

1. Deploy `server/` behind HTTPS on infrastructure controlled by the project.
2. Configure GitHub Actions variable `SYNC_BASE_URL` or build with `-PSYNC_BASE_URL=https://your-host`.
3. Configure signing secrets in GitHub settings; never paste secret values into chat or commit them.
4. Run backend tests, Android unit tests, emulator instrumentation tests and a physical-device acceptance test.
5. Only then create a version tag and verify the signed release artifact.
