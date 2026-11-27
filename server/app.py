from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, sqlite3, threading, time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("MOLIDO_DB_PATH", "molido-server.sqlite3"))
JWT_SECRET = os.environ.get("MOLIDO_JWT_SECRET", "")
TOKEN_TTL = int(os.environ.get("MOLIDO_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 14)))

# Brute-force and abuse limits. Every value is overridable so deployments and the
# test-suite can tune them without code changes.
MAX_LOGIN_FAILURES = int(os.environ.get("MOLIDO_MAX_LOGIN_FAILURES", "5"))
LOCKOUT_SECONDS = int(os.environ.get("MOLIDO_LOGIN_LOCKOUT_SECONDS", "900"))
AUTH_RATE_LIMIT = int(os.environ.get("MOLIDO_AUTH_RATE_LIMIT", "60"))
LOGIN_RATE_LIMIT = int(os.environ.get("MOLIDO_LOGIN_RATE_LIMIT", "20"))
AUTH_RATE_WINDOW = int(os.environ.get("MOLIDO_AUTH_RATE_WINDOW_SECONDS", "60"))
# Only trust X-Forwarded-For when the service is reachable solely through the
# reverse proxy; otherwise a client could spoof its address and dodge the limiter.
TRUST_PROXY_HEADERS = os.environ.get("MOLIDO_TRUST_PROXY_HEADERS", "0").strip() == "1"
# A 100-operation push with small records is far below this; the cap only stops abuse.
MAX_REQUEST_BYTES = int(os.environ.get("MOLIDO_MAX_REQUEST_BYTES", str(1024 * 1024)))
# Owner manages accounts, operators record farm and inventory work, accountants approve
# financial postings. Only the two approver roles may confirm ledgers and cost entries.
ROLES = ("OWNER", "OPERATOR", "ACCOUNTANT")
APPROVER_ROLES = ("OWNER", "ACCOUNTANT")
ADMIN_TOKEN = os.environ.get("MOLIDO_ADMIN_TOKEN", "")
# Self-registration hands out the OWNER role, which is right for a LAN install whose first user
# owns the farm and wrong for anything reachable from the internet; such a deployment sets this
# to 0 and creates accounts through the admin API instead.
ALLOW_REGISTRATION = os.environ.get("MOLIDO_ALLOW_REGISTRATION", "1").strip() == "1"
# Scheduled SQLite copies are the only protection against a lost volume or a bad migration; they
# stay off until a directory is configured so a local test run never writes files.
BACKUP_DIR = os.environ.get("MOLIDO_BACKUP_DIR", "")
BACKUP_INTERVAL = int(os.environ.get("MOLIDO_BACKUP_INTERVAL_SECONDS", str(24 * 60 * 60)))
BACKUP_KEEP = int(os.environ.get("MOLIDO_BACKUP_KEEP", "14"))
METRICS_TOKEN = os.environ.get("MOLIDO_METRICS_TOKEN", "")
STARTED_AT = time.time()
METRICS: dict[str, int] = {}

def metric(name: str, amount: int = 1) -> None:
    """Increment an in-process counter exposed by GET /metrics."""
    METRICS[name] = METRICS.get(name, 0) + amount
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def data_key() -> bytes:
    raw = os.environ.get("MOLIDO_DATA_KEY", "")
    try: key = base64.urlsafe_b64decode(raw + "=" * ((4 - len(raw) % 4) % 4))
    except Exception: key = b""
    if len(key) != 32: raise HTTPException(503, "Server data encryption is not configured")
    return key

def encrypt_payload(value: dict[str, Any]) -> str:
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(data_key()).encrypt(nonce, json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode(), None)
    return b64(nonce + encrypted)

def decrypt_payload(value: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))
    plain = AESGCM(data_key()).decrypt(raw[:12], raw[12:], None)
    return json.loads(plain)
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Defined further down; resolved when the server actually starts, not at import time.
    start_backup_thread()
    yield

app = FastAPI(title="Molido Agro Sync API", version="1.0.0", lifespan=_lifespan)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@app.middleware("http")
async def access_log(request: Request, call_next):
    """Structured access log plus a coarse body-size guard."""
    started = time.perf_counter()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
        metric("request_too_large")
        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
    else:
        response = await call_next(request)
    metric("http_requests")
    metric(f"http_status_{response.status_code}")
    print(json.dumps({
        "ts": int(time.time()),
        "event": "http_request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "durationMs": round((time.perf_counter() - started) * 1000, 1),
    }, ensure_ascii=False), flush=True)
    return response

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS records(user_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,entity_type,entity_id), FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS operations(user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, result TEXT NOT NULL, created_at INTEGER NOT NULL, request_hash TEXT NOT NULL DEFAULT '', PRIMARY KEY(user_id,idempotency_key), FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS change_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS revoked_tokens(jti TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS login_failures(username TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limits(bucket_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, count INTEGER NOT NULL);
        """)
        operation_columns = {row["name"] for row in c.execute("PRAGMA table_info(operations)").fetchall()}
        if "request_hash" not in operation_columns:
            c.execute("ALTER TABLE operations ADD COLUMN request_hash TEXT NOT NULL DEFAULT ''")
        user_columns = {row["name"] for row in c.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in user_columns:
            c.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'OWNER'")
init_db()

def backup_database(stamp: float | None = None) -> Path:
    """Copy the live database with SQLite's online backup API and drop old copies.

    Copying the file itself would race with writers, so the connection-level backup is used: it
    takes a consistent snapshot while other requests keep serving.
    """
    if not BACKUP_DIR:
        raise HTTPException(503, "Backups are not configured")
    directory = Path(BACKUP_DIR)
    moment = time.strftime("%Y%m%d-%H%M%S", time.gmtime(time.time() if stamp is None else stamp))
    target = directory / f"molido-{moment}.sqlite3"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(DB_PATH)
        try:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except (OSError, sqlite3.Error) as error:
        # Usually a mounted directory owned by another user; say so instead of a stack trace.
        raise HTTPException(503, f"Backup directory is not writable: {target.parent}") from error
    rotate_backups(directory)
    metric("backup_created")
    return target

def rotate_backups(directory: Path) -> None:
    """Keep the newest BACKUP_KEEP copies so an unattended server cannot fill its disk."""
    if BACKUP_KEEP <= 0:
        return
    copies = sorted(directory.glob("molido-*.sqlite3"))
    for stale in copies[:-BACKUP_KEEP] if len(copies) > BACKUP_KEEP else []:
        try:
            stale.unlink()
        except OSError:
            pass

def backup_loop() -> None:
    while True:
        time.sleep(max(1, BACKUP_INTERVAL))
        try:
            backup_database()
        except Exception:
            # A failed backup must never take the API down; the next tick retries.
            pass

_BACKUP_THREAD: threading.Thread | None = None

def start_backup_thread() -> None:
    global _BACKUP_THREAD
    if not BACKUP_DIR or BACKUP_INTERVAL <= 0:
        return
    if _BACKUP_THREAD is not None and _BACKUP_THREAD.is_alive():
        return
    _BACKUP_THREAD = threading.Thread(target=backup_loop, name="molido-backup", daemon=True)
    _BACKUP_THREAD.start()

def b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).decode().rstrip("=")
def password_hash(password: str, salt: bytes) -> bytes: return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
def ensure_auth_configured() -> None:
    if len(JWT_SECRET) < 32:
        raise HTTPException(503, "Server authentication is not configured")

def token_for(user_id: str) -> str:
    """Issue a signed access token with a unique id so it can be revoked."""
    ensure_auth_configured()
    now = int(time.time())
    head = b64(b'{"alg":"HS256","typ":"JWT"}')
    body = b64(json.dumps({"sub":user_id,"iat":now,"exp":now+TOKEN_TTL,"jti":secrets.token_hex(16)}).encode())
    signature = b64(hmac.new(JWT_SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{signature}"

def decode_token(authorization: str | None) -> dict[str, Any]:
    """Verify signature and expiry, then return the claims."""
    ensure_auth_configured()
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Authentication required")
    parts=authorization[7:].split(".")
    if len(parts)!=3: raise HTTPException(401,"Invalid token")
    expected=b64(hmac.new(JWT_SECRET.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected,parts[2]): raise HTTPException(401,"Invalid token")
    try:
        payload=json.loads(base64.urlsafe_b64decode(parts[1]+"="*((4-len(parts[1])%4)%4)))
        if payload["exp"] < int(time.time()): raise ValueError()
        if not payload.get("sub"): raise ValueError()
    except Exception: raise HTTPException(401,"Expired or invalid token")
    return payload

def revoke_token(claims: dict[str, Any]) -> bool:
    """Record a token id as revoked. Returns False for legacy tokens without a jti."""
    jti = claims.get("jti")
    if not jti: return False
    with db() as c:
        c.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (int(time.time()),))
        c.execute("INSERT OR REPLACE INTO revoked_tokens(jti,user_id,expires_at) VALUES(?,?,?)",
                  (str(jti), str(claims.get("sub", "")), int(claims.get("exp", 0))))
    return True

def current_user(authorization: str | None) -> str:
    claims = decode_token(authorization)
    jti = claims.get("jti")
    if jti:
        with db() as c:
            revoked = c.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (str(jti),)).fetchone()
        if revoked: raise HTTPException(401,"Token has been revoked")
    return str(claims["sub"])

class Credentials(BaseModel):
    username: str = Field(min_length=3,max_length=64,pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12,max_length=256)
class Operation(BaseModel):
    idempotencyKey: str = Field(min_length=1,max_length=200)
    entityType: Literal["greenhouse", "crop_cycle", "farm_activity", "inventory_item", "financial_entry", "customer", "supplier", "product", "sales_order", "purchase_order", "inventory_movement", "crm_activity", "crm_lead", "crm_followup", "support_ticket", "inventory_reservation", "harvest", "harvest_batch", "journal_entry", "settlement"]
    entityId: str = Field(min_length=1,max_length=200)
    operation: str = Field(pattern=r"^(CREATE|UPDATE|DELETE)$")
    payload: dict[str,Any] = Field(default_factory=dict)
    baseVersion: int = Field(default=0,ge=0)
class PushBody(BaseModel):
    operations: list[Operation] = Field(max_length=100)
class PullBody(BaseModel):
    cursor: int = Field(default=0,ge=0)
    limit: int = Field(default=100,ge=1,le=500)

@app.get("/health")
def health(): return {"status":"ok","service":"molido-agro-sync"}

def client_ip(request: Request) -> str:
    """Client address used for rate limiting, honouring X-Forwarded-For only when configured."""
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first: return first
    return request.client.host if request.client else "unknown"

def enforce_rate_limit(request: Request, bucket: str, limit: int) -> None:
    """Fixed-window limiter shared through the database, so every worker process agrees."""
    if limit <= 0: return
    now = int(time.time())
    window = max(1, AUTH_RATE_WINDOW)
    window_start = now - (now % window)
    key = f"{bucket}:{client_ip(request)}"
    with db() as c:
        row = c.execute(
            """INSERT INTO rate_limits(bucket_key,window_start,count) VALUES(?,?,1)
               ON CONFLICT(bucket_key) DO UPDATE SET
                 count = CASE WHEN window_start = excluded.window_start THEN count + 1 ELSE 1 END,
                 window_start = excluded.window_start
               RETURNING count""",
            (key, window_start),
        ).fetchone()
        count = int(row[0])
        if count == 1:
            c.execute("DELETE FROM rate_limits WHERE window_start < ?", (window_start - 3600,))
    if count > limit:
        retry_after = max(1, window_start + window - now)
        raise HTTPException(429, "Too many requests; try again shortly", headers={"Retry-After": str(retry_after)})

@app.post("/v1/auth/register")
def register(body: Credentials, request: Request):
    ensure_auth_configured()
    if not ALLOW_REGISTRATION:
        raise HTTPException(403, "Self-registration is disabled; ask an administrator for an account")
    enforce_rate_limit(request, "register", AUTH_RATE_LIMIT)
    salt=secrets.token_bytes(16); uid=secrets.token_hex(16)
    try:
        with db() as c:
            c.execute("INSERT INTO users(id,username,salt,password_hash,created_at,role) VALUES(?,?,?,?,?,?)",
                      (uid,body.username,salt,password_hash(body.password,salt),int(time.time()),"OWNER"))
    except sqlite3.IntegrityError: raise HTTPException(409,"Username already exists")
    metric("auth_register")
    return {"accessToken":token_for(uid),"tokenType":"Bearer","expiresIn":TOKEN_TTL,"userId":uid}

@app.post("/v1/auth/login")
def login(body: Credentials, request: Request):
    ensure_auth_configured()
    enforce_rate_limit(request, "login", LOGIN_RATE_LIMIT)
    now = int(time.time())
    failure: HTTPException | None = None
    user_row = None
    with db() as c:
        state = c.execute("SELECT failures,locked_until FROM login_failures WHERE username=?", (body.username,)).fetchone()
        locked_until = int(state["locked_until"]) if state else 0
        if locked_until > now:
            raise HTTPException(429, "Account temporarily locked after repeated failed sign-in attempts",
                                headers={"Retry-After": str(locked_until - now)})
        user = c.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        if user and hmac.compare_digest(password_hash(body.password, user["salt"]), user["password_hash"]):
            c.execute("DELETE FROM login_failures WHERE username=?", (body.username,))
            user_row = user
            metric("auth_login_ok")
        else:
            c.execute("DELETE FROM login_failures WHERE (locked_until > 0 AND locked_until < ?) OR updated_at < ?",
                      (now, now - 86_400))
            previous = int(state["failures"]) if state and locked_until == 0 else 0
            failures = previous + 1
            lock_until = now + LOCKOUT_SECONDS if failures >= MAX_LOGIN_FAILURES else 0
            c.execute(
                """INSERT INTO login_failures(username,failures,locked_until,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,
                   locked_until=excluded.locked_until, updated_at=excluded.updated_at""",
                (body.username, failures, lock_until, now),
            )
            metric("auth_login_failed")
            if lock_until: metric("auth_lockout")
            failure = (HTTPException(429, "Account temporarily locked after repeated failed sign-in attempts",
                                     headers={"Retry-After": str(LOCKOUT_SECONDS)})
                       if lock_until else HTTPException(401, "Invalid credentials"))
    if failure: raise failure
    assert user_row is not None
    return {"accessToken":token_for(user_row["id"]),"tokenType":"Bearer","expiresIn":TOKEN_TTL,"userId":user_row["id"]}

@app.post("/v1/auth/refresh")
def refresh(authorization: str | None = Header(default=None)):
    """Rotate the current access token: the presented token is revoked immediately."""
    uid = current_user(authorization)
    revoke_token(decode_token(authorization))
    metric("auth_refresh")
    return {"accessToken":token_for(uid),"tokenType":"Bearer","expiresIn":TOKEN_TTL,"userId":uid}

@app.post("/v1/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    """Revoke the presented token so a copied token cannot be replayed."""
    metric("auth_logout")
    return {"revoked": revoke_token(decode_token(authorization))}

@app.get("/v1/auth/me")
def me(authorization: str | None = Header(default=None)):
    """Describe the signed-in account, including the role that gates approvals."""
    uid = current_user(authorization)
    with db() as c:
        row = c.execute("SELECT id,username,role,created_at FROM users WHERE id=?", (uid,)).fetchone()
    if row is None: raise HTTPException(401, "Account no longer exists")
    return {"userId": row["id"], "username": row["username"], "role": row["role"], "createdAt": row["created_at"]}

def require_admin(token: str | None) -> None:
    if not ADMIN_TOKEN: raise HTTPException(503, "Admin API is not configured")
    if not token or not hmac.compare_digest(ADMIN_TOKEN, token): raise HTTPException(403, "Admin authorization failed")

class CreateUser(Credentials):
    role: Literal["OWNER", "OPERATOR", "ACCOUNTANT"] = "OPERATOR"
class RoleUpdate(BaseModel):
    role: Literal["OWNER", "OPERATOR", "ACCOUNTANT"]

@app.get("/v1/admin/users")
def admin_list_users(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    with db() as c:
        rows = c.execute("SELECT id,username,role,created_at FROM users ORDER BY created_at").fetchall()
    return {"users": [{"userId": r["id"], "username": r["username"], "role": r["role"], "createdAt": r["created_at"]} for r in rows]}

@app.post("/v1/admin/users")
def admin_create_user(body: CreateUser, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    salt = secrets.token_bytes(16); uid = secrets.token_hex(16)
    try:
        with db() as c:
            c.execute("INSERT INTO users(id,username,salt,password_hash,created_at,role) VALUES(?,?,?,?,?,?)",
                      (uid, body.username, salt, password_hash(body.password, salt), int(time.time()), body.role))
    except sqlite3.IntegrityError: raise HTTPException(409, "Username already exists")
    metric("admin_user_created")
    return {"userId": uid, "username": body.username, "role": body.role}

@app.patch("/v1/admin/users/{username}")
def admin_set_role(username: str, body: RoleUpdate, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    with db() as c:
        changed = c.execute("UPDATE users SET role=? WHERE username=?", (body.role, username)).rowcount
    if not changed: raise HTTPException(404, "Account not found")
    metric("admin_role_changed")
    return {"username": username, "role": body.role}

@app.post("/v1/admin/backup")
def admin_backup(x_admin_token: str | None = Header(default=None)):
    """Take an on-demand consistent copy, e.g. before an upgrade, and report where it went."""
    require_admin(x_admin_token)
    path = backup_database()
    return {"file": path.name, "bytes": path.stat().st_size}

@app.get("/metrics")
def metrics_snapshot(authorization: str | None = Header(default=None)):
    """Counters plus a few database gauges; keep behind the proxy and optionally behind a token."""
    if METRICS_TOKEN and (not authorization or not hmac.compare_digest(authorization, f"Bearer {METRICS_TOKEN}")):
        raise HTTPException(401, "Metrics authorization required")
    with db() as c:
        accounts = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        records = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        change_log = c.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    return {"service": "molido-agro-sync", "uptimeSeconds": int(time.time() - STARTED_AT),
            "accounts": accounts, "records": records, "changeLog": change_log,
            "counters": dict(sorted(METRICS.items()))}

@app.post("/v1/sync/push")
def push(body: PushBody, authorization: str | None = Header(default=None)):
    uid=current_user(authorization); results=[]; metric("sync_push_requests")
    with db() as c:
        for op in body.operations:
            request_payload = {
                "entityType": op.entityType,
                "entityId": op.entityId,
                "operation": op.operation,
                "payload": op.payload,
                "baseVersion": op.baseVersion,
            }
            request_hash = hashlib.sha256(
                json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            old=c.execute("SELECT result,request_hash FROM operations WHERE user_id=? AND idempotency_key=?",(uid,op.idempotencyKey)).fetchone()
            if old:
                if old["request_hash"] and not hmac.compare_digest(old["request_hash"], request_hash):
                    results.append({
                        "idempotencyKey": op.idempotencyKey,
                        "status": "conflict",
                        "reason": "Idempotency key reused with a different request",
                    })
                else:
                    results.append(json.loads(old["result"]))
                continue
            current=c.execute("SELECT version FROM records WHERE user_id=? AND entity_type=? AND entity_id=?",(uid,op.entityType,op.entityId)).fetchone()
            version=current["version"] if current else 0
            if version != op.baseVersion:
                result={"idempotencyKey":op.idempotencyKey,"status":"conflict","serverVersion":version}
                metric("sync_push_conflict")
            else:
                next_version=version+1
                payload=encrypt_payload(op.payload)
                updated_at = int(time.time() * 1000)
                deleted = 1 if op.operation == "DELETE" else 0
                c.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,entity_type,entity_id) DO UPDATE SET payload=excluded.payload,version=excluded.version,updated_at=excluded.updated_at,deleted=excluded.deleted",(uid,op.entityType,op.entityId,payload,next_version,updated_at,deleted))
                c.execute("INSERT INTO change_log(user_id,entity_type,entity_id,payload,version,updated_at,deleted) VALUES(?,?,?,?,?,?,?)",(uid,op.entityType,op.entityId,payload,next_version,updated_at,deleted))
                result={"idempotencyKey":op.idempotencyKey,"status":"applied","serverVersion":next_version}
                metric("sync_push_applied")
                try:
                    bridge_status = materialize_record(c, uid, op.entityType, op.entityId, payload, op.payload, updated_at, bool(deleted))
                    if bridge_status.startswith("skipped"):
                        print(json.dumps({"event":"sync_bridge_skipped","entityType":op.entityType,
                                          "entityId":op.entityId,"reason":bridge_status}, ensure_ascii=False), flush=True)
                except Exception as exc:
                    # The bridge must never break the sync contract; report and continue.
                    print(json.dumps({"event":"sync_bridge_failed","entityType":op.entityType,
                                      "entityId":op.entityId,"error":type(exc).__name__}, ensure_ascii=False), flush=True)
            c.execute("INSERT INTO operations(user_id,idempotency_key,result,created_at,request_hash) VALUES(?,?,?,?,?)",(uid,op.idempotencyKey,json.dumps(result),int(time.time()),request_hash))
            results.append(result)
    return {"results":results}

@app.post("/v1/sync/pull")
def pull(body: PullBody, authorization: str | None = Header(default=None)):
    uid=current_user(authorization)
    with db() as c:
        rows=c.execute("SELECT id,entity_type,entity_id,payload,version,updated_at,deleted FROM change_log WHERE user_id=? AND id>? ORDER BY id LIMIT ?",(uid,body.cursor,body.limit)).fetchall()
    changes=[{"cursorId":r["id"],"entityType":r["entity_type"],"entityId":r["entity_id"],"payload":decrypt_payload(r["payload"]),"version":r["version"],"updatedAt":r["updated_at"],"deleted":bool(r["deleted"])} for r in rows]
    cursor=max([body.cursor]+[r["id"] for r in rows])
    return {"changes":changes,"cursor":cursor}

# Offline-sync records are mirrored into the CRM/ERP read models by a narrow bridge.
from sync_materializer import materialize_record

# Sensor endpoints are kept in a separate module to isolate the greenhouse telemetry API.
from sensor_api import register_sensor_routes
register_sensor_routes(app, db, current_user, encrypt_payload, decrypt_payload)

# CRM and ERP APIs share the same account identity, encrypted payload storage and audit boundary.
from business_api import register_business_routes
register_business_routes(app, db, current_user, encrypt_payload, decrypt_payload)


# CRM pipeline, order lifecycle, double-entry journal and greenhouse harvest integration.
from business_workflows import register_business_workflow_routes
register_business_workflow_routes(app, db, current_user, encrypt_payload, decrypt_payload)



from business_settlements import register_settlement_routes
register_settlement_routes(app, db, current_user, encrypt_payload)


from business_approval_ledger import register_approval_ledger_routes
register_approval_ledger_routes(app, db, current_user, encrypt_payload, decrypt_payload)


from advanced_inventory import register_advanced_inventory_routes
register_advanced_inventory_routes(app, db, current_user)


from production_costing import register_production_costing_routes
register_production_costing_routes(app, db, current_user, decrypt_payload)


from advanced_inventory_controls import register_advanced_inventory_control_routes
register_advanced_inventory_control_routes(app, db, current_user, decrypt_payload, encrypt_payload)

from ai_diagnostics_api import register_ai_diagnostics_routes
register_ai_diagnostics_routes(app, db, current_user, decrypt_payload)
