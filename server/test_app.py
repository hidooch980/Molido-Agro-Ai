import os, tempfile
os.environ["MOLIDO_JWT_SECRET"]="test-secret-that-is-long-enough-for-hmac-sha256"
from fastapi.testclient import TestClient
import app

def test_auth_and_user_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "test.sqlite3")
    app.init_db()
    c=TestClient(app.app)
    a=c.post("/v1/auth/register",json={"username":"grower_a","password":"strong-password-123"}); assert a.status_code==200
    b=c.post("/v1/auth/register",json={"username":"grower_b","password":"strong-password-456"}); assert b.status_code==200
    token_a=a.json()["accessToken"]; token_b=b.json()["accessToken"]
    op={"idempotencyKey":"create:greenhouse:1","entityType":"greenhouse","entityId":"1","operation":"CREATE","payload":{"name":"A"},"baseVersion":0}
    pushed=c.post("/v1/sync/push",json={"operations":[op]},headers={"Authorization":f"Bearer {token_a}"})
    assert pushed.json()["results"][0]["status"]=="applied"
    pulled=c.post("/v1/sync/pull",json={"cursor":0},headers={"Authorization":f"Bearer {token_b}"})
    assert pulled.json()["changes"]==[]
    own=c.post("/v1/sync/pull",json={"cursor":0},headers={"Authorization":f"Bearer {token_a}"})
    assert own.json()["changes"][0]["payload"]["name"]=="A"

def test_idempotency_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "test.sqlite3"); app.init_db()
    c=TestClient(app.app)
    auth=c.post("/v1/auth/register",json={"username":"grower_c","password":"strong-password-789"}).json()["accessToken"]
    h={"Authorization":f"Bearer {auth}"}
    op={"idempotencyKey":"same-key","entityType":"inventory_item","entityId":"x","operation":"CREATE","payload":{"quantity":1},"baseVersion":0}
    assert c.post("/v1/sync/push",json={"operations":[op]},headers=h).json()["results"][0]["status"]=="applied"
    assert c.post("/v1/sync/push",json={"operations":[op]},headers=h).json()["results"][0]["status"]=="applied"
    stale={**op,"idempotencyKey":"stale-key","payload":{"quantity":2},"baseVersion":0}
    assert c.post("/v1/sync/push",json={"operations":[stale]},headers=h).json()["results"][0]["status"]=="conflict"
