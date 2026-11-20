package com.molido.agroai

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.BusinessLocalRecord
import com.molido.agroai.data.BusinessLocalStore
import com.molido.agroai.data.BusinessSyncScheduler
import com.molido.agroai.data.SyncPayloadCipher
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.collect
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

private val businessKinds = listOf(
    "CUSTOMER" to "مشتری",
    "PRODUCT" to "محصول",
    "OPPORTUNITY" to "فرصت فروش",
    "TICKET" to "درخواست پشتیبانی",
    "SALES_ORDER" to "سفارش فروش"
)

@Composable
fun CrmErpPage(accountId: String?, onNotice: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var selected by remember { mutableStateOf("CUSTOMER") }
    var records by remember { mutableStateOf(emptyList<BusinessLocalRecord>()) }
    var name by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var unit by remember { mutableStateOf("kg") }
    var customerId by remember { mutableStateOf("") }
    var productId by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    var quantity by remember { mutableStateOf("1") }
    var price by remember { mutableStateOf("0") }

    LaunchedEffect(accountId) {
        records = emptyList()
        if (!accountId.isNullOrBlank()) {
            BusinessLocalStore.get(context).businessDao().observe(accountId).collect { records = it }
        }
    }

    fun persist(type: String, payload: JSONObject) {
        val uid = accountId
        if (uid.isNullOrBlank()) {
            onNotice("برای ثبت اطلاعات CRM و ERP ابتدا وارد حساب کاربری شوید.")
            return
        }
        scope.launch {
            runCatching {
                val entityId = UUID.randomUUID().toString()
                val dao = BusinessLocalStore.get(context).businessDao()
                dao.put(BusinessLocalRecord(
                    id = UUID.randomUUID().toString(),
                    accountId = uid,
                    entityType = type,
                    entityId = entityId,
                    encryptedPayload = SyncPayloadCipher.encrypt(context, payload.put("id", entityId).toString())
                ))
                BusinessSyncScheduler.enqueue(context)
            }.onSuccess {
                onNotice("اطلاعات به‌صورت محلی و رمزگذاری‌شده ذخیره شد؛ همگام‌سازی در صف قرار گرفت.")
                name = ""; phone = ""; subject = ""; description = ""
            }.onFailure {
                onNotice("ذخیره اطلاعات ناموفق بود: " + (it.message ?: "خطای نامشخص"))
            }
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("مدیریت مشتری و کسب‌وکار", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("ثبت آفلاین با رمزگذاری محلی؛ ارسال خودکار پس از اتصال امن به سرور", style = MaterialTheme.typography.bodySmall)
        if (accountId.isNullOrBlank()) {
            Card(shape = RoundedCornerShape(14.dp)) {
                Text("برای نگهداری اطلاعات خصوصی، ابتدا وارد حساب شوید.", modifier = Modifier.padding(16.dp))
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("در انتظار همگام‌سازی: " + records.count { it.syncState == "PENDING" }, style = MaterialTheme.typography.labelLarge)
                Text("•", color = MaterialTheme.colorScheme.primary)
                Text("تعارض: " + records.count { it.syncState == "CONFLICT" }, style = MaterialTheme.typography.labelLarge)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                businessKinds.forEach { (key, title) ->
                    FilterChip(selected = selected == key, onClick = { selected = key }, label = { Text(title) })
                }
            }
            when (selected) {
                "CUSTOMER" -> {
                    OutlinedTextField(name, { name = it }, label = { Text("نام مشتری") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(phone, { phone = it }, label = { Text("شماره تماس") }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = {
                        if (name.trim().length < 2) onNotice("نام مشتری را وارد کنید.")
                        else persist("customer", JSONObject().put("name", name.trim()).put("phone", phone.trim()))
                    }, modifier = Modifier.fillMaxWidth()) { Text("ثبت مشتری") }
                }
                "PRODUCT" -> {
                    OutlinedTextField(name, { name = it }, label = { Text("نام محصول / کالا") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(unit, { unit = it }, label = { Text("واحد (مثلاً kg)") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(price, { price = it }, label = { Text("قیمت فروش") }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = {
                        val value = price.toDoubleOrNull()
                        if (name.trim().length < 2 || value == null || value < 0) onNotice("نام و قیمت معتبر محصول را وارد کنید.")
                        else persist("product", JSONObject().put("sku", "LOCAL-" + UUID.randomUUID().toString().take(8)).put("name", name.trim()).put("unit", unit).put("salePrice", value).put("purchasePrice", 0))
                    }, modifier = Modifier.fillMaxWidth()) { Text("ثبت محصول") }
                }
                "OPPORTUNITY" -> {
                    OutlinedTextField(customerId, { customerId = it }, label = { Text("شناسه مشتری") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(subject, { subject = it }, label = { Text("عنوان فرصت فروش") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(price, { price = it }, label = { Text("ارزش پیش‌بینی‌شده") }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = {
                        val value = price.toDoubleOrNull()
                        if (customerId.isBlank() || subject.trim().length < 2 || value == null || value < 0) onNotice("شناسه مشتری، عنوان و ارزش معتبر لازم است.")
                        else persist("opportunity", JSONObject().put("customerId", customerId.trim()).put("title", subject.trim()).put("stage", "LEAD").put("expectedValue", value))
                    }, modifier = Modifier.fillMaxWidth()) { Text("ثبت فرصت فروش") }
                }
                "TICKET" -> {
                    OutlinedTextField(customerId, { customerId = it }, label = { Text("شناسه مشتری") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(subject, { subject = it }, label = { Text("موضوع درخواست") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(description, { description = it }, label = { Text("شرح درخواست") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
                    Button(onClick = {
                        if (customerId.isBlank() || subject.trim().length < 2 || description.trim().length < 2) onNotice("اطلاعات درخواست پشتیبانی کامل نیست.")
                        else persist("support_ticket", JSONObject().put("customerId", customerId.trim()).put("subject", subject.trim()).put("description", description.trim()).put("priority", "NORMAL").put("status", "OPEN"))
                    }, modifier = Modifier.fillMaxWidth()) { Text("ثبت درخواست پشتیبانی") }
                }
                "SALES_ORDER" -> {
                    OutlinedTextField(customerId, { customerId = it }, label = { Text("شناسه مشتری") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(productId, { productId = it }, label = { Text("شناسه محصول") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(quantity, { quantity = it }, label = { Text("مقدار") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(price, { price = it }, label = { Text("قیمت واحد") }, modifier = Modifier.fillMaxWidth())
                    Button(onClick = {
                        val q = quantity.toDoubleOrNull(); val p = price.toDoubleOrNull()
                        if (customerId.isBlank() || productId.isBlank() || q == null || q <= 0 || p == null || p < 0) onNotice("شناسه مشتری، محصول، مقدار و قیمت را بررسی کنید.")
                        else persist("sales_order", JSONObject().put("partyId", customerId.trim()).put("status", "DRAFT").put("lines", JSONArray().put(JSONObject().put("productId", productId.trim()).put("quantity", q).put("unitPrice", p))))
                    }, modifier = Modifier.fillMaxWidth()) { Text("ثبت پیش‌نویس سفارش فروش") }
                }
            }
            Divider()
            Text("سوابق ثبت‌شده روی این دستگاه", fontWeight = FontWeight.Bold)
            records.take(30).forEach { record ->
                val data = runCatching { JSONObject(SyncPayloadCipher.decrypt(record.encryptedPayload)) }.getOrNull()
                Card(shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(businessKinds.firstOrNull { it.first == record.entityType.uppercase() }?.second ?: record.entityType, fontWeight = FontWeight.SemiBold)
                        Text(data?.optString("name").takeUnless { it.isNullOrBlank() } ?: data?.optString("title").takeUnless { it.isNullOrBlank() } ?: data?.optString("subject").takeUnless { it.isNullOrBlank() } ?: record.entityId)
                        Text("شناسه: " + record.entityId, style = MaterialTheme.typography.labelSmall)
                        Text("وضعیت همگام‌سازی: " + when (record.syncState) { "SYNCED" -> "ارسال‌شده"; "CONFLICT" -> "نیازمند بررسی تعارض"; else -> "در صف ارسال" }, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}
