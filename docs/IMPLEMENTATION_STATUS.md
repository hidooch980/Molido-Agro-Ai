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
| سنسور دما/رطوبت | ثبت قرائت، تاریخچه، آستانه و وضعیت سمت سرور؛ صفحه Android وضعیت، نمودار ۴۸ قرائت اخیر و **ثبت قرائت دستی** (منبع MANUAL با idempotency) فعال است؛ ورودی فارسی/عربی-هندی و جداکننده اعشار «٫» پذیرفته و بازه‌ها اعتبارسنجی می‌شوند (۵ آزمون واحد) |
| اتصال ChirpStack | نگاشت DevEUI به گلخانه، uplink با HMAC/timestamp/nonce و پل MQTT با TLS اضافه شده؛ تست‌های جدید نوشته شده و CI در انتظار نتیجه؛ broker/gateway واقعی متصل نیست |
| استقرار LAN/TLS/بازیابی | طرح reverse proxy، TLS داخلی، مدیریت secrets و رویه backup/restore مستند شده؛ در محیط واقعی deploy یا restore آزمایشی نشده |
| صف outbox همگام‌سازی | عملیات CREATE پنج بخش متصل؛ CREATE/UPDATE/DELETE در UI هر پنج بخش به outbox تراکنشی متصل شده‌اند؛ حذف به‌صورت tombstone نسخه‌دار ارسال می‌شود |
| همگام‌سازی شبکه‌ای | Worker و API خودمیزبان، احراز هویت، push دسته‌ای (تا ۵۰ عملیات با سقف بایت)، اعمال pull در Room (پنج نوع کشاورزی + رکوردهای عمومی CRM/ERP)، ذخیره serverVersion در inbox و حل تعارض انتخابی؛ کارت تعارض اکنون برچسب خوانا (نام رکورد) دارد و ردیف متعارض پس از تصمیم بازنشسته می‌شود؛ تعویض حساب با پاک‌سازی کنترل‌شده پیاده شد (پیش‌نمایش تعداد عملیات همگام‌نشده، تأیید دومرحله‌ای، لغو workerها، پاک‌سازی ردیف‌ها و آزادسازی اتصال دستگاه) |
| ثبت‌نام و آدرس سرور | اپ به‌طور پیش‌فرض هیچ سروری ندارد؛ پیش‌تر ثبت‌نام همیشه با «آدرس سرور تنظیم نشده است» شکست می‌خورد. اکنون پنل «اتصال به سرور» آدرس را اعتبارسنجی (https، یا http فقط برای loopback) و ذخیره می‌کند و ثبت‌نام/ورود، workerهای همگام‌سازی و صفحه سنسورها از همان آدرس استفاده می‌کنند؛ بدون سرور، داده‌ها محلی می‌مانند و دکمه «شروع بدون سرور» یک پروفایل محلی بدون توکن می‌سازد (workerها با توکن null بی‌کار می‌مانند)
| احراز هویت و جداسازی چندکاربره | API حساب‌محور و توکن رمزگذاری‌شده؛ خروج/ابطال و چرخش توکن؛ قفل حساب و محدودیت نرخ؛ نقش‌های OWNER/OPERATOR/ACCOUNTANT با API مدیریت حساب (MOLIDO_ADMIN_TOKEN) و گیت نقش روی تأییدهای مالی؛ تعویض حساب در اپ ممکن است (با پاک‌سازی کامل داده محلی و تأیید صریح)؛ مالکیت per-row و چند حساب هم‌زمان روی یک دستگاه پشتیبانی نمی‌شود |
| سخت‌سازی و پایش سرور | لاگ دسترسی JSON، قفل ورود با Retry-After، محدودیت نرخ per-IP (ذخیره در جدول rate_limits تا بین چند worker مشترک باشد) با پشتیبانی اختیاری X-Forwarded-For، سقف اندازه بدنه (413)، ابطال توکن و endpoint /metrics با شمارنده‌ها و گیت اختیاری توکن |
| پل صف آفلاین به CRM/ERP | مشتری، تأمین‌کننده و محصولِ ارسال‌شده با /v1/sync/push در business_parties و business_products آینه می‌شوند و در APIهای CRM/ERP دیده می‌شوند؛ SKU تکراری push را خراب نمی‌کند؛ سایر موجودیت‌ها همچنان فقط در انبار رکورد عمومی هستند |
| رمزگذاری | AES-GCM برای نشست، payload صف/سرور و فایل پشتیبان؛ **دیتابیس‌های محلی تازه با SQLCipher رمزگذاری می‌شوند** (کلید ۳۲ بایتی تصادفی، پیچیده‌شده با کلید Keystore). دیتابیس‌های قدیمیِ plaintext به‌صورت خودکار و ایمن تبدیل می‌شوند: ردیف‌ها به یک کپی رمزگذاری‌شده منتقل، با `PRAGMA integrity_check` و شمارش ردیف هر جدول بررسی، و تنها پس از موفقیت جای‌گزینی می‌شوند؛ فایل اصلی به‌عنوان `<name>.plaintext-backup` نگه داشته می‌شود و هر خطا نسخه اصلی را دست‌نخورده باقی می‌گذارد (پنج آزمون ابزارداری رمزگذاری/مهاجرت) |
| پشتیبان‌گیری محلی | snapshot JSON از همه جدول‌های Room، رمزگذاری AES-GCM با کلید Keystore، بازیابی تراکنشی از طریق فایل‌گزین سیستم (بدون نوشتن در حافظه مشترک) و دو آزمون ابزارداری؛ آزمون ارتقای نسخه با فایل واقعی باقی است |
| Schema دیتابیس | `exportSchema=true` و `app/schemas/.../7.json` کامیت شده تا تغییر جدول بدون migration در بازبینی دیده شود |
| CameraX و ثبت تصویر | وابستگی‌ها موجود؛ گردش‌کار محصولی پیاده‌سازی نشده |
| تشخیص بیماری/آفت | **ارزیابی قاعده‌محور نشانه‌ها فعال است** (۶ بیماری، ۴ محصول): نشانه‌ها روی بوته انتخاب می‌شوند، الگوی کامل الزامی هر بیماری با آستانه اطمینان ۰٫۷۰ تطبیق داده می‌شود، ترکیب مبهم رد و به کارشناس ارجاع می‌شود و توصیه محلی کاتالوگ نمایش داده می‌شود؛ اگر سرور در دسترس باشد توصیه IPM و هشدار اقلیمی از `/v1/ai/diagnose/disease` هم گرفته می‌شود (۶ آزمون واحد) |
| مدل یادگیری ماشین/بینایی | پیاده‌سازی نشده؛ بدون مدل آموزش‌دیده و داده برچسب‌دار، تشخیص تصویری ارائه نمی‌شود |
| سرویس AI ابری | سمت سرور موجود است؛ کلاینت آن را فقط به‌عنوان تکمیل‌کننده ارزیابی محلی صدا می‌زند |
| به‌روزرسانی APK | پایه بررسی manifest و دانلود وجود دارد؛ نیازمند تست شبکه/نصب واقعی |
| APK امضاشده CI | برای اجرای 44685744976، apksigner موفق و گواهی با SHA-256 ثبت‌شده؛ این artifact مربوط به Commit 53eb94ce است، نه تغییرات بعدی؛ تست نصب واقعی باقی است |
| تست واحد | ۱۱۴ آزمون سرور (شامل ابطال/چرخش توکن، قفل ورود، محدودیت نرخ، نقش‌ها، متریک‌ها، سقف بدنه و پل صف به CRM/ERP) محلی موفق؛ CI ابری سبز و ۱۳ آزمون ابزارداری Android (شامل تعارض، پشتیبان‌گیری و آدرس سرور) روی امولاتور موفق |
| تست UI و دستگاه واقعی | انجام نشده |

