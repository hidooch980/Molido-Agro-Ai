package com.molido.agroai.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/**
 * Best-effort call to the self-hosted diagnosis endpoint. The local catalog already answers
 * offline, so every failure here is reported as "no server advice" instead of an error.
 */
object DiseaseDiagnosisApi {
    private val SUPPORTED = setOf("cuc-downy-mildew", "cuc-powdery-mildew", "tom-late-blight", "str-gray-mold")

    data class Advice(
        val condition: String,
        val riskLevel: String,
        val culturalControls: List<String>,
        val biologicalControls: List<String>,
        val safetyAdvisory: String,
        val requiresHumanSignoff: Boolean,
        val temperatureCelsius: Double?,
        val humidityPercent: Double?
    )

    fun isSupported(diseaseId: String): Boolean = diseaseId in SUPPORTED

    suspend fun diagnose(
        context: Context,
        cropCode: String,
        diseaseId: String,
        confidence: Double,
        notes: String,
        greenhouseId: String? = null
    ): Advice? = withContext(Dispatchers.IO) {
        if (!isSupported(diseaseId)) return@withContext null
        val base = ServerConfig.baseUrl(context)
        if (base.isEmpty()) return@withContext null
        val token = SessionStore(context).accessToken() ?: return@withContext null
        runCatching {
            val connection = (URL("$base/v1/ai/diagnose/disease").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8_000
                readTimeout = 15_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("Authorization", "Bearer $token")
            }
            try {
                val body = JSONObject()
                    .put("cropCode", cropCode)
                    .put("diseaseId", diseaseId)
                    .put("confidence", confidence)
                    .put("notes", notes.take(1000))
                    .apply { if (!greenhouseId.isNullOrBlank()) put("greenhouseId", greenhouseId) }
                    .toString()
                OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { it.write(body) }
                val code = connection.responseCode
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                if (code !in 200..299) return@runCatching null
                parse(JSONObject(text))
            } finally {
                connection.disconnect()
            }
        }.getOrNull()
    }

    private fun parse(json: JSONObject): Advice? {
        val condition = json.optString("condition")
        if (condition.isEmpty()) return null
        val microclimate = json.optJSONObject("microclimate")
        return Advice(
            condition = condition,
            riskLevel = json.optString("riskLevel"),
            culturalControls = json.optJSONArray("culturalControls").toStringList(),
            biologicalControls = json.optJSONArray("biologicalControls").toStringList(),
            safetyAdvisory = json.optString("safetyAdvisory"),
            requiresHumanSignoff = json.optBoolean("requiresHumanSignoff", true),
            temperatureCelsius = microclimate?.optDoubleOrNull("temperatureCelsius"),
            humidityPercent = microclimate?.optDoubleOrNull("humidityPercent")
        )
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        val items = ArrayList<String>()
        for (index in 0 until length()) {
            val value = optString(index)
            if (value.isNotEmpty()) items.add(value)
        }
        return items
    }

    private fun JSONObject.optDoubleOrNull(key: String): Double? {
        if (!has(key) || isNull(key)) return null
        val value = optDouble(key, Double.NaN)
        return if (value.isNaN()) null else value
    }
}
