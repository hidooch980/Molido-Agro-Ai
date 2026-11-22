package com.molido.agroai.domain

/**
 * Plant disease definitions, symptoms, IPM (Integrated Pest Management) controls,
 * and safety advisories for supported greenhouse food crops in Iran.
 */
data class DiseaseInfo(
    val id: String,
    val cropCode: String,
    val persianName: String,
    val scientificName: String,
    val symptoms: String,
    val culturalControls: List<String>,
    val biologicalControls: List<String>,
    val safetyNotice: String,
    val riskLevel: RiskLevel = RiskLevel.MEDIUM
)

enum class RiskLevel {
    LOW,
    MEDIUM,
    HIGH
}

data class DiagnosisReport(
    val cropCode: String,
    val condition: String,
    val confidence: Double,
    val isConfident: Boolean,
    val symptoms: String,
    val culturalRecommendations: List<String>,
    val biologicalRecommendations: List<String>,
    val safetyWarning: String,
    val requiresExpertReview: Boolean,
    val evaluatedAtEpochMillis: Long = System.currentTimeMillis()
)

object PlantDiseaseCatalog {
    val diseases = listOf(
        // Cucumber
        DiseaseInfo(
            id = "cuc-downy-mildew",
            cropCode = "cucumber",
            persianName = "سفیدک داخلی (دروغی) خیار",
            scientificName = "Pseudoperonospora cubensis",
            symptoms = "لکه‌های زرد زاویه‌دار در سطح بالایی برگ که با رگبرگ‌ها محدود شده و در سطح زیرین پوشش خاکستری تا بنفش تشکیل می‌شود.",
            culturalControls = listOf(
                "کاهش رطوبت نسبی گلخانه به زیر ۸۰٪ از طریق تهویه مناسب",
                "اجتناب از آبیاری بارانی یا پاشش آب روی برگ‌ها در ساعات عصر",
                "هرس برگ‌های مسن و آلوده کف بوته و خروج ایمن از گلخانه"
            ),
            biologicalControls = listOf(
                "استفاده از فرمولاسیون‌های بر پایه باسیلوس سوبتیلیس (Bacillus subtilis)",
                "محلول‌پاشی ترکیبات فسفیت پتاسیم جهت القای مقاومت سیستمیک"
            ),
            safetyNotice = "استفاده از قارچ‌کش‌های شیمیایی فقط با نسخه کارشناس گیاه‌پزشکی و رعایت دوره کارنس (PHI) مجاز است.",
            riskLevel = RiskLevel.HIGH
        ),
        DiseaseInfo(
            id = "cuc-powdery-mildew",
            cropCode = "cucumber",
            persianName = "سفیدک سطحی (پودری) خیار",
            scientificName = "Podosphaera xanthii",
            symptoms = "پوشش سفید پودری شکل مانند آرد روی هر دو سطح برگ و ساقه‌ها که باعث زردی و خشکی زودهنگام برگ‌ها می‌شود.",
            culturalControls = listOf(
                "تنظیم تراکم بوته‌ها جهت گردش هوای مناسب بین ردیف‌ها",
                "مدیریت تغذیه و جلوگیری از مصرف بیش از حد کودهای ازته",
                "نوردهی کافی و حذف علف‌های هرز میزبان در اطراف گلخانه"
            ),
            biologicalControls = listOf(
                "کاربرد ترکیبات گوگردی میکرونیزه طبق استاندارد با دمای زیر ۲۸ درجه سانتی‌گراد",
                "عصاره گیاهی روغن چریش (Neem oil)"
            ),
            safetyNotice = "از محلول‌پاشی گوگرد در ساعات گرم روز خودداری فرمایید تا از گیاه‌سوزی جلوگیری شود.",
            riskLevel = RiskLevel.MEDIUM
        ),

        // Tomato
        DiseaseInfo(
            id = "tom-late-blight",
            cropCode = "tomato",
            persianName = "بادزدگی (سوختگی دیرهنگام) گوجه‌فرنگی",
            scientificName = "Phytophthora infestans",
            symptoms = "لکه‌های قهوه‌ای آبسوخته روی برگ و ساقه و پوسیدگی سفت و چرمی با لکه‌های قهوه‌ای روی میوه‌ها.",
            culturalControls = listOf(
                "کنترل جدی رطوبت هوای گلخانه با گرمادهی و تهویه متناوب",
                "ضدعفونی ابزار هرس پس از کار روی هر ردیف",
                "معدوم‌سازی سریع بقایای گیاهی آلوده در کیسه‌های دربسته"
            ),
            biologicalControls = listOf(
                "ترکیبات تریکودرما (Trichoderma harzianum) در بستر کشت",
                "محلول‌های القاگر ایمنی حاوی مس کلاته در دوز پیشگیرانه"
            ),
            safetyNotice = "خسارت بادزدگی در صورت عدم مهار سریع بسیار بالاست؛ فوراً به کلینیک گیاه‌پزشکی مراجعه فرمایید.",
            riskLevel = RiskLevel.HIGH
        ),
        DiseaseInfo(
            id = "tom-early-blight",
            cropCode = "tomato",
            persianName = "سوختگی زودهنگام (آلترناریا) گوجه‌فرنگی",
            scientificName = "Alternaria solani",
            symptoms = "لکه‌های دوایر متحدالمرکز (طرح هدف تیراندازی) به رنگ قهوه‌ای تیره روی برگ‌های پایینی بوته.",
            culturalControls = listOf(
                "جلوگیری از استرس کم‌آبی و تقویت بوته با کودهای پتاسیمی",
                "حذف برگ‌های پایین بوته تا ارتفاع ۳۰ سانتی‌متری از سطح خاک",
                "استفاده از پوشش مالچ برای جلوگیری از ترشح ذرات خاک به برگ‌ها"
            ),
            biologicalControls = listOf(
                "میکروارگانیسم‌های آنتاگونیست زیستی ثبت‌شده"
            ),
            safetyNotice = "هرگونه سم‌پاشی باید با رعایت دوره ماندگاری سم و ثبت در دفترچه عملیات گلخانه همراه باشد.",
            riskLevel = RiskLevel.MEDIUM
        ),

        // Pepper
        DiseaseInfo(
            id = "pep-anthracnose",
            cropCode = "pepper",
            persianName = "آنتراکنوز فلفل",
            scientificName = "Colletotrichum spp.",
            symptoms = "لکه‌های فرورفته دایره‌ای روی میوه همراه با توده‌های ژلاتینی اسپور در شرایط مرطوب.",
            culturalControls = listOf(
                "استفاده از بذور سالم و ضدعفونی‌شده",
                "مدیریت رطوبت نسبی و اجتناب از خیس ماندن سطح میوه‌ها",
                "جمع‌آوری و امحای میوه‌های لکه‌دار از بوته"
            ),
            biologicalControls = listOf(
                "بیوپپتیدها و قارچ‌کش‌های زیستی مجاز ارگانیک"
            ),
            safetyNotice = "مصرف سموم شیمیایی برای میوه‌های آماده برداشت اکیداً مشروط به رعایت دوره کارنس زیر ۳ روز است.",
            riskLevel = RiskLevel.HIGH
        ),

        // Strawberry
        DiseaseInfo(
            id = "str-gray-mold",
            cropCode = "strawberry",
            persianName = "کپک خاکستری توت‌فرنگی (بوتریتیس)",
            scientificName = "Botrytis cinerea",
            symptoms = "پوشش نمدی خاکستری رنگ روی گلبرگ‌ها و میوه‌های رسیده، نرم‌شدگی و لهیدگی بافت میوه.",
            culturalControls = listOf(
                "چینش مرتب و به موقع میوه‌های رسیده بدون باقی گذاشتن روی بوته",
                "کاهش رطوبت محیطی گلخانه و تهویه مداوم در ساعات تاریکی",
                "استفاده از پوشش مناسب در بستر کشت هیدروپونیک برای عدم تماس میوه با رطوبت"
            ),
            biologicalControls = listOf(
                "کاربرد قارچ کش زیستی حاوی کلونوستاکیس (Clonostachys rosea)",
                "استفاده از زنبورهای ناقل قارچ زیستی در صورت امکان"
            ),
            safetyNotice = "توت‌فرنگی محصولی با مصرف تازه است؛ ترجیح اول مدیریت غیرشیمیایی و زیستی است.",
            riskLevel = RiskLevel.HIGH
        )
    )

