package com.molido.agroai.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Base64

/**
 * Uses one private repository as the backup target so no server has to be hosted. Each upload is a
 * single commit under `molido-backups/`; the file is always a [PortableBackupCipher] envelope, so
 * the repository never contains readable farm data. Reads use the Git blob API, which (unlike the
 * contents API) returns files larger than 1 MB.
 */
object GitHubBackup {
    const val DIRECTORY = "molido-backups"
    private const val API = "https://api.github.com"
    private const val TIMEOUT_MS = 25_000
    private const val NAME_PREFIX = "molido-backup-"
    private val REPOSITORY = Regex("[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}")
    private val FILE_NAME = Regex("molido-backup-[0-9]{8}-[0-9]{6}\\.json")

    data class Outcome(val ok: Boolean, val message: String, val content: String? = null, val fileName: String? = null)

    fun isValidRepository(value: String): Boolean = REPOSITORY.matches(value.trim())

    fun isValidToken(value: String): Boolean =
        value.trim().length >= 20 && value.trim().none { it.isWhitespace() }

    fun newFileName(now: Instant = Instant.now()): String {
        val stamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").withZone(ZoneOffset.UTC).format(now)
        return "$NAME_PREFIX$stamp.json"
    }

    suspend fun push(token: String, repository: String, fileName: String, content: String): Outcome =
        withContext(Dispatchers.IO) {
            val repo = repository.trim()
            if (!isValidRepository(repo)) return@withContext Outcome(false, "نام ریپو باید به شکل owner/repo باشد.")
            if (!isValidToken(token)) return@withContext Outcome(false, "توکن گیت‌هاب معتبر نیست.")
            if (!FILE_NAME.matches(fileName)) return@withContext Outcome(false, "نام فایل پشتیبان معتبر نیست.")
            runCatching {
                val body = JSONObject()
                    .put("message", "backup: $fileName")
                    .put("content", Base64.getEncoder().encodeToString(content.toByteArray(Charsets.UTF_8)))
                    .toString()
                send("PUT", "$API/repos/$repo/contents/$DIRECTORY/$fileName", token, body)
                Outcome(true, "پشتیبان رمزگذاری‌شده در $DIRECTORY/$fileName روی گیت‌هاب ثبت شد.")
            }.getOrElse { exception ->
                Outcome(false, exception.message ?: "ارسال پشتیبان به گیت‌هاب ناموفق بود.")
            }
        }

    suspend fun pullLatest(token: String, repository: String): Outcome = withContext(Dispatchers.IO) {
        val repo = repository.trim()
        if (!isValidRepository(repo)) return@withContext Outcome(false, "نام ریپو باید به شکل owner/repo باشد.")
        if (!isValidToken(token)) return@withContext Outcome(false, "توکن گیت‌هاب معتبر نیست.")
        runCatching {
            val listing = JSONArray(get(token, "$API/repos/$repo/contents/$DIRECTORY"))
            var bestName: String? = null
            var bestSha: String? = null
            for (index in 0 until listing.length()) {
                val entry = listing.getJSONObject(index)
                val name = entry.optString("name")
                if (entry.optString("type") != "file" || !FILE_NAME.matches(name)) continue
                if (bestName == null || name > bestName) {
                    bestName = name
                    bestSha = entry.getString("sha")
                }
            }
            val name = bestName ?: return@runCatching Outcome(true, "هنوز پشتیبانی روی گیت‌هاب ثبت نشده است.")
            val blob = JSONObject(get(token, "$API/repos/$repo/git/blobs/$bestSha"))
            val encoded = blob.getString("content").replace("\n", "")
            val content = String(Base64.getDecoder().decode(encoded), Charsets.UTF_8)
            Outcome(true, "آخرین پشتیبان دریافت شد.", content = content, fileName = name)
        }.getOrElse { exception ->
            if ((exception as? GitHubHttpException)?.code == 404) {
                Outcome(true, "هنوز پشتیبانی روی گیت‌هاب ثبت نشده است.")
            } else {
                Outcome(false, exception.message ?: "دریافت پشتیبان از گیت‌هاب ناموفق بود.")
            }
        }
    }

    private fun get(token: String, url: String): String = send("GET", url, token, null)

    private fun send(method: String, url: String, token: String, body: String?): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("Authorization", "Bearer ${token.trim()}")
            setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            setRequestProperty("User-Agent", "MolidoAgroAI")
        }
        try {
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code in 200..299) return text
            throw GitHubHttpException(code, describe(code, text))
        } finally {
            connection.disconnect()
        }
    }

    private class GitHubHttpException(val code: Int, message: String) : IllegalStateException(message)

    private fun describe(code: Int, text: String): String = when (code) {
        401 -> "توکن گیت‌هاب پذیرفته نشد؛ توکن را بررسی کنید."
        403 -> "توکن اجازه نوشتن/خواندن این ریپو را ندارد."
        404 -> "ریپو یا مسیر پیدا نشد؛ نام ریپو و دسترسی توکن را بررسی کنید."
        409, 422 -> "گیت‌هاب این درخواست را نپذیرفت: " + text.take(160)
        else -> "خطای گیت‌هاب ($code): " + text.take(160)
    }
}
