# Sync API and client worker contract

The Android client runs a unique WorkManager periodic task (15-minute minimum interval) when connected to a network. A one-time worker can be enqueued after local changes. It requires an HTTPS base URL configured at build time and a valid encrypted session token.

## Authentication endpoints
- `POST /v1/auth/register` — creates an account. Body: `{username, password}` (password 12–256 characters). Returns `accessToken`, `tokenType`, `expiresIn`, `userId`.
- `POST /v1/auth/login` — returns the same payload. Repeated failures are throttled (see below).
- `POST /v1/auth/refresh` — exchanges a valid token for a new one; the presented token is revoked immediately (rotation, not sliding expiry).
- `POST /v1/auth/logout` — revokes the presented token. Returns `{revoked: true}`.

Every token carries a unique id (`jti`). Revoked ids are stored in `revoked_tokens` until their expiry, so a copied token stops working as soon as the device logs out or refreshes. Tokens issued by an older server build (without `jti`) still validate until they expire; they simply cannot be revoked individually.

## Sync endpoints
- `POST /v1/sync/push` — accepts a batch of up to 100 idempotent operations (`CREATE`/`UPDATE`/`DELETE`, `baseVersion`, encrypted `payload`). Each result is `applied`, `conflict` or a per-operation error.
- `POST /v1/sync/pull` — returns changes in the authenticated account namespace after `cursor`, capped by `limit` (max 100) with a cursor for the next call.

`DELETE` is stored as a versioned tombstone in `records`/`change_log`; the record stays visible to pull so other devices learn about the deletion.

## CRM/ERP projection
Customers, suppliers and products pushed through `/v1/sync/push` are mirrored into `business_parties` and `business_products` (see `server/sync_materializer.py`), so a record captured offline on a phone appears in `GET /v1/crm/customers`, `GET /v1/erp/suppliers` and `GET /v1/erp/products`.

Projection rules:
- The encrypted payload is copied verbatim; no second copy of plaintext is stored.
- A duplicate SKU never fails the push. The record is stored, the projection is skipped and an `sync_bridge_skipped` line is logged.
- Any other projection error is logged as `sync_bridge_failed` and never rolls back the sync operation.
- Other entity types (harvest, orders, tickets, …) remain in the generic record store; their dedicated APIs are separate write paths.

## Abuse limits
- Login lockout: after `MOLIDO_MAX_LOGIN_FAILURES` (default 5) failed attempts the account is locked for `MOLIDO_LOGIN_LOCKOUT_SECONDS` (default 900) and answers `429` with `Retry-After`. A successful login clears the counter.
- Fixed-window rate limiting per client IP: `/v1/auth/register` at `MOLIDO_AUTH_RATE_LIMIT` (default 60/min) and `/v1/auth/login` at `MOLIDO_LOGIN_RATE_LIMIT` (default 20/min). Limits apply per server process; put a shared limiter (reverse proxy or Redis) in front when running multiple workers.
- Limits are best-effort protection, not the only control: keep the API behind a TLS reverse proxy and never expose it directly to the internet.

## Observability
Every request emits one JSON line on stdout: `ts`, `event: "http_request"`, `method`, `path`, `status`, `durationMs`. No payloads, tokens or usernames are logged. Collect the container logs with the platform of your choice.

## Important implementation boundary
The Android worker now sends up to 50 operations per request (byte-budgeted below the server body cap) and applies pulled changes directly to Room when no local operation is pending: `greenhouse`, `crop_cycle`, `farm_activity`, `inventory_item` and `financial_entry` map to their own tables, every other entity type is stored as a generic business record carrying its original payload. Each applied change keeps its `serverVersion` in the inbox row, and the next local update uses that version as `baseVersion`. Pending local work still becomes a `CONFLICT` for the review screen, and unsupported entity types stay `PENDING_REVIEW`. Account switching and a full conflict review UI are still missing, so multi-device sync should remain opt-in until the Android instrumentation tests run in CI.

Set Gradle property `SYNC_BASE_URL=https://your-host.example` for a self-hosted API. Never use HTTP on production devices. Release builds trust only the system CA store; debug builds can additionally trust a user-installed LAN CA (see `docs/LAN_DEPLOYMENT_AND_RECOVERY.md`).
