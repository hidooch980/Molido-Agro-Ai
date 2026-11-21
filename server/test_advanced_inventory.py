import base64
import os
from decimal import Decimal
from pathlib import Path

DB = Path("/tmp/molido-advanced-inventory-tests.sqlite3")
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "advanced-inventory-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)
os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"] = "inventory-approval-token-for-ci-minimum-32"
os.environ["MOLIDO_COST_APPROVAL_TOKEN"] = "cost-approval-token-for-ci-minimum-32"

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


def test_customer_and_supplier_returns_require_approval_and_keep_ledger_history():
    h = account("returnflows")
    p = product(h, "CUC-RETURN-01")
    w = warehouse(h, "RETURNS")
    received = lot(h, p, w, "return-base-lot-01", "RETURN-BASE", "20")
    release(h, received["lotId"])
    customer = client.post("/v2/erp/inventory/returns", headers=h, json={
        "idempotencyKey":"customer-return-001","direction":"CUSTOMER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"3",
        "referenceId":"SO-RETURN-1","reason":"Customer returned damaged packaging"
    })
    assert customer.status_code == 200 and customer.json()["status"] == "pending_approval"
    approval_headers = {**h, "X-Approval-Token":os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]}
    approved_customer = client.post(
        f"/v2/erp/inventory/returns/{customer.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-customer-return-001"})
    assert approved_customer.status_code == 200, approved_customer.text
    returned_lot = client.get(f"/v2/erp/inventory/lots/{approved_customer.json()['lotId']}/trace",
                              headers=h).json()["lot"]
    assert returned_lot["qualityState"] == "PENDING_INSPECTION"
    supplier = client.post("/v2/erp/inventory/returns", headers=h, json={
        "idempotencyKey":"supplier-return-001","direction":"SUPPLIER_RETURN",
        "lotId":received["lotId"],"warehouseId":w,"quantity":"4",
        "referenceId":"PO-RETURN-1","reason":"Supplier quality claim"
    })
    assert supplier.status_code == 200
    approved_supplier = client.post(
        f"/v2/erp/inventory/returns/{supplier.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-supplier-return-001"})
    assert approved_supplier.status_code == 200, approved_supplier.text
    trace = client.get(f"/v2/erp/inventory/lots/{received['lotId']}/trace", headers=h).json()
    assert [x["type"] for x in trace["movements"]][-1] == "SUPPLIER_RETURN"
    assert trace["balances"][0]["quantity"] == "16"


def test_scrap_and_cycle_count_are_approval_gated_and_idempotent():
    h = account("scrapcount")
    p = product(h, "CUC-SCRAP-COUNT")
    w = warehouse(h, "SCRAPCOUNT")
    received = lot(h, p, w, "scrap-count-lot-01", "SCRAP-COUNT-LOT", "10")
    release(h, received["lotId"])
    scrap = client.post("/v2/erp/inventory/scrap", headers=h, json={
        "idempotencyKey":"scrap-doc-0001","lotId":received["lotId"],"warehouseId":w,
        "quantity":"2","reasonCode":"DAMAGED","reason":"Damaged produce",
        "sourceReference":"QC-REPORT-1"
    })
    assert scrap.status_code == 200 and scrap.json()["status"] == "pending_approval"
    approval_headers = {**h, "X-Approval-Token":os.environ["MOLIDO_INVENTORY_APPROVAL_TOKEN"]}
    posted_scrap = client.post(
        f"/v2/erp/inventory/scrap/{scrap.json()['documentId']}/approve",
        headers=approval_headers, json={"idempotencyKey":"approve-scrap-0001"})
    assert posted_scrap.status_code == 200, posted_scrap.text
    count = client.post("/v2/erp/inventory/cycle-counts", headers=h, json={
        "idempotencyKey":"cycle-count-0001","warehouseId":w,"reason":"Weekly physical count",
        "lines":[{"lotId":received["lotId"],"countedQuantity":"7"}]
    })
    assert count.status_code == 200 and count.json()["variances"][0]["variance"] == "-1"
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
    reserved = client.post(f"/v2/erp/inventory/orders/{order.json()['id']}/fefo-reservations",
                           headers=h,json={"idempotencyKey":"order-fefo-reserve-001","warehouseId":w})
    assert reserved.status_code == 200, reserved.text
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
    order_state = next(x for x in client.get("/v1/erp/orders",headers=h).json()["items"]
                       if x["id"] == order.json()["id"])
    assert order_state["status"] == "RECEIVED"



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
