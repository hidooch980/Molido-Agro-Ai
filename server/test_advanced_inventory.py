import base64
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

DB = Path(tempfile.gettempdir()) / "molido-advanced-inventory-tests.sqlite3"
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "advanced-inventory-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)
os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"] = "inventory-approval-token-for-ci-minimum-32"
os.environ["MOLIDO_COST_APPROVAL_TOKEN"] = "cost-approval-token-for-ci-minimum-32"
os.environ["MOLIDO_LEDGER_APPROVAL_TOKEN"] = "ledger-approval-token-for-ci-minimum-32"

from fastapi.testclient import TestClient
import app as app_module

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
    response = client.post(f"/v2/erp/inventory/lots/{lot_id}/quality",
        headers={**headers, "X-Approval-Token": os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]},
        json={"state": "RELEASED", "reason": "Inspection passed"})
    assert response.status_code == 200, response.text


def test_registered_api_routes_have_no_method_path_collisions():
    seen = {}
    duplicates = []
    for route in app_module.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        for method in methods:
            key = (method, path)
            if key in seen:
                duplicates.append((key, seen[key], route.endpoint.__name__))
            else:
                seen[key] = route.endpoint.__name__
    assert duplicates == []


def test_fefo_reservation_endpoints_are_distinct_and_registered_once():
    expected = {
        "/v2/erp/inventory/fefo/reservations": "reserve_fefo",
        "/v2/erp/inventory/fefo/allocate": "allocate_fefo",
    }
    for path, endpoint_name in expected.items():
        matching = [
            route for route in app_module.app.routes
            if getattr(route, "path", None) == path
            and "POST" in getattr(route, "methods", set())
        ]
        assert len(matching) == 1
        assert matching[0].endpoint.__name__ == endpoint_name


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
    quarantined = client.post(f"/v2/erp/inventory/lots/{received['lotId']}/quality",
        headers={**h, "X-Approval-Token": os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]},
        json={"state": "QUARANTINED", "reason": "Packaging damage", "evidenceRef": "photo:qc-1"})
    assert quarantined.status_code == 200
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-quarantine-01", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "order-2", "quantity": "1"
    })
    assert reserved.status_code == 409


def test_reservation_release_and_fulfillment_are_idempotent_and_preserve_stock():
    h = account("reservationactions")
    p = product(h, "CUC-RES-ACT")
    w = warehouse(h, "RES-ACT")
    received = lot(h, p, w, key="lot-res-action-01", code="LOT-RES-ACT", quantity="20")
    release(h, received["lotId"])
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-res-action-01", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "SO-RES-1", "quantity": "7"
    })
    assert reserved.status_code == 200, reserved.text
    rid = reserved.json()["reservationId"]
    blocked_transfer = client.post("/v2/erp/inventory/transfers", headers=h, json={
        "idempotencyKey": "transfer-reserved-01", "lotId": received["lotId"],
        "sourceWarehouseId": w, "destinationWarehouseId": warehouse(h, "RES-DEST"), "quantity": "14"
    })
    assert blocked_transfer.status_code == 409
    fulfilled = client.post(f"/v2/erp/inventory/reservations/{rid}/actions", headers=h, json={
        "idempotencyKey": "fulfill-res-action-01", "action": "FULFILL"
    })
    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["status"] == "fulfilled"
    duplicate = client.post(f"/v2/erp/inventory/reservations/{rid}/actions", headers=h, json={
        "idempotencyKey": "fulfill-res-action-01", "action": "FULFILL"
    })
    assert duplicate.status_code == 200 and duplicate.json() == fulfilled.json()
    balances = client.get("/v2/erp/inventory/balances", headers=h).json()["items"]
    row = next(x for x in balances if x["lotId"] == received["lotId"])
    assert row["quantity"] == "13"


def test_reservation_release_restores_available_quantity_without_moving_stock():
    h = account("reservationrelease")
    p = product(h, "CUC-RES-REL")
    w = warehouse(h, "RES-REL")
    received = lot(h, p, w, key="lot-res-release-01", code="LOT-RES-REL", quantity="9")
    release(h, received["lotId"])
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-res-release-01", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "SO-RES-2", "quantity": "5"
    })
    rid = reserved.json()["reservationId"]
    released = client.post(f"/v2/erp/inventory/reservations/{rid}/actions", headers=h, json={
        "idempotencyKey": "release-res-action-01", "action": "RELEASE"
    })
    assert released.status_code == 200 and released.json()["status"] == "released"
    duplicate = client.post(f"/v2/erp/inventory/reservations/{rid}/actions", headers=h, json={
        "idempotencyKey": "release-res-action-01", "action": "RELEASE"
    })
    assert duplicate.status_code == 200 and duplicate.json() == released.json()
    reserve_again = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "reserve-res-release-02", "lotId": received["lotId"], "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "SO-RES-3", "quantity": "9"
    })
    assert reserve_again.status_code == 200, reserve_again.text


def test_lot_trace_returns_full_history_and_is_account_scoped():
    owner = account("lottraceowner")
    other = account("lottraceother")
    p = product(owner, "CUC-TRACE-01")
    w = warehouse(owner, "TRACE-MAIN")
    received = lot(owner, p, w, "trace-receipt-001", "LOT-TRACE-001", "18")
    lot_id = received["lotId"]
    release(owner, lot_id)
    reserved = client.post("/v2/erp/inventory/reservations", headers=owner, json={
        "idempotencyKey": "trace-reserve-001", "lotId": lot_id, "warehouseId": w,
        "referenceType": "SALES_ORDER", "referenceId": "SO-TRACE-1", "quantity": "4"
    })
    assert reserved.status_code == 200, reserved.text
    trace = client.get(f"/v2/erp/inventory/lots/{lot_id}/trace", headers=owner)
    assert trace.status_code == 200, trace.text
    data = trace.json()
    assert data["lot"]["lotCode"] == "LOT-TRACE-001"
    assert [x["type"] for x in data["movements"]] == ["RECEIPT"]
    assert data["reservations"][0]["referenceId"] == "SO-TRACE-1"
    assert data["qualityHistory"][0]["to"] == "RELEASED"
    assert data["balances"][0]["quantity"] == "18"
    assert client.get(f"/v2/erp/inventory/lots/{lot_id}/trace", headers=other).status_code == 404



