package com.molido.agroai

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.*
import com.molido.agroai.domain.CropCatalog
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

private val Forest = Color(0xFF123C2B)
private val Leaf = Color(0xFF45A36D)
private val Panel = Color(0xFF1B2C23)
private val Muted = Color(0xFFB8C8BE)

private enum class Tab(val title: String) { HOME("خانه"), GREENHOUSE("گلخانه"), SENSORS("پایش"), CROP("کشت"), LOG("عملیات"), STOCK("انبار"), MONEY("مالی"), BUSINESS("CRM/ERP") }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Leaf, background = Forest, surface = Panel, onPrimary = Color.White, onBackground = Color.White, onSurface = Color.White)) {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) { AgroApp() }
            }
        }
    }
}

@Composable
private fun AgroApp() {
    val context = LocalContext.current
    val db = remember(context) { AgroDatabaseProvider.get(context) }
    val scope = rememberCoroutineScope()
    var authRevision by remember { mutableIntStateOf(0) }
    var currentUser by remember { mutableStateOf<String?>(null) }
    var boundAccount by remember { mutableStateOf<String?>(null) }
    var accountStateLoaded by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        SyncScheduler.schedule(context)
        BusinessSyncScheduler.enqueue(context)
        // Keystore decryption and the first Room query must never run on the UI thread: on a
        // cold device that combination is slow enough to be flagged as an ANR.
        val loaded = withContext(Dispatchers.IO) {
            SessionStore(context).userId() to db.appMetadataDao().value("bound_account_id")
        }
        currentUser = loaded.first
        boundAccount = loaded.second
        accountStateLoaded = true
    }
    val greenhouses by db.greenhouseDao().observeAll().collectAsState(initial = emptyList())
    val cycles by db.cropCycleDao().observeAll().collectAsState(initial = emptyList())
    val activities by db.farmActivityDao().observeRecent().collectAsState(initial = emptyList())
    val stock by db.inventoryDao().observeAll().collectAsState(initial = emptyList())
    val finance by db.financeDao().observeAll().collectAsState(initial = emptyList())
    val balance by db.financeDao().observeBalance().collectAsState(initial = 0.0)
    val businessRecords by db.businessRecordDao().observeAll().collectAsState(initial = emptyList())
    var tab by remember { mutableStateOf(Tab.HOME) }
    var notice by remember { mutableStateOf("ذخیره‌سازی محلی فعال است؛ برای ثبت اطلاعات نیازی به اینترنت نیست.") }

    Scaffold(containerColor = Forest, bottomBar = {
        NavigationBar(containerColor = Panel) {
            Tab.values().forEach { t ->
                NavigationBarItem(selected = tab == t, onClick = { tab = t }, icon = { Text(tabIcon(t)) }, label = { Text(t.title) })
            }
        }
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState())) {
            Column(Modifier.padding(horizontal = 18.dp, vertical = 10.dp)) {
                Text("مولیدو آگرو", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("مدیریت هوشمند کشاورزی و گلخانه", color = Muted)
                Text(notice, color = Color(0xFF9BE0B1), style = MaterialTheme.typography.bodySmall)
            }
            UpdateCheckerCard()
            AuthPanel(context) {
                authRevision += 1
                scope.launch {
                    currentUser = withContext(Dispatchers.IO) { SessionStore(context).userId() }
                    boundAccount = db.appMetadataDao().value("bound_account_id")
                }
            }
            if (!accountStateLoaded) {
                PanelCard("در حال بررسی وضعیت امنیت حساب...")
            } else if (boundAccount != null && currentUser == null) {
                PanelCard("اطلاعات این دستگاه به حساب دیگری متصل است. برای مشاهده اطلاعات خصوصی، با همان حساب وارد شوید.")
            } else {
                SyncInboxPanel(context, db)
                when (tab) {
                Tab.HOME -> HomePage(greenhouses.size, cycles.count { it.status == "ACTIVE" }, activities.size, stock.size, balance, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE)
                Tab.GREENHOUSE -> GreenhousePage(greenhouses, onSave = { n, a, l ->
                    scope.launch { try { val id = UUID.randomUUID().toString(); val item = GreenhouseEntity(id, n.trim(), a, l.trim()); val payload = JSONObject().put("id", id).put("name", item.name).put("areaSquareMeters", a).put("location", item.location).put("cultivationMethod", item.cultivationMethod).toString(); db.insertAndEnqueue(context, "greenhouse", id, payload) { db.greenhouseDao().insert(item) }; notice = "گلخانه ثبت شد؛ تغییر در صف همگام‌سازی محلی قرار گرفت." } catch (_: Exception) { notice = "ثبت ناموفق؛ نام گلخانه باید یکتا باشد." } }
                }, onUpdate = { item -> scope.launch { try { val payload = JSONObject().put("id", item.id).put("name", item.name).put("areaSquareMeters", item.areaSquareMeters).put("location", item.location).put("cultivationMethod", item.cultivationMethod).put("createdAtEpochMillis", item.createdAtEpochMillis).put("isActive", item.isActive).toString(); db.updateAndEnqueue(context, "greenhouse", item.id, payload) { db.greenhouseDao().upsert(item) }; notice = "گلخانه ویرایش شد." } catch (_: Exception) { notice = "ویرایش گلخانه ناموفق بود." } } }, onDelete = { id -> scope.launch { db.deleteAndEnqueue(context, "greenhouse", id) { db.greenhouseDao().deleteById(id) }; notice = "گلخانه حذف شد." } })
                Tab.SENSORS -> SensorMonitoringPage(greenhouses, SessionStore(context).accessToken())
                Tab.CROP -> CropPage(greenhouses, cycles, onSave = { g, c, a, p, n ->
                    scope.launch { try { val id = UUID.randomUUID().toString(); val item = CropCycleEntity(id, g, c, System.currentTimeMillis(), null, a, p, notes = n); val payload = JSONObject().put("id", id).put("greenhouseId", g).put("cropCode", c).put("plantedAreaSquareMeters", a).put("plantCount", p).put("status", item.status).put("notes", n).put("startDateEpochMillis", item.startDateEpochMillis).toString(); db.insertAndEnqueue(context, "crop_cycle", id, payload) { db.cropCycleDao().insert(item) }; notice = "دوره کشت ثبت شد؛ تغییر در صف همگام‌سازی محلی قرار گرفت." } catch (_: Exception) { notice = "ثبت دوره کشت ناموفق بود." } }
                }, onUpdate = { item -> scope.launch { try { val payload = JSONObject().put("id", item.id).put("greenhouseId", item.greenhouseId).put("cropCode", item.cropCode).put("plantedAreaSquareMeters", item.plantedAreaSquareMeters).put("plantCount", item.plantCount).put("status", item.status).put("notes", item.notes).put("startDateEpochMillis", item.startDateEpochMillis).put("expectedHarvestDateEpochMillis", item.expectedHarvestDateEpochMillis).toString(); db.updateAndEnqueue(context, "crop_cycle", item.id, payload) { db.cropCycleDao().upsert(item) }; notice = "دوره کشت ویرایش شد." } catch (_: Exception) { notice = "ویرایش دوره کشت ناموفق بود." } } }, onDelete = { id -> scope.launch { db.deleteAndEnqueue(context, "crop_cycle", id) { db.cropCycleDao().deleteById(id) }; notice = "دوره کشت حذف شد." } })
                Tab.LOG -> ActivityPage(greenhouses, activities, onSave = { g, c, type, title, qty, unit, cost, notes ->
                    scope.launch { try { val id = UUID.randomUUID().toString(); val item = FarmActivityEntity(id, g, null, c, type, title.trim(), qty, unit, cost, notes = notes); val payload = JSONObject().put("id", id).put("greenhouseId", g).put("cropCode", c).put("type", type).put("title", item.title).put("quantity", qty).put("unit", unit).put("cost", cost).put("occurredAtEpochMillis", item.occurredAtEpochMillis).put("notes", notes).toString(); db.insertAndEnqueue(context, "farm_activity", id, payload) { db.farmActivityDao().insert(item) }; notice = "عملیات ثبت شد؛ تغییر در صف همگام‌سازی محلی قرار گرفت." } catch (_: Exception) { notice = "ثبت عملیات ناموفق بود." } }
                }, onUpdate = { item -> scope.launch { try { val payload = JSONObject().put("id", item.id).put("greenhouseId", item.greenhouseId).put("cropCycleId", item.cropCycleId).put("cropCode", item.cropCode).put("type", item.type).put("title", item.title).put("quantity", item.quantity).put("unit", item.unit).put("cost", item.cost).put("occurredAtEpochMillis", item.occurredAtEpochMillis).put("notes", item.notes).toString(); db.updateAndEnqueue(context, "farm_activity", item.id, payload) { db.farmActivityDao().upsert(item) }; notice = "عملیات ویرایش شد." } catch (_: Exception) { notice = "ویرایش عملیات ناموفق بود." } } }, onDelete = { id -> scope.launch { db.deleteAndEnqueue(context, "farm_activity", id) { db.farmActivityDao().deleteById(id) }; notice = "عملیات حذف شد." } })
                Tab.STOCK -> StockPage(stock, onSave = { n, cat, q, u, min ->
                    scope.launch { try { val id = UUID.randomUUID().toString(); val item = InventoryItemEntity(id, n.trim(), cat, q, u, min); val payload = JSONObject().put("id", id).put("name", item.name).put("category", cat).put("quantity", q).put("unit", u).put("minimumQuantity", min).put("updatedAtEpochMillis", item.updatedAtEpochMillis).toString(); db.insertAndEnqueue(context, "inventory_item", id, payload) { db.inventoryDao().insert(item) }; notice = "قلم انبار ثبت شد؛ تغییر در صف همگام‌سازی محلی قرار گرفت." } catch (_: Exception) { notice = "نام قلم انبار باید یکتا باشد." } }
                }, onUpdate = { item -> scope.launch { try { val payload = JSONObject().put("id", item.id).put("name", item.name).put("category", item.category).put("quantity", item.quantity).put("unit", item.unit).put("minimumQuantity", item.minimumQuantity).put("updatedAtEpochMillis", item.updatedAtEpochMillis).toString(); db.updateAndEnqueue(context, "inventory_item", item.id, payload) { db.inventoryDao().upsert(item) }; notice = "قلم انبار ویرایش شد." } catch (_: Exception) { notice = "ویرایش قلم انبار ناموفق بود." } } }, onDelete = { id -> scope.launch { db.deleteAndEnqueue(context, "inventory_item", id) { db.inventoryDao().deleteById(id) }; notice = "قلم انبار حذف شد." } })
                Tab.BUSINESS -> CrmErpPage(currentUser, businessRecords, onLegacySave = { type, title, description, amount ->
                    scope.launch { try {
                        val id = UUID.randomUUID().toString()
                        val now = System.currentTimeMillis()
                        val payload = JSONObject().put("id", id).put("recordType", type).put("title", title)
                            .put("description", description).put("amount", amount).put("status", "LOCAL_DRAFT")
                            .put("createdAtEpochMillis", now).toString()
                        val item = BusinessRecordEntity(id, type, title, "LOCAL_DRAFT", payload, now)
                        db.insertAndEnqueue(context, type, id, payload) { db.businessRecordDao().insert(item) }
                        notice = "رکورد ذخیره شد و در صف همگام‌سازی قرار گرفت."
                    } catch (_: Exception) { notice = "ذخیره رکورد ناموفق بود؛ اطلاعات را بررسی کنید." } }
                }, onNotice = { notice = it })
                Tab.MONEY -> FinancePage(finance, balance, onSave = { type, cat, amount, desc ->
                    scope.launch { try { val id = UUID.randomUUID().toString(); val item = FinancialEntryEntity(id, null, type, cat, amount, description = desc); val payload = JSONObject().put("id", id).put("type", type).put("category", cat).put("amount", amount).put("currency", item.currency).put("occurredAtEpochMillis", item.occurredAtEpochMillis).put("description", desc).toString(); db.insertAndEnqueue(context, "financial_entry", id, payload) { db.financeDao().insert(item) }; notice = "سند مالی ثبت شد؛ تغییر در صف همگام‌سازی محلی قرار گرفت." } catch (_: Exception) { notice = "ثبت سند مالی ناموفق بود." } }
                }, onUpdate = { item -> scope.launch { try { val payload = JSONObject().put("id", item.id).put("greenhouseId", item.greenhouseId).put("type", item.type).put("category", item.category).put("amount", item.amount).put("currency", item.currency).put("occurredAtEpochMillis", item.occurredAtEpochMillis).put("description", item.description).toString(); db.updateAndEnqueue(context, "financial_entry", item.id, payload) { db.financeDao().upsert(item) }; notice = "سند مالی ویرایش شد." } catch (_: Exception) { notice = "ویرایش سند مالی ناموفق بود." } } }, onDelete = { id -> scope.launch { db.deleteAndEnqueue(context, "financial_entry", id) { db.financeDao().deleteById(id) }; notice = "سند مالی حذف شد." } })
                }
            }
        }
    }
}

