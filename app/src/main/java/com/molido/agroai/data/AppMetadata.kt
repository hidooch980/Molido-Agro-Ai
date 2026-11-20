package com.molido.agroai.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Upsert
import androidx.room.withTransaction

@Entity(tableName = "app_metadata")
data class AppMetadataEntity(@PrimaryKey val key: String, val value: String)

@Dao
interface AppMetadataDao {
    @Query("SELECT value FROM app_metadata WHERE key = :key LIMIT 1")
    suspend fun value(key: String): String?

    @Upsert
    suspend fun put(item: AppMetadataEntity)
}

suspend fun AgroDatabase.bindToAccount(userId: String) {
    require(userId.isNotBlank() && userId.length <= 128)
    withTransaction {
        val dao = appMetadataDao()
        val bound = dao.value("bound_account_id")
        require(bound == null || bound == userId) {
            "این دستگاه قبلاً به حساب دیگری متصل شده است. برای جلوگیری از افشای داده‌های محلی، تغییر حساب مسدود شد."
        }
        dao.put(AppMetadataEntity("bound_account_id", userId))
    }
}
