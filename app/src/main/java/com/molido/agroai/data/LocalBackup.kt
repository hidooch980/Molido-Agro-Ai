package com.molido.agroai.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.util.Base64
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * Single-file snapshot: every Room table is dumped to JSON and wrapped in a small envelope.
 * [export]/[restore] encrypt the dump with the Keystore-backed payload key, so that file is only
 * readable on the device that produced it (a wiped Keystore makes it unrecoverable, by design).
 * [exportDump]/[restoreDump] are the plain-text building blocks used by the passphrase-protected
 * GitHub backup, which is the cross-device path.
 */
object LocalBackup {
    private const val FORMAT = 1
    private const val BLOB_PREFIX = "b64:"
    private val SKIPPED_TABLES = setOf("room_master_table", "android_metadata", "sqlite_sequence")

    suspend fun export(context: Context, database: AgroDatabase): String = withContext(Dispatchers.IO) {
        JSONObject()
            .put("format", FORMAT)
            .put("createdAtEpochMillis", System.currentTimeMillis())
            .put("payload", SyncPayloadCipher.encrypt(context, exportDump(database)))
            .toString()
    }

    /** Replaces the local tables with the snapshot and returns the number of restored rows. */
    suspend fun restore(context: Context, database: AgroDatabase, envelope: String): Int = withContext(Dispatchers.IO) {
        val root = JSONObject(envelope)
        require(root.optInt("format") == FORMAT) { "نسخه فایل پشتیبان پشتیبانی نمی‌شود." }
        restoreDump(database, SyncPayloadCipher.decrypt(root.getString("payload")))
    }

    /** Plain-text table dump. Only for encryption by a passphrase-protected layer. */
    suspend fun exportDump(database: AgroDatabase): String = withContext(Dispatchers.IO) {
        val sqlite = database.openHelper.writableDatabase
        val dump = JSONArray()
        for (table in tables(sqlite)) {
            dump.put(JSONObject().put("table", table).put("rows", dumpTable(sqlite, table)))
        }
        dump.toString()
    }

    /**
     * Restores a plain-text dump produced by [exportDump]. The account binding of the receiving
     * device wins, so importing someone else's snapshot cannot silently rebind this phone.
     */
    suspend fun restoreDump(database: AgroDatabase, dumpJson: String): Int = withContext(Dispatchers.IO) {
        val dump = JSONArray(dumpJson)
        val sqlite = database.openHelper.writableDatabase
        val boundAccountBefore = runCatching {
            sqlite.query("SELECT value FROM app_metadata WHERE key = 'bound_account_id' LIMIT 1").use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0) else null
            }
        }.getOrNull()
        var dumpBoundAccount: String? = null
        for (index in 0 until dump.length()) {
            val table = dump.getJSONObject(index)
            if (table.getString("table") != "app_metadata") continue
            val rows = table.getJSONArray("rows")
            for (rowIndex in 0 until rows.length()) {
                val row = rows.getJSONObject(rowIndex)
                if (row.optString("key") == "bound_account_id") {
                    dumpBoundAccount = row.optString("value").takeIf { it.isNotBlank() }
                }
            }
        }
        if (boundAccountBefore != null && dumpBoundAccount != null && boundAccountBefore != dumpBoundAccount) {
            throw IllegalStateException("این پشتیبان به حساب دیگری تعلق دارد؛ بازیابی روی این دستگاه مجاز نیست.")
        }
        var restored = 0
        sqlite.beginTransaction()
        try {
            for (index in 0 until dump.length()) {
                val table = dump.getJSONObject(index).getString("table")
                if (table in SKIPPED_TABLES) continue
                sqlite.execSQL("DELETE FROM \"$table\"")
                val rows = dump.getJSONObject(index).getJSONArray("rows")
                for (rowIndex in 0 until rows.length()) {
                    val row = rows.getJSONObject(rowIndex)
                    val values = ContentValues()
                    for (column in row.keys()) {
                        when (val value = row.get(column)) {
                            is Int -> values.put(column, value)
                            is Long -> values.put(column, value)
                            is Double -> values.put(column, value)
                            is Boolean -> values.put(column, if (value) 1 else 0)
                            is String -> if (value.startsWith(BLOB_PREFIX)) {
                                values.put(column, Base64.decode(value.removePrefix(BLOB_PREFIX), Base64.NO_WRAP))
                            } else {
                                values.put(column, value)
                            }
                            else -> values.putNull(column)
                        }
                    }
                    sqlite.insert(table, SQLiteDatabase.CONFLICT_REPLACE, values)
                }
                restored += rows.length()
            }
            // The receiving device keeps its own binding; only a fresh device adopts the dump's.
            if (boundAccountBefore != null) {
                sqlite.execSQL("DELETE FROM app_metadata WHERE key = 'bound_account_id'")
                sqlite.execSQL(
                    "INSERT INTO app_metadata(key, value) VALUES('bound_account_id', ?)",
                    arrayOf<Any?>(boundAccountBefore)
                )
            }
            sqlite.setTransactionSuccessful()
        } finally {
            sqlite.endTransaction()
        }
        // Room installs per-table triggers that log these writes, so every observer refreshes
        // without an explicit invalidation call.
        restored
    }

    private fun tables(sqlite: SupportSQLiteDatabase): List<String> {
        val names = mutableListOf<String>()
        sqlite.query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").use { cursor ->
            while (cursor.moveToNext()) {
                val name = cursor.getString(0)
                if (name !in SKIPPED_TABLES && !name.startsWith("sqlite_")) names += name
            }
        }
        return names
    }

    private fun dumpTable(sqlite: SupportSQLiteDatabase, table: String): JSONArray {
        val rows = JSONArray()
        sqlite.query("SELECT * FROM \"$table\"").use { cursor ->
            val columns = cursor.columnNames
            while (cursor.moveToNext()) {
                val row = JSONObject()
                for (index in columns.indices) {
                    val column = columns[index]
                    when (cursor.getType(index)) {
                        Cursor.FIELD_TYPE_NULL -> row.put(column, JSONObject.NULL)
                        Cursor.FIELD_TYPE_INTEGER -> row.put(column, cursor.getLong(index))
                        Cursor.FIELD_TYPE_FLOAT -> row.put(column, cursor.getDouble(index))
                        Cursor.FIELD_TYPE_BLOB -> row.put(column, BLOB_PREFIX + Base64.encodeToString(cursor.getBlob(index), Base64.NO_WRAP))
                        else -> row.put(column, cursor.getString(index))
                    }
                }
                rows.put(row)
            }
        }
        return rows
    }
}