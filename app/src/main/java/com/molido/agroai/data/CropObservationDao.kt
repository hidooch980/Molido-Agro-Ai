package com.molido.agroai.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface CropObservationDao {
    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(observation: CropObservationEntity)

    @Query("SELECT * FROM crop_observations ORDER BY observedAtEpochMillis DESC")
    fun observeAll(): Flow<List<CropObservationEntity>>

    @Query("SELECT * FROM crop_observations WHERE cropCode = :cropCode ORDER BY observedAtEpochMillis DESC")
    fun observeByCrop(cropCode: String): Flow<List<CropObservationEntity>>

    @Query("SELECT COUNT(*) FROM crop_observations")
    suspend fun count(): Int
}
