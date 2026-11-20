# Advanced ERP, Production Costing, Iran Accounting and Acceptance Specification

Status: approved implementation scope / design baseline. This document is not evidence that the features are implemented, legally certified, or deployed.

## 1. Non-negotiable implementation rules

- Keep the product LAN-first and self-hosted. Core inventory, production, costing, accounting, sync, backup and recovery must work without a mandatory SaaS dependency.
- Preserve existing greenhouse, crop-cycle, harvest, CRM, order and sync data. All schema changes require forward migrations and tested backup/restore compatibility.
- Use append-only business ledgers for stock movements and posted accounting journals. Correct errors with reversals/counter-entries; never silently rewrite posted history.
- Every tenant-owned row and every relationship must be scoped and validated against the authenticated account on the server. Client-supplied account IDs are never authorization.
- Use decimal-safe arithmetic. Do not use binary floating point for money or quantities that affect valuation. Persist currency and unit explicitly; use integer Rials for IRR monetary amounts unless an approved currency precision policy says otherwise.
- All write commands must be idempotent and transactionally safe. Use optimistic entity versions for offline edits and explicit conflict resolution.
- No AI-generated agricultural, accounting, tax, or inventory decision may post or irreversibly execute without the required human approval.
- No feature may be labelled production-ready until its tests and acceptance evidence pass.

## 2. Advanced inventory model

### 2.1 Master data

Introduce account-scoped entities:
- warehouses: code, name, type, address/site, active state;
- warehouse_locations: warehouse, zone/bin, temperature or handling profile where relevant;
- inventory_items: SKU, product, base unit, tracking policy, valuation policy, minimum/maximum stock;
- lots: lot code, product, supplier or production source, manufacture/harvest date, expiry/best-before date, received date, quality state;
- lot_genealogy: parent lot to child lot transformations (grading, repacking, splitting, merging) with quantities and conversion factors;
- stock_reservations: order line, warehouse, location, lot, reserved quantity, expiry and state;
- quality_inspections: sample, inspection plan, measured values, result, inspector, evidence and disposition;
- inventory_documents: receipt, issue, transfer, adjustment, return, quarantine, release, scrap and count documents.

Unique constraints must be tenant-scoped. Lot codes need a configurable uniqueness scope (per product, supplier, or account); never assume global uniqueness.

### 2.2 Movement ledger and balances

Implement an immutable stock movement ledger with:
- receipt, issue, transfer-out, transfer-in, reservation, reservation-release, shipment, customer-return, supplier-return, positive/negative adjustment, quarantine, quality-release, scrap and production-consumption/production-output events;
- source and destination warehouse/location, product, lot, quantity, base unit, reference document, actor, timestamp, idempotency key and reversal link;
- a transactionally maintained balance projection by account + warehouse + location + product + lot + stock status.

Transfers must be atomic: source decrement and destination increment commit together. Reservation must not change physical on-hand quantity; it changes available-to-promise. Available quantity = on-hand minus active reservations and blocked/quarantined quantities. Prevent negative available stock under concurrent requests using database transactions/locking and unique idempotency keys.

### 2.3 Expiry, FEFO and traceability

- Support production/harvest date, receipt date, expiry date, best-before date and optional shelf-life rules.
- Provide FEFO (first-expire-first-out) allocation as the default suggestion for perishable goods, with explicit authorized override and audit trail. FEFO suggestions must exclude quarantined, expired, rejected and otherwise blocked lots.
- Trace forward from input lot to all derived lots, harvest lots, shipments, customers and order lines; trace backward from a shipped lot to source receipts, suppliers, greenhouse, crop cycle, harvest, consumed inputs and related activities.
- Record lot splitting, merging, grading and packaging as genealogy transformations with mass-balance checks and documented loss/yield.
- Block expiry-invalid shipment unless an authorized override policy explicitly allows it.

### 2.4 Quality, quarantine, waste and returns

- Quality states: PENDING_INSPECTION, RELEASED, QUARANTINED, REJECTED, EXPIRED. State transitions require permissions, evidence and audit events.
- Quarantine moves stock into a blocked status/location; it must not be available for reservation or sale.
- Scrap/waste requires reason code, quantity, lot, responsible actor, approval threshold and accounting/cost impact.
- Customer returns must reference original shipment/order/lot where known; inspect returned goods and route to RELEASED, QUARANTINED, REWORK or SCRAP. Never auto-return to sellable stock.
- Supplier returns must reference receipt/lot and reverse the corresponding stock and payable/settlement workflow without deleting original receipt history.
- Cycle counts and adjustments require reason, approval thresholds and variance reporting.

## 3. Greenhouse production and cost of production

### 3.1 Cost objects and traceability

Use crop_cycle as the production cost object. Each harvest lot is a child cost object linked to greenhouse, crop cycle, crop, harvest event, product grade, quantity and quality. Preserve the chain:
greenhouse -> crop cycle -> farm activity/input consumption -> harvest batch/lot -> grading/packaging -> inventory lot -> sales order/shipment -> customer.

