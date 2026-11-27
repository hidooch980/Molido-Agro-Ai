"""Write a readable database from a stored copy, decrypting a sealed one.

Usage: python restore_backup.py <copy.sqlite3[.enc]> <destination.sqlite3>
The service holds the key, so this runs inside the container:
  docker compose run --rm api python restore_backup.py /backups/<copy> /data/molido.sqlite3
"""
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException

from app import open_backup


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    source, destination = Path(argv[1]), Path(argv[2])
    if not source.exists():
        print(f"copy not found: {source}")
        return 1
    try:
        written = open_backup(source, destination)
    except HTTPException as error:
        print(f"cannot restore: {error.detail}")
        return 1
    except InvalidTag:
        print("cannot restore: wrong MOLIDO_BACKUP_KEY or damaged copy")
        return 1
    # Keep the output ASCII: a Windows console with a legacy code page fails on non-ASCII paths,
    # and the restore itself has already succeeded by this point.
    print(f"restored {written.stat().st_size} bytes from {source.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))