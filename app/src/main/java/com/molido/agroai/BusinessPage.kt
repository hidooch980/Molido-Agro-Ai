package com.molido.agroai

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.BusinessRecordEntity

private val businessTypes = listOf(
    "customer" to "مشتری", "supplier" to "تأمین‌کننده",
    "crm_lead" to "فرصت فروش", "crm_activity" to "پیگیری مشتری",
    "support_ticket" to "درخواست پشتیبانی", "product" to "محصول",
    "sales_order" to "سفارش فروش", "purchase_order" to "سفارش خرید",
    "harvest_batch" to "بچ برداشت", "journal_entry" to "سند حسابداری",
    "settlement" to "تسویه"
)

@Composable
fun BusinessPage(records: List<BusinessRecordEntity>, onSave: (String, String, String, Double) -> Unit) {
    var selectedType by remember { mutableStateOf(businessTypes.first().first) }
    var title by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(false) }
    val selectedLabel = businessTypes.first { it.first == selectedType }.second
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("مدیریت یکپارچه CRM و ERP", style = MaterialTheme.typography.titleLarge)
        Text("ثبت آفلاین فعال است؛ اطلاعات ابتدا روی دستگاه ذخیره و سپس در صف همگام‌سازی قرار می‌گیرد.", style = MaterialTheme.typography.bodySmall)
        Box {
            OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
                Text("نوع رکورد: " + selectedLabel)
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                businessTypes.forEach { pair ->
                    DropdownMenuItem(text = { Text(pair.second) }, onClick = { selectedType = pair.first; expanded = false })
                }
            }
        }
        OutlinedTextField(title, { title = it }, label = { Text("عنوان / نام") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(description, { description = it }, label = { Text("شرح و جزئیات") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
        OutlinedTextField(amount, { amount = it }, label = { Text("مبلغ یا مقدار (اختیاری)") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(
            enabled = title.trim().length >= 2 && (amount.isBlank() || amount.toDoubleOrNull()?.let { it.isFinite() && it >= 0.0 } == true),
            onClick = {
                onSave(selectedType, title.trim(), description.trim(), amount.toDoubleOrNull() ?: 0.0)
                title = ""; description = ""; amount = ""
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("ذخیره محلی و افزودن به صف همگام‌سازی") }
        Text("سوابق ثبت‌شده (" + records.size + ")", style = MaterialTheme.typography.titleMedium)
        if (records.isEmpty()) Text("هنوز رکوردی ثبت نشده است.")
        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
            records.take(100).forEach { item ->
                val label = businessTypes.firstOrNull { it.first == item.recordType }?.second ?: item.recordType
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(label + " • " + item.title, style = MaterialTheme.typography.titleSmall)
                        Text(item.status, style = MaterialTheme.typography.labelSmall)
                        Text(java.text.SimpleDateFormat("yyyy/MM/dd HH:mm", java.util.Locale("fa", "IR")).format(java.util.Date(item.createdAtEpochMillis)), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        Text("توجه: این صفحه در این مرحله، ثبت محلی و صف همگام‌سازی رکوردهای CRM/ERP را فراهم می‌کند. گردش‌های قطعی فروش، رزرو/تحویل، دفترکل و تسویه از APIهای تخصصی سرور استفاده می‌کنند و تکمیل فرم‌ها و اتصال مستقیم UI به آن APIها در حال توسعه است.", style = MaterialTheme.typography.bodySmall)
    }
}
