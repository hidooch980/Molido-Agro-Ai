package com.molido.agroai.data

import com.molido.agroai.BuildConfig

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
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
        WorkManager.getInstance(context).enqueueUniqueWork("molido-agro-sync-immediate", ExistingWorkPolicy.APPEND_OR_REPLACE, request)
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
                        .put("baseVersion", operation.baseVersion)))
                val response = request("$base/v1/sync/push", token, body.toString())
                val result = JSONObject(response).getJSONArray("results").getJSONObject(0)
                when (result.optString("status")) {
                    "applied" -> {
                        dao.markSynced(operation.id)
                        val version = result.optInt("serverVersion", 0)
                        if (version > 0) db.syncInboxDao().receive(SyncInboxEntity(
                            id = "${operation.entityType}:${operation.entityId}:$version",
                            entityType = operation.entityType,
                            entityId = operation.entityId,
                            encryptedPayload = operation.payloadJson,
                            serverVersion = version,
                            updatedAtEpochMillis = System.currentTimeMillis(),
                            deleted = operation.operation == "DELETE",
                            state = "SYNCED"
                        ))
                    }
                    "conflict" -> dao.markConflict(operation.id, "Server version conflict: ${result.optLong("serverVersion")}")
                    else -> dao.scheduleRetry(operation.id, "Unrecognized server response", SyncRetryPolicy.nextAttemptAt(System.currentTimeMillis(), operation.attemptCount))
                }
            }
            pullRemoteChanges(base, token, db)
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

    private suspend fun pullRemoteChanges(base: String, token: String, db: AgroDatabase) {
        val prefs = applicationContext.getSharedPreferences("molido_sync_state", Context.MODE_PRIVATE)
        val cursor = prefs.getLong("remote_cursor", 0L)
        val body = JSONObject().put("cursor", cursor).put("limit", 100).toString()
        val response = JSONObject(request("$base/v1/sync/pull", token, body))
        val changes = response.optJSONArray("changes") ?: JSONArray()
        val inbox = db.syncInboxDao()
        val outbox = db.syncOperationDao()
        var newestCursor = cursor
        for (index in 0 until changes.length()) {
            val change = changes.getJSONObject(index)
            val type = change.getString("entityType")
            val entityId = change.getString("entityId")
            val version = change.getInt("version")
            val payload = change.optJSONObject("payload") ?: JSONObject()
            val localPending = outbox.pendingForEntity(type, entityId) ?: outbox.conflictedForEntity(type, entityId)
            val state = if (localPending != null) "CONFLICT" else "PENDING_REVIEW"
            if (localPending != null) outbox.markConflict(localPending.id, "Remote update arrived while local changes were pending")
            inbox.receive(SyncInboxEntity(
                id = "$type:$entityId:$version", entityType = type, entityId = entityId,
                encryptedPayload = SyncPayloadCipher.encrypt(applicationContext, payload.toString()),
                serverVersion = version, updatedAtEpochMillis = change.optLong("updatedAt"),
                deleted = change.optBoolean("deleted"), state = state
            ))
            newestCursor = maxOf(newestCursor, change.optLong("cursorId"))
        }
        val serverCursor = response.optLong("cursor", newestCursor)
        check(prefs.edit().putLong("remote_cursor", maxOf(newestCursor, serverCursor)).commit())
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
            instanceFollowRedirects = false
            useCaches = false
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
