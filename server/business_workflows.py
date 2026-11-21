from __future__ import annotations

import json
import math
import time
import uuid
from typing import Literal

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field


class LeadInput(BaseModel):
    customerId: str | None = None
    title: str = Field(min_length=2, max_length=200)
    source: str = Field(default="OTHER", max_length=40)
    estimatedValue: float = Field(default=0, ge=0, allow_inf_nan=False)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    stage: Literal["NEW", "QUALIFIED", "PROPOSAL", "WON", "LOST"] = "NEW"
    nextActionAtEpochMillis: int | None = None
    notes: str = Field(default="", max_length=4000)


class LeadStageInput(BaseModel):
    stage: Literal["NEW", "QUALIFIED", "PROPOSAL", "WON", "LOST"]
    notes: str | None = Field(default=None, max_length=4000)


class CRMActivityInput(BaseModel):
    customerId: str | None = None
    leadId: str | None = None
    activityType: Literal["CALL", "EMAIL", "MEETING", "TASK", "NOTE", "VISIT"]
    subject: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    details: str | None = Field(default=None, max_length=4000)
    dueAtEpochMillis: int | None = None


class OpportunityInput(BaseModel):
    customerId: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=2, max_length=200)
    stage: Literal["LEAD", "QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON", "LOST"] = "LEAD"
    expectedValue: float = Field(default=0, ge=0, allow_inf_nan=False)
    expectedCloseAtEpochMillis: int | None = None
    notes: str = Field(default="", max_length=4000)


class TicketInput(BaseModel):
    customerId: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=5000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"


class OrderTransitionInput(BaseModel):
    action: Literal["CONFIRM", "CANCEL", "SHIP", "DELIVER", "RECEIVE", "FULFILL"]
    idempotencyKey: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=8, max_length=200)


