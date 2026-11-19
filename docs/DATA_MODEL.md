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
