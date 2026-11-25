package com.molido.agroai.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/**
 * Uploads a manually typed reading to the account-isolated sensor API. The server deduplicates on
 * the idempotency key, so a retried submission cannot create two rows.
 */
object SensorReadingsApi {
    private const val MANUAL_SENSOR_ID = "manual-app"

    data class Outcome(val ok: Boolean, val message: String)

    suspend fun submit(
        context: Context,
        token: String?,
        greenhouseId: String,
        temperatureC: Double,
        humidityPct: Double,
        measuredAtEpochMillis: Long = System.currentTimeMillis()
    ): Outcome = withContext(Dispatchers.IO) {
        if (token.isNullOrBlank()) return@withContext Outcome(false, "برای ثبت قرائت ابتدا وارد حساب شوید.")
        val base = ServerConfig.baseUrl(context)
        if (!base.startsWith("https://") && !base.startsWith("http://")) {
            return@withContext Outcome(false, "آدرس سرور تنظیم نشده است؛ آن را در بخش «اتصال به سرور» وارد کنید.")
        }
        runCatching {
            val connection = (URL("$base/v1/sensors/readings").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 15_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Authorization", "Bearer $token")
            }
            try {
                val body = JSONObject()
                    .put("idempotencyKey", UUID.randomUUID().toString())
                    .put("greenhouseId", greenhouseId)
                    .put("sensorId", MANUAL_SENSOR_ID)
                    .put("measuredAtEpochMillis", measuredAtEpochMillis)
                    .put("temperatureC", temperatureC)
                    .put("relativeHumidityPct", humidityPct)
                    .put("source", "MANUAL")
                    .toString()
                OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { it.write(body) }
                val code = connection.responseCode
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                when {
                    code in 200..299 -> {
                        val json = runCatching { JSONObject(text) }.getOrNull()
                        val duplicate = json?.optString("status") == "duplicate"
                        Outcome(true, if (duplicate) "این قرائت قبلاً ثبت شده بود." else "قرائت دستی ثبت شد.")
                    }
                    code == 401 -> Outcome(false, "نشست منقضی شده است؛ دوباره وارد شوید.")
                    else -> {
                        val detail = runCatching { JSONObject(text).optString("detail") }.getOrDefault("")
                        Outcome(false, "ثبت ناموفق (کد $code)${if (detail.isNotEmpty()) ": $detail" else ""}")
                    }
                }
            } finally {
                connection.disconnect()
            }
        }.getOrElse { Outcome(false, "ارتباط با سرور برقرار نشد: ${it.message ?: "خطای شبکه"}") }
    }
}
