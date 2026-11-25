package com.molido.agroai.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AccountSwitchTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private lateinit var db: AgroDatabase
    private lateinit var business: BusinessLocalDatabase

    @Before
    fun setUp() {
        context.deleteDatabase(AGRO_DB)
        context.deleteDatabase(BUSINESS_DB)
        SessionStore(context).clear()
        db = Room.databaseBuilder(context, AgroDatabase::class.java, AGRO_DB)
            .openHelperFactory(DatabaseEncryption.factory(context))
            .addMigrations(
                AgroDatabase.MIGRATION_1_2, AgroDatabase.MIGRATION_2_3, AgroDatabase.MIGRATION_3_4,
                AgroDatabase.MIGRATION_4_5, AgroDatabase.MIGRATION_5_6, AgroDatabase.MIGRATION_6_7
            )
            .build()
        business = Room.databaseBuilder(context, BusinessLocalDatabase::class.java, BUSINESS_DB)
            .openHelperFactory(DatabaseEncryption.factory(context))
            .build()
    }

    @After
    fun tearDown() {
        db.close()
        business.close()
        context.deleteDatabase(AGRO_DB)
        context.deleteDatabase(BUSINESS_DB)
        SessionStore(context).clear()
    }

    @Test
    fun previewReportsUnsyncedWorkBeforeAnythingIsDeleted() = runBlocking {
        db.bindToAccount(ACCOUNT_A)
        db.syncOperationDao().enqueue(
            SyncOperationEntity(
                id = "op-1",
                idempotencyKey = "idem-1",
                entityType = "greenhouse",
                entityId = "g-1",
                operation = "UPSERT",
                payloadJson = "{}"
            )
        )
        business.businessDao().put(
            BusinessLocalRecord(
                id = "biz-1",
                accountId = ACCOUNT_A,
                entityType = "crm.lead",
                entityId = "lead-1",
                encryptedPayload = "cipher"
            )
        )

        val preview = AccountSwitch.preview(context, db, business)

        assertEquals(ACCOUNT_A, preview.boundAccountId)
        assertEquals(1, preview.outstandingSyncOperations)
        assertEquals(1, preview.pendingBusinessRecords)
        assertTrue(preview.hasUnsyncedWork)
        assertEquals(1, count("sync_operations"))
    }

    @Test
    fun switchingWipesEveryRowAndUnbindsTheDevice() = runBlocking {
        db.bindToAccount(ACCOUNT_A)
        SessionStore(context).saveLocalProfile(ACCOUNT_A)
        db.greenhouseDao().insert(GreenhouseEntity("g-1", "گلخانه یک", 100.0, "تهران"))
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { db.bindToAccount(ACCOUNT_B) }
        }

        AccountSwitch.switchAccount(context, db, business)

        assertNull(db.appMetadataDao().value(AccountSwitch.BOUND_ACCOUNT_KEY))
        assertNull(SessionStore(context).userId())
        assertFalse(SessionStore(context).isLocalProfile())
        assertEquals(0, count("greenhouses"))
        assertEquals(0, count("sync_operations"))
        // The device is free again, so another account can bind without an exception.
        db.bindToAccount(ACCOUNT_B)
        assertEquals(ACCOUNT_B, db.appMetadataDao().value(AccountSwitch.BOUND_ACCOUNT_KEY))
    }

    private fun count(table: String): Int =
        db.openHelper.readableDatabase.query("SELECT count(*) FROM \"$table\"").use { cursor ->
            if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }

    private companion object {
        private const val AGRO_DB = "molido-account-switch.db"
        private const val BUSINESS_DB = "molido-account-switch-business.db"
        private const val ACCOUNT_A = "owner-a"
        private const val ACCOUNT_B = "owner-b"
    }
}
