import base64
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid

DB = Path("/tmp/molido-business-settlement-tests.sqlite3")
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "business-settlement-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)

import app as app_module
from fastapi.testclient import TestClient
client = TestClient(app_module.app)


def setup_delivered_sales_order():
    auth = client.post("/v1/auth/register", json={
        "username": "settlementUser-" + uuid.uuid4().hex[:10], "password": "Strong-test-password-123"
    })
    assert auth.status_code == 200, auth.text
    h = {"Authorization": "Bearer " + auth.json()["accessToken"]}
    customer = client.post("/v1/crm/customers", headers=h, json={"name": "Settlement Customer"}).json()
    product = client.post("/v1/erp/products", headers=h, json={
        "sku": "SETTLE-001", "name": "Cucumber", "unit": "kg", "salePrice": 100, "purchasePrice": 50
    }).json()
    stock = client.post("/v1/erp/inventory/movements", headers=h, json={
        "productId": product["id"], "warehouseId": "main", "movementType": "RECEIPT", "quantity": 10
    })
    assert stock.status_code == 200, stock.text
    order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 5, "unitPrice": 100}]
    })
    assert order.status_code == 200, order.text
    for action, key in [("CONFIRM", "confirm-order-0001"), ("DELIVER", "deliver-order-0001")]:
        result = client.post(f"/v1/erp/orders/{order.json()['id']}/transition", headers=h,
                             json={"action": action, "idempotencyKey": key})
        assert result.status_code == 200, result.text
    return h, order.json()["id"]


def test_customer_partial_settlement_is_idempotent_and_cannot_overpay():
    h, order_id = setup_delivered_sales_order()
    settlement = {"idempotencyKey": "customer-pay-0001", "orderId": order_id,
                  "amount": 200, "method": "BANK", "reference": "BANK-REF-1"}
    first = client.post("/v1/erp/settlements", headers=h, json=settlement)
    assert first.status_code == 200, first.text
    assert first.json()["outstanding"] == 300
    duplicate = client.post("/v1/erp/settlements", headers=h, json=settlement)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "DUPLICATE"
    overpay = {**settlement, "idempotencyKey": "customer-pay-0002", "amount": 301}
    assert client.post("/v1/erp/settlements", headers=h, json=overpay).status_code == 409
    trial = client.get("/v1/erp/accounting/trial-balance", headers=h).json()
    assert abs(trial["totalDebit"] - trial["totalCredit"]) < 0.001


def test_settlement_idempotency_key_cannot_be_reused_for_different_payload():
    h, order_id = setup_delivered_sales_order()
    first = {"idempotencyKey": "same-settlement-key-001", "orderId": order_id,
             "amount": 100, "method": "BANK", "reference": "REF-A"}
    created = client.post("/v1/erp/settlements", headers=h, json=first)
    assert created.status_code == 200, created.text
    changed = {**first, "amount": 150, "reference": "REF-B"}
    replay = client.post("/v1/erp/settlements", headers=h, json=changed)
    assert replay.status_code == 409, replay.text


def test_concurrent_settlements_cannot_overpay_order():
    h, order_id = setup_delivered_sales_order()
    def pay(key):
        return client.post("/v1/erp/settlements", headers=h, json={
            "idempotencyKey": key, "orderId": order_id, "amount": 300,
            "method": "BANK", "reference": key
        })
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(pay, ["concurrent-pay-0001", "concurrent-pay-0002"]))
    assert sorted(response.status_code for response in results) == [200, 409]
    listed = client.get("/v1/erp/settlements", headers=h, params={"orderId": order_id})
    assert listed.status_code == 200
    assert sum(float(item["amount"]) for item in listed.json()["items"]) == 300
