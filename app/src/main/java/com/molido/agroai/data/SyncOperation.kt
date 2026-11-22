package com.molido.agroai.data

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Entity(
    tableName = "sync_operations",
    indices = [
        Index(value = ["idempotencyKey"], unique = true),
        Index(value = ["state", "nextAttemptAtEpochMillis"])
    ]
)
data class SyncOperationEntity(
    @PrimaryKey val id: String,
    val idempotencyKey: String,
    val entityType: String,
    val entityId: String,
    val operation: String,
    val payloadJson: String,
    val state: String = "PENDING",
    val attemptCount: Int = 0,
    val createdAtEpochMillis: Long = System.currentTimeMillis(),
    val nextAttemptAtEpochMillis: Long = System.currentTimeMillis(),
    val lastError: String? = null,
    @ColumnInfo(defaultValue = "0") val baseVersion: Int = 0
)

@Dao
interface SyncOperationDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun enqueue(operation: SyncOperationEntity): Long

    @Query("SELECT * FROM sync_operations WHERE state = 'PENDING' AND nextAttemptAtEpochMillis <= :now ORDER BY createdAtEpochMillis, rowid LIMIT :limit")
    suspend fun due(now: Long = System.currentTimeMillis(), limit: Int = 50): List<SyncOperationEntity>

    @Query("SELECT COUNT(*) FROM sync_operations WHERE state = 'PENDING'")
    fun observePendingCount(): Flow<Int>

    @Query("UPDATE sync_operations SET state = 'SYNCED', lastError = NULL WHERE id = :id")
    suspend fun markSynced(id: String)

    @Query("UPDATE sync_operations SET attemptCount = attemptCount + 1, lastError = :error, nextAttemptAtEpochMillis = :retryAt WHERE id = :id AND state = 'PENDING'")
    suspend fun scheduleRetry(id: String, error: String, retryAt: Long)

    @Query("UPDATE sync_operations SET state = 'CONFLICT', lastError = :reason WHERE id = :id")
    suspend fun markConflict(id: String, reason: String)

    @Query("SELECT * FROM sync_operations WHERE idempotencyKey = :key LIMIT 1")
    suspend fun findByIdempotencyKey(key: String): SyncOperationEntity?

    @Query("SELECT * FROM sync_operations WHERE entityType = :type AND entityId = :entityId AND state = 'PENDING' ORDER BY createdAtEpochMillis DESC LIMIT 1")
    suspend fun pendingForEntity(type: String, entityId: String): SyncOperationEntity?

    @Query("SELECT * FROM sync_operations WHERE entityType = :type AND entityId = :entityId AND state = 'CONFLICT' ORDER BY createdAtEpochMillis DESC LIMIT 1")
    suspend fun conflictedForEntity(type: String, entityId: String): SyncOperationEntity?
}