def test_fefo_reserves_earliest_expiry_across_multiple_lots_and_is_idempotent():
    h = account("fefoalloc")
    p = product(h, "CUC-FEFO-01")
    w = warehouse(h, "FEFO")
    def receive(code, expiry, quantity):
        response = client.post("/v2/erp/inventory/lots", headers=h, json={
            "idempotencyKey": "fefo-receipt-" + code, "warehouseId": w, "productId": p,
            "lotCode": code, "quantity": quantity, "unit": "kg",
            "receivedDate": "2026-11-20", "expiryDate": expiry, "sourceType": "SUPPLIER"
        })
        assert response.status_code == 200, response.text
        release(h, response.json()["lotId"])
        return response.json()["lotId"]
    later = receive("FEFO-LATE", "2027-02-01", "8")
    earlier = receive("FEFO-EARLY", "2026-12-01", "5")
    body = {"idempotencyKey":"fefo-order-0001","productId":p,"warehouseId":w,
            "quantity":"10","referenceType":"SALES_ORDER","referenceId":"SO-FEFO-1"}
    reserved = client.post("/v2/erp/inventory/fefo/reservations", headers=h, json=body)
    assert reserved.status_code == 200, reserved.text
    allocations = reserved.json()["allocations"]
    assert allocations[0]["lotId"] == earlier and allocations[0]["quantity"] == "5"
    assert allocations[1]["lotId"] == later and allocations[1]["quantity"] == "5"
    duplicate = client.post("/v2/erp/inventory/fefo/reservations", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"


def test_fefo_reservation_replay_binds_payload_and_returns_all_lot_allocations():
    h = account("feforeservationkey")
    p = product(h,"CUC-FEFO-RES-KEY")
    w = warehouse(h,"FEFO-RES-KEY")
    def receive(code, expiry, quantity):
        response = client.post("/v2/erp/inventory/lots",headers=h,json={
            "idempotencyKey":"fefo-res-key-"+code,"warehouseId":w,"productId":p,
            "lotCode":code,"quantity":quantity,"unit":"kg",
            "receivedDate":"2026-11-20","expiryDate":expiry,"sourceType":"SUPPLIER"
        })
        assert response.status_code == 200, response.text
        release(h,response.json()["lotId"])
    receive("FEFO-RES-LATE","2027-02-01","8")
    receive("FEFO-RES-EARLY","2026-12-01","5")
    body = {"idempotencyKey":"fefo-reservation-key-01","productId":p,"warehouseId":w,
            "quantity":"10","referenceType":"SALES_ORDER","referenceId":"SO-FEFO-KEY"}
    first = client.post("/v2/erp/inventory/fefo/reservations",headers=h,json=body)
    assert first.status_code == 200, first.text
    assert len(first.json()["allocations"]) == 2
    duplicate = client.post("/v2/erp/inventory/fefo/reservations",headers=h,json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["allocations"] == first.json()["allocations"]
    changed = client.post("/v2/erp/inventory/fefo/reservations",headers=h,json={**body,"quantity":"11"})
    assert changed.status_code == 409, changed.text
    balances = client.get("/v2/erp/inventory/balances",headers=h).json()["items"]
    assert sum(Decimal(row["quantity"]) for row in balances) == Decimal("13")


def test_customer_and_supplier_returns_require_approval_and_keep_ledger_history():
    h = account("returnflows")
    p = product(h, "CUC-RETURN-01")
    w = warehouse(h, "RETURNS")
    received = lot(h, p, w, "return-base-lot-01", "RETURN-BASE", "20")
    release(h, received["lotId"])
    customer_account = client.post("/v1/crm/customers",headers=h,json={"name":"Return Customer"})
    sales_order = client.post("/v1/erp/sales/orders",headers=h,json={
        "partyId":customer_account.json()["id"],
        "lines":[{"productId":p,"quantity":10,"unitPrice":100}]
    })
    assert sales_order.status_code == 200, sales_order.text
    reserved_order = client.post(
        f"/v2/erp/inventory/orders/{sales_order.json()['id']}/fefo-reservations",
        headers=h,json={"idempotencyKey":"return-order-reserve-01","warehouseId":w})
    assert reserved_order.status_code == 200, reserved_order.text
    confirmed_order = client.post(
        f"/v1/erp/orders/{sales_order.json()['id']}/transition",headers=h,
        json={"action":"CONFIRM","idempotencyKey":"return-order-confirm-01"})
    assert confirmed_order.status_code == 200, confirmed_order.text
    shipped_order = client.post(
        f"/v2/erp/inventory/orders/{sales_order.json()['id']}/fulfill",headers=h,
        json={"idempotencyKey":"return-order-ship-01"})
    assert shipped_order.status_code == 200, shipped_order.text
    customer = client.post("/v2/erp/inventory/returns", headers=h, json={
        "idempotencyKey":"customer-return-001","direction":"CUSTOMER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"3",
        "referenceId":sales_order.json()["id"],"reason":"Customer returned damaged packaging",
        "accountingAmount":"300","currency":"IRR"
    })
    assert customer.status_code == 200 and customer.json()["status"] == "pending_approval"
    fake_reference = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"customer-return-fake-001","direction":"CUSTOMER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"1",
        "referenceId":"SO-NOT-SHIPPED","reason":"Unverified customer return"
    })
    assert fake_reference.status_code == 409
    over_return = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"customer-return-over-001","direction":"CUSTOMER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"8",
        "referenceId":sales_order.json()["id"],"reason":"Excess customer return"
    })
    assert over_return.status_code == 409
    approval_headers = {**h, "X-Approval-Token":os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]}
    approved_customer = client.post(
        f"/v2/erp/inventory/returns/{customer.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-customer-return-001"})
    assert approved_customer.status_code == 200, approved_customer.text
    assert approved_customer.json()["accountingStatus"] == "PENDING_LEDGER_APPROVAL"
    customer_journal = client.post(
        f"/v1/erp/ledger/journals/{approved_customer.json()['journalId']}/approve",
        headers={**h,"X-Approval-Token":os.environ["MOLIDO_LEDGER_APPROVAL_TOKEN"]})
    assert customer_journal.status_code == 200 and customer_journal.json()["status"] == "POSTED"
    returned_lot = client.get(f"/v2/erp/inventory/lots/{approved_customer.json()['lotId']}/trace",
                              headers=h).json()["lot"]
    assert returned_lot["qualityState"] == "PENDING_INSPECTION"
    wrong_supplier_reference = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"supplier-return-wrong-source-001","direction":"SUPPLIER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"1",
        "referenceId":"PO-UNRELATED-1","reason":"Wrong supplier source"
    })
    assert wrong_supplier_reference.status_code == 409
    supplier = client.post("/v2/erp/inventory/returns", headers=h, json={
        "idempotencyKey":"supplier-return-001","direction":"SUPPLIER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"4",
        "referenceId":"supplier-1","reason":"Supplier quality claim",
        "accountingAmount":"200","currency":"IRR"
    })
    assert supplier.status_code == 200
    cross_return_replay = client.post(
        f"/v2/erp/inventory/returns/{supplier.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-customer-return-001"})
    assert cross_return_replay.status_code == 409
    approved_supplier = client.post(
        f"/v2/erp/inventory/returns/{supplier.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-supplier-return-001"})
    assert approved_supplier.status_code == 200, approved_supplier.text
    assert approved_supplier.json()["accountingStatus"] == "PENDING_LEDGER_APPROVAL"
    supplier_journal = client.post(
        f"/v1/erp/ledger/journals/{approved_supplier.json()['journalId']}/approve",
        headers={**h,"X-Approval-Token":os.environ["MOLIDO_LEDGER_APPROVAL_TOKEN"]})
    assert supplier_journal.status_code == 200 and supplier_journal.json()["status"] == "POSTED"
    trace = client.get(f"/v2/erp/inventory/lots/{received['lotId']}/trace", headers=h).json()
    assert [x["type"] for x in trace["movements"]][-1] == "SUPPLIER_RETURN"
    assert Decimal(trace["balances"][0]["quantity"]) == Decimal("6")


