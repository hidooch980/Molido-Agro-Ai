package com.molido.agroai

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.GreenhouseEntity
import com.molido.agroai.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private data class GreenhouseSensorStatus(
    val greenhouseId: String,
    val state: String,
    val temperature: Double? = null,
    val humidity: Double? = null,
    val measuredAt: Long? = null,
    val alerts: List<String> = emptyList(),
    val error: String? = null
)

@Composable
fun SensorMonitoringPage(greenhouses: List<GreenhouseEntity>, token: String?) {
    var statuses by remember { mutableStateOf<Map<String, GreenhouseSensorStatus>>(emptyMap()) }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("برای مشاهده داده‌های سنسورها، حساب کاربری و سرور را متصل کنید.") }
    val scope = rememberCoroutineScope()
    val base = BuildConfig.SYNC_BASE_URL.trim().trimEnd('/')

    fun refresh() {
        if (token.isNullOrBlank()) {
            message = "برای مشاهده پایش سنسورها ابتدا وارد حساب شوید."
            return
        }
        if (!base.startsWith("https://")) {
            message = "آدرس HTTPS سرور محلی در تنظیمات نسخه برنامه تعریف نشده است."
            return
        }
        loading = true
        message = "در حال دریافت وضعیت سنسورها..."
        scope.launch {
            val results = withContext(Dispatchers.IO) {
                greenhouses.associate { greenhouse ->
                    greenhouse.id to runCatching { fetchGreenhouseSensorStatus(base, token, greenhouse.id) }
                        .getOrElse { GreenhouseSensorStatus(greenhouse.id, "ERROR", error = it.message ?: "خطای ارتباط") }
                }
            }
            statuses = results
            val errors = results.values.count { it.state == "ERROR" }
            message = if (errors == 0) "وضعیت ${results.size} گلخانه به‌روزرسانی شد." else "دریافت اطلاعات $errors گلخانه ناموفق بود؛ اتصال سرور را بررسی کنید."
            loading = false
        }
    }

    LaunchedEffect(greenhouses.map { it.id }.toSet(), token, base) {
        if (token != null && base.startsWith("https://")) refresh()
    }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.padding(16.dp)) {
        Text("پایش دما و رطوبت گلخانه‌ها", style = MaterialTheme.typography.titleLarge)
        Text("اطلاعات فقط از اندازه‌گیری‌های ثبت‌شده نمایش داده می‌شوند؛ نبود داده با عدد ساختگی جایگزین نمی‌شود.", color = Color.LightGray)
        Button(onClick = { refresh() }, enabled = !loading && greenhouses.isNotEmpty()) {
            Text(if (loading) "در حال دریافت..." else "به‌روزرسانی وضعیت")
        }
        Text(message, color = Color(0xFF9BE0B1))
        if (greenhouses.isEmpty()) {
            Text("ابتدا گلخانه‌ها را در بخش گلخانه ثبت کنید.")
        }
        greenhouses.forEach { greenhouse ->
            val status = statuses[greenhouse.id]
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = Color(0xFF1B2C23))
            ) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text(greenhouse.name, style = MaterialTheme.typography.titleMedium)
                    val stateLabel = when (status?.state) {
                        "ONLINE" -> "متصل و دارای داده تازه"
                        "STALE" -> "داده قدیمی؛ ارتباط نیازمند بررسی"
                        "SIMULATED" -> "داده آزمایشی"
                        "NO_DATA" -> "هنوز داده‌ای دریافت نشده"
                        "ERROR" -> "خطا در دریافت وضعیت"
                        else -> "وضعیت هنوز دریافت نشده"
                    }
                    Text(stateLabel, color = if (status?.state == "ONLINE") Color(0xFF9BE0B1) else Color(0xFFFFD180))
                    if (status?.temperature != null && status.humidity != null) {
                        Text("دما: ${status.temperature} °C")
                        Text("رطوبت نسبی: ${status.humidity} %")
                        status.measuredAt?.let { Text("زمان اندازه‌گیری: ${java.text.DateFormat.getDateTimeInstance().format(java.util.Date(it))}") }
                    }
                    status?.alerts?.forEach { alert ->
                        Text("هشدار: " + when (alert) {
                            "TEMPERATURE_TOO_LOW" -> "دمای کمتر از حد تنظیم‌شده"
                            "TEMPERATURE_TOO_HIGH" -> "دمای بیشتر از حد تنظیم‌شده"
                            "HUMIDITY_TOO_LOW" -> "رطوبت کمتر از حد تنظیم‌شده"
                            "HUMIDITY_TOO_HIGH" -> "رطوبت بیشتر از حد تنظیم‌شده"
                            else -> alert
                        }, color = Color(0xFFFFAB91))
                    }
                    status?.error?.let { Text(it, color = Color(0xFFFFAB91)) }
                }
            }
        }
    }
}

private fun fetchGreenhouseSensorStatus(base: String, token: String, greenhouseId: String): GreenhouseSensorStatus {
    val encodedId = java.net.URLEncoder.encode(greenhouseId, "UTF-8")
    val endpoint = "$base/v1/sensors/greenhouses/$encodedId/status"
    val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"
        instanceFollowRedirects = false
        connectTimeout = 10_000
        readTimeout = 15_000
        setRequestProperty("Authorization", "Bearer $token")
        setRequestProperty("Accept", "application/json")
    }
    try {
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code == 401) throw SecurityException("نشست کاربری منقضی شده است؛ دوباره وارد شوید.")
        if (code !in 200..299) throw java.io.IOException("سرور وضعیت HTTP $code برگرداند.")
        val json = JSONObject(body)
        val alertsJson = json.optJSONArray("alerts")
        val alerts = (0 until (alertsJson?.length() ?: 0)).map { alertsJson!!.optString(it) }
        return GreenhouseSensorStatus(
            greenhouseId = greenhouseId,
            state = json.optString("status", "NO_DATA"),
            temperature = if (json.has("temperatureC") && !json.isNull("temperatureC")) json.optDouble("temperatureC") else null,
            humidity = if (json.has("relativeHumidityPct") && !json.isNull("relativeHumidityPct")) json.optDouble("relativeHumidityPct") else null,
            measuredAt = if (json.has("measuredAtEpochMillis") && !json.isNull("measuredAtEpochMillis")) json.optLong("measuredAtEpochMillis") else null,
            alerts = alerts
        )
    } finally {
        connection.disconnect()
    }
}
