"""Offline sync -> CRM/ERP bridge: pushed customer, supplier and product records
must be visible to the CRM/ERP read APIs without breaking the sync contract."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("MOLIDO_JWT_SECRET", "sync-bridge-test-secret-minimum-32-chars")
os.environ.setdefault("MOLIDO_DATA_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY")
os.environ.setdefault("MOLIDO_DB_PATH", str(Path(tempfile.gettempdir()) / "molido-sync-bridge-tests.sqlite3"))

from fastapi.testclient import TestClient

import app

PASSWORD = "Strong-test-password-123"


def make_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "bridge.sqlite3")
    app.init_db()
    return TestClient(app.app)


def account(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/v1/auth/register", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def push(client, headers, key, entity_type, entity_id, payload, operation="CREATE", base_version=0):
    response = client.post("/v1/sync/push", headers=headers, json={"operations": [{
        "idempotencyKey": key,
        "entityType": entity_type,
        "entityId": entity_id,
        "operation": operation,
        "payload": payload,
        "baseVersion": base_version,
    }]})
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def test_customer_and_supplier_reach_the_crm(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = account(client, "bridge_parties")

    assert push(client, headers, "op-customer-1", "customer", "cust-1",
                {"name": "مشتری نمونه", "phone": "09120000000"})["status"] == "applied"
    assert push(client, headers, "op-supplier-1", "supplier", "sup-1",
                {"name": "تأمین‌کننده نمونه", "phone": "09121111111"})["status"] == "applied"

    customers = client.get("/v1/crm/customers", headers=headers).json()["items"]
    assert [(item["id"], item["name"]) for item in customers] == [("cust-1", "مشتری نمونه")]
    suppliers = client.get("/v1/erp/suppliers", headers=headers).json()["items"]
    assert [(item["id"], item["name"]) for item in suppliers] == [("sup-1", "تأمین‌کننده نمونه")]


def test_product_mirrors_its_sku_into_the_erp(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = account(client, "bridge_products")

    push(client, headers, "op-product-1", "product", "prod-1",
         {"sku": "CUC-500", "name": "خیار گلخانه‌ای", "unit": "kg", "salePrice": 120000})

    products = client.get("/v1/erp/products", headers=headers).json()["items"]
    assert len(products) == 1
    assert products[0]["id"] == "prod-1"
    assert products[0]["sku"] == "CUC-500"
    assert products[0]["name"] == "خیار گلخانه‌ای"


def test_a_later_update_replaces_the_mirror_instead_of_duplicating_it(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = account(client, "bridge_updates")

    push(client, headers, "op-update-1", "customer", "cust-upd", {"name": "نام اول"})
    push(client, headers, "op-update-2", "customer", "cust-upd", {"name": "نام دوم"}, operation="UPDATE", base_version=1)

    customers = client.get("/v1/crm/customers", headers=headers).json()["items"]
    assert [(item["id"], item["name"]) for item in customers] == [("cust-upd", "نام دوم")]


def test_a_deleted_record_is_removed_from_the_crm(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = account(client, "bridge_deletes")

    push(client, headers, "op-delete-1", "supplier", "sup-del", {"name": "حذف شدنی"})
    push(client, headers, "op-delete-2", "supplier", "sup-del", {}, operation="DELETE", base_version=1)

    assert client.get("/v1/erp/suppliers", headers=headers).json()["items"] == []
    # The tombstone still exists in the generic record store for other devices.
    changes = client.post("/v1/sync/pull", headers=headers, json={"cursor": 0}).json()["changes"]
    assert [change["deleted"] for change in changes if change["entityId"] == "sup-del"] == [0, 1]


def test_the_bridge_is_account_isolated(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    owner = account(client, "bridge_owner")
    other = account(client, "bridge_other")

    push(client, owner, "op-isolation-1", "customer", "cust-owner", {"name": "مالک"})

    assert client.get("/v1/crm/customers", headers=other).json()["items"] == []


def test_a_duplicate_sku_never_breaks_the_sync_push(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    headers = account(client, "bridge_duplicates")

    push(client, headers, "op-dup-1", "product", "prod-dup-1", {"sku": "SAME", "name": "اول", "unit": "kg"})
    second = push(client, headers, "op-dup-2", "product", "prod-dup-2", {"sku": "SAME", "name": "دوم", "unit": "kg"})
    assert second["status"] == "applied"

    products = client.get("/v1/erp/products", headers=headers).json()["items"]
    assert [item["sku"] for item in products] == ["SAME"]
    # Both records remain durable in the generic store even though one could not be mirrored.
    records = client.post("/v1/sync/pull", headers=headers, json={"cursor": 0}).json()["changes"]
    assert {change["entityId"] for change in records} == {"prod-dup-1", "prod-dup-2"}
