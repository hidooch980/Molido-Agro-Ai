package com.molido.agroai.data

import kotlinx.coroutines.flow.Flow
import com.molido.agroai.domain.CropCatalog
import java.util.UUID

class CropObservationRepository(
    private val dao: CropObservationDao
) {
    fun observeAll(): Flow<List<CropObservationEntity>> = dao.observeAll()

    fun observeByCrop(cropCode: String): Flow<List<CropObservationEntity>> =
        dao.observeByCrop(cropCode)

    suspend fun record(
        cropCode: String,
        greenhouseId: String? = null,
        growthStage: String,
        temperatureCelsius: Double? = null,
        humidityPercent: Double? = null,
        soilPh: Double? = null,
        soilEc: Double? = null,
        irrigationLiters: Double? = null,
        notes: String = "",
        photoUri: String? = null,
        source: String = "USER"
    ) {
        require(CropCatalog.find(cropCode) != null) { "cropCode is not supported" }
        require(growthStage.isNotBlank()) { "growthStage is required" }
        require(source in setOf("USER", "SENSOR", "IMPORT", "AI_ESTIMATE"))
        require(humidityPercent == null || (humidityPercent.isFinite() && humidityPercent in 0.0..100.0))
        require(soilPh == null || (soilPh.isFinite() && soilPh in 0.0..14.0))
        require(temperatureCelsius == null || (temperatureCelsius.isFinite() && temperatureCelsius in -10.0..60.0))
        require(soilEc == null || (soilEc.isFinite() && soilEc in 0.0..100.0))
        require(irrigationLiters == null || (irrigationLiters.isFinite() && irrigationLiters in 0.0..100000.0))
        require(notes.length <= 4000)

        dao.insert(
            CropObservationEntity(
                id = UUID.randomUUID().toString(),
                cropCode = cropCode,
                greenhouseId = greenhouseId,
                observedAtEpochMillis = System.currentTimeMillis(),
                growthStage = growthStage,
                temperatureCelsius = temperatureCelsius,
                humidityPercent = humidityPercent,
                soilPh = soilPh,
                soilEc = soilEc,
                irrigationLiters = irrigationLiters,
                notes = notes,
                photoUri = photoUri,
                source = source
            )
        )
    }
}
