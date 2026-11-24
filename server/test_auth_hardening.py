"""Authentication hardening: token revocation, rotation, lockout and rate limits."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MOLIDO_JWT_SECRET", "auth-hardening-test-secret-minimum-32-chars")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-auth-hardening-tests.sqlite3"))

from fastapi.testclient import TestClient

import app

PASSWORD = "Strong-test-password-123"


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "auth.sqlite3")
    app.init_db()
    return TestClient(app.app)


def register(client: TestClient, username: str) -> str:
    response = client.post("/v1/auth/register", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_the_presented_token(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = bearer(register(client, "logout_user"))

    assert client.post("/v1/sync/pull", json={"cursor": 0}, headers=headers).status_code == 200
    assert client.post("/v1/auth/logout", headers=headers).json() == {"revoked": True}
    replay = client.post("/v1/sync/pull", json={"cursor": 0}, headers=headers)
    assert replay.status_code == 401
    assert "revoked" in replay.json()["detail"].lower()


def test_refresh_rotates_the_token_and_retires_the_old_one(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    old_headers = bearer(register(client, "refresh_user"))

    refreshed = client.post("/v1/auth/refresh", headers=old_headers)
    assert refreshed.status_code == 200, refreshed.text
    new_token = refreshed.json()["accessToken"]
    assert new_token != old_headers["Authorization"][7:]

    assert client.post("/v1/sync/pull", json={"cursor": 0}, headers=bearer(new_token)).status_code == 200
    assert client.post("/v1/sync/pull", json={"cursor": 0}, headers=old_headers).status_code == 401


def test_refresh_requires_a_valid_token(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert client.post("/v1/auth/refresh").status_code == 401
    assert client.post("/v1/auth/logout").status_code == 401


def test_repeated_failures_lock_the_account_then_expire(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "MAX_LOGIN_FAILURES", 3)
    monkeypatch.setattr(app, "LOCKOUT_SECONDS", 900)
    client = make_client(tmp_path, monkeypatch)
    register(client, "lock_user")

    for _ in range(2):
        attempt = client.post("/v1/auth/login", json={"username": "lock_user", "password": "wrong-password-123"})
        assert attempt.status_code == 401, attempt.text

    third = client.post("/v1/auth/login", json={"username": "lock_user", "password": "wrong-password-123"})
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) > 0

    # Even the correct password is refused while the lock is active.
    blocked = client.post("/v1/auth/login", json={"username": "lock_user", "password": PASSWORD})
    assert blocked.status_code == 429

    with app.db() as connection:
        connection.execute("UPDATE login_failures SET locked_until=0 WHERE username=?", ("lock_user",))

    recovered = client.post("/v1/auth/login", json={"username": "lock_user", "password": PASSWORD})
    assert recovered.status_code == 200, recovered.text
    with app.db() as connection:
        assert connection.execute("SELECT 1 FROM login_failures WHERE username=?", ("lock_user",)).fetchone() is None


def test_successful_login_clears_earlier_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "MAX_LOGIN_FAILURES", 3)
    client = make_client(tmp_path, monkeypatch)
    register(client, "clear_user")

    client.post("/v1/auth/login", json={"username": "clear_user", "password": "wrong-password-123"})
    assert client.post("/v1/auth/login", json={"username": "clear_user", "password": PASSWORD}).status_code == 200

    for _ in range(2):
        attempt = client.post("/v1/auth/login", json={"username": "clear_user", "password": "wrong-password-123"})
        assert attempt.status_code == 401


def test_login_attempts_are_rate_limited_per_client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "LOGIN_RATE_LIMIT", 2)
    client = make_client(tmp_path, monkeypatch)
    register(client, "rate_user")

    for _ in range(2):
        assert client.post("/v1/auth/login", json={"username": "rate_user", "password": "wrong-password-123"}).status_code == 401
    limited = client.post("/v1/auth/login", json={"username": "rate_user", "password": "wrong-password-123"})
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


def test_revoked_tokens_are_pruned_when_expired(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    token = register(client, "prune_user")
    client.post("/v1/auth/logout", headers=bearer(token))
    with app.db() as connection:
        connection.execute("UPDATE revoked_tokens SET expires_at=?", (0,))
    register(client, "prune_user_two")  # a new revocation write prunes expired rows
    token_two = client.post("/v1/auth/login", json={"username": "prune_user_two", "password": PASSWORD}).json()["accessToken"]
    client.post("/v1/auth/logout", headers=bearer(token_two))
    with app.db() as connection:
        expired = connection.execute("SELECT COUNT(*) FROM revoked_tokens WHERE expires_at<=?", (int(__import__("time").time()),)).fetchone()[0]
    assert expired == 0
