# Molido Agro Sync API

Self-hostable FastAPI service for account-scoped sync. It uses SQLite, scrypt password hashing, signed bearer tokens and per-user record namespaces.

## Run
Set a unique random `MOLIDO_JWT_SECRET` of at least 32 characters, a URL-safe Base64 `MOLIDO_DATA_KEY` encoding exactly 32 random bytes, and a persistent `MOLIDO_DB_PATH`, then:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8080
```

Put the service behind a TLS reverse proxy before exposing it publicly. Do not use the development secret. Back up the SQLite database and protect the host filesystem.

## API
- `POST /v1/auth/register` and `POST /v1/auth/login`
- `POST /v1/sync/push`: idempotent batch, optimistic baseVersion check
- `POST /v1/sync/pull`: changes scoped to the authenticated account

Record and change-log payloads are encrypted at rest with AES-256-GCM using `MOLIDO_DATA_KEY`. Back up this key separately; losing it makes encrypted records unrecoverable. The server never accepts a userId in record operations; identity comes only from the verified bearer token. A stale baseVersion returns `conflict`, never silently overwrites newer data.

## Current limits
This is an initial single-node API, not a hardened public multi-tenant deployment. Add rate limiting, email/account recovery, token revocation/rotation, audit logging, TLS, database backup/restore drills and operational monitoring before production.
