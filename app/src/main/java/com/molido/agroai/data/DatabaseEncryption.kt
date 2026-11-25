package com.molido.agroai.data

import android.content.Context
import android.util.Base64
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import net.zetetic.database.sqlcipher.SupportOpenHelperFactory
import java.io.File
import java.security.SecureRandom

/**
 * At-rest encryption for the local Room databases.
 *
 * A 32-byte passphrase is generated once per installation and wrapped by the Keystore-backed
 * [SyncPayloadCipher], so the key material never leaves the app sandbox in clear text. The
 * passphrase is handed to SQLCipher as raw key bytes, which is what the byte[] factory overload
 * expects, so it never appears inside a SQL statement.
 *
 * Databases written before this release are plain files. Opening them with a key would fail, so
 * the file header decides which helper to use: a legacy plaintext file keeps the framework
 * helper and stays readable, while every new database is created encrypted. Converting an
 * existing plaintext file in place needs a verified rewrite (export, integrity check, atomic
 * swap) that this release deliberately does not attempt, because a partial rewrite would lose
 * operator data.
 */
object DatabaseEncryption {
    private const val PREFS = "molido_db_crypto"
    private const val PASSPHRASE = "passphrase"
    private const val KEY_BYTES = 32
    private val PLAINTEXT_HEADER = byteArrayOf(
        0x53, 0x51, 0x4C, 0x69, 0x74, 0x65, 0x20, 0x66, 0x6F, 0x72, 0x6D, 0x61, 0x74, 0x20, 0x33, 0x00
    )

    @Volatile
    private var cachedPassphrase: ByteArray? = null

    @Volatile
    private var nativeLoaded = false

    fun factory(context: Context): SupportSQLiteOpenHelper.Factory = Factory(context.applicationContext)

    private class Factory(private val context: Context) : SupportSQLiteOpenHelper.Factory {
        override fun create(configuration: SupportSQLiteOpenHelper.Configuration): SupportSQLiteOpenHelper {
            val name = configuration.name
            if (name != null && isLegacyPlaintext(context.getDatabasePath(name))) {
                // Best effort: copy the plaintext rows into an encrypted database and verify the
                // copy before swapping. Until that succeeds the file must stay plaintext, so a
                // failure keeps the framework helper.
                if (!LegacyDatabaseEncryption.migrate(context, name)) {
                    return FrameworkSQLiteOpenHelperFactory().create(configuration)
                }
            }
            loadNativeLibrary()
            return SupportOpenHelperFactory(passphrase(context)).create(configuration)
        }
    }

    /** True when the file on disk is an unencrypted SQLite database written by an older release. */
    fun isLegacyPlaintext(file: File): Boolean {
        if (!file.isFile || file.length() < PLAINTEXT_HEADER.size) return false
        val header = ByteArray(PLAINTEXT_HEADER.size)
        file.inputStream().use { stream ->
            var read = 0
            while (read < header.size) {
                val count = stream.read(header, read, header.size - read)
                if (count <= 0) return false
                read += count
            }
        }
        return header.contentEquals(PLAINTEXT_HEADER)
    }

    fun passphrase(context: Context): ByteArray {
        cachedPassphrase?.let { return it }
        synchronized(this) {
            cachedPassphrase?.let { return it }
            val app = context.applicationContext
            val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val stored = prefs.getString(PASSPHRASE, null)
            val value = if (stored != null) {
                Base64.decode(SyncPayloadCipher.decrypt(stored), Base64.NO_WRAP)
            } else {
                ByteArray(KEY_BYTES).also { SecureRandom().nextBytes(it) }.also { created ->
                    val wrapped = SyncPayloadCipher.encrypt(app, Base64.encodeToString(created, Base64.NO_WRAP))
                    check(prefs.edit().putString(PASSPHRASE, wrapped).commit()) { "Could not persist the database passphrase" }
                }
            }
            require(value.size == KEY_BYTES) { "Unexpected database passphrase length: ${value.size}" }
            cachedPassphrase = value
            return value
        }
    }

    /** Drops the cached passphrase; used by the test suite and by an explicit "clear data" path. */
    fun forgetCachedPassphrase() {
        cachedPassphrase = null
    }

    private fun loadNativeLibrary() {
        if (nativeLoaded) return
        synchronized(this) {
            if (nativeLoaded) return
            System.loadLibrary("sqlcipher")
            nativeLoaded = true
        }
    }
}
