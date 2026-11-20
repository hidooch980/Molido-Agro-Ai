import base64
import os
from pathlib import Path

DB = Path("/tmp/molido-settlement-tests.sqlite3")
os.environ["MOLIDO_JWT_SECRET"] = "settlement-tests-secret-with-more-than-32-chars"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_customer_partial_settlement_is_idempotent_and_cannot_overpay():
    auth = client.post("/v1/auth/register", json={
        "username": "settlementUser", "password": "Strong-test-password-123"
    })
    h = {"Authorization": "Bearer " + auth.json()["accessToken"]}
    customer = client.post("/v1/crm/customers", headers=h, json={"name": "Buyer"}).json()
    product = client.post("/v1/erp/products", headers=h, json={
        "sku": "SET-01", "name": "Pepper", "unit": "kg", "salePrice": 100, "purchasePrice": 50
    }).json()
    stock = client.post("/v1/erp/inventory/movements", headers=h, json={
        "idempotencyKey": "settlement-stock-01", "productId": product["id"],
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 10
    })
    assert stock.status_code == 200
    order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId": customer["id"],
        "lines": [{"productId": product["id"], "quantity": 5, "unitPrice": 100}]
    }).json()
    for action, key in [("CONFIRM", "settlement-confirm-01"), ("SHIP", "settlement-ship-01"), ("DELIVER", "settlement-deliver-01")]:
        result = client.post(f"/v1/erp/orders/{order['id']}/transition", headers=h,
                             json={"action": action, "idempotencyKey": key})
        assert result.status_code == 200, result.text

    settlement = {"idempotencyKey": "customer-pay-0001", "orderId": order["id"],
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
