from __future__ import annotations

import os
import hmac
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
    currency: str = Field(default="IRR", pattern=r"^[A-Z]{3}$")
    stage: Literal["NEW", "QUALIFIED", "PROPOSAL", "WON", "LOST"] = "NEW"
    nextActionAtEpochMillis: int | None = None
    notes: str = Field(default="", max_length=4000)


class CrmActivityInput(BaseModel):
    leadId: str | None = None
    customerId: str | None = None
    activityType: Literal["CALL", "MEETING", "EMAIL", "VISIT", "NOTE"] 
    subject: str = Field(min_length=2, max_length=200)
    details: str = Field(default="", max_length=4000)
    occurredAtEpochMillis: int | None = None
    nextFollowUpAtEpochMillis: int | None = None


class TicketInput(BaseModel):
    customerId: str | None = None
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=5000)
    priority: Literal["LOW", "NORMAL", "HIGH", "URGENT"] = "NORMAL"
    category: str = Field(default="GENERAL", max_length=60)


class LeadStageInput(BaseModel):
    stage: Literal["NEW", "QUALIFIED", "PROPOSAL", "WON", "LOST"]
    notes: str | None = Field(default=None, max_length=4000)


class TicketStatusInput(BaseModel):
    status: Literal["OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED", "CLOSED"]


class OrderTransitionInput(BaseModel):
    action: Literal["CONFIRM", "FULFILL", "CANCEL"]


class HarvestInput(BaseModel):
    greenhouseId: str = Field(min_length=1, max_length=200)
    cropCycleId: str = Field(min_length=1, max_length=200)
    productId: str = Field(min_length=1, max_length=200)
    warehouseId: str = Field(min_length=1, max_length=200)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=32)
    qualityGrade: str = Field(default="UNASSESSED", max_length=40)
    harvestedAtEpochMillis: int | None = None
    notes: str = Field(default="", max_length=2000)


class JournalLine(BaseModel):
    accountCode: str = Field(min_length=2, max_length=40)
    debit: float = Field(default=0, ge=0, allow_inf_nan=False)
    credit: float = Field(default=0, ge=0, allow_inf_nan=False)
    description: str = Field(default="", max_length=500)


class JournalInput(BaseModel):
    dateEpochMillis: int | None = None
    reference: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=3, max_length=1000)
    currency: str = Field(default="IRR", pattern=r"^[A-Z]{3}$")
    lines: list[JournalLine] = Field(min_length=2, max_length=100)


class SettlementInput(BaseModel):
    orderId: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0, allow_inf_nan=False)
    method: Literal["CASH", "BANK_TRANSFER", "CARD", "OTHER"]
    reference: str | None = Field(default=None, max_length=200)
    receivedAtEpochMillis: int | None = None


