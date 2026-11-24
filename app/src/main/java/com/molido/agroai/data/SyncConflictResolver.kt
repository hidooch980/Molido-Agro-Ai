package com.molido.agroai.data

import android.content.Context
import androidx.room.withTransaction
import java.util.UUID

class SyncConflictResolver(private val context: Context, private val database: AgroDatabase) {
    private val projector = SyncProjector(database)

    suspend fun acceptServerVersion(change: SyncInboxEntity) {
        database.withTransaction {
            projector.applyChange(change)
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
}