def test_supplier_return_rejects_greenhouse_sourced_lots():
    h = account("supplierreturnsource")
    p = product(h,"CUC-SUPPLIER-RETURN-SOURCE")
    w = warehouse(h,"SUPPLIER-RETURN-SOURCE")
    received = client.post("/v2/erp/inventory/lots",headers=h,json={
        "idempotencyKey":"greenhouse-source-lot-001","warehouseId":w,"productId":p,
        "lotCode":"GREENHOUSE-SOURCE-LOT","quantity":"10","unit":"kg",
        "receivedDate":"2026-11-21","sourceType":"GREENHOUSE","sourceId":"harvest-source-001"
    })
    assert received.status_code == 200, received.text
    rejected = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"supplier-return-wrong-source-001","direction":"SUPPLIER_RETURN",
        "lotId":received.json()["lotId"],"warehouseId":w,"quantity":"1",
        "referenceId":"PO-UNRELATED-001","reason":"Attempt to return greenhouse harvest"
    })
    assert rejected.status_code == 409, rejected.text


def test_scrap_and_cycle_count_are_approval_gated_and_idempotent():
    h = account("scrapcount")
    p = product(h, "CUC-SCRAP-COUNT")
    w = warehouse(h, "SCRAPCOUNT")
    received = lot(h, p, w, "scrap-count-lot-01", "SCRAP-COUNT-LOT", "10")
    release(h, received["lotId"])
    gh,cycle="gh-scrap-001","cycle-scrap-001"
    sync=client.post("/v1/sync/push",headers=h,json={"operations":[
        {"idempotencyKey":"gh-scrap-create-001","entityType":"greenhouse","entityId":gh,
         "operation":"CREATE","payload":{"name":"Waste Cost Greenhouse"},"baseVersion":0},
        {"idempotencyKey":"cycle-scrap-create-001","entityType":"crop_cycle","entityId":cycle,
         "operation":"CREATE","payload":{"greenhouseId":gh,"cropCode":"CUCUMBER"},"baseVersion":0}
    ]})
    assert sync.status_code == 200, sync.text
    scrap = client.post("/v2/erp/inventory/scrap", headers=h, json={
        "idempotencyKey":"scrap-doc-0001","lotId":received["lotId"],"warehouseId":w,
        "quantity":"2","reasonCode":"DAMAGED","reason":"Damaged produce",
        "sourceReference":"QC-REPORT-1","greenhouseId":gh,"cropCycleId":cycle,
        "unitCost":"5","currency":"IRR"
    })
    assert scrap.status_code == 200 and scrap.json()["status"] == "pending_approval"
    approval_headers = {**h, "X-Approval-Token":os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]}
    posted_scrap = client.post(
        f"/v2/erp/inventory/scrap/{scrap.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-scrap-0001"})
    assert posted_scrap.status_code == 200, posted_scrap.text
    wrong_replay = client.post(
        f"/v2/erp/inventory/scrap/{scrap.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-scrap-0001"})
    assert wrong_replay.status_code == 200 and wrong_replay.json() == posted_scrap.json()
    count = client.post("/v2/erp/inventory/cycle-counts", headers=h, json={
        "idempotencyKey":"cycle-count-0001","warehouseId":w,"reason":"Weekly physical count",
        "lines":[{"lotId":received["lotId"],"countedQuantity":"7"}]
    })
    assert count.status_code == 200 and count.json()["variances"][0]["variance"] == "-1"
    cross_document_replay = client.post(
        f"/v2/erp/inventory/cycle-counts/{count.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-scrap-0001"})
    assert cross_document_replay.status_code == 409
    posted_count = client.post(
        f"/v2/erp/inventory/cycle-counts/{count.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-count-0001"})
    assert posted_count.status_code == 200, posted_count.text
    balance_row = next(x for x in client.get("/v2/erp/inventory/balances",headers=h).json()["items"]
                       if x["lotId"] == received["lotId"])
    assert balance_row["quantity"] == "7"



