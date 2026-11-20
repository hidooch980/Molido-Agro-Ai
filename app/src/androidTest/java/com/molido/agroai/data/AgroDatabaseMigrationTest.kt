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
    fun migrationsOneToSevenPreserveLegacyDataAndCreateCrmErpStore() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val name = "agro-migration-${UUID.randomUUID()}.db"
        val configuration = SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name)
            .callback(object : SupportSQLiteOpenHelper.Callback(1) {
                override fun onCreate(db: androidx.sqlite.db.SupportSQLiteDatabase) {
                    db.execSQL("CREATE TABLE crop_observations (id TEXT NOT NULL PRIMARY KEY, cropCode TEXT NOT NULL, greenhouseId TEXT, observedAtEpochMillis INTEGER NOT NULL, growthStage TEXT NOT NULL, temperatureCelsius REAL, humidityPercent REAL, soilPh REAL, soilEc REAL, irrigationLiters REAL, notes TEXT NOT NULL, photoUri TEXT, source TEXT NOT NULL, syncState TEXT NOT NULL)")
                    db.execSQL("INSERT INTO crop_observations VALUES ('observation-1','cucumber',NULL,10,'seedling',NULL,NULL,NULL,NULL,NULL,'legacy observation',NULL,'MANUAL','LOCAL_ONLY')")
                }
                override fun onUpgrade(db: androidx.sqlite.db.SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            }).build()
        val helper = FrameworkSQLiteOpenHelperFactory().create(configuration)
        try {
            val db = helper.writableDatabase
            AgroDatabase.MIGRATION_1_2.migrate(db)
            AgroDatabase.MIGRATION_2_3.migrate(db)
            db.execSQL("INSERT INTO sync_operations VALUES ('legacy-1','CREATE:greenhouse:1','greenhouse','1','CREATE','{}','PENDING',0,1,1,NULL)")
            AgroDatabase.MIGRATION_3_4.migrate(db)
            AgroDatabase.MIGRATION_4_5.migrate(db)
            AgroDatabase.MIGRATION_5_6.migrate(db)
            AgroDatabase.MIGRATION_6_7.migrate(db)
            val metadata = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='app_metadata'")
            val inbox = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_inbox'")
            val business = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='business_records'")
            val legacy = db.query("SELECT id, baseVersion FROM sync_operations WHERE id='legacy-1'")
            val observation = db.query("SELECT id, notes FROM crop_observations WHERE id='observation-1'")
            assertTrue(metadata.moveToFirst())
            assertTrue(inbox.moveToFirst())
            assertTrue(business.moveToFirst())
            assertTrue(legacy.moveToFirst())
            assertEquals("legacy-1", legacy.getString(0))
            assertEquals(0, legacy.getInt(1))
            assertTrue(observation.moveToFirst())
            assertEquals("legacy observation", observation.getString(1))
            metadata.close(); inbox.close(); business.close(); legacy.close(); observation.close()
        } finally {
            helper.close()
            context.deleteDatabase(name)
        }
    }
}
