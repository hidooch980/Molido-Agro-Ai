package com.molido.agroai.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SessionStoreLocalProfileTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val store = SessionStore(context)

    @After
    fun tearDown() = store.clear()

    @Test
    fun localProfileHidesTheTokenEvenWhenOneWasCached() {
        store.saveSession("token-1", "user-1")
        assertEquals("token-1", store.accessToken())

        store.saveLocalProfile("local-abc")
        assertEquals("local-abc", store.userId())
        assertNull(store.accessToken())
        assertTrue(store.isLocalProfile())

        // The flag lives in SharedPreferences, so a new instance must behave the same way.
        assertNull(SessionStore(context).accessToken())

        store.saveSession("token-2", "user-2")
        assertFalse(store.isLocalProfile())
        assertEquals("token-2", store.accessToken())
    }
}