def test_sales_order_fefo_fulfillment_posts_lot_movements_against_order():
    h = account("salesorderfefo")
    customer = client.post("/v1/crm/customers", headers=h, json={"name":"FEFO Customer"})
    p = product(h, "CUC-SALES-FEFO")
    w = warehouse(h, "SALES-FEFO")
    order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId":customer.json()["id"],"lines":[{"productId":p,"quantity":2,"unitPrice":100},{"productId":p,"quantity":3,"unitPrice":100}]
    })
    assert order.status_code == 200, order.text
    received = lot(h,p,w,"sales-fefo-lot-001","SALES-FEFO-LOT","5")
    release(h,received["lotId"])
    reserve_body = {"idempotencyKey":"order-fefo-reserve-001","warehouseId":w}
    reserved = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fefo-reservations",
                           headers=h,json=reserve_body)
    assert reserved.status_code == 200, reserved.text
    replay = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fefo-reservations",
                         headers=h,json=reserve_body)
    assert replay.status_code == 200 and replay.json()["status"] == "duplicate"
    assert replay.json()["allocations"] == reserved.json()["allocations"]
    second_reservation = client.post(
        f"/v2/erp/inventory/orders/{order.json()['id']}/fefo-reservations",
        headers=h,json={"idempotencyKey":"order-fefo-reserve-002","warehouseId":w})
    assert second_reservation.status_code == 409, second_reservation.text
    confirmed = client.post(f"/v1/erp/orders/{order.json()['id']}/transition", headers=h,
                            json={"action":"CONFIRM","idempotencyKey":"confirm-sales-fefo-001"})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "CONFIRMED"
    shipped = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fulfill",
                          headers=h,json={"idempotencyKey":"order-fefo-ship-001"})
    assert shipped.status_code == 200, shipped.text
    assert shipped.json()["status"] == "shipped"
    trace = client.get(f"/v2/erp/inventory/lots/{received['lotId']}/trace",headers=h).json()
    assert any(x["type"] == "SHIPMENT_ISSUE" and x["referenceId"] == order.json()["id"]
               for x in trace["movements"])
    order_state = next(x for x in client.get("/v1/erp/orders",headers=h).json()["items"]
                       if x["id"] == order.json()["id"])
    assert order_state["status"] == "SHIPPED"


def test_purchase_order_receipt_creates_inspection_lots_and_links_supplier_order():
    h = account("purchaseorderlot")
    supplier = client.post("/v1/erp/suppliers",headers=h,json={"name":"FEFO Supplier"})
    p = product(h,"CUC-PURCHASE-LOT")
    w = warehouse(h,"PURCHASE-LOT")
    order = client.post("/v1/erp/purchase/orders",headers=h,json={
        "partyId":supplier.json()["id"],"lines":[{"productId":p,"quantity":12,"unitPrice":50}]
    })
    assert order.status_code == 200, order.text
    confirmed = client.post(f"/v1/erp/orders/{order.json()['id']}/transition",headers=h,
                            json={"action":"CONFIRM","idempotencyKey":"confirm-purchase-lot-001"})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "CONFIRMED"
    receipt = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/purchase-receipts",
                          headers=h,json={"idempotencyKey":"purchase-receipt-001","warehouseId":w,
                          "lines":[{"productId":p,"lotCode":"PO-LOT-001","quantity":"12",
                                    "unit":"kg","receivedDate":"2026-11-21","expiryDate":"2027-01-01"}]})
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["receipts"][0]["qualityState"] == "PENDING_INSPECTION"
    wrong_supplier_return = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"purchase-lot-wrong-po-return-01","direction":"SUPPLIER_RETURN",
        "lotId":receipt.json()["receipts"][0]["lotId"],"warehouseId":w,"quantity":"1",
        "referenceId":"PO-WRONG-REFERENCE","reason":"Wrong purchase order reference"
    })
    assert wrong_supplier_return.status_code == 409, wrong_supplier_return.text
    correct_supplier_return = client.post("/v2/erp/inventory/returns",headers=h,json={
        "idempotencyKey":"purchase-lot-correct-po-return-01","direction":"SUPPLIER_RETURN",
        "lotId":receipt.json()["receipts"][0]["lotId"],"warehouseId":w,"quantity":"1",
        "referenceId":order.json()["id"],"reason":"Return to original supplier order"
    })
    assert correct_supplier_return.status_code == 200, correct_supplier_return.text
    order_state = next(x for x in client.get("/v1/erp/orders",headers=h).json()["items"]
                       if x["id"] == order.json()["id"])
    assert order_state["status"] == "RECEIVED"



def test_purchase_receipt_idempotency_rejects_changed_request():
    h = account("purchaseidempotency")
    supplier = client.post("/v1/erp/suppliers",headers=h,json={"name":"Idempotency Supplier"})
    p = product(h,"CUC-PURCHASE-IDEM")
    w = warehouse(h,"PURCHASE-IDEM")
    order = client.post("/v1/erp/purchase/orders",headers=h,json={
        "partyId":supplier.json()["id"],"lines":[{"productId":p,"quantity":12,"unitPrice":50}]
    })
    assert order.status_code == 200, order.text
    confirmed = client.post(f"/v1/erp/orders/{order.json()['id']}/transition",headers=h,
                            json={"action":"CONFIRM","idempotencyKey":"confirm-purchase-idem-01"})
    assert confirmed.status_code == 200, confirmed.text
    body = {"idempotencyKey":"purchase-receipt-idem-01","warehouseId":w,
            "lines":[{"productId":p,"lotCode":"PO-IDEM-001","quantity":"12",
                      "unit":"kg","receivedDate":"2026-11-21","expiryDate":"2027-01-01"}]}
    first = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/purchase-receipts",headers=h,json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/purchase-receipts",headers=h,json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    changed = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/purchase-receipts",
        headers=h,json={**body,"lines":[{**body["lines"][0],"lotCode":"PO-IDEM-CHANGED"}]})
    assert changed.status_code == 409, changed.text
    foreign_order = client.post("/v1/erp/purchase/orders",headers=h,json={
        "partyId":supplier.json()["id"],"lines":[{"productId":p,"quantity":12,"unitPrice":50}]
    })
    assert foreign_order.status_code == 200
    conflict = client.post(f"/v2/erp/inventory/orders/{foreign_order.json()['id']}/purchase-receipts",
                           headers=h,json=body)
    assert conflict.status_code == 409, conflict.text
    duplicate_lot_order = client.post("/v1/erp/purchase/orders",headers=h,json={
        "partyId":supplier.json()["id"],"lines":[{"productId":p,"quantity":12,"unitPrice":50}]
    })
    assert duplicate_lot_order.status_code == 200, duplicate_lot_order.text
    duplicate_lot_confirmed = client.post(
        f"/v1/erp/orders/{duplicate_lot_order.json()['id']}/transition",headers=h,
        json={"action":"CONFIRM","idempotencyKey":"confirm-duplicate-lot-order-01"})
    assert duplicate_lot_confirmed.status_code == 200, duplicate_lot_confirmed.text
    duplicate_lot_receipt = client.post(
        f"/v2/erp/inventory/orders/{duplicate_lot_order.json()['id']}/purchase-receipts",headers=h,
        json={"idempotencyKey":"purchase-duplicate-lot-01","warehouseId":w,
              "lines":[{"productId":p,"lotCode":"PO-IDEM-001","quantity":"12",
                        "unit":"kg","receivedDate":"2026-11-21","expiryDate":"2027-01-01"}]})
    assert duplicate_lot_receipt.status_code == 409, duplicate_lot_receipt.text
    balances = client.get("/v2/erp/inventory/balances",headers=h).json()["items"]
    assert sum(Decimal(row["quantity"]) for row in balances) == Decimal("12")


