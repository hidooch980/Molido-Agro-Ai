"""Account roles, admin endpoints and metrics counters."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MOLIDO_JWT_SECRET", "roles-and-metrics-test-secret-32chars")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-roles-tests.sqlite3"))

from fastapi.testclient import TestClient

import app

PASSWORD = "correct-horse-battery-staple"
ADMIN = "a" * 40


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "roles.sqlite3")
    app.init_db()
    return TestClient(app.app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client: TestClient, username: str) -> str:
    response = client.post("/v1/auth/register", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def create_operator(client: TestClient, username: str) -> None:
    response = client.post("/v1/admin/users",
                           json={"username": username, "password": PASSWORD, "role": "OPERATOR"},
                           headers={"X-Admin-Token": ADMIN})
    assert response.status_code == 200, response.text


def test_registration_creates_an_owner_account(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = register(client, "owner_one")
    profile = client.get("/v1/auth/me", headers=bearer(token))
    assert profile.status_code == 200
    body = profile.json()
    assert body["username"] == "owner_one"
    assert body["role"] == "OWNER"


def test_admin_api_is_disabled_until_a_token_is_configured(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "ADMIN_TOKEN", "")
    assert client.get("/v1/admin/users", headers={"X-Admin-Token": ADMIN}).status_code == 503
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    assert client.get("/v1/admin/users", headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.get("/v1/admin/users", headers={"X-Admin-Token": ADMIN}).json()["users"] == []


def test_admin_can_create_an_operator_and_promote_the_account(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    create_operator(client, "field_operator")
    token = client.post("/v1/auth/login", json={"username": "field_operator", "password": PASSWORD}).json()["accessToken"]
    assert client.get("/v1/auth/me", headers=bearer(token)).json()["role"] == "OPERATOR"
    promoted = client.patch("/v1/admin/users/field_operator", json={"role": "ACCOUNTANT"},
                            headers={"X-Admin-Token": ADMIN})
    assert promoted.status_code == 200
    assert client.get("/v1/auth/me", headers=bearer(token)).json()["role"] == "ACCOUNTANT"
    assert client.patch("/v1/admin/users/missing", json={"role": "OWNER"},
                        headers={"X-Admin-Token": ADMIN}).status_code == 404


def test_an_operator_cannot_approve_financial_records(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    monkeypatch.setenv("MOLIDO_COST_APPROVAL_TOKEN", "c" * 40)
    owner = register(client, "owner_two")
    create_operator(client, "operator_two")
    operator = client.post("/v1/auth/login", json={"username": "operator_two", "password": PASSWORD}).json()["accessToken"]
    denied = client.post("/v2/erp/costs/entries/unknown/approve",
                         headers={**bearer(operator), "X-Approval-Token": "c" * 40})
    assert denied.status_code == 403
    assert "role" in denied.json()["detail"]
    # The owner passes the role gate and reaches the missing-entry check instead.
    allowed = client.post("/v2/erp/costs/entries/unknown/approve",
                          headers={**bearer(owner), "X-Approval-Token": "c" * 40})
    assert allowed.status_code == 404


def test_metrics_count_requests_and_failed_sign_ins(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "METRICS_TOKEN", "m" * 40)
    assert client.get("/metrics").status_code == 401
    before = app.METRICS.get("auth_login_failed", 0)
    client.post("/v1/auth/login", json={"username": "ghost", "password": PASSWORD})
    snapshot = client.get("/metrics", headers=bearer("m" * 40))
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["counters"]["auth_login_failed"] == before + 1
    assert body["counters"]["http_requests"] > 0
    assert body["accounts"] == 0


def test_rate_limits_are_stored_in_the_database_not_in_memory(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "LOGIN_RATE_LIMIT", 2)
    monkeypatch.setattr(app, "AUTH_RATE_WINDOW", 60)
    payload = {"username": "ghost", "password": PASSWORD}
    assert client.post("/v1/auth/login", json=payload).status_code == 401
    assert client.post("/v1/auth/login", json=payload).status_code == 401
    blocked = client.post("/v1/auth/login", json=payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    with app.db() as connection:
        stored = connection.execute("SELECT COUNT(*) FROM rate_limits").fetchone()[0]
    assert stored >= 1
