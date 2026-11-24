"""Bridge offline sync records into the CRM/ERP read models.

The Android client queues generic encrypted records through ``/v1/sync/push``,
while CRM/ERP screens and reports read ``business_parties`` and
``business_products``. Without a bridge, a customer or product captured on a
phone would never appear in the CRM. This module keeps that bridge narrow and
explicit: only customers, suppliers and products are mirrored; every other
entity type stays in the generic record store.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from business_api import ensure_business_tables

PARTY_TYPES = {'customer': 'CUSTOMER', 'supplier': 'SUPPLIER'}


def materialize_record(connection, user_id: str, entity_type: str, entity_id: str,
                       encrypted_payload: str, plaintext_payload: dict[str, Any],
                       created_at_millis: int, deleted: bool) -> str:
    """Mirror one applied sync record and return a short status for logging."""
    if entity_type not in PARTY_TYPES and entity_type != "product":
        return "ignored"
    ensure_business_tables(connection)

    if entity_type in PARTY_TYPES:
        party_type = PARTY_TYPES[entity_type]
        if deleted:
            connection.execute(
                "DELETE FROM business_parties WHERE user_id=? AND party_type=? AND party_id=?",
                (user_id, party_type, entity_id),
            )
            return "deleted"
        connection.execute(
            """INSERT INTO business_parties(user_id,party_type,party_id,payload,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(user_id,party_type,party_id)
               DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at""",
            (user_id, party_type, entity_id, encrypted_payload, created_at_millis),
        )
        return "applied"

    if deleted:
        connection.execute(
            "DELETE FROM business_products WHERE user_id=? AND product_id=?",
            (user_id, entity_id),
        )
        return "deleted"

    raw_sku = plaintext_payload.get("sku") if isinstance(plaintext_payload, dict) else None
    sku = str(raw_sku).strip() if raw_sku not in (None, "") else str(entity_id)
    sku = sku[:80] or str(entity_id)[:80]
    try:
        connection.execute(
            """INSERT INTO business_products(user_id,product_id,sku,payload,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(user_id,product_id)
               DO UPDATE SET sku=excluded.sku, payload=excluded.payload, created_at=excluded.created_at""",
            (user_id, entity_id, sku, encrypted_payload, created_at_millis),
        )
    except sqlite3.IntegrityError:
        # Another product already owns this SKU. The sync record is still stored;
        # only the CRM mirror is skipped so the push contract never fails.
        return "skipped_duplicate_sku"
    return "applied"
