from __future__ import annotations

import time
import os
import hmac
import hashlib
from datetime import datetime
from typing import Any, Literal

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    greenhouseId: str = Field(min_length=1, max_length=200)
    sensorId: str = Field(min_length=1, max_length=200)
    measuredAtEpochMillis: int = Field(ge=1_600_000_000_000)
    temperatureC: float = Field(ge=-20, le=70, allow_inf_nan=False)
    relativeHumidityPct: float = Field(ge=0, le=100, allow_inf_nan=False)
    source: Literal["DEVICE", "MANUAL", "SIMULATED"] = "DEVICE"


class SensorDeviceMapping(BaseModel):
    devEui: str = Field(min_length=16, max_length=16, pattern=r"^[0-9A-Fa-f]{16}$")
    greenhouseId: str = Field(min_length=1, max_length=200)
    sensorId: str = Field(min_length=1, max_length=200)


class SensorThresholds(BaseModel):
    minTemperatureC: float = Field(ge=-20, le=70, allow_inf_nan=False)
    maxTemperatureC: float = Field(ge=-20, le=70, allow_inf_nan=False)
    minHumidityPct: float = Field(ge=0, le=100, allow_inf_nan=False)
    maxHumidityPct: float = Field(ge=0, le=100, allow_inf_nan=False)
    staleAfterSeconds: int = Field(default=900, ge=60, le=86400)


