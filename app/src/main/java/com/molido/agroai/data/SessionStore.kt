package com.molido.agroai.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Stores bearer credentials encrypted with an Android Keystore AES-GCM key. */
class SessionStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("molido_secure_session", Context.MODE_PRIVATE)
    private val alias = "molido.session.aes.v1"

    fun saveAccessToken(token: String) = saveSecret("access_token", token)
    fun saveUserId(userId: String) = saveSecret("user_id", userId)
    fun saveSession(token: String, userId: String) {
        require(token.isNotBlank() && userId.isNotBlank())
        saveSecret("access_token", token)
        saveSecret("user_id", userId)
    }
    fun accessToken(): String? = readSecret("access_token")
    fun userId(): String? = readSecret("user_id")
    fun clear() { prefs.edit().clear().apply() }

    private fun saveSecret(name: String, value: String) {
        require(value.isNotBlank() && value.length <= 8192)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val encoded = Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)
        check(prefs.edit().putString(name, encoded).commit()) { "Could not persist session" }
    }

    private fun readSecret(name: String): String? {
        val value = prefs.getString(name, null) ?: return null
        return try {
            val bytes = Base64.decode(value, Base64.NO_WRAP)
            require(bytes.size > 12)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
        } catch (_: Exception) { clear(); null }
    }

    private fun getOrCreateKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build())
        return generator.generateKey()
    }
}

object SyncPayloadCipher {
    private const val PREFIX = "enc:v1:"
    private const val ALIAS = "molido.outbox.aes.v1"

    fun encrypt(context: Context, plainText: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val bytes = cipher.iv + cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
        return PREFIX + Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    fun decrypt(cipherText: String): String {
        if (!cipherText.startsWith(PREFIX)) return cipherText // Backward compatibility for pre-encryption outbox rows.
        val bytes = Base64.decode(cipherText.removePrefix(PREFIX), Base64.NO_WRAP)
        require(bytes.size > 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        return String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).build())
        return generator.generateKey()
    }
}
