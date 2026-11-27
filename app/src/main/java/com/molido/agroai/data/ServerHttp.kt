package com.molido.agroai.data

import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * One HTTP entry point for the server-backed panels. It resolves the configured base URL and the
 * stored bearer token, and turns a non-2xx answer into the Persian detail the server sent so the UI
 * can show the real reason instead of a generic failure.
 */
object ServerHttp {
    fun request(
        context: Context,
        method: String,
        path: String,
        body: String? = null,
        headers: Map<String, String> = emptyMap(),
    ): String {
        val base = ServerConfig.baseUrl(context)
        check(base.startsWith("http")) { "سرور همگام‌سازی تنظیم نشده است؛ آدرس آن را در بخش «اتصال به سرور» وارد کنید." }
        val token = SessionStore(context).accessToken()
            ?: throw IllegalStateException("برای این کار باید وارد حساب شوید.")
        val connection = (URL(base + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            useCaches = false
            connectTimeout = 15_000
            readTimeout = 20_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer $token")
            headers.forEach { (name, value) -> setRequestProperty(name, value) }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(response).optString("detail") }.getOrDefault("")
                throw IllegalStateException(detail.ifBlank { "سرور درخواست را نپذیرفت (کد $code)." })
            }
            return response
        } finally {
            connection.disconnect()
        }
    }
}