def register_sensor_routes(app, db, current_user, encrypt_payload, decrypt_payload) -> None:
    """Register account-isolated sensor APIs. Physical device provisioning is a later step."""

    def ensure_tables(connection) -> None:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS greenhouse_sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            greenhouse_id TEXT NOT NULL,
            sensor_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            measured_at INTEGER NOT NULL,
            received_at INTEGER NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE(user_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_lookup
            ON greenhouse_sensor_readings(user_id, greenhouse_id, measured_at DESC);
        CREATE TABLE IF NOT EXISTS greenhouse_sensor_devices (
            dev_eui TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            greenhouse_id TEXT NOT NULL,
            sensor_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chirpstack_nonces (
            nonce TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS greenhouse_sensor_thresholds (
            user_id TEXT NOT NULL,
            greenhouse_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, greenhouse_id)
        );
        """)

    def alert_state(reading: dict[str, Any], thresholds: dict[str, Any] | None) -> list[str]:
        if not thresholds:
            return []
        alerts = []
        if reading["temperatureC"] < thresholds["minTemperatureC"]:
            alerts.append("TEMPERATURE_TOO_LOW")
        if reading["temperatureC"] > thresholds["maxTemperatureC"]:
            alerts.append("TEMPERATURE_TOO_HIGH")
        if reading["relativeHumidityPct"] < thresholds["minHumidityPct"]:
            alerts.append("HUMIDITY_TOO_LOW")
        if reading["relativeHumidityPct"] > thresholds["maxHumidityPct"]:
            alerts.append("HUMIDITY_TOO_HIGH")
        return alerts

    @app.post("/v1/sensors/readings")
    def ingest_sensor_reading(body: SensorReading, authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        now_ms = int(time.time() * 1000)
        if body.measuredAtEpochMillis > now_ms + 300_000:
            raise HTTPException(422, "Sensor timestamp is too far in the future")
        payload = body.model_dump()
        with db() as connection:
            ensure_tables(connection)
            duplicate = connection.execute(
                "SELECT id, measured_at FROM greenhouse_sensor_readings WHERE user_id=? AND idempotency_key=?",
                (uid, body.idempotencyKey),
            ).fetchone()
            if duplicate:
                return {"status": "duplicate", "readingId": duplicate["id"], "measuredAtEpochMillis": duplicate["measured_at"]}
            cursor = connection.execute(
                """INSERT INTO greenhouse_sensor_readings
                   (user_id, greenhouse_id, sensor_id, idempotency_key, measured_at, received_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uid, body.greenhouseId, body.sensorId, body.idempotencyKey,
                 body.measuredAtEpochMillis, now_ms, encrypt_payload(payload)),
            )
            reading_id = cursor.lastrowid
        return {"status": "accepted", "readingId": reading_id, "receivedAtEpochMillis": now_ms,
                "isSimulated": body.source == "SIMULATED"}

    @app.get("/v1/sensors/greenhouses/{greenhouse_id}/readings")
    def list_sensor_readings(greenhouse_id: str, limit: int = 100, authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        if limit < 1 or limit > 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        with db() as connection:
            ensure_tables(connection)
            rows = connection.execute(
                """SELECT id, measured_at, received_at, payload FROM greenhouse_sensor_readings
                   WHERE user_id=? AND greenhouse_id=? ORDER BY measured_at DESC, id DESC LIMIT ?""",
                (uid, greenhouse_id, limit),
            ).fetchall()
        return {"greenhouseId": greenhouse_id, "readings": [
            {"readingId": row["id"], "measuredAtEpochMillis": row["measured_at"],
             "receivedAtEpochMillis": row["received_at"], **decrypt_payload(row["payload"])}
            for row in rows
        ]}

    @app.put("/v1/sensors/greenhouses/{greenhouse_id}/thresholds")
    def save_sensor_thresholds(greenhouse_id: str, body: SensorThresholds,
                               authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        if body.minTemperatureC >= body.maxTemperatureC or body.minHumidityPct >= body.maxHumidityPct:
            raise HTTPException(422, "Minimum thresholds must be lower than maximum thresholds")
        now_ms = int(time.time() * 1000)
        with db() as connection:
            ensure_tables(connection)
            connection.execute(
                """INSERT INTO greenhouse_sensor_thresholds(user_id, greenhouse_id, payload, updated_at)
                   VALUES(?, ?, ?, ?) ON CONFLICT(user_id, greenhouse_id)
                   DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at""",
                (uid, greenhouse_id, encrypt_payload(body.model_dump()), now_ms),
            )
        return {"status": "saved", "greenhouseId": greenhouse_id, "updatedAtEpochMillis": now_ms}

    @app.get("/v1/sensors/greenhouses/{greenhouse_id}/status")
    def sensor_status(greenhouse_id: str, authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        with db() as connection:
            ensure_tables(connection)
            row = connection.execute(
                """SELECT id, measured_at, received_at, payload FROM greenhouse_sensor_readings
                   WHERE user_id=? AND greenhouse_id=? ORDER BY measured_at DESC, id DESC LIMIT 1""",
                (uid, greenhouse_id),
            ).fetchone()
            config = connection.execute(
                "SELECT payload FROM greenhouse_sensor_thresholds WHERE user_id=? AND greenhouse_id=?",
                (uid, greenhouse_id),
            ).fetchone()
        if not row:
            return {"greenhouseId": greenhouse_id, "status": "NO_DATA", "isRealMeasurement": False,
                    "lastReceivedAtEpochMillis": None, "alerts": []}
        reading = decrypt_payload(row["payload"])
        thresholds = decrypt_payload(config["payload"]) if config else None
        age_seconds = max(0, int(time.time() * 1000) - row["received_at"]) // 1000
        stale_after = thresholds["staleAfterSeconds"] if thresholds else 900
        stale = age_seconds > stale_after
        simulated = reading.get("source") == "SIMULATED"
        status = "SIMULATED" if simulated else ("STALE" if stale else "ONLINE")
        return {"greenhouseId": greenhouse_id, "status": status,
                "isRealMeasurement": not simulated, "sensorId": reading["sensorId"],
                "temperatureC": reading["temperatureC"],
                "relativeHumidityPct": reading["relativeHumidityPct"],
                "measuredAtEpochMillis": row["measured_at"],
                "lastReceivedAtEpochMillis": row["received_at"], "ageSeconds": age_seconds,
                "alerts": alert_state(reading, thresholds)}



    @app.post("/v1/sensors/devices")
    def register_sensor_device(body: SensorDeviceMapping, authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        dev_eui = body.devEui.upper()
        with db() as connection:
            ensure_tables(connection)
            greenhouse = connection.execute(
                "SELECT 1 FROM records WHERE user_id=? AND entity_type='greenhouse' AND entity_id=? AND deleted=0",
                (uid, body.greenhouseId),
            ).fetchone()
            if not greenhouse:
                raise HTTPException(404, "Greenhouse not found in this account")
            existing = connection.execute(
                "SELECT user_id FROM greenhouse_sensor_devices WHERE dev_eui=?", (dev_eui,)
            ).fetchone()
            if existing and existing["user_id"] != uid:
                raise HTTPException(409, "Device is already assigned to another account")
            connection.execute(
                """INSERT INTO greenhouse_sensor_devices(dev_eui,user_id,greenhouse_id,sensor_id,created_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(dev_eui) DO UPDATE SET
                   greenhouse_id=excluded.greenhouse_id,sensor_id=excluded.sensor_id""",
                (dev_eui, uid, body.greenhouseId, body.sensorId, int(time.time() * 1000)),
            )
        return {"status": "registered", "devEui": dev_eui, "greenhouseId": body.greenhouseId, "sensorId": body.sensorId}

    @app.post("/v1/integrations/chirpstack/uplink")
    async def chirpstack_uplink(request: Request, x_chirpstack_signature: str | None = Header(default=None, alias="X-ChirpStack-Signature")):
        secret = os.environ.get("MOLIDO_CHIRPSTACK_INGEST_SECRET", "")
        if len(secret) < 32:
            raise HTTPException(503, "ChirpStack integration secret is not configured")
        if not x_chirpstack_signature:
            raise HTTPException(401, "Missing integration signature")
        try:
            timestamp_text, nonce, supplied = x_chirpstack_signature.split(":", 2)
            timestamp = int(timestamp_text)
        except Exception:
            raise HTTPException(401, "Invalid integration signature")
        now = int(time.time())
        if abs(now - timestamp) > 300 or not (8 <= len(nonce) <= 128):
            raise HTTPException(401, "Expired or invalid integration timestamp")
        raw = await request.body()
        signed = timestamp_text.encode() + b"." + nonce.encode() + b"." + raw
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(401, "Invalid integration signature")
        try:
            event = __import__("json").loads(raw)
            info = event.get("deviceInfo") or {}
            dev_eui = str(info.get("devEui") or event.get("devEui") or "").upper()
            counter = event.get("fCnt")
            decoded = event.get("object") or event.get("decoded_payload") or {}
            temperature = float(decoded["temperatureC"])
            humidity = float(decoded["relativeHumidityPct"])
            measured_at = int(datetime.fromisoformat(str(event.get("time")).replace("Z", "+00:00")).timestamp() * 1000)
            if counter is None or not dev_eui:
                raise ValueError("Missing device identity or frame counter")
        except Exception:
            raise HTTPException(422, "Uplink must include deviceInfo.devEui, fCnt, time, object.temperatureC and object.relativeHumidityPct")
        if not (-20 <= temperature <= 70 and 0 <= humidity <= 100):
            raise HTTPException(422, "Decoded sensor values are outside accepted ranges")
        with db() as connection:
            ensure_tables(connection)
            try:
                connection.execute("INSERT INTO chirpstack_nonces(nonce,created_at) VALUES(?,?)", (nonce, now))
            except Exception:
                raise HTTPException(409, "Replayed integration request")
            connection.execute("DELETE FROM chirpstack_nonces WHERE created_at < ?", (now - 600,))
            device = connection.execute(
                "SELECT user_id,greenhouse_id,sensor_id FROM greenhouse_sensor_devices WHERE dev_eui=?",
                (dev_eui,),
            ).fetchone()
            if not device:
                raise HTTPException(404, "Unregistered ChirpStack device")
            idem = f"chirpstack:{dev_eui}:{int(counter)}"
            duplicate = connection.execute(
                "SELECT id FROM greenhouse_sensor_readings WHERE user_id=? AND idempotency_key=?",
                (device["user_id"], idem),
            ).fetchone()
            if duplicate:
                return {"status": "duplicate", "readingId": duplicate["id"]}
            payload = {
                "idempotencyKey": idem, "greenhouseId": device["greenhouse_id"],
                "sensorId": device["sensor_id"], "measuredAtEpochMillis": measured_at,
                "temperatureC": temperature, "relativeHumidityPct": humidity, "source": "DEVICE"
            }
            cursor = connection.execute(
                """INSERT INTO greenhouse_sensor_readings
                   (user_id,greenhouse_id,sensor_id,idempotency_key,measured_at,received_at,payload)
                   VALUES(?,?,?,?,?,?,?)""",
                (device["user_id"], device["greenhouse_id"], device["sensor_id"], idem,
                 measured_at, int(time.time() * 1000), encrypt_payload(payload)),
            )
        return {"status": "accepted", "readingId": cursor.lastrowid, "greenhouseId": device["greenhouse_id"]}
