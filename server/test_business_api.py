import base64
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

TEST_DB = Path("/tmp/molido-crm-erp-tests.sqlite3")
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "crm-erp-test-secret-with-at-least-32-characters"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(TEST_DB)

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def account(username: str):
    response = client.post("/v1/auth/register", json={
        "username": username, "password": "Strong-test-password-123"
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def create_customer(headers, name="Customer One"):
    response = client.post("/v1/crm/customers", headers=headers, json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()


def create_supplier(headers):
    response = client.post("/v1/erp/suppliers", headers=headers, json={"name": "Supplier One"})
    assert response.status_code == 200, response.text
    return response.json()


def create_product(headers, sku="TOM-001"):
    response = client.post("/v1/erp/products", headers=headers, json={
        "sku": sku, "name": "Tomato", "unit": "kg", "salePrice": 50000, "purchasePrice": 30000
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_crm_parties_are_account_isolated():
    owner = account("crmowner")
    other = account("crmother")
    customer = create_customer(owner)
    assert len(client.get("/v1/crm/customers", headers=owner).json()["items"]) == 1
    assert client.get("/v1/crm/customers", headers=other).json()["items"] == []
    assert customer["type"] == "CUSTOMER"


def test_product_sku_is_unique_per_account():
    owner = account("skuowner")
    other = account("skuother")
    create_product(owner)
    duplicate = client.post("/v1/erp/products", headers=owner, json={
        "sku": "TOM-001", "name": "Other Tomato", "unit": "kg"
    })
    assert duplicate.status_code == 409
    assert client.post("/v1/erp/products", headers=other, json={
        "sku": "TOM-001", "name": "Other Tomato", "unit": "kg"
    }).status_code == 200


def test_inventory_idempotency_and_no_negative_stock():
    owner = account("stockowner")
    product = create_product(owner)
    receipt = {
        "idempotencyKey": "receipt-key-0001", "productId": product["id"],
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 12
    }
    first = client.post("/v1/erp/inventory/movements", headers=owner, json=receipt)
    assert first.status_code == 200
    assert first.json()["balance"] == 12
    duplicate = client.post("/v1/erp/inventory/movements", headers=owner, json=receipt)
    assert duplicate.json()["status"] == "duplicate"
    issue = {**receipt, "idempotencyKey": "issue-key-00001", "movementType": "ISSUE", "quantity": 5}
    assert client.post("/v1/erp/inventory/movements", headers=owner, json=issue).json()["balance"] == 7
    too_much = {**receipt, "idempotencyKey": "issue-key-00002", "movementType": "ISSUE", "quantity": 8}
    assert client.post("/v1/erp/inventory/movements", headers=owner, json=too_much).status_code == 409
    balances = client.get("/v1/erp/inventory/balances", headers=owner).json()["items"]
    assert balances[0]["quantity"] == 7


def test_sales_and_purchase_orders_use_shared_parties_and_products():
    owner = account("ordersowner")
    customer = create_customer(owner)
    supplier = create_supplier(owner)
    product = create_product(owner)
    sales = client.post("/v1/erp/sales/orders", headers=owner, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 2, "unitPrice": 50000}]
    })
    assert sales.status_code == 200, sales.text
    assert sales.json()["status"] == "DRAFT"
    assert sales.json()["total"] == 100000
    purchase = client.post("/v1/erp/purchase/orders", headers=owner, json={
        "partyId": supplier["id"],
        "lines": [{"productId": product["id"], "quantity": 4, "unitPrice": 30000}]
    })
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["total"] == 120000


def test_finance_entries_remain_unposted_pending_approval():
    owner = account("financeowner")
    response = client.post("/v1/erp/finance/entries", headers=owner, json={
        "direction": "EXPENSE", "amount": 120000, "currency": "IRR",
        "category": "SEEDS", "description": "Seed purchase"
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_APPROVAL"
    assert response.json()["posted"] is False
    assert client.get("/v1/erp/finance/entries", headers=owner).json()["items"][0]["posted"] is False


def test_business_endpoints_require_authentication():
    response = client.get("/v1/crm/customers")
    assert response.status_code == 401


def test_order_cannot_reference_another_accounts_customer():
    owner = account("orderowner")
    other = account("orderother")
    customer = create_customer(owner)
    product = create_product(other)
    response = client.post("/v1/erp/sales/orders", headers=other, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 1, "unitPrice": 10}]
    })
    assert response.status_code == 404


def test_crm_lead_activity_and_support_ticket_lifecycle_creation():
    owner = account("crmflowowner")
    customer = create_customer(owner)
    lead = client.post("/v1/crm/leads", headers=owner, json={
        "customerId": customer["id"], "title": "Greenhouse tomato supply",
        "source": "REFERRAL", "estimatedValue": 2500000, "currency": "IRR",
        "stage": "QUALIFIED", "notes": "First qualification"
    })
    assert lead.status_code == 200, lead.text
    assert client.get("/v1/crm/leads?stage=QUALIFIED", headers=owner).json()["items"][0]["id"] == lead.json()["id"]
    activity = client.post("/v1/crm/activities", headers=owner, json={
        "leadId": lead.json()["id"], "customerId": customer["id"],
        "activityType": "CALL", "subject": "Initial call", "details": "Discussed volume"
    })
    assert activity.status_code == 200, activity.text
    ticket = client.post("/v1/crm/tickets", headers=owner, json={
        "customerId": customer["id"], "subject": "Delivery status",
        "description": "Customer requests delivery tracking", "priority": "HIGH"
    })
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["status"] == "OPEN"


def test_double_entry_journal_rejects_unbalanced_and_posts_balanced():
    owner = account("ledgerowner")
    unbalanced = client.post("/v1/erp/ledger/journals", headers=owner, json={
        "description": "Unbalanced", "lines": [
            {"accountCode": "1000", "debit": 100, "credit": 0},
            {"accountCode": "4000", "debit": 0, "credit": 90}
        ]
    })
    assert unbalanced.status_code == 422
    balanced = client.post("/v1/erp/ledger/journals", headers=owner, json={
        "description": "Opening capital", "lines": [
            {"accountCode": "1000", "debit": 1000, "credit": 0},
            {"accountCode": "3000", "debit": 0, "credit": 1000}
        ]
    })
    assert balanced.status_code == 200, balanced.text
    assert balanced.json()["status"] == "PENDING_APPROVAL"
    assert balanced.json()["posted"] is False
    journal_id = balanced.json()["id"]
    import os
    os.environ["MOLIDO_LEDGER_APPROVAL_TOKEN"] = "human-approval-token-for-ledger-testing-32"
    denied = client.post(f"/v1/erp/ledger/journals/{journal_id}/approve", headers=owner)
    assert denied.status_code == 403
    approved = client.post(f"/v1/erp/ledger/journals/{journal_id}/approve",
                           headers={**owner, "X-Approval-Token": os.environ["MOLIDO_LEDGER_APPROVAL_TOKEN"]})
    assert approved.status_code == 200 and approved.json()["posted"] is True
    report = client.get("/v1/erp/reports/financial", headers=owner)
    assert report.status_code == 200
    assert report.json()["journalCount"] == 1


def test_sales_order_reservation_fulfilment_and_settlement():
    owner = account("fulfilowner")
    customer = create_customer(owner)
    product = create_product(owner)
    receipt = client.post("/v1/erp/inventory/movements", headers=owner, json={
        "idempotencyKey": "initial-stock-0001", "productId": product["id"],
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 10
    })
    assert receipt.status_code == 200
    order = client.post("/v1/erp/sales/orders", headers=owner, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 4, "unitPrice": 250}]
    })
    assert order.status_code == 200
    order_id = order.json()["id"]
    confirm = client.post(f"/v1/erp/orders/{order_id}/transition", headers=owner, json={"action": "CONFIRM"})
    assert confirm.status_code == 200 and confirm.json()["status"] == "CONFIRMED"
    fulfill = client.post(f"/v1/erp/orders/{order_id}/transition", headers=owner, json={"action": "FULFILL"})
    assert fulfill.status_code == 200 and fulfill.json()["status"] == "FULFILLED"
    balance = client.get("/v1/erp/inventory/balances?warehouseId=main", headers=owner).json()["items"][0]["quantity"]
    assert balance == 6
    settlement = client.post("/v1/erp/settlements", headers=owner, json={
        "orderId": order_id, "amount": 1000, "method": "BANK_TRANSFER", "reference": "BANK-001"
    })
    assert settlement.status_code == 200, settlement.text
    assert settlement.json()["status"] == "POSTED"
    assert settlement.json()["journalId"]


def test_sales_reservation_prevents_overselling_and_releases_on_cancel():
    owner = account("reserveowner")
    customer = create_customer(owner)
    product = create_product(owner)
    client.post("/v1/erp/inventory/movements", headers=owner, json={
        "idempotencyKey": "reserve-stock-001", "productId": product["id"],
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 5
    })
    order = client.post("/v1/erp/sales/orders", headers=owner, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 5, "unitPrice": 100}]
    }).json()
    confirmed = client.post(f"/v1/erp/orders/{order['id']}/transition", headers=owner, json={"action": "CONFIRM"})
    assert confirmed.status_code == 200
    second = client.post("/v1/erp/sales/orders", headers=owner, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 1, "unitPrice": 100}]
    }).json()
    blocked = client.post(f"/v1/erp/orders/{second['id']}/transition", headers=owner, json={"action": "CONFIRM"})
    assert blocked.status_code == 409
    cancelled = client.post(f"/v1/erp/orders/{order['id']}/transition", headers=owner, json={"action": "CANCEL"})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"


def test_harvest_batch_posts_inventory_against_synced_greenhouse_and_crop_cycle():
    owner = account("harvestowner")
    product = create_product(owner)
    push = client.post("/v1/sync/push", headers=owner, json={"operations": [
        {"idempotencyKey": "gh-sync-harvest-001", "entityType": "greenhouse", "entityId": "gh-h1",
         "operation": "CREATE", "payload": {"id": "gh-h1", "name": "Greenhouse 1"}, "baseVersion": 0},
        {"idempotencyKey": "cycle-sync-harvest-001", "entityType": "crop_cycle", "entityId": "cycle-h1",
         "operation": "CREATE", "payload": {"id": "cycle-h1", "greenhouseId": "gh-h1"}, "baseVersion": 0}
    ]})
    assert push.status_code == 200, push.text
    harvested = client.post("/v1/erp/harvest", headers=owner, json={
        "greenhouseId": "gh-h1", "cropCycleId": "cycle-h1",
        "productId": product["id"], "warehouseId": "main",
        "quantity": 24.5, "unit": "kg", "qualityGrade": "A"
    })
    assert harvested.status_code == 200, harvested.text
    assert harvested.json()["inventoryUpdated"] is True
    balances = client.get("/v1/erp/inventory/balances?warehouseId=main", headers=owner).json()["items"]
    assert balances[0]["quantity"] == 24.5


