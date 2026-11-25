package com.molido.agroai.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(
    tableName = "business_local_records",
    indices = [Index(value = ["accountId", "entityType", "createdAtEpochMillis"])]
)
data class BusinessLocalRecord(
    @PrimaryKey val id: String,
    val accountId: String,
    val entityType: String,
    val entityId: String,
    val encryptedPayload: String,
    val syncState: String = "PENDING",
    val createdAtEpochMillis: Long = System.currentTimeMillis()
)

@Dao
interface BusinessLocalDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(record: BusinessLocalRecord)

    @Query("SELECT * FROM business_local_records WHERE accountId = :accountId ORDER BY createdAtEpochMillis DESC")
    fun observe(accountId: String): Flow<List<BusinessLocalRecord>>

    @Query("SELECT * FROM business_local_records WHERE accountId = :accountId AND syncState = 'PENDING' ORDER BY createdAtEpochMillis LIMIT :limit")
    suspend fun pending(accountId: String, limit: Int): List<BusinessLocalRecord>

    @Query("UPDATE business_local_records SET syncState = :state WHERE id = :id")
    suspend fun setState(id: String, state: String)

    @Query("SELECT COUNT(*) FROM business_local_records WHERE accountId = :accountId AND syncState = 'PENDING'")
    fun pendingCount(accountId: String): Flow<Int>

    @Query("SELECT COUNT(*) FROM business_local_records WHERE accountId = :accountId AND syncState = 'PENDING'")
    suspend fun countPending(accountId: String): Int
}

@Database(entities = [BusinessLocalRecord::class], version = 1, exportSchema = false)
abstract class BusinessLocalDatabase : RoomDatabase() {
    abstract fun businessDao(): BusinessLocalDao
}

object BusinessLocalStore {
    @Volatile private var instance: BusinessLocalDatabase? = null
    fun get(context: Context): BusinessLocalDatabase = instance ?: synchronized(this) {
        instance ?: Room.databaseBuilder(
            context.applicationContext,
            BusinessLocalDatabase::class.java,
            "molido-business-local.db"
        ).openHelperFactory(DatabaseEncryption.factory(context))
            .build().also { instance = it }
    }
}
