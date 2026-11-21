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
    accountingAmount: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=2)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class ScrapInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    lotId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    reasonCode: Literal["EXPIRED", "DAMAGED", "QUALITY_REJECT", "CONTAMINATION", "PROCESS_LOSS", "OTHER"]
    reason: str = Field(min_length=3, max_length=1000)
    sourceReference: str = Field(min_length=2, max_length=200)
    greenhouseId: str | None = Field(default=None, max_length=200)
    cropCycleId: str | None = Field(default=None, max_length=200)
    unitCost: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


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


class OrderActionInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)


class PurchaseReceiptLine(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    lotCode: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    unit: str = Field(min_length=1, max_length=24)
    expiryDate: str | None = None
    receivedDate: str | None = None


class PurchaseReceiptInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    lines: list[PurchaseReceiptLine] = Field(min_length=1, max_length=200)


class HarvestLotInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    harvestId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    lotCode: str = Field(min_length=1, max_length=100)
    expiryDate: str | None = None


def register_advanced_inventory_control_routes(app, db, current_user, decrypt_payload, encrypt_payload) -> None:
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
        CREATE TABLE IF NOT EXISTS crop_cost_entries(
          entry_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          greenhouse_id TEXT NOT NULL, crop_cycle_id TEXT NOT NULL, category TEXT NOT NULL,
          amount TEXT NOT NULL, currency TEXT NOT NULL, quantity TEXT, unit TEXT,
          allocation_method TEXT NOT NULL, source_reference TEXT NOT NULL,
          notes TEXT NOT NULL, actor_id TEXT NOT NULL, created_at INTEGER NOT NULL,
          approval_status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL', approved_by TEXT, approved_at INTEGER,
          UNIQUE(user_id,idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_crop_cost_cycle ON crop_cost_entries(user_id,crop_cycle_id,created_at);
        CREATE TABLE IF NOT EXISTS approval_ledger_accounts(
          user_id TEXT NOT NULL, account_code TEXT NOT NULL, name TEXT NOT NULL,
          account_type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(user_id,account_code)
        );
        CREATE TABLE IF NOT EXISTS approval_ledger_journals(
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, reference TEXT,
          description TEXT NOT NULL, currency TEXT NOT NULL, total_debit REAL NOT NULL,
          status TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,journal_id)
        );
        CREATE TABLE IF NOT EXISTS crop_cost_runs(
          run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          greenhouse_id TEXT NOT NULL, crop_cycle_id TEXT NOT NULL, version INTEGER NOT NULL,
          currency TEXT NOT NULL, output_quantity TEXT NOT NULL, output_unit TEXT NOT NULL,
          capitalizable_cost TEXT NOT NULL, abnormal_waste_cost TEXT NOT NULL,
          created_at INTEGER NOT NULL, UNIQUE(user_id,idempotency_key),
          UNIQUE(user_id,crop_cycle_id,version)
        );
        CREATE TABLE IF NOT EXISTS crop_cost_allocations(
          run_id TEXT NOT NULL, user_id TEXT NOT NULL, harvest_id TEXT NOT NULL,
          quantity TEXT NOT NULL, unit TEXT NOT NULL, allocated_cost TEXT NOT NULL,
          cost_per_unit TEXT NOT NULL, PRIMARY KEY(run_id,harvest_id),
          FOREIGN KEY(run_id) REFERENCES crop_cost_runs(run_id)
        );
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

    def replay_control_action(c, user, key, expected_action, document_id):
        prior = c.execute(
            "SELECT reservation_id,action,result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
            (user, key),
        ).fetchone()
        if not prior:
            return None
        if prior["action"] != expected_action or prior["reservation_id"] != document_id:
            raise HTTPException(409, "Idempotency key already belongs to a different action or document")
        return json.loads(prior["result"])

    def ensure_crop_cycle(c, user, greenhouse_id, crop_cycle_id):
        greenhouse = c.execute(
            "SELECT 1 FROM records WHERE user_id=? AND entity_type='greenhouse' AND entity_id=? AND deleted=0",
            (user, greenhouse_id),
        ).fetchone()
        cycle = c.execute(
            "SELECT payload FROM records WHERE user_id=? AND entity_type='crop_cycle' AND entity_id=? AND deleted=0",
            (user, crop_cycle_id),
        ).fetchone()
        if not greenhouse or not cycle:
            raise HTTPException(404, "Greenhouse or crop cycle not found in this account")
        if decrypt_payload(cycle["payload"]).get("greenhouseId") != greenhouse_id:
            raise HTTPException(409, "Crop cycle does not belong to the supplied greenhouse")

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
                       "unit":lot["unit"],"expiryDate":lot["expiry_date"],
                       "accountingAmount":format(body.accountingAmount,"f") if body.accountingAmount is not None else None,
                       "currency":body.currency}
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
            replay = replay_control_action(c,user,body.idempotencyKey,"RETURN_APPROVE",document_id)
            if replay is not None:
                return replay
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
            journal_id = None
            if data.get("accountingAmount") is not None:
                ledger_accounts = [
                    ("1100","حساب‌های دریافتنی","ASSET"),
                    ("1200","موجودی کالا","ASSET"),
                    ("2000","حساب‌های پرداختنی","LIABILITY"),
                    ("4100","مرجوعی فروش و تخفیفات","REVENUE"),
                ]
                for code,name,kind in ledger_accounts:
                    c.execute("INSERT OR IGNORE INTO approval_ledger_accounts VALUES(?,?,?,?,1)",(user,code,name,kind))
                value = Decimal(data["accountingAmount"])
                if data["direction"] == "CUSTOMER_RETURN":
                    journal_lines = [
                        {"accountCode":"4100","debit":float(value),"credit":0,"description":"Customer sales return"},
                        {"accountCode":"1100","debit":0,"credit":float(value),"description":"Customer credit note"},
                    ]
                    journal_description = "Customer return credit note"
                else:
                    journal_lines = [
                        {"accountCode":"2000","debit":float(value),"credit":0,"description":"Supplier return payable adjustment"},
                        {"accountCode":"1200","debit":0,"credit":float(value),"description":"Supplier return inventory valuation"},
                    ]
                    journal_description = "Supplier return payable and inventory adjustment"
                journal_id = uuid.uuid4().hex
                journal_payload = {"description":journal_description,"reference":document_id,
                                   "currency":data["currency"],"lines":journal_lines}
                c.execute("INSERT INTO approval_ledger_journals VALUES(?,?,?,?,?,?,?,?,?)",
                          (user,journal_id,document_id,journal_description,data["currency"],float(value),
                           "PENDING_APPROVAL",encrypt_payload(journal_payload),now))
            result={"status":"approved","documentId":document_id,"lotId":returned_lot_id,"movementId":move,
                    "accountingStatus":"PENDING_LEDGER_APPROVAL" if journal_id else "VALUATION_REQUIRED",
                    "journalId":journal_id}
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
            lot=c.execute("SELECT product_id,unit FROM adv_lots WHERE user_id=? AND lot_id=?",(user,body.lotId)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            if body.unitCost is not None:
                if not body.greenhouseId or not body.cropCycleId:
                    raise HTTPException(422,"Greenhouse and crop cycle are required when scrap cost is supplied")
                ensure_crop_cycle(c,user,body.greenhouseId,body.cropCycleId)
            elif body.greenhouseId or body.cropCycleId:
                raise HTTPException(422,"A unit cost is required to create a crop-cycle waste cost entry")
            on_hand=balance(c,user,body.warehouseId,body.lotId)
            if on_hand-reserved(c,user,body.warehouseId,body.lotId)<q:
                raise HTTPException(409,"Scrap exceeds unreserved stock")
            payload={"lotId":body.lotId,"warehouseId":body.warehouseId,"quantity":format(q,"f"),
                     "reasonCode":body.reasonCode,"reason":body.reason,"sourceReference":body.sourceReference,
                     "productId":lot["product_id"],"unit":lot["unit"],
                     "greenhouseId":body.greenhouseId,"cropCycleId":body.cropCycleId,
                     "unitCost":format(body.unitCost,"f") if body.unitCost is not None else None,
                     "currency":body.currency}
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
            replay = replay_control_action(c,user,body.idempotencyKey,"SCRAP_APPROVE",document_id)
            if replay is not None:
                return replay
            doc=get_doc(c,user,document_id,"SCRAP")
            if doc["state"]!="PENDING_APPROVAL": raise HTTPException(409,"Scrap is not pending approval")
            data=json.loads(doc["payload"]); q=Decimal(data["quantity"]); lot_id=data["lotId"]
            on_hand=balance(c,user,data["warehouseId"],lot_id)
            if on_hand-reserved(c,user,data["warehouseId"],lot_id)<q:
                raise HTTPException(409,"Scrap stock is no longer available")
            write_balance(c,user,data["warehouseId"],lot_id,on_hand-q,now)
            move=movement(c,user,body.idempotencyKey,"SCRAP",lot_id,data["productId"],data["warehouseId"],
                          q,"SCRAP",document_id,now)
            cost_entry_id = None
            if data.get("unitCost") is not None:
                cost_entry_id = uuid.uuid4().hex
                cost_amount = q * Decimal(data["unitCost"])
                c.execute("""INSERT INTO crop_cost_entries(
                  entry_id,user_id,idempotency_key,greenhouse_id,crop_cycle_id,category,amount,currency,
                  quantity,unit,allocation_method,source_reference,notes,actor_id,created_at,approval_status)
                  VALUES(?,?,?,?,?,'WASTE_ABNORMAL',?,?,?,?,?,?,?,?,?,'PENDING_APPROVAL')""",
                  (cost_entry_id,user,"inventory-scrap-cost:"+document_id,data["greenhouseId"],data["cropCycleId"],
                   format(cost_amount,"f"),data["currency"],format(q,"f"),data["unit"],"OUTPUT_QUANTITY",
                   "INVENTORY_SCRAP:"+document_id,
                   f'{data["reasonCode"]}: {data["reason"]}; source={data["sourceReference"]}',user,now))
            result={"status":"posted","documentId":document_id,"movementId":move,"quantity":format(q,"f"),
                    "cropCostStatus":"PENDING_COST_APPROVAL" if cost_entry_id else "NOT_LINKED",
                    "costEntryId":cost_entry_id}
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
                stock_row=c.execute(
                    "SELECT quantity FROM adv_stock_balances WHERE user_id=? AND warehouse_id=? AND lot_id=?",
                    (user,body.warehouseId,line.lotId),
                ).fetchone()
                if not stock_row:
                    raise HTTPException(404,"Lot has no stock record in the selected warehouse")
                expected=Decimal(stock_row["quantity"])
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
            replay = replay_control_action(c,user,body.idempotencyKey,"COUNT_APPROVE",document_id)
            if replay is not None:
                return replay
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
                                  ("COUNT_INCREASE" if delta > 0 else "COUNT_DECREASE"),
                                  line["lot_id"],lot["product_id"],warehouse,
                                  abs(delta),"CYCLE_COUNT",document_id,now)
                    results.append({"lotId":line["lot_id"],"variance":format(delta,"f"),"movementId":move})
            result={"status":"posted","documentId":document_id,"adjustments":results}
            c.execute("UPDATE adv_inventory_control_docs SET state='POSTED',updated_at=? WHERE user_id=? AND document_id=?",
                      (now,user,document_id))
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,document_id,"COUNT_APPROVE",json.dumps(result),now))
        return result


    @app.post("/v2/erp/inventory/orders/{order_id}/fefo-reservations")
    def reserve_sales_order_fefo(order_id: str, body: OrderActionInput,
                                 authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            replay=c.execute("SELECT result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
                             (user,body.idempotencyKey)).fetchone()
            if replay: return json.loads(replay["result"])
            order=c.execute("SELECT order_type,status,payload FROM business_orders WHERE user_id=? AND order_id=?",
                            (user,order_id)).fetchone()
            if not order: raise HTTPException(404,"Sales order not found in this account")
            if order["order_type"]!="SALES" or order["status"] not in ("DRAFT","CONFIRMED"):
                raise HTTPException(409,"Only confirmed sales orders can reserve FEFO stock")
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            payload=decrypt_payload(order["payload"]); allocations=[]
            for index,line in enumerate(payload.get("lines",[])):
                requested=amount(line["quantity"])
                rows=c.execute("""SELECT l.lot_id,l.expiry_date,b.quantity
                  FROM adv_lots l JOIN adv_stock_balances b
                    ON b.user_id=l.user_id AND b.lot_id=l.lot_id
                  WHERE l.user_id=? AND l.product_id=? AND b.warehouse_id=?
                    AND l.quality_state='RELEASED'
                    AND (l.expiry_date IS NULL OR l.expiry_date>=?)
                  ORDER BY CASE WHEN l.expiry_date IS NULL THEN 1 ELSE 0 END,
                    l.expiry_date,l.received_date,l.created_at,l.lot_id""",
                  (user,line["productId"],body.warehouseId,time.strftime("%Y-%m-%d",time.gmtime()))).fetchall()
                available_rows=[]; total=Decimal("0")
                for row in rows:
                    free=Decimal(row["quantity"])-reserved(c,user,body.warehouseId,row["lot_id"])
                    if free>0:
                        available_rows.append((row,free)); total+=free
                if total<requested:
                    raise HTTPException(409,f"Insufficient FEFO-eligible stock for order line {index+1}")
                remaining=requested
                for row,free in available_rows:
                    if remaining<=0: break
                    take=min(remaining,free); reservation_id=uuid.uuid4().hex
                    key=f"{body.idempotencyKey}:{index}:{reservation_id}"
                    c.execute("INSERT INTO adv_reservations VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (reservation_id,user,key,row["lot_id"],body.warehouseId,"SALES_ORDER",
                       order_id,format(take,"f"),"ACTIVE",now))
                    allocations.append({"line":index,"reservationId":reservation_id,"lotId":row["lot_id"],
                                        "quantity":format(take,"f"),"expiryDate":row["expiry_date"]})
                    remaining-=take
            result={"status":"reserved","orderId":order_id,"allocationPolicy":"FEFO","allocations":allocations}
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,order_id,"ORDER_FEFO_RESERVE",json.dumps(result),now))
        return result

    @app.post("/v2/erp/inventory/orders/{order_id}/fulfill")
    def fulfill_sales_order_inventory(order_id: str, body: ApprovalInput,
                                      authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            replay=c.execute("SELECT result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",
                             (user,body.idempotencyKey)).fetchone()
            if replay: return json.loads(replay["result"])
            order=c.execute("SELECT order_type,status FROM business_orders WHERE user_id=? AND order_id=?",
                            (user,order_id)).fetchone()
            if not order: raise HTTPException(404,"Sales order not found in this account")
            if order["order_type"]!="SALES" or order["status"]!="CONFIRMED":
                raise HTTPException(409,"Only confirmed sales orders can be fulfilled")
            reservations=c.execute("""SELECT * FROM adv_reservations
              WHERE user_id=? AND reference_type='SALES_ORDER' AND reference_id=? AND state='ACTIVE'
              ORDER BY created_at,reservation_id""",(user,order_id)).fetchall()
            if not reservations: raise HTTPException(409,"No active FEFO reservations exist for this order")
            shipped=[]
            for reservation in reservations:
                lot=c.execute("SELECT product_id,quality_state,expiry_date FROM adv_lots WHERE user_id=? AND lot_id=?",
                              (user,reservation["lot_id"])).fetchone()
                if not lot or lot["quality_state"]!="RELEASED":
                    raise HTTPException(409,"A reserved lot is no longer released")
                if lot["expiry_date"] and lot["expiry_date"]<time.strftime("%Y-%m-%d",time.gmtime()):
                    raise HTTPException(409,"Expired lot cannot be shipped")
                q=Decimal(reservation["quantity"]); on_hand=balance(c,user,reservation["warehouse_id"],reservation["lot_id"])
                if on_hand<q: raise HTTPException(409,"Reserved stock is no longer available")
                write_balance(c,user,reservation["warehouse_id"],reservation["lot_id"],on_hand-q,now)
                move=movement(c,user,body.idempotencyKey+":"+reservation["reservation_id"],
                              "SHIPMENT_ISSUE",reservation["lot_id"],lot["product_id"],
                              reservation["warehouse_id"],q,"SALES_ORDER",order_id,now)
                c.execute("UPDATE adv_reservations SET state='FULFILLED' WHERE user_id=? AND reservation_id=? AND state='ACTIVE'",
                          (user,reservation["reservation_id"]))
                shipped.append({"lotId":reservation["lot_id"],"quantity":format(q,"f"),"movementId":move})
            c.execute("UPDATE business_orders SET status='SHIPPED' WHERE user_id=? AND order_id=? AND status='CONFIRMED'",
                      (user,order_id))
            result={"status":"shipped","orderId":order_id,"shipments":shipped}
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",
                      (user,body.idempotencyKey,order_id,"ORDER_FULFILL",json.dumps(result),now))
        return result

    @app.post("/v2/erp/inventory/orders/{order_id}/purchase-receipts")
    def receive_purchase_order_inventory(order_id: str, body: PurchaseReceiptInput,
                                         authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT document_id,state FROM adv_inventory_control_docs WHERE user_id=? AND idempotency_key=?",
                          (user,body.idempotencyKey)).fetchone()
            if old: return {"status":"duplicate","documentId":old["document_id"],"state":old["state"]}
            order=c.execute("SELECT order_type,status,payload FROM business_orders WHERE user_id=? AND order_id=?",
                            (user,order_id)).fetchone()
            if not order: raise HTTPException(404,"Purchase order not found in this account")
            if order["order_type"]!="PURCHASE" or order["status"]!="CONFIRMED":
                raise HTTPException(409,"Only confirmed purchase orders can be received")
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            order_payload=decrypt_payload(order["payload"])
            expected={}
            for line in order_payload.get("lines",[]):
                expected[line["productId"]]=expected.get(line["productId"],Decimal("0"))+amount(line["quantity"])
            supplied={}
            for line in body.lines:
                supplied[line.productId]=supplied.get(line.productId,Decimal("0"))+amount(line.quantity)
                if not c.execute("SELECT 1 FROM business_products WHERE user_id=? AND product_id=?",
                                 (user,line.productId)).fetchone():
                    raise HTTPException(404,"Purchase order product not found in this account")
                if line.expiryDate and line.receivedDate and line.expiryDate<line.receivedDate:
                    raise HTTPException(422,"Expiry date cannot precede receipt date")
            if supplied!=expected:
                raise HTTPException(409,"Receipt quantities must exactly reconcile to purchase order lines")
            document_id=uuid.uuid4().hex; receipts=[]
            for index,line in enumerate(body.lines):
                product=c.execute("SELECT payload FROM business_products WHERE user_id=? AND product_id=?",
                                  (user,line.productId)).fetchone()
                product_payload=decrypt_payload(product["payload"])
                if product_payload.get("unit")!=line.unit:
                    raise HTTPException(409,"Receipt unit does not match the product base unit")
                lot_id=uuid.uuid4().hex
                c.execute("INSERT INTO adv_lots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (user,lot_id,line.productId,line.lotCode,line.unit,None,None,
                   line.receivedDate or time.strftime("%Y-%m-%d",time.gmtime()),line.expiryDate,
                   "SUPPLIER",order_id,"PENDING_INSPECTION",now))
                write_balance(c,user,body.warehouseId,lot_id,amount(line.quantity),now)
                move=movement(c,user,f"{body.idempotencyKey}:{index}","PURCHASE_RECEIPT",lot_id,
                              line.productId,body.warehouseId,amount(line.quantity),"PURCHASE_ORDER",order_id,now)
                receipts.append({"lotId":lot_id,"productId":line.productId,"quantity":format(amount(line.quantity),"f"),
                                 "movementId":move,"qualityState":"PENDING_INSPECTION"})
            c.execute("UPDATE business_orders SET status='RECEIVED' WHERE user_id=? AND order_id=? AND status='CONFIRMED'",
                      (user,order_id))
            c.execute("INSERT INTO adv_inventory_control_docs VALUES(?,?,?,?,?,?,?,?)",
              (user,document_id,"PURCHASE_RECEIPT",body.idempotencyKey,"POSTED",
               json.dumps({"orderId":order_id,"receipts":receipts},separators=(",",":")),now,now))
        return {"status":"received_pending_inspection","orderId":order_id,"documentId":document_id,"receipts":receipts}


    @app.post("/v2/erp/inventory/harvest-receipts")
    def receive_harvest_lot(body: HarvestLotInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            duplicate=c.execute("SELECT movement_id FROM adv_stock_movements WHERE user_id=? AND idempotency_key=?",
                                (user,body.idempotencyKey)).fetchone()
            if duplicate: return {"status":"duplicate","movementId":duplicate["movement_id"]}
            if not c.execute("SELECT 1 FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1",
                             (user,body.warehouseId)).fetchone():
                raise HTTPException(404,"Warehouse not found in this account")
            harvest=c.execute("""SELECT greenhouse_id,crop_cycle_id,product_id,quantity,payload
              FROM greenhouse_harvests WHERE user_id=? AND harvest_id=?""",(user,body.harvestId)).fetchone()
            if not harvest: raise HTTPException(404,"Harvest record not found in this account")
            existing=c.execute("SELECT lot_id FROM adv_lots WHERE user_id=? AND source_type='GREENHOUSE' AND source_id=?",
                               (user,body.harvestId)).fetchone()
            if existing: raise HTTPException(409,"Harvest already has an advanced inventory lot")
            harvest_payload=decrypt_payload(harvest["payload"])
            unit=harvest_payload.get("unit","kg")
            lot_id=uuid.uuid4().hex
            c.execute("INSERT INTO adv_lots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (user,lot_id,harvest["product_id"],body.lotCode,unit,None,
               time.strftime("%Y-%m-%d",time.gmtime()),time.strftime("%Y-%m-%d",time.gmtime()),
               body.expiryDate,"GREENHOUSE",body.harvestId,"PENDING_INSPECTION",now))
            q=amount(harvest["quantity"])
            write_balance(c,user,body.warehouseId,lot_id,q,now)
            move=movement(c,user,body.idempotencyKey,"HARVEST_RECEIPT",lot_id,harvest["product_id"],
                          body.warehouseId,q,"HARVEST",body.harvestId,now)
        return {"status":"received_pending_inspection","lotId":lot_id,"movementId":move,
                "quantity":format(q,"f"),"unit":unit,"greenhouseId":harvest["greenhouse_id"],
                "cropCycleId":harvest["crop_cycle_id"]}

    @app.get("/v2/erp/inventory/orders/{order_id}/cost-reconciliation")
    def order_cost_reconciliation(order_id: str, authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            order=c.execute("SELECT order_type,status,total,payload FROM business_orders WHERE user_id=? AND order_id=?",
                            (user,order_id)).fetchone()
            if not order: raise HTTPException(404,"Order not found in this account")
            if order["order_type"]!="SALES": raise HTTPException(409,"Cost reconciliation is only available for sales orders")
            payload=decrypt_payload(order["payload"])
            shipped=c.execute("""SELECT movement_id,lot_id,quantity,created_at FROM adv_stock_movements
              WHERE user_id=? AND movement_type='SHIPMENT_ISSUE'
                AND reference_type='SALES_ORDER' AND reference_id=? ORDER BY created_at,movement_id""",
              (user,order_id)).fetchall()
            return_rows=c.execute("""SELECT quantity FROM adv_stock_movements
              WHERE user_id=? AND movement_type='CUSTOMER_RETURN'
                AND reference_type='SALES_RETURN' AND reference_id=?""",(user,order_id)).fetchall()
            returns=sum((Decimal(row["quantity"]) for row in return_rows),Decimal("0"))
            cost_rows=[]; total_cogs=Decimal("0"); currencies=set(); missing=[]
            for item in shipped:
                lot=c.execute("SELECT source_type,source_id,unit,product_id FROM adv_lots WHERE user_id=? AND lot_id=?",
                              (user,item["lot_id"])).fetchone()
                if not lot or lot["source_type"]!="GREENHOUSE" or not lot["source_id"]:
                    missing.append({"lotId":item["lot_id"],"reason":"LOT_NOT_LINKED_TO_HARVEST_COST_OBJECT"})
                    continue
                allocation=c.execute("""SELECT a.cost_per_unit,a.unit,r.currency,r.version
                  FROM crop_cost_allocations a JOIN crop_cost_runs r
                    ON r.user_id=a.user_id AND r.run_id=a.run_id
                  WHERE a.user_id=? AND a.harvest_id=?
                  ORDER BY r.version DESC LIMIT 1""",(user,lot["source_id"])).fetchone()
                if not allocation:
                    missing.append({"lotId":item["lot_id"],"harvestId":lot["source_id"],"reason":"APPROVED_COST_RUN_REQUIRED"})
                    continue
                if allocation["unit"]!=lot["unit"]:
                    missing.append({"lotId":item["lot_id"],"reason":"UNIT_MISMATCH"})
                    continue
                q=Decimal(item["quantity"]); unit_cost=Decimal(allocation["cost_per_unit"])
                line_cost=q*unit_cost; total_cogs+=line_cost; currencies.add(allocation["currency"])
                cost_rows.append({"movementId":item["movement_id"],"lotId":item["lot_id"],
                                  "harvestId":lot["source_id"],"quantity":item["quantity"],
                                  "unitCost":format(unit_cost,"f"),"cogs":format(line_cost,"f"),
                                  "currency":allocation["currency"],"costRunVersion":allocation["version"]})
            if len(currencies)>1:
                raise HTTPException(409,"Mixed currencies require an approved conversion policy")
            order_lines=payload.get("lines",[])
            ordered_quantity=sum((Decimal(str(line["quantity"])) for line in order_lines),Decimal("0"))
            shipped_quantity=sum((Decimal(item["quantity"]) for item in shipped),Decimal("0"))
            currency=next(iter(currencies)) if currencies else None
            complete=bool(shipped) and not missing and shipped_quantity==ordered_quantity and returns==0
            status="PROVISIONAL_COGS" if complete else "NOT_FINALIZED_INCOMPLETE_COST_OR_SHIPMENT_OR_RETURNS"
        return {"orderId":order_id,"orderStatus":order["status"],"orderValue":str(order["total"]),
                "orderedQuantity":format(ordered_quantity,"f"),"shippedQuantity":format(shipped_quantity,"f"),
                "customerReturnQuantityPendingDisposition":format(returns,"f"),"cogs":format(total_cogs,"f"),
                "costCurrency":currency,"costedShipments":cost_rows,"missingCostLinks":missing,
                "profitabilityStatus":status,
                "grossMarginBeforeOtherAdjustments":format(Decimal(str(order["total"]))-total_cogs,"f") if complete else None}
