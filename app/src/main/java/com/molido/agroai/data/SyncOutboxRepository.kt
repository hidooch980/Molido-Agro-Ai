package com.molido.agroai.data

import java.util.UUID

object SyncRetryPolicy {
    fun nextAttemptAt(nowEpochMillis: Long, attemptCount: Int): Long {
        require(attemptCount >= 0)
        val exponent = attemptCount.coerceAtMost(10)
        val delay = (30_000L * (1L shl exponent)).coerceAtMost(6L * 60L * 60L * 1000L)
        return nowEpochMillis + delay
    }
}

class SyncOutboxRepository(private val dao: SyncOperationDao) {
    suspend fun enqueue(
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
            payloadJson = payloadJson,
            createdAtEpochMillis = now,
            nextAttemptAtEpochMillis = now
        )
        return dao.enqueue(row) != -1L
    }

    suspend fun retry(id: String, attemptCount: Int, error: String, nowEpochMillis: Long = System.currentTimeMillis()) {
        val safeError = error.take(500)
        dao.scheduleRetry(id, safeError, SyncRetryPolicy.nextAttemptAt(nowEpochMillis, attemptCount))
    }
}
