package com.molido.agroai.data

import android.content.Context
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class AgroDatabaseMigrationTest {
    @Test
    fun migrationsThreeToSixCreateAccountAndInboxTablesWithoutDroppingRows() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val name = "agro-migration-${UUID.randomUUID()}.db"
        val configuration = SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name)
            .callback(object : SupportSQLiteOpenHelper.Callback(3) {
                override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                    db.execSQL("CREATE TABLE sync_operations (id TEXT NOT NULL PRIMARY KEY, idempotencyKey TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, operation TEXT NOT NULL, payloadJson TEXT NOT NULL, state TEXT NOT NULL, attemptCount INTEGER NOT NULL, createdAtEpochMillis INTEGER NOT NULL, nextAttemptAtEpochMillis INTEGER NOT NULL, lastError TEXT)")
                    db.execSQL("INSERT INTO sync_operations VALUES ('legacy-1','CREATE:greenhouse:1','greenhouse','1','CREATE','{}','PENDING',0,1,1,NULL)")
                }
                override fun onUpgrade(db: androidx.sqlite.db.SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            }).build()
        val helper = FrameworkSQLiteOpenHelperFactory().create(configuration)
        try {
            val db = helper.writableDatabase
            AgroDatabase.MIGRATION_3_4.migrate(db)
            AgroDatabase.MIGRATION_4_5.migrate(db)
            AgroDatabase.MIGRATION_5_6.migrate(db)
            val metadata = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='app_metadata'")
            val inbox = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_inbox'")
            val legacy = db.query("SELECT id, baseVersion FROM sync_operations WHERE id='legacy-1'")
            assertTrue(metadata.moveToFirst())
            assertTrue(inbox.moveToFirst())
            assertTrue(legacy.moveToFirst())
            assertEquals("legacy-1", legacy.getString(0))
            assertEquals(0, legacy.getInt(1))
            metadata.close(); inbox.close(); legacy.close()
        } finally {
            helper.close()
            context.deleteDatabase(name)
        }
    }
}
