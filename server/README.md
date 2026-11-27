# Molido Agro Sync API

Self-hostable FastAPI service for account-scoped sync and CRM/ERP. It uses SQLite, scrypt password hashing, signed bearer tokens and per-user record namespaces.

## Run
Set a unique random `MOLIDO_JWT_SECRET` of at least 32 characters, a URL-safe Base64 `MOLIDO_DATA_KEY` encoding exactly 32 random bytes, and a persistent `MOLIDO_DB_PATH`, then:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8080
```

Or run the whole service with one command from the repository root: `cp .env.example .env`, fill the two secrets, then `docker compose up -d --build`. The container listens on port 8080 and keeps the database in the `molido-data` volume.

Set `MOLIDO_BACKUP_DIR` to have the service copy the database on a schedule (`MOLIDO_BACKUP_INTERVAL_SECONDS`, keeping `MOLIDO_BACKUP_KEEP` copies) and call `POST /v1/admin/backup` with `X-Admin-Token` for an on-demand copy before an upgrade.

Put the service behind a TLS reverse proxy before exposing it publicly. Do not use the development secret. Back up the SQLite database and protect the host filesystem.

## API
- `POST /v1/auth/register`, `POST /v1/auth/login`: returns bearer token and userId.
- `POST /v1/auth/refresh`: rotates the token; the old token is revoked immediately.
- `POST /v1/auth/logout`: revokes the presented token.
- `GET /v1/auth/me`: returns the account name and its role (`OWNER`, `OPERATOR`, `ACCOUNTANT`).
- `GET /v1/admin/users`, `POST /v1/admin/users`, `PATCH /v1/admin/users/{username}`: account management, enabled only when `MOLIDO_ADMIN_TOKEN` is set (sent as `X-Admin-Token`).
- `GET /metrics`: counters and database gauges; returns `401` when `MOLIDO_METRICS_TOKEN` is set and the bearer token does not match.
- `POST /v1/sync/push`: idempotent batch (max 100 operations), optimistic `baseVersion` check.
- `POST /v1/sync/pull`: changes scoped to the authenticated account.
- `GET /v1/crm/*`, `GET /v1/erp/*`, `POST /v1/erp/*`: account-scoped CRM/ERP read and write models.
- `GET /health`: liveness probe.

Record and change-log payloads are encrypted at rest with AES-256-GCM using `MOLIDO_DATA_KEY`. Back up this key separately; losing it makes encrypted records unrecoverable. The server never accepts a userId in record operations; identity comes only from the verified bearer token. A stale baseVersion returns `conflict`, never silently overwrites newer data.

### Sync to CRM/ERP projection
`server/sync_materializer.py` mirrors pushed `customer`, `supplier` and `product` records into `business_parties` / `business_products` so offline captures appear in the CRM/ERP APIs. The encrypted payload is copied verbatim. A duplicate SKU skips only the projection (logged as `sync_bridge_skipped`) and never fails the push; any other projection error is logged as `sync_bridge_failed`. The generic record store stays the source of truth for sync.

### Roles
Registration creates an `OWNER` account. The admin API can create `OPERATOR` accounts and promote them to `ACCOUNTANT`. Approval endpoints (ledger journals, cost entries, inventory quality/returns/scrap/cycle-counts) additionally require an approver role, so an operator can record work but cannot post financial movements even when holding the service approval token.

### Tokens and abuse limits
Every token carries a unique `jti`. `logout` and `refresh` write the id to `revoked_tokens` until it expires, so a copied token cannot be replayed.

| Variable | Default | Meaning |
|---|---|---|
| `MOLIDO_TOKEN_TTL_SECONDS` | `1209600` (14 days) | Token lifetime (`TOKEN_TTL` is built from this) |
| `MOLIDO_MAX_LOGIN_FAILURES` | `5` | Failed logins before the account is locked |
| `MOLIDO_LOGIN_LOCKOUT_SECONDS` | `900` | Lock duration; responses carry `Retry-After` |
| `MOLIDO_AUTH_RATE_LIMIT` | `60` | Requests per minute per IP on `/v1/auth/register` (0 disables) |
| `MOLIDO_LOGIN_RATE_LIMIT` | `20` | Requests per minute per IP on `/v1/auth/login` (0 disables) |
| `MOLIDO_AUTH_RATE_WINDOW_SECONDS` | `60` | Fixed window for both limits |
| `MOLIDO_ADMIN_TOKEN` | unset | Enables `/v1/admin/users`; unset returns `503` |
| `MOLIDO_METRICS_TOKEN` | unset | When set, `/metrics` requires `Authorization: Bearer <token>` |
| `MOLIDO_TRUST_PROXY_HEADERS` | `0` | Set to `1` only when the service is reachable solely through the reverse proxy, so `X-Forwarded-For` is trusted for rate limiting |
| `MOLIDO_MAX_REQUEST_BYTES` | `1048576` | Requests with a larger declared body get `413` |

Rate-limit counters live in the shared rate_limits table of the SQLite database, so every worker process enforces the same fixed window, and the table is pruned as windows roll over. Failed-attempt and revocation records also survive restarts.

Every request writes one JSON access-log line to stdout: `ts`, `event`, `method`, `path`, `status`, `durationMs`. Payloads, tokens and usernames are never logged.

## Tests
```sh
python -m pytest server -q
```
`server/conftest.py` raises the abuse limits for the suite (a single test client would otherwise trip them); `test_auth_hardening.py`, `test_roles_and_metrics.py` and `test_request_guards.py` exercise the real limits, roles and request guards by patching them per test.

## Current limits
This is an initial single-node API, not a hardened public multi-tenant deployment. Account recovery, admin roles, a complete write-audit trail, a shared multi-worker rate limiter, TLS, database backup/restore drills and operational monitoring are still required before production.

## Container deployment

Copy `.env.example` to `.env`, generate independent random secrets for `MOLIDO_JWT_SECRET` and `MOLIDO_DATA_KEY`, and keep the populated file outside source control. Then run:

```sh
docker compose -f compose.yaml up -d --build
```

The service binds to loopback port 8080. Put a TLS reverse proxy in front of it; do not expose port 8080 directly to the public internet. Persist and back up both the SQLite volume and the data-encryption key.