@Composable
private fun SyncInboxPanel(context: android.content.Context, db: AgroDatabase) {
    val changes by db.syncInboxDao().observePending().collectAsState(initial = emptyList())
    val scope = rememberCoroutineScope()
    if (changes.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(horizontal = 16.dp)) {
        Text("تغییرات دریافتی و تعارض‌ها (${changes.size})", fontWeight = FontWeight.Bold)
        changes.forEach { change ->
            Card(colors = CardDefaults.cardColors(containerColor = Panel), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("${change.entityType} • ${change.entityId} • نسخه سرور ${change.serverVersion}")
                    Text(if (change.state == "CONFLICT") "تعارض با تغییر محلی" else "نسخه دریافتی آماده بررسی", color = Muted)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { scope.launch { runCatching { SyncConflictResolver(context, db).acceptServerVersion(change) } } }) { Text("پذیرش نسخه سرور") }
                        if (change.state == "CONFLICT") {
                            OutlinedButton(onClick = { scope.launch { runCatching { SyncConflictResolver(context, db).keepLocalVersion(change) } } }) { Text("حفظ نسخه دستگاه") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AuthPanel(context: android.content.Context, onAuthChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    val session = remember(context) { SessionStore(context) }
    var user by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("در حال بررسی وضعیت حساب…") }
    LaunchedEffect(session) {
        status = withContext(Dispatchers.IO) { session.userId() }
            ?.let { "حساب متصل: $it" } ?: "برای همگام‌سازی، وارد حساب شوید یا حساب بسازید."
    }
    var busy by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(horizontal = 16.dp)) {
        Text(status, color = Muted, style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(user, { user = it }, label = { Text("نام کاربری") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(password, { password = it }, label = { Text("گذرواژه (حداقل ۱۲ نویسه)") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy, onClick = {
                when {
                    !user.trim().matches(Regex("[A-Za-z0-9_.-]{3,64}")) -> status = "نام کاربری باید ۳ تا ۶۴ نویسه و شامل حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد."
                    password.length !in 12..256 -> status = "گذرواژه باید حداقل ۱۲ نویسه داشته باشد."
                    else -> {
                busy = true
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) { AuthRepository(context).login(user.trim(), password) }
                        status = "ورود موفق؛ همگام‌سازی زمان‌بندی شد."
                        password = ""
                        onAuthChanged()
                    } catch (e: Exception) { status = e.message ?: "ورود ناموفق بود." }
                    busy = false
                }
                    }
                }
            }) { Text("ورود") }
            OutlinedButton(enabled = !busy, onClick = {
                when {
                    !user.trim().matches(Regex("[A-Za-z0-9_.-]{3,64}")) -> status = "نام کاربری باید ۳ تا ۶۴ نویسه و شامل حروف انگلیسی، عدد، نقطه، خط تیره یا زیرخط باشد."
                    password.length !in 12..256 -> status = "گذرواژه باید حداقل ۱۲ نویسه داشته باشد."
                    else -> {
                busy = true
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) { AuthRepository(context).register(user.trim(), password) }
                        status = "حساب ساخته شد و ورود انجام شد."
                        password = ""
                        onAuthChanged()
                    } catch (e: Exception) { status = e.message ?: "ثبت‌نام ناموفق بود." }
                    busy = false
                }
                    }
                }
            }) { Text("ساخت حساب") }
            if (session.userId() != null) {
                TextButton(onClick = { AuthRepository(context).signOut(); status = "از حساب خارج شدید."; onAuthChanged() }) { Text("خروج") }
            }
        }
    }
}

