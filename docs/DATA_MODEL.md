# مدل داده اولیه

موجودیت‌های دامنه که به‌تدریج در Room پیاده می‌شوند:

- Farm: واحد مزرعه یا محل تولید
- Greenhouse: گلخانه وابسته به مزرعه
- GreenhouseSection: سالن یا بخش کشت
- Crop: محصول خوراکی
- CropVariety: رقم محصول
- CropCycle: دوره کشت با تاریخ شروع و پایان
- PlantHealthRecord: مشاهده سلامت گیاه
- DiagnosisRecord: نتیجه تشخیص با مدل، نسخه و اطمینان
- PestObservation: مشاهده آفت و شمارش
- TreatmentRecord: اقدام انجام‌شده و نتیجه پیگیری
- SoilTest / WaterTest: نتایج آزمایش
- FertilizerPlan: برنامه تغذیه
- IrrigationRecord: عملیات آبیاری
- Task / Employee: وظایف و کارکنان
- InventoryItem / InventoryTransaction: اقلام و گردش انبار
- HarvestRecord: برداشت، کیفیت و ضایعات
- FinancialTransaction: هزینه و درآمد
- WeatherSnapshot: داده هواشناسی با منبع و زمان
- SyncOperation: صف همگام‌سازی و وضعیت آن

## قواعد
- همه شناسه‌ها پایدار و یکتا هستند.
- زمان‌ها در UTC ذخیره و در رابط محلی نمایش داده می‌شوند.
- مقادیر اندازه‌گیری همراه واحد ثبت می‌شوند.
- حذف سوابق حساس باید قابل ردیابی باشد.
- تغییر ساختار با migration نسخه‌دار انجام می‌شود.

## مدل سمت سرور (SQLite)

| جدول | نقش |
|---|---|
| `users` | حساب‌ها با salt و hash رمز (scrypt) |
| `records` | آخرین نسخه هر موجودیت هر حساب با payload رمزگذاری‌شده AES-GCM و tombstone حذف |
| `change_log` | تاریخچه تغییرات برای pull افزایشی با cursor |
| `operations` | idempotency کلیدهای push و hash درخواست |
| `revoked_tokens` | jti توکن‌های باطل‌شده تا زمان انقضا |
| `login_failures` | شمارنده تلاش ناموفق و زمان پایان قفل هر نام کاربری |
| `business_parties` / `business_products` | تصویر رمزگذاری‌شده مشتری/تأمین‌کننده/محصول برای APIهای CRM/ERP (پل صف آفلاین) |
| `inventory_balances` / `inventory_movements` | موجودی و گردش انبار با idempotency |
| `business_orders` / `finance_entries` / `business_audit_log` | سفارش‌ها، اسناد مالی و ردپای عملیات تجاری |

`records` همچنان منبع حقیقت همگام‌سازی است؛ جدول‌های `business_*` فقط برای خواندن گزارش‌ها و APIهای CRM/ERP نگه داشته می‌شوند و هرگز جای رمزنگاری payload را نمی‌گیرند.

