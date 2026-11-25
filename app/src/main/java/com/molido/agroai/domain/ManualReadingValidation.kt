package com.molido.agroai.domain

/**
 * Validation for a reading an operator types in by hand, when no gateway is installed yet.
 *
 * The field is Persian, so the parser accepts Persian and Arabic-Indic digits and the
 * decimal separator "٫"; the range limits mirror the server contract (-20..70 °C, 0..100 %).
 */
object ManualReadingValidation {
    const val MIN_TEMPERATURE_C = -20.0
    const val MAX_TEMPERATURE_C = 70.0
    const val MIN_HUMIDITY_PCT = 0.0
    const val MAX_HUMIDITY_PCT = 100.0

    data class Result(
        val temperatureC: Double?,
        val humidityPct: Double?,
        val errors: List<String>
    ) {
        val isValid: Boolean get() = errors.isEmpty() && temperatureC != null && humidityPct != null
    }

    fun parse(temperatureRaw: String, humidityRaw: String): Result {
        val errors = ArrayList<String>()
        val temperature = number(temperatureRaw)
        val humidity = number(humidityRaw)
        when {
            temperature == null -> errors.add("دمای واردشده عدد معتبری نیست.")
            temperature !in MIN_TEMPERATURE_C..MAX_TEMPERATURE_C ->
                errors.add("دما باید بین ${MIN_TEMPERATURE_C.toInt()} و ${MAX_TEMPERATURE_C.toInt()} درجه باشد.")
        }
        when {
            humidity == null -> errors.add("رطوبت واردشده عدد معتبری نیست.")
            humidity !in MIN_HUMIDITY_PCT..MAX_HUMIDITY_PCT -> errors.add("رطوبت باید بین ۰ و ۱۰۰ درصد باشد.")
        }
        return Result(temperature, humidity, errors)
    }

    /** Accepts "24", "24.5", "۲۴٫۵" and trims spaces; returns null for anything else. */
    fun number(raw: String): Double? {
        val normalized = buildString {
            for (character in raw.trim()) {
                when {
                    character in '0'..'9' -> append(character)
                    character in '۰'..'۹' -> append('0' + (character - '۰'))
                    character in '٠'..'٩' -> append('0' + (character - '٠'))
                    character == '٫' || character == '،' || character == ',' || character == '/' -> append('.')
                    else -> append(character)
                }
            }
        }
        if (normalized.isEmpty()) return null
        return normalized.toDoubleOrNull()
    }
}