## وضعیت همگام‌سازی
مسیر رفت‌وبرگشت پیاده شده است: عملیات محلی رمزگذاری‌شده در صف می‌مانند، Worker آن‌ها را دسته‌ای به سرور می‌فرستد و تغییرات سرور با نسخه‌دار بودن در Room اعمال می‌شوند؛ تعارض‌ها برای بازبینی کاربر ذخیره می‌شوند. با این حال چون آزمون Android و اجرای چنددستگاهی واقعی انجام نشده، وضعیت «در حال توسعه» است و فعال‌سازی پیش‌فرض همگام‌سازی توصیه نمی‌شود.

## محدودیت انتشار
موفقیت build یا تولید APK unsigned به معنی انتشار قابل نصب به‌عنوان به‌روزرسانی نیست. انتشار فقط پس از تأیید کلید ثابت، امضای APK، fingerprint، SHA-256 و آزمون نصب/ارتقا مجاز است.


## پایش سنسورها
سرور قرائت دما/رطوبت هر گلخانه، تاریخچه، آستانه و وضعیت را ارائه می‌دهد و اپ علاوه بر مشاهده، قرائت دستی را با منبع `MANUAL` ثبت می‌کند؛ بنابراین حتی بدون گیت‌وی، نمودار و هشدارهای اقلیمی داده واقعی دارند. اتصال خودکار گیت‌وی (provision امن دستگاه، ChirpStack/LAN) و آزمون با سخت‌افزار واقعی هنوز پیاده نشده است. جزئیات در `docs/GREENHOUSE_SENSOR_MONITORING.md` آمده است.


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
| Sync | Authenticated encrypted batch push (≤50 ops / 500 KB per request) and cursor pull; every entity type is projected into Room (farm tables or `business_records`); conflicts are parked as `CONFLICT`/`PENDING_REVIEW` instead of being dropped | Conflict review UI, replay/clock-skew stress tests, multi-device acceptance |
| Security/concurrency/recovery | Account scoping and write locks added to key inventory/order/ledger paths; tests added for account isolation, approval gate and concurrent sales reservation oversell prevention | Full penetration/security review, parallel load test, backup/restore with expanded schema, real LAN and phone acceptance |

