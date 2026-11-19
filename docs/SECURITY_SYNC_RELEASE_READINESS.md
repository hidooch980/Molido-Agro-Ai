# Security, sync and release readiness

## Implemented in source (not yet production-certified)

- WorkManager periodic sync scheduling (15-minute minimum) and immediate work after local outbox writes.
- HTTPS-only Android sync URL gate; configure Gradle property `SYNC_BASE_URL=https://host.example`.
- Self-hosted FastAPI service under `server/`: account registration/login, scrypt password hashes, signed bearer tokens, user-scoped records, idempotent push and monotonic change-log pull cursor.
- Android Keystore AES-GCM protection for bearer token, local account ID, outbound outbox payloads and inbound review payloads.
- One-account-per-local-database binding. A second account is blocked to prevent one device's unpartitioned local records from being exposed to another account.
- Optimistic server version checks, conflict inbox, and explicit user choice to accept server data or re-submit local data against the current server version.
- Additive Room migrations through version 6; Android instrumentation test covers preservation of an existing outbox row through migrations 3->4->5->6.
- Backend tests cover account isolation, idempotency, stale-version conflicts and change-log pagination.
- Transactional helpers exist for CREATE, UPDATE and DELETE/tombstone outbox operations.

## Still required before production

- The current five create forms are connected to the outbox. Edit/delete actions are not yet wired into every screen; do not claim complete CRUD.
- Inbound changes are staged and resolved through the conflict panel for supported record types. They are not silently auto-applied.
- Main Room business tables remain ordinary Room/SQLite storage. Android Keystore encryption currently protects session material and sync payloads, not the entire local database or every sensitive field. Full database-at-rest encryption and key-loss recovery remain open.
- The backend is source-only and has not been deployed. Set a strong unique `MOLIDO_JWT_SECRET`, persistent database path, TLS reverse proxy, firewall, backups and monitoring before connecting devices.
- Backend rate limiting, account recovery, refresh/revocation, audit logs, admin roles and hardened production deployment are not implemented.
- Local database is bound to one account rather than partitioned by ownerId. Account switching requires a reviewed export/reset flow; do not manually delete the database.
- Emulator instrumentation is not a substitute for testing on a physical Android device.
- A signed APK is not approved until the configured keystore is validated, apksigner succeeds, signer fingerprint continuity is checked and an upgrade install is tested.

## Deployment/configuration

1. Deploy `server/` behind HTTPS on infrastructure controlled by the project.
2. Configure GitHub Actions variable `SYNC_BASE_URL` or build with `-PSYNC_BASE_URL=https://your-host`.
3. Configure signing secrets in GitHub settings; never paste secret values into chat or commit them.
4. Run backend tests, Android unit tests, emulator instrumentation tests and a physical-device acceptance test.
5. Only then create a version tag and verify the signed release artifact.
