from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field, field_validator


class FefoReserveInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    referenceType: Literal["SALES_ORDER", "INTERNAL_REQUEST"] = "SALES_ORDER"
    referenceId: str = Field(min_length=1, max_length=200)


class ReturnInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    direction: Literal["CUSTOMER_RETURN", "SUPPLIER_RETURN"]
    lotId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    referenceId: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=1000)


class ScrapInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    lotId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    reasonCode: Literal["EXPIRED", "DAMAGED", "QUALITY_REJECT", "CONTAMINATION", "PROCESS_LOSS", "OTHER"]
    reason: str = Field(min_length=3, max_length=1000)
    sourceReference: str = Field(min_length=2, max_length=200)


class CountLine(BaseModel):
    lotId: str = Field(min_length=1, max_length=200)
    countedQuantity: Decimal = Field(ge=0, max_digits=24, decimal_places=6)


class CycleCountInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    lines: list[CountLine] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=1000)


class ApprovalInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)


def register_advanced_inventory_control_routes(app, db, current_user) -> None:
    def schema(c):
        c.executescript("""
        CREATE TABLE IF NOT EXISTS adv_inventory_control_docs(
          user_id TEXT NOT NULL, document_id TEXT NOT NULL, document_type TEXT NOT NULL,
          idempotency_key TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,document_id), UNIQUE(user_id,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS adv_cycle_count_lines(
          user_id TEXT NOT NULL, document_id TEXT NOT NULL, lot_id TEXT NOT NULL,
          expected_quantity TEXT NOT NULL, counted_quantity TEXT NOT NULL,
          PRIMARY KEY(user_id,document_id,lot_id)
        );
        CREATE INDEX IF NOT EXISTS idx_adv_control_docs_state
          ON adv_inventory_control_docs(user_id,document_type,state);
        """)

    def actor(auth):
        return current_user(auth)

    def amount(value, allow_zero=False):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise HTTPException(422, "Invalid quantity")
        if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
            raise HTTPException(422, "Quantity must be a finite positive decimal")
        return result

    def balance(c, user, warehouse, lot):
        row = c.execute(
            "SELECT quantity FROM adv_stock_balances WHERE user_id=? AND warehouse_id=? AND lot_id=?",
            (user, warehouse, lot),
        ).fetchone()
        return Decimal(row["quantity"]) if row else Decimal("0")

    def reserved(c, user, warehouse, lot):
        rows = c.execute(
            "SELECT quantity FROM adv_reservations WHERE user_id=? AND warehouse_id=? AND lot_id=? AND state='ACTIVE'",
            (user, warehouse, lot),
        ).fetchall()
        return sum((Decimal(r["quantity"]) for r in rows), Decimal("0"))

    def write_balance(c, user, warehouse, lot, quantity, now):
        if quantity < 0:
            raise HTTPException(409, "Insufficient stock")
        c.execute("""INSERT INTO adv_stock_balances(user_id,warehouse_id,lot_id,quantity,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,lot_id)
          DO UPDATE SET quantity=excluded.quantity,updated_at=excluded.updated_at""",
          (user, warehouse, lot, format(quantity, "f"), now))

    def movement(c, user, key, kind, lot, product, warehouse, quantity, reference_type, reference_id, now):
        ident = uuid.uuid4().hex
        payload = json.dumps({"movementId": ident, "type": kind, "referenceId": reference_id},
                             separators=(",", ":"))
        c.execute("""INSERT INTO adv_stock_movements(movement_id,user_id,idempotency_key,movement_type,
          lot_id,product_id,source_warehouse_id,destination_warehouse_id,quantity,reference_type,
          reference_id,actor_id,created_at,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (ident,user,key,kind,lot,product,warehouse,None,format(quantity,"f"),
           reference_type,reference_id,user,now,payload))
        return ident

    def require_approval(token):
        expected = os.environ.get("MOLIDO_INVENTORY_APPROVAL_TOKEN", "")
        if len(expected) < 32 or not token or not secrets.compare_digest(expected, token):
            raise HTTPException(403, "Inventory approval is not configured or token is invalid")

    def get_doc(c, user, document_id, expected_type):
        row = c.execute("""SELECT * FROM adv_inventory_control_docs
          WHERE user_id=? AND document_id=? AND document_type=?""",
          (user, document_id, expected_type)).fetchone()
        if not row:
            raise HTTPException(404, "Inventory document not found in this account")
        return row

    @app.post("/v2/erp/inventory/fefo/reservations")
    def reserve_fefo(body: FefoReserveInput, authorization: str | None = Header(default=None)):
        user = actor(authorization)
        now = int(time.time() * 1000)
        requested = amount(body.quantity)
        with db() as c:
            schema(c)
            c.execute("BEGIN IMMEDIATE")
            duplicate = c.execute(
                "SELECT reservation_id FROM adv_reservations WHERE user_id=? AND idempotency_key=?",
                (user, body.idempotencyKey),
            ).fetchone()
            if duplicate:
                return {"status": "duplicate", "reservationIds": [duplicate["reservation_id"]]}
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user, body.warehouseId)).fetchone():
                raise HTTPException(404, "Warehouse not found in this account")
            if not c.execute("SELECT 1 FROM business_products WHERE user_id=? AND product_id=?",
                             (user, body.productId)).fetchone():
                raise HTTPException(404, "Product not found in this account")
            today = time.strftime("%Y-%m-%d", time.gmtime())
            rows = c.execute("""SELECT l.lot_id,l.product_id,l.expiry_date,b.quantity
              FROM adv_lots l JOIN adv_stock_balances b
                ON b.user_id=l.user_id AND b.lot_id=l.lot_id
              WHERE l.user_id=? AND l.product_id=? AND b.warehouse_id=?
                AND l.quality_state='RELEASED'
                AND (l.expiry_date IS NULL OR l.expiry_date>=?)
              ORDER BY CASE WHEN l.expiry_date IS NULL THEN 1 ELSE 0 END,
                l.expiry_date,l.received_date,l.created_at,l.lot_id""",
              (user, body.productId, body.warehouseId, today)).fetchall()
            candidates = []
            available_total = Decimal("0")
            for row in rows:
                on_hand = Decimal(row["quantity"])
                available = on_hand - reserved(c, user, body.warehouseId, row["lot_id"])
                if available > 0:
                    candidates.append((row, available))
                    available_total += available
            if available_total < requested:
                raise HTTPException(409, "Insufficient eligible stock for FEFO reservation")
            remaining = requested
            created = []
            for row, available in candidates:
                if remaining <= 0:
                    break
                take = min(remaining, available)
                reservation_id = uuid.uuid4().hex
                c.execute("INSERT INTO adv_reservations VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (reservation_id,user,(body.idempotencyKey if not created else body.idempotencyKey + ":" + reservation_id),row["lot_id"],
                   body.warehouseId,body.referenceType,body.referenceId,format(take,"f"),"ACTIVE",now))
                created.append({"reservationId":reservation_id,"lotId":row["lot_id"],
                                "quantity":format(take,"f"),"expiryDate":row["expiry_date"]})
                remaining -= take
        return {"status":"reserved","allocationPolicy":"FEFO","referenceId":body.referenceId,
                "quantity":format(requested,"f"),"allocations":created}

    @app.post("/v2/erp/inventory/returns")
    def create_return(body: ReturnInput, authorization: str | None = Header(default=None)):
        user = actor(authorization)
        now = int(time.time() * 1000)
        requested = amount(body.quantity)
        document_id = uuid.uuid4().hex
        with db() as c:
            schema(c)
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT document_id,state,payload FROM adv_inventory_control_docs WHERE user_id=? AND idempotency_key=?",
                            (user, body.idempotencyKey)).fetchone()
            if old:
                return {"status":"duplicate","documentId":old["document_id"],"state":old["state"]}
            lot = c.execute("""SELECT product_id,lot_code,unit,expiry_date,quality_state
              FROM adv_lots WHERE user_id=? AND lot_id=?""",(user,body.lotId)).fetchone()
            if not lot:
                raise HTTPException(404,"Lot not found in this account")
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            if body.direction == "SUPPLIER_RETURN":
                on_hand = balance(c,user,body.warehouseId,body.lotId)
                if on_hand - reserved(c,user,body.warehouseId,body.lotId) < requested:
                    raise HTTPException(409,"Supplier return exceeds unreserved stock")
            payload = {"direction":body.direction,"lotId":body.lotId,"warehouseId":body.warehouseId,
                       "quantity":format(requested,"f"),"referenceId":body.referenceId,
                       "reason":body.reason,"productId":lot["product_id"],"lotCode":lot["lot_code"],
                       "unit":lot["unit"],"expiryDate":lot["expiry_date"]}
            c.execute("INSERT INTO adv_inventory_control_docs VALUES(?,?,?,?,?,?,?,?)",
              (user,document_id,"RETURN",body.idempotencyKey,"PENDING_APPROVAL",
               json.dumps(payload,separators=(",",":")),now,now))
        return {"status":"pending_approval","documentId":document_id,"direction":body.direction}

    @app.post("/v2/erp/inventory/returns/{document_id}/approve")
    def approve_return(document_id: str, body: ApprovalInput,
                       x_approval_token: str | None = Header(default=None),
                       authorization: str | None = Header(default=None)):
        require_approval(x_approval_token)
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            prior=c.execute("SELECT result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
                            (user,body.idempotencyKey)).fetchone()
            if prior:
                return json.loads(prior["result"])
            doc=get_doc(c,user,document_id,"RETURN")
            if doc["state"]!="PENDING_APPROVAL":
                raise HTTPException(409,"Return is not pending approval")
            data=json.loads(doc["payload"]); q=Decimal(data["quantity"]); lot_id=data["lotId"]
            if data["direction"]=="SUPPLIER_RETURN":
                on_hand=balance(c,user,data["warehouseId"],lot_id)
                if on_hand-reserved(c,user,data["warehouseId"],lot_id)<q:
                    raise HTTPException(409,"Supplier return stock is no longer available")
                write_balance(c,user,data["warehouseId"],lot_id,on_hand-q,now)
                move=movement(c,user,body.idempotencyKey,"SUPPLIER_RETURN",lot_id,data["productId"],
                              data["warehouseId"],q,"SUPPLIER_RETURN",data["referenceId"],now)
                returned_lot_id=lot_id
            else:
                returned_lot_id=uuid.uuid4().hex
                code=f'{data["lotCode"]}-CR-{returned_lot_id[:8]}'
                c.execute("INSERT INTO adv_lots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (user,returned_lot_id,data["productId"],code,data["unit"],None,None,
                   time.strftime("%Y-%m-%d",time.gmtime()),data["expiryDate"],"OTHER",
                   data["referenceId"],"PENDING_INSPECTION",now))
                write_balance(c,user,data["warehouseId"],returned_lot_id,q,now)
                move=movement(c,user,body.idempotencyKey,"CUSTOMER_RETURN",returned_lot_id,
                              data["productId"],data["warehouseId"],q,"SALES_RETURN",data["referenceId"],now)
            result={"status":"approved","documentId":document_id,"lotId":returned_lot_id,"movementId":move}
            c.execute("UPDATE adv_inventory_control_docs SET state='POSTED',updated_at=? WHERE user_id=? AND document_id=?",
                      (now,user,document_id))
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,document_id,"RETURN_APPROVE",json.dumps(result),now))
        return result

    @app.post("/v2/erp/inventory/scrap")
    def create_scrap(body: ScrapInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); document_id=uuid.uuid4().hex
        q=amount(body.quantity)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT document_id,state FROM adv_inventory_control_docs WHERE user_id=? AND idempotency_key=?",
                          (user,body.idempotencyKey)).fetchone()
            if old:
                return {"status":"duplicate","documentId":old["document_id"],"state":old["state"]}
            lot=c.execute("SELECT product_id FROM adv_lots WHERE user_id=? AND lot_id=?",(user,body.lotId)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            on_hand=balance(c,user,body.warehouseId,body.lotId)
            if on_hand-reserved(c,user,body.warehouseId,body.lotId)<q:
                raise HTTPException(409,"Scrap exceeds unreserved stock")
            payload={"lotId":body.lotId,"warehouseId":body.warehouseId,"quantity":format(q,"f"),
                     "reasonCode":body.reasonCode,"reason":body.reason,"sourceReference":body.sourceReference,
                     "productId":lot["product_id"]}
            c.execute("INSERT INTO adv_inventory_control_docs VALUES(?,?,?,?,?,?,?,?)",
              (user,document_id,"SCRAP",body.idempotencyKey,"PENDING_APPROVAL",
               json.dumps(payload,separators=(",",":")),now,now))
        return {"status":"pending_approval","documentId":document_id}

    @app.post("/v2/erp/inventory/scrap/{document_id}/approve")
    def approve_scrap(document_id: str, body: ApprovalInput,
                      x_approval_token: str | None = Header(default=None),
                      authorization: str | None = Header(default=None)):
        require_approval(x_approval_token)
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            prior=c.execute("SELECT result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
                            (user,body.idempotencyKey)).fetchone()
            if prior: return json.loads(prior["result"])
            doc=get_doc(c,user,document_id,"SCRAP")
            if doc["state"]!="PENDING_APPROVAL": raise HTTPException(409,"Scrap is not pending approval")
            data=json.loads(doc["payload"]); q=Decimal(data["quantity"]); lot_id=data["lotId"]
            on_hand=balance(c,user,data["warehouseId"],lot_id)
            if on_hand-reserved(c,user,data["warehouseId"],lot_id)<q:
                raise HTTPException(409,"Scrap stock is no longer available")
            write_balance(c,user,data["warehouseId"],lot_id,on_hand-q,now)
            move=movement(c,user,body.idempotencyKey,"SCRAP",lot_id,data["productId"],data["warehouseId"],
                          q,"SCRAP",document_id,now)
            result={"status":"posted","documentId":document_id,"movementId":move,"quantity":format(q,"f")}
            c.execute("UPDATE adv_inventory_control_docs SET state='POSTED',updated_at=? WHERE user_id=? AND document_id=?",
                      (now,user,document_id))
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,document_id,"SCRAP_APPROVE",json.dumps(result),now))
        return result

    @app.post("/v2/erp/inventory/cycle-counts")
    def create_cycle_count(body: CycleCountInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); document_id=uuid.uuid4().hex
        if len({line.lotId for line in body.lines}) != len(body.lines):
            raise HTTPException(422,"A lot may appear only once in a count")
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT document_id,state FROM adv_inventory_control_docs WHERE user_id=? AND idempotency_key=?",
                          (user,body.idempotencyKey)).fetchone()
            if old: return {"status":"duplicate","documentId":old["document_id"],"state":old["state"]}
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            snapshots=[]
            for line in body.lines:
                counted=amount(line.countedQuantity,allow_zero=True)
                lot=c.execute("SELECT 1 FROM adv_lots WHERE user_id=? AND lot_id=?",(user,line.lotId)).fetchone()
                if not lot: raise HTTPException(404,"Count lot not found in this account")
                expected=balance(c,user,body.warehouseId,line.lotId)
                snapshots.append((line.lotId,expected,counted))
            payload={"warehouseId":body.warehouseId,"reason":body.reason}
            c.execute("INSERT INTO adv_inventory_control_docs VALUES(?,?,?,?,?,?,?,?)",
              (user,document_id,"CYCLE_COUNT",body.idempotencyKey,"PENDING_APPROVAL",
               json.dumps(payload,separators=(",",":")),now,now))
            for lot_id,expected,counted in snapshots:
                c.execute("INSERT INTO adv_cycle_count_lines VALUES(?,?,?,?,?)",
                          (user,document_id,lot_id,format(expected,"f"),format(counted,"f")))
        return {"status":"pending_approval","documentId":document_id,
                "variances":[{"lotId":lot,"expected":format(expected,"f"),
                              "counted":format(counted,"f"),"variance":format(counted-expected,"f")}
                             for lot,expected,counted in snapshots]}

    @app.post("/v2/erp/inventory/cycle-counts/{document_id}/approve")
    def approve_cycle_count(document_id: str, body: ApprovalInput,
                            x_approval_token: str | None = Header(default=None),
                            authorization: str | None = Header(default=None)):
        require_approval(x_approval_token)
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            prior=c.execute("SELECT result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
                            (user,body.idempotencyKey)).fetchone()
            if prior: return json.loads(prior["result"])
            doc=get_doc(c,user,document_id,"CYCLE_COUNT")
            if doc["state"]!="PENDING_APPROVAL": raise HTTPException(409,"Count is not pending approval")
            data=json.loads(doc["payload"]); warehouse=data["warehouseId"]
            lines=c.execute("SELECT * FROM adv_cycle_count_lines WHERE user_id=? AND document_id=?",
                            (user,document_id)).fetchall()
            results=[]
            for line in lines:
                expected=Decimal(line["expected_quantity"]); counted=Decimal(line["counted_quantity"])
                current=balance(c,user,warehouse,line["lot_id"])
                if current != expected:
                    raise HTTPException(409,"Stock changed after count snapshot; recount is required")
                active=reserved(c,user,warehouse,line["lot_id"])
                if counted < active:
                    raise HTTPException(409,"Counted stock is below active reservations")
                delta=counted-current
                if delta:
                    lot=c.execute("SELECT product_id FROM adv_lots WHERE user_id=? AND lot_id=?",
                                  (user,line["lot_id"])).fetchone()
                    write_balance(c,user,warehouse,line["lot_id"],counted,now)
                    move=movement(c,user,body.idempotencyKey+":"+line["lot_id"],
                                  "COUNT_ADJUSTMENT",line["lot_id"],lot["product_id"],warehouse,
                                  abs(delta),"CYCLE_COUNT",document_id,now)
                    results.append({"lotId":line["lot_id"],"variance":format(delta,"f"),"movementId":move})
            result={"status":"posted","documentId":document_id,"adjustments":results}
            c.execute("UPDATE adv_inventory_control_docs SET state='POSTED',updated_at=? WHERE user_id=? AND document_id=?",
                      (now,user,document_id))
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,document_id,"COUNT_APPROVE",json.dumps(result),now))
        return result
