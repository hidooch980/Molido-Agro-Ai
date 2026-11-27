"""Scheduled database copies: consistency, rotation and the admin trigger."""
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ.setdefault("MOLIDO_JWT_SECRET", "backup-rotation-test-secret-32-chars")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-backup-tests.sqlite3"))

from fastapi.testclient import TestClient

import app

PASSWORD = "correct-horse-battery-staple"
ADMIN = "b" * 40


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "backup.sqlite3")
    app.init_db()
    return TestClient(app.app)


def test_backup_is_a_readable_copy_of_the_live_database(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    created = client.post("/v1/auth/register", json={"username": "backed-up", "password": PASSWORD})
    assert created.status_code == 200, created.text
    directory = tmp_path / "copies"
    monkeypatch.setattr(app, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(app, "BACKUP_KEEP", 5)

    path = app.backup_database(stamp=1_700_000_000)

    assert path.exists() and path.name == "molido-20231114-221320.sqlite3"
    with sqlite3.connect(path) as copy:
        names = [row[0] for row in copy.execute("SELECT username FROM users").fetchall()]
    assert "backed-up" in names


def test_rotation_keeps_only_the_newest_copies(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)  # noqa: F841 - creates the schema the copy needs
    directory = tmp_path / "copies"
    monkeypatch.setattr(app, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(app, "BACKUP_KEEP", 2)

    for offset in range(4):
        app.backup_database(stamp=1_700_000_000 + offset)

    remaining = sorted(p.name for p in directory.glob("molido-*.sqlite3"))
    assert remaining == ["molido-20231114-221322.sqlite3", "molido-20231114-221323.sqlite3"]


def test_admin_can_take_a_backup_on_demand(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "BACKUP_DIR", str(tmp_path / "copies"))
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)

    assert client.post("/v1/admin/backup").status_code == 403
    response = client.post("/v1/admin/backup", headers={"X-Admin-Token": ADMIN})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file"].startswith("molido-") and body["bytes"] > 0


def test_unwritable_directory_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    monkeypatch.setattr(app, "BACKUP_DIR", str(blocker / "copies"))
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    response = client.post("/v1/admin/backup", headers={"X-Admin-Token": ADMIN})
    assert response.status_code == 503
    assert "not writable" in response.json()["detail"]


def test_backup_is_refused_when_no_directory_is_configured(tmp_path, monkeypatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(app, "BACKUP_DIR", "")
    monkeypatch.setattr(app, "ADMIN_TOKEN", ADMIN)
    response = client.post("/v1/admin/backup", headers={"X-Admin-Token": ADMIN})
    assert response.status_code == 503
