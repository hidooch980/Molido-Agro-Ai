package com.molido.agroai.data

import android.content.Context
import androidx.room.withTransaction
import org.json.JSONObject
import java.util.UUID

class SyncConflictResolver(private val context: Context, private val database: AgroDatabase) {
    suspend fun acceptServerVersion(change: SyncInboxEntity) {
        val payload = JSONObject(SyncPayloadCipher.decrypt(change.encryptedPayload))
        database.withTransaction {
            if (change.deleted) {
                deleteLocal(change.entityType, change.entityId)
            } else {
                applyLocal(change.entityType, change.entityId, payload)
            }
            database.syncInboxDao().setState(change.id, "RESOLVED_SERVER")
        }
    }

    suspend fun keepLocalVersion(change: SyncInboxEntity) {
        val old = database.syncOperationDao().conflictedForEntity(change.entityType, change.entityId)
            ?: error("نسخه محلی قابل بازیابی برای این تعارض وجود ندارد.")
        val now = System.currentTimeMillis()
        database.withTransaction {
            database.syncOperationDao().enqueue(
                SyncOperationEntity(
                    id = UUID.randomUUID().toString(),
                    idempotencyKey = "RESOLVE_LOCAL:${change.entityType}:${change.entityId}:${change.serverVersion}",
                    entityType = old.entityType,
                    entityId = old.entityId,
                    operation = old.operation,
                    payloadJson = old.payloadJson,
                    state = "PENDING",
                    attemptCount = 0,
                    createdAtEpochMillis = now,
                    nextAttemptAtEpochMillis = now,
                    baseVersion = change.serverVersion
                )
            )
            database.syncInboxDao().setState(change.id, "RESOLVED_LOCAL")
        }
        SyncScheduler.runNow(context)
    }

    private suspend fun deleteLocal(type: String, id: String) {
        when (type) {
            "greenhouse" -> database.greenhouseDao().deleteById(id)
            "crop_cycle" -> database.cropCycleDao().deleteById(id)
            "farm_activity" -> database.farmActivityDao().deleteById(id)
            "inventory_item" -> database.inventoryDao().deleteById(id)
            "financial_entry" -> database.financeDao().deleteById(id)
            else -> error("نوع داده دریافتی پشتیبانی نمی‌شود: $type")
        }
    }

    private suspend fun applyLocal(type: String, id: String, p: JSONObject) {
        fun nullableDouble(key: String): Double? = if (p.isNull(key) || !p.has(key)) null else p.getDouble(key)
        when (type) {
            "greenhouse" -> database.greenhouseDao().upsert(GreenhouseEntity(
                id, p.getString("name"), p.getDouble("areaSquareMeters"), p.optString("location"),
                p.optString("cultivationMethod", "SOIL"), p.optLong("createdAtEpochMillis", System.currentTimeMillis()),
                p.optBoolean("isActive", true)
            ))
            "crop_cycle" -> database.cropCycleDao().upsert(CropCycleEntity(
                id, p.getString("greenhouseId"), p.getString("cropCode"), p.optLong("startDateEpochMillis"),
                if (p.isNull("expectedHarvestDateEpochMillis")) null else p.optLong("expectedHarvestDateEpochMillis"),
                p.getDouble("plantedAreaSquareMeters"), if (p.isNull("plantCount")) null else p.optInt("plantCount"),
                p.optString("status", "ACTIVE"), p.optString("notes")
            ))
            "farm_activity" -> database.farmActivityDao().upsert(FarmActivityEntity(
                id, if (p.isNull("greenhouseId")) null else p.optString("greenhouseId"),
                if (p.isNull("cropCycleId")) null else p.optString("cropCycleId"),
                if (p.isNull("cropCode")) null else p.optString("cropCode"),
                p.getString("type"), p.getString("title"), nullableDouble("quantity"),
                if (p.isNull("unit")) null else p.optString("unit"), nullableDouble("cost"),
                p.optLong("occurredAtEpochMillis", System.currentTimeMillis()), p.optString("notes")
            ))
            "inventory_item" -> database.inventoryDao().upsert(InventoryItemEntity(
                id, p.getString("name"), p.optString("category"), p.getDouble("quantity"),
                p.optString("unit"), p.optDouble("minimumQuantity"), p.optLong("updatedAtEpochMillis", System.currentTimeMillis())
            ))
            "financial_entry" -> database.financeDao().upsert(FinancialEntryEntity(
                id, if (p.isNull("greenhouseId")) null else p.optString("greenhouseId"),
                p.getString("type"), p.optString("category"), p.getDouble("amount"),
                p.optString("currency", "IRR"), p.optLong("occurredAtEpochMillis", System.currentTimeMillis()),
                p.optString("description")
            ))
            else -> error("نوع داده دریافتی پشتیبانی نمی‌شود: $type")
        }
    }
}
