"""Account recovery, the approval queue and encrypted copies of the database."""
import base64
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("MOLIDO_JWT_SECRET", "recovery-paths-test-secret-32-characters")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-recovery-tests.sqlite3"))

from fastapi.testclient import TestClient

import app

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "another-long-password-42"
ADMIN = "c" * 40
APPROVAL = "ledger-approval-token-for-recovery-tests"
BACKUP_KEY = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "recovery.sqlite3")
    app.init_db()
    return TestClient(app.app)


def sign_in(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/v1/auth/login", json={"username": username, "password": password})


def token_for(client: TestClient, username: str) -> dict:
    response = sign_in(client, username)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def post_journal(client: TestClient, headers: dict, description: str = "Sale on account"):
    response = client.post("/v1/erp/ledger/journals", headers=headers, json={
        "description": description, "currency": "IRR",
        "lines": [{"accountCode": "1100", "debit": 1000},
                  {"accountCode": "4000", "credit": 1000}]})
    assert response.status_code == 200, response.text
    return response.json()


def test_password_change_requires_the_current_password(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "changer", "password": PASSWORD})
    headers = token_for(client, "changer")

    wrong = client.post("/v1/auth/password", headers=headers,
                        json={"currentPassword": "not-the-password-1", "newPassword": NEW_PASSWORD})
    assert wrong.status_code == 403

    changed = client.post("/v1/auth/password", headers=headers,
                          json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})
    assert changed.status_code == 200, changed.text
    assert changed.json()["username"] == "changer"
    # The old password stops working and the new one signs in.
    assert sign_in(client, "changer").status_code == 401
    assert sign_in(client, "changer", NEW_PASSWORD).status_code == 200


def test_a_successful_password_change_clears_the_lockout(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "MAX_LOGIN_FAILURES", 2)
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "locked", "password": PASSWORD})
    headers = token_for(client, "locked")
    for _ in range(2):
        sign_in(client, "locked", "wrong-password-123")
    assert sign_in(client, "locked").status_code == 429

    changed = client.post("/v1/auth/password", headers=headers,
                          json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD})
    assert changed.status_code == 200, changed.text
    # Without clearing the failure counter the new password would still be refused.
    assert sign_in(client, "locked", NEW_PASSWORD).status_code == 200


def test_admin_reset_covers_a_forgotten_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "forgetful", "password": PASSWORD})

    anonymous = client.post("/v1/admin/users/forgetful/password", json={"newPassword": NEW_PASSWORD})
    assert anonymous.status_code == 403
    missing = client.post("/v1/admin/users/ghost/password", headers={"X-Admin-Token": ADMIN},
                          json={"newPassword": NEW_PASSWORD})
    assert missing.status_code == 404

    reset = client.post("/v1/admin/users/forgetful/password", headers={"X-Admin-Token": ADMIN},
                        json={"newPassword": NEW_PASSWORD})
    assert reset.status_code == 200, reset.text
    assert sign_in(client, "forgetful").status_code == 401
    assert sign_in(client, "forgetful", NEW_PASSWORD).status_code == 200


def test_approval_queue_lists_pending_journals(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOLIDO_LEDGER_APPROVAL_TOKEN", APPROVAL)
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "approver", "password": PASSWORD})
    headers = token_for(client, "approver")
    created = post_journal(client, headers)

    pending = client.get("/v1/erp/ledger/journals", headers=headers,
                         params={"status": "PENDING_APPROVAL"})
    assert pending.status_code == 200, pending.text
    items = pending.json()["items"]
    assert [item["id"] for item in items] == [created["id"]]
    assert items[0]["lines"][0]["accountCode"] == "1100"
    assert items[0]["totalDebit"] == 1000

    approved = client.post(f"/v1/erp/ledger/journals/{created['id']}/approve",
                           headers={**headers, "X-Approval-Token": APPROVAL})
    assert approved.status_code == 200, approved.text
    assert client.get("/v1/erp/ledger/journals", headers=headers,
                      params={"status": "PENDING_APPROVAL"}).json()["items"] == []
    posted = client.get("/v1/erp/ledger/journals", headers=headers).json()["items"]
    assert [item["status"] for item in posted] == ["POSTED"]


def test_the_queue_is_account_isolated_and_rejects_unknown_status(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "queue_owner", "password": PASSWORD})
    client.post("/v1/auth/register", json={"username": "queue_other", "password": PASSWORD})
    owner = token_for(client, "queue_owner")
    other = token_for(client, "queue_other")
    post_journal(client, owner)

    assert client.get("/v1/erp/ledger/journals", headers=other).json()["items"] == []
    assert client.get("/v1/erp/ledger/journals", headers=owner,
                      params={"status": "WHATEVER"}).status_code == 422


def test_copies_are_sealed_and_can_be_reopened(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "sealed-user", "password": PASSWORD})
    directory = tmp_path / "copies"
    monkeypatch.setattr(app, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(app, "BACKUP_KEEP", 5)
    monkeypatch.setattr(app, "BACKUP_KEY", BACKUP_KEY)

    path = app.backup_database(stamp=1_700_000_000)

    assert path.name == "molido-20231114-221320.sqlite3.enc"
    assert not (directory / "molido-20231114-221320.sqlite3").exists()
    blob = path.read_bytes()
    assert blob.startswith(app.BACKUP_MAGIC) and b"sealed-user" not in blob

    reopened = app.open_backup(path, tmp_path / "restored.sqlite3")
    with sqlite3.connect(reopened) as copy:
        names = [row[0] for row in copy.execute("SELECT username FROM users")]
    assert "sealed-user" in names


def test_a_sealed_copy_needs_the_same_key(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    client.post("/v1/auth/register", json={"username": "key-user", "password": PASSWORD})
    monkeypatch.setattr(app, "BACKUP_DIR", str(tmp_path / "copies"))
    monkeypatch.setattr(app, "BACKUP_KEY", BACKUP_KEY)
    path = app.backup_database(stamp=1_700_000_000)

    monkeypatch.setattr(app, "BACKUP_KEY", base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("="))
    with pytest.raises(Exception):
        app.open_backup(path, tmp_path / "wrong.sqlite3")


def test_encrypted_copies_rotate_too(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)  # noqa: F841 - creates the schema the copy needs
    directory = tmp_path / "copies"
    monkeypatch.setattr(app, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(app, "BACKUP_KEEP", 2)
    monkeypatch.setattr(app, "BACKUP_KEY", BACKUP_KEY)

    for offset in range(4):
        app.backup_database(stamp=1_700_000_000 + offset)

    remaining = sorted(p.name for p in directory.iterdir())
    assert remaining == ["molido-20231114-221322.sqlite3.enc", "molido-20231114-221323.sqlite3.enc"]


def test_a_mis_sized_backup_key_writes_nothing(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    directory = tmp_path / "copies"
    monkeypatch.setattr(app, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(app, "BACKUP_KEY", "too-short-to-be-a-key")

    with pytest.raises(app.HTTPException) as error:
        app.backup_database(stamp=1_700_000_000)
    assert error.value.status_code == 503
    assert not directory.exists() or list(directory.iterdir()) == []