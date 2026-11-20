package com.molido.agroai.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SyncPayloadCipherTest {
    @Test
    fun sensitivePayloadIsEncryptedAndRoundTripsWithKeystoreKey() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val plain = """{"amount":1250000,"description":"private farm expense"}"""
        val encrypted = SyncPayloadCipher.encrypt(context, plain)
        assertTrue(encrypted.startsWith("enc:v1:"))
        assertTrue(!encrypted.contains("private farm expense"))
        assertEquals(plain, SyncPayloadCipher.decrypt(encrypted))
    }
}
