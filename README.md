# Molido Agro AI

اپلیکیشن اندرویدی فارسی برای مدیریت گلخانه و کشاورزی هوشمند، با معماری ترکیبی هوش مصنوعی محلی و ابری.

## وضعیت پروژه

این مخزن تازه ایجاد شده و در حال حاضر زیرساخت اولیه محصول در حال راه‌اندازی است. هیچ مدل تشخیص بیماری، سرویس ابری، یا قابلیت تولیدی تا زمان پیاده‌سازی و آزمون مستقل، فعال یا تأییدشده تلقی نمی‌شود.

## اصول محصول

- اپلیکیشن Native Android با Kotlin و Jetpack Compose
- فارسی و راست‌چین به‌عنوان زبان پیش‌فرض
- ذخیره‌سازی محلی و اولویت آفلاین
- معماری Hybrid AI: مدل محلی + ارائه‌دهنده ابری قابل تعویض
- محصولات خوراکی؛ بدون ماژول گل و گیاه زینتی
- عدم نیاز کاربر به هاست، دامنه، VPS یا کامپیوتر شخصی
- عدم قرار دادن کلیدهای API در APK یا مخزن
- توصیه‌های حساس کشاورزی با تأیید انسانی و منابع معتبر

## محصولات اولیه

خیار، گوجه‌فرنگی، بادمجان، فلفل، توت‌فرنگی، سبزیجات خوراکی و سایر محصولات خوراکی قابل تعریف.

## نسخه‌بندی و انتشار

- سیاست نسخه‌بندی بر اساس Semantic Versioning در [سیاست انتشار پایدار](docs/STABLE_RELEASE_POLICY.md) تعریف شده است.
- نسخه پایه توسعه در `version.properties` نگهداری می‌شود؛ ساخت‌های CI با پسوند `-dev.RUN_NUMBER` مشخص می‌شوند.
- نسخه پایدار فقط از Git Tag با قالب `vMAJOR.MINOR.PATCH` و پس از عبور تمام آزمون‌های اجباری منتشر می‌شود.
- اجرای موفق CI یا ساخت APK به‌تنهایی به معنی آماده‌بودن محصول برای انتشار پایدار نیست.
- آخرین نسخه منتشرشده و رسمی (Latest): [v0.2.7](https://github.com/hidooch980/Molido-Agro-Ai/releases/tag/v0.2.7) — امضاشده با کلید انتشار، دارای `molido-agro-ai.apk` و `latest.json`، و قابل به‌روزرسانی داخل برنامه.
- نسخه‌های 0.x به‌صورت Pre-release منتشر می‌شوند؛ چون مسیر `releases/latest` این نسخه‌ها را شامل نمی‌شود، بررسی به‌روزرسانی داخل برنامه ابتدا همان مسیر و در صورت نبود آن آخرین Tag منتشرشده را از API گیت‌هاب می‌خواند و مانیفست/APK را از `releases/download/<tag>` دریافت می‌کند.

## ساخت

ساخت نسخه Release از طریق GitHub Actions انجام می‌شود. وضعیت واقعی ساخت و آزمون فقط از اجرای موفق workflow و گزارش‌های آن اعلام خواهد شد.

## حریم خصوصی و امنیت

- داده‌های اصلی ابتدا روی دستگاه ذخیره می‌شوند.
- ارسال تصویر یا اطلاعات به سرویس ابری باید شفاف و با رضایت کاربر باشد.
- اسرار و کلیدهای API فقط از طریق سازوکار امن سمت سرور/سرویس مدیریت‌شده نگهداری می‌شوند.
- نسخه پشتیبان باید رمزگذاری و قابل بازیابی باشد.

## مستندات

- [معماری فنی](docs/ARCHITECTURE.md)
- [نقشه راه](docs/ROADMAP.md)
- [مدل داده](docs/DATA_MODEL.md)
- [ایمنی توصیه‌های کشاورزی](docs/AGRICULTURAL_SAFETY.md)
- [وضعیت پیاده‌سازی](docs/IMPLEMENTATION_STATUS.md)
- [قرارداد API همگام‌سازی](docs/SYNC_API_CONTRACT.md)
- [امنیت، همگام‌سازی و آمادگی انتشار](docs/SECURITY_SYNC_RELEASE_READINESS.md)
- [استقرار LAN، TLS و بازیابی](docs/LAN_DEPLOYMENT_AND_RECOVERY.md)
- [CRM و ERP](docs/CRM_ERP.md)

## مجوز

تا زمان انتخاب و ثبت مجوز رسمی، استفاده مجدد و توزیع این مخزن تابع حقوق مالکیت صاحب مخزن است.


## CRM + ERP implementation status
The CRM/ERP foundation is being delivered incrementally. Current backend work includes account-scoped customers, suppliers, products, CRM leads/activities/tickets, draft sales and purchase orders, inventory reservations and fulfilment, harvest-to-inventory posting, double-entry journals, human approval for manual ledger entries, and partial settlements. The Android Persian CRM/ERP tab currently provides encrypted local create-only forms and an HTTPS outbox for customers, suppliers, products, opportunities, tickets, draft orders and harvest records.

Customers, suppliers and products pushed from Android are now projected server-side into the CRM/ERP tables, so offline captures appear in the CRM/ERP APIs. This is still not a complete production CRM/ERP: mobile update/delete and remote pull/conflict resolution, full mobile order/accounting workflows, Iranian statutory accounting/tax, multi-warehouse/lot/quality/costing, and physical-device acceptance tests remain outstanding. See [CRM_ERP.md](docs/CRM_ERP.md) for the detailed scope and limits.