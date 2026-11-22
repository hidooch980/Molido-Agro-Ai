import base64
import os
from pathlib import Path
import tempfile

DB = Path(tempfile.gettempdir()) / "molido-business-workflows-tests.sqlite3"
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "business-workflows-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def account(name):
    response = client.post("/v1/auth/register", json={"username": name, "password": "Strong-test-password-123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["accessToken"]}


def customer(headers):
    return client.post("/v1/crm/customers", headers=headers, json={"name": "Greenhouse Buyer"}).json()


def supplier(headers):
    return client.post("/v1/erp/suppliers", headers=headers, json={"name": "Seed Supplier"}).json()


def product(headers):
    return client.post("/v1/erp/products", headers=headers, json={
        "sku": "CUC-001", "name": "Cucumber", "unit": "kg", "salePrice": 100, "purchasePrice": 50
    }).json()


def order(headers, party, product_id, kind="sales", quantity=4, price=100):
    route = "/v1/erp/sales/orders" if kind == "sales" else "/v1/erp/purchase/orders"
    response = client.post(route, headers=headers, json={
        "partyId": party["id"],
        "lines": [{"productId": product_id, "quantity": quantity, "unitPrice": price}]
    })
    assert response.status_code == 200, response.text
    return response.json()


def transition(headers, order_id, action, key):
    return client.post(f"/v1/erp/orders/{order_id}/transition", headers=headers, json={
        "action": action, "idempotencyKey": key
    })


def stock(headers, product_id, qty):
    return client.post("/v1/erp/inventory/movements", headers=headers, json={
        "idempotencyKey": "stock-receipt-0001", "productId": product_id,
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": qty
    })


def test_crm_activities_opportunities_and_support_tickets():
    h = account("workflowcrm")
    c = customer(h)
    activity = client.post("/v1/crm/activities", headers=h, json={
        "customerId": c["id"], "activityType": "CALL", "subject": "Follow up",
        "description": "Discuss next planting cycle"
    })
    assert activity.status_code == 200, activity.text
    opportunity = client.post("/v1/crm/opportunities", headers=h, json={
        "customerId": c["id"], "title": "Spring cucumber supply", "expectedValue": 250000
    })
    assert opportunity.status_code == 200, opportunity.text
    ticket = client.post("/v1/crm/tickets", headers=h, json={
        "customerId": c["id"], "subject": "Quality issue", "description": "Please review batch quality",
        "priority": "HIGH"
    })
    assert ticket.status_code == 200, ticket.text
    changed = client.patch(f"/v1/crm/tickets/{ticket.json()['id']}", params={"status": "IN_PROGRESS"}, headers=h)
    assert changed.status_code == 200 and changed.json()["status"] == "IN_PROGRESS"
    assert len(client.get("/v1/crm/opportunities", headers=h).json()["items"]) == 1


def test_sales_order_reservation_delivery_and_balanced_journal():
    h = account("workflowSales")
    c = customer(h); p = product(h)
    assert stock(h, p["id"], 10).status_code == 200
    o = order(h, c, p["id"])
    assert transition(h, o["id"], "CONFIRM", "sales-confirm-0001").json()["status"] == "CONFIRMED"
    too_much = order(h, c, p["id"], quantity=7)
    assert transition(h, too_much["id"], "CONFIRM", "sales-confirm-0002").status_code == 409
    assert transition(h, o["id"], "SHIP", "sales-ship-00001").json()["status"] == "SHIPPED"
    assert transition(h, o["id"], "DELIVER", "sales-deliver-001").json()["status"] == "DELIVERED"
    balances = client.get("/v1/erp/inventory/balances", headers=h).json()["items"]
    assert balances[0]["quantity"] == 6
    journals = client.get("/v1/erp/accounting/journals", headers=h).json()["items"]
    assert len(journals) == 1 and journals[0]["balanced"] is True


def test_purchase_receipt_adds_stock_and_posts_balanced_journal():
    h = account("workflowPurchase")
    s = supplier(h); p = product(h)
    o = order(h, s, p["id"], kind="purchase", quantity=9, price=50)
    assert transition(h, o["id"], "CONFIRM", "purchase-confirm-01").json()["status"] == "CONFIRMED"
    assert transition(h, o["id"], "RECEIVE", "purchase-receive-01").json()["status"] == "RECEIVED"
    balances = client.get("/v1/erp/inventory/balances", headers=h).json()["items"]
    assert balances[0]["quantity"] == 9
    assert client.get("/v1/erp/accounting/journals", headers=h).json()["items"][0]["balanced"] is True


def test_double_entry_journal_rejects_unbalanced_and_duplicate_reference():
    h = account("workflowLedger")
    body = {"reference": "MANUAL-001", "description": "Opening balance", "currency": "IRR",
            "lines": [{"accountCode": "1000", "debit": 100, "credit": 0},
                      {"accountCode": "3000", "debit": 0, "credit": 90}]}
    assert client.post("/v1/erp/accounting/journals", headers=h, json=body).status_code == 422
    body["lines"][1]["credit"] = 100
    first = client.post("/v1/erp/accounting/journals", headers=h, json=body)
    assert first.status_code == 200 and first.json()["balanced"] is True
    assert client.post("/v1/erp/accounting/journals", headers=h, json=body).status_code == 409
    trial = client.get("/v1/erp/accounting/trial-balance", headers=h).json()
    assert trial["totalDebit"] == trial["totalCredit"] == 100


def test_crm_and_accounting_records_are_account_isolated():
    owner = account("workflowOwner"); other = account("workflowOther")
    c = customer(owner)
    forbidden = client.post("/v1/crm/opportunities", headers=other, json={
        "customerId": c["id"], "title": "Should not attach to other account"
    })
    assert forbidden.status_code == 404
    assert client.get("/v1/erp/accounting/journals", headers=other).json()["items"] == []


def test_harvest_is_linked_to_account_greenhouse_crop_and_inventory():
    h = account("workflowHarvest")
    p = product(h)
    # Seed account-owned greenhouse and crop-cycle records through the normal sync API.
    push = client.post("/v1/sync/push", headers=h, json={"operations": [
        {"idempotencyKey": "gh-harvest-0001", "entityType": "greenhouse", "entityId": "gh-1",
         "operation": "CREATE", "payload": {"name": "North greenhouse"}, "baseVersion": 0},
        {"idempotencyKey": "cycle-harvest-01", "entityType": "crop_cycle", "entityId": "cycle-1",
         "operation": "CREATE", "payload": {"greenhouseId": "gh-1", "cropCode": "CUCUMBER"}, "baseVersion": 0}
    ]})
    assert push.status_code == 200
    result = client.post("/v1/erp/greenhouse/harvests", headers=h, json={
        "greenhouseId": "gh-1", "cropCycleId": "cycle-1", "productId": p["id"],
        "warehouseId": "main", "quantity": 22, "unitPrice": 80
    })
    assert result.status_code == 200, result.text
    assert result.json()["inventoryUpdated"] is True
    balances = client.get("/v1/erp/inventory/balances", headers=h).json()["items"]
    assert balances[0]["quantity"] == 22

def test_order_transition_idempotency_key_is_bound_to_order_and_action():
    h = account("workflowTransitionKey")
    s = supplier(h)
    p = product(h)
    first_order = order(h, s, p["id"], kind="purchase", quantity=2, price=50)
    second_order = order(h, s, p["id"], kind="purchase", quantity=3, price=50)

    key = "transition-bound-key-001"
    first = transition(h, first_order["id"], "CONFIRM", key)
    assert first.status_code == 200, first.text
    replay = transition(h, first_order["id"], "CONFIRM", key)
    assert replay.status_code == 200
    assert replay.json() == first.json()

    changed_action = transition(h, first_order["id"], "RECEIVE", key)
    assert changed_action.status_code == 409, changed_action.text

    changed_order = transition(h, second_order["id"], "CONFIRM", key)
    assert changed_order.status_code == 409, changed_order.text
    listed = client.get("/v1/erp/orders", headers=h, params={"orderType": "PURCHASE"})
    assert listed.status_code == 200
    states = {item["id"]: item["status"] for item in listed.json()["items"]}
    assert states[first_order["id"]] == "CONFIRMED"
    assert states[second_order["id"]] == "DRAFT"

def test_harvest_idempotency_prevents_duplicate_inventory_receipt():
    h = account("workflowHarvestIdempotency")
    p = product(h)
    push = client.post("/v1/sync/push", headers=h, json={"operations": [
        {"idempotencyKey": "gh-harvest-idempotent-01", "entityType": "greenhouse", "entityId": "gh-idem",
         "operation": "CREATE", "payload": {"name": "Harvest greenhouse"}, "baseVersion": 0},
        {"idempotencyKey": "cycle-harvest-idem-1", "entityType": "crop_cycle", "entityId": "cycle-idem",
         "operation": "CREATE", "payload": {"greenhouseId": "gh-idem", "cropCode": "TOMATO"}, "baseVersion": 0}
    ]})
    assert push.status_code == 200, push.text
    body = {"idempotencyKey": "harvest-receipt-idempotency-001", "greenhouseId": "gh-idem",
            "cropCycleId": "cycle-idem", "productId": p["id"], "warehouseId": "main",
            "quantity": 22, "unitPrice": 80, "unit": "kg"}
    first = client.post("/v1/erp/greenhouse/harvests", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v1/erp/greenhouse/harvests", headers=h, json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == first.json()["id"]

    changed = client.post("/v1/erp/greenhouse/harvests", headers=h, json={**body, "quantity": 25})
    assert changed.status_code == 409, changed.text
    balances = client.get("/v1/erp/inventory/balances", headers=h).json()["items"]
    assert len(balances) == 1
    assert balances[0]["quantity"] == 22

