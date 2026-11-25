package com.molido.agroai.data

import com.molido.agroai.BuildConfig

import android.content.Context
import androidx.room.withTransaction
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
            var rounds = 0
            while (rounds < MAX_PUSH_ROUNDS) {
                val batch = buildBatch(dao)
                if (batch.isEmpty()) break
                pushBatch(base, token, db, dao, batch)
                rounds += 1
            }
            pullRemoteChanges(base, token, db)
            Result.success()
        } catch (e: java.io.IOException) {
            dueRetry(dao, e)
            Result.retry()
        } catch (e: SecurityException) {
            // The stored token was rejected, so drop it now; otherwise the account panel keeps
            // claiming a live session while every scheduled sync fails silently.
            SessionStore(applicationContext).clear()
            Result.failure()
        } catch (e: Exception) {
            dueRetry(dao, e)
            Result.retry()
        }
    }

    /**
     * Collects pending operations into one push request. The server rejects bodies above
     * 1 MiB, so the batch stops before crossing the local byte budget instead of failing
     * the whole round.
     */
    private suspend fun buildBatch(dao: SyncOperationDao): List<Pair<SyncOperationEntity, JSONObject>> {
        val due = dao.due(limit = MAX_BATCH_OPERATIONS)
        val batch = ArrayList<Pair<SyncOperationEntity, JSONObject>>(due.size)
        var approxBytes = 0
        for (operation in due) {
            val payload = try {
                JSONObject(SyncPayloadCipher.decrypt(operation.payloadJson))
            } catch (e: Exception) {
                // A single unreadable payload must not fail every round and stall the queue.
                dao.markConflict(operation.id, "Stored payload could not be decrypted; re-enter this record")
                continue
            }
            val entry = JSONObject()
                .put("idempotencyKey", operation.idempotencyKey)
                .put("entityType", operation.entityType)
                .put("entityId", operation.entityId)
                .put("operation", operation.operation)
                .put("payload", payload)
                .put("baseVersion", operation.baseVersion)
            val size = entry.toString().toByteArray(Charsets.UTF_8).size
            if (batch.isNotEmpty() && approxBytes + size > MAX_BATCH_BYTES) break
            batch.add(operation to entry)
            approxBytes += size
        }
        return batch
    }

    private suspend fun pushBatch(
        base: String,
        token: String,
        db: AgroDatabase,
        dao: SyncOperationDao,
        batch: List<Pair<SyncOperationEntity, JSONObject>>
    ) {
        val operations = JSONArray()
        for ((_, entry) in batch) operations.put(entry)
        val body = JSONObject().put("operations", operations).toString()
        val response = JSONObject(request("$base/v1/sync/push", token, body))
        val results = response.optJSONArray("results") ?: JSONArray()
        val byKey = HashMap<String, JSONObject>(results.length())
        for (index in 0 until results.length()) {
            val result = results.optJSONObject(index) ?: continue
            val key = result.optString("idempotencyKey")
            if (key.isNotEmpty()) byKey[key] = result
        }
        val now = System.currentTimeMillis()
        for ((operation, _) in batch) {
            val result = byKey[operation.idempotencyKey]
            if (result == null) {
                dao.scheduleRetry(operation.id, "Server did not report a result for this operation",
                    SyncRetryPolicy.nextAttemptAt(now, operation.attemptCount))
                continue
            }
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
                        updatedAtEpochMillis = now,
                        deleted = operation.operation == "DELETE",
                        state = "SYNCED"
                    ))
                }
                "conflict" -> dao.markConflict(operation.id, "Server version conflict: ${result.optLong("serverVersion")}")
                else -> dao.scheduleRetry(operation.id, "Unrecognized server response",
                    SyncRetryPolicy.nextAttemptAt(now, operation.attemptCount))
            }
        }
    }

    private suspend fun pullRemoteChanges(base: String, token: String, db: AgroDatabase) {
        val prefs = applicationContext.getSharedPreferences("molido_sync_state", Context.MODE_PRIVATE)
        val startCursor = prefs.getLong("remote_cursor", 0L)
        var newestCursor = startCursor
        val inbox = db.syncInboxDao()
        val outbox = db.syncOperationDao()
        val projector = SyncProjector(db)
        var rounds = 0
        while (rounds < MAX_PULL_ROUNDS) {
            val pageStartCursor = newestCursor
            val body = JSONObject().put("cursor", newestCursor).put("limit", PULL_PAGE_SIZE).toString()
            val response = JSONObject(request("$base/v1/sync/pull", token, body))
            val changes = response.optJSONArray("changes") ?: JSONArray()
            for (index in 0 until changes.length()) {
                val change = changes.optJSONObject(index) ?: continue
                val type = change.getString("entityType")
                val entityId = change.getString("entityId")
                val version = change.getInt("version")
                val payload = change.optJSONObject("payload") ?: JSONObject()
                val deleted = change.optBoolean("deleted")
                val inboxEntity = SyncInboxEntity(
                    id = "$type:$entityId:$version",
                    entityType = type,
                    entityId = entityId,
                    encryptedPayload = SyncPayloadCipher.encrypt(applicationContext, payload.toString()),
                    serverVersion = version,
                    updatedAtEpochMillis = change.optLong("updatedAt"),
                    deleted = deleted,
                    state = "APPLIED"
                )
                val pending = outbox.pendingForEntity(type, entityId) ?: outbox.conflictedForEntity(type, entityId)
                if (pending != null) {
                    outbox.markConflict(pending.id, "Remote update arrived while local changes were pending")
                    inbox.receive(inboxEntity.copy(state = "CONFLICT"))
                } else {
                    try {
                        db.withTransaction {
                            val recheck = outbox.pendingForEntity(type, entityId) ?: outbox.conflictedForEntity(type, entityId)
                            if (recheck != null) {
                                outbox.markConflict(recheck.id, "Remote update arrived while local changes were pending")
                                inbox.receive(inboxEntity.copy(state = "CONFLICT"))
                            } else {
                                projector.applyChange(inboxEntity)
                                inbox.receive(inboxEntity)
                            }
                        }
                    } catch (e: Exception) {
                        // Keep the change for manual review instead of dropping it silently.
                        inbox.receive(inboxEntity.copy(state = "PENDING_REVIEW"))
                    }
                }
                newestCursor = maxOf(newestCursor, change.optLong("cursorId"))
            }
            rounds += 1
            val serverCursor = response.optLong("cursor", newestCursor)
            newestCursor = maxOf(newestCursor, serverCursor)
            if (changes.length() < PULL_PAGE_SIZE) break
            // A server that echoes the same cursor would otherwise replay this page on every run.
            if (newestCursor == pageStartCursor) break
        }
        if (newestCursor != startCursor) {
            check(prefs.edit().putLong("remote_cursor", newestCursor).commit())
        }
    }

    private suspend fun dueRetry(dao: SyncOperationDao, error: Exception) {
        val now = System.currentTimeMillis()
        dao.due(limit = MAX_BATCH_OPERATIONS).forEach { op ->
            dao.scheduleRetry(op.id, (error.message ?: "Sync error").take(500),
                SyncRetryPolicy.nextAttemptAt(now, op.attemptCount))
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

    private companion object {
        const val MAX_BATCH_OPERATIONS = 50
        const val MAX_BATCH_BYTES = 500_000
        const val MAX_PUSH_ROUNDS = 5
        const val MAX_PULL_ROUNDS = 5
        const val PULL_PAGE_SIZE = 100
    }
}
