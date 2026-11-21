from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from decimal import Decimal, InvalidOperation
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Literal


CATEGORIES = (
    "SEED_SEEDLING", "INPUTS", "LABOR", "ENERGY", "WATER",
    "MACHINERY_MAINTENANCE", "OPERATIONS", "PACKAGING",
    "POST_HARVEST", "QUALITY_STORAGE", "WASTE_NORMAL", "WASTE_ABNORMAL"
)


class CostEntryInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    greenhouseId: str = Field(min_length=1, max_length=200)
    cropCycleId: str = Field(min_length=1, max_length=200)
    category: Literal["SEED_SEEDLING","INPUTS","LABOR","ENERGY","WATER","MACHINERY_MAINTENANCE","OPERATIONS","PACKAGING","POST_HARVEST","QUALITY_STORAGE","WASTE_NORMAL","WASTE_ABNORMAL"]
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=2)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    unit: str | None = Field(default=None, max_length=24)
    allocationMethod: Literal["DIRECT", "OUTPUT_QUANTITY"] = "OUTPUT_QUANTITY"
    sourceReference: str = Field(min_length=2, max_length=200)
    notes: str = Field(default="", max_length=2000)

    @field_validator("amount")
    @classmethod
    def finite_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("amount must be finite")
        return value


class CostRunInput(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=200)
    greenhouseId: str = Field(min_length=1, max_length=200)
    cropCycleId: str = Field(min_length=1, max_length=200)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