private fun tabIcon(t: Tab) = when (t) { Tab.HOME -> "⌂"; Tab.GREENHOUSE -> "🏡"; Tab.SENSORS -> "🌡"; Tab.CROP -> "🌱"; Tab.LOG -> "☑"; Tab.STOCK -> "▣"; Tab.MONEY -> "◉"; Tab.BUSINESS -> "CRM" }

@Composable
private fun Page(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(11.dp), content = content)
}

@Composable
private fun Heading(text: String) { Text(text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp)) }

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, onChange, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), singleLine = true)
}

@Composable
private fun PanelCard(text: String) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(14.dp), color = Color.White)
    }
}

@Composable
private fun Metric(title: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(13.dp)) { Text(title, color = Muted, style = MaterialTheme.typography.bodySmall); Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
    }
}

@Composable
private fun HomePage(g: Int, c: Int, a: Int, s: Int, balance: Double, versionName: String, versionCode: Int) {
    Page {
        PanelCard("به مولیدو آگرو خوش آمدید\nاطلاعات مزرعه ابتدا روی دستگاه شما ذخیره می‌شود و بدون اینترنت در دسترس است.")
        Heading("اطلاعات نسخه")
        PanelCard("نسخه برنامه: $versionName\nشماره ساخت: $versionCode\nبه‌روزرسانی: بررسی خودکار هنگام بازشدن برنامه؛ نصب نهایی با تأیید شما")
        Heading("اطلاعات عمومی برنامه")
        PanelCard("مولیدو آگرو؛ سامانه مدیریت کشاورزی و گلخانه برای محصولات خوراکی و زراعی. دامنه محصولات شامل خیار، گوجه‌فرنگی، بادمجان، انواع فلفل، توت‌فرنگی، سبزیجات و سایر محصولات قابل کشت است. گل‌ها و گیاهان زینتی در دامنه محصول قرار ندارند.")
        Heading("نمای کلی")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Metric("گلخانه‌ها", g.toString(), Modifier.weight(1f)); Metric("دوره‌های فعال کشت", c.toString(), Modifier.weight(1f)) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Metric("سوابق عملیات", a.toString(), Modifier.weight(1f)); Metric("اقلام انبار", s.toString(), Modifier.weight(1f)) }
        Metric("تراز مالی ثبت‌شده (ریال)", balance.asMoney(), Modifier.fillMaxWidth())
        Heading("امکانات")
        listOf("مدیریت گلخانه و مساحت", "دوره‌های کشت محصولات خوراکی", "ثبت آبیاری، تغذیه، کنترل آفات و برداشت", "مدیریت انبار نهاده‌ها و حداقل موجودی", "ثبت هزینه‌ها و درآمدها").forEach { PanelCard(it) }
        Text("تشخیص تصویری و توصیه‌های هوشمند تا زمان اتصال مدل معتبر و آزمون میدانی، فعال محسوب نمی‌شوند.", color = Muted, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun GreenhousePage(items: List<GreenhouseEntity>, onSave: (String, Double, String) -> Unit, onUpdate: (GreenhouseEntity) -> Unit, onDelete: (String) -> Unit) {
    var name by remember { mutableStateOf("") }; var area by remember { mutableStateOf("") }; var location by remember { mutableStateOf("") }
    Page {
        Heading("ثبت گلخانه")
        Field("نام گلخانه", name) { name = it }
        Field("مساحت (مترمربع)", area) { area = it }
        Field("موقعیت یا توضیحات", location) { location = it }
        Button(onClick = { onSave(name, area.toDouble(), location); name = ""; area = ""; location = "" }, enabled = name.isNotBlank() && (area.toDoubleOrNull()?.let { it.isFinite() && it in 1000.0..5000.0 } == true), modifier = Modifier.fillMaxWidth()) { Text("ذخیره گلخانه") }
        Heading("گلخانه‌های ثبت‌شده (${items.size})")
        if (items.isEmpty()) PanelCard("هنوز گلخانه‌ای ثبت نشده است.")
        items.forEach { item ->
            var editing by remember(item.id) { mutableStateOf(false) }
            var editName by remember(item.id) { mutableStateOf(item.name) }
            var editArea by remember(item.id) { mutableStateOf(item.areaSquareMeters.toString()) }
            var editLocation by remember(item.id) { mutableStateOf(item.location) }
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PanelCard("${item.name}\nمساحت: ${item.areaSquareMeters.asMoney()} مترمربع\n${item.location}")
                if (editing) {
                    Field("نام گلخانه", editName) { editName = it }
                    Field("مساحت", editArea) { editArea = it }
                    Field("موقعیت", editLocation) { editLocation = it }
                    Button(enabled = editName.isNotBlank() && (editArea.toDoubleOrNull()?.let { it.isFinite() && it in 1000.0..5000.0 } == true), onClick = { onUpdate(item.copy(name = editName.trim(), areaSquareMeters = editArea.toDouble(), location = editLocation.trim())); editing = false }) { Text("ذخیره ویرایش") }
                }
                Row { TextButton(onClick = { editing = !editing }) { Text(if (editing) "بستن ویرایش" else "ویرایش") }; TextButton(onClick = { onDelete(item.id) }) { Text("حذف") } }
            }
        }
    }
}

@Composable
private fun CropPage(greenhouses: List<GreenhouseEntity>, cycles: List<CropCycleEntity>, onSave: (String, String, Double, Int?, String) -> Unit, onUpdate: (CropCycleEntity) -> Unit, onDelete: (String) -> Unit) {
    var greenhouse by remember(greenhouses) { mutableStateOf(greenhouses.firstOrNull()?.id.orEmpty()) }
    var crop by remember { mutableStateOf(CropCatalog.initialCrops.first().code) }
    var area by remember { mutableStateOf("") }; var plants by remember { mutableStateOf("") }; var notes by remember { mutableStateOf("") }
    var gMenu by remember { mutableStateOf(false) }; var cMenu by remember { mutableStateOf(false) }
    Page {
        Heading("ثبت دوره کشت")
        Box {
            TextButton(onClick = { gMenu = true }) { Text(greenhouses.firstOrNull { it.id == greenhouse }?.name ?: "انتخاب گلخانه") }
            DropdownMenu(gMenu, { gMenu = false }) { greenhouses.forEach { item -> DropdownMenuItem(text = { Text(item.name) }, onClick = { greenhouse = item.id; gMenu = false }) } }
        }
        Box {
            TextButton(onClick = { cMenu = true }) { Text(CropCatalog.find(crop)?.persianName ?: "انتخاب محصول") }
            DropdownMenu(cMenu, { cMenu = false }) { CropCatalog.initialCrops.forEach { item -> DropdownMenuItem(text = { Text(item.persianName) }, onClick = { crop = item.code; cMenu = false }) } }
        }
        Field("مساحت زیر کشت (مترمربع)", area) { area = it }
        Field("تعداد بوته (اختیاری)", plants) { plants = it }
        Field("یادداشت", notes) { notes = it }
        Button(onClick = { onSave(greenhouse, crop, area.toDouble(), plants.toIntOrNull(), notes); area = ""; plants = ""; notes = "" }, enabled = greenhouse.isNotBlank() && (area.toDoubleOrNull()?.let { value -> value.isFinite() && value > 0.0 && value <= (greenhouses.firstOrNull { it.id == greenhouse }?.areaSquareMeters ?: 0.0) } == true) && (plants.isBlank() || (plants.toIntOrNull() ?: -1) >= 0), modifier = Modifier.fillMaxWidth()) { Text("ثبت دوره کشت") }
        Heading("دوره‌ها (${cycles.size})")
        if (cycles.isEmpty()) PanelCard("دوره کشتی ثبت نشده است.")
        cycles.forEach { item ->
            var editing by remember(item.id) { mutableStateOf(false) }
            var editArea by remember(item.id) { mutableStateOf(item.plantedAreaSquareMeters.toString()) }
            var editPlants by remember(item.id) { mutableStateOf(item.plantCount?.toString().orEmpty()) }
            var editNotes by remember(item.id) { mutableStateOf(item.notes) }
            val gh = greenhouses.firstOrNull { it.id == item.greenhouseId }?.name ?: "گلخانه نامشخص"
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PanelCard("${CropCatalog.find(item.cropCode)?.persianName ?: item.cropCode} • $gh\n${item.plantedAreaSquareMeters.asMoney()} مترمربع • ${if (item.status == "ACTIVE") "فعال" else item.status}")
                if (editing) {
                    Field("مساحت زیر کشت", editArea) { editArea = it }; Field("تعداد بوته", editPlants) { editPlants = it }; Field("یادداشت", editNotes) { editNotes = it }
                    Button(enabled = editArea.toDoubleOrNull()?.let { it.isFinite() && it > 0 && it <= (greenhouses.firstOrNull { g -> g.id == item.greenhouseId }?.areaSquareMeters ?: 0.0) } == true && (editPlants.isBlank() || (editPlants.toIntOrNull() ?: -1) >= 0), onClick = { onUpdate(item.copy(plantedAreaSquareMeters = editArea.toDouble(), plantCount = editPlants.toIntOrNull(), notes = editNotes)); editing = false }) { Text("ذخیره ویرایش") }
                }
                Row { TextButton(onClick = { editing = !editing }) { Text(if (editing) "بستن ویرایش" else "ویرایش") }; TextButton(onClick = { onDelete(item.id) }) { Text("حذف") } }
            }
        }
    }
}

