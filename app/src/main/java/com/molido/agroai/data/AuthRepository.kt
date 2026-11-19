package com.molido.agroai.data

import android.content.Context
import com.molido.agroai.BuildConfig
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class AuthRepository(context: Context) {
    private val appContext = context.applicationContext
    private val session = SessionStore(appContext)

    fun register(username: String, password: String) = authenticate("register", username, password)
    fun login(username: String, password: String) = authenticate("login", username, password)
    fun signOut() = session.clear()

    private fun authenticate(action: String, username: String, password: String) {
        require(username.matches(Regex("[A-Za-z0-9_.-]{3,64}")))
        require(password.length in 12..256)
        val base = BuildConfig.SYNC_BASE_URL.trim().trimEnd('/')
        require(base.startsWith("https://")) { "آدرس امن سرور همگام‌سازی تنظیم نشده است." }
        val connection = (URL("$base/v1/auth/$action").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 20_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        try {
            val body = JSONObject().put("username", username).put("password", password).toString()
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IllegalStateException(JSONObject(response).optString("detail", "ورود ناموفق بود."))
            val json = JSONObject(response)
            session.saveSession(json.getString("accessToken"), json.getString("userId"))
            SyncScheduler.runNow(appContext)
        } finally { connection.disconnect() }
    }
}
