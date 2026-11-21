from __future__ import annotations

import json
import time
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field, field_validator


def _validate_iso_date(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("date must use valid YYYY-MM-DD format")
    if parsed.isoformat() != value:
        raise ValueError("date must use valid YYYY-MM-DD format")
    return value


class WarehouseInput(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=2, max_length=160)
    warehouseType: Literal["GENERAL", "INPUTS", "PRODUCE", "PACKAGING", "QUARANTINE", "COLD_STORAGE"] = "GENERAL"


class LotInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    lotCode: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    unit: str = Field(min_length=1, max_length=24)
    manufactureDate: str | None = None
    harvestDate: str | None = None
    receivedDate: str | None = None
    expiryDate: str | None = None
    sourceType: Literal["SUPPLIER", "GREENHOUSE", "TRANSFER", "OTHER"] = "OTHER"
    sourceId: str | None = Field(default=None, max_length=200)

    @field_validator("quantity")
    @classmethod
    def finite_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantity must be finite")
        return value

    @field_validator("manufactureDate", "harvestDate", "receivedDate", "expiryDate")
    @classmethod
    def valid_lot_dates(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class TransferInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    lotId: str = Field(min_length=1, max_length=200)
    sourceWarehouseId: str = Field(min_length=1, max_length=200)
    destinationWarehouseId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)


class ReservationInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    lotId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    referenceType: str = Field(min_length=2, max_length=40)
    referenceId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)


class FefoAllocationInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=160)
    warehouseId: str = Field(min_length=1, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    referenceType: str = Field(min_length=2, max_length=40)
    referenceId: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=24, decimal_places=6)

    @field_validator("quantity")
    @classmethod
    def finite_quantity(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantity must be finite")
        return value


class QualityInput(BaseModel):
    state: Literal["RELEASED", "QUARANTINED", "REJECTED", "EXPIRED"]
    reason: str = Field(min_length=3, max_length=1000)
    evidenceRef: str | None = Field(default=None, max_length=500)


class ReservationActionInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    action: Literal["RELEASE", "FULFILL"]


def register_advanced_inventory_routes(app, db, current_user) -> None:
    def schema(c):
        c.executescript("""
        CREATE TABLE IF NOT EXISTS adv_warehouses(
          user_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, code TEXT NOT NULL,
          name TEXT NOT NULL, warehouse_type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,warehouse_id), UNIQUE(user_id,code)
        );
        CREATE TABLE IF NOT EXISTS adv_lots(
          user_id TEXT NOT NULL, lot_id TEXT NOT NULL, product_id TEXT NOT NULL,
          lot_code TEXT NOT NULL, unit TEXT NOT NULL, manufacture_date TEXT,
          harvest_date TEXT, received_date TEXT, expiry_date TEXT,
          source_type TEXT NOT NULL, source_id TEXT, quality_state TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,lot_id),
          UNIQUE(user_id,product_id,lot_code)
        );
        CREATE TABLE IF NOT EXISTS adv_stock_balances(
          user_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, lot_id TEXT NOT NULL,
          quantity TEXT NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,warehouse_id,lot_id)
        );
        CREATE TABLE IF NOT EXISTS adv_stock_movements(
          movement_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          movement_type TEXT NOT NULL, lot_id TEXT NOT NULL, product_id TEXT NOT NULL,
          source_warehouse_id TEXT, destination_warehouse_id TEXT,
          quantity TEXT NOT NULL, reference_type TEXT, reference_id TEXT,
          actor_id TEXT NOT NULL, created_at INTEGER NOT NULL, payload TEXT NOT NULL,
          UNIQUE(user_id,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS adv_reservations(
          reservation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          lot_id TEXT NOT NULL, warehouse_id TEXT NOT NULL, reference_type TEXT NOT NULL,
          reference_id TEXT NOT NULL, quantity TEXT NOT NULL, state TEXT NOT NULL,
          created_at INTEGER NOT NULL, UNIQUE(user_id,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS adv_quality_events(
          event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, lot_id TEXT NOT NULL,
          from_state TEXT NOT NULL, to_state TEXT NOT NULL, reason TEXT NOT NULL,
          evidence_ref TEXT, actor_id TEXT NOT NULL, created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS adv_reservation_actions(
          user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, reservation_id TEXT NOT NULL,
          action TEXT NOT NULL, result TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS adv_fefo_allocations(
          user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, result TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_adv_lots_expiry ON adv_lots(user_id,expiry_date);
        CREATE INDEX IF NOT EXISTS idx_adv_movements_lot ON adv_stock_movements(user_id,lot_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_adv_reservations_lot ON adv_reservations(user_id,lot_id,state);
        """)

    def actor(auth):
        return current_user(auth)

    def ensure_warehouse(c, user, warehouse_id):
        row = c.execute("SELECT warehouse_id FROM adv_warehouses WHERE user_id=? AND warehouse_id=? AND active=1", (user, warehouse_id)).fetchone()
        if not row:
            raise HTTPException(404, "Warehouse not found in this account")

    def ensure_product(c, user, product_id):
        row = c.execute("SELECT product_id FROM business_products WHERE user_id=? AND product_id=?", (user, product_id)).fetchone()
        if not row:
            raise HTTPException(404, "Product not found in this account")

    def qty(value):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise HTTPException(422, "Invalid quantity")
        if not result.is_finite() or result <= 0:
            raise HTTPException(422, "Quantity must be a positive finite decimal")
        return result

    def balance(c, user, warehouse, lot):
        row = c.execute("SELECT quantity FROM adv_stock_balances WHERE user_id=? AND warehouse_id=? AND lot_id=?", (user, warehouse, lot)).fetchone()
        return Decimal(row["quantity"]) if row else Decimal("0")

    def write_balance(c, user, warehouse, lot, amount, now):
        if amount < 0:
            raise HTTPException(409, "Insufficient lot stock")
        c.execute("""INSERT INTO adv_stock_balances(user_id,warehouse_id,lot_id,quantity,updated_at)
          VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,lot_id)
          DO UPDATE SET quantity=excluded.quantity,updated_at=excluded.updated_at""",
          (user, warehouse, lot, format(amount, "f"), now))

    def record(c, user, key, kind, lot, product, source, dest, amount, actor_id, now, reference_type=None, reference_id=None):
        movement_id = uuid.uuid4().hex
        payload = json.dumps({"movementId":movement_id,"type":kind,"lotId":lot,"quantity":format(amount,"f")}, separators=(",",":"))
        c.execute("""INSERT INTO adv_stock_movements(movement_id,user_id,idempotency_key,movement_type,lot_id,product_id,
          source_warehouse_id,destination_warehouse_id,quantity,reference_type,reference_id,actor_id,created_at,payload)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (movement_id,user,key,kind,lot,product,source,dest,format(amount,"f"),reference_type,reference_id,actor_id,now,payload))
        return movement_id

    @app.post("/v2/erp/inventory/warehouses")
    def create_warehouse(body: WarehouseInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); ident=uuid.uuid4().hex
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            try:
                c.execute("INSERT INTO adv_warehouses VALUES(?,?,?,?,?,?,?)",
                  (user,ident,body.code,body.name,body.warehouseType,1,now))
            except Exception as exc:
                if "UNIQUE" in str(exc): raise HTTPException(409,"Warehouse code already exists in this account")
                raise
        return {"id":ident,**body.model_dump(),"active":True}

    @app.get("/v2/erp/inventory/warehouses")
    def list_warehouses(authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c); rows=c.execute("SELECT warehouse_id,code,name,warehouse_type,active FROM adv_warehouses WHERE user_id=? ORDER BY code",(user,)).fetchall()
        return {"items":[{"id":r["warehouse_id"],"code":r["code"],"name":r["name"],"warehouseType":r["warehouse_type"],"active":bool(r["active"])} for r in rows]}

    @app.post("/v2/erp/inventory/lots")
    def receive_lot(body: LotInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); lot_id=uuid.uuid4().hex
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            duplicate=c.execute("SELECT movement_id FROM adv_stock_movements WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if duplicate: return {"status":"duplicate","movementId":duplicate["movement_id"]}
            ensure_warehouse(c,user,body.warehouseId); ensure_product(c,user,body.productId)
            if body.expiryDate and body.receivedDate and body.expiryDate < body.receivedDate:
                raise HTTPException(422,"Expiry date cannot precede receipt date")
            try:
                c.execute("INSERT INTO adv_lots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (user,lot_id,body.productId,body.lotCode,body.unit,body.manufactureDate,body.harvestDate,
                   body.receivedDate,body.expiryDate,body.sourceType,body.sourceId,"PENDING_INSPECTION",now))
            except Exception as exc:
                if "UNIQUE" in str(exc): raise HTTPException(409,"Lot code already exists for this product")
                raise
            write_balance(c,user,body.warehouseId,lot_id,body.quantity,now)
            movement=record(c,user,body.idempotencyKey,"RECEIPT",lot_id,body.productId,None,body.warehouseId,body.quantity,user,now,body.sourceType,body.sourceId)
        return {"status":"received_pending_inspection","lotId":lot_id,"movementId":movement,"quantity":format(body.quantity,"f")}

    @app.get("/v2/erp/inventory/lots")
    def list_lots(warehouseId: str | None = None, productId: str | None = None, authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c)
            rows=c.execute("""SELECT l.*,b.warehouse_id,b.quantity FROM adv_lots l
              LEFT JOIN adv_stock_balances b ON b.user_id=l.user_id AND b.lot_id=l.lot_id
              WHERE l.user_id=? AND (? IS NULL OR b.warehouse_id=?) AND (? IS NULL OR l.product_id=?)
              ORDER BY CASE WHEN l.expiry_date IS NULL THEN 1 ELSE 0 END,l.expiry_date,l.created_at""",
              (user,warehouseId,warehouseId,productId,productId)).fetchall()
        return {"items":[{"id":r["lot_id"],"productId":r["product_id"],"lotCode":r["lot_code"],"unit":r["unit"],
          "warehouseId":r["warehouse_id"],"quantity":r["quantity"],"manufactureDate":r["manufacture_date"],
          "harvestDate":r["harvest_date"],"receivedDate":r["received_date"],"expiryDate":r["expiry_date"],
          "sourceType":r["source_type"],"sourceId":r["source_id"],"qualityState":r["quality_state"]} for r in rows]}

    @app.post("/v2/erp/inventory/transfers")
    def transfer_lot(body: TransferInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        if body.sourceWarehouseId == body.destinationWarehouseId: raise HTTPException(422,"Source and destination must differ")
        amount=qty(body.quantity)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            duplicate=c.execute("SELECT movement_id FROM adv_stock_movements WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if duplicate: return {"status":"duplicate","movementId":duplicate["movement_id"]}
            ensure_warehouse(c,user,body.sourceWarehouseId); ensure_warehouse(c,user,body.destinationWarehouseId)
            lot=c.execute("SELECT product_id,quality_state FROM adv_lots WHERE user_id=? AND lot_id=?",(user,body.lotId)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            if lot["quality_state"] != "RELEASED": raise HTTPException(409,"Only released lots can be transferred")
            source=balance(c,user,body.sourceWarehouseId,body.lotId)
            reserved=sum((Decimal(r["quantity"]) for r in c.execute("SELECT quantity FROM adv_reservations WHERE user_id=? AND warehouse_id=? AND lot_id=? AND state='ACTIVE'",(user,body.sourceWarehouseId,body.lotId)).fetchall()),Decimal("0"))
            if source-reserved < amount: raise HTTPException(409,"Insufficient unreserved lot stock")
            write_balance(c,user,body.sourceWarehouseId,body.lotId,source-amount,now)
            dest=balance(c,user,body.destinationWarehouseId,body.lotId)
            write_balance(c,user,body.destinationWarehouseId,body.lotId,dest+amount,now)
            movement=record(c,user,body.idempotencyKey,"TRANSFER",body.lotId,lot["product_id"],body.sourceWarehouseId,body.destinationWarehouseId,amount,user,now)
        return {"status":"transferred","movementId":movement,"quantity":format(amount,"f")}

    @app.post("/v2/erp/inventory/reservations")
    def reserve_lot(body: ReservationInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); amount=qty(body.quantity)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            old=c.execute("SELECT * FROM adv_reservations WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if old:
                same_request = (
                    old["lot_id"] == body.lotId
                    and old["warehouse_id"] == body.warehouseId
                    and old["reference_type"] == body.referenceType
                    and old["reference_id"] == body.referenceId
                    and Decimal(old["quantity"]) == amount
                )
                if not same_request:
                    raise HTTPException(409,"Idempotency key already belongs to a different reservation request")
                return {"status":"duplicate","reservationId":old["reservation_id"]}
            ensure_warehouse(c,user,body.warehouseId)
            lot=c.execute("SELECT product_id,quality_state,expiry_date FROM adv_lots WHERE user_id=? AND lot_id=?",(user,body.lotId)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            if lot["quality_state"] != "RELEASED": raise HTTPException(409,"Lot is not released for reservation")
            if lot["expiry_date"] and lot["expiry_date"] < time.strftime("%Y-%m-%d",time.gmtime()): raise HTTPException(409,"Expired lot cannot be reserved")
            on_hand=balance(c,user,body.warehouseId,body.lotId)
            reserved=sum((Decimal(r["quantity"]) for r in c.execute("SELECT quantity FROM adv_reservations WHERE user_id=? AND warehouse_id=? AND lot_id=? AND state='ACTIVE'",(user,body.warehouseId,body.lotId)).fetchall()),Decimal("0"))
            if on_hand-reserved < amount: raise HTTPException(409,"Insufficient available quantity")
            ident=uuid.uuid4().hex
            c.execute("INSERT INTO adv_reservations VALUES(?,?,?,?,?,?,?,?,?,?)",
              (ident,user,body.idempotencyKey,body.lotId,body.warehouseId,body.referenceType,body.referenceId,format(amount,"f"),"ACTIVE",now))
        return {"status":"reserved","reservationId":ident,"availableAfter":format(on_hand-reserved-amount,"f")}

    @app.post("/v2/erp/inventory/lots/{lot_id}/quality")
    def change_quality(lot_id: str, body: QualityInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            lot=c.execute("SELECT quality_state FROM adv_lots WHERE user_id=? AND lot_id=?",(user,lot_id)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            old=lot["quality_state"]
            if old in ("REJECTED","EXPIRED") and body.state=="RELEASED": raise HTTPException(409,"Rejected or expired lot cannot be released")
            c.execute("UPDATE adv_lots SET quality_state=? WHERE user_id=? AND lot_id=?",(body.state,user,lot_id))
            c.execute("INSERT INTO adv_quality_events VALUES(?,?,?,?,?,?,?,?,?)",
              (uuid.uuid4().hex,user,lot_id,old,body.state,body.reason,body.evidenceRef,user,now))
        return {"lotId":lot_id,"previousState":old,"qualityState":body.state,"changedAtEpochMillis":now}

    @app.post("/v2/erp/inventory/reservations/{reservation_id}/actions")
    def act_on_reservation(reservation_id: str, body: ReservationActionInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            previous=c.execute("SELECT reservation_id,action,result FROM adv_reservation_actions WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if previous:
                if previous["reservation_id"] != reservation_id or previous["action"] != body.action:
                    raise HTTPException(409,"Idempotency key already belongs to a different reservation action")
                return json.loads(previous["result"])
            reservation=c.execute("SELECT * FROM adv_reservations WHERE user_id=? AND reservation_id=?",(user,reservation_id)).fetchone()
            if not reservation: raise HTTPException(404,"Reservation not found in this account")
            if reservation["state"] != "ACTIVE": raise HTTPException(409,"Only active reservations can be changed")
            result={"reservationId":reservation_id,"action":body.action.lower()}
            if body.action == "RELEASE":
                c.execute("UPDATE adv_reservations SET state='RELEASED' WHERE user_id=? AND reservation_id=? AND state='ACTIVE'",(user,reservation_id))
                result["status"]="released"
            else:
                lot=c.execute("SELECT product_id,quality_state,expiry_date FROM adv_lots WHERE user_id=? AND lot_id=?",(user,reservation["lot_id"])).fetchone()
                if not lot: raise HTTPException(404,"Lot not found in this account")
                if lot["quality_state"] != "RELEASED": raise HTTPException(409,"Lot is not released for fulfillment")
                if lot["expiry_date"] and lot["expiry_date"] < time.strftime("%Y-%m-%d",time.gmtime()): raise HTTPException(409,"Expired lot cannot be fulfilled")
                amount=Decimal(reservation["quantity"]); on_hand=balance(c,user,reservation["warehouse_id"],reservation["lot_id"])
                if on_hand < amount: raise HTTPException(409,"Reserved stock is no longer available")
                write_balance(c,user,reservation["warehouse_id"],reservation["lot_id"],on_hand-amount,now)
                movement=record(c,user,body.idempotencyKey,"ISSUE",reservation["lot_id"],lot["product_id"],reservation["warehouse_id"],None,amount,user,now,reservation["reference_type"],reservation["reference_id"])
                c.execute("UPDATE adv_reservations SET state='FULFILLED' WHERE user_id=? AND reservation_id=? AND state='ACTIVE'",(user,reservation_id))
                result.update({"status":"fulfilled","movementId":movement,"quantity":format(amount,"f")})
            c.execute("INSERT INTO adv_reservation_actions VALUES(?,?,?,?,?,?)",(user,body.idempotencyKey,reservation_id,body.action,json.dumps(result,separators=(",",":")),now))
        return result

    @app.get("/v2/erp/inventory/lots/{lot_id}/trace")
    def trace_lot(lot_id: str, authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c)
            lot=c.execute("""SELECT lot_id,product_id,lot_code,unit,manufacture_date,harvest_date,received_date,
              expiry_date,source_type,source_id,quality_state,created_at FROM adv_lots
              WHERE user_id=? AND lot_id=?""",(user,lot_id)).fetchone()
            if not lot: raise HTTPException(404,"Lot not found in this account")
            movements=c.execute("""SELECT movement_id,movement_type,source_warehouse_id,destination_warehouse_id,
              quantity,reference_type,reference_id,actor_id,created_at FROM adv_stock_movements
              WHERE user_id=? AND lot_id=? ORDER BY created_at,movement_id""",(user,lot_id)).fetchall()
            reservations=c.execute("""SELECT reservation_id,warehouse_id,reference_type,reference_id,quantity,state,created_at
              FROM adv_reservations WHERE user_id=? AND lot_id=? ORDER BY created_at,reservation_id""",(user,lot_id)).fetchall()
            quality=c.execute("""SELECT event_id,from_state,to_state,reason,evidence_ref,actor_id,created_at
              FROM adv_quality_events WHERE user_id=? AND lot_id=? ORDER BY created_at,event_id""",(user,lot_id)).fetchall()
            balances=c.execute("""SELECT b.warehouse_id,w.code,w.name,b.quantity,b.updated_at
              FROM adv_stock_balances b JOIN adv_warehouses w ON w.user_id=b.user_id AND w.warehouse_id=b.warehouse_id
              WHERE b.user_id=? AND b.lot_id=? ORDER BY w.code""",(user,lot_id)).fetchall()
        return {
          "lot":{"id":lot["lot_id"],"productId":lot["product_id"],"lotCode":lot["lot_code"],"unit":lot["unit"],
            "manufactureDate":lot["manufacture_date"],"harvestDate":lot["harvest_date"],"receivedDate":lot["received_date"],
            "expiryDate":lot["expiry_date"],"sourceType":lot["source_type"],"sourceId":lot["source_id"],
            "qualityState":lot["quality_state"],"createdAt":lot["created_at"]},
          "movements":[{"id":r["movement_id"],"type":r["movement_type"],"sourceWarehouseId":r["source_warehouse_id"],
            "destinationWarehouseId":r["destination_warehouse_id"],"quantity":r["quantity"],"referenceType":r["reference_type"],
            "referenceId":r["reference_id"],"actorId":r["actor_id"],"createdAt":r["created_at"]} for r in movements],
          "reservations":[{"id":r["reservation_id"],"warehouseId":r["warehouse_id"],"referenceType":r["reference_type"],
            "referenceId":r["reference_id"],"quantity":r["quantity"],"state":r["state"],"createdAt":r["created_at"]} for r in reservations],
          "qualityHistory":[{"id":r["event_id"],"from":r["from_state"],"to":r["to_state"],"reason":r["reason"],
            "evidenceRef":r["evidence_ref"],"actorId":r["actor_id"],"createdAt":r["created_at"]} for r in quality],
          "balances":[{"warehouseId":r["warehouse_id"],"warehouseCode":r["code"],"warehouseName":r["name"],
            "quantity":r["quantity"],"updatedAt":r["updated_at"]} for r in balances]
        }

    @app.post("/v2/erp/inventory/fefo/allocate")
    def allocate_fefo(body: FefoAllocationInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000)
        today=time.strftime("%Y-%m-%d",time.gmtime())
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            previous=c.execute("SELECT result FROM adv_fefo_allocations WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if previous:
                result=json.loads(previous["result"]); result["status"]="duplicate"; return result
            ensure_warehouse(c,user,body.warehouseId); ensure_product(c,user,body.productId)
            rows=c.execute("""SELECT l.lot_id,l.product_id,l.expiry_date,l.received_date,l.created_at,b.quantity
              FROM adv_lots l JOIN adv_stock_balances b ON b.user_id=l.user_id AND b.lot_id=l.lot_id
              WHERE l.user_id=? AND l.product_id=? AND b.warehouse_id=? AND l.quality_state='RELEASED'
                AND (l.expiry_date IS NULL OR l.expiry_date>=?)
              ORDER BY CASE WHEN l.expiry_date IS NULL THEN 1 ELSE 0 END,
                l.expiry_date ASC, COALESCE(l.received_date,''),l.created_at,l.lot_id""",
              (user,body.productId,body.warehouseId,today)).fetchall()
            available=[]; total=Decimal("0")
            for row in rows:
                on_hand=Decimal(row["quantity"])
                reserved=sum((Decimal(r["quantity"]) for r in c.execute(
                  "SELECT quantity FROM adv_reservations WHERE user_id=? AND warehouse_id=? AND lot_id=? AND state='ACTIVE'",
                  (user,body.warehouseId,row["lot_id"])).fetchall()),Decimal("0"))
                free=max(Decimal("0"),on_hand-reserved)
                if free>0:
                    available.append((row,free)); total+=free
            if total<body.quantity:
                raise HTTPException(409,"Insufficient unreserved released stock for FEFO allocation")
            remaining=body.quantity; allocations=[]
            for index,(row,free) in enumerate(available):
                if remaining<=0: break
                take=min(free,remaining)
                reservation_id=uuid.uuid4().hex
                child_key=f"{body.idempotencyKey}:{index}"
                c.execute("INSERT INTO adv_reservations VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (reservation_id,user,child_key,row["lot_id"],body.warehouseId,body.referenceType,body.referenceId,format(take,"f"),"ACTIVE",now))
                allocations.append({"reservationId":reservation_id,"lotId":row["lot_id"],"quantity":format(take,"f"),"expiryDate":row["expiry_date"]})
                remaining-=take
            result={"status":"reserved","productId":body.productId,"warehouseId":body.warehouseId,
              "requestedQuantity":format(body.quantity,"f"),"allocations":allocations}
            c.execute("INSERT INTO adv_fefo_allocations VALUES(?,?,?,?)",
              (user,body.idempotencyKey,json.dumps(result,separators=(",",":")),now))
        return result

    @app.get("/v2/erp/inventory/balances")
    def advanced_balances(authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c)
            rows=c.execute("""SELECT w.code warehouse_code,w.name warehouse_name,l.product_id,l.lot_code,l.unit,l.quality_state,
              b.lot_id,b.quantity,l.expiry_date FROM adv_stock_balances b
              JOIN adv_warehouses w ON w.user_id=b.user_id AND w.warehouse_id=b.warehouse_id
              JOIN adv_lots l ON l.user_id=b.user_id AND l.lot_id=b.lot_id
              WHERE b.user_id=? ORDER BY w.code,l.expiry_date""",(user,)).fetchall()
        return {"items":[{"warehouseCode":r["warehouse_code"],"warehouseName":r["warehouse_name"],"productId":r["product_id"],
          "lotId":r["lot_id"],"lotCode":r["lot_code"],"unit":r["unit"],"quantity":r["quantity"],
          "qualityState":r["quality_state"],"expiryDate":r["expiry_date"]} for r in rows]}