@Composable
private fun ActivityPage(greenhouses: List<GreenhouseEntity>, items: List<FarmActivityEntity>, onSave: (String?, String?, String, String, Double?, String?, Double?, String) -> Unit, onUpdate: (FarmActivityEntity) -> Unit, onDelete: (String) -> Unit) {
    val types = listOf("IRRIGATION" to "آبیاری", "FERTILIZER" to "کوددهی", "PEST_CONTROL" to "کنترل آفات", "HARVEST" to "برداشت", "OBSERVATION" to "بازدید و پایش", "OTHER" to "سایر")
    var type by remember { mutableStateOf(types.first().first) }; var greenhouse by remember(greenhouses) { mutableStateOf(greenhouses.firstOrNull()?.id.orEmpty()) }
    var title by remember { mutableStateOf("") }; var qty by remember { mutableStateOf("") }; var unit by remember { mutableStateOf("لیتر") }; var cost by remember { mutableStateOf("") }; var notes by remember { mutableStateOf("") }
    var typeMenu by remember { mutableStateOf(false) }; var gMenu by remember { mutableStateOf(false) }
    Page {
        Heading("ثبت عملیات کشاورزی")
        Box {
            TextButton(onClick = { typeMenu = true }) { Text(types.first { it.first == type }.second) }
            DropdownMenu(typeMenu, { typeMenu = false }) { types.forEach { t -> DropdownMenuItem(text = { Text(t.second) }, onClick = { type = t.first; typeMenu = false }) } }
        }
        Box {
            TextButton(onClick = { gMenu = true }) { Text(greenhouses.firstOrNull { it.id == greenhouse }?.name ?: "بدون انتخاب گلخانه") }
            DropdownMenu(gMenu, { gMenu = false }) {
                DropdownMenuItem(text = { Text("بدون انتخاب") }, onClick = { greenhouse = ""; gMenu = false })
                greenhouses.forEach { g -> DropdownMenuItem(text = { Text(g.name) }, onClick = { greenhouse = g.id; gMenu = false }) }
            }
        }
        Field("شرح عملیات", title) { title = it }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Column(Modifier.weight(1f)) { Field("مقدار", qty) { qty = it } }; Column(Modifier.weight(1f)) { Field("واحد", unit) { unit = it } } }
        Field("هزینه (ریال، اختیاری)", cost) { cost = it }
        Field("یادداشت", notes) { notes = it }
        Button(onClick = { onSave(greenhouse.ifBlank { null }, null, type, title, qty.toDoubleOrNull(), unit, cost.toDoubleOrNull(), notes); title = ""; qty = ""; cost = ""; notes = "" }, enabled = title.isNotBlank() && (qty.isBlank() || (qty.toDoubleOrNull()?.let { it.isFinite() && it >= 0.0 } == true)) && (cost.isBlank() || (cost.toDoubleOrNull()?.let { it.isFinite() && it >= 0.0 } == true)), modifier = Modifier.fillMaxWidth()) { Text("ثبت عملیات") }
        Heading("سوابق اخیر")
        if (items.isEmpty()) PanelCard("عملیاتی ثبت نشده است.")
        items.forEach { item ->
            var editing by remember(item.id) { mutableStateOf(false) }
            var editTitle by remember(item.id) { mutableStateOf(item.title) }
            var editQuantity by remember(item.id) { mutableStateOf(item.quantity?.toString().orEmpty()) }
            var editCost by remember(item.id) { mutableStateOf(item.cost?.toString().orEmpty()) }
            var editNotes by remember(item.id) { mutableStateOf(item.notes) }
            val label = types.firstOrNull { it.first == item.type }?.second ?: item.type
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PanelCard("$label • ${item.title}\n${item.quantity?.let { it.asMoney() + " " + (item.unit ?: "") } ?: "بدون مقدار"}${item.cost?.let { " • هزینه ${it.asMoney()} ریال" } ?: ""}\n${item.notes}")
                if (editing) {
                    Field("شرح عملیات", editTitle) { editTitle = it }; Field("مقدار", editQuantity) { editQuantity = it }; Field("هزینه", editCost) { editCost = it }; Field("یادداشت", editNotes) { editNotes = it }
                    Button(enabled = editTitle.isNotBlank() && (editQuantity.isBlank() || editQuantity.toDoubleOrNull()?.let { it.isFinite() && it >= 0 } == true) && (editCost.isBlank() || editCost.toDoubleOrNull()?.let { it.isFinite() && it >= 0 } == true), onClick = { onUpdate(item.copy(title = editTitle.trim(), quantity = editQuantity.toDoubleOrNull(), cost = editCost.toDoubleOrNull(), notes = editNotes)); editing = false }) { Text("ذخیره ویرایش") }
                }
                Row { TextButton(onClick = { editing = !editing }) { Text(if (editing) "بستن ویرایش" else "ویرایش") }; TextButton(onClick = { onDelete(item.id) }) { Text("حذف") } }
            }
        }
    }
}

