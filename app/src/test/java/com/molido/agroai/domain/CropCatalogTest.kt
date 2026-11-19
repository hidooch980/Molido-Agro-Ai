package com.molido.agroai.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CropCatalogTest {
    @Test fun includesRequiredFoodCrops() {
        listOf("cucumber", "tomato", "eggplant", "pepper", "strawberry", "herbs").forEach {
            assertNotNull("Missing supported crop: $it", CropCatalog.find(it))
        }
    }

    @Test fun excludesOrnamentalPlants() {
        assertNull(CropCatalog.find("ornamental"))
        assertTrue(CropCatalog.initialCrops.none { it.category.contains("زینتی") || it.persianName.contains("گل زینتی") })
    }

    @Test fun cropCodesAreUnique() {
        val codes = CropCatalog.initialCrops.map { it.code }
        assertEquals(codes.size, codes.toSet().size)
    }

    @Test fun rejectsInvalidObservationNumbersAndAcceptsNullMeasurements() {
        val base = ObservationDraft("tomato", "VEGETATIVE", null, null, null, null, null, "")
        assertTrue(ObservationValidator.validate(base).isValid)
        assertFalse(ObservationValidator.validate(base.copy(temperatureCelsius = Double.NaN)).isValid)
        assertFalse(ObservationValidator.validate(base.copy(humidityPercent = Double.POSITIVE_INFINITY)).isValid)
    }
}
