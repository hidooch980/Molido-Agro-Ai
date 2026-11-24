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
    fun supports(entityType: String): Boolean = entityType.isNotBlank()

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
        fun nullableDouble(key: String): Double? = if (payload.isNull(key) || !payload.has(key)) null else payload.getDouble(key)
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
                if (payload.isNull("expectedHarvestDateEpochMillis")) null else payload.optLong("expectedHarvestDateEpochMillis"),
                payload.getDouble("plantedAreaSquareMeters"),
                if (payload.isNull("plantCount")) null else payload.optInt("plantCount"),
                payload.optString("status", "ACTIVE"), payload.optString("notes")
            ))
            "farm_activity" -> database.farmActivityDao().upsert(FarmActivityEntity(
                entityId,
                if (payload.isNull("greenhouseId")) null else payload.optString("greenhouseId"),
                if (payload.isNull("cropCycleId")) null else payload.optString("cropCycleId"),
                if (payload.isNull("cropCode")) null else payload.optString("cropCode"),
                payload.getString("type"), payload.getString("title"), nullableDouble("quantity"),
                if (payload.isNull("unit")) null else payload.optString("unit"), nullableDouble("cost"),
                payload.optLong("occurredAtEpochMillis", System.currentTimeMillis()), payload.optString("notes")
            ))
            "inventory_item" -> database.inventoryDao().upsert(InventoryItemEntity(
                entityId, payload.getString("name"), payload.optString("category"),
                payload.getDouble("quantity"), payload.optString("unit"),
                payload.optDouble("minimumQuantity"), payload.optLong("updatedAtEpochMillis", System.currentTimeMillis())
            ))
            "financial_entry" -> database.financeDao().upsert(FinancialEntryEntity(
                entityId,
                if (payload.isNull("greenhouseId")) null else payload.optString("greenhouseId"),
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
