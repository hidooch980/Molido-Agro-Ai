package com.molido.agroai

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import java.io.File
import java.util.UUID

private val PhotoMuted = Color(0xFFB8C8BE)

/**
 * Evidence photo for a diagnosis note. The file stays in app-private storage: nothing is uploaded,
 * and the camera is optional so the panel still works on a device without one.
 */
@Composable
fun PhotoCapture(onCaptured: (File) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var granted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED,
        )
    }
    var cameraOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf<File?>(null) }
    var status by remember { mutableStateOf("برای ثبت شاهد تصویری، دوربین را روشن کنید.") }
    val cameraController = remember { LifecycleCameraController(context) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { result ->
        granted = result
        if (result) {
            cameraOpen = true
        } else {
            status = "بدون اجازه دوربین، عکس گرفته نمی‌شود؛ بقیه پنل کار می‌کند."
        }
    }

    DisposableEffect(cameraOpen, lifecycleOwner) {
        if (cameraOpen) cameraController.bindToLifecycle(lifecycleOwner)
        onDispose { cameraController.unbind() }
    }

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("شاهد تصویری", style = MaterialTheme.typography.bodyMedium)
        Text(status, color = PhotoMuted, style = MaterialTheme.typography.bodySmall)
        if (cameraOpen) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).apply {
                        this.controller = cameraController
                        scaleType = PreviewView.ScaleType.FILL_CENTER
                    }
                },
                modifier = Modifier.fillMaxWidth().height(220.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = !busy, onClick = {
                    val directory = File(context.filesDir, "diagnosis").apply { mkdirs() }
                    val file = File(directory, "${System.currentTimeMillis()}-${UUID.randomUUID()}.jpg")
                    val options = ImageCapture.OutputFileOptions.Builder(file).build()
                    busy = true
                    cameraController.takePicture(
                        options,
                        ContextCompat.getMainExecutor(context),
                        object : ImageCapture.OnImageSavedCallback {
                            override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                busy = false
                                saved = file
                                status = "عکس ذخیره شد؛ فقط روی همین دستگاه می‌ماند."
                                onCaptured(file)
                                cameraOpen = false
                            }

                            override fun onError(exception: ImageCaptureException) {
                                busy = false
                                status = "گرفتن عکس ناموفق بود: ${exception.message}"
                            }
                        },
                    )
                }) { Text(if (busy) "در حال گرفتن عکس…" else "گرفتن عکس") }
                OutlinedButton(enabled = !busy, onClick = { cameraOpen = false }) { Text("بستن دوربین") }
            }
        } else {
            OutlinedButton(onClick = {
                if (granted) {
                    cameraOpen = true
                } else {
                    permission.launch(Manifest.permission.CAMERA)
                }
            }) { Text("روشن کردن دوربین") }
        }

        val bitmap = remember(saved) {
            saved?.let { file -> runCatching { BitmapFactory.decodeFile(file.absolutePath) }.getOrNull() }
        }
        if (bitmap != null) {
            Image(
                bitmap = bitmap.asImageBitmap(),
                contentDescription = "شاهد تصویری ثبت‌شده",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxWidth().height(180.dp).padding(top = 4.dp),
            )
            Text(saved!!.name, color = PhotoMuted, style = MaterialTheme.typography.bodySmall)
        }
    }
}