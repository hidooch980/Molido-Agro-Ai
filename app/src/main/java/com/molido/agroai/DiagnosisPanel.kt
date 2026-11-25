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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.DiseaseDiagnosisApi
import com.molido.agroai.domain.CropCatalog
import com.molido.agroai.domain.DiagnosisReport
import com.molido.agroai.domain.PlantDiseaseCatalog
import com.molido.agroai.domain.SymptomSignal
import com.molido.agroai.domain.SymptomTriage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val DiagnosisPanelColor = Color(0xFF1B2C23)
private val DiagnosisMuted = Color(0xFFB8C8BE)
private val DiagnosisCrops = listOf("cucumber", "tomato", "pepper", "strawberry")

/** Rule-based symptom triage with an optional server-side IPM enrichment. */
@Composable
fun DiagnosisPanel(context: Context) {
    var cropCode by remember { mutableStateOf(DiagnosisCrops.first()) }
    var selected by remember { mutableStateOf(emptySet<SymptomSignal>()) }
    var status by remember { mutableStateOf("نشانه‌های مشاهده‌شده روی بوته را انتخاب کنید.") }
    var report by remember { mutableStateOf<DiagnosisReport?>(null) }
    var advice by remember { mutableStateOf<DiseaseDiagnosisApi.Advice?>(null) }
    var adviceNote by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Card(
        colors = CardDefaults.cardColors(containerColor = DiagnosisPanelColor),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp)
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("تشخیص بیماری بر اساس نشانه‌ها", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, color = Color.White)
            Text(
                "این ارزیابی قاعده‌محور است، نه مدل یادگیری ماشین؛ نتیجه فقط راهنمای مدیریت تلفیقی (IPM) است و جای بررسی کارشناس را نمی‌گیرد.",
                style = MaterialTheme.typography.bodySmall,
                color = DiagnosisMuted
            )
            Text("محصول", color = DiagnosisMuted, style = MaterialTheme.typography.bodySmall)
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for (code in DiagnosisCrops) {
                    val name = CropCatalog.find(code)?.persianName ?: code
                    FilterChip(
                        selected = cropCode == code,
                        onClick = {
                            cropCode = code
                            selected = emptySet()
                            report = null
                            advice = null
                            status = "نشانه‌های مشاهده‌شده روی بوته را انتخاب کنید."
                        },
                        label = { Text(name) },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
            Text("نشانه‌ها", color = DiagnosisMuted, style = MaterialTheme.typography.bodySmall)
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for (symptom in SymptomTriage.symptomsFor(cropCode)) {
                    FilterChip(
                        selected = symptom in selected,
                        onClick = {
                            selected = if (symptom in selected) selected - symptom else selected + symptom
                            report = null
                            advice = null
                        },
                        label = { Text(symptom.label) },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(
                    enabled = !busy && selected.isNotEmpty(),
                    onClick = {
                        busy = true
                        status = "در حال ارزیابی…"
                        scope.launch {
                            val picked = selected
                            val triage = withContext(Dispatchers.Default) { SymptomTriage.triage(cropCode, picked) }
                            report = PlantDiseaseCatalog.evaluate(cropCode, triage.conditionId, triage.confidence)
                            advice = null
                            adviceNote = ""
                            status = if (triage.conditionId == null) {
                                triage.note
                            } else {
                                "ارزیابی محلی انجام شد."
                            }
                            val conditionId = triage.conditionId
                            if (conditionId != null) {
                                if (!DiseaseDiagnosisApi.isSupported(conditionId)) {
                                    adviceNote = "توصیه تکمیلی سرور برای این بیماری موجود نیست؛ توصیه‌های کاتالوگ محلی نمایش داده شد."
                                } else {
                                    val notes = triage.matched.joinToString("، ") { it.label }
                                    advice = DiseaseDiagnosisApi.diagnose(context, cropCode, conditionId, triage.confidence, notes)
                                    if (advice == null) {
                                        adviceNote = "سرور همگام‌سازی در دسترس نیست؛ ارزیابی محلی معتبر است."
                                    }
                                }
                            }
                            busy = false
                        }
                    },
                    modifier = Modifier.weight(1f)
                ) { Text(if (busy) "در حال ارزیابی…" else "تشخیص") }
                OutlinedButton(
                    onClick = {
                        selected = emptySet()
                        report = null
                        advice = null
                        adviceNote = ""
                        status = "انتخاب‌ها پاک شد."
                    }
                    modifier = Modifier.weight(1f)
                ) { Text("پاک کردن") }
            }
            Text(status, color = DiagnosisMuted, style = MaterialTheme.typography.bodySmall)
            val current = report
            if (current != null) {
                Text(current.condition, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color.White)
                Text(
                    "ضریب اطمینان: ${(current.confidence * 100).toInt()}٪" + if (current.isConfident) "" else " (کمتر از حد قابل اتکا)",
                    color = DiagnosisMuted,
                    style = MaterialTheme.typography.bodySmall
                )
                Text(current.symptoms, color = Color.White, style = MaterialTheme.typography.bodySmall)
                for (item in current.culturalRecommendations) Text("• $item", color = Color.White, style = MaterialTheme.typography.bodySmall)
                for (item in current.biologicalRecommendations) Text("• $item", color = Color.White, style = MaterialTheme.typography.bodySmall)
                Text(current.safetyWarning, color = Color(0xFFFFD79A), style = MaterialTheme.typography.bodySmall)
                if (current.requiresExpertReview) {
                    Text("این بیماری در سطح پرخطر است؛ تصمیم نهایی باید با کارشناس گیاه‌پزشکی باشد.", color = Color(0xFFFFD79A), style = MaterialTheme.typography.bodySmall)
                }
            }
            val remote = advice
            if (remote != null) {
                Text("توصیه سرور (${remote.riskLevel})", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color.White)
                val climate = listOfNotNull(
                    remote.temperatureCelsius?.let { "دمای ثبت‌شده: ${it}°C" },
                    remote.humidityPercent?.let { "رطوبت ثبت‌شده: ${it}٪" }
                ).joinToString(" • ")
                if (climate.isNotEmpty()) Text(climate, color = DiagnosisMuted, style = MaterialTheme.typography.bodySmall)
                for (item in remote.culturalControls) Text("• $item", color = Color.White, style = MaterialTheme.typography.bodySmall)
                for (item in remote.biologicalControls) Text("• $item", color = Color.White, style = MaterialTheme.typography.bodySmall)
                if (remote.safetyAdvisory.isNotEmpty()) Text(remote.safetyAdvisory, color = Color(0xFFFFD79A), style = MaterialTheme.typography.bodySmall)
            }
            if (adviceNote.isNotEmpty()) Text(adviceNote, color = DiagnosisMuted, style = MaterialTheme.typography.bodySmall)
        }
    }
}
