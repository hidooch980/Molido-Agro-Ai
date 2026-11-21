from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, sqlite3, time
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("MOLIDO_DB_PATH", "molido-server.sqlite3"))
JWT_SECRET = os.environ.get("MOLIDO_JWT_SECRET", "")
TOKEN_TTL = 60 * 60 * 24 * 14
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
app = FastAPI(title="Molido Agro Sync API", version="1.0.0")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS records(user_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,entity_type,entity_id), FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS operations(user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, result TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(user_id,idempotency_key), FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS change_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
        """)
init_db()

def b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).decode().rstrip("=")
def password_hash(password: str, salt: bytes) -> bytes: return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
def ensure_auth_configured() -> None:
    if len(JWT_SECRET) < 32:
        raise HTTPException(503, "Server authentication is not configured")

def token_for(user_id: str) -> str:
    ensure_auth_configured()
    now = int(time.time())
    head = b64(b'{"alg":"HS256","typ":"JWT"}')
    body = b64(json.dumps({"sub":user_id,"iat":now,"exp":now+TOKEN_TTL}).encode())
    signature = b64(hmac.new(JWT_SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{signature}"
def current_user(authorization: str | None) -> str:
    ensure_auth_configured()
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Authentication required")
    parts=authorization[7:].split(".")
    if len(parts)!=3: raise HTTPException(401,"Invalid token")
    expected=b64(hmac.new(JWT_SECRET.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected,parts[2]): raise HTTPException(401,"Invalid token")
    try:
        payload=json.loads(base64.urlsafe_b64decode(parts[1]+"="*((4-len(parts[1])%4)%4)))
        if payload["exp"] < int(time.time()): raise ValueError()
        return str(payload["sub"])
    except Exception: raise HTTPException(401,"Expired or invalid token")

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

@app.post("/v1/auth/register")
def register(body: Credentials):
    ensure_auth_configured()
    salt=secrets.token_bytes(16); uid=secrets.token_hex(16)
    try:
        with db() as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)",(uid,body.username,salt,password_hash(body.password,salt),int(time.time())))
    except sqlite3.IntegrityError: raise HTTPException(409,"Username already exists")
    return {"accessToken":token_for(uid),"tokenType":"Bearer","expiresIn":TOKEN_TTL,"userId":uid}

@app.post("/v1/auth/login")
def login(body: Credentials):
    ensure_auth_configured()
    with db() as c: user=c.execute("SELECT * FROM users WHERE username=?",(body.username,)).fetchone()
    if not user or not hmac.compare_digest(password_hash(body.password,user["salt"]),user["password_hash"]): raise HTTPException(401,"Invalid credentials")
    return {"accessToken":token_for(user["id"]),"tokenType":"Bearer","expiresIn":TOKEN_TTL,"userId":user["id"]}

@app.post("/v1/sync/push")
def push(body: PushBody, authorization: str | None = Header(default=None)):
    uid=current_user(authorization); results=[]
    with db() as c:
        for op in body.operations:
            old=c.execute("SELECT result FROM operations WHERE user_id=? AND idempotency_key=?",(uid,op.idempotencyKey)).fetchone()
            if old:
                results.append(json.loads(old["result"])); continue
            current=c.execute("SELECT version FROM records WHERE user_id=? AND entity_type=? AND entity_id=?",(uid,op.entityType,op.entityId)).fetchone()
            version=current["version"] if current else 0
            if version != op.baseVersion:
                result={"idempotencyKey":op.idempotencyKey,"status":"conflict","serverVersion":version}
            else:
                next_version=version+1
                payload=encrypt_payload(op.payload)
                updated_at = int(time.time() * 1000)
                deleted = 1 if op.operation == "DELETE" else 0
                c.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,entity_type,entity_id) DO UPDATE SET payload=excluded.payload,version=excluded.version,updated_at=excluded.updated_at,deleted=excluded.deleted",(uid,op.entityType,op.entityId,payload,next_version,updated_at,deleted))
                c.execute("INSERT INTO change_log(user_id,entity_type,entity_id,payload,version,updated_at,deleted) VALUES(?,?,?,?,?,?,?)",(uid,op.entityType,op.entityId,payload,next_version,updated_at,deleted))
                result={"idempotencyKey":op.idempotencyKey,"status":"applied","serverVersion":next_version}
            c.execute("INSERT INTO operations VALUES(?,?,?,?)",(uid,op.idempotencyKey,json.dumps(result),int(time.time())))
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
