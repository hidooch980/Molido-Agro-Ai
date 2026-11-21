import base64
import os
from pathlib import Path

DB = Path("/tmp/molido-production-costing-tests.sqlite3")
if DB.exists():
    DB.unlink()
os.environ["MOLIDO_JWT_SECRET"] = "production-costing-test-secret-minimum-32"
os.environ["MOLIDO_DATA_KEY"] = base64.urlsafe_b64encode(b"abcdefghijklmnopqrstuvwxyz123456").decode().rstrip("=")
os.environ["MOLIDO_DB_PATH"] = str(DB)
os.environ["MOLIDO_COST_APPROVAL_TOKEN"] = "cost-approval-token-for-ci-minimum-32"

import app as app_module
from fastapi.testclient import TestClient
client = TestClient(app_module.app)


def account(name):
    r = client.post("/v1/auth/register", json={"username": name, "password": "Strong-test-password-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["accessToken"]}


def setup_cycle(headers, suffix):
    gh = "gh-" + suffix
    cycle = "cycle-" + suffix
    r = client.post("/v1/sync/push", headers=headers, json={"operations": [
        {"idempotencyKey": "greenhouse-" + suffix, "entityType": "greenhouse", "entityId": gh,
         "operation": "CREATE", "payload": {"name": "Greenhouse " + suffix}, "baseVersion": 0},
        {"idempotencyKey": "cycle-" + suffix, "entityType": "crop_cycle", "entityId": cycle,
         "operation": "CREATE", "payload": {"greenhouseId": gh, "cropCode": "CUCUMBER"}, "baseVersion": 0}
    ]})
    assert r.status_code == 200, r.text
    p = client.post("/v1/erp/products", headers=headers, json={
        "sku": "COST-" + suffix, "name": "Cucumber", "unit": "kg", "salePrice": 120, "purchasePrice": 50
    })
    assert p.status_code == 200, p.text
    h = client.post("/v1/erp/greenhouse/harvests", headers=headers, json={
        "greenhouseId": gh, "cropCycleId": cycle, "productId": p.json()["id"],
        "warehouseId": "main", "quantity": 100, "unitPrice": 120, "unit": "kg"
    })
    assert h.status_code == 200, h.text
    return gh, cycle


def test_cost_entries_require_approval_and_cost_run_is_versioned():
    h = account("costingapproval")
    gh, cycle = setup_cycle(h, "approval")
    entry = client.post("/v2/erp/costs/entries", headers=h, json={
        "idempotencyKey": "seed-cost-000001", "greenhouseId": gh, "cropCycleId": cycle,
        "category": "SEED_SEEDLING", "amount": "100000", "currency": "IRR",
        "allocationMethod": "OUTPUT_QUANTITY", "sourceReference": "PURCHASE-1001"
    })
    assert entry.status_code == 200 and entry.json()["status"] == "pending_approval"
    blocked = client.post("/v2/erp/costs/runs", headers=h, json={
        "idempotencyKey": "cost-run-blocked", "greenhouseId": gh, "cropCycleId": cycle, "currency": "IRR"
    })
    assert blocked.status_code == 409
    approved = client.post(f"/v2/erp/costs/entries/{entry.json()['entryId']}/approve",
        headers={**h, "X-Approval-Token": os.environ["MOLIDO_COST_APPROVAL_TOKEN"]})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    run = client.post("/v2/erp/costs/runs", headers=h, json={
        "idempotencyKey": "cost-run-approved", "greenhouseId": gh, "cropCycleId": cycle, "currency": "IRR"
    })
    assert run.status_code == 200, run.text
    assert run.json()["costPerUnit"] == "1000"
    assert run.json()["profitability"] == "NOT_CALCULATED_SALES_LINK_REQUIRED"
    duplicate = client.post("/v2/erp/costs/runs", headers=h, json={
        "idempotencyKey": "cost-run-approved", "greenhouseId": gh, "cropCycleId": cycle, "currency": "IRR"
    })
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    summary = client.get(f"/v2/erp/costs/cycles/{cycle}/summary", headers=h).json()
    assert summary["latestRun"]["capitalizableCost"] == "100000"


def test_abnormal_waste_is_reported_separately_from_capitalized_cost():
    h = account("costingwaste")
    gh, cycle = setup_cycle(h, "waste")
    for key, category, amount in [
        ("normal-cost-0001", "LABOR", "50000"),
        ("abnormal-waste-01", "WASTE_ABNORMAL", "7000")
    ]:
        entry = client.post("/v2/erp/costs/entries", headers=h, json={
            "idempotencyKey": key, "greenhouseId": gh, "cropCycleId": cycle,
            "category": category, "amount": amount, "currency": "IRR",
            "allocationMethod": "OUTPUT_QUANTITY", "sourceReference": "DOC-" + key
        })
        assert entry.status_code == 200
        approved = client.post(f"/v2/erp/costs/entries/{entry.json()['entryId']}/approve",
            headers={**h, "X-Approval-Token": os.environ["MOLIDO_COST_APPROVAL_TOKEN"]})
        assert approved.status_code == 200
    run = client.post("/v2/erp/costs/runs", headers=h, json={
        "idempotencyKey": "waste-cost-run-001", "greenhouseId": gh, "cropCycleId": cycle, "currency": "IRR"
    })
    assert run.status_code == 200, run.text
    assert run.json()["capitalizableCost"] == "50000"
    assert run.json()["abnormalWasteCost"] == "7000"


def test_cost_entries_are_tenant_isolated():
    owner = account("costowner")
    other = account("costother")
    gh, cycle = setup_cycle(owner, "tenant")
    foreign = client.post("/v2/erp/costs/entries", headers=other, json={
        "idempotencyKey": "foreign-cost-0001", "greenhouseId": gh, "cropCycleId": cycle,
        "category": "ENERGY", "amount": "1000", "currency": "IRR", "sourceReference": "ENERGY-1"
    })
    assert foreign.status_code == 404

def test_cost_entry_idempotency_rejects_changed_payload_and_preserves_original():
    h = account("costidempotency")
    gh, cycle = setup_cycle(h, "idempotency")
    body = {
        "idempotencyKey": "cost-entry-replay-0001", "greenhouseId": gh, "cropCycleId": cycle,
        "category": "ENERGY", "amount": "1250.50", "currency": "IRR",
        "quantity": "2.5", "unit": "kWh", "allocationMethod": "OUTPUT_QUANTITY",
        "sourceReference": "METER-READ-001", "notes": "Initial meter cost"
    }
    first = client.post("/v2/erp/costs/entries", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/costs/entries", headers=h, json=body)
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["entryId"] == first.json()["entryId"]

    changed = client.post("/v2/erp/costs/entries", headers=h, json={**body, "amount": "1251.50"})
    assert changed.status_code == 409, changed.text
    entries = client.get(f"/v2/erp/costs/cycles/{cycle}/entries", headers=h).json()["items"]
    assert len(entries) == 1
    assert entries[0]["amount"] == "1250.50"
    assert entries[0]["approvalStatus"] == "PENDING_APPROVAL"


def test_cost_run_idempotency_rejects_changed_cycle_or_currency():
    h = account("costrunidempotency")
    gh, cycle = setup_cycle(h, "runidempotency")
    entry = client.post("/v2/erp/costs/entries", headers=h, json={
        "idempotencyKey": "cost-run-seed-entry-01", "greenhouseId": gh, "cropCycleId": cycle,
        "category": "LABOR", "amount": "500", "currency": "IRR", "sourceReference": "LABOR-01"
    })
    assert entry.status_code == 200, entry.text
    approved = client.post(f"/v2/erp/costs/entries/{entry.json()['entryId']}/approve",
        headers={**h, "X-Approval-Token": os.environ["MOLIDO_COST_APPROVAL_TOKEN"]})
    assert approved.status_code == 200
    body = {"idempotencyKey": "cost-run-replay-0001", "greenhouseId": gh,
            "cropCycleId": cycle, "currency": "IRR"}
    first = client.post("/v2/erp/costs/runs", headers=h, json=body)
    assert first.status_code == 200, first.text
    duplicate = client.post("/v2/erp/costs/runs", headers=h, json=body)
    assert duplicate.status_code == 200 and duplicate.json()["status"] == "duplicate"
    changed = client.post("/v2/erp/costs/runs", headers=h, json={**body, "currency": "USD"})
    assert changed.status_code == 409, changed.text
    summary = client.get(f"/v2/erp/costs/cycles/{cycle}/summary", headers=h).json()
    assert len(summary["runs"]) == 1

