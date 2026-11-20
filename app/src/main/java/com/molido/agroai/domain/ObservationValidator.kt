package com.molido.agroai.domain

data class ObservationDraft(
    val cropCode: String,
    val growthStage: String,
    val temperatureCelsius: Double?,
    val humidityPercent: Double?,
    val soilPh: Double?,
    val soilEc: Double?,
    val irrigationLiters: Double?,
    val notes: String
)

data class ValidationResult(val errors: List<String>) {
    val isValid: Boolean get() = errors.isEmpty()
}

object ObservationValidator {
    fun validate(draft: ObservationDraft): ValidationResult {
        val errors = mutableListOf<String>()
        if (CropCatalog.find(draft.cropCode) == null) errors += "محصول انتخاب‌شده معتبر نیست."
        if (draft.growthStage.isBlank()) errors += "مرحله رشد را مشخص کنید."
        draft.temperatureCelsius?.let {
            if (!it.isFinite() || it !in -10.0..60.0) errors += "دمای ثبت‌شده خارج از محدوده قابل قبول است."
        }
        draft.humidityPercent?.let {
            if (!it.isFinite() || it !in 0.0..100.0) errors += "رطوبت باید بین صفر تا صد درصد باشد."
        }
        draft.soilPh?.let {
            if (!it.isFinite() || it !in 0.0..14.0) errors += "pH باید بین صفر تا ۱۴ باشد."
        }
        draft.soilEc?.let {
            if (!it.isFinite() || it !in 0.0..100.0) errors += "EC باید عددی معتبر و در محدوده قابل قبول باشد."
        }
        draft.irrigationLiters?.let {
            if (!it.isFinite() || it !in 0.0..100000.0) errors += "حجم آبیاری نامعتبر است."
        }
        if (draft.notes.length > 4000) errors += "یادداشت بیش از حد طولانی است."
        return ValidationResult(errors)
    }
}
