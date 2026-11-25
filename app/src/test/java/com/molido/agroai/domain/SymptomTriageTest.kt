package com.molido.agroai.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SymptomTriageTest {
    @Test
    fun fullPatternClearsTheConfidenceGate() {
        val result = SymptomTriage.triage(
            "cucumber",
            setOf(SymptomSignal.ANGULAR_YELLOW_SPOTS, SymptomSignal.UNDERLEAF_FUZZ)
        )
        assertEquals("cuc-downy-mildew", result.conditionId)
        assertTrue("confidence was ${result.confidence}", result.confidence >= 0.70)
        assertEquals(2, result.matched.size)
    }

    @Test
    fun requiredSymptomAloneIsEnoughForTheGreenhouseCommonCase() {
        val result = SymptomTriage.triage("strawberry", setOf(SymptomSignal.GRAY_MOLD_ON_FRUIT))
        assertEquals("str-gray-mold", result.conditionId)
        assertTrue(result.confidence >= 0.70)
    }

    @Test
    fun partialPatternStaysInconclusive() {
        val result = SymptomTriage.triage("tomato", setOf(SymptomSignal.WILTING))
        assertNull(result.conditionId)
        assertTrue("confidence was ${result.confidence}", result.confidence < 0.70)
    }

    @Test
    fun ambiguousPatternIsRejectedInsteadOfGuessed() {
        val result = SymptomTriage.triage(
            "cucumber",
            setOf(SymptomSignal.ANGULAR_YELLOW_SPOTS, SymptomSignal.WHITE_POWDER)
        )
        assertNull(result.conditionId)
        assertTrue(result.note.contains("مشترک"))
    }

    @Test
    fun emptySelectionAndUnknownCropStayEmpty() {
        val empty = SymptomTriage.triage("tomato", emptySet())
        assertNull(empty.conditionId)
        assertEquals(0.0, empty.confidence, 0.0)
        val unknown = SymptomTriage.triage("banana", setOf(SymptomSignal.WILTING))
        assertNull(unknown.conditionId)
    }

    @Test
    fun everyCatalogDiseaseHasATriageProfile() {
        for (disease in PlantDiseaseCatalog.diseases) {
            val signals = SymptomTriage.symptomsFor(disease.cropCode)
            assertTrue("${disease.cropCode} has no symptoms", signals.isNotEmpty())
            val confident = SymptomTriage.triage(disease.cropCode, signals.toSet())
            assertTrue("${disease.id} matched nothing", confident.matched.isNotEmpty())
        }
    }
}
