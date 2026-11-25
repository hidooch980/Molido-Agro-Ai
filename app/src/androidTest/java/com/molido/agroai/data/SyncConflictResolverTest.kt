package com.molido.agroai.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SyncConflictResolverTest {
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
    fun acceptingTheServerVersionAppliesItAndRetiresTheConflictedRow() = runBlocking {
        database.syncOperationDao().enqueue(conflictedOperation())
        val change = remoteChange(version = 2, name = "گلخانه سرور")
        database.syncInboxDao().receive(change)

        SyncConflictResolver(context, database).acceptServerVersion(change)

        assertEquals("گلخانه سرور", database.greenhouseDao().find(ENTITY_ID)?.name)
        assertEquals("RESOLVED_SERVER", database.syncInboxDao().latest("greenhouse", ENTITY_ID)?.state)
        // A row left in CONFLICT would make every later remote change look conflicted again.
        assertNull(database.syncOperationDao().conflictedForEntity("greenhouse", ENTITY_ID))
    }

    @Test
    fun keepingTheDeviceVersionQueuesTheLocalPayloadWithTheServerBaseVersion() = runBlocking {
        database.syncOperationDao().enqueue(conflictedOperation())
        val change = remoteChange(version = 3, name = "گلخانه سرور")
        database.syncInboxDao().receive(change)

        SyncConflictResolver(context, database).keepLocalVersion(change)

        val resent = requireNotNull(database.syncOperationDao().pendingForEntity("greenhouse", ENTITY_ID))
        assertEquals("RESOLVE_LOCAL:greenhouse:$ENTITY_ID:3", resent.idempotencyKey)
        assertEquals(3, resent.baseVersion)
        assertEquals("RESOLVED_LOCAL", database.syncInboxDao().latest("greenhouse", ENTITY_ID)?.state)
        assertNull(database.syncOperationDao().conflictedForEntity("greenhouse", ENTITY_ID))
        // The device version is only re-sent, never applied locally, so no row is written here.
        assertNull(database.greenhouseDao().find(ENTITY_ID))
    }

    private fun conflictedOperation() = SyncOperationEntity(
        id = "conflicted-1",
        idempotencyKey = "CREATE:greenhouse:$ENTITY_ID",
        entityType = "greenhouse",
        entityId = ENTITY_ID,
        operation = "CREATE",
        payloadJson = SyncPayloadCipher.encrypt(context, JSONObject().put("name", "گلخانه دستگاه").put("areaSquareMeters", 12.0).toString()),
        state = "CONFLICT",
        lastError = "Server version conflict"
    )

    private fun remoteChange(version: Int, name: String) = SyncInboxEntity(
        id = "greenhouse:$ENTITY_ID:$version",
        entityType = "greenhouse",
        entityId = ENTITY_ID,
        encryptedPayload = SyncPayloadCipher.encrypt(context, JSONObject().put("name", name).put("areaSquareMeters", 30.0).toString()),
        serverVersion = version,
        updatedAtEpochMillis = 1_700_000_000_000,
        deleted = false,
        state = "CONFLICT"
    )

    private companion object {
        const val ENTITY_ID = "greenhouse-local-1"
    }
}