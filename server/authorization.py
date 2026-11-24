"""Role checks shared by the financial approval endpoints.

Approval still requires the per-service approval token; the role check adds a second,
per-account gate so an operator account cannot post money movements.
"""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException

APPROVER_ROLES = ("OWNER", "ACCOUNTANT")


def role_of(connection: sqlite3.Connection, user_id: str) -> str | None:
    row = connection.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    return row["role"] if row else None


def require_approver(connection: sqlite3.Connection, user_id: str) -> None:
    """Reject accounts that are not allowed to approve financial postings."""
    if role_of(connection, user_id) not in APPROVER_ROLES:
        raise HTTPException(403, "This account role cannot approve financial records")
