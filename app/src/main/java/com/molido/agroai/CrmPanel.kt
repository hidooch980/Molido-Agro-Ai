package com.molido.agroai

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.CrmApi
import com.molido.agroai.data.CropCycleEntity
import com.molido.agroai.data.GreenhouseEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

private val CrmPanelColor = Color(0xFF1B2C23)
private val CrmMuted = Color(0xFFB8C8BE)
private val CrmWarning = Color(0xFFF0C36D)
private val CrmPositive = Color(0xFF9BE0B1)

private val LeadStageLabels = mapOf(
    "NEW" to "جدید",
    "QUALIFIED" to "واجد شرایط",
    "PROPOSAL" to "پیشنهاد",
    "WON" to "برنده",
    "LOST" to "از دست رفته",
)

/**
 * CRM leads/activities and the harvest posting, which is the one place where a field record
 * (harvest) must reach the server directly because it moves ERP stock in the same transaction.
 */
@Composable
fun CrmPanel(
    context: Context,
    greenhouses: List<GreenhouseEntity>,
    cycles: List<CropCycleEntity>,
) {
    val scope = rememberCoroutineScope()
    var leads by remember { mutableStateOf<List<CrmApi.Lead>>(emptyList()) }
    var activities by remember { mutableStateOf<List<CrmApi.Activity>>(emptyList()) }
    var products by remember { mutableStateOf<List<CrmApi.Product>>(emptyList()) }
    var status by remember { mutableStateOf("برای دیدن سرنخ‌ها و ثبت برداشت، به سرور وصل شوید.") }
    var busy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }

    var leadTitle by remember { mutableStateOf("") }
    var leadValue by remember { mutableStateOf("0") }
    var leadNotes by remember { mutableStateOf("") }
    var activitySubject by remember { mutableStateOf("") }
    var activityType by remember { mutableStateOf(CrmApi.activityTypes.first()) }
    var activityLeadId by remember { mutableStateOf<String?>(null) }

    var harvestGreenhouseId by remember { mutableStateOf<String?>(null) }
    var harvestCycleId by remember { mutableStateOf<String?>(null) }
    var harvestProductId by remember { mutableStateOf<String?>(null) }
    var harvestWarehouse by remember { mutableStateOf("WH-1") }
    var harvestQuantity by remember { mutableStateOf("") }
    var harvestPrice by remember { mutableStateOf("0") }

    LaunchedEffect(reload) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            runCatching { Triple(CrmApi.leads(context), CrmApi.activities(context), CrmApi.products(context)) }
        }
        loaded.fold(
            { (queue, activitiesLoaded, productList) ->
                leads = queue
                activities = activitiesLoaded
                products = productList
                status = "${queue.size} سرنخ و ${activitiesLoaded.size} فعالیت روی سرور ثبت است."
            },
            { status = it.message ?: "دریافت اطلاعات CRM ناموفق بود." },
        )
        busy = false
    }

    val greenhouseCycles = cycles.filter { it.greenhouseId == harvestGreenhouseId }

    Card(
        colors = CardDefaults.cardColors(containerColor = CrmPanelColor),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("سرنخ‌ها و برداشت (CRM/ERP)", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(status, color = CrmMuted, style = MaterialTheme.typography.bodySmall)

            Text("سرنخ جدید", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            OutlinedTextField(leadTitle, { leadTitle = it }, label = { Text("عنوان سرنخ") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(leadValue, { leadValue = it }, label = { Text("ارزش برآوردی (ریال)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(leadNotes, { leadNotes = it }, label = { Text("یادداشت") }, modifier = Modifier.fillMaxWidth())
            OutlinedButton(enabled = !busy, onClick = {
                val title = leadTitle.trim()
                val value = leadValue.trim().toDoubleOrNull()
                when {
                    title.length < 2 -> status = "عنوان سرنخ باید حداقل ۲ نویسه باشد."
                    value == null || value < 0 -> status = "ارزش برآوردی باید عددی صفر یا بزرگ‌تر باشد."
                    else -> {
                        busy = true
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                runCatching { CrmApi.createLead(context, title, value, notes = leadNotes) }
                            }
                            status = result.fold(
                                { "سرنخ «${it.title}» ثبت شد." },
                                { it.message ?: "ثبت سرنخ ناموفق بود." },
                            )
                            if (result.isSuccess) {
                                leadTitle = ""
                                leadNotes = ""
                                leadValue = "0"
                            }
                            reload += 1
                        }
                    }
                }
            }) { Text("ثبت سرنخ") }

            if (leads.isNotEmpty()) {
                HorizontalDivider(color = CrmMuted.copy(alpha = 0.3f))
                leads.take(6).forEach { lead ->
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(
                            "${lead.title} • ${formatMoney(lead.estimatedValue)} ${lead.currency}",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            CrmApi.leadStages.forEach { stage ->
                                FilterChip(
                                    selected = lead.stage == stage,
                                    enabled = !busy && lead.stage != stage,
                                    onClick = {
                                        busy = true
                                        scope.launch {
                                            val result = withContext(Dispatchers.IO) {
                                                runCatching { CrmApi.moveLead(context, lead.id, stage) }
                                            }
                                            status = result.fold(
                                                { "مرحله سرنخ به «${LeadStageLabels[stage] ?: stage}» تغییر کرد." },
                                                { it.message ?: "تغییر مرحله ناموفق بود." },
                                            )
                                            reload += 1
                                        }
                                    },
                                    label = { Text(LeadStageLabels[stage] ?: stage, style = MaterialTheme.typography.labelSmall) },
                                )
                            }
                        }
                    }
                }
            }

            HorizontalDivider(color = CrmMuted.copy(alpha = 0.3f))
            Text("فعالیت جدید", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CrmApi.activityTypes.forEach { type ->
                    FilterChip(
                        selected = activityType == type,
                        onClick = { activityType = type },
                        label = { Text(type, style = MaterialTheme.typography.labelSmall) },
                    )
                }
            }
            OutlinedTextField(activitySubject, { activitySubject = it }, label = { Text("موضوع فعالیت") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            if (leads.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    leads.take(4).forEach { lead ->
                        FilterChip(
                            selected = activityLeadId == lead.id,
                            onClick = { activityLeadId = lead.id },
                            label = { Text(lead.title.take(18), style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
            }
            OutlinedButton(enabled = !busy && activityLeadId != null, onClick = {
                val leadId = activityLeadId
                when {
                    activitySubject.trim().length < 2 -> status = "موضوع فعالیت باید حداقل ۲ نویسه باشد."
                    leadId == null -> status = "برای فعالیت، یک سرنخ انتخاب کنید."
                    else -> {
                        busy = true
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                runCatching { CrmApi.createActivity(context, activityType, activitySubject, leadId) }
                            }
                            status = result.fold(
                                { "فعالیت ثبت شد و در وضعیت ${it.state} است." },
                                { it.message ?: "ثبت فعالیت ناموفق بود." },
                            )
                            if (result.isSuccess) activitySubject = ""
                            reload += 1
                        }
                    }
                }
            }) { Text("ثبت فعالیت") }

            if (activities.isNotEmpty()) {
                activities.take(5).forEach { activity ->
                    Text(
                        "${activity.activityType} • ${activity.subject} (${activity.state})",
                        color = CrmMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            HorizontalDivider(color = CrmMuted.copy(alpha = 0.3f))
            Text("ثبت برداشت", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            if (greenhouses.isEmpty()) {
                Text("برای ثبت برداشت، اول یک گلخانه بسازید.", color = CrmWarning, style = MaterialTheme.typography.bodySmall)
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    greenhouses.take(4).forEach { greenhouse ->
                        FilterChip(
                            selected = harvestGreenhouseId == greenhouse.id,
                            onClick = {
                                harvestGreenhouseId = greenhouse.id
                                harvestCycleId = null
                            },
                            label = { Text(greenhouse.name.take(14), style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                if (greenhouseCycles.isNotEmpty()) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        greenhouseCycles.take(4).forEach { cycle ->
                            FilterChip(
                                selected = harvestCycleId == cycle.id,
                                onClick = { harvestCycleId = cycle.id },
                                label = { Text(cycle.cropCode, style = MaterialTheme.typography.labelSmall) },
                            )
                        }
                    }
                } else if (harvestGreenhouseId != null) {
                    Text("این گلخانه دوره کشت فعال ندارد.", color = CrmWarning, style = MaterialTheme.typography.bodySmall)
                }
                if (products.isNotEmpty()) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        products.take(4).forEach { product ->
                            FilterChip(
                                selected = harvestProductId == product.id,
                                onClick = { harvestProductId = product.id },
                                label = { Text(product.sku.take(12), style = MaterialTheme.typography.labelSmall) },
                            )
                        }
                    }
                } else {
                    Text("محصولی در ERP سرور ثبت نشده است؛ ابتدا محصول را از سرور بسازید.", color = CrmWarning, style = MaterialTheme.typography.bodySmall)
                }
                OutlinedTextField(harvestWarehouse, { harvestWarehouse = it }, label = { Text("انبار مقصد") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(harvestQuantity, { harvestQuantity = it }, label = { Text("مقدار") }, singleLine = true, modifier = Modifier.weight(1f))
                    OutlinedTextField(harvestPrice, { harvestPrice = it }, label = { Text("قیمت واحد") }, singleLine = true, modifier = Modifier.weight(1f))
                }
                Button(
                    enabled = !busy,
                    onClick = {
                        val greenhouseId = harvestGreenhouseId
                        val cycleId = harvestCycleId
                        val productId = harvestProductId
                        val quantity = harvestQuantity.trim().toDoubleOrNull()
                        val price = harvestPrice.trim().toDoubleOrNull() ?: 0.0
                        val unit = products.firstOrNull { it.id == productId }?.unit ?: "kg"
                        when {
                            greenhouseId == null -> status = "گلخانه را انتخاب کنید."
                            cycleId == null -> status = "دوره کشت را انتخاب کنید."
                            productId == null -> status = "محصول را انتخاب کنید."
                            harvestWarehouse.isBlank() -> status = "انبار مقصد را وارد کنید."
                            quantity == null || quantity <= 0 -> status = "مقدار برداشت باید بزرگ‌تر از صفر باشد."
                            price < 0 -> status = "قیمت واحد نمی‌تواند منفی باشد."
                            else -> {
                                busy = true
                                scope.launch {
                                    val result = withContext(Dispatchers.IO) {
                                        runCatching {
                                            CrmApi.recordHarvest(
                                                context = context,
                                                greenhouseId = greenhouseId,
                                                cropCycleId = cycleId,
                                                productId = productId,
                                                warehouseId = harvestWarehouse,
                                                quantity = quantity,
                                                unitPrice = price,
                                                unit = unit,
                                                // A retry after a timeout must not book the harvest twice.
                                                idempotencyKey = "harvest-" + UUID.randomUUID(),
                                            )
                                        }
                                    }
                                    status = result.fold(
                                        { "برداشت ${formatMoney(it.quantity)} ${it.unit} ثبت و به موجودی انبار اضافه شد." },
                                        { it.message ?: "ثبت برداشت ناموفق بود." },
                                    )
                                    if (result.isSuccess) harvestQuantity = ""
                                    busy = false
                                }
                            }
                        }
                    },
                ) { Text("ثبت برداشت در انبار") }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(enabled = !busy, onClick = { reload += 1 }) { Text("نوسازی") }
            }
        }
    }
}

private fun formatMoney(value: Double): String =
    if (value == value.toLong().toDouble()) value.toLong().toString() else String.format("%.1f", value)