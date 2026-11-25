package com.molido.agroai.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualReadingValidationTest {
    @Test
    fun acceptsPlainAsciiNumbers() {
        val result = ManualReadingValidation.parse("24.5", "60")
        assertTrue(result.isValid)
        assertEquals(24.5, result.temperatureC!!, 0.0001)
        assertEquals(60.0, result.humidityPct!!, 0.0001)
    }

    @Test
    fun acceptsPersianDigitsAndDecimalSeparator() {
        val result = ManualReadingValidation.parse("۲۴٫۵", "۶۰")
        assertTrue(result.isValid)
        assertEquals(24.5, result.temperatureC!!, 0.0001)
        assertEquals(60.0, result.humidityPct!!, 0.0001)
    }

    @Test
    fun rejectsOutOfRangeValues() {
        val tooHot = ManualReadingValidation.parse("95", "60")
        assertFalse(tooHot.isValid)
        assertTrue(tooHot.errors.any { it.contains("دما") })
        val badHumidity = ManualReadingValidation.parse("20", "140")
        assertFalse(badHumidity.isValid)
        assertTrue(badHumidity.errors.any { it.contains("رطوبت") })
    }

    @Test
    fun rejectsTextAndEmptyInput() {
        assertFalse(ManualReadingValidation.parse("", "").isValid)
        assertFalse(ManualReadingValidation.parse("گرم", "۶۰").isValid)
        assertNull(ManualReadingValidation.number("  "))
    }

    @Test
    fun boundariesAreInclusive() {
        assertTrue(ManualReadingValidation.parse("-20", "0").isValid)
        assertTrue(ManualReadingValidation.parse("70", "100").isValid)
    }
}
