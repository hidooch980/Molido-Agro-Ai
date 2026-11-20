# وضعیت پیاده‌سازی

آخرین وضعیت بر اساس سورس شاخه foundation/android-release-foundation؛ این جدول وضعیت واقعی کد را از برنامه‌ریزی آینده جدا می‌کند.

| قابلیت | وضعیت واقعی |
|---|---|
| مخزن اختصاصی و CI ابری | موجود؛ اجرای نهایی باید موفق شود |
| داشبورد فارسی و RTL | نسخه اولیه موجود |
| صفحه گلخانه و ثبت پایه | CRUD محلی اولیه موجود؛ ویرایش/حذف و تست UI ناقص |
| دوره کشت | ثبت و نمایش اولیه موجود؛ اعتبارسنجی دامنه‌ای بیشتر لازم |
| عملیات کشاورزی | ثبت و نمایش اولیه موجود؛ اتصال به دوره کشت ناقص |
| انبار | ثبت و نمایش اولیه موجود؛ گردش ورود/خروج و ویرایش ناقص |
| مالی | ثبت درآمد/هزینه و تراز اولیه؛ گزارش و کنترل دسترسی ناقص |
| کاتالوگ محصولات خوراکی | فهرست اولیه موجود؛ پوشش همه محصولات هنوز کامل نیست |
| اعتبارسنجی اندازه‌گیری‌ها | منطق و تست واحد اولیه موجود |
| زیرساخت API سنسور دما/رطوبت | ثبت قرائت، تاریخچه، آستانه و وضعیت؛ جداسازی حساب، idempotency و اعتبارسنجی در تست‌ها؛ صفحه Android وضعیت و نمودار ۴۸ قرائت اخیر اضافه شده؛ CI تغییر UI در حال اجراست |
| اتصال ChirpStack | نگاشت DevEUI به گلخانه، uplink با HMAC/timestamp/nonce و پل MQTT با TLS اضافه شده؛ تست‌های جدید نوشته شده و CI در انتظار نتیجه؛ broker/gateway واقعی متصل نیست |
| استقرار LAN/TLS/بازیابی | طرح reverse proxy، TLS داخلی، مدیریت secrets و رویه backup/restore مستند شده؛ در محیط واقعی deploy یا restore آزمایشی نشده |
| صف outbox همگام‌سازی | عملیات CREATE پنج بخش متصل؛ CREATE/UPDATE/DELETE در UI هر پنج بخش به outbox تراکنشی متصل شده‌اند؛ حذف به‌صورت tombstone نسخه‌دار ارسال می‌شود |
| همگام‌سازی شبکه‌ای | Worker و API خودمیزبان اولیه، احراز هویت، push و inbox دریافت تغییرات و حل تعارض انتخابی پیاده شده؛ pull خودکار به رکوردها اعمال نمی‌شود و هنوز production-ready نیست |
| احراز هویت و جداسازی چندکاربره | API حساب‌محور و توکن رمزگذاری‌شده؛ دیتابیس محلی به یک حساب bind می‌شود و تعویض حساب مسدود است؛ نقش‌ها و مالکیت per-row کامل نیست |
| رمزگذاری | رمزگذاری AES-GCM برای نشست و payload صف/سرور؛ دیتابیس محلی کامل رمزگذاری نشده |
| CameraX و ثبت تصویر | وابستگی‌ها موجود؛ گردش‌کار محصولی پیاده‌سازی نشده |
| تشخیص بیماری/آفت با AI | پیاده‌سازی نشده؛ هیچ تشخیص واقعی فعال نیست |
| مدل محلی و سرویس AI ابری | پیاده‌سازی نشده |
| به‌روزرسانی APK | پایه بررسی manifest و دانلود وجود دارد؛ نیازمند تست شبکه/نصب واقعی |
| APK امضاشده CI | برای اجرای 44685744976، apksigner موفق و گواهی با SHA-256 ثبت‌شده؛ این artifact مربوط به Commit 53eb94ce است، نه تغییرات بعدی؛ تست نصب واقعی باقی است |
| تست واحد | آزمون‌های اولیه اعتبارسنجی و retry اضافه شده؛ منتظر CI موفق |
| تست UI و دستگاه واقعی | انجام نشده |

## وضعیت همگام‌سازی
صف محلی به‌تنهایی همگام‌سازی محسوب نمی‌شود. تا زمان پیاده‌سازی Worker، مقصد API، احراز هویت، رمزگذاری payload، حل تعارض و آزمون چنددستگاهی، وضعیت همگام‌سازی «غیرفعال/در حال توسعه» است.

