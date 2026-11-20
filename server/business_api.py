from __future__ import annotations

import json
import math
import time
import uuid
from typing import Any, Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


class PartyInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=2, max_length=200)
    unit: str = Field(min_length=1, max_length=32)
    category: str = Field(default="AGRICULTURAL_PRODUCT", max_length=80)
    salePrice: float = Field(default=0, ge=0, allow_inf_nan=False)
    purchasePrice: float = Field(default=0, ge=0, allow_inf_nan=False)


class StockMovementInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    movementType: Literal["RECEIPT", "ISSUE", "ADJUSTMENT"]
    quantity: float = Field(gt=0, allow_inf_nan=False)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class OrderLine(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    unitPrice: float = Field(ge=0, allow_inf_nan=False)


class OrderInput(BaseModel):
    partyId: str = Field(min_length=1, max_length=200)
    lines: list[OrderLine] = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class FinanceEntryInput(BaseModel):
    direction: Literal["INCOME", "EXPENSE"]
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    category: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=2, max_length=1000)
    relatedPartyId: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=200)


def register_business_routes(app, db, current_user, encrypt_payload, decrypt_payload) -> None:
    """Account-isolated first CRM/ERP transaction APIs. Finance remains unposted pending approval."""

    def ensure_tables(connection) -> None:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS business_parties (
            user_id TEXT NOT NULL, party_type TEXT NOT NULL, party_id TEXT NOT NULL,
            payload TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, party_type, party_id)
        );
        CREATE TABLE IF NOT EXISTS business_products (
            user_id TEXT NOT NULL, product_id TEXT NOT NULL, sku TEXT NOT NULL,
            payload TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, product_id), UNIQUE(user_id, sku)
        );
        CREATE TABLE IF NOT EXISTS inventory_balances (
            user_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, product_id TEXT NOT NULL,
            quantity REAL NOT NULL CHECK(quantity >= 0), updated_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, warehouse_id, product_id)
        );
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL, warehouse_id TEXT NOT NULL, product_id TEXT NOT NULL,
            movement_type TEXT NOT NULL, quantity REAL NOT NULL, payload TEXT NOT NULL,
            created_at INTEGER NOT NULL, UNIQUE(user_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS business_orders (
            user_id TEXT NOT NULL, order_id TEXT NOT NULL, order_type TEXT NOT NULL,
            party_id TEXT NOT NULL, status TEXT NOT NULL, total REAL NOT NULL,
            payload TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, order_id)
        );
        CREATE TABLE IF NOT EXISTS finance_entries (
            user_id TEXT NOT NULL, entry_id TEXT NOT NULL, direction TEXT NOT NULL,
            amount REAL NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, entry_id)
        );
        CREATE TABLE IF NOT EXISTS business_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_business_parties_lookup
            ON business_parties(user_id, party_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_business_orders_lookup
            ON business_orders(user_id, order_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_inventory_movements_lookup
            ON inventory_movements(user_id, warehouse_id, created_at DESC);
        """)

    def actor(authorization: str | None) -> str:
        return current_user(authorization)

    def audit(connection, uid: str, action: str, entity_type: str, entity_id: str) -> None:
        connection.execute(
            "INSERT INTO business_audit_log(user_id,action,entity_type,entity_id,created_at) VALUES(?,?,?,?,?)",
            (uid, action, entity_type, entity_id, int(time.time() * 1000)),
        )

    def create_party(party_type: str, body: PartyInput, authorization: str | None):
        uid = actor(authorization)
        party_id = uuid.uuid4().hex
        now = int(time.time() * 1000)
        payload = body.model_dump()
        with db() as connection:
            ensure_tables(connection)
            connection.execute(
                "INSERT INTO business_parties VALUES(?,?,?,?,?)",
                (uid, party_type, party_id, encrypt_payload(payload), now),
            )
            audit(connection, uid, "CREATE", party_type, party_id)
        return {"id": party_id, "type": party_type, "createdAtEpochMillis": now, **payload}

    def list_parties(party_type: str, authorization: str | None, limit: int = 100):
        uid = actor(authorization)
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        with db() as connection:
            ensure_tables(connection)
            rows = connection.execute(
                "SELECT party_id,payload,created_at FROM business_parties WHERE user_id=? AND party_type=? ORDER BY created_at DESC LIMIT ?",
                (uid, party_type, limit),
            ).fetchall()
        return {"items": [
            {"id": row["party_id"], "type": party_type, "createdAtEpochMillis": row["created_at"],
             **decrypt_payload(row["payload"])} for row in rows
        ]}

    @app.post("/v1/crm/customers")
    def create_customer(body: PartyInput, authorization: str | None = Header(default=None)):
        return create_party("CUSTOMER", body, authorization)

    @app.get("/v1/crm/customers")
    def get_customers(limit: int = 100, authorization: str | None = Header(default=None)):
        return list_parties("CUSTOMER", authorization, limit)

    @app.post("/v1/erp/suppliers")
    def create_supplier(body: PartyInput, authorization: str | None = Header(default=None)):
        return create_party("SUPPLIER", body, authorization)

    @app.get("/v1/erp/suppliers")
    def get_suppliers(limit: int = 100, authorization: str | None = Header(default=None)):
        return list_parties("SUPPLIER", authorization, limit)

    @app.post("/v1/erp/products")
    def create_product(body: ProductInput, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        product_id = uuid.uuid4().hex
        now = int(time.time() * 1000)
        payload = body.model_dump()
        with db() as connection:
            ensure_tables(connection)
            try:
                connection.execute(
                    "INSERT INTO business_products VALUES(?,?,?,?,?)",
                    (uid, product_id, body.sku, encrypt_payload(payload), now),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise HTTPException(409, "SKU already exists in this account")
                raise
            audit(connection, uid, "CREATE", "PRODUCT", product_id)
        return {"id": product_id, "createdAtEpochMillis": now, **payload}

    @app.get("/v1/erp/products")
    def get_products(limit: int = 100, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        with db() as connection:
            ensure_tables(connection)
            rows = connection.execute(
                "SELECT product_id,payload,created_at FROM business_products WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return {"items": [
            {"id": row["product_id"], "createdAtEpochMillis": row["created_at"],
             **decrypt_payload(row["payload"])} for row in rows
        ]}

    @app.post("/v1/erp/inventory/movements")
    def post_inventory_movement(body: StockMovementInput, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        now = int(time.time() * 1000)
        with db() as connection:
            ensure_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT id FROM inventory_movements WHERE user_id=? AND idempotency_key=?",
                (uid, body.idempotencyKey),
            ).fetchone()
            if duplicate:
                return {"status": "duplicate", "movementId": duplicate["id"]}
            product = connection.execute(
                "SELECT 1 FROM business_products WHERE user_id=? AND product_id=?",
                (uid, body.productId),
            ).fetchone()
            if not product:
                raise HTTPException(404, "Product not found in this account")
            current = connection.execute(
                "SELECT quantity FROM inventory_balances WHERE user_id=? AND warehouse_id=? AND product_id=?",
                (uid, body.warehouseId, body.productId),
            ).fetchone()
            old_qty = float(current["quantity"]) if current else 0.0
            delta = body.quantity if body.movementType == "RECEIPT" else (
                -body.quantity if body.movementType == "ISSUE" else body.quantity - old_qty
            )
            new_qty = old_qty + delta
            if not math.isfinite(new_qty) or new_qty < 0:
                raise HTTPException(409, "Insufficient stock for this movement")
            connection.execute(
                """INSERT INTO inventory_balances VALUES(?,?,?,?,?)
                   ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE
                   SET quantity=excluded.quantity,updated_at=excluded.updated_at""",
                (uid, body.warehouseId, body.productId, new_qty, now),
            )
            cursor = connection.execute(
                """INSERT INTO inventory_movements
                   (user_id,idempotency_key,warehouse_id,product_id,movement_type,quantity,payload,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (uid, body.idempotencyKey, body.warehouseId, body.productId,
                 body.movementType, body.quantity, encrypt_payload(body.model_dump()), now),
            )
            audit(connection, uid, body.movementType, "INVENTORY", str(cursor.lastrowid))
        return {"status": "applied", "movementId": cursor.lastrowid, "balance": new_qty}

    @app.get("/v1/erp/inventory/balances")
    def get_inventory_balances(warehouseId: str | None = None, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        with db() as connection:
            ensure_tables(connection)
            if warehouseId:
                rows = connection.execute(
                    "SELECT warehouse_id,product_id,quantity,updated_at FROM inventory_balances WHERE user_id=? AND warehouse_id=? ORDER BY product_id",
                    (uid, warehouseId),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT warehouse_id,product_id,quantity,updated_at FROM inventory_balances WHERE user_id=? ORDER BY warehouse_id,product_id",
                    (uid,),
                ).fetchall()
        return {"items": [
            {"warehouseId": r["warehouse_id"], "productId": r["product_id"],
             "quantity": r["quantity"], "updatedAtEpochMillis": r["updated_at"]} for r in rows
        ]}

    def create_order(order_type: str, party_type: str, body: OrderInput, authorization: str | None):
        uid = actor(authorization)
        order_id = uuid.uuid4().hex
        now = int(time.time() * 1000)
        with db() as connection:
            ensure_tables(connection)
            party = connection.execute(
                "SELECT 1 FROM business_parties WHERE user_id=? AND party_type=? AND party_id=?",
                (uid, party_type, body.partyId),
            ).fetchone()
            if not party:
                raise HTTPException(404, f"{party_type.lower()} not found in this account")
            lines = []
            total = 0.0
            for line in body.lines:
                product = connection.execute(
                    "SELECT payload FROM business_products WHERE user_id=? AND product_id=?",
                    (uid, line.productId),
                ).fetchone()
                if not product:
                    raise HTTPException(404, "Product not found in this account")
                line_total = line.quantity * line.unitPrice
                if not math.isfinite(line_total) or not math.isfinite(total + line_total):
                    raise HTTPException(422, "Order total is outside supported numeric range")
                total += line_total
                lines.append({**line.model_dump(), "lineTotal": line_total})
            payload = {"partyId": body.partyId, "lines": lines, "notes": body.notes}
            connection.execute(
                "INSERT INTO business_orders VALUES(?,?,?,?,?,?,?,?)",
                (uid, order_id, order_type, body.partyId, "DRAFT", total, encrypt_payload(payload), now),
            )
            audit(connection, uid, "CREATE", order_type, order_id)
        return {"id": order_id, "type": order_type, "status": "DRAFT", "total": total,
                "currency": "IRR", "createdAtEpochMillis": now, **payload}

    @app.post("/v1/erp/sales/orders")
    def create_sales_order(body: OrderInput, authorization: str | None = Header(default=None)):
        return create_order("SALES", "CUSTOMER", body, authorization)

    @app.post("/v1/erp/purchase/orders")
    def create_purchase_order(body: OrderInput, authorization: str | None = Header(default=None)):
        return create_order("PURCHASE", "SUPPLIER", body, authorization)

    @app.get("/v1/erp/orders")
    def get_orders(orderType: Literal["SALES", "PURCHASE"] | None = None,
                   limit: int = 100, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        with db() as connection:
            ensure_tables(connection)
            if orderType:
                rows = connection.execute(
                    "SELECT order_id,order_type,party_id,status,total,payload,created_at FROM business_orders WHERE user_id=? AND order_type=? ORDER BY created_at DESC LIMIT ?",
                    (uid, orderType, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT order_id,order_type,party_id,status,total,payload,created_at FROM business_orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (uid, limit),
                ).fetchall()
        return {"items": [
            {"id": r["order_id"], "type": r["order_type"], "partyId": r["party_id"],
             "status": r["status"], "total": r["total"], "payload": decrypt_payload(r["payload"]),
             "createdAtEpochMillis": r["created_at"]} for r in rows
        ]}

    @app.post("/v1/erp/finance/entries")
    def create_finance_entry(body: FinanceEntryInput, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        entry_id = uuid.uuid4().hex
        now = int(time.time() * 1000)
        if body.relatedPartyId:
            with db() as connection:
                ensure_tables(connection)
                exists = connection.execute(
                    "SELECT 1 FROM business_parties WHERE user_id=? AND party_id=?",
                    (uid, body.relatedPartyId),
                ).fetchone()
                if not exists:
                    raise HTTPException(404, "Related party not found in this account")
        payload = body.model_dump()
        with db() as connection:
            ensure_tables(connection)
            connection.execute(
                "INSERT INTO finance_entries VALUES(?,?,?,?,?,?,?,?)",
                (uid, entry_id, body.direction, body.amount, body.currency, "PENDING_APPROVAL",
                 encrypt_payload(payload), now),
            )
            audit(connection, uid, "CREATE_PENDING", "FINANCE_ENTRY", entry_id)
        return {"id": entry_id, "status": "PENDING_APPROVAL", "posted": False,
                "createdAtEpochMillis": now, **payload}

    @app.get("/v1/erp/finance/entries")
    def get_finance_entries(limit: int = 100, authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        if not 1 <= limit <= 500:
            raise HTTPException(422, "limit must be between 1 and 500")
        with db() as connection:
            ensure_tables(connection)
            rows = connection.execute(
                "SELECT entry_id,direction,amount,currency,status,payload,created_at FROM finance_entries WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        return {"items": [
            {"id": r["entry_id"], "direction": r["direction"], "amount": r["amount"],
             "currency": r["currency"], "status": r["status"], "posted": False,
             "payload": decrypt_payload(r["payload"]), "createdAtEpochMillis": r["created_at"]}
            for r in rows
        ]}

    @app.get("/v1/crm-erp/summary")
    def crm_erp_summary(authorization: str | None = Header(default=None)):
        uid = actor(authorization)
        with db() as connection:
            ensure_tables(connection)
            counts = {}
            for key, table, where in [
                ("customers", "business_parties", "party_type='CUSTOMER'"),
                ("suppliers", "business_parties", "party_type='SUPPLIER'"),
                ("products", "business_products", "1=1"),
                ("salesOrders", "business_orders", "order_type='SALES'"),
                ("purchaseOrders", "business_orders", "order_type='PURCHASE'"),
                ("pendingFinanceEntries", "finance_entries", "status='PENDING_APPROVAL'"),
            ]:
                counts[key] = connection.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=? AND {where}", (uid,)
                ).fetchone()["n"]
            counts["inventoryProductBalances"] = connection.execute(
                "SELECT COUNT(*) AS n FROM inventory_balances WHERE user_id=?", (uid,)
            ).fetchone()["n"]
        return {"counts": counts, "financialPostingEnabled": False,
                "note": "Finance entries are pending approval and are not posted to a ledger."}
