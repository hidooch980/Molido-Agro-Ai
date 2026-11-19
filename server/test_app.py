import os, tempfile
os.environ["MOLIDO_JWT_SECRET"]="test-secret-that-is-long-enough-for-hmac-sha256"
os.environ["MOLIDO_DATA_KEY"]="eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHg"
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

def test_change_log_cursor_paginates_without_skipping_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "cursor.sqlite3"); app.init_db()
    client=TestClient(app.app)
    token=client.post("/v1/auth/register",json={"username":"grower_cursor","password":"strong-password-987"}).json()["accessToken"]
    headers={"Authorization":f"Bearer {token}"}
    for n in range(3):
        op={"idempotencyKey":f"key-{n}","entityType":"greenhouse","entityId":str(n),"operation":"CREATE","payload":{"name":str(n)},"baseVersion":0}
        assert client.post("/v1/sync/push",json={"operations":[op]},headers=headers).status_code==200
    first=client.post("/v1/sync/pull",json={"cursor":0,"limit":1},headers=headers).json()
    second=client.post("/v1/sync/pull",json={"cursor":first["cursor"],"limit":10},headers=headers).json()
    assert len(first["changes"])==1
    assert len(second["changes"])==2
    assert first["changes"][0]["cursorId"] < second["changes"][0]["cursorId"]

def test_delete_is_a_versioned_tombstone_for_other_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "delete.sqlite3"); app.init_db()
    client=TestClient(app.app)
    token=client.post("/v1/auth/register",json={"username":"grower_delete","password":"strong-password-987"}).json()["accessToken"]
    headers={"Authorization":f"Bearer {token}"}
    create={"idempotencyKey":"create-record","entityType":"inventory_item","entityId":"fertilizer-1","operation":"CREATE","payload":{"name":"Fertilizer","quantity":20},"baseVersion":0}
    assert client.post("/v1/sync/push",json={"operations":[create]},headers=headers).json()["results"][0]["status"]=="applied"
    delete={"idempotencyKey":"delete-record","entityType":"inventory_item","entityId":"fertilizer-1","operation":"DELETE","payload":{},"baseVersion":1}
    result=client.post("/v1/sync/push",json={"operations":[delete]},headers=headers).json()["results"][0]
    assert result["status"]=="applied" and result["serverVersion"]==2
    changes=client.post("/v1/sync/pull",json={"cursor":0},headers=headers).json()["changes"]
    assert changes[-1]["deleted"] is True
    assert changes[-1]["version"]==2

def test_register_fails_before_creating_account_when_jwt_secret_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "missing-secret.sqlite3")
    monkeypatch.setattr(app, "JWT_SECRET", "")
    app.init_db()
    client = TestClient(app.app)
    response = client.post("/v1/auth/register", json={"username": "grower_no_secret", "password": "strong-password-123"})
    assert response.status_code == 503
    with app.db() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_push_rejects_unsupported_entity_types(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "entity-type.sqlite3")
    monkeypatch.setattr(app, "JWT_SECRET", "test-secret-that-is-long-enough-for-hmac-sha256")
    app.init_db()
    client = TestClient(app.app)
    token = client.post("/v1/auth/register", json={"username": "grower_entity", "password": "strong-password-123"}).json()["accessToken"]
    operation = {"idempotencyKey": "unsupported-1", "entityType": "unknown_entity", "entityId": "x", "operation": "CREATE", "payload": {}, "baseVersion": 0}
    response = client.post("/v1/sync/push", json={"operations": [operation]}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422

def test_sync_rejects_tokens_when_jwt_secret_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "missing-jwt.sqlite3")
    monkeypatch.setattr(app, "JWT_SECRET", "")
    app.init_db()
    client = TestClient(app.app)
    response = client.post(
        "/v1/sync/pull",
        json={"cursor": 0},
        headers={"Authorization": "Bearer forged.header.signature"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Server authentication is not configured"

