package com.molido.agroai.domain

data class CropDefinition(
    val code: String,
    val persianName: String,
    val category: String
)

object CropCatalog {
    val initialCrops = listOf(
        CropDefinition("cucumber", "خیار", "صیفی‌جات"),
        CropDefinition("tomato", "گوجه‌فرنگی", "صیفی‌جات"),
        CropDefinition("eggplant", "بادمجان", "صیفی‌جات"),
        CropDefinition("pepper", "فلفل", "صیفی‌جات"),
        CropDefinition("strawberry", "توت‌فرنگی", "میوه"),
        CropDefinition("lettuce", "کاهو", "سبزی خوراکی"),
        CropDefinition("herbs", "سبزی‌های خوراکی", "سبزی خوراکی"),
        CropDefinition("melon", "خربزه و طالبی", "صیفی‌جات"),
        CropDefinition("watermelon", "هندوانه", "صیفی‌جات"),
        CropDefinition("zucchini", "کدو", "صیفی‌جات")
    )

    fun find(code: String): CropDefinition? = initialCrops.firstOrNull { it.code == code }
}