This expansion is source-code work under review. It is not a deployed or production-ready CRM/ERP release.

## این دور: سخت‌سازی احراز هویت و اتصال صف به داده تجاری

| تغییر | جزئیات | تأیید |
|---|---|---|
| ابطال و چرخش توکن | هر توکن jti یکتا دارد؛ POST /v1/auth/logout آن را باطل و POST /v1/auth/refresh توکن جدید صادر و توکن قبلی را بازنشسته می‌کند | server/test_auth_hardening.py |
| قفل ورود | پس از ۵ تلاش ناموفق، حساب ۱۵ دقیقه قفل و پاسخ ۴۲۹ با Retry-After برمی‌گردد؛ ورود موفق شمارنده را پاک می‌کند | همان فایل آزمون |
| محدودیت نرخ | پنجره ثابت per-IP برای register و login؛ مقادیر با متغیرهای محیطی قابل تنظیم؛ X-Forwarded-For فقط با MOLIDO_TRUST_PROXY_HEADERS=1 معتبر است | test_auth_hardening.py، test_request_guards.py |
| سقف اندازه درخواست | بدنه بزرگ‌تر از MOLIDO_MAX_REQUEST_BYTES (پیش‌فرض ۱ مگابایت) پیش از رسیدن به endpoint با ۴۱۳ رد می‌شود | test_request_guards.py |
| لاگ دسترسی | هر درخواست یک خط JSON با method/path/status/durationMs؛ بدون داده حساس | بازبینی کد |
| پل صف آفلاین | مشتری/تأمین‌کننده/محصول از صف عمومی به جدول‌های CRM/ERP تصویر می‌شوند؛ خطا هرگز push را rollback نمی‌کند | server/test_sync_materializer.py |
| اعتماد TLS در اندروید | network_security_config.xml: نسخه release فقط CA سیستمی و بدون cleartext؛ نسخه debug می‌تواند CA نصب‌شده کاربر را برای LAN بپذیرد | بازبینی پیکربندی؛ آزمون روی دستگاه لازم است |

هنوز باز است: اعمال pull در Room، ذخیره نسخه سرور هر رکورد، ارسال دسته‌ای عملیات، بازیابی حساب، نقش‌ها و آزمون دستگاه واقعی.

