package com.molido.agroai.data

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "crop_observations")
data class CropObservationEntity(
    @PrimaryKey val id: String,
    val cropCode: String,
    val greenhouseId: String?,
    val observedAtEpochMillis: Long,
    val growthStage: String,
    val temperatureCelsius: Double?,
    val humidityPercent: Double?,
    val soilPh: Double?,
    val soilEc: Double?,
    val irrigationLiters: Double?,
    val notes: String,
    val photoUri: String?,
    val source: String,
    val syncState: String = "LOCAL_ONLY"
)