def register_production_costing_routes(app, db, current_user, decrypt_payload) -> None:
    def schema(c):
        c.executescript("""
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

    def decimal(value):
        try:
            result=Decimal(str(value))
        except (InvalidOperation,ValueError):
            raise HTTPException(422,"Invalid decimal value")
        if not result.is_finite():
            raise HTTPException(422,"Decimal value must be finite")
        return result

    def ensure_cycle(c,user,greenhouse,cycle):
        gh=c.execute("SELECT payload FROM records WHERE user_id=? AND entity_type='greenhouse' AND entity_id=? AND deleted=0",(user,greenhouse)).fetchone()
        cc=c.execute("SELECT payload FROM records WHERE user_id=? AND entity_type='crop_cycle' AND entity_id=? AND deleted=0",(user,cycle)).fetchone()
        if not gh or not cc:
            raise HTTPException(404,"Greenhouse or crop cycle not found in this account")
        cycle_payload=decrypt_payload(cc["payload"])
        linked_greenhouse=cycle_payload.get("greenhouseId")
        if linked_greenhouse != greenhouse:
            raise HTTPException(409,"Crop cycle does not belong to the supplied greenhouse")
        return True

    @app.post("/v2/erp/costs/entries")
    def create_cost_entry(body: CostEntryInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); ident=uuid.uuid4().hex
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            duplicate=c.execute("SELECT entry_id FROM crop_cost_entries WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if duplicate: return {"status":"duplicate","entryId":duplicate["entry_id"]}
            ensure_cycle(c,user,body.greenhouseId,body.cropCycleId)
            c.execute("""INSERT INTO crop_cost_entries(
              entry_id,user_id,idempotency_key,greenhouse_id,crop_cycle_id,category,amount,currency,
              quantity,unit,allocation_method,source_reference,notes,actor_id,created_at,approval_status)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING_APPROVAL')""",
              (ident,user,body.idempotencyKey,body.greenhouseId,body.cropCycleId,body.category,
               format(body.amount,"f"),body.currency,format(body.quantity,"f") if body.quantity is not None else None,
               body.unit,body.allocationMethod,body.sourceReference,body.notes,user,now))
        return {"status":"pending_approval","entryId":ident,"amount":format(body.amount,"f"),"currency":body.currency}

    @app.post("/v2/erp/costs/entries/{entry_id}/approve")
    def approve_cost_entry(entry_id: str, x_approval_token: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        user=actor(authorization)
        expected=os.environ.get("MOLIDO_COST_APPROVAL_TOKEN","")
        if len(expected)<32 or not x_approval_token or not secrets.compare_digest(expected,x_approval_token):
            raise HTTPException(403,"Cost approval is not configured or token is invalid")
        now=int(time.time()*1000)
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT approval_status FROM crop_cost_entries WHERE user_id=? AND entry_id=?",(user,entry_id)).fetchone()
            if not row: raise HTTPException(404,"Cost entry not found in this account")
            if row["approval_status"]=="APPROVED": return {"status":"already_approved","entryId":entry_id}
            c.execute("UPDATE crop_cost_entries SET approval_status='APPROVED',approved_by=?,approved_at=? WHERE user_id=? AND entry_id=?",
              (user,now,user,entry_id))
        return {"status":"approved","entryId":entry_id,"approvedAtEpochMillis":now}

    @app.get("/v2/erp/costs/cycles/{crop_cycle_id}/entries")
    def list_cost_entries(crop_cycle_id: str, authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c)
            rows=c.execute("SELECT * FROM crop_cost_entries WHERE user_id=? AND crop_cycle_id=? ORDER BY created_at,entry_id",(user,crop_cycle_id)).fetchall()
        return {"items":[{"id":r["entry_id"],"greenhouseId":r["greenhouse_id"],"cropCycleId":r["crop_cycle_id"],
          "category":r["category"],"amount":r["amount"],"currency":r["currency"],"quantity":r["quantity"],
          "unit":r["unit"],"allocationMethod":r["allocation_method"],"sourceReference":r["source_reference"],
          "notes":r["notes"],"approvalStatus":r["approval_status"],"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.post("/v2/erp/costs/runs")
    def run_costing(body: CostRunInput, authorization: str | None = Header(default=None)):
        user=actor(authorization); now=int(time.time()*1000); run_id=uuid.uuid4().hex
        with db() as c:
            schema(c); c.execute("BEGIN IMMEDIATE")
            duplicate=c.execute("SELECT run_id,version FROM crop_cost_runs WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if duplicate: return {"status":"duplicate","runId":duplicate["run_id"],"version":duplicate["version"]}
            ensure_cycle(c,user,body.greenhouseId,body.cropCycleId)
            entries=c.execute("SELECT category,amount,currency,allocation_method FROM crop_cost_entries WHERE user_id=? AND greenhouse_id=? AND crop_cycle_id=? AND approval_status='APPROVED'",
              (user,body.greenhouseId,body.cropCycleId)).fetchall()
            if not entries: raise HTTPException(409,"No approved cost entries exist for this crop cycle")
            currencies={r["currency"] for r in entries}
            if currencies != {body.currency}: raise HTTPException(409,"Cost run currency does not match every cost entry")
            harvests=c.execute("SELECT harvest_id,quantity,payload FROM greenhouse_harvests WHERE user_id=? AND greenhouse_id=? AND crop_cycle_id=? ORDER BY created_at,harvest_id",
              (user,body.greenhouseId,body.cropCycleId)).fetchall()
            if not harvests: raise HTTPException(409,"No harvest output exists for this crop cycle")
            decoded=[]
            for h in harvests:
                payload=decrypt_payload(h["payload"])
                unit=payload.get("unit","kg")
                decoded.append((h["harvest_id"],decimal(h["quantity"]),unit))
            units={item[2] for item in decoded}
            if len(units)!=1: raise HTTPException(409,"Mixed harvest units require a reviewed conversion policy")
            output=sum((item[1] for item in decoded),Decimal("0"))
            if output<=0: raise HTTPException(409,"Harvest output quantity must be positive")
            normal=sum((decimal(r["amount"]) for r in entries if r["category"]!="WASTE_ABNORMAL"),Decimal("0"))
            abnormal=sum((decimal(r["amount"]) for r in entries if r["category"]=="WASTE_ABNORMAL"),Decimal("0"))
            version_row=c.execute("SELECT COALESCE(MAX(version),0) version FROM crop_cost_runs WHERE user_id=? AND crop_cycle_id=?",(user,body.cropCycleId)).fetchone()
            version=int(version_row["version"])+1
            c.execute("INSERT INTO crop_cost_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (run_id,user,body.idempotencyKey,body.greenhouseId,body.cropCycleId,version,body.currency,
               format(output,"f"),next(iter(units)),format(normal,"f"),format(abnormal,"f"),now))
            for harvest_id,quantity,unit in decoded:
                allocated=normal*quantity/output
                per_unit=allocated/quantity
                c.execute("INSERT INTO crop_cost_allocations VALUES(?,?,?,?,?,?,?)",
                  (run_id,user,harvest_id,format(quantity,"f"),unit,format(allocated,"f"),format(per_unit,"f")))
        return {"status":"calculated","runId":run_id,"version":version,"currency":body.currency,
          "outputQuantity":format(output,"f"),"outputUnit":next(iter(units)),
          "capitalizableCost":format(normal,"f"),"abnormalWasteCost":format(abnormal,"f"),
          "costPerUnit":format(normal/output,"f"),"profitability":"NOT_CALCULATED_SALES_LINK_REQUIRED"}

    @app.get("/v2/erp/costs/cycles/{crop_cycle_id}/summary")
    def cost_summary(crop_cycle_id: str, authorization: str | None = Header(default=None)):
        user=actor(authorization)
        with db() as c:
            schema(c)
            runs=c.execute("SELECT * FROM crop_cost_runs WHERE user_id=? AND crop_cycle_id=? ORDER BY version DESC",(user,crop_cycle_id)).fetchall()
            latest=runs[0] if runs else None
            allocations=c.execute("SELECT * FROM crop_cost_allocations WHERE user_id=? AND run_id=? ORDER BY harvest_id",(user,latest["run_id"])).fetchall() if latest else []
        return {"latestRun":None if not latest else {"runId":latest["run_id"],"version":latest["version"],
          "currency":latest["currency"],"outputQuantity":latest["output_quantity"],"outputUnit":latest["output_unit"],
          "capitalizableCost":latest["capitalizable_cost"],"abnormalWasteCost":latest["abnormal_waste_cost"],
          "allocations":[{"harvestId":r["harvest_id"],"quantity":r["quantity"],"unit":r["unit"],
            "allocatedCost":r["allocated_cost"],"costPerUnit":r["cost_per_unit"]} for r in allocations]},
          "runs":[{"runId":r["run_id"],"version":r["version"],"createdAtEpochMillis":r["created_at"]} for r in runs]}
