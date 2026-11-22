package com.molido.agroai.domain

import org.junit.Assert.*
import org.junit.Test

class PlantDiseaseCatalogTest {

    @Test
    fun foodCropsHaveConfiguredDiseases() {
        val crops = listOf("cucumber", "tomato", "pepper", "strawberry")
        crops.forEach { crop ->
            val diseases = PlantDiseaseCatalog.findByCrop(crop)
            assertTrue("Expected diseases configured for crop: $crop", diseases.isNotEmpty())
        }
    }

    @Test
    fun highConfidenceYieldsValidReportWithIPMControls() {
        val report = PlantDiseaseCatalog.evaluate(
            cropCode = "cucumber",
            detectedConditionId = "cuc-downy-mildew",
            confidence = 0.88
        )

        assertTrue(report.isConfident)
        assertEquals("سفیدک داخلی (دروغی) خیار", report.condition)
        assertTrue(report.culturalRecommendations.isNotEmpty())
        assertTrue(report.biologicalRecommendations.isNotEmpty())
        assertTrue(report.safetyWarning.contains("کارنس"))
        assertTrue("High risk disease must require expert review", report.requiresExpertReview)
    }

    @Test
    fun lowConfidenceRequiresExpertReviewAndBlocksChemicalAdvice() {
        val report = PlantDiseaseCatalog.evaluate(
            cropCode = "cucumber",
            detectedConditionId = "cuc-downy-mildew",
            confidence = 0.52
        )

        assertFalse(report.isConfident)
        assertTrue(report.requiresExpertReview)
        assertTrue(report.safetyWarning.contains("پایین بودن ضریب اطمینان"))
        assertTrue(report.biologicalRecommendations.isEmpty())
    }

    @Test
    fun unknownDiseaseFallsBackSafely() {
        val report = PlantDiseaseCatalog.evaluate(
            cropCode = "tomato",
            detectedConditionId = "unknown-fungus",
            confidence = 0.95
        )

        assertFalse(report.isConfident)
        assertTrue(report.requiresExpertReview)
    }

    @Test
    fun allConfiguredDiseasesHaveIranianLanguageDetails() {
        PlantDiseaseCatalog.diseases.forEach { disease ->
            assertFalse(disease.persianName.isBlank())
            assertFalse(disease.symptoms.isBlank())
            assertFalse(disease.safetyNotice.isBlank())
            assertTrue(disease.culturalControls.isNotEmpty())
        }
    }
}
