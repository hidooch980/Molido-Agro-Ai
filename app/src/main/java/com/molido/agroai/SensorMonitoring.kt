package com.molido.agroai

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.molido.agroai.data.GreenhouseEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private data class GreenhouseSensorStatus(
    val greenhouseId: String, val state: String, val temperature: Double? = null,
    val humidity: Double? = null, val measuredAt: Long? = null,
    val alerts: List<String> = emptyList(), val error: String? = null
)
private data class SensorHistoryPoint(val measuredAt: Long, val temperature: Double, val humidity: Double)

@Composable
fun SensorMonitoringPage(greenhouses: List<GreenhouseEntity>, token: String?) {
    var statuses by remember { mutableStateOf<Map<String, GreenhouseSensorStatus>>(emptyMap()) }
    var histories by remember { mutableStateOf<Map<String, List<SensorHistoryPoint>>>(emptyMap()) }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("برای مشاهده داده‌های سنسورها، حساب کاربری و سرور را متصل کنید.") }
    val scope = rememberCoroutineScope()
    val base = BuildConfig.SYNC_BASE_URL.trim().trimEnd('/')

    fun refresh() {
        if (token.isNullOrBlank()) { message = "برای مشاهده پایش سنسورها ابتدا وارد حساب شوید."; return }
        if (!base.startsWith("https://")) { message = "آدرس HTTPS سرور محلی در تنظیمات نسخه برنامه تعریف نشده است."; return }
        loading = true
        message = "در حال دریافت وضعیت و تاریخچه سنسورها..."
        scope.launch {
            val results = coroutineScope {
                greenhouses.map { greenhouse ->
                    async(Dispatchers.IO) {
                        val status = runCatching { fetchGreenhouseSensorStatus(base, token, greenhouse.id) }
                            .getOrElse { GreenhouseSensorStatus(greenhouse.id, "ERROR", error = it.message ?: "خطای ارتباط") }
                        val history = if (status.state == "ERROR") emptyList() else
                            runCatching { fetchGreenhouseSensorHistory(base, token, greenhouse.id) }.getOrDefault(emptyList())
                        Triple(greenhouse.id, status, history)
                    }
                }.awaitAll()
            }
            statuses = results.associate { it.first to it.second }
            histories = results.associate { it.first to it.third }
            val errors = results.count { it.second.state == "ERROR" }
            message = if (errors == 0) "وضعیت و تاریخچه ${results.size} گلخانه به‌روزرسانی شد."
                else "دریافت اطلاعات $errors گلخانه ناموفق بود؛ اتصال سرور را بررسی کنید."
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
            Text(if (loading) "در حال دریافت..." else "به‌روزرسانی وضعیت و تاریخچه")
        }
        Text(message, color = Color(0xFF9BE0B1))
        if (greenhouses.isEmpty()) Text("ابتدا گلخانه‌ها را در بخش گلخانه ثبت کنید.")
        greenhouses.forEach { greenhouse ->
            val status = statuses[greenhouse.id]
            val history = histories[greenhouse.id].orEmpty()
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFF1B2C23))) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
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
                    if (history.isNotEmpty()) {
                        Text("تاریخچه ${history.size} اندازه‌گیری اخیر", style = MaterialTheme.typography.titleSmall)
                        SensorHistoryChart("دما (°C)", history, { it.temperature }, Color(0xFFFFB74D))
                        SensorHistoryChart("رطوبت نسبی (%)", history, { it.humidity }, Color(0xFF80CBC4))
                        val first = history.first().measuredAt
                        val last = history.last().measuredAt
                        Text("بازه: ${java.text.DateFormat.getDateTimeInstance().format(java.util.Date(first))} تا ${java.text.DateFormat.getDateTimeInstance().format(java.util.Date(last))}",
                            color = Color.LightGray, style = MaterialTheme.typography.bodySmall)
                    } else if (status?.state == "NO_DATA") {
                        Text("برای رسم نمودار هنوز اندازه‌گیری ثبت نشده است.", color = Color.LightGray)
                    }
                }
            }
        }
    }
}

