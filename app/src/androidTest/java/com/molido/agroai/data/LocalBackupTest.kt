package com.molido.agroai.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalBackupTest {
    private lateinit var context: Context
    private lateinit var database: AgroDatabase

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AgroDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun aSnapshotRestoresEveryTableAndKeepsTheContentEncrypted() = runBlocking {
        database.greenhouseDao().upsert(GreenhouseEntity("phone-1", "گلخانه شمالی", 120.5, "تهران"))
        database.financeDao().upsert(
            FinancialEntryEntity(
                id = "entry-1",
                greenhouseId = null,
                type = "EXPENSE",
                category = "کود",
                amount = 4_500_000.0,
                description = "خرید کود"
            )
        )

        val envelope = LocalBackup.export(context, database)
        assertTrue(envelope.startsWith("{"))
        assertTrue("the snapshot must not store readable farm data", !envelope.contains("گلخانه شمالی"))

        database.clearAllTables()
        assertNull(database.greenhouseDao().find("phone-1"))

        val restored = LocalBackup.restore(context, database, envelope)

        assertTrue("expected at least the two seeded rows, restored $restored", restored >= 2)
        assertEquals("گلخانه شمالی", database.greenhouseDao().find("phone-1")?.name)
        assertEquals(120.5, database.greenhouseDao().find("phone-1")?.areaSquareMeters ?: 0.0, 0.001)
    }

    @Test
    fun anEnvelopeFromAnUnknownFormatIsRejected() = runBlocking {
        val failure = runCatching {
            LocalBackup.restore(context, database, "{\"format\":99,\"payload\":\"ignored\"}")
        }.exceptionOrNull()

        assertTrue("unexpected failure type: $failure", failure is IllegalArgumentException)
    }
}