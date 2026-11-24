package com.molido.agroai.data

import org.json.JSONObject

/**
 * Applies a decrypted sync payload onto the local Room entities.
 *
 * The payload shape is the same JSON the outbox builds when it enqueues a change, so a
 * record written by another device can be materialised locally without a second mapping.
 * Callers must run the methods inside a database transaction.
 */
class SyncProjector(private val database: AgroDatabase) {
    /** Farm records map onto their own tables; every other type is a generic business record. */
    suspend fun applyChange(change: SyncInboxEntity) {
        val payload = JSONObject(SyncPayloadCipher.decrypt(change.encryptedPayload))
        if (change.deleted) delete(change.entityType, change.entityId)
        else applyPayload(change.entityType, change.entityId, payload)
    }

    suspend fun delete(entityType: String, entityId: String) {
        when (entityType) {
            "greenhouse" -> database.greenhouseDao().deleteById(entityId)
            "crop_cycle" -> database.cropCycleDao().deleteById(entityId)
            "farm_activity" -> database.farmActivityDao().deleteById(entityId)
            "inventory_item" -> database.inventoryDao().deleteById(entityId)
            "financial_entry" -> database.financeDao().deleteById(entityId)
            else -> database.businessRecordDao().deleteById(entityId)
        }
    }

    suspend fun applyPayload(entityType: String, entityId: String, payload: JSONObject) {
        // org.json reports an absent key as "not null", so presence must be checked first:
        // otherwise an omitted optional field becomes "" or 0 instead of staying null.
        fun present(key: String): Boolean = payload.has(key) && !payload.isNull(key)
        fun optionalString(key: String): String? = if (present(key)) payload.optString(key) else null
        fun optionalInt(key: String): Int? = if (present(key)) payload.optInt(key) else null
        fun optionalLong(key: String): Long? = if (present(key)) payload.optLong(key) else null
        fun nullableDouble(key: String): Double? = if (present(key)) payload.getDouble(key) else null
        when (entityType) {
            "greenhouse" -> database.greenhouseDao().upsert(GreenhouseEntity(
                entityId, payload.getString("name"), payload.getDouble("areaSquareMeters"),
                payload.optString("location"), payload.optString("cultivationMethod", "SOIL"),
                payload.optLong("createdAtEpochMillis", System.currentTimeMillis()),
                payload.optBoolean("isActive", true)
            ))
            "crop_cycle" -> database.cropCycleDao().upsert(CropCycleEntity(
                entityId, payload.getString("greenhouseId"), payload.getString("cropCode"),
                payload.optLong("startDateEpochMillis"),
                optionalLong("expectedHarvestDateEpochMillis"),
                payload.getDouble("plantedAreaSquareMeters"),
                optionalInt("plantCount"),
                payload.optString("status", "ACTIVE"), payload.optString("notes")
            ))
            "farm_activity" -> database.farmActivityDao().upsert(FarmActivityEntity(
                entityId,
                optionalString("greenhouseId"),
                optionalString("cropCycleId"),
                optionalString("cropCode"),
                payload.getString("type"), payload.getString("title"), nullableDouble("quantity"),
                optionalString("unit"), nullableDouble("cost"),
                payload.optLong("occurredAtEpochMillis", System.currentTimeMillis()), payload.optString("notes")
            ))
            "inventory_item" -> database.inventoryDao().upsert(InventoryItemEntity(
                entityId, payload.getString("name"), payload.optString("category"),
                payload.getDouble("quantity"), payload.optString("unit"),
                payload.optDouble("minimumQuantity"), payload.optLong("updatedAtEpochMillis", System.currentTimeMillis())
            ))
            "financial_entry" -> database.financeDao().upsert(FinancialEntryEntity(
                entityId,
                optionalString("greenhouseId"),
                payload.getString("type"), payload.optString("category"), payload.getDouble("amount"),
                payload.optString("currency", "IRR"),
                payload.optLong("occurredAtEpochMillis", System.currentTimeMillis()),
                payload.optString("description")
            ))
            else -> database.businessRecordDao().upsert(BusinessRecordEntity(
                id = entityId,
                recordType = payload.optString("recordType", entityType),
                title = payload.optString("title", payload.optString("name", entityId)),
                status = payload.optString("status", "SYNCED"),
                payloadJson = payload.toString(),
                createdAtEpochMillis = payload.optLong("createdAtEpochMillis", System.currentTimeMillis())
            ))
        }
    }

    companion object {
        val FARM_TYPES: Set<String> = setOf("greenhouse", "crop_cycle", "farm_activity", "inventory_item", "financial_entry")
    }
}
