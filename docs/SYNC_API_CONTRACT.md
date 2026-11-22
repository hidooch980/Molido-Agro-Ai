# Sync API and client worker contract

The Android client runs a unique WorkManager periodic task (15-minute minimum interval) when connected to a network. A one-time worker can be enqueued after local changes. It requires an HTTPS base URL configured at build time and a valid encrypted session token.

## Server endpoints
- `POST /v1/auth/register`, `POST /v1/auth/login`: returns bearer token and userId.
- `POST /v1/sync/push`: accepts a batch of idempotent operations.
- `POST /v1/sync/pull`: returns changes in the authenticated account namespace.

## Important implementation boundary
The current worker pushes queued operations and marks server conflicts. It does not yet apply pulled remote changes to Room or maintain per-record server versions on Android. Therefore it is not yet a complete bidirectional sync release. Do not enable production sync until pull application, version persistence, account switching, and conflict resolution UI are completed and tested.

Set Gradle property `SYNC_BASE_URL=https://your-host.example` for a self-hosted API. Never use HTTP on production devices.
