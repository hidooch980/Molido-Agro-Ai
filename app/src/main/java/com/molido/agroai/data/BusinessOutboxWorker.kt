package com.molido.agroai.data

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.molido.agroai.BuildConfig
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

object BusinessSyncScheduler {
    fun enqueue(context: Context) {
        val request = OneTimeWorkRequestBuilder<BusinessOutboxWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("molido-business-outbox", ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }
}

class BusinessOutboxWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val base = BuildConfig.SYNC_BASE_URL.trim().trimEnd('/')
        if (base.isBlank()) return Result.success()
        if (!base.startsWith("https://")) return Result.failure()
        val session = SessionStore(applicationContext)
        val token = session.accessToken() ?: return Result.success()
        val accountId = session.userId() ?: return Result.success()
        val dao = BusinessLocalStore.get(applicationContext).businessDao()
        return try {
            val pending = dao.pending(accountId, 50)
            for (record in pending) {
                val payload = try {
                    JSONObject(SyncPayloadCipher.decrypt(record.encryptedPayload))
                } catch (e: Exception) {
                    // One unreadable record must not block every other pending CRM/ERP row.
                    dao.setState(record.id, "CONFLICT")
                    continue
                }
                val operation = JSONObject()
                    .put("idempotencyKey", "business:" + record.entityType + ":" + record.entityId)
                    .put("entityType", record.entityType)
                    .put("entityId", record.entityId)
                    .put("operation", "CREATE")
                    .put("payload", payload)
                    .put("baseVersion", 0)
                val body = JSONObject().put("operations", JSONArray().put(operation))
                val result = JSONObject(post(base + "/v1/sync/push", token, body.toString()))
                    .getJSONArray("results").getJSONObject(0)
                when (result.optString("status")) {
                    "applied" -> dao.setState(record.id, "SYNCED")
                    "conflict" -> dao.setState(record.id, "CONFLICT")
                    else -> return Result.retry()
                }
            }
            Result.success()
        } catch (_: SecurityException) {
            SessionStore(applicationContext).clear()
            Result.failure()
        } catch (_: Exception) {
            Result.retry()
        }
    }

    private fun post(endpoint: String, token: String, body: String): String {
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            instanceFollowRedirects = false
            connectTimeout = 15000
            readTimeout = 20000
            doOutput = true
            setRequestProperty("Authorization", "Bearer " + token)
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        try {
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code == 401 || code == 403) throw SecurityException("Business sync authentication failed")
            if (code !in 200..299) throw java.io.IOException("Business sync HTTP " + code)
            return text
        } finally {
            connection.disconnect()
        }
    }
}
