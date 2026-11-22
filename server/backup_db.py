from __future__ import annotations

import base64
import contextlib
import os
import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"MOLIDODB1"


def key_bytes() -> bytes:
    raw = os.environ.get("MOLIDO_BACKUP_KEY", "")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * ((4 - len(raw) % 4) % 4))
    except Exception as exc:
        raise SystemExit("MOLIDO_BACKUP_KEY must be valid Base64") from exc
    if len(key) != 32:
        raise SystemExit("MOLIDO_BACKUP_KEY must decode to exactly 32 bytes")
    return key


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python backup_db.py /secure/path/molido.sqlite3.enc")
    source = Path(os.environ.get("MOLIDO_DB_PATH", "molido-server.sqlite3"))
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise SystemExit(f"Database does not exist: {source}")
    with tempfile.TemporaryDirectory(prefix="molido-backup-") as directory:
        snapshot = Path(directory) / "snapshot.sqlite3"
        with contextlib.closing(sqlite3.connect(source)) as src, contextlib.closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise SystemExit(f"SQLite integrity check failed: {result}")
        plain = snapshot.read_bytes()
        nonce = secrets.token_bytes(12)
        encrypted = MAGIC + nonce + AESGCM(key_bytes()).encrypt(nonce, plain, MAGIC)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    print(f"Encrypted backup created: {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
