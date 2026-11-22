from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

DB = Path(tempfile.gettempdir()) / "molido-ai-diagnostics-test.sqlite3"
if DB.exists():
    DB.unlink()

os.environ["MOLIDO_JWT_SECRET"] = "ai-diagnostics-test-secret-at-least-32-chars"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)

import app as app_module
client = TestClient(app_module.app)


def get_auth_headers(username="grower_ai_user"):
    import uuid
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    reg = client.post("/v1/auth/register", json={"username": uname, "password": "Strong-password-123"})
    assert reg.status_code == 200
    token = reg.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_ai_diagnosis_high_confidence_cucumber_downy_mildew():
    headers = get_auth_headers("grower_ai_high")
    payload = {
        "cropCode": "cucumber",
        "diseaseId": "cuc-downy-mildew",
        "confidence": 0.89,
        "notes": "Yellow patches on cucumber leaves"
    }
    response = client.post("/v1/ai/diagnose/disease", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "diagnosed"
    assert body["condition"] == "سفیدک داخلی (دروغی) خیار"
    assert len(body["culturalControls"]) > 0
    assert len(body["biologicalControls"]) > 0
    assert "کارنس" in body["safetyAdvisory"]
    assert body["requiresHumanSignoff"] is True


def test_ai_diagnosis_low_confidence_triggers_safety_fallback():
    headers = get_auth_headers("grower_ai_low")
    payload = {
        "cropCode": "cucumber",
        "diseaseId": "cuc-downy-mildew",
        "confidence": 0.45,
    }
    response = client.post("/v1/ai/diagnose/disease", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "inconclusive"
    assert body["riskLevel"] == "ELEVATED_UNCERTAINTY"
    assert body["requiresHumanSignoff"] is True
    assert "پایین" in body["safetyAdvisory"] or "ناکافی" in body["safetyAdvisory"]


def test_ai_diagnosis_with_microclimate_sensor_escalation():
    headers = get_auth_headers("grower_ai_sensor")
    # Record sensor reading with high risk humidity: 88% and temp 21.5C
    sensor_post = client.post(
        "/v1/sensors/readings",
        headers=headers,
        json={
            "idempotencyKey": "sensor-read-risk-1-unique-key",
            "greenhouseId": "gh-risk-1",
            "sensorId": "sensor-env-01",
            "measuredAtEpochMillis": 1_700_000_000_000,
            "temperatureC": 21.5,
            "relativeHumidityPct": 88.0,
            "source": "DEVICE"
        }
    )
    assert sensor_post.status_code == 200, sensor_post.text

    payload = {
        "cropCode": "cucumber",
        "diseaseId": "cuc-downy-mildew",
        "confidence": 0.85,
        "greenhouseId": "gh-risk-1"
    }
    response = client.post("/v1/ai/diagnose/disease", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "diagnosed"
    assert body["riskLevel"] == "CRITICAL"
    assert "هشدار اقلیمی" in body["microclimate"]["alert"]
