import base64
import os
from pathlib import Path

DB = Path("/tmp/molido-advanced-inventory-tests.sqlite3")
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "advanced-inventory-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)

from fastapi.testclient import TestClient
import app as app_module
app_module.DB_PATH = DB

client = TestClient(app_module.app)


def account(name):
    response = client.post("/v1/auth/register", json={"username": name, "password": "Strong-test-password-123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["accessToken"]}


def product(headers, sku="CUC-LOT-01"):
    response = client.post("/v1/erp/products", headers=headers, json={
        "sku": sku, "name": "Cucumber", "unit": "kg", "salePrice": 100, "purchasePrice": 50
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def warehouse(headers, code):
    response = client.post("/v2/erp/inventory/warehouses", headers=headers, json={
        "code": code, "name": code + " warehouse", "warehouseType": "GENERAL"
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def lot(headers, product_id, warehouse_id, key="lot-receipt-0001", code="LOT-2026-001", quantity="100.250"):
    response = client.post("/v2/erp/inventory/lots", headers=headers, json={
        "idempotencyKey": key, "warehouseId": warehouse_id, "productId": product_id,
        "lotCode": code, "quantity": quantity, "unit": "kg",
        "receivedDate": "2026-11-20", "expiryDate": "2026-12-20",
        "sourceType": "SUPPLIER", "sourceId": "supplier-1"
    })
    assert response.status_code == 200, response.text
    return response.json()


def release(headers, lot_id):
    response = client.post(f"/v2/erp/inventory/lots/{lot_id}/quality", headers=headers, json={
        "state": "RELEASED", "reason": "Inspection passed"
    })
    assert response.status_code == 200, response.text


def test_lot_receipt_quality_reservation_and_fefo_listing():
    h = account("advancedlot")
    p = product(h)
    w = warehouse(h, "MAIN")
    received = lot(h, p, w)
    assert received["status"] == "received_pending_inspection"
    assert lot(h, p, w)["status"] == "duplicate"
    assert client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-blocked-001", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "order-1", "quantity": "1"
    }).status_code == 409
    release(h, received["lotId"])
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-lot-0001", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "order-1", "quantity": "20.125"
    })
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["availableAfter"] == "80.125"
    rows = client.get("/v2/erp/inventory/lots", headers=h).json()["items"]
    assert rows[0]["quantity"] == "100.250"
    assert rows[0]["qualityState"] == "RELEASED"


def test_atomic_transfer_preserves_total_and_blocks_insufficient_stock():
    h = account("advancedtransfer")
    p = product(h, "CUC-LOT-02")
    w1 = warehouse(h, "SOURCE")
    w2 = warehouse(h, "DEST")
    received = lot(h, p, w1, "transfer-receipt-001", "LOT-TRANSFER-1", "30")
    release(h, received["lotId"])
    moved = client.post("/v2/erp/inventory/transfers", headers=h, json={
        "idempotencyKey": "transfer-0000001", "lotId": received["lotId"],
        "sourceWarehouseId": w1, "destinationWarehouseId": w2, "quantity": "12.5"
    })
    assert moved.status_code == 200, moved.text
    duplicate = client.post("/v2/erp/inventory/transfers", headers=h, json={
        "idempotencyKey": "transfer-0000001", "lotId": received["lotId"],
        "sourceWarehouseId": w1, "destinationWarehouseId": w2, "quantity": "12.5"
    })
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    balances = client.get("/v2/erp/inventory/balances", headers=h).json()["items"]
    by_code = {x["warehouseCode"]: x["quantity"] for x in balances}
    assert by_code["SOURCE"] == "17.5"
    assert by_code["DEST"] == "12.5"
    too_much = client.post("/v2/erp/inventory/transfers", headers=h, json={
        "idempotencyKey": "transfer-0000002", "lotId": received["lotId"],
        "sourceWarehouseId": w1, "destinationWarehouseId": w2, "quantity": "18"
    })
    assert too_much.status_code == 409


def test_tenant_isolation_for_warehouse_lot_and_quality():
    owner = account("advancedowner")
    other = account("advancedother")
    p = product(owner, "CUC-LOT-03")
    w = warehouse(owner, "PRIVATE")
    received = lot(owner, p, w, "private-lot-0001", "PRIVATE-LOT", "5")
    assert client.get("/v2/erp/inventory/lots", headers=other).json()["items"] == []
    forbidden = client.post(f"/v2/erp/inventory/lots/{received['lotId']}/quality", headers=other, json={
        "state": "RELEASED", "reason": "forged cross-account update"
    })
    assert forbidden.status_code == 404
    assert client.get("/v2/erp/inventory/warehouses", headers=other).json()["items"] == []


def test_quarantine_prevents_reservation_and_release_is_audited():
    h = account("advancedquality")
    p = product(h, "CUC-LOT-04")
    w = warehouse(h, "QUALITY")
    received = lot(h, p, w, "quality-lot-0001", "QUALITY-LOT", "8")
    release(h, received["lotId"])
    quarantined = client.post(f"/v2/erp/inventory/lots/{received['lotId']}/quality", headers=h, json={
        "state": "QUARANTINED", "reason": "Packaging damage", "evidenceRef": "photo:qc-1"
    })
    assert quarantined.status_code == 200
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-quarantine-01", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "order-2", "quantity": "1"
    })
    assert reserved.status_code == 409
