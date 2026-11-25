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
 * Single-file local snapshot: every Room table is dumped to JSON, the dump is encrypted with the
 * Keystore-backed payload key and wrapped in a small envelope. No server is involved, so the file
 * can be moved to a new device and restored there.
 */
object LocalBackup {
    private const val FORMAT = 1
    private const val BLOB_PREFIX = "b64:"
    private val SKIPPED_TABLES = setOf("room_master_table", "android_metadata", "sqlite_sequence")

    suspend fun export(context: Context, database: AgroDatabase): String = withContext(Dispatchers.IO) {
        val sqlite = database.openHelper.writableDatabase
        val dump = JSONArray()
        for (table in tables(sqlite)) {
            dump.put(JSONObject().put("table", table).put("rows", dumpTable(sqlite, table)))
        }
        JSONObject()
            .put("format", FORMAT)
            .put("createdAtEpochMillis", System.currentTimeMillis())
            .put("payload", SyncPayloadCipher.encrypt(context, dump.toString()))
            .toString()
    }

    /** Replaces the local tables with the snapshot and returns the number of restored rows. */
    suspend fun restore(context: Context, database: AgroDatabase, envelope: String): Int = withContext(Dispatchers.IO) {
        val root = JSONObject(envelope)
        require(root.optInt("format") == FORMAT) { "نسخه فایل پشتیبان پشتیبانی نمی‌شود." }
        val dump = JSONArray(SyncPayloadCipher.decrypt(root.getString("payload")))
        val sqlite = database.openHelper.writableDatabase
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