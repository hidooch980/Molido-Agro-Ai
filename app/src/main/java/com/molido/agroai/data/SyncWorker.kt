package com.molido.agroai.data

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

object SyncScheduler {
    private const val UNIQUE = "molido-agro-periodic-sync"
    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<AgroSyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(UNIQUE, ExistingPeriodicWorkPolicy.KEEP, request)
    }
    fun runNow(context: Context) {
        val request = androidx.work.OneTimeWorkRequestBuilder<AgroSyncWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueue(request)
    }
}

class AgroSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val base = BuildConfig.SYNC_BASE_URL.trim().trimEnd('/')
        if (base.isBlank()) return Result.success()
        if (!base.startsWith("https://")) return Result.failure()
        val token = SessionStore(applicationContext).accessToken() ?: return Result.success()
        val db = AgroDatabaseProvider.get(applicationContext)
        val dao = db.syncOperationDao()
        return try {
            val due = dao.due(limit = 50)
            for (operation in due) {
                val payload = JSONObject(SyncPayloadCipher.decrypt(operation.payloadJson))
                val body = JSONObject()
                    .put("operations", JSONArray().put(JSONObject()
                        .put("idempotencyKey", operation.idempotencyKey)
                        .put("entityType", operation.entityType)
                        .put("entityId", operation.entityId)
                        .put("operation", operation.operation)
                        .put("payload", payload)
                        .put("baseVersion", 0)))
                val response = request("$base/v1/sync/push", token, body.toString())
                val result = JSONObject(response).getJSONArray("results").getJSONObject(0)
                when (result.optString("status")) {
                    "applied" -> dao.markSynced(operation.id)
                    "conflict" -> dao.markConflict(operation.id, "Server version conflict: ${result.optLong("serverVersion")}")
                    else -> dao.scheduleRetry(operation.id, "Unrecognized server response", SyncRetryPolicy.nextAttemptAt(System.currentTimeMillis(), operation.attemptCount))
                }
            }
            Result.success()
        } catch (e: java.io.IOException) {
            dueRetry(dao, e)
            Result.retry()
        } catch (e: SecurityException) {
            Result.failure()
        } catch (e: Exception) {
            dueRetry(dao, e)
            Result.retry()
        }
    }

    private suspend fun dueRetry(dao: SyncOperationDao, error: Exception) {
        dao.due(limit = 50).forEach { op ->
            dao.scheduleRetry(op.id, (error.message ?: "Sync error").take(500),
                SyncRetryPolicy.nextAttemptAt(System.currentTimeMillis(), op.attemptCount))
        }
    }

    private fun request(endpoint: String, token: String, body: String): String {
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 20_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        try {
            connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code == 401) throw SecurityException("Sync session expired")
            if (code !in 200..299) throw java.io.IOException("Sync API returned HTTP $code")
            return text
        } finally { connection.disconnect() }
    }
}
