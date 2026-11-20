from __future__ import annotations

import base64
import os
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
        raise SystemExit("Usage: python restore_db.py /secure/path/molido.sqlite3.enc")
    source = Path(sys.argv[1])
    target = Path(os.environ.get("MOLIDO_DB_PATH", "molido-server.sqlite3"))
    if not source.is_file():
        raise SystemExit(f"Backup does not exist: {source}")
    blob = source.read_bytes()
    if len(blob) < len(MAGIC) + 12 + 16 or not blob.startswith(MAGIC):
        raise SystemExit("Backup format is invalid")
    nonce = blob[len(MAGIC):len(MAGIC) + 12]
    try:
        plain = AESGCM(key_bytes()).decrypt(nonce, blob[len(MAGIC) + 12:], MAGIC)
    except Exception as exc:
        raise SystemExit("Backup authentication failed; wrong key or damaged file") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="molido-restore-", suffix=".sqlite3", dir=target.parent, delete=False) as handle:
        staged = Path(handle.name)
        handle.write(plain)
    try:
        with sqlite3.connect(staged) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise SystemExit(f"Restored SQLite integrity check failed: {result}")
        os.chmod(staged, 0o600)
        os.replace(staged, target)
    finally:
        if staged.exists():
            staged.unlink()
    print(f"Database restored and verified: {target}")


if __name__ == "__main__":
    main()