def test_harvest_receipt_idempotency_rejects_changed_harvest_or_destination():
    h = account("harvestidempotency")
    gh = "gh-harvest-idem-01"
    cycle = "cycle-harvest-idem-01"
    sync = client.post("/v1/sync/push",headers=h,json={"operations":[
        {"idempotencyKey":"gh-harvest-idem-create","entityType":"greenhouse","entityId":gh,
         "operation":"CREATE","payload":{"name":"Harvest Idempotency"},"baseVersion":0},
        {"idempotencyKey":"cycle-harvest-idem-create","entityType":"crop_cycle","entityId":cycle,
         "operation":"CREATE","payload":{"greenhouseId":gh,"cropCode":"CUCUMBER"},"baseVersion":0}
    ]})
    assert sync.status_code == 200, sync.text
    p = product(h,"CUC-HARVEST-IDEM")
    first_harvest = client.post("/v1/erp/greenhouse/harvests",headers=h,json={
        "greenhouseId":gh,"cropCycleId":cycle,"productId":p,"warehouseId":"main",
        "quantity":10,"unitPrice":200,"unit":"kg"
    })
    second_harvest = client.post("/v1/erp/greenhouse/harvests",headers=h,json={
        "greenhouseId":gh,"cropCycleId":cycle,"productId":p,"warehouseId":"main",
        "quantity":5,"unitPrice":200,"unit":"kg"
    })
    assert first_harvest.status_code == 200 and second_harvest.status_code == 200
    w = warehouse(h,"HARVEST-IDEM")
    body = {"idempotencyKey":"harvest-receipt-idem-01","harvestId":first_harvest.json()["id"],
            "warehouseId":w,"lotCode":"HARVEST-IDEM-001","expiryDate":"2026-12-15"}
    first = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    duplicate_harvest_lot = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json={
        **body,"idempotencyKey":"harvest-duplicate-lot-01","harvestId":second_harvest.json()["id"]})
    assert duplicate_harvest_lot.status_code == 409, duplicate_harvest_lot.text
    changed_harvest = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json={**body,"harvestId":second_harvest.json()["id"]})
    assert changed_harvest.status_code == 409, changed_harvest.text
    changed_lot = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json={**body,"lotCode":"HARVEST-IDEM-CHANGED"})
    assert changed_lot.status_code == 409, changed_lot.text
    assert Decimal(client.get("/v2/erp/inventory/balances",headers=h).json()["items"][0]["quantity"]) == Decimal("10")


def test_harvest_lot_sales_shipment_and_crop_cost_reconcile_end_to_end():
    h = account("harvestcogs")
    gh = "gh-cogs-001"
    cycle = "cycle-cogs-001"
    sync = client.post("/v1/sync/push", headers=h, json={"operations":[
        {"idempotencyKey":"gh-cogs-create-001","entityType":"greenhouse","entityId":gh,
         "operation":"CREATE","payload":{"name":"Greenhouse COGS"},"baseVersion":0},
        {"idempotencyKey":"cycle-cogs-create-001","entityType":"crop_cycle","entityId":cycle,
         "operation":"CREATE","payload":{"greenhouseId":gh,"cropCode":"CUCUMBER"},"baseVersion":0}
    ]})
    assert sync.status_code == 200, sync.text
    p = product(h,"CUC-COGS-001")
    harvest = client.post("/v1/erp/greenhouse/harvests",headers=h,json={
        "greenhouseId":gh,"cropCycleId":cycle,"productId":p,"warehouseId":"main",
        "quantity":10,"unitPrice":200,"unit":"kg","qualityGrade":"A"
    })
    assert harvest.status_code == 200, harvest.text
    w = warehouse(h,"COGS-WH")
    lot_response = client.post("/v2/erp/inventory/harvest-receipts",headers=h,json={
        "idempotencyKey":"harvest-lot-cogs-001","harvestId":harvest.json()["id"],
        "warehouseId":w,"lotCode":"HARVEST-COGS-001","expiryDate":"2026-12-10"
    })
    assert lot_response.status_code == 200, lot_response.text
    release(h,lot_response.json()["lotId"])
    cost = client.post("/v2/erp/costs/entries",headers=h,json={
        "idempotencyKey":"cogs-cost-entry-001","greenhouseId":gh,"cropCycleId":cycle,
        "category":"LABOR","amount":"1000","currency":"IRR",
        "allocationMethod":"OUTPUT_QUANTITY","sourceReference":"HARVEST-COST-001"
    })
    assert cost.status_code == 200, cost.text
    approved = client.post(f"/v2/erp/costs/entries/{cost.json()['entryId']}/approve",
        headers={**h,"X-Approval-Token":os.environ["MOLIDO_COST_APPROVAL_TOKEN"]})
    assert approved.status_code == 200, approved.text
    run = client.post("/v2/erp/costs/runs",headers=h,json={
        "idempotencyKey":"cogs-cost-run-001","greenhouseId":gh,"cropCycleId":cycle,"currency":"IRR"
    })
    assert run.status_code == 200, run.text
    customer = client.post("/v1/crm/customers",headers=h,json={"name":"COGS Customer"})
    order = client.post("/v1/erp/sales/orders",headers=h,json={
        "partyId":customer.json()["id"],"lines":[{"productId":p,"quantity":10,"unitPrice":200}]
    })
    assert order.status_code == 200, order.text
    reserve_order = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fefo-reservations",
        headers=h,json={"idempotencyKey":"cogs-order-reserve-001","warehouseId":w})
    assert reserve_order.status_code == 200, reserve_order.text
    confirm = client.post(f"/v1/erp/orders/{order.json()['id']}/transition",headers=h,
        json={"action":"CONFIRM","idempotencyKey":"cogs-order-confirm-001"})
    assert confirm.status_code == 200, confirm.text
    shipped = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fulfill",headers=h,
        json={"idempotencyKey":"cogs-order-ship-001"})
    assert shipped.status_code == 200, shipped.text
    reconciliation = client.get(
        f"/v2/erp/inventory/orders/{order.json()['id']}/cost-reconciliation",headers=h)
    assert reconciliation.status_code == 200, reconciliation.text
    data = reconciliation.json()
    assert Decimal(data["cogs"]) == Decimal("1000")
    assert data["profitabilityStatus"] == "PROVISIONAL_COGS"
    assert Decimal(data["grossMarginBeforeOtherAdjustments"]) == Decimal("1000")
    delivered = client.post(f"/v1/erp/orders/{order.json()['id']}/transition",headers=h,
        json={"action":"DELIVER","idempotencyKey":"cogs-order-deliver-001"})
    assert delivered.status_code == 200 and delivered.json()["status"] == "DELIVERED"


