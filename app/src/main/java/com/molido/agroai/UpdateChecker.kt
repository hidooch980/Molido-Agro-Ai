package com.molido.agroai

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

private data class AvailableUpdate(val versionName: String, val versionCode: Int, val apkFile: String, val sha256: String)

@Composable
fun UpdateCheckerCard() {
    val context = LocalContext.current
    var update by remember { mutableStateOf<AvailableUpdate?>(null) }
    var downloaded by remember { mutableStateOf<File?>(null) }
    var status by remember { mutableStateOf("بررسی نسخه جدید…") }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val connection = URL("https://github.com/hidooch980/Molido-Agro-Ai/releases/latest/download/latest.json").openConnection() as HttpURLConnection
                connection.connectTimeout = 8000
                connection.readTimeout = 8000
                try {
                    check(connection.responseCode == 200)
                    val json = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                    AvailableUpdate(json.getString("versionName"), json.getInt("versionCode"), json.getString("apkFile"), json.getString("sha256").lowercase())
                } finally { connection.disconnect() }
            }
        }
        result.onSuccess { candidate ->
            if (candidate.versionCode > BuildConfig.VERSION_CODE) {
                update = candidate
                status = "نسخه \${candidate.versionName} آماده دریافت است."
            } else status = "برنامه به‌روز است."
        }.onFailure { status = "بررسی به‌روزرسانی در حال حاضر ممکن نیست." }
    }

    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Text("به‌روزرسانی برنامه", style = MaterialTheme.typography.titleSmall)
            Text(status, style = MaterialTheme.typography.bodySmall)
            if (update != null && downloaded == null) {
                Button(enabled = !busy, onClick = {
                    val candidate = update ?: return@Button
                    busy = true
                    status = "در حال دریافت و بررسی فایل…"
                    MainScope().launch {
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                require(candidate.apkFile.matches(Regex("[A-Za-z0-9._-]+\\.apk")))
                                val connection = URL("https://github.com/hidooch980/Molido-Agro-Ai/releases/latest/download/\${candidate.apkFile}").openConnection() as HttpURLConnection
                                connection.connectTimeout = 15000
                                connection.readTimeout = 30000
                                connection.instanceFollowRedirects = true
                                try {
                                    check(connection.responseCode == 200)
                                    val dir = File(context.cacheDir, "updates").apply { mkdirs() }
                                    val file = File(dir, "molido-agro-ai-\${candidate.versionCode}.apk")
                                    connection.inputStream.use { input -> file.outputStream().use { output -> input.copyTo(output) } }
                                    val digest = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }
                                    check(digest.equals(candidate.sha256, ignoreCase = true)) { "checksum mismatch" }
                                    file
                                } finally { connection.disconnect() }
                            }
                        }
                        result.onSuccess {
                            downloaded = it
                            status = "دریافت کامل و صحت SHA-256 تأیید شد."
                        }.onFailure { status = "دریافت ناموفق یا فایل نامعتبر است؛ دوباره تلاش کنید." }
                        busy = false
                    }
                }) { Text(if (busy) "در حال دریافت…" else "دریافت به‌روزرسانی") }
            }
            if (downloaded != null) {
                Button(onClick = {
                    val file = downloaded ?: return@Button
                    if (android.os.Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
                        context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:\${context.packageName}")))
                    } else {
                        val uri = FileProvider.getUriForFile(context, "\${context.packageName}.updates", file)
                        context.startActivity(Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(uri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                        })
                    }
                }) { Text("نصب نسخه تأییدشده") }
                Text("اندروید برای نصب APK خارج از فروشگاه، تأیید نهایی کاربر را الزامی می‌کند.", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
