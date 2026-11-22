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
    changed_same_key={**op,"payload":{"quantity":999}}
    changed_result=c.post("/v1/sync/push",json={"operations":[changed_same_key]},headers=h).json()["results"][0]
    assert changed_result["status"]=="conflict"
    unchanged=c.post("/v1/sync/pull",json={"cursor":0},headers=h).json()["changes"]
    assert unchanged[0]["payload"]["quantity"]==1
    stale={**op,"idempotencyKey":"stale-key","payload":{"quantity":2},"baseVersion":0}
    assert c.post("/v1/sync/push",json={"operations":[stale]},headers=h).json()["results"][0]["status"]=="conflict"

def test_harvest_sync_accepts_current_and_legacy_entity_types(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "harvest-sync.sqlite3")
    app.init_db()
    client = TestClient(app.app)
    token = client.post("/v1/auth/register",json={
        "username":"grower_harvest_sync","password":"strong-password-987"
    }).json()["accessToken"]
    headers = {"Authorization":f"Bearer {token}"}
    for index, entity_type in enumerate(("harvest_batch", "harvest")):
        operation = {
            "idempotencyKey":f"harvest-sync-{index}",
            "entityType":entity_type,
            "entityId":f"harvest-{index}",
            "operation":"CREATE",
            "payload":{"quantity":12,"unit":"kg"},
            "baseVersion":0,
        }
        response = client.post("/v1/sync/push",json={"operations":[operation]},headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["status"] == "applied"


def test_operations_table_migrates_request_hash_without_losing_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "legacy-operations.sqlite3")
    with app.db() as connection:
        connection.execute("""CREATE TABLE operations(
            user_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,result TEXT NOT NULL,
            created_at INTEGER NOT NULL,PRIMARY KEY(user_id,idempotency_key)
        )""")
        connection.execute("INSERT INTO operations VALUES(?,?,?,?)",("legacy-user","legacy-key",'{"status":"applied"}',1))
    app.init_db()
    with app.db() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(operations)").fetchall()}
        legacy = connection.execute("SELECT result,request_hash FROM operations WHERE idempotency_key='legacy-key'").fetchone()
    assert "request_hash" in columns
    assert legacy["result"] == '{"status":"applied"}'
    assert legacy["request_hash"] == ""


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

def _sensor_client(tmp_path, monkeypatch, username="sensor_owner"):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / f"{username}.sqlite3")
    app.init_db()
    client = TestClient(app.app)
    token = client.post("/v1/auth/register", json={
        "username": username, "password": "strong-password-sensor-123"
    }).json()["accessToken"]
    return client, {"Authorization": f"Bearer {token}"}


def test_sensor_reading_history_threshold_alerts_and_idempotency(tmp_path, monkeypatch):
    client, headers = _sensor_client(tmp_path, monkeypatch)
    thresholds = {
        "minTemperatureC": 18, "maxTemperatureC": 30,
        "minHumidityPct": 45, "maxHumidityPct": 80,
        "staleAfterSeconds": 900,
    }
    saved = client.put("/v1/sensors/greenhouses/gh-1/thresholds", json=thresholds, headers=headers)
    assert saved.status_code == 200
    reading = {
        "idempotencyKey": "sensor-reading-0001", "greenhouseId": "gh-1",
        "sensorId": "esp32-01", "measuredAtEpochMillis": int(__import__("time").time() * 1000),
        "temperatureC": 34.5, "relativeHumidityPct": 35, "source": "DEVICE",
    }
    first = client.post("/v1/sensors/readings", json=reading, headers=headers)
    assert first.status_code == 200 and first.json()["status"] == "accepted"
    duplicate = client.post("/v1/sensors/readings", json=reading, headers=headers)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    status = client.get("/v1/sensors/greenhouses/gh-1/status", headers=headers).json()
    assert status["status"] == "ONLINE"
    assert status["isRealMeasurement"] is True
    assert set(status["alerts"]) == {"TEMPERATURE_TOO_HIGH", "HUMIDITY_TOO_LOW"}
    history = client.get("/v1/sensors/greenhouses/gh-1/readings", headers=headers).json()
    assert len(history["readings"]) == 1
    assert history["readings"][0]["sensorId"] == "esp32-01"


def test_sensor_data_is_account_isolated_and_empty_status_is_explicit(tmp_path, monkeypatch):
    client, owner_headers = _sensor_client(tmp_path, monkeypatch, "sensor_owner_a")
    second = client.post("/v1/auth/register", json={
        "username": "sensor_owner_b", "password": "strong-password-sensor-456"
    })
    other_headers = {"Authorization": f"Bearer {second.json()['accessToken']}"}
    status = client.get("/v1/sensors/greenhouses/gh-private/status", headers=other_headers).json()
    assert status["status"] == "NO_DATA"
    assert status["isRealMeasurement"] is False
    reading = {
        "idempotencyKey": "private-reading-0001", "greenhouseId": "gh-private",
        "sensorId": "sensor-private", "measuredAtEpochMillis": int(__import__("time").time() * 1000),
        "temperatureC": 25, "relativeHumidityPct": 60, "source": "DEVICE",
    }
    assert client.post("/v1/sensors/readings", json=reading, headers=owner_headers).status_code == 200
    hidden = client.get("/v1/sensors/greenhouses/gh-private/readings", headers=other_headers).json()
    assert hidden["readings"] == []