## محدودیت انتشار
موفقیت build یا تولید APK unsigned به معنی انتشار قابل نصب به‌عنوان به‌روزرسانی نیست. انتشار فقط پس از تأیید کلید ثابت، امضای APK، fingerprint، SHA-256 و آزمون نصب/ارتقا مجاز است.


## پایش سنسورها
زیرساخت API اولیه برای ثبت و تاریخچه دما/رطوبت هر گلخانه و آستانه‌های هشدار اضافه شده است. این به معنی نمایش زنده در اپ یا اتصال سنسور نیست؛ رابط Android، provision امن gateway، اتصال LAN و آزمون با سخت‌افزار واقعی هنوز باقی است. جزئیات در `docs/GREENHOUSE_SENSOR_MONITORING.md` آمده است.


## CRM + ERP (شاخه feature/crm-erp-foundation)
| قابلیت | وضعیت واقعی |
|---|---|
| CRM مشتریان | API ایجاد/فهرست، احراز هویت و جداسازی حساب اضافه شده؛ رابط Android و فعالیت‌ها/فرصت‌ها/پیگیری هنوز نیست |
| تأمین‌کنندگان | API ایجاد/فهرست حساب‌محور اضافه شده |
| کاتالوگ محصولات | API ایجاد/فهرست با SKU یکتا در هر حساب اضافه شده |
| انبار | رسید، حواله و تعدیل با idempotency و جلوگیری از موجودی منفی اضافه شده؛ رزرو، بچ/لات و انبارگردانی کامل باقی است |
| سفارش فروش و خرید | ایجاد سفارش DRAFT و اعتبارسنجی ارتباطات حسابی و محاسبه جمع خطوط اضافه شده؛ تأیید، تحویل، دریافت و چرخه کامل وضعیت باقی است |
| مالی | ثبت سند PENDING_APPROVAL اضافه شده؛ دفترکل، تأیید، تسویه، مالیات و گزارش حسابداری پیاده‌سازی نشده‌اند |
| گزارش مدیریتی | شمارنده‌های اولیه CRM/ERP اضافه شده |
| اتصال تولید گلخانه به سفارش/انبار/هزینه | هنوز پیاده‌سازی نشده |
| Android/Room و outbox برای CRM/ERP | هنوز پیاده‌سازی نشده |
| آزمون CRM/ERP | آزمون‌های API نوشته شده‌اند؛ تا اجرای موفق CI تأییدشده محسوب نمی‌شوند |


## CRM + ERP expansion (2026-11-20)
| Scope | Implemented in source | Verification still required |
|---|---|---|
| Persian Android CRM/ERP | New CRM/ERP navigation tab, generic offline-first entry form/history, Room v7 business_records table, encrypted outbox enqueue | Android CI for this head, real-device UX, specialized forms |
| CRM | Customer/supplier foundation, lead pipeline stages, activities/follow-up timestamps, support tickets/status | Full search/edit/delete, role permissions, complete customer lifecycle |
| Orders | Draft sales/purchase orders; confirm/fulfil/cancel state machine; sales stock reservation and fulfil consumption; purchase fulfil receipt | Multi-warehouse selection, concurrency stress, full returns/refunds and approvals |
| Finance | Chart-of-accounts seed, balanced double-entry journal validation, pending approval, server-side approval token, posted-only report | RBAC/two-person approval, decimal-safe accounting, Iran statutory rules, tax, bank reconciliation |
| Harvest | API records harvest batches linked to synchronized greenhouse/crop-cycle records and increases stock | Android harvest form/API integration, batch/lot traceability and cost-of-production |
| Settlement | Records partial settlements and prevents amount above order total | Reconciliation, automatic ledger posting, refunds and idempotency |
| Sync | Generic entity types added to authenticated encrypted sync record store; Android local records enqueue encrypted outbox operations | Domain materialization adapters, remote-to-Room application for every new entity, conflict and replay stress tests |
| Security/concurrency/recovery | Account scoping and write locks added to key inventory/order/ledger paths; tests added for account isolation, approval gate and concurrent sales reservation oversell prevention | Full penetration/security review, parallel load test, backup/restore with expanded schema, real LAN and phone acceptance |

This expansion is source-code work under review. It is not a deployed or production-ready CRM/ERP release.