    fun findByCrop(cropCode: String): List<DiseaseInfo> = diseases.filter { it.cropCode == cropCode }

    fun evaluate(cropCode: String, detectedConditionId: String?, confidence: Double): DiagnosisReport {
        val minConfidenceThreshold = 0.70
        val disease = diseases.firstOrNull { it.id == detectedConditionId && it.cropCode == cropCode }

        if (disease == null || confidence < minConfidenceThreshold) {
            return DiagnosisReport(
                cropCode = cropCode,
                condition = disease?.persianName ?: "تشخیص نامشخص یا اطمینان ناکافی",
                confidence = confidence,
                isConfident = false,
                symptoms = disease?.symptoms ?: "علائم به صورت قطعی منطبق بر کاتالوگ بیماری‌های رایج نبود.",
                culturalRecommendations = listOf(
                    "تصویربرداری مجدد با نور طبیعی و تمرکز دقیق روی محل آسیب‌دیده",
                    "بررسی وضعیت رطوبت و دمای گلخانه در ۴۸ ساعت گذشته",
                    "ارسال نمونه به کلینیک گیاه‌پزشکی مورد تأیید جهاد کشاورزی"
                ),
                biologicalRecommendations = emptyList(),
                safetyWarning = "با توجه به پایین بودن ضریب اطمینان مدل (${(confidence * 100).toInt()}٪)، اتخاذ تصمیمات سم‌پاشی مجاز نیست.",
                requiresExpertReview = true
            )
        }

        return DiagnosisReport(
            cropCode = cropCode,
            condition = disease.persianName,
            confidence = confidence,
            isConfident = true,
            symptoms = disease.symptoms,
            culturalRecommendations = disease.culturalControls,
            biologicalRecommendations = disease.biologicalControls,
            safetyWarning = disease.safetyNotice,
            requiresExpertReview = disease.riskLevel == RiskLevel.HIGH
        )
    }
}
