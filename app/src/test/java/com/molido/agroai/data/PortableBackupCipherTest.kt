package com.molido.agroai.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PortableBackupCipherTest {
    private val passphrase = "گلخانه-سبز-1404"

    @Test
    fun encryptThenDecryptReturnsTheSameText() {
        val plaintext = """[{"table":"greenhouses","rows":[{"name":"گلخانه یک"}]}]"""
        val envelope = PortableBackupCipher.encrypt(plaintext, passphrase)
        assertEquals(plaintext, PortableBackupCipher.decrypt(envelope, passphrase))
    }

    @Test
    fun envelopeDoesNotContainThePlaintext() {
        val envelope = PortableBackupCipher.encrypt("secret-greenhouse-name", passphrase)
        assertFalse(envelope.contains("secret-greenhouse-name"))
        assertTrue(envelope.startsWith("v1|PBKDF2WithHmacSHA256|"))
    }

    @Test
    fun wrongPassphraseIsRejected() {
        val envelope = PortableBackupCipher.encrypt("data", passphrase)
        val error = assertThrows(IllegalStateException::class.java) {
            PortableBackupCipher.decrypt(envelope, "گذرواژه-اشتباه-1404")
        }
        assertTrue(error.message!!.contains("گذرواژه نادرست"))
    }

    @Test
    fun tamperedCiphertextIsRejected() {
        val envelope = PortableBackupCipher.encrypt("data", passphrase)
        val parts = envelope.split("|").toMutableList()
        val last = parts.last()
        parts[parts.size - 1] = if (last.startsWith("A")) "B" + last.drop(1) else "A" + last.drop(1)
        assertThrows(RuntimeException::class.java) {
            PortableBackupCipher.decrypt(parts.joinToString("|"), passphrase)
        }
    }

    @Test
    fun shortPassphraseIsRefused() {
        assertThrows(IllegalArgumentException::class.java) {
            PortableBackupCipher.encrypt("data", "short")
        }
    }

    @Test
    fun malformedEnvelopeIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            PortableBackupCipher.decrypt("not-a-backup", passphrase)
        }
    }

    @Test
    fun repositoryAndTokenValidation() {
        assertTrue(GitHubBackup.isValidRepository("hidooch980/Molido-Agro-Ai"))
        assertFalse(GitHubBackup.isValidRepository("no-slash"))
        assertFalse(GitHubBackup.isValidRepository("owner/"))
        assertTrue(GitHubBackup.isValidToken("ghp_" + "a".repeat(30)))
        assertFalse(GitHubBackup.isValidToken("short"))
        assertFalse(GitHubBackup.isValidToken("has space inside token value"))
    }

    @Test
    fun backupFileNameSortsChronologically() {
        val first = GitHubBackup.newFileName(java.time.Instant.parse("2026-01-02T03:04:05Z"))
        val second = GitHubBackup.newFileName(java.time.Instant.parse("2026-01-02T03:04:06Z"))
        assertEquals("molido-backup-20260102-030405.json", first)
        assertTrue(second > first)
    }
}