def test_fefo_allocator_uses_earliest_expiry_and_is_idempotent():
    h = account("advancedfefo")
    p = product(h, "CUC-FEFO-01")
    w = warehouse(h, "FEFO")
    early = client.post("/v2/erp/inventory/lots", headers=h, json={
        "idempotencyKey": "fefo-receipt-early-01", "warehouseId": w, "productId": p,
        "lotCode": "FEFO-EARLY", "quantity": "3", "unit": "kg",
        "receivedDate": "2026-11-20", "expiryDate": "2026-12-10", "sourceType": "SUPPLIER"
    })
    late = client.post("/v2/erp/inventory/lots", headers=h, json={
        "idempotencyKey": "fefo-receipt-late-001", "warehouseId": w, "productId": p,
        "lotCode": "FEFO-LATE", "quantity": "8", "unit": "kg",
        "receivedDate": "2026-11-20", "expiryDate": "2026-12-20", "sourceType": "SUPPLIER"
    })
    assert early.status_code == 200 and late.status_code == 200
    release(h, early.json()["lotId"])
    release(h, late.json()["lotId"])
    body = {
        "idempotencyKey": "fefo-allocation-order-01", "warehouseId": w, "productId": p,
        "referenceType": "SALES_ORDER", "referenceId": "fefo-order-1", "quantity": "6"
    }
    allocated = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json=body)
    assert allocated.status_code == 200, allocated.text
    data = allocated.json()
    assert [x["lotId"] for x in data["allocations"]] == [early.json()["lotId"], late.json()["lotId"]]
    assert [x["quantity"] for x in data["allocations"]] == ["3", "3"]
    duplicate = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    assert len(duplicate.json()["allocations"]) == 2
    insufficient = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json={
        **body, "idempotencyKey": "fefo-allocation-order-02", "referenceId": "fefo-order-2", "quantity": "20"
    })
    assert insufficient.status_code == 409

def test_fefo_concurrent_allocations_never_reserve_more_than_available_stock():
    h = account("fefo-concurrency")
    p = product(h, "CUC-FEFO-RACE")
    w = warehouse(h, "FEFO-RACE")
    received = lot(h, p, w, "fefo-race-receipt-01", "FEFO-RACE-LOT", "10")
    release(h, received["lotId"])

    def reserve(index):
        return client.post("/v2/erp/inventory/fefo/allocate", headers=h, json={
            "idempotencyKey": f"fefo-race-request-{index:02d}",
            "warehouseId": w, "productId": p, "referenceType": "SALES_ORDER",
            "referenceId": f"SO-FEFO-RACE-{index:02d}", "quantity": "2"
        })

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(reserve, range(8)))
    successes = [response for response in responses if response.status_code == 200]
    conflicts = [response for response in responses if response.status_code == 409]
    assert len(successes) == 5, [(r.status_code, r.text) for r in responses]
    assert len(conflicts) == 3, [(r.status_code, r.text) for r in responses]
    assert all(response.status_code in (200, 409) for response in responses)
    trace = client.get(f"/v2/erp/inventory/lots/{received['lotId']}/trace", headers=h).json()
    active = sum(Decimal(row["quantity"]) for row in trace["reservations"] if row["state"] == "ACTIVE")
    assert active == Decimal("10")


def test_reservation_idempotency_keys_cannot_be_reused_for_different_requests_or_actions():
    h = account("reservationkeycollision")
    p = product(h, "CUC-RES-KEY")
    w = warehouse(h, "RES-KEY")
    received = lot(h, p, w, key="lot-res-key-001", code="LOT-RES-KEY", quantity="12")
    release(h, received["lotId"])

    request = {
        "idempotencyKey": "reserve-key-collision-01",
        "lotId": received["lotId"],
        "warehouseId": w,
        "referenceType": "SALES_ORDER",
        "referenceId": "SO-KEY-1",
        "quantity": "4",
    }
    reserved = client.post("/v2/erp/inventory/reservations", headers=h, json=request)
    assert reserved.status_code == 200, reserved.text
    duplicate = client.post("/v2/erp/inventory/reservations", headers=h, json=request)
    assert duplicate.status_code == 200
    assert duplicate.json()["reservationId"] == reserved.json()["reservationId"]

    changed_request = client.post(
        "/v2/erp/inventory/reservations",
        headers=h,
        json={**request, "quantity": "5"},
    )
    assert changed_request.status_code == 409

    reservation_id = reserved.json()["reservationId"]
    released = client.post(
        f"/v2/erp/inventory/reservations/{reservation_id}/actions",
        headers=h,
        json={"idempotencyKey": "reservation-action-key-01", "action": "RELEASE"},
    )
    assert released.status_code == 200, released.text

    changed_action = client.post(
        f"/v2/erp/inventory/reservations/{reservation_id}/actions",
        headers=h,
        json={"idempotencyKey": "reservation-action-key-01", "action": "FULFILL"},
    )
    assert changed_action.status_code == 409

    second = client.post(
        "/v2/erp/inventory/reservations",
        headers=h,
        json={**request, "idempotencyKey": "reserve-key-collision-02", "referenceId": "SO-KEY-2"},
    )
    assert second.status_code == 200, second.text
    reused_for_other_reservation = client.post(
        f"/v2/erp/inventory/reservations/{second.json()['reservationId']}/actions",
        headers=h,
        json={"idempotencyKey": "reservation-action-key-01", "action": "RELEASE"},
    )
    assert reused_for_other_reservation.status_code == 409

