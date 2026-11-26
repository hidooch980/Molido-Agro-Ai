package com.molido.agroai.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class AuthRepository(context: Context) {
    private val appContext = context.applicationContext
    private val session = SessionStore(appContext)

    suspend fun register(username: String, password: String) = authenticate("register", username, password)
    suspend fun login(username: String, password: String) = authenticate("login", username, password)

    /**
     * Revokes the token on the server before dropping it locally. Local sign-out alone would leave
     * a copied token usable for the rest of its two-week lifetime.
     */
    suspend fun signOut() {
        val token = session.accessToken()
        if (token != null) {
            withContext(Dispatchers.IO) {
                runCatching { send("POST", "${ServerConfig.baseUrl(appContext)}/v1/auth/logout", token, null) }
            }
        }
        session.clear()
    }

    /** Reads the signed-in account (including its role) and caches the role for the UI. */
    suspend fun refreshProfile(): AccountRole? = withContext(Dispatchers.IO) {
        val token = session.accessToken() ?: return@withContext null
        val base = ServerConfig.baseUrl(appContext)
        if (!base.startsWith("http")) return@withContext null
        val response = runCatching { send("GET", "$base/v1/auth/me", token, null) }.getOrNull()
            ?: return@withContext null
        val role = AccountRole.parse(JSONObject(response).optString("role"))
        session.saveRole(role?.wire)
        role
    }

    private suspend fun authenticate(action: String, username: String, password: String) {
        require(username.matches(Regex("[A-Za-z0-9_.-]{3,64}")))
        require(password.length in 12..256)
        val base = ServerConfig.baseUrl(appContext)
        require(base.startsWith("https://") || base.startsWith("http://")) { "سروری تنظیم نشده است؛ آدرس سرور همگام‌سازی را در بخش «اتصال به سرور» وارد کنید." }
        val body = JSONObject().put("username", username).put("password", password).toString()
        val response = withContext(Dispatchers.IO) { send("POST", "$base/v1/auth/$action", null, body) }
        val json = JSONObject(response)
        val userId = json.getString("userId")
        AgroDatabaseProvider.get(appContext).bindToAccount(userId)
        session.saveSession(json.getString("accessToken"), userId)
        SyncScheduler.runNow(appContext)
        runCatching { refreshProfile() }
    }

    private fun send(method: String, url: String, token: String?, body: String?): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            instanceFollowRedirects = false
            useCaches = false
            connectTimeout = 15_000
            readTimeout = 20_000
            setRequestProperty("Accept", "application/json")
            if (token != null) setRequestProperty("Authorization", "Bearer $token")
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
                val detail = runCatching { JSONObject(response).optString("detail", "درخواست به سرور ناموفق بود.") }
                    .getOrDefault("درخواست به سرور ناموفق بود.")
                throw IllegalStateException(detail.ifBlank { "درخواست به سرور ناموفق بود." })
            }
            return response
        } finally { connection.disconnect() }
    }
}
