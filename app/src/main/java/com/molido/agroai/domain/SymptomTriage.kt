package com.molido.agroai.domain

/** Observable symptoms an operator can tick without any lab equipment. */
enum class SymptomSignal(val label: String) {
    ANGULAR_YELLOW_SPOTS("لکه‌های زرد زاویه‌دار محدود به رگبرگ"),
    UNDERLEAF_FUZZ("پوشش خاکستری یا بنفش در پشت برگ"),
    WHITE_POWDER("پودر سفید آردی روی برگ و ساقه"),
    LEAF_DRYING("زردی و خشکی زودهنگام برگ"),
    WATER_SOAKED_LESIONS("لکه‌های آب‌سوخته قهوه‌ای یا سیاه روی برگ"),
    STEM_DARK_LESIONS("زخم تیره روی ساقه"),
    CONCENTRIC_RINGS("لکه‌های قهوه‌ای با حلقه‌های متحدالمرکز"),
    LOWER_LEAVES_YELLOW("زردی برگ‌های پایینی"),
    SUNKEN_FRUIT_LESIONS("لکه‌های فرورفته روی میوه"),
    GRAY_MOLD_ON_FRUIT("کپک خاکستری روی میوه"),
    FRUIT_ROT("پوسیدگی میوه"),
    WILTING("پژمردگی بوته")
}

data class TriageResult(
    val cropCode: String,
    val conditionId: String?,
    val confidence: Double,
    val matched: List<SymptomSignal>,
    val note: String
)

/**
 * Transparent, rule-based triage between the ticked symptoms and the disease catalog.
 *
 * This is deliberately not a machine-learning model: each disease declares the symptoms it
 * always shows (required) and the ones it often shows (optional), and the score is a weighted
 * ratio. Only a full required-symptom match can cross the 0.70 gate that both the catalog and
 * the server use, so an uncertain combination stays "inconclusive" instead of guessing.
 */
object SymptomTriage {
    private const val CONFIDENCE_GATE = 0.70
    private const val AMBIGUITY_MARGIN = 0.02

    private data class Profile(
        val cropCode: String,
        val diseaseId: String,
        val required: Set<SymptomSignal>,
        val optional: Set<SymptomSignal>
    )

    private val profiles = listOf(
        Profile("cucumber", "cuc-downy-mildew", setOf(SymptomSignal.ANGULAR_YELLOW_SPOTS), setOf(SymptomSignal.UNDERLEAF_FUZZ, SymptomSignal.WILTING)),
        Profile("cucumber", "cuc-powdery-mildew", setOf(SymptomSignal.WHITE_POWDER), setOf(SymptomSignal.LEAF_DRYING)),
        Profile("tomato", "tom-late-blight", setOf(SymptomSignal.WATER_SOAKED_LESIONS), setOf(SymptomSignal.STEM_DARK_LESIONS, SymptomSignal.WILTING, SymptomSignal.FRUIT_ROT)),
        Profile("tomato", "tom-early-blight", setOf(SymptomSignal.CONCENTRIC_RINGS), setOf(SymptomSignal.LOWER_LEAVES_YELLOW, SymptomSignal.LEAF_DRYING)),
        Profile("pepper", "pep-anthracnose", setOf(SymptomSignal.SUNKEN_FRUIT_LESIONS), setOf(SymptomSignal.FRUIT_ROT, SymptomSignal.WILTING)),
        Profile("strawberry", "str-gray-mold", setOf(SymptomSignal.GRAY_MOLD_ON_FRUIT), setOf(SymptomSignal.FRUIT_ROT, SymptomSignal.WILTING))
    )

    fun symptomsFor(cropCode: String): List<SymptomSignal> {
        val relevant = profiles.filter { it.cropCode == cropCode }.flatMap { it.required + it.optional }.toSet()
        return SymptomSignal.entries.filter { it in relevant }
    }

    fun triage(cropCode: String, signals: Set<SymptomSignal>): TriageResult {
        val candidates = profiles.filter { it.cropCode == cropCode }
        if (candidates.isEmpty() || signals.isEmpty()) {
            return TriageResult(cropCode, null, 0.0, emptyList(), "نشانه‌ای برای ارزیابی انتخاب نشده است.")
        }
        val scored = candidates.map { profile -> profile to score(profile, signals) }.sortedByDescending { it.second }
        val best = scored.first()
        val second = scored.getOrNull(1)
        val ambiguous = second != null && second.second > 0.0 && best.second - second.second < AMBIGUITY_MARGIN
        val matched = (best.first.required + best.first.optional).filter { it in signals }

        return when {
            ambiguous -> TriageResult(
                cropCode,
                null,
                best.second,
                matched,
                "این ترکیب نشانه‌ها بین چند بیماری مشترک است؛ برای تفکیک، تصویر واضح‌تر یا بررسی آزمایشگاهی لازم است."
            )
            best.second < CONFIDENCE_GATE -> TriageResult(
                cropCode,
                null,
                best.second,
                matched,
                "نشانه‌های انتخاب‌شده الگوی کامل هیچ بیماری شناخته‌شده‌ای را پر نمی‌کنند."
            )
            else -> TriageResult(cropCode, best.first.diseaseId, best.second, matched, "")
        }
    }

    private fun score(profile: Profile, signals: Set<SymptomSignal>): Double {
        val requiredHits = profile.required.count { it in signals }
        val optionalHits = profile.optional.count { it in signals }
        val requiredRatio = requiredHits.toDouble() / profile.required.size
        val optionalRatio = if (profile.optional.isEmpty()) 0.0 else optionalHits.toDouble() / profile.optional.size
        return if (requiredHits == profile.required.size) {
            (0.70 + 0.25 * optionalRatio).coerceAtMost(0.95)
        } else {
            0.45 * requiredRatio + 0.20 * optionalRatio
        }
    }
}
