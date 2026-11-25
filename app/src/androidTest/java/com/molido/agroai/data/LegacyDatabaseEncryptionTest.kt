package com.molido.agroai.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class LegacyDatabaseEncryptionTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @After
    fun tearDown() {
        for (suffix in listOf("", LegacyDatabaseEncryption.BACKUP_SUFFIX, ".converting", "-wal", "-shm")) {
            for (name in listOf(LEGACY_DB, ENCRYPTED_DB)) {
                context.deleteDatabase(name + suffix)
                File(context.getDatabasePath(name).parentFile, name + suffix).delete()
            }
        }
        context.getSharedPreferences("molido_db_crypto", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun convertsAPlaintextDatabaseAndKeepsABackup() {
        context.deleteDatabase(LEGACY_DB)
        val file = context.getDatabasePath(LEGACY_DB)
        file.parentFile?.mkdirs()
        SQLiteDatabase.openDatabase(file.absolutePath, null, SQLiteDatabase.CREATE_IF_NECESSARY).use { legacy ->
            legacy.execSQL("CREATE TABLE notes (value TEXT)")
            legacy.execSQL("CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT, weight REAL)")
            legacy.execSQL("CREATE INDEX index_notes_value ON notes (value)")
            legacy.execSQL("INSERT INTO notes (value) VALUES ('first')")
            legacy.execSQL("INSERT INTO notes (value) VALUES ('second')")
            legacy.execSQL("INSERT INTO notes (value) VALUES (NULL)")
            legacy.execSQL("INSERT INTO tags (id, label, weight) VALUES (1, 'green', 2.5)")
            legacy.version = 3
        }
        assertTrue(DatabaseEncryption.isLegacyPlaintext(file))

        assertTrue(LegacyDatabaseEncryption.migrate(context, LEGACY_DB))

        assertFalse("the converted database must be encrypted", DatabaseEncryption.isLegacyPlaintext(file))
        val backup = File(file.parentFile, LEGACY_DB + LegacyDatabaseEncryption.BACKUP_SUFFIX)
        assertTrue(backup.isFile)
        assertTrue(DatabaseEncryption.isLegacyPlaintext(backup))
        assertFalse(File(file.parentFile, LEGACY_DB + ".converting").exists())

        val helper = DatabaseEncryption.factory(context).create(configuration(LEGACY_DB, 3))
        try {
            val database = helper.readableDatabase
            assertEquals(3, database.version)
            assertEquals(3, count(database, "notes"))
            assertEquals(1, count(database, "tags"))
            database.query("SELECT value FROM notes WHERE value = 'second'").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("second", cursor.getString(0))
            }
            database.query("SELECT weight FROM tags WHERE id = 1").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(2.5, cursor.getDouble(0), 0.0001)
            }
        } finally {
            helper.close()
        }

        // A second run must be a no-op: the database is already encrypted.
        assertFalse(LegacyDatabaseEncryption.migrate(context, LEGACY_DB))
    }

    @Test
    fun leavesAnAlreadyEncryptedDatabaseAlone() {
        context.deleteDatabase(ENCRYPTED_DB)
        val helper = DatabaseEncryption.factory(context).create(configuration(ENCRYPTED_DB, 1))
        try {
            helper.writableDatabase.execSQL("INSERT INTO notes (value) VALUES ('kept')")
        } finally {
            helper.close()
        }

        val file = context.getDatabasePath(ENCRYPTED_DB)
        assertFalse(DatabaseEncryption.isLegacyPlaintext(file))
        assertFalse(LegacyDatabaseEncryption.migrate(context, ENCRYPTED_DB))
        assertFalse(File(file.parentFile, ENCRYPTED_DB + LegacyDatabaseEncryption.BACKUP_SUFFIX).exists())

        val reopened = DatabaseEncryption.factory(context).create(configuration(ENCRYPTED_DB, 1))
        try {
            assertEquals(1, count(reopened.readableDatabase, "notes"))
        } finally {
            reopened.close()
        }
    }

    private fun count(database: SupportSQLiteDatabase, table: String): Int =
        database.query("SELECT count(*) FROM \"$table\"").use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }

    private fun configuration(name: String, version: Int): SupportSQLiteOpenHelper.Configuration =
        SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name)
            .callback(object : SupportSQLiteOpenHelper.Callback(version) {
                override fun onCreate(db: SupportSQLiteDatabase) {
                    db.execSQL("CREATE TABLE IF NOT EXISTS notes (value TEXT)")
                }

                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            })
            .build()

    private companion object {
        private const val LEGACY_DB = "molido-legacy-conversion.db"
        private const val ENCRYPTED_DB = "molido-legacy-encrypted.db"
    }
}