def test_crm_lead_and_ticket_are_isolated_and_statuses_transition():
    owner = account("crmstatusowner")
    other = account("crmstatusother")
    lead = client.post("/v1/crm/leads", headers=owner, json={"title": "Lead One"}).json()
    customer = create_customer(owner)
    ticket = client.post("/v1/crm/tickets", headers=owner, json={
        "customerId": customer["id"], "subject": "Damaged packaging",
        "description": "Customer reports damaged packaging", "priority": "URGENT"
    }).json()
    assert client.get("/v1/crm/leads", headers=other).json()["items"] == []
    assert client.get("/v1/crm/tickets", headers=other).json()["items"] == []
    stage = client.post(f"/v1/crm/leads/{lead['id']}/stage", headers=owner, json={"stage": "PROPOSAL"})
    assert stage.status_code == 200 and stage.json()["stage"] == "PROPOSAL"
    status = client.post(f"/v1/crm/tickets/{ticket['id']}/status", headers=owner, json={"status": "RESOLVED"})
    assert status.status_code == 200 and status.json()["status"] == "RESOLVED"


def test_concurrent_sales_reservations_cannot_oversell_stock():
    owner = account("parallelreserve")
    customer = create_customer(owner)
    product = create_product(owner)
    client.post("/v1/erp/inventory/movements", headers=owner, json={
        "idempotencyKey": "parallel-stock-001", "productId": product["id"],
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 5
    })
    orders = []
    for index in range(2):
        order = client.post("/v1/erp/sales/orders", headers=owner, json={
            "partyId": customer["id"],
            "lines": [{"productId": product["id"], "quantity": 4, "unitPrice": 100}]
        })
        assert order.status_code == 200
        orders.append(order.json()["id"])

    def confirm(order_id):
        from fastapi.testclient import TestClient
        with TestClient(app) as isolated_client:
            return isolated_client.post(
                f"/v1/erp/orders/{order_id}/transition",
                headers=owner, json={"action": "CONFIRM"}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(confirm, orders))
    assert sorted(statuses) == [200, 409]
    reservations = client.get("/v1/erp/inventory/balances?warehouseId=main", headers=owner).json()["items"]
    assert reservations[0]["quantity"] == 5

def test_inventory_idempotency_key_rejects_changed_payload_without_mutating_stock():
    owner = account("stockkeyowner")
    other = account("stockkeyother")
    product = create_product(owner, "KEY-001")
    other_product = create_product(other, "KEY-001")
    request = {
        "idempotencyKey": "inventory-key-collision-001",
        "productId": product["id"],
        "warehouseId": "main",
        "movementType": "RECEIPT",
        "quantity": 12,
        "reference": "SUPPLIER-RECEIPT-1",
        "notes": "Initial receipt",
    }
    created = client.post("/v1/erp/inventory/movements", headers=owner, json=request)
    assert created.status_code == 200, created.text
    assert created.json()["balance"] == 12

    replay = client.post("/v1/erp/inventory/movements", headers=owner, json=request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "duplicate"
    assert replay.json()["movementId"] == created.json()["movementId"]

    changed = client.post(
        "/v1/erp/inventory/movements",
        headers=owner,
        json={**request, "quantity": 99},
    )
    assert changed.status_code == 409, changed.text

    balances = client.get("/v1/erp/inventory/balances", headers=owner).json()["items"]
    assert len(balances) == 1
    assert balances[0]["quantity"] == 12

    # Idempotency keys are tenant-scoped, not globally reserved across accounts.
    other_request = {**request, "productId": other_product["id"], "quantity": 3}
    other_created = client.post(
        "/v1/erp/inventory/movements", headers=other, json=other_request
    )
    assert other_created.status_code == 200, other_created.text
    assert other_created.json()["balance"] == 3

