package com.molido.agroai.data

import java.security.SecureRandom
import java.util.Base64
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * Passphrase-based envelope for backups that leave the device. Unlike the Keystore-backed
 * [SyncPayloadCipher] it can be opened on another phone or after a factory reset, because the key
 * is derived from a passphrase the operator remembers (PBKDF2-HMAC-SHA256 + AES-256-GCM).
 *
 * Wire format, one line, `|` separated: `v1|PBKDF2WithHmacSHA256|<iterations>|<salt>|<nonce>|<ciphertext>`
 * with every binary part Base64 encoded.
 */
object PortableBackupCipher {
    private const val VERSION = "v1"
    private const val KDF = "PBKDF2WithHmacSHA256"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val ITERATIONS = 120_000
    private const val MIN_ITERATIONS = 10_000
    private const val MAX_ITERATIONS = 1_000_000
    private const val KEY_BITS = 256
    private const val SALT_BYTES = 16
    private const val NONCE_BYTES = 12
    private const val TAG_BITS = 128
    const val MIN_PASSPHRASE = 10

    fun encrypt(plaintext: String, passphrase: String): String {
        require(passphrase.length >= MIN_PASSPHRASE) { "گذرواژه پشتیبان باید حداقل $MIN_PASSPHRASE نویسه باشد." }
        val random = SecureRandom()
        val salt = ByteArray(SALT_BYTES).also(random::nextBytes)
        val nonce = ByteArray(NONCE_BYTES).also(random::nextBytes)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key(passphrase, salt, ITERATIONS), GCMParameterSpec(TAG_BITS, nonce))
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        return listOf(VERSION, KDF, ITERATIONS.toString(), encode(salt), encode(nonce), encode(ciphertext))
            .joinToString("|")
    }

    fun decrypt(envelope: String, passphrase: String): String {
        require(passphrase.isNotEmpty()) { "گذرواژه پشتیبان خالی است." }
        val parts = envelope.trim().split("|")
        require(parts.size == 6) { "فایل پشتیبان معتبر نیست." }
        require(parts[0] == VERSION) { "نسخه فایل پشتیبان پشتیبانی نمی‌شود." }
        require(parts[1] == KDF) { "روش رمزگذاری فایل پشتیبان پشتیبانی نمی‌شود." }
        val iterations = parts[2].toIntOrNull()
        require(iterations != null && iterations in MIN_ITERATIONS..MAX_ITERATIONS) {
            "تعداد تکرار مشتق‌سازی کلید معتبر نیست."
        }
        val salt = decode(parts[3])
        val nonce = decode(parts[4])
        val ciphertext = decode(parts[5])
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(passphrase, salt, iterations), GCMParameterSpec(TAG_BITS, nonce))
        val plaintext = try {
            cipher.doFinal(ciphertext)
        } catch (exception: AEADBadTagException) {
            throw IllegalStateException("گذرواژه نادرست است یا فایل پشتیبان آسیب دیده است.", exception)
        }
        return String(plaintext, Charsets.UTF_8)
    }

    private fun key(passphrase: String, salt: ByteArray, iterations: Int): SecretKeySpec {
        val spec = PBEKeySpec(passphrase.toCharArray(), salt, iterations, KEY_BITS)
        try {
            val encoded = SecretKeyFactory.getInstance(KDF).generateSecret(spec).encoded
            return SecretKeySpec(encoded, "AES")
        } finally {
            spec.clearPassword()
        }
    }

    private fun encode(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)
    private fun decode(value: String): ByteArray = Base64.getDecoder().decode(value)
}
