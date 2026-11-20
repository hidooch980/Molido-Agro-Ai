from __future__ import annotations

import math
import time
import uuid
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


class SettlementInput(BaseModel):
    idempotencyKey: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=200)
    orderId: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, allow_inf_nan=False)
    method: Literal["CASH", "BANK", "BANK_TRANSFER", "CARD", "OTHER"] = "BANK"
    reference: str | None = Field(default=None, max_length=200)


def register_settlement_routes(app, db, current_user, encrypt_payload):
    def ensure(c):
        c.executescript("""
        CREATE TABLE IF NOT EXISTS journal_entries (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, reference TEXT NOT NULL,
          currency TEXT NOT NULL, debit_total REAL NOT NULL, credit_total REAL NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,journal_id), UNIQUE(user_id,reference)
        );
        CREATE TABLE IF NOT EXISTS journal_lines (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, line_no INTEGER NOT NULL,
          account_code TEXT NOT NULL, debit REAL NOT NULL, credit REAL NOT NULL,
          description TEXT NOT NULL, PRIMARY KEY(user_id,journal_id,line_no)
        );
        CREATE TABLE IF NOT EXISTS business_settlements (
          user_id TEXT NOT NULL, settlement_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          order_id TEXT NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL,
          reference TEXT, journal_id TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,settlement_id), UNIQUE(user_id,idempotency_key)
        );
        """)

    @app.post("/v1/erp/settlements")
    def create_settlement(body: SettlementInput, authorization: str | None = Header(default=None)):
        user = current_user(authorization)
        now = int(time.time() * 1000)
        settlement_id = uuid.uuid4().hex
        with db() as c:
            ensure(c)
            replay = c.execute(
                "SELECT settlement_id,order_id,amount,method,journal_id FROM business_settlements WHERE user_id=? AND idempotency_key=?",
                (user, body.idempotencyKey),
            ).fetchone()
            if replay:
                return {"id": replay["settlement_id"], "orderId": replay["order_id"],
                        "amount": replay["amount"], "method": replay["method"],
                        "journalId": replay["journal_id"], "status": "DUPLICATE"}
            order = c.execute(
                "SELECT order_type,status,total FROM business_orders WHERE user_id=? AND order_id=?",
                (user, body.orderId),
            ).fetchone()
            if not order:
                raise HTTPException(404, "Order not found")
            kind = order["order_type"]
            if order["status"] not in (("DELIVERED", "FULFILLED") if kind == "SALES" else ("RECEIVED", "FULFILLED")):
                raise HTTPException(409, "Order must be delivered or received before settlement")
            paid = c.execute(
                "SELECT COALESCE(SUM(amount),0) amount FROM business_settlements WHERE user_id=? AND order_id=?",
                (user, body.orderId),
            ).fetchone()["amount"]
            outstanding = float(order["total"]) - float(paid)
            if body.amount > outstanding + 0.000001:
                raise HTTPException(409, "Settlement exceeds outstanding order balance")
            journal_id = uuid.uuid4().hex
            reference = "SETTLEMENT-" + body.idempotencyKey
            cash_account = "1000-CASH" if body.method == "CASH" else "1010-BANK"
            if kind == "SALES":
                debit_account, credit_account = cash_account, "1100-RECEIVABLE"
                debit, credit = body.amount, body.amount
                description = "Customer settlement"
            else:
                debit_account, credit_account = "2100-PAYABLE", cash_account
                debit, credit = body.amount, body.amount
                description = "Supplier settlement"
            payload = {"description": description, "orderId": body.orderId,
                       "settlementId": settlement_id, "method": body.method}
            c.execute("INSERT INTO journal_entries VALUES(?,?,?,?,?,?,?,?)",
                      (user, journal_id, reference, "IRR", debit, credit,
                       encrypt_payload(payload), now))
            c.execute("INSERT INTO journal_lines VALUES(?,?,?,?,?,?,?)",
                      (user, journal_id, 1, debit_account,
                       body.amount if kind == "SALES" else 0,
                       body.amount if kind == "PURCHASE" else 0, description))
            c.execute("INSERT INTO journal_lines VALUES(?,?,?,?,?,?,?)",
                      (user, journal_id, 2, credit_account,
                       body.amount if kind == "PURCHASE" else 0,
                       body.amount if kind == "SALES" else 0, description))
            c.execute("INSERT INTO business_settlements VALUES(?,?,?,?,?,?,?,?,?)",
                      (user, settlement_id, body.idempotencyKey, body.orderId,
                       body.amount, body.method, body.reference, journal_id, now))
        return {"id": settlement_id, "orderId": body.orderId, "amount": body.amount,
                "method": body.method, "journalId": journal_id, "status": "POSTED",
                "outstanding": max(0.0, outstanding - body.amount)}

    @app.get("/v1/erp/settlements")
    def list_settlements(orderId: str | None = None, authorization: str | None = Header(default=None)):
        user = current_user(authorization)
        with db() as c:
            ensure(c)
            rows = c.execute(
                "SELECT settlement_id,order_id,amount,method,reference,journal_id,created_at FROM business_settlements WHERE user_id=? AND (? IS NULL OR order_id=?) ORDER BY created_at DESC LIMIT 500",
                (user, orderId, orderId),
            ).fetchall()
        return {"items": [{"id": r["settlement_id"], "orderId": r["order_id"],
                           "amount": r["amount"], "method": r["method"],
                           "reference": r["reference"], "journalId": r["journal_id"],
                           "createdAtEpochMillis": r["created_at"]} for r in rows]}
