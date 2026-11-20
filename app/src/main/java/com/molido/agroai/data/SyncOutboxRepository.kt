package com.molido.agroai.data

import android.content.Context
import androidx.room.withTransaction
import java.util.UUID

object SyncRetryPolicy {
    fun nextAttemptAt(nowEpochMillis: Long, attemptCount: Int): Long {
        require(attemptCount >= 0)
        val exponent = attemptCount.coerceAtMost(10)
        val delay = (30_000L * (1L shl exponent)).coerceAtMost(6L * 60L * 60L * 1000L)
        return if (nowEpochMillis > Long.MAX_VALUE - delay) Long.MAX_VALUE else nowEpochMillis + delay
    }
}

class SyncOutboxRepository(private val dao: SyncOperationDao) {
    suspend fun enqueue(
        context: Context,
        idempotencyKey: String,
        entityType: String,
        entityId: String,
        operation: String,
        payloadJson: String
    ): Boolean {
        require(idempotencyKey.isNotBlank() && idempotencyKey.length <= 200)
        require(entityType.isNotBlank() && entityId.isNotBlank())
        require(operation in setOf("CREATE", "UPDATE", "DELETE"))
        require(payloadJson.length <= 1_000_000)
        val now = System.currentTimeMillis()
        val row = SyncOperationEntity(
            id = UUID.randomUUID().toString(),
            idempotencyKey = idempotencyKey,
            entityType = entityType,
            entityId = entityId,
            operation = operation,
            payloadJson = SyncPayloadCipher.encrypt(context, payloadJson),
            createdAtEpochMillis = now,
            nextAttemptAtEpochMillis = now
        )
        val inserted = dao.enqueue(row) != -1L
        if (inserted) SyncScheduler.runNow(context)
        return inserted
    }

    suspend fun retry(id: String, attemptCount: Int, error: String, nowEpochMillis: Long = System.currentTimeMillis()) {
        val safeError = error.take(500)
        dao.scheduleRetry(id, safeError, SyncRetryPolicy.nextAttemptAt(nowEpochMillis, attemptCount))
    }
}


/**
 * Persists a local entity and its outbound CREATE event atomically.
 * The event remains local until a real authenticated sync transport is configured.
 */
suspend fun AgroDatabase.insertAndEnqueue(
    context: Context,
    entityType: String,
    entityId: String,
    payloadJson: String,
    insertLocal: suspend () -> Unit
) {
    require(entityType.matches(Regex("[a-z_]{1,40}")))
    require(entityId.isNotBlank() && entityId.length <= 200)
    require(payloadJson.length <= 1_000_000)
    withTransaction {
        insertLocal()
        val now = System.currentTimeMillis()
        syncOperationDao().enqueue(
            SyncOperationEntity(
                id = UUID.randomUUID().toString(),
                idempotencyKey = "CREATE:$entityType:$entityId",
                entityType = entityType,
                entityId = entityId,
                operation = "CREATE",
                payloadJson = SyncPayloadCipher.encrypt(context, payloadJson),
                createdAtEpochMillis = now,
                nextAttemptAtEpochMillis = now
            )
        )
    }
    SyncScheduler.runNow(context)
}

/** Update a local record and its outbound versioned operation atomically. */
suspend fun AgroDatabase.updateAndEnqueue(
    context: Context,
    entityType: String,
    entityId: String,
    payloadJson: String,
    updateLocal: suspend () -> Unit
) {
    require(entityType.matches(Regex("[a-z_]{1,40}")))
    require(entityId.isNotBlank() && payloadJson.length <= 1_000_000)
    withTransaction {
        updateLocal()
        val base = syncInboxDao().latest(entityType, entityId)?.serverVersion ?: 0
        val now = System.currentTimeMillis()
        syncOperationDao().enqueue(SyncOperationEntity(
            id = UUID.randomUUID().toString(),
            idempotencyKey = "UPDATE:$entityType:$entityId:${UUID.randomUUID()}",
            entityType = entityType, entityId = entityId, operation = "UPDATE",
            payloadJson = SyncPayloadCipher.encrypt(context, payloadJson),
            createdAtEpochMillis = now, nextAttemptAtEpochMillis = now, baseVersion = base
        ))
    }
    SyncScheduler.runNow(context)
}

/** Delete locally while preserving a versioned server tombstone in the outbox. */
suspend fun AgroDatabase.deleteAndEnqueue(
    context: Context,
    entityType: String,
    entityId: String,
    deleteLocal: suspend () -> Unit
) {
    require(entityType.matches(Regex("[a-z_]{1,40}")) && entityId.isNotBlank())
    withTransaction {
        val base = syncInboxDao().latest(entityType, entityId)?.serverVersion ?: 0
        deleteLocal()
        val now = System.currentTimeMillis()
        syncOperationDao().enqueue(SyncOperationEntity(
            id = UUID.randomUUID().toString(),
            idempotencyKey = "DELETE:$entityType:$entityId:${UUID.randomUUID()}",
            entityType = entityType, entityId = entityId, operation = "DELETE",
            payloadJson = SyncPayloadCipher.encrypt(context, "{}"),
            createdAtEpochMillis = now, nextAttemptAtEpochMillis = now, baseVersion = base
        ))
    }
    SyncScheduler.runNow(context)
}