@Composable
private fun StockPage(items: List<InventoryItemEntity>, onSave: (String, String, Double, String, Double) -> Unit, onUpdate: (InventoryItemEntity) -> Unit, onDelete: (String) -> Unit) {
    var name by remember { mutableStateOf("") }; var category by remember { mutableStateOf("کود و تغذیه") }; var quantity by remember { mutableStateOf("") }; var unit by remember { mutableStateOf("کیلوگرم") }; var minimum by remember { mutableStateOf("0") }
    Page {
        Heading("افزودن نهاده به انبار")
        Field("نام قلم", name) { name = it }; Field("دسته‌بندی", category) { category = it }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Column(Modifier.weight(1f)) { Field("موجودی", quantity) { quantity = it } }; Column(Modifier.weight(1f)) { Field("واحد", unit) { unit = it } } }
        Field("حداقل موجودی هشدار", minimum) { minimum = it }
        Button(onClick = { onSave(name, category, quantity.toDouble(), unit, minimum.toDoubleOrNull() ?: 0.0); name = ""; quantity = "" }, enabled = name.isNotBlank() && (quantity.toDoubleOrNull()?.let { it.isFinite() && it >= 0.0 } == true) && (minimum.toDoubleOrNull()?.let { it.isFinite() && it >= 0.0 } == true), modifier = Modifier.fillMaxWidth()) { Text("ثبت قلم انبار") }
        Heading("موجودی (${items.size})")
        if (items.isEmpty()) PanelCard("انبار خالی است.")
        items.forEach { item ->
            var editing by remember(item.id) { mutableStateOf(false) }
            var editName by remember(item.id) { mutableStateOf(item.name) }
            var editCategory by remember(item.id) { mutableStateOf(item.category) }
            var editQuantity by remember(item.id) { mutableStateOf(item.quantity.toString()) }
            var editMinimum by remember(item.id) { mutableStateOf(item.minimumQuantity.toString()) }
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PanelCard("${item.name} • ${item.quantity.asMoney()} ${item.unit}\n${item.category} • حداقل ${item.minimumQuantity.asMoney()}${if (item.quantity <= item.minimumQuantity) "\nهشدار: موجودی به حداقل رسیده" else ""}")
                if (editing) {
                    Field("نام قلم", editName) { editName = it }; Field("دسته‌بندی", editCategory) { editCategory = it }; Field("موجودی", editQuantity) { editQuantity = it }; Field("حداقل موجودی", editMinimum) { editMinimum = it }
                    Button(enabled = editName.isNotBlank() && editQuantity.toDoubleOrNull()?.let { it.isFinite() && it >= 0 } == true && editMinimum.toDoubleOrNull()?.let { it.isFinite() && it >= 0 } == true, onClick = { onUpdate(item.copy(name = editName.trim(), category = editCategory.trim(), quantity = editQuantity.toDouble(), minimumQuantity = editMinimum.toDouble(), updatedAtEpochMillis = System.currentTimeMillis())); editing = false }) { Text("ذخیره ویرایش") }
                }
                Row { TextButton(onClick = { editing = !editing }) { Text(if (editing) "بستن ویرایش" else "ویرایش") }; TextButton(onClick = { onDelete(item.id) }) { Text("حذف") } }
            }
        }
    }
}

