package com.molido.agroai.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "greenhouses", indices = [Index(value = ["name"], unique = true)])
data class GreenhouseEntity(
    @PrimaryKey val id: String,
    val name: String,
    val areaSquareMeters: Double,
    val location: String,
    val cultivationMethod: String = "SOIL",
    val createdAtEpochMillis: Long = System.currentTimeMillis(),
    val isActive: Boolean = true
)

@Entity(tableName = "crop_cycles", indices = [Index("greenhouseId"), Index("cropCode")])
data class CropCycleEntity(
    @PrimaryKey val id: String,
    val greenhouseId: String,
    val cropCode: String,
    val startDateEpochMillis: Long,
    val expectedHarvestDateEpochMillis: Long?,
    val plantedAreaSquareMeters: Double,
    val plantCount: Int?,
    val status: String = "ACTIVE",
    val notes: String = ""
)

@Entity(tableName = "farm_activities", indices = [Index("greenhouseId"), Index("cropCycleId"), Index("type"), Index("occurredAtEpochMillis")])
data class FarmActivityEntity(
    @PrimaryKey val id: String,
    val greenhouseId: String?,
    val cropCycleId: String?,
    val cropCode: String?,
    val type: String,
    val title: String,
    val quantity: Double?,
    val unit: String?,
    val cost: Double?,
    val occurredAtEpochMillis: Long = System.currentTimeMillis(),
    val notes: String = "",
    val syncState: String = "LOCAL_ONLY"
)

@Entity(tableName = "inventory_items", indices = [Index(value = ["name"], unique = true)])
data class InventoryItemEntity(
    @PrimaryKey val id: String,
    val name: String,
    val category: String,
    val quantity: Double,
    val unit: String,
    val minimumQuantity: Double = 0.0,
    val updatedAtEpochMillis: Long = System.currentTimeMillis()
)

@Entity(tableName = "financial_entries", indices = [Index("occurredAtEpochMillis"), Index("greenhouseId")])
data class FinancialEntryEntity(
    @PrimaryKey val id: String,
    val greenhouseId: String?,
    val type: String,
    val category: String,
    val amount: Double,
    val currency: String = "IRR",
    val occurredAtEpochMillis: Long = System.currentTimeMillis(),
    val description: String = ""
)

@Dao
interface GreenhouseDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(item: GreenhouseEntity)
    @Query("SELECT * FROM greenhouses ORDER BY createdAtEpochMillis DESC") fun observeAll(): Flow<List<GreenhouseEntity>>
    @Query("SELECT COUNT(*) FROM greenhouses WHERE isActive = 1") fun observeActiveCount(): Flow<Int>
    @Query("SELECT * FROM greenhouses WHERE id = :id LIMIT 1") suspend fun find(id: String): GreenhouseEntity?
}

@Dao
interface CropCycleDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(item: CropCycleEntity)
    @Query("SELECT * FROM crop_cycles ORDER BY startDateEpochMillis DESC") fun observeAll(): Flow<List<CropCycleEntity>>
    @Query("SELECT * FROM crop_cycles WHERE greenhouseId = :greenhouseId AND status = 'ACTIVE'") fun observeActiveForGreenhouse(greenhouseId: String): Flow<List<CropCycleEntity>>
}

@Dao
interface FarmActivityDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(item: FarmActivityEntity)
    @Query("SELECT * FROM farm_activities ORDER BY occurredAtEpochMillis DESC LIMIT 300") fun observeRecent(): Flow<List<FarmActivityEntity>>
    @Query("SELECT COUNT(*) FROM farm_activities") fun observeCount(): Flow<Int>
    @Query("SELECT COALESCE(SUM(cost), 0) FROM farm_activities WHERE cost IS NOT NULL") fun observeCosts(): Flow<Double>
}

@Dao
interface InventoryDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(item: InventoryItemEntity)
    @Query("SELECT * FROM inventory_items ORDER BY name COLLATE NOCASE") fun observeAll(): Flow<List<InventoryItemEntity>>
}

@Dao
interface FinanceDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(item: FinancialEntryEntity)
    @Query("SELECT * FROM financial_entries ORDER BY occurredAtEpochMillis DESC LIMIT 300") fun observeAll(): Flow<List<FinancialEntryEntity>>
    @Query("SELECT COALESCE(SUM(CASE WHEN type = 'INCOME' THEN amount ELSE -amount END), 0) FROM financial_entries") fun observeBalance(): Flow<Double>
}
