package com.molido.agroai.data

import android.content.Context
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DatabaseEncryptionTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val helper = DatabaseEncryption.factory(context)

    @After
    fun tearDown() {
        context.deleteDatabase(FRESH_DB)
        context.deleteDatabase(LEGACY_DB)
    }

    @Test
    fun passphraseIsStableAndThirtyTwoBytes() {
        val first = DatabaseEncryption.passphrase(context)
        DatabaseEncryption.forgetCachedPassphrase()
        val second = DatabaseEncryption.passphrase(context)
        assertEquals(32, first.size)
        assertArrayEquals(first, second)
    }

    @Test
    fun newDatabaseIsEncryptedOnDiskAndStillReadable() {
        context.deleteDatabase(FRESH_DB)
        helper.create(configuration(FRESH_DB, 1)).use { open ->
            open.writableDatabase.execSQL("INSERT INTO notes (value) VALUES ('secret')")
        }

        val file = context.getDatabasePath(FRESH_DB)
        assertTrue(file.length() > 0)
        assertFalse("a fresh database must not be a plaintext SQLite file", DatabaseEncryption.isLegacyPlaintext(file))

        helper.create(configuration(FRESH_DB, 1)).use { open ->
            open.readableDatabase.query("SELECT value FROM notes").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("secret", cursor.getString(0))
            }
        }
    }

    @Test
    fun legacyPlaintextDatabaseStillOpensWithoutAKey() {
        context.deleteDatabase(LEGACY_DB)
        val file = context.getDatabasePath(LEGACY_DB)
        file.parentFile?.mkdirs()
        android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(file, null).use { legacy ->
            legacy.execSQL("CREATE TABLE notes (value TEXT)")
            legacy.execSQL("INSERT INTO notes (value) VALUES ('old')")
            // A real pre-encryption database carries a user_version; without it the helper would
            // treat the file as empty and run onCreate again on a table that already exists.
            legacy.version = 1
        }
        assertTrue(DatabaseEncryption.isLegacyPlaintext(file))

        helper.create(configuration(LEGACY_DB, 1)).use { open ->
            open.readableDatabase.query("SELECT value FROM notes").use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("old", cursor.getString(0))
            }
        }
    }

    private fun configuration(name: String, version: Int): SupportSQLiteOpenHelper.Configuration =
        SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name)
            .callback(object : SupportSQLiteOpenHelper.Callback(version) {
                override fun onCreate(db: SupportSQLiteDatabase) {
                    db.execSQL("CREATE TABLE notes (value TEXT)")
                }

                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            })
            .build()

    private companion object {
        private const val FRESH_DB = "molido-encryption-fresh.db"
        private const val LEGACY_DB = "molido-encryption-legacy.db"
    }
}