def test_return_idempotency_key_rejects_changed_payload():
    h = account("return-key-replay")
    customer = client.post("/v1/crm/customers", headers=h, json={"name": "Return Replay Customer"})
    p = product(h, "CUC-RETURN-REPLAY")
    w = warehouse(h, "RETURN-REPLAY")
    received = lot(h, p, w, key="return-replay-lot-01", code="RETURN-REPLAY-LOT", quantity="10")
    release(h, received["lotId"])
    order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId": customer.json()["id"], "lines": [{"productId": p, "quantity": 2, "unitPrice": 100}]
    })
    assert order.status_code == 200, order.text
    order_id = order.json()["id"]
    reserved = client.post(f"/v2/erp/inventory/orders/{order_id}/fefo-reservations", headers=h,
                           json={"idempotencyKey": "return-replay-reserve-01", "warehouseId": w})
    assert reserved.status_code == 200, reserved.text
    confirmed = client.post(f"/v1/erp/orders/{order_id}/transition", headers=h,
                            json={"action": "CONFIRM", "idempotencyKey": "return-replay-confirm-01"})
    assert confirmed.status_code == 200, confirmed.text
    shipped = client.post(f"/v2/erp/inventory/orders/{order_id}/fulfill", headers=h,
                          json={"idempotencyKey": "return-replay-ship-01"})
    assert shipped.status_code == 200, shipped.text
    body = {"idempotencyKey":"return-replay-key-001","direction":"CUSTOMER_RETURN",
            "lotId":received["lotId"],"warehouseId":w,"quantity":"2",
            "referenceId":order_id,"reason":"Damaged package","currency":"IRR"}
    first = client.post("/v2/erp/inventory/returns", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/inventory/returns", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["documentId"] == first.json()["documentId"]
    changed = client.post("/v2/erp/inventory/returns", headers=h, json={**body,"quantity":"3"})
    assert changed.status_code == 409


def test_scrap_idempotency_key_rejects_changed_payload():
    h = account("scrap-key-replay")
    p = product(h, "CUC-SCRAP-REPLAY")
    w = warehouse(h, "SCRAP-REPLAY")
    received = lot(h, p, w, key="scrap-replay-lot-01", code="SCRAP-REPLAY-LOT", quantity="10")
    body = {"idempotencyKey":"scrap-replay-key-001","lotId":received["lotId"],
            "warehouseId":w,"quantity":"2","reasonCode":"DAMAGED","reason":"Damaged stock",
            "sourceReference":"QC-001","currency":"IRR"}
    first = client.post("/v2/erp/inventory/scrap", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/inventory/scrap", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["documentId"] == first.json()["documentId"]
    changed = client.post("/v2/erp/inventory/scrap", headers=h, json={**body,"quantity":"3"})
    assert changed.status_code == 409


def test_cycle_count_idempotency_key_rejects_changed_count_lines():
    h = account("count-key-replay")
    p = product(h, "CUC-COUNT-REPLAY")
    w = warehouse(h, "COUNT-REPLAY")
    received = lot(h, p, w, key="count-replay-lot-01", code="COUNT-REPLAY-LOT", quantity="10")
    body = {"idempotencyKey":"count-replay-key-001","warehouseId":w,"reason":"Monthly count",
            "lines":[{"lotId":received["lotId"],"countedQuantity":"9"}]}
    first = client.post("/v2/erp/inventory/cycle-counts", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/inventory/cycle-counts", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["documentId"] == first.json()["documentId"]
    changed = client.post("/v2/erp/inventory/cycle-counts", headers=h,
                          json={**body,"lines":[{"lotId":received["lotId"],"countedQuantity":"8"}]})
    assert changed.status_code == 409

def test_sales_order_fefo_idempotency_key_is_bound_to_order_action_and_warehouse():
    h = account("sales-fefo-key-binding")
    customer = client.post("/v1/crm/customers", headers=h, json={"name":"FEFO Key Customer"})
    p = product(h, "CUC-FEFO-KEY-BIND")
    w = warehouse(h, "FEFO-KEY-BIND")
    other_w = warehouse(h, "FEFO-KEY-OTHER")
    first_order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId":customer.json()["id"],"lines":[{"productId":p,"quantity":2,"unitPrice":100}]
    })
    second_order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId":customer.json()["id"],"lines":[{"productId":p,"quantity":2,"unitPrice":100}]
    })
    assert first_order.status_code == 200 and second_order.status_code == 200
    received = lot(h, p, w, key="fefo-key-stock-01", code="FEFO-KEY-STOCK", quantity="4")
    release(h, received["lotId"])
    key = "sales-fefo-key-binding-01"
    endpoint = f"/v2/erp/inventory/orders/{first_order.json()['id']}/fefo-reservations"
    first = client.post(endpoint, headers=h, json={"idempotencyKey":key,"warehouseId":w})
    assert first.status_code == 200, first.text
    same = client.post(endpoint, headers=h, json={"idempotencyKey":key,"warehouseId":w})
    assert same.status_code == 200 and same.json()["status"] == "duplicate"
    wrong_warehouse = client.post(endpoint, headers=h, json={"idempotencyKey":key,"warehouseId":other_w})
    assert wrong_warehouse.status_code == 409
    wrong_order = client.post(
        f"/v2/erp/inventory/orders/{second_order.json()['id']}/fefo-reservations",
        headers=h,json={"idempotencyKey":key,"warehouseId":w})
    assert wrong_order.status_code == 409

def test_inventory_lot_rejects_invalid_calendar_dates():
    h = account("lot-invalid-date")
    p = product(h, "CUC-INVALID-DATE")
    w = warehouse(h, "INVALID-DATE")
    response = client.post("/v2/erp/inventory/lots", headers=h, json={
        "idempotencyKey":"invalid-lot-date-0001","warehouseId":w,"productId":p,
        "lotCode":"INVALID-DATE-LOT","quantity":"1","unit":"kg",
        "receivedDate":"2026-02-30","expiryDate":"2026-12-20"
    })
    assert response.status_code == 422