class HarvestInput(BaseModel):
    greenhouseId: str = Field(min_length=1, max_length=200)
    cropCycleId: str = Field(min_length=1, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    unitPrice: float = Field(default=0, ge=0, allow_inf_nan=False)
    unit: str = Field(default="kg", min_length=1, max_length=32)
    qualityGrade: str = Field(default="UNASSESSED", max_length=40)
    notes: str = Field(default="", max_length=2000)


class TicketStatusInput(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"]


class JournalInput(BaseModel):
    reference: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=1000)
    currency: str = Field(default="IRR", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    lines: list[dict] = Field(min_length=2, max_length=100)


def register_business_workflow_routes(app, db, current_user, encrypt_payload, decrypt_payload) -> None:
    def init(connection):
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS crm_leads (
          user_id TEXT NOT NULL, lead_id TEXT NOT NULL, customer_id TEXT,
          stage TEXT NOT NULL, estimated_value REAL NOT NULL, currency TEXT NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,lead_id)
        );
        CREATE TABLE IF NOT EXISTS crm_activities (
          user_id TEXT NOT NULL, activity_id TEXT NOT NULL, customer_id TEXT, lead_id TEXT,
          activity_type TEXT NOT NULL, subject TEXT NOT NULL, payload TEXT NOT NULL,
          due_at INTEGER, state TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,activity_id)
        );
        CREATE TABLE IF NOT EXISTS crm_opportunities (
          user_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, customer_id TEXT NOT NULL,
          title TEXT NOT NULL, stage TEXT NOT NULL, expected_value REAL NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,opportunity_id)
        );
        CREATE TABLE IF NOT EXISTS crm_tickets (
          user_id TEXT NOT NULL, ticket_id TEXT NOT NULL, customer_id TEXT NOT NULL,
          subject TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,ticket_id)
        );
        CREATE TABLE IF NOT EXISTS order_reservations (
          user_id TEXT NOT NULL, order_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
          product_id TEXT NOT NULL, quantity REAL NOT NULL CHECK(quantity > 0),
          state TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,order_id,warehouse_id,product_id)
        );
        CREATE TABLE IF NOT EXISTS journal_entries (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, reference TEXT NOT NULL,
          currency TEXT NOT NULL, debit_total REAL NOT NULL, credit_total REAL NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,journal_id), UNIQUE(user_id,reference)
        );
        CREATE TABLE IF NOT EXISTS journal_lines (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, line_no INTEGER NOT NULL,
          account_code TEXT NOT NULL, debit REAL NOT NULL, credit REAL NOT NULL,
          description TEXT NOT NULL,
          PRIMARY KEY(user_id,journal_id,line_no),
          FOREIGN KEY(user_id,journal_id) REFERENCES journal_entries(user_id,journal_id)
        );
        CREATE TABLE IF NOT EXISTS greenhouse_harvests (
          user_id TEXT NOT NULL, harvest_id TEXT NOT NULL, greenhouse_id TEXT NOT NULL,
          crop_cycle_id TEXT NOT NULL, product_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
          quantity REAL NOT NULL, unit_price REAL NOT NULL, payload TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,harvest_id)
        );
        CREATE TABLE IF NOT EXISTS business_transition_keys (
          user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, result TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,idempotency_key)
        );
        """)

    def uid(auth):
        return current_user(auth)

    def require_party(c, user, party_id):
        if not c.execute("SELECT 1 FROM business_parties WHERE user_id=? AND party_type='CUSTOMER' AND party_id=?", (user, party_id)).fetchone():
            raise HTTPException(404, "Customer not found in this account")

    @app.post("/v1/crm/leads")
    def create_lead(body: LeadInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000); ident=uuid.uuid4().hex
        with db() as c:
            init(c)
            if body.customerId: require_party(c,user,body.customerId)
            c.execute("INSERT INTO crm_leads VALUES(?,?,?,?,?,?,?,?,?)",
                      (user,ident,body.customerId,body.stage,body.estimatedValue,body.currency,
                       encrypt_payload(body.model_dump()),now,now))
        return {"id":ident,**body.model_dump(),"createdAtEpochMillis":now}

    @app.get("/v1/crm/leads")
    def list_leads(stage: str | None = None, authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c)
            rows=c.execute("SELECT lead_id,payload,created_at FROM crm_leads WHERE user_id=? AND (? IS NULL OR stage=?) ORDER BY updated_at DESC LIMIT 500",(user,stage,stage)).fetchall()
        return {"items":[{"id":r["lead_id"],**decrypt_payload(r["payload"]),"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.post("/v1/crm/leads/{lead_id}/stage")
    def update_lead_stage(lead_id: str, body: LeadStageInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000)
        with db() as c:
            init(c)
            row=c.execute("SELECT payload FROM crm_leads WHERE user_id=? AND lead_id=?",(user,lead_id)).fetchone()
            if not row: raise HTTPException(404,"Lead not found")
            payload=decrypt_payload(row["payload"]); payload["stage"]=body.stage
            if body.notes is not None: payload["notes"]=body.notes
            c.execute("UPDATE crm_leads SET stage=?,payload=?,updated_at=? WHERE user_id=? AND lead_id=?",(body.stage,encrypt_payload(payload),now,user,lead_id))
        return {"id":lead_id,"stage":body.stage,"updatedAtEpochMillis":now}

    @app.post("/v1/crm/activities")
    def create_activity(body: CRMActivityInput, authorization: str | None = Header(default=None)):
        user = uid(authorization); now = int(time.time() * 1000); ident = uuid.uuid4().hex
        with db() as c:
            init(c)
            if body.customerId: require_party(c,user,body.customerId)
            if body.leadId and not c.execute("SELECT 1 FROM crm_leads WHERE user_id=? AND lead_id=?",(user,body.leadId)).fetchone():
                raise HTTPException(404,"Lead not found in this account")
            if not body.customerId and not body.leadId: raise HTTPException(422,"Activity must be linked to a customer or lead")
            c.execute("INSERT INTO crm_activities VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user,ident,body.customerId,body.leadId,body.activityType,body.subject,encrypt_payload(body.model_dump()),body.dueAtEpochMillis,"OPEN",now))
        return {"id":ident,"status":"OPEN","createdAtEpochMillis":now,**body.model_dump()}

    @app.get("/v1/crm/activities")
    def list_activities(customerId: str | None = None, authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c)
            rows=c.execute("SELECT activity_id,payload,state,created_at FROM crm_activities WHERE user_id=? AND (? IS NULL OR customer_id=?) ORDER BY created_at DESC LIMIT 500",(user,customerId,customerId)).fetchall()
        return {"items":[{"id":r["activity_id"],"state":r["state"],"createdAtEpochMillis":r["created_at"],**decrypt_payload(r["payload"])} for r in rows]}

    @app.post("/v1/crm/opportunities")
    def create_opportunity(body: OpportunityInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000); ident=uuid.uuid4().hex
        with db() as c:
            init(c); require_party(c,user,body.customerId)
            c.execute("INSERT INTO crm_opportunities VALUES(?,?,?,?,?,?,?,?)",(user,ident,body.customerId,body.title,body.stage,body.expectedValue,encrypt_payload(body.model_dump()),now))
        return {"id":ident,"createdAtEpochMillis":now,**body.model_dump()}

    @app.get("/v1/crm/opportunities")
    def list_opportunities(authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c); rows=c.execute("SELECT opportunity_id,payload,stage,created_at FROM crm_opportunities WHERE user_id=? ORDER BY created_at DESC LIMIT 500",(user,)).fetchall()
        return {"items":[{"id":r["opportunity_id"],"stage":r["stage"],"createdAtEpochMillis":r["created_at"],**decrypt_payload(r["payload"])} for r in rows]}

    @app.post("/v1/crm/tickets")
    def create_ticket(body: TicketInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000); ident=uuid.uuid4().hex
        with db() as c:
            init(c); require_party(c,user,body.customerId)
            c.execute("INSERT INTO crm_tickets VALUES(?,?,?,?,?,?,?,?,?)",(user,ident,body.customerId,body.subject,body.priority,"OPEN",encrypt_payload(body.model_dump()),now,now))
        return {"id":ident,"status":"OPEN","createdAtEpochMillis":now,**body.model_dump()}

    @app.patch("/v1/crm/tickets/{ticket_id}")
    def update_ticket(ticket_id: str, status: Literal["OPEN","IN_PROGRESS","WAITING_CUSTOMER","RESOLVED","CLOSED"], authorization: str | None = Header(default=None)):
        return set_ticket_status(ticket_id, status, authorization)

    @app.post("/v1/crm/tickets/{ticket_id}/status")
    def update_ticket_status(ticket_id: str, body: TicketStatusInput, authorization: str | None = Header(default=None)):
        return set_ticket_status(ticket_id, body.status, authorization)

    def set_ticket_status(ticket_id: str, status: str, authorization: str | None):
        user=uid(authorization); now=int(time.time()*1000)
        with db() as c:
            init(c); cur=c.execute("UPDATE crm_tickets SET status=?,updated_at=? WHERE user_id=? AND ticket_id=?",(status,now,user,ticket_id))
            if cur.rowcount != 1: raise HTTPException(404,"Ticket not found")
            row=c.execute("SELECT payload FROM crm_tickets WHERE user_id=? AND ticket_id=?",(user,ticket_id)).fetchone()
        return {"id":ticket_id,"status":status,"updatedAtEpochMillis":now,**decrypt_payload(row["payload"])}

    @app.get("/v1/crm/tickets")
    def list_tickets(authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c); rows=c.execute("SELECT ticket_id,payload,status,priority,updated_at FROM crm_tickets WHERE user_id=? ORDER BY updated_at DESC LIMIT 500",(user,)).fetchall()
        return {"items":[{"id":r["ticket_id"],"status":r["status"],"priority":r["priority"],"updatedAtEpochMillis":r["updated_at"],**decrypt_payload(r["payload"])} for r in rows]}

    @app.post("/v1/erp/orders/{order_id}/transition")
    def transition_order(order_id: str, body: OrderTransitionInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000)
        with db() as c:
            init(c)
            c.execute("BEGIN IMMEDIATE")
            replay=c.execute("SELECT result FROM business_transition_keys WHERE user_id=? AND idempotency_key=?",(user,body.idempotencyKey)).fetchone()
            if replay: return json.loads(replay["result"])
            order=c.execute("SELECT order_type,party_id,status,total,payload FROM business_orders WHERE user_id=? AND order_id=?",(user,order_id)).fetchone()
            if not order: raise HTTPException(404,"Order not found")
            payload=decrypt_payload(order["payload"]); lines=payload["lines"]; state=order["status"]; action=body.action
            if action=="CONFIRM":
                if state!="DRAFT": raise HTTPException(409,"Only draft orders can be confirmed")
                if order["order_type"]=="SALES":
                    advanced_table=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='adv_reservations'").fetchone()
                    advanced_rows=[]
                    if advanced_table:
                        advanced_rows=c.execute("SELECT product_id,quantity FROM adv_reservations r JOIN adv_lots l ON l.user_id=r.user_id AND l.lot_id=r.lot_id WHERE r.user_id=? AND r.reference_type='SALES_ORDER' AND r.reference_id=? AND r.state='ACTIVE'",(user,order_id)).fetchall()
                    if advanced_rows:
                        from decimal import Decimal
                        for line in lines:
                            reserved_qty=sum((Decimal(r["quantity"]) for r in advanced_rows if r["product_id"]==line["productId"]),Decimal("0"))
                            if reserved_qty < Decimal(str(line["quantity"])):
                                raise HTTPException(409,"Advanced lot reservations do not cover every sales order line")
                    else:
                        for line in lines:
                            warehouse="main"
                            balance=c.execute("SELECT quantity FROM inventory_balances WHERE user_id=? AND warehouse_id=? AND product_id=?",(user,warehouse,line["productId"])).fetchone()
                            available=float(balance["quantity"]) if balance else 0.0
                            reserved=c.execute("SELECT COALESCE(SUM(quantity),0) q FROM order_reservations WHERE user_id=? AND warehouse_id=? AND product_id=? AND state='RESERVED'",(user,warehouse,line["productId"])).fetchone()["q"]
                            if available-float(reserved)<float(line["quantity"]): raise HTTPException(409,"Insufficient available stock to reserve order")
                        for line in lines:
                            c.execute("INSERT INTO order_reservations VALUES(?,?,?,?,?,?,?)",(user,order_id,"main",line["productId"],line["quantity"],"RESERVED",now))
                state="CONFIRMED"
            elif action=="CANCEL":
                if state not in ("DRAFT","CONFIRMED"): raise HTTPException(409,"Order cannot be cancelled in this state")
                c.execute("UPDATE order_reservations SET state='RELEASED' WHERE user_id=? AND order_id=? AND state='RESERVED'",(user,order_id)); state="CANCELLED"
            elif action=="SHIP":
                if order["order_type"]!="SALES" or state!="CONFIRMED": raise HTTPException(409,"Sales order must be confirmed before shipment")
                state="SHIPPED"
            elif action=="DELIVER":
                if order["order_type"]!="SALES" or state!="SHIPPED": raise HTTPException(409,"Sales order must be shipped before delivery")
                for line in lines:
                    c.execute("UPDATE inventory_balances SET quantity=quantity-?,updated_at=? WHERE user_id=? AND warehouse_id='main' AND product_id=? AND quantity>=?",(line["quantity"],now,user,line["productId"],line["quantity"]))
                    if c.execute("SELECT changes()").fetchone()[0]!=1: raise HTTPException(409,"Stock changed; delivery rejected")
                    c.execute("UPDATE order_reservations SET state='CONSUMED' WHERE user_id=? AND order_id=? AND product_id=? AND state='RESERVED'",(user,order_id,line["productId"]))
                state="DELIVERED"
                _post_order_journal(c,user,order_id,order["total"],"SALES",now,encrypt_payload)
            elif action=="FULFILL":
                if state!="CONFIRMED": raise HTTPException(409,"Only confirmed orders can be fulfilled")
                if order["order_type"]=="SALES":
                    reservations=c.execute("SELECT * FROM order_reservations WHERE user_id=? AND order_id=? AND state='RESERVED'",(user,order_id)).fetchall()
                    if not reservations: raise HTTPException(409,"No active inventory reservation")
                    for reservation in reservations:
                        cur=c.execute("UPDATE inventory_balances SET quantity=quantity-?,updated_at=? WHERE user_id=? AND warehouse_id=? AND product_id=? AND quantity>=?",
                                      (reservation["quantity"],now,user,reservation["warehouse_id"],reservation["product_id"],reservation["quantity"]))
                        if cur.rowcount != 1: raise HTTPException(409,"Stock changed after reservation")
                        c.execute("UPDATE order_reservations SET state='CONSUMED' WHERE user_id=? AND order_id=? AND product_id=? AND state='RESERVED'",
                                  (user,order_id,reservation["product_id"]))
                        c.execute("INSERT INTO inventory_movements(user_id,idempotency_key,warehouse_id,product_id,movement_type,quantity,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (user,"order-fulfill:"+order_id+":"+reservation["product_id"],reservation["warehouse_id"],reservation["product_id"],"ISSUE",reservation["quantity"],encrypt_payload({"orderId":order_id}),now))
                    state="FULFILLED"
                    _post_order_journal(c,user,order_id,order["total"],"SALES",now,encrypt_payload)
                else:
                    for line in lines:
                        c.execute("INSERT INTO inventory_balances VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at",
                                  (user,"main",line["productId"],line["quantity"],now))
                    state="FULFILLED"
                    _post_order_journal(c,user,order_id,order["total"],"PURCHASE",now,encrypt_payload)
            elif action=="RECEIVE":
                if order["order_type"]!="PURCHASE" or state not in ("CONFIRMED","DRAFT"): raise HTTPException(409,"Purchase order must be confirmed before receipt")
                for line in lines:
                    c.execute("""INSERT INTO inventory_balances VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at""",(user,"main",line["productId"],line["quantity"],now))
                state="RECEIVED"
                _post_order_journal(c,user,order_id,order["total"],"PURCHASE",now,encrypt_payload)
            result={"id":order_id,"status":state,"action":action,"idempotencyKey":body.idempotencyKey}
            c.execute("UPDATE business_orders SET status=? WHERE user_id=? AND order_id=?",(state,user,order_id))
            c.execute("INSERT INTO business_transition_keys VALUES(?,?,?,?)",(user,body.idempotencyKey,json.dumps(result),now))
        return result

    def _post_order_journal(c, user, order_id, amount, kind, now, encrypt):
        amount=float(amount)
        if not math.isfinite(amount) or amount<=0: raise HTTPException(409,"Order value must be positive to post accounting")
        journal_id=uuid.uuid4().hex; reference=f"{kind}-{order_id}"
        debit="1100-RECEIVABLE" if kind=="SALES" else "1300-INVENTORY"
        credit="4100-SALES" if kind=="SALES" else "2100-PAYABLE"
        description="Sales delivered" if kind=="SALES" else "Purchase received"
        payload={"description":description,"sourceOrderId":order_id}
        c.execute("INSERT INTO journal_entries VALUES(?,?,?,?,?,?,?,?)",(user,journal_id,reference,"IRR",amount,amount,encrypt(payload),now))
        c.execute("INSERT INTO journal_lines VALUES(?,?,?,?,?,?,?)",(user,journal_id,1,debit,amount,0,description))
        c.execute("INSERT INTO journal_lines VALUES(?,?,?,?,?,?,?)",(user,journal_id,2,credit,0,amount,description))

    @app.post("/v1/erp/accounting/journals")
    def create_journal(body: JournalInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000); journal_id=uuid.uuid4().hex
        debit=credit=0.0; normalized=[]
        for index,line in enumerate(body.lines,1):
            account=str(line.get("accountCode","")).strip()
            d=float(line.get("debit",0)); cr=float(line.get("credit",0))
            if not account or not math.isfinite(d) or not math.isfinite(cr) or d<0 or cr<0 or (d>0 and cr>0) or (d==0 and cr==0):
                raise HTTPException(422,"Each journal line needs an account and either a positive debit or credit")
            debit+=d; credit+=cr
            normalized.append((index,account,d,cr,str(line.get("description",""))[:500]))
        if not math.isclose(debit,credit,rel_tol=1e-9,abs_tol=0.01): raise HTTPException(422,"Journal debits and credits must balance")
        with db() as c:
            init(c)
            try:
                c.execute("INSERT INTO journal_entries VALUES(?,?,?,?,?,?,?,?)",(user,journal_id,body.reference,body.currency,debit,credit,encrypt_payload({"description":body.description}),now))
            except Exception as exc:
                if "UNIQUE" in str(exc).upper(): raise HTTPException(409,"Journal reference already exists")
                raise
            for index,account,d,cr,description in normalized:
                c.execute("INSERT INTO journal_lines VALUES(?,?,?,?,?,?,?)",(user,journal_id,index,account,d,cr,description))
        return {"id":journal_id,"reference":body.reference,"currency":body.currency,"debitTotal":debit,"creditTotal":credit,"balanced":True,"posted":True}

    @app.get("/v1/erp/accounting/journals")
    def list_journals(authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c); rows=c.execute("SELECT journal_id,reference,currency,debit_total,credit_total,payload,created_at FROM journal_entries WHERE user_id=? ORDER BY created_at DESC LIMIT 500",(user,)).fetchall()
        return {"items":[{"id":r["journal_id"],"reference":r["reference"],"currency":r["currency"],"debitTotal":r["debit_total"],"creditTotal":r["credit_total"],"balanced":math.isclose(r["debit_total"],r["credit_total"],abs_tol=0.01),"createdAtEpochMillis":r["created_at"],**decrypt_payload(r["payload"])} for r in rows]}

    @app.post("/v1/erp/harvest")
    @app.post("/v1/erp/greenhouse/harvests")
    def record_harvest(body: HarvestInput, authorization: str | None = Header(default=None)):
        user=uid(authorization); now=int(time.time()*1000); harvest_id=uuid.uuid4().hex
        with db() as c:
            init(c)
            # Verify greenhouse and crop-cycle records are owned by this account's synchronized records.
            for entity_type,entity_id in (("greenhouse",body.greenhouseId),("crop_cycle",body.cropCycleId)):
                if not c.execute("SELECT 1 FROM records WHERE user_id=? AND entity_type=? AND entity_id=? AND deleted=0",(user,entity_type,entity_id)).fetchone():
                    raise HTTPException(404,f"{entity_type} not found in this account")
            if not c.execute("SELECT 1 FROM business_products WHERE user_id=? AND product_id=?",(user,body.productId)).fetchone():
                raise HTTPException(404,"Product not found in this account")
            c.execute("""INSERT INTO inventory_balances VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at""",(user,body.warehouseId,body.productId,body.quantity,now))
            payload=body.model_dump()
            c.execute("INSERT INTO greenhouse_harvests VALUES(?,?,?,?,?,?,?,?,?,?)",(user,harvest_id,body.greenhouseId,body.cropCycleId,body.productId,body.warehouseId,body.quantity,body.unitPrice,encrypt_payload(payload),now))
            c.execute("INSERT INTO inventory_movements(user_id,idempotency_key,warehouse_id,product_id,movement_type,quantity,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",(user,f"harvest:{harvest_id}",body.warehouseId,body.productId,"RECEIPT",body.quantity,encrypt_payload({"source":"HARVEST","harvestId":harvest_id,**payload}),now))
        return {"id":harvest_id,"status":"RECORDED","inventoryUpdated":True,"quantity":body.quantity,"unitPrice":body.unitPrice}

    @app.get("/v1/erp/harvest")
    @app.get("/v1/erp/greenhouse/harvests")
    def list_harvests(authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c); rows=c.execute("SELECT harvest_id,payload,created_at FROM greenhouse_harvests WHERE user_id=? ORDER BY created_at DESC LIMIT 500",(user,)).fetchall()
        return {"items":[{"id":r["harvest_id"],"createdAtEpochMillis":r["created_at"],**decrypt_payload(r["payload"])} for r in rows]}

    @app.get("/v1/erp/accounting/trial-balance")
    def trial_balance(authorization: str | None = Header(default=None)):
        user=uid(authorization)
        with db() as c:
            init(c); rows=c.execute("SELECT l.account_code,SUM(l.debit) debit,SUM(l.credit) credit FROM journal_lines l WHERE l.user_id=? GROUP BY l.account_code ORDER BY l.account_code",(user,)).fetchall()
        items=[{"accountCode":r["account_code"],"debit":r["debit"],"credit":r["credit"],"netDebit":r["debit"]-r["credit"]} for r in rows]
        return {"items":items,"totalDebit":sum(x["debit"] for x in items),"totalCredit":sum(x["credit"] for x in items)}
