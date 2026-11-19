package com.molido.agroai.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "sync_inbox", indices = [Index(value = ["entityType", "entityId", "serverVersion"], unique = true)])
data class SyncInboxEntity(
    @PrimaryKey val id: String,
    val entityType: String,
    val entityId: String,
    val encryptedPayload: String,
    val serverVersion: Int,
    val updatedAtEpochMillis: Long,
    val deleted: Boolean,
    val state: String = "PENDING_REVIEW"
)

@Dao
interface SyncInboxDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun receive(change: SyncInboxEntity): Long

    @Query("SELECT * FROM sync_inbox WHERE state = 'PENDING_REVIEW' ORDER BY updatedAtEpochMillis")
    fun observePending(): Flow<List<SyncInboxEntity>>

    @Query("SELECT * FROM sync_inbox WHERE entityType = :type AND entityId = :id ORDER BY serverVersion DESC LIMIT 1")
    suspend fun latest(type: String, id: String): SyncInboxEntity?

    @Query("UPDATE sync_inbox SET state = :state WHERE id = :id")
    suspend fun setState(id: String, state: String)
}