A crop-cycle cost ledger must capture:
- seeds and seedlings;
- fertilizers, growing media and other inputs;
- crop protection inputs (record use and cost only; do not generate unsafe dosage recommendations);
- direct labor and approved labor burden;
- energy, water and utilities;
- machinery, maintenance and operational services;
- packaging and post-harvest handling;
- quality inspection and storage costs where policy permits;
- normal and abnormal waste/loss separately.

Each cost entry requires amount, currency, tax treatment if known, source document, date, cost category, greenhouse, crop cycle, quantity/unit where applicable, allocation method, actor and approval status.

### 3.2 Allocation and costing engine

- Directly assign costs where traceable; otherwise allocate by a configured and auditable driver such as labor hours, area-days, machine hours, water/energy meter consumption, input quantity or harvested kilograms.
- Support multi-stage allocation: crop cycle -> harvest lots -> grades/packaging lots -> inventory lots.
- Separate normal yield loss from abnormal waste. Abnormal loss must be separately visible and must not be silently capitalized into good output.
- Calculate actual cost per unit and per lot from posted/approved cost entries and accepted output quantity. Recalculate through explicit versioned cost runs; preserve previous runs and explain deltas.
- Support provisional estimates during the crop cycle, then actual/settled cost after harvest and cost close.
- Define treatment for joint products/by-products and allocation of shared costs before enabling production close.
- Inventory valuation policy (e.g., weighted average or FIFO) must be selected per account/item and validated by accounting review. Physical FEFO picking and financial FIFO valuation are different policies and must not be conflated.
- Profitability reports must use actual shipment quantities, returns, discounts, freight/packaging policy, recognized revenue and lot cost. Show provisional vs finalized margin distinctly.

### 3.3 Reconciliation controls

Reconcile:
- input issues to crop-cycle consumption;
- crop-cycle costs to harvest output and waste;
- harvest lots to inventory receipts;
- inventory issues to shipments and sales order lines;
- shipment cost to cost of goods sold;
- returns and credit notes to original lots and journals.

A production period cannot be marked closed while unexplained quantity or value variances exceed configured tolerances.

## 4. Iran accounting and tax design

### 4.1 Scope and legal boundary

The system is initially an internal management accounting and operational ERP system. It is not a certified statutory accounting package, tax advisor, or official invoice issuer.

Before any statutory/official mode is enabled, a qualified Iranian accountant and tax specialist must approve:
- chart of accounts and account mapping;
- fiscal year/period close and opening/closing entries;
- inventory valuation and cost-of-sales policy;
- revenue recognition, returns, discounts and advances;
- payroll/labor cost and statutory liabilities where included;
- VAT classifications, exemptions, rates and effective dates;
- electronic invoice types, required fields, identifiers, correction/cancellation/refund flows and submission protocol;
- tax return and statutory report formats;
- retention, audit trail, signing, authorization and evidence requirements.

Rules must be versioned by effective date and taxpayer/business profile. Never hardcode a single VAT rate or assume all agricultural goods/inputs are taxable or exempt. Tax treatment must be based on current law, executive regulations, official notices and the taxpayer's classification, with human approval.

### 4.2 Ledger architecture

- Account chart is configurable, versioned and tenant-specific, with code, title, parent, nature, currency policy, control account and effective dates.
- Journal header and lines are immutable once POSTED. Draft and pending-approval states are editable only under permission; posting is atomic and validates debits = credits.
- Every journal links to source event/document and uses a unique source reference to prevent duplicate posting.
- Periods support OPEN, SOFT_CLOSED and CLOSED; posting into closed periods is blocked except a controlled reopening workflow with elevated approval and audit.
- Reversals are new linked journals. Do not delete or mutate posted entries.
- Separate tax amount, tax code, taxable base, exemption reason, tax date and tax effective-version from gross/net amount.
- Multi-currency requires explicit exchange-rate source, rate date, functional currency and realized/unrealized FX treatment; do not imply this is implemented until reviewed.
- Enforce maker-checker approval for sensitive postings, period close, write-offs, inventory adjustments, manual journals and statutory invoice submission. Approval must be role-based and auditable; a shared static token alone is insufficient.
- Reports: trial balance, general ledger, subledger reconciliation, income statement, balance sheet, cash flow, inventory valuation, COGS, VAT control/reconciliation and production profitability. Mark management-only reports clearly until legally reviewed.

### 4.3 Electronic invoicing and VAT

- Build an adapter boundary for the Iranian Taxpayer System (سامانه مؤدیان), but keep it disabled until the official current technical specification, taxpayer identifiers/certificate/key management, invoice schema, signing, transport, error handling, cancellation/correction rules and test environment are verified.
- Store outbound payload, payload hash, submission attempt, official tracking/unique identifiers, response, timestamps and retry state. Idempotency must prevent duplicate invoice submission.
- Support offline draft preparation, but never claim an offline draft is an official electronic invoice.
- Maintain a tax rule registry with source citation, publication/effective dates, scope, rate or exemption, reviewer and approval status. A rule without verified authoritative source is marked UNVERIFIED and cannot drive statutory output.
- Verify the current effect of the 1404/10/01 (2025-12-22) transition and subsequent amendments/notices before implementation; do not rely on secondary summaries alone.

