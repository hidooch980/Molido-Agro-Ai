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
    private val KEY_LOCAL_PROFILE = "local_profile"
    private val KEY_ROLE = "account_role"

    /**
     * The role is not a credential, so it is kept in plain preferences; it is cleared with the
     * session and re-read from `/v1/auth/me` on the next sign-in.
     */
    fun saveRole(role: String?) {
        prefs.edit().apply {
            if (role.isNullOrBlank()) remove(KEY_ROLE) else putString(KEY_ROLE, role)
        }.apply()
    }

    fun role(): String? = prefs.getString(KEY_ROLE, null)

    /**
     * Keystore decrypt operations can take seconds on a cold, software-emulated device, so a
     * decrypted value is remembered for the life of the process. Every read from the UI thread
     * after the first one is therefore a plain map lookup.
     */
    private fun cache(): MutableMap<String, String> = cachedSecrets

    fun saveAccessToken(token: String) = saveSecret("access_token", token)
    fun saveUserId(userId: String) = saveSecret("user_id", userId)
    fun saveSession(token: String, userId: String) {
        require(token.isNotBlank() && userId.isNotBlank())
        saveSecret("access_token", token)
        saveSecret("user_id", userId)
        prefs.edit().putBoolean(KEY_LOCAL_PROFILE, false).remove(KEY_ROLE).commit()
    }

    /**
     * A device-only profile: the user owns the local data without any server account. It stores
     * only the id, so the sync workers see no token and stay idle instead of sending empty requests.
     */
    fun saveLocalProfile(userId: String) {
        require(userId.isNotBlank() && userId.length <= 128)
        saveSecret("user_id", userId)
        prefs.edit().remove("access_token").putBoolean(KEY_LOCAL_PROFILE, true).remove(KEY_ROLE).commit()
        cache().remove("access_token")
    }

    fun isLocalProfile(): Boolean = prefs.getBoolean(KEY_LOCAL_PROFILE, false)

    fun accessToken(): String? = if (isLocalProfile()) null else readSecret("access_token")
    fun userId(): String? = readSecret("user_id")
    fun clear() {
        prefs.edit().clear().apply()
        cache().clear()
    }

    private fun saveSecret(name: String, value: String) {
        require(value.isNotBlank() && value.length <= 8192)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val encoded = Base64.encodeToString(cipher.iv + encrypted, Base64.NO_WRAP)
        check(prefs.edit().putString(name, encoded).commit()) { "Could not persist session" }
        cache()[name] = value
    }

    private fun readSecret(name: String): String? {
        cache()[name]?.let { return it }
        val value = prefs.getString(name, null) ?: return null
        return try {
            val bytes = Base64.decode(value, Base64.NO_WRAP)
            require(bytes.size > 12)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8).also { cache()[name] = it }
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

    private companion object {
        private val cachedSecrets: MutableMap<String, String> = java.util.concurrent.ConcurrentHashMap()
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