@Composable
private fun FinancePage(items: List<FinancialEntryEntity>, balance: Double, onSave: (String, String, Double, String) -> Unit, onUpdate: (FinancialEntryEntity) -> Unit, onDelete: (String) -> Unit) {
    var type by remember { mutableStateOf("EXPENSE") }; var category by remember { mutableStateOf("نهاده و مواد مصرفی") }; var amount by remember { mutableStateOf("") }; var description by remember { mutableStateOf("") }
    Page {
        Heading("ثبت درآمد و هزینه")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { type = "EXPENSE" }, modifier = Modifier.weight(1f)) { Text(if (type == "EXPENSE") "✓ هزینه" else "هزینه") }
            Button(onClick = { type = "INCOME" }, modifier = Modifier.weight(1f)) { Text(if (type == "INCOME") "✓ درآمد" else "درآمد") }
        }
        Field("دسته‌بندی", category) { category = it }; Field("مبلغ به ریال", amount) { amount = it }; Field("شرح", description) { description = it }
        Button(onClick = { onSave(type, category, amount.toDouble(), description); amount = ""; description = "" }, enabled = amount.toDoubleOrNull()?.let { it.isFinite() && it > 0.0 } == true, modifier = Modifier.fillMaxWidth()) { Text("ثبت سند مالی") }
        Metric("تراز خالص (ریال)", balance.asMoney(), Modifier.fillMaxWidth())
        Heading("اسناد مالی (${items.size})")
        if (items.isEmpty()) PanelCard("سندی ثبت نشده است.")
        items.forEach { item ->
            var editing by remember(item.id) { mutableStateOf(false) }
            var editCategory by remember(item.id) { mutableStateOf(item.category) }
            var editAmount by remember(item.id) { mutableStateOf(item.amount.toString()) }
            var editDescription by remember(item.id) { mutableStateOf(item.description) }
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                PanelCard("${if (item.type == "INCOME") "درآمد" else "هزینه"} • ${item.category}\n${item.amount.asMoney()} ریال\n${item.description}")
                if (editing) {
                    Field("دسته‌بندی", editCategory) { editCategory = it }; Field("مبلغ", editAmount) { editAmount = it }; Field("شرح", editDescription) { editDescription = it }
                    Button(enabled = editCategory.isNotBlank() && editAmount.toDoubleOrNull()?.let { it.isFinite() && it > 0 } == true, onClick = { onUpdate(item.copy(category = editCategory.trim(), amount = editAmount.toDouble(), description = editDescription)); editing = false }) { Text("ذخیره ویرایش") }
                }
                Row { TextButton(onClick = { editing = !editing }) { Text(if (editing) "بستن ویرایش" else "ویرایش") }; TextButton(onClick = { onDelete(item.id) }) { Text("حذف") } }
            }
        }
    }
}

private fun Double.asMoney(): String = String.format(java.util.Locale("fa", "IR"), "%,.0f", this)