@Composable
private fun SensorHistoryChart(title: String, points: List<SensorHistoryPoint>, value: (SensorHistoryPoint) -> Double, lineColor: Color) {
    val values = points.map(value).filter { it.isFinite() }
    Text(title, style = MaterialTheme.typography.bodyMedium)
    if (values.isEmpty()) { Text("داده معتبر برای نمودار وجود ندارد.", color = Color.LightGray); return }
    val minValue = values.minOrNull() ?: 0.0
    val maxValue = values.maxOrNull() ?: 1.0
    val range = (maxValue - minValue).takeIf { it > 0.000001 } ?: 1.0
    Text("کمینه: ${"%.1f".format(minValue)} • بیشینه: ${"%.1f".format(maxValue)}", color = Color.LightGray, style = MaterialTheme.typography.bodySmall)
    Canvas(Modifier.fillMaxWidth().height(112.dp)) {
        val left = 8.dp.toPx(); val right = size.width - 8.dp.toPx()
        val top = 8.dp.toPx(); val bottom = size.height - 8.dp.toPx()
        for (i in 0..2) {
            val y = top + (bottom - top) * i / 2f
            drawLine(Color.White.copy(alpha = 0.16f), Offset(left, y), Offset(right, y), strokeWidth = 1.dp.toPx())
        }
        val valid = points.filter { value(it).isFinite() }
        if (valid.size == 1) {
            val y = bottom - ((value(valid.first()) - minValue) / range).toFloat() * (bottom - top)
            drawCircle(lineColor, radius = 4.dp.toPx(), center = Offset((left + right) / 2f, y))
        } else if (valid.size > 1) {
            val path = Path()
            valid.forEachIndexed { index, point ->
                val x = left + (right - left) * index / (valid.size - 1).toFloat()
                val y = bottom - ((value(point) - minValue) / range).toFloat() * (bottom - top)
                if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, lineColor, style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round))
            val lastY = bottom - ((value(valid.last()) - minValue) / range).toFloat() * (bottom - top)
            drawCircle(lineColor, radius = 4.dp.toPx(), center = Offset(right, lastY))
        }
    }
}

private fun fetchGreenhouseSensorStatus(base: String, token: String, greenhouseId: String): GreenhouseSensorStatus {
    val encodedId = java.net.URLEncoder.encode(greenhouseId, "UTF-8")
    val connection = (URL("$base/v1/sensors/greenhouses/$encodedId/status").openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"; instanceFollowRedirects = false; connectTimeout = 10_000; readTimeout = 15_000
        setRequestProperty("Authorization", "Bearer $token"); setRequestProperty("Accept", "application/json")
    }
    try {
        val code = connection.responseCode
        val body = (if (code in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code == 401) throw SecurityException("نشست کاربری منقضی شده است؛ دوباره وارد شوید.")
        if (code !in 200..299) throw java.io.IOException("سرور وضعیت HTTP $code برگرداند.")
        val json = JSONObject(body); val alertsJson = json.optJSONArray("alerts")
        val alerts = (0 until (alertsJson?.length() ?: 0)).map { alertsJson!!.optString(it) }
        return GreenhouseSensorStatus(greenhouseId, json.optString("status", "NO_DATA"),
            if (json.has("temperatureC") && !json.isNull("temperatureC")) json.optDouble("temperatureC") else null,
            if (json.has("relativeHumidityPct") && !json.isNull("relativeHumidityPct")) json.optDouble("relativeHumidityPct") else null,
            if (json.has("measuredAtEpochMillis") && !json.isNull("measuredAtEpochMillis")) json.optLong("measuredAtEpochMillis") else null, alerts)
    } finally { connection.disconnect() }
}

private fun fetchGreenhouseSensorHistory(base: String, token: String, greenhouseId: String): List<SensorHistoryPoint> {
    val encodedId = java.net.URLEncoder.encode(greenhouseId, "UTF-8")
    val connection = (URL("$base/v1/sensors/greenhouses/$encodedId/readings?limit=48").openConnection() as HttpURLConnection).apply {
        requestMethod = "GET"; instanceFollowRedirects = false; connectTimeout = 10_000; readTimeout = 15_000
        setRequestProperty("Authorization", "Bearer $token"); setRequestProperty("Accept", "application/json")
    }
    try {
        val code = connection.responseCode
        val body = (if (code in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        if (code == 401) throw SecurityException("نشست کاربری منقضی شده است؛ دوباره وارد شوید.")
        if (code !in 200..299) throw java.io.IOException("سرور تاریخچه HTTP $code برگرداند.")
        val rows = JSONObject(body).optJSONArray("readings") ?: return emptyList()
        return (0 until rows.length()).mapNotNull { index ->
            val row = rows.optJSONObject(index) ?: return@mapNotNull null
            if (row.isNull("temperatureC") || row.isNull("relativeHumidityPct")) return@mapNotNull null
            val temp = row.optDouble("temperatureC", Double.NaN); val humidity = row.optDouble("relativeHumidityPct", Double.NaN)
            if (!temp.isFinite() || !humidity.isFinite()) return@mapNotNull null
            SensorHistoryPoint(row.optLong("measuredAtEpochMillis"), temp, humidity)
        }.sortedBy { it.measuredAt }
    } finally { connection.disconnect() }
}