def test_sensor_rejects_invalid_values_and_future_timestamps(tmp_path, monkeypatch):
    client, headers = _sensor_client(tmp_path, monkeypatch)
    base = {
        "idempotencyKey": "sensor-reading-invalid", "greenhouseId": "gh-1",
        "sensorId": "sensor-1", "measuredAtEpochMillis": int(__import__("time").time() * 1000),
        "temperatureC": 24, "relativeHumidityPct": 55, "source": "DEVICE",
    }
    invalid_humidity = client.post("/v1/sensors/readings", json={**base, "relativeHumidityPct": 120}, headers=headers)
    assert invalid_humidity.status_code == 422
    future = client.post("/v1/sensors/readings", json={
        **base, "idempotencyKey": "sensor-reading-future",
        "measuredAtEpochMillis": int(__import__("time").time() * 1000) + 600_000,
    }, headers=headers)
    assert future.status_code == 422


def test_chirpstack_device_mapping_and_signed_uplink_ingestion(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "chirpstack.sqlite3")
    monkeypatch.setattr(app, "JWT_SECRET", "test-secret-that-is-long-enough-for-hmac-sha256")
    monkeypatch.setenv("MOLIDO_CHIRPSTACK_INGEST_SECRET", "chirpstack-test-secret-longer-than-32-characters")
    app.init_db()
    client = TestClient(app.app)
    token = client.post("/v1/auth/register", json={
        "username": "chirpstack_owner", "password": "strong-password-chirpstack"
    }).json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}
    greenhouse = {
        "idempotencyKey": "gh-create-001", "entityType": "greenhouse",
        "entityId": "gh-west", "operation": "CREATE",
        "payload": {"name": "گلخانه غرب"}, "baseVersion": 0,
    }
    assert client.post("/v1/sync/push", json={"operations": [greenhouse]}, headers=headers).status_code == 200
    mapped = client.post("/v1/sensors/devices", json={
        "devEui": "A1B2C3D4E5F60718", "greenhouseId": "gh-west", "sensorId": "lora-01"
    }, headers=headers)
    assert mapped.status_code == 200
    assert mapped.json()["greenhouseId"] == "gh-west"

    import hashlib, hmac, json, time
    event = {
        "deviceInfo": {"devEui": "A1B2C3D4E5F60718"},
        "fCnt": 17,
        "time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "object": {"temperatureC": 26.4, "relativeHumidityPct": 63.2},
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = "chirpstack-nonce-0001"
    secret = "chirpstack-test-secret-longer-than-32-characters"
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + nonce.encode() + b"." + raw, hashlib.sha256).hexdigest()
    signed_headers = {"X-ChirpStack-Signature": f"{timestamp}:{nonce}:{digest}"}
    accepted = client.post("/v1/integrations/chirpstack/uplink", content=raw, headers=signed_headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    status = client.get("/v1/sensors/greenhouses/gh-west/status", headers=headers).json()
    assert status["temperatureC"] == 26.4
    assert status["relativeHumidityPct"] == 63.2
    replay = client.post("/v1/integrations/chirpstack/uplink", content=raw, headers=signed_headers)
    assert replay.status_code == 409

    tampered = raw.replace(b"26.4", b"29.4")
    rejected = client.post("/v1/integrations/chirpstack/uplink", content=tampered, headers=signed_headers)
    assert rejected.status_code == 401


def test_encrypted_sqlite_backup_and_restore_round_trip(tmp_path, monkeypatch):
    import base64, sqlite3, subprocess, sys
    monkeypatch.setenv("MOLIDO_BACKUP_KEY", base64.urlsafe_b64encode(b"b" * 32).decode())
    original = tmp_path / "source.sqlite3"
    with sqlite3.connect(original) as connection:
        connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES('backup-ok')")
    backup = tmp_path / "backup.sqlite3.enc"
    env = dict(os.environ, MOLIDO_DB_PATH=str(original))
    subprocess.run([sys.executable, "backup_db.py", str(backup)], check=True, env=env, capture_output=True, text=True)
    restored = tmp_path / "restored.sqlite3"
    env["MOLIDO_DB_PATH"] = str(restored)
    subprocess.run([sys.executable, "restore_db.py", str(backup)], check=True, env=env, capture_output=True, text=True)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "backup-ok"