def register_advanced_business_routes(app, db, current_user, encrypt_payload, decrypt_payload) -> None:
    def ensure(connection):
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS crm_leads (
          user_id TEXT NOT NULL, lead_id TEXT NOT NULL, customer_id TEXT, stage TEXT NOT NULL,
          estimated_value REAL NOT NULL, currency TEXT NOT NULL, payload TEXT NOT NULL,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,lead_id)
        );
        CREATE TABLE IF NOT EXISTS crm_activities (
          user_id TEXT NOT NULL, activity_id TEXT NOT NULL, lead_id TEXT, customer_id TEXT,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(user_id,activity_id)
        );
        CREATE TABLE IF NOT EXISTS crm_tickets (
          user_id TEXT NOT NULL, ticket_id TEXT NOT NULL, customer_id TEXT, status TEXT NOT NULL,
          priority TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,ticket_id)
        );
        CREATE TABLE IF NOT EXISTS inventory_reservations (
          user_id TEXT NOT NULL, reservation_id TEXT NOT NULL, order_id TEXT NOT NULL,
          warehouse_id TEXT NOT NULL, product_id TEXT NOT NULL, quantity REAL NOT NULL,
          status TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,reservation_id),
          UNIQUE(user_id,order_id,product_id)
        );
        CREATE TABLE IF NOT EXISTS harvest_batches (
          user_id TEXT NOT NULL, batch_id TEXT NOT NULL, greenhouse_id TEXT NOT NULL,
          crop_cycle_id TEXT NOT NULL, product_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
          quantity REAL NOT NULL, unit TEXT NOT NULL, quality_grade TEXT NOT NULL,
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,batch_id)
        );
        CREATE TABLE IF NOT EXISTS ledger_accounts (
          user_id TEXT NOT NULL, account_code TEXT NOT NULL, name TEXT NOT NULL,
          account_type TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(user_id,account_code)
        );
        CREATE TABLE IF NOT EXISTS journal_entries (
          user_id TEXT NOT NULL, journal_id TEXT NOT NULL, reference TEXT,
          description TEXT NOT NULL, currency TEXT NOT NULL, total_debit REAL NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
          payload TEXT NOT NULL, created_at INTEGER NOT NULL,
          PRIMARY KEY(user_id,journal_id)
        );
        CREATE TABLE IF NOT EXISTS settlements (
          user_id TEXT NOT NULL, settlement_id TEXT NOT NULL, order_id TEXT NOT NULL,
          amount REAL NOT NULL, method TEXT NOT NULL, reference TEXT, payload TEXT NOT NULL,
          created_at INTEGER NOT NULL, PRIMARY KEY(user_id,settlement_id)
        );
        CREATE INDEX IF NOT EXISTS idx_crm_leads_stage ON crm_leads(user_id,stage,updated_at);
        CREATE INDEX IF NOT EXISTS idx_crm_tickets_status ON crm_tickets(user_id,status,created_at);
        CREATE INDEX IF NOT EXISTS idx_harvest_cycle ON harvest_batches(user_id,crop_cycle_id);
        """)

    def uid_for(authorization):
        return current_user(authorization)

    def setup(connection, uid):
        # Use account-scoped chart of accounts, initialized idempotently.
        ensure(connection)
        defaults = [
          ("1000","نقد و بانک","ASSET"),("1100","حساب‌های دریافتنی","ASSET"),
          ("1200","موجودی کالا","ASSET"),("2000","حساب‌های پرداختنی","LIABILITY"),
          ("3000","سرمایه","EQUITY"),("4000","فروش محصولات","REVENUE"),
          ("5000","بهای تمام‌شده فروش","EXPENSE"),("6000","هزینه‌های تولید","EXPENSE")
        ]
        for code,name,kind in defaults:
            connection.execute("INSERT OR IGNORE INTO ledger_accounts(user_id,account_code,name,account_type) VALUES(?,?,?,?)",
                               (uid,code,name,kind))

    def validate_party(connection, uid, party_id):
        if party_id and not connection.execute(
            "SELECT 1 FROM business_parties WHERE user_id=? AND party_id=? AND party_type='CUSTOMER'",
            (uid,party_id)).fetchone():
            raise HTTPException(404,"Customer not found in this account")

    @app.post("/v1/crm/leads")
    def create_lead(body: LeadInput, authorization: str | None = Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000); lead_id=uuid.uuid4().hex
        with db() as c:
            setup(c,uid); validate_party(c,uid,body.customerId)
            c.execute("INSERT INTO crm_leads VALUES(?,?,?,?,?,?,?,?,?)",
                      (uid,lead_id,body.customerId,body.stage,body.estimatedValue,body.currency,
                       encrypt_payload(body.model_dump()),now,now))
        return {"id":lead_id,**body.model_dump(),"createdAtEpochMillis":now}

    @app.get("/v1/crm/leads")
    def list_leads(stage: str | None=None, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("SELECT lead_id,payload,created_at FROM crm_leads WHERE user_id=? AND (? IS NULL OR stage=?) ORDER BY updated_at DESC LIMIT 500",
                           (uid,stage,stage)).fetchall()
        return {"items":[{"id":r["lead_id"],**decrypt_payload(r["payload"]),"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.post("/v1/crm/activities")
    def create_activity(body: CrmActivityInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000); item_id=uuid.uuid4().hex
        with db() as c:
            setup(c,uid); validate_party(c,uid,body.customerId)
            if body.leadId and not c.execute("SELECT 1 FROM crm_leads WHERE user_id=? AND lead_id=?",(uid,body.leadId)).fetchone():
                raise HTTPException(404,"Lead not found in this account")
            c.execute("INSERT INTO crm_activities VALUES(?,?,?,?,?,?)",
                      (uid,item_id,body.leadId,body.customerId,encrypt_payload(body.model_dump()),now))
        return {"id":item_id,**body.model_dump(),"createdAtEpochMillis":now}

    @app.get("/v1/crm/activities")
    def list_activities(leadId: str | None=None, customerId: str | None=None,
                        authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("""SELECT activity_id,payload,created_at FROM crm_activities
                WHERE user_id=? AND (? IS NULL OR lead_id=?) AND (? IS NULL OR customer_id=?)
                ORDER BY created_at DESC LIMIT 500""",(uid,leadId,leadId,customerId,customerId)).fetchall()
        return {"items":[{"id":r["activity_id"],**decrypt_payload(r["payload"]),"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.post("/v1/crm/leads/{lead_id}/stage")
    def update_lead_stage(lead_id: str, body: LeadStageInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000)
        with db() as c:
            setup(c,uid)
            row=c.execute("SELECT payload FROM crm_leads WHERE user_id=? AND lead_id=?",(uid,lead_id)).fetchone()
            if not row: raise HTTPException(404,"Lead not found")
            payload=decrypt_payload(row["payload"]); payload["stage"]=body.stage
            if body.notes is not None: payload["notes"]=body.notes
            c.execute("UPDATE crm_leads SET stage=?,payload=?,updated_at=? WHERE user_id=? AND lead_id=?",
                      (body.stage,encrypt_payload(payload),now,uid,lead_id))
        return {"id":lead_id,"stage":body.stage,"updatedAtEpochMillis":now}

    @app.post("/v1/crm/tickets")
    def create_ticket(body: TicketInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000); ticket_id=uuid.uuid4().hex
        with db() as c:
            setup(c,uid); validate_party(c,uid,body.customerId)
            c.execute("INSERT INTO crm_tickets VALUES(?,?,?,?,?,?,?)",
                      (uid,ticket_id,body.customerId,"OPEN",body.priority,encrypt_payload(body.model_dump()),now))
        return {"id":ticket_id,"status":"OPEN",**body.model_dump(),"createdAtEpochMillis":now}

    @app.post("/v1/crm/tickets/{ticket_id}/status")
    def update_ticket_status(ticket_id: str, body: TicketStatusInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            changed=c.execute("UPDATE crm_tickets SET status=? WHERE user_id=? AND ticket_id=?",
                              (body.status,uid,ticket_id)).rowcount
            if not changed: raise HTTPException(404,"Ticket not found")
        return {"id":ticket_id,"status":body.status}

    @app.get("/v1/crm/tickets")
    def list_tickets(status: str | None=None, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("SELECT ticket_id,status,payload,created_at FROM crm_tickets WHERE user_id=? AND (? IS NULL OR status=?) ORDER BY created_at DESC LIMIT 500",
                           (uid,status,status)).fetchall()
        return {"items":[{"id":r["ticket_id"],"status":r["status"],**decrypt_payload(r["payload"]),"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.post("/v1/erp/orders/{order_id}/transition")
    def transition_order(order_id: str, body: OrderTransitionInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000)
        with db() as c:
            setup(c,uid)
            c.execute("BEGIN IMMEDIATE")
            order=c.execute("SELECT order_type,status,payload FROM business_orders WHERE user_id=? AND order_id=?",(uid,order_id)).fetchone()
            if not order: raise HTTPException(404,"Order not found")
            payload=decrypt_payload(order["payload"]); lines=payload.get("lines",[])
            current=order["status"]; action=body.action
            if action=="CONFIRM":
                if current!="DRAFT": raise HTTPException(409,"Only draft orders can be confirmed")
                if order["order_type"]=="SALES":
                    for line in lines:
                        bal=c.execute("SELECT quantity FROM inventory_balances WHERE user_id=? AND warehouse_id=? AND product_id=?",
                                      (uid,"main",line["productId"])).fetchone()
                        reserved=c.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM inventory_reservations WHERE user_id=? AND warehouse_id=? AND product_id=? AND status='ACTIVE'",
                                           (uid,"main",line["productId"])).fetchone()["n"]
                        available=(float(bal["quantity"]) if bal else 0)-float(reserved)
                        if available < float(line["quantity"]): raise HTTPException(409,"Insufficient available stock to reserve order")
                    for line in lines:
                        c.execute("INSERT INTO inventory_reservations VALUES(?,?,?,?,?,?,?,?)",
                                  (uid,uuid.uuid4().hex,order_id,"main",line["productId"],line["quantity"],"ACTIVE",now))
                next_status="CONFIRMED"
            elif action=="FULFILL":
                if current!="CONFIRMED": raise HTTPException(409,"Only confirmed orders can be fulfilled")
                if order["order_type"]=="SALES":
                    reservations=c.execute("SELECT * FROM inventory_reservations WHERE user_id=? AND order_id=? AND status='ACTIVE'",(uid,order_id)).fetchall()
                    if not reservations: raise HTTPException(409,"No active stock reservation")
                    for r in reservations:
                        cur=c.execute("SELECT quantity FROM inventory_balances WHERE user_id=? AND warehouse_id=? AND product_id=?",
                                      (uid,r["warehouse_id"],r["product_id"])).fetchone()
                        if not cur or float(cur["quantity"]) < float(r["quantity"]): raise HTTPException(409,"Stock changed after reservation")
                        c.execute("UPDATE inventory_balances SET quantity=quantity-?,updated_at=? WHERE user_id=? AND warehouse_id=? AND product_id=?",
                                  (r["quantity"],now,uid,r["warehouse_id"],r["product_id"]))
                        c.execute("UPDATE inventory_reservations SET status='CONSUMED' WHERE user_id=? AND reservation_id=?",(uid,r["reservation_id"]))
                        c.execute("INSERT INTO inventory_movements(user_id,idempotency_key,warehouse_id,product_id,movement_type,quantity,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (uid,f"order-fulfil:{order_id}:{r['product_id']}","main",r["product_id"],"ISSUE",r["quantity"],encrypt_payload({"orderId":order_id}),now))
                else:
                    for line in lines:
                        c.execute("""INSERT INTO inventory_balances(user_id,warehouse_id,product_id,quantity,updated_at)
                          VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE SET
                          quantity=inventory_balances.quantity+excluded.quantity,updated_at=excluded.updated_at""",
                          (uid,"main",line["productId"],line["quantity"],now))
                next_status="FULFILLED"
            else:
                if current not in ("DRAFT","CONFIRMED"): raise HTTPException(409,"This order cannot be cancelled")
                c.execute("UPDATE inventory_reservations SET status='RELEASED' WHERE user_id=? AND order_id=? AND status='ACTIVE'",(uid,order_id))
                next_status="CANCELLED"
            c.execute("UPDATE business_orders SET status=? WHERE user_id=? AND order_id=?",(next_status,uid,order_id))
        return {"id":order_id,"status":next_status,"updatedAtEpochMillis":now}

    @app.post("/v1/erp/harvest")
    def record_harvest(body: HarvestInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); now=int(time.time()*1000); batch_id=uuid.uuid4().hex
        with db() as c:
            setup(c,uid)
            c.execute("BEGIN IMMEDIATE")
            if not c.execute("SELECT 1 FROM business_products WHERE user_id=? AND product_id=?",(uid,body.productId)).fetchone():
                raise HTTPException(404,"Product not found")
            if not c.execute("SELECT 1 FROM records WHERE user_id=? AND entity_type='greenhouse' AND entity_id=? AND deleted=0",(uid,body.greenhouseId)).fetchone():
                raise HTTPException(404,"Greenhouse not found in synchronized records")
            if not c.execute("SELECT 1 FROM records WHERE user_id=? AND entity_type='crop_cycle' AND entity_id=? AND deleted=0",(uid,body.cropCycleId)).fetchone():
                raise HTTPException(404,"Crop cycle not found in synchronized records")
            payload=body.model_dump()
            c.execute("""INSERT INTO inventory_balances(user_id,warehouse_id,product_id,quantity,updated_at)
              VALUES(?,?,?,?,?) ON CONFLICT(user_id,warehouse_id,product_id) DO UPDATE SET
              quantity=inventory_balances.quantity+excluded.quantity,updated_at=excluded.updated_at""",
              (uid,body.warehouseId,body.productId,body.quantity,now))
            c.execute("INSERT INTO harvest_batches VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (uid,batch_id,body.greenhouseId,body.cropCycleId,body.productId,body.warehouseId,
                       body.quantity,body.unit,body.qualityGrade,encrypt_payload(payload),now))
            c.execute("INSERT INTO inventory_movements(user_id,idempotency_key,warehouse_id,product_id,movement_type,quantity,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (uid,f"harvest:{batch_id}",body.warehouseId,body.productId,"RECEIPT",body.quantity,encrypt_payload({"harvestBatchId":batch_id}),now))
        return {"id":batch_id,"status":"RECORDED","inventoryUpdated":True,"quantity":body.quantity,"unit":body.unit}

    @app.get("/v1/erp/harvest")
    def list_harvest(authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("SELECT batch_id,payload,created_at FROM harvest_batches WHERE user_id=? ORDER BY created_at DESC LIMIT 500",(uid,)).fetchall()
        return {"items":[{"id":r["batch_id"],**decrypt_payload(r["payload"]),"createdAtEpochMillis":r["created_at"]} for r in rows]}

    @app.get("/v1/erp/ledger/accounts")
    def ledger_accounts(authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("SELECT account_code,name,account_type FROM ledger_accounts WHERE user_id=? AND active=1 ORDER BY account_code",(uid,)).fetchall()
        return {"items":[{"code":r["account_code"],"name":r["name"],"type":r["account_type"]} for r in rows]}

    @app.post("/v1/erp/ledger/journals")
    def post_journal(body: JournalInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); journal_id=uuid.uuid4().hex; now=int(time.time()*1000)
        debit=sum(x.debit for x in body.lines); credit=sum(x.credit for x in body.lines)
        if abs(debit-credit)>0.000001 or debit<=0: raise HTTPException(422,"Journal must balance: total debit must equal total credit and be positive")
        for line in body.lines:
            if (line.debit>0)==(line.credit>0): raise HTTPException(422,"Each journal line must contain either debit or credit, not both")
        with db() as c:
            setup(c,uid)
            c.execute("BEGIN IMMEDIATE")
            for line in body.lines:
                if not c.execute("SELECT 1 FROM ledger_accounts WHERE user_id=? AND account_code=? AND active=1",(uid,line.accountCode)).fetchone():
                    raise HTTPException(422,f"Unknown account code: {line.accountCode}")
            payload=body.model_dump()
            c.execute("INSERT INTO journal_entries(user_id,journal_id,reference,description,currency,total_debit,status,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (uid,journal_id,body.reference,body.description,body.currency,debit,"PENDING_APPROVAL",encrypt_payload(payload),now))
        return {"id":journal_id,"status":"PENDING_APPROVAL","posted":False,"totalDebit":debit,"totalCredit":credit,"currency":body.currency}

    @app.post("/v1/erp/ledger/journals/{journal_id}/approve")
    def approve_journal(journal_id: str, x_approval_token: str | None=Header(default=None),
                        authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        configured=os.environ.get("MOLIDO_LEDGER_APPROVAL_TOKEN","")
        if len(configured)<32: raise HTTPException(503,"Ledger approval token is not configured")
        if not x_approval_token or not hmac.compare_digest(configured,x_approval_token):
            raise HTTPException(403,"Ledger approval authorization failed")
        with db() as c:
            setup(c,uid)
            changed=c.execute("UPDATE journal_entries SET status='POSTED' WHERE user_id=? AND journal_id=? AND status='PENDING_APPROVAL'",
                              (uid,journal_id)).rowcount
            if not changed: raise HTTPException(404,"Pending journal not found")
        return {"id":journal_id,"status":"POSTED","posted":True}

    @app.post("/v1/erp/settlements")
    def create_settlement(body: SettlementInput, authorization: str | None=Header(default=None)):
        uid=uid_for(authorization); settlement_id=uuid.uuid4().hex; now=int(time.time()*1000)
        with db() as c:
            setup(c,uid)
            c.execute("BEGIN IMMEDIATE")
            order=c.execute("SELECT order_type,status,total FROM business_orders WHERE user_id=? AND order_id=?",(uid,body.orderId)).fetchone()
            if not order or order["status"] not in ("CONFIRMED","FULFILLED"): raise HTTPException(404,"Active confirmed order not found")
            paid=c.execute("SELECT COALESCE(SUM(amount),0) AS n FROM settlements WHERE user_id=? AND order_id=?",(uid,body.orderId)).fetchone()["n"]
            if float(paid)+body.amount>float(order["total"])+0.000001: raise HTTPException(409,"Settlement exceeds order outstanding amount")
            c.execute("INSERT INTO settlements VALUES(?,?,?,?,?,?,?,?)",
                      (uid,settlement_id,body.orderId,body.amount,body.method,body.reference,encrypt_payload(body.model_dump()),now))
        return {"id":settlement_id,"orderId":body.orderId,"amount":body.amount,"status":"RECORDED_NOT_RECONCILED"}

    @app.get("/v1/erp/reports/financial")
    def financial_report(authorization: str | None=Header(default=None)):
        uid=uid_for(authorization)
        with db() as c:
            setup(c,uid)
            rows=c.execute("SELECT payload FROM journal_entries WHERE user_id=? AND status='POSTED'",(uid,)).fetchall()
            totals={}
            for row in rows:
                journal=decrypt_payload(row["payload"])
                for line in journal["lines"]:
                    key=line["accountCode"]
                    pair=totals.setdefault(key,{"debit":0.0,"credit":0.0})
                    pair["debit"]+=float(line["debit"]); pair["credit"]+=float(line["credit"])
            accounts=c.execute("SELECT account_code,name,account_type FROM ledger_accounts WHERE user_id=?",(uid,)).fetchall()
        return {"accounts":[{"code":a["account_code"],"name":a["name"],"type":a["account_type"],
                             **totals.get(a["account_code"],{"debit":0.0,"credit":0.0})} for a in accounts],
                "journalCount":len(rows),"basis":"posted double-entry journals only; pending approvals excluded"}
