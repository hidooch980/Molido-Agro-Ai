from __future__ import annotations

import base64
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_SCRIPT = ROOT / "server" / "backup_db.py"
RESTORE_SCRIPT = ROOT / "server" / "restore_db.py"
BACKUP_KEY = base64.urlsafe_b64encode(b"molido-backup-test-key-32-bytes!").decode().rstrip("=")


def run_script(script: Path, argument: Path, database: Path, key: str = BACKUP_KEY):
    env = os.environ.copy()
    env["MOLIDO_DB_PATH"] = str(database)
    env["MOLIDO_BACKUP_KEY"] = key
    return subprocess.run(
        [sys.executable, str(script), str(argument)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def create_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS legacy_records (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT OR REPLACE INTO legacy_records(id, value) VALUES ('legacy-1', ?)", (value,))


def read_legacy_value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM legacy_records WHERE id='legacy-1'").fetchone()[0]


def test_encrypted_backup_restores_consistent_database_and_legacy_data(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3.enc"
    restored = tmp_path / "restored.sqlite3"
    create_database(source, "legacy-private-value")

    made = run_script(BACKUP_SCRIPT, backup, source)
    assert made.returncode == 0, made.stderr
    assert backup.is_file()
    assert b"legacy-private-value" not in backup.read_bytes()

    # Change the source after the snapshot: restore must reproduce the backup point-in-time state.
    create_database(source, "changed-after-backup")
    restored_result = run_script(RESTORE_SCRIPT, backup, restored)
    assert restored_result.returncode == 0, restored_result.stderr
    assert read_legacy_value(restored) == "legacy-private-value"


def test_restore_with_wrong_key_does_not_replace_existing_database(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3.enc"
    target = tmp_path / "production.sqlite3"
    create_database(source, "backup-value")
    create_database(target, "keep-existing-value")

    made = run_script(BACKUP_SCRIPT, backup, source)
    assert made.returncode == 0, made.stderr
    rejected = run_script(RESTORE_SCRIPT, backup, target, key=base64.urlsafe_b64encode(b"wrong-backup-key-32-bytes-value!").decode().rstrip("="))
    assert rejected.returncode != 0
    assert read_legacy_value(target) == "keep-existing-value"


def test_tampered_backup_does_not_replace_existing_database(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3.enc"
    target = tmp_path / "production.sqlite3"
    create_database(source, "backup-value")
    create_database(target, "keep-existing-value")

    made = run_script(BACKUP_SCRIPT, backup, source)
    assert made.returncode == 0, made.stderr
    damaged = bytearray(backup.read_bytes())
    damaged[-1] ^= 0x01
    backup.write_bytes(damaged)

    rejected = run_script(RESTORE_SCRIPT, backup, target)
    assert rejected.returncode != 0
    assert read_legacy_value(target) == "keep-existing-value"
