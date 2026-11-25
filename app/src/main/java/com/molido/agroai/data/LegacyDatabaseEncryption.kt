package com.molido.agroai.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import java.io.File

/**
 * Converts a database written by a pre-encryption release into a SQLCipher database.
 *
 * The rewrite never touches the original file until the copy is complete and verified: the rows
 * are copied into a sibling database, the copy is reopened with its key and compared table by
 * table, and only then are the files swapped. The plaintext file is kept next to the new one as
 * `<name>.plaintext-backup` so an operator can still recover manually. Any failure deletes the
 * copy and leaves the original exactly as it was, which keeps the pre-encryption behaviour.
 */
object LegacyDatabaseEncryption {
    const val BACKUP_SUFFIX = ".plaintext-backup"
    private const val PREFS = "molido_db_crypto"
    private const val FAILED_PREFIX = "conversion-failed:"
    private const val RETRY_AFTER_MS = 24L * 60L * 60L * 1000L

    /** Returns true when the database on disk is encrypted after the call. */
    fun migrate(context: Context, name: String): Boolean {
        val app = context.applicationContext
        val file = app.getDatabasePath(name)
        if (!DatabaseEncryption.isLegacyPlaintext(file)) return false
        if (failedRecently(app, name)) return false
        return try {
            convert(app, name, file)
        } catch (_: Throwable) {
            markFailed(app, name)
            false
        }
    }

    private fun convert(context: Context, name: String, file: File): Boolean {
        val copyName = "$name.converting"
        val copyFile = context.getDatabasePath(copyName)
        context.deleteDatabase(copyName)
        val key = DatabaseEncryption.passphrase(context)
        val counts = LinkedHashMap<String, Int>()
        var version = 1

        val source = SQLiteDatabase.openDatabase(file.absolutePath, null, SQLiteDatabase.OPEN_READONLY)
        try {
            version = source.version.coerceAtLeast(1)
            val schema = schemaStatements(source)
            val tables = tables(source)
            for (table in tables) counts[table] = count(source, table)

            val targetHelper = encryptedHelper(context, copyName, version, key)
            try {
                val target = targetHelper.writableDatabase
                target.execSQL("PRAGMA foreign_keys = OFF")
                for (statement in schema) target.execSQL(statement)
                for (table in tables) copyRows(source, target, table)
                target.version = version
            } finally {
                targetHelper.close()
            }
        } finally {
            source.close()
        }

        verify(context, copyName, version, key, counts)
        swap(context, name, file, context.getDatabasePath(copyName))
        return true
    }

    /** DDL in creation order: tables first, then other objects, then indexes. */
    private fun schemaStatements(source: SQLiteDatabase): List<String> {
        val statements = ArrayList<String>()
        source.rawQuery(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' " +
                "ORDER BY CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 3 ELSE 2 END",
            null
        ).use { cursor ->
            while (cursor.moveToNext()) statements.add(cursor.getString(0))
        }
        return statements
    }

    private fun tables(source: SQLiteDatabase): List<String> {
        val tables = ArrayList<String>()
        source.rawQuery(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
            null
        ).use { cursor ->
            while (cursor.moveToNext()) tables.add(cursor.getString(0))
        }
        return tables
    }

    private fun count(source: SQLiteDatabase, table: String): Int =
        source.rawQuery("SELECT count(*) FROM \"$table\"", null).use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }

    private fun count(source: SupportSQLiteDatabase, table: String): Int =
        source.query("SELECT count(*) FROM \"$table\"").use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }

    private fun copyRows(source: SQLiteDatabase, target: SupportSQLiteDatabase, table: String) {
        source.rawQuery("SELECT * FROM \"$table\"", null).use { cursor ->
            val columns = cursor.columnNames
            while (cursor.moveToNext()) {
                val values = ContentValues(columns.size)
                for (index in columns.indices) {
                    when (cursor.getType(index)) {
                        android.database.Cursor.FIELD_TYPE_NULL -> values.putNull(columns[index])
                        android.database.Cursor.FIELD_TYPE_INTEGER -> values.put(columns[index], cursor.getLong(index))
                        android.database.Cursor.FIELD_TYPE_FLOAT -> values.put(columns[index], cursor.getDouble(index))
                        android.database.Cursor.FIELD_TYPE_BLOB -> values.put(columns[index], cursor.getBlob(index))
                        else -> values.put(columns[index], cursor.getString(index))
                    }
                }
                target.insert(table, SQLiteDatabase.CONFLICT_NONE, values)
            }
        }
    }

    private fun verify(context: Context, copyName: String, version: Int, key: ByteArray, expected: Map<String, Int>) {
        val helper = encryptedHelper(context, copyName, version, key)
        try {
            val database = helper.readableDatabase
            val integrity = database.query("PRAGMA integrity_check").use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0) else "no result"
            }
            check(integrity == "ok") { "integrity check failed: $integrity" }
            check(database.version == version) { "user_version changed during the copy" }
            for ((table, rows) in expected) {
                check(count(database, table) == rows) { "row count mismatch in $table" }
            }
        } finally {
            helper.close()
        }
    }

    private fun swap(context: Context, name: String, file: File, copy: File) {
        val parent = file.parentFile ?: error("database directory is missing")
        val backup = File(parent, name + BACKUP_SUFFIX)
        val backupWal = File(parent, name + BACKUP_SUFFIX + "-wal")
        val backupShm = File(parent, name + BACKUP_SUFFIX + "-shm")
        backup.delete()
        backupWal.delete()
        backupShm.delete()
        check(file.renameTo(backup)) { "could not move the plaintext database aside" }
        for (suffix in listOf("-wal", "-shm")) {
            val stale = File(parent, name + suffix)
            if (stale.isFile) stale.renameTo(File(parent, name + BACKUP_SUFFIX + suffix))
        }
        if (!copy.renameTo(file)) {
            backup.renameTo(file)
            error("could not install the encrypted database")
        }
        context.deleteDatabase("$name.converting")
    }

    private fun encryptedHelper(context: Context, name: String, version: Int, key: ByteArray): SupportSQLiteOpenHelper =
        SupportOpenHelperFactory(key).create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name(name)
                .callback(object : SupportSQLiteOpenHelper.Callback(version) {
                    override fun onCreate(db: SupportSQLiteDatabase) = Unit
                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
                })
                .build()
        )

    private fun failedRecently(context: Context, name: String): Boolean {
        val last = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getLong(FAILED_PREFIX + name, 0L)
        return last > 0L && System.currentTimeMillis() - last < RETRY_AFTER_MS
    }

    private fun markFailed(context: Context, name: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong(FAILED_PREFIX + name, System.currentTimeMillis()).commit()
    }
}
