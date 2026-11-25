package com.molido.agroai.data

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
class ServerConfigTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @After
    fun cleanUp() = ServerConfig.clear(context)

    @Test
    fun normalizesHostnamesAndRejectsInsecureOrNestedUrls() {
        assertEquals("https://molido.example.com", ServerConfig.normalize("molido.example.com"))
        assertEquals("https://molido.example.com:8443", ServerConfig.normalize("https://molido.example.com:8443/"))
        assertEquals("http://127.0.0.1:8000", ServerConfig.normalize("http://127.0.0.1:8000"))
        assertNull(ServerConfig.normalize("http://molido.example.com"))
        assertNull(ServerConfig.normalize("https://molido.example.com/api/v1"))
        assertNull(ServerConfig.normalize("   "))
    }

    @Test
    fun savesAndClearsTheServerAddress() {
        assertFalse(ServerConfig.save(context, "ftp://molido.example.com"))
        assertTrue(ServerConfig.save(context, "molido.example.com"))
        assertEquals("https://molido.example.com", ServerConfig.baseUrl(context))
        ServerConfig.clear(context)
        assertEquals("", ServerConfig.saved(context))
    }
}