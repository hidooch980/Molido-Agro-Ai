package com.molido.agroai.data

import android.content.Context
import android.net.Uri
import com.molido.agroai.BuildConfig

/**
 * Base URL of the self-hosted sync API. CI can bake one in through BuildConfig.SYNC_BASE_URL, but
 * the published APK ships without it, so the user can point the app at their own server from the
 * "اتصال به سرور" panel. The URL is not a secret; only the token and payloads are encrypted.
 */
object ServerConfig {
    private const val PREFS = "molido_server_config"
    private const val KEY_BASE_URL = "base_url"

    fun saved(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_BASE_URL, "").orEmpty()

    fun baseUrl(context: Context): String =
        (saved(context).ifBlank { BuildConfig.SYNC_BASE_URL.trim() }).trimEnd('/')

    /** Accepts "example.com" and normalises to https; plain http is allowed only for the loopback host. */
    fun normalize(raw: String): String? {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isEmpty()) return null
        val candidate = when {
            trimmed.startsWith("https://") || trimmed.startsWith("http://") -> trimmed
            else -> "https://$trimmed"
        }
        val uri = runCatching { Uri.parse(candidate) }.getOrNull() ?: return null
        val host = uri.host?.lowercase() ?: return null
        if (!uri.path.isNullOrEmpty() || uri.query != null) return null
        val loopback = host == "127.0.0.1" || host == "localhost"
        return when {
            candidate.startsWith("https://") && host.contains('.') -> candidate
            loopback && candidate.startsWith("http://") -> candidate
            else -> null
        }
    }

    fun save(context: Context, raw: String): Boolean {
        val normalized = normalize(raw) ?: return false
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_BASE_URL, normalized).apply()
        return true
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_BASE_URL).apply()
    }
}