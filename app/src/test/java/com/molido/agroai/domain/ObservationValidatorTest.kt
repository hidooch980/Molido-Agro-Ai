package com.molido.agroai.domain

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ObservationValidatorTest {
    private fun draft(
        temperature: Double? = 24.0,
        humidity: Double? = 60.0,
        ph: Double? = 6.5,
        ec: Double? = 1.2,
        irrigation: Double? = 10.0
    ) = ObservationDraft(
        cropCode = "tomato",
        growthStage = "VEGETATIVE",
        temperatureCelsius = temperature,
        humidityPercent = humidity,
        soilPh = ph,
        soilEc = ec,
        irrigationLiters = irrigation,
        notes = ""
    )

    @Test fun acceptsValidObservation() {
        assertTrue(ObservationValidator.validate(draft()).isValid)
    }

    @Test fun rejectsUnknownCrop() {
        assertFalse(ObservationValidator.validate(draft().copy(cropCode = "ornamental")).isValid)
    }

    @Test fun rejectsNonFiniteMeasurements() {
        assertFalse(ObservationValidator.validate(draft(ec = Double.NaN)).isValid)
        assertFalse(ObservationValidator.validate(draft(irrigation = Double.POSITIVE_INFINITY)).isValid)
        assertFalse(ObservationValidator.validate(draft(temperature = Double.NaN)).isValid)
    }

    @Test fun rejectsOutOfRangeMeasurements() {
        assertFalse(ObservationValidator.validate(draft(humidity = 101.0)).isValid)
        assertFalse(ObservationValidator.validate(draft(ph = 14.1)).isValid)
        assertFalse(ObservationValidator.validate(draft(ec = -0.1)).isValid)
        assertFalse(ObservationValidator.validate(draft(irrigation = -1.0)).isValid)
    }
}
