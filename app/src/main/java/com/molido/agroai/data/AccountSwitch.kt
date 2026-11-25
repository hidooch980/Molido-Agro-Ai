package com.molido.agroai.data

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.work.WorkManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Moving a device to another account. The local databases are bound to one account so that a
 * different login cannot read them, which means a switch is necessarily destructive: every local
 * row (including unsynced work) is deleted, the binding is dropped and the session is cleared.
 * Callers must show [Preview] first and get an explicit confirmation.
 */
object AccountSwitch {
    const val BOUND_ACCOUNT_KEY = "bound_account_id"
    private const val SYNC_PERIODIC_WORK = "molido-agro-periodic-sync"
    private const val SYNC_IMMEDIATE_WORK = "molido-agro-sync-immediate"
    private const val BUSINESS_OUTBOX_WORK = "molido-business-outbox"

    data class Preview(
        val boundAccountId: String?,
        val activeAccountId: String?,
        val outstandingSyncOperations: Int,
        val pendingBusinessRecords: Int
    ) {
        val hasLocalAccount: Boolean get() = boundAccountId != null || activeAccountId != null
        val hasUnsyncedWork: Boolean get() = outstandingSyncOperations > 0 || pendingBusinessRecords > 0
    }

    suspend fun preview(
        context: Context,
        db: AgroDatabase,
        business: BusinessLocalDatabase
    ): Preview = withContext(Dispatchers.IO) {
        val bound = db.appMetadataDao().value(BOUND_ACCOUNT_KEY)
        val active = SessionStore(context).userId()
        val accountId = active ?: bound
        Preview(
            boundAccountId = bound,
            activeAccountId = active,
            outstandingSyncOperations = db.syncOperationDao().outstandingCount(),
            pendingBusinessRecords = if (accountId == null) 0 else business.businessDao().countPending(accountId)
        )
    }

    /** Irreversible. Cancels the sync workers first so nothing uploads a half-deleted state. */
    suspend fun switchAccount(
        context: Context,
        db: AgroDatabase,
        business: BusinessLocalDatabase
    ) = withContext(Dispatchers.IO) {
        val workManager = WorkManager.getInstance(context)
        workManager.cancelUniqueWork(SYNC_PERIODIC_WORK)
        workManager.cancelUniqueWork(SYNC_IMMEDIATE_WORK)
        workManager.cancelUniqueWork(BUSINESS_OUTBOX_WORK)
        wipe(db.openHelper.writableDatabase)
        wipe(business.openHelper.writableDatabase)
        SessionStore(context).clear()
    }

    /**
     * Deletes every row but keeps Room's identity table, so the schema is still validated and the
     * database does not have to be deleted while instances are open.
     */
    private fun wipe(database: SupportSQLiteDatabase) {
        database.execSQL("PRAGMA foreign_keys = OFF")
        try {
            val tables = ArrayList<String>()
            database.query(
                "SELECT name FROM sqlite_master WHERE type = 'table' " +
                    "AND name NOT IN ('room_master_table', 'android_metadata', 'sqlite_sequence')"
            ).use { cursor ->
                while (cursor.moveToNext()) tables.add(cursor.getString(0))
            }
            for (table in tables) database.execSQL("DELETE FROM \"$table\"")
        } finally {
            database.execSQL("PRAGMA foreign_keys = ON")
        }
    }
}
