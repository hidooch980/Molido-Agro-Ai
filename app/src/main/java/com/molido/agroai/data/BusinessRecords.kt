package com.molido.agroai.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "business_records", indices = [Index(value = ["recordType", "createdAtEpochMillis"])])
data class BusinessRecordEntity(
    @PrimaryKey val id: String,
    val recordType: String,
    val title: String,
    val status: String,
    val payloadJson: String,
    val createdAtEpochMillis: Long = System.currentTimeMillis()
)

@Dao
interface BusinessRecordDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(item: BusinessRecordEntity)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(item: BusinessRecordEntity)

    @Query("DELETE FROM business_records WHERE id = :id")
    suspend fun deleteById(id: String)

    @Query("SELECT * FROM business_records ORDER BY createdAtEpochMillis DESC LIMIT 500")
    fun observeAll(): Flow<List<BusinessRecordEntity>>

    @Query("SELECT * FROM business_records WHERE recordType = :type ORDER BY createdAtEpochMillis DESC LIMIT 300")
    fun observeByType(type: String): Flow<List<BusinessRecordEntity>>
}
