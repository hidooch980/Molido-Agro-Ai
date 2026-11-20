from __future__ import annotations

import hmac
import os
import time
import uuid
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


class ApprovalJournalLine(BaseModel):
    accountCode: str = Field(min_length=2, max_length=40)
    debit: float = Field(default=0, ge=0, allow_inf_nan=False)
    credit: float = Field(default=0, ge=0, allow_inf_nan=False)
    description: str = Field(default="", max_length=500)


class ApprovalJournalInput(BaseModel):
    dateEpochMillis: int | None = None
    reference: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=3, max_length=1000)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    lines: list[ApprovalJournalLine] = Field(min_length=2, max_length=100)


def register_approval_ledger_routes(app, db, current_user, encrypt_payload, decrypt_payload):
    def setup(c, uid):
        c.executescript("""
        CREATE TABLE IF NOT EXISTS approval_ledger_accounts (
          user_id TEXT NOT NULL, account_code TEXT NOT NULL, name TEXT NOT NULL,
          account_type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(user_id,account_code)
        );
        CREATE TABLE IF NOT EXISTS approval_ledger_journals (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, reference TEXT,
          description TEXT NOT NULL, currency TEXT NOT NULL, total_debit REAL NOT NULL,
          status TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,journal_id)
        );
        """)
        defaults = [
            ("1000", "نقد و بانک", "ASSET"), ("1100", "حساب‌های دریافتنی", "ASSET"),
            ("1200", "موجودی کالا", "ASSET"), ("2000", "حساب‌های پرداختنی", "LIABILITY"),
            ("3000", "سرمایه", "EQUITY"), ("4000", "فروش محصولات", "REVENUE"),
            ("5000", "بهای تمام‌شده فروش", "EXPENSE"), ("6000", "هزینه‌های تولید", "EXPENSE")
        ]
        for code, name, kind in defaults:
            c.execute("INSERT OR IGNORE INTO approval_ledger_accounts VALUES(?,?,?,?,1)", (uid, code, name, kind))

    @app.get("/v1/erp/ledger/accounts")
    def get_ledger_accounts(authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        with db() as c:
            setup(c, uid)
            rows = c.execute("SELECT account_code,name,account_type FROM approval_ledger_accounts WHERE user_id=? AND active=1 ORDER BY account_code", (uid,)).fetchall()
        return {"items": [{"code": r["account_code"], "name": r["name"], "type": r["account_type"]} for r in rows]}

    @app.post("/v1/erp/ledger/journals")
    def create_approval_journal(body: ApprovalJournalInput, authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        debit = sum(x.debit for x in body.lines)
        credit = sum(x.credit for x in body.lines)
        if debit <= 0 or abs(debit - credit) > 0.000001:
            raise HTTPException(422, "Journal must balance: total debit must equal total credit and be positive")
        for line in body.lines:
            if (line.debit > 0) == (line.credit > 0):
                raise HTTPException(422, "Each journal line must contain either debit or credit")
        now = int(time.time() * 1000)
        journal_id = uuid.uuid4().hex
        with db() as c:
            setup(c, uid)
            c.execute("BEGIN IMMEDIATE")
            for line in body.lines:
                if not c.execute("SELECT 1 FROM approval_ledger_accounts WHERE user_id=? AND account_code=? AND active=1", (uid, line.accountCode)).fetchone():
                    raise HTTPException(422, "Unknown account code: " + line.accountCode)
            payload = body.model_dump()
            c.execute("INSERT INTO approval_ledger_journals VALUES(?,?,?,?,?,?,?,?,?)",
                      (uid, journal_id, body.reference, body.description, body.currency,
                       debit, "PENDING_APPROVAL", encrypt_payload(payload), now))
        return {"id": journal_id, "status": "PENDING_APPROVAL", "posted": False,
                "totalDebit": debit, "totalCredit": credit, "currency": body.currency}

    @app.post("/v1/erp/ledger/journals/{journal_id}/approve")
    def approve_journal(journal_id: str, x_approval_token: str | None = Header(default=None),
                        authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        configured = os.environ.get("MOLIDO_LEDGER_APPROVAL_TOKEN", "")
        if len(configured) < 32:
            raise HTTPException(503, "Ledger approval token is not configured")
        if not x_approval_token or not hmac.compare_digest(configured, x_approval_token):
            raise HTTPException(403, "Ledger approval authorization failed")
        with db() as c:
            setup(c, uid)
            changed = c.execute("UPDATE approval_ledger_journals SET status='POSTED' WHERE user_id=? AND journal_id=? AND status='PENDING_APPROVAL'", (uid, journal_id)).rowcount
            if not changed:
                raise HTTPException(404, "Pending journal not found")
        return {"id": journal_id, "status": "POSTED", "posted": True}

    @app.get("/v1/erp/reports/financial")
    def financial_report(authorization: str | None = Header(default=None)):
        uid = current_user(authorization)
        with db() as c:
            setup(c, uid)
            rows = c.execute("SELECT payload FROM approval_ledger_journals WHERE user_id=? AND status='POSTED'", (uid,)).fetchall()
            totals = {}
            for row in rows:
                journal = decrypt_payload(row["payload"])
                for line in journal["lines"]:
                    pair = totals.setdefault(line["accountCode"], {"debit": 0.0, "credit": 0.0})
                    pair["debit"] += float(line["debit"])
                    pair["credit"] += float(line["credit"])
            accounts = c.execute("SELECT account_code,name,account_type FROM approval_ledger_accounts WHERE user_id=?", (uid,)).fetchall()
        return {"accounts": [{"code": a["account_code"], "name": a["name"], "type": a["account_type"],
                              **totals.get(a["account_code"], {"debit": 0.0, "credit": 0.0})} for a in accounts],
                "journalCount": len(rows), "basis": "posted double-entry journals only; pending approvals excluded"}