### 4.4 Legal research references to verify before sign-off

Starting research leads (not legal sign-off):
- Law on Invoicing Terminals and Taxpayer System (قانون پایانه‌های فروشگاهی و سامانه مؤدیان), including amendments and later facilitation provisions: https://law-ir.ir/law/cat/1769/
- Value Added Tax Act 1400 (قانون مالیات بر ارزش افزوده مصوب ۱۴۰۰): https://acco.ir/15696
- Accounting Standard No. 8, Inventories (استاندارد حسابداری شماره ۸): https://hesabgaranpishtaz.ir/wp-content/uploads/2023/12/8.pdf
- Tax circular regarding electronic invoices and VAT input-credit treatment from 1404/10/01, subject to checking original official circular and later amendments: https://hoghogh.ai/circulars/c-53cc450d

The final legal matrix must link every implemented rule to the exact current official source and article/paragraph, record retrieval date and effective date, and be signed off by the named professional reviewers. Secondary websites are discovery aids only; official tax authority and Audit Organization publications prevail.

## 5. Android workflows and offline synchronization

- Add domain-specific screens for warehouse selection, lot/expiry, QC inspection, quarantine/release, transfers, counts, scrap, returns, production input consumption, harvest lot creation, packaging and traceability.
- Add crop-cycle cost capture and per-lot costing/profitability views with clear provisional/final state.
- Add accounting journal review, approvals, period controls, tax code selection and invoice draft status; sensitive posting/submission requires server-side permission and approval.
- Sync commands must target domain APIs and materialize to domain tables, not merely generic sync records.
- Every local edit/delete carries entity ID, base server version, operation ID, idempotency key and tombstone; server returns canonical entity version and conflict details.
- Pull uses an account-scoped change cursor with stable ordering, pagination and replay safety. Persist cursor only after local transaction commits.
- Conflicts are surfaced with field-level comparison where possible; never silently overwrite server or local changes. Resolution creates a new versioned command.
- On logout/account change, isolate or securely purge account-scoped cache according to an explicit retention policy.

## 6. Security, concurrency and recovery acceptance

Required automated and integration tests:
- cross-account reads/writes and relationship-ID substitution across every new endpoint;
- unauthorized role, approval bypass, forged actor, mass assignment and request tampering;
- duplicate/replayed requests, idempotency-key collision and retry after timeout;
- concurrent receipt/issue/reservation/transfer/return/scrap against the same lot, proving no negative stock and no duplicate posting;
- concurrent cost-run and period-close attempts;
- expired/quarantined/rejected lot allocation and unauthorized override;
- broken lot genealogy and mass-balance variance;
- network loss before/after server commit, retry, cursor replay, local crash before cursor commit and conflict recovery;
- encrypted backup, integrity check, restore into clean environment, schema migration from supported prior versions, and post-restore reconciliation of balances, lot genealogy, journals and sync cursors;
- secret rotation, TLS validation, audit-log tamper resistance and least-privilege permissions.

Use property-based and stress tests for inventory invariants. A successful unit test is not a substitute for concurrency/load and restore drills.

## 7. Physical Android acceptance

A real device test is mandatory and cannot be marked complete using an emulator alone:
1. Install the currently signed APK on a supported Android phone.
2. Verify signer certificate/fingerprint and SHA-256; verify update APK uses the same signing identity.
3. Exercise offline create/edit/delete for stock, lot, QC, harvest, cost and order records.
4. Reconnect to trusted LAN TLS and verify two-way sync, retries, duplicate suppression and conflict resolution across at least two clients.
5. Force-stop/reboot during pending sync and confirm durable recovery.
6. Upgrade from the previous installed build without clearing app data; verify Room migrations, login/session policy, local records, outbox and sync cursor.
7. Test backup/restore and verify inventory/cost/accounting reconciliations.
8. Record phone model, Android version, APK version/code, signer fingerprint, test data, screenshots/logs, pass/fail and defects.

Do not claim physical-device acceptance until a real device has been available and the evidence is recorded.

## 8. Delivery gates

Gate A: schema and migrations reviewed; existing data preserved.
Gate B: inventory ledger, lot genealogy, QC, reservations, returns and invariants pass tests.
Gate C: crop-cycle and harvest-lot cost engine reconciles quantities and values.
Gate D: accounting engine and reports pass double-entry, period, audit and reconciliation tests; legal matrix reviewed by professionals.
Gate E: Android workflows and bidirectional domain sync pass offline, replay and conflict tests.
Gate F: security, concurrency, backup/restore and load tests pass.
Gate G: signed APK installed and upgraded on a physical phone with evidence.
Only after all applicable gates pass may the feature set be described as complete. Legal/statutory claims additionally require documented external professional sign-off.