def test_lot_receipt_idempotency_rejects_changed_payload():
    h = account("lot-receipt-key")
    p = product(h, "CUC-LOT-REPLAY")
    w = warehouse(h, "LOT-REPLAY")
    body = {"idempotencyKey":"lot-receipt-replay-001","warehouseId":w,"productId":p,
            "lotCode":"LOT-REPLAY-001","quantity":"5","unit":"kg",
            "receivedDate":"2026-11-20","expiryDate":"2026-12-20","sourceType":"SUPPLIER"}
    first = client.post("/v2/erp/inventory/lots", headers=h, json=body)
    assert first.status_code == 200, first.text
    same = client.post("/v2/erp/inventory/lots", headers=h, json=body)
    assert same.status_code == 200 and same.json()["status"] == "duplicate"
    changed = client.post("/v2/erp/inventory/lots", headers=h, json={**body,"quantity":"6"})
    assert changed.status_code == 409


def test_fefo_allocation_idempotency_rejects_changed_request():
    h = account("fefo-replay-payload")
    p = product(h, "CUC-FEFO-REPLAY")
    w = warehouse(h, "FEFO-REPLAY")
    received = lot(h, p, w, key="fefo-replay-lot-001", code="FEFO-REPLAY-LOT", quantity="10")
    release(h, received["lotId"])
    body = {"idempotencyKey":"fefo-replay-key-001","warehouseId":w,"productId":p,
            "referenceType":"SALES_ORDER","referenceId":"SO-FEFO-REPLAY","quantity":"4"}
    first = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json=body)
    assert first.status_code == 200, first.text
    same = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json=body)
    assert same.status_code == 200 and same.json()["status"] == "duplicate"
    changed = client.post("/v2/erp/inventory/fefo/allocate", headers=h, json={**body,"quantity":"5"})
    assert changed.status_code == 409

def test_quality_status_change_requires_separate_human_approval():
    h = account("quality-approval-required")
    p = product(h, "CUC-QC-APPROVAL")
    w = warehouse(h, "QC-APPROVAL")
    received = lot(h, p, w, key="qc-approval-lot-001", code="QC-APPROVAL-LOT", quantity="5")
    endpoint = f"/v2/erp/inventory/lots/{received['lotId']}/quality"
    denied = client.post(endpoint, headers=h, json={"state":"RELEASED","reason":"Inspection passed"})
    assert denied.status_code == 403
    approved = client.post(endpoint,
        headers={**h,"X-Approval-Token":os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]},
        json={"state":"RELEASED","reason":"Inspection passed"})
    assert approved.status_code == 200, approved.text

def test_sales_order_confirmation_rejects_excess_lot_reservations():
    h = account("salesorderexcessreserve")
    customer = client.post("/v1/crm/customers",headers=h,json={"name":"Excess Reserve Customer"})
    p = product(h,"CUC-SALES-EXCESS")
    w = warehouse(h,"SALES-EXCESS")
    order = client.post("/v1/erp/sales/orders",headers=h,json={
        "partyId":customer.json()["id"],"lines":[{"productId":p,"quantity":5,"unitPrice":100}]
    })
    assert order.status_code == 200, order.text
    received = lot(h,p,w,"sales-excess-lot-001","SALES-EXCESS-LOT","10")
    release(h,received["lotId"])
    excess = client.post("/v2/erp/inventory/reservations",headers=h,json={
        "idempotencyKey":"sales-excess-reserve-001","lotId":received["lotId"],
        "warehouseId":w,"referenceType":"SALES_ORDER","referenceId":order.json()["id"],
        "quantity":"6"
    })
    assert excess.status_code == 200, excess.text
    confirmed = client.post(f"/v1/erp/orders/{order.json()['id']}/transition",headers=h,
        json={"action":"CONFIRM","idempotencyKey":"sales-excess-confirm-001"})
    assert confirmed.status_code == 409, confirmed.text
    balance_row = next(row for row in client.get("/v2/erp/inventory/balances",headers=h).json()["items"]
                       if row["lotId"] == received["lotId"])
    assert Decimal(balance_row["quantity"]) == Decimal("10")


def test_sales_order_fulfillment_rejects_partial_inventory_reservations():
    h = account("salesorderpartialreserve")
    customer = client.post("/v1/crm/customers", headers=h, json={"name":"Partial Reserve Customer"})
    p = product(h, "CUC-SALES-PARTIAL")
    w = warehouse(h, "SALES-PARTIAL")
    order = client.post("/v1/erp/sales/orders", headers=h, json={
        "partyId": customer.json()["id"],
        "lines": [{"productId": p, "quantity": 5, "unitPrice": 100}],
    })
    assert order.status_code == 200, order.text
    legacy_stock = client.post("/v1/erp/inventory/movements", headers=h, json={
        "idempotencyKey": "sales-partial-legacy-stock-001", "productId": p,
        "warehouseId": "main", "movementType": "RECEIPT", "quantity": 5,
    })
    assert legacy_stock.status_code == 200, legacy_stock.text
    received = lot(h, p, w, "sales-partial-lot-001", "SALES-PARTIAL-LOT", "10")
    release(h, received["lotId"])
    confirmed = client.post(f"/v1/erp/orders/{order.json()['id']}/transition", headers=h,
                            json={"action": "CONFIRM", "idempotencyKey": "sales-partial-confirm-001"})
    assert confirmed.status_code == 200, confirmed.text
    partial = client.post("/v2/erp/inventory/reservations", headers=h, json={
        "idempotencyKey": "sales-partial-reserve-001", "lotId": received["lotId"],
        "warehouseId": w, "referenceType": "SALES_ORDER", "referenceId": order.json()["id"],
        "quantity": "4",
    })
    assert partial.status_code == 200, partial.text
    blocked = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fulfill", headers=h,
                          json={"idempotencyKey": "sales-partial-fulfill-001"})
    assert blocked.status_code == 409, blocked.text
    balance_row = next(
        row for row in client.get("/v2/erp/inventory/balances", headers=h).json()["items"]
        if row["lotId"] == received["lotId"]
    )
    assert Decimal(balance_row["quantity"]) == Decimal("10")

