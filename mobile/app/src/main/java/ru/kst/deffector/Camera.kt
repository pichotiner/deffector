package ru.kst.deffector

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.*
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@Composable
fun CameraFeed(modifier: Modifier, onFrame: suspend (Bitmap) -> Unit, onError: (String) -> Unit) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    val currentFrame by rememberUpdatedState(onFrame)
    val currentError by rememberUpdatedState(onError)
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }
    if (!granted) {
        Surface(modifier) {
            Column(Modifier.fillMaxSize().padding(androidx.compose.ui.unit.Dp(16f)), verticalArrangement = Arrangement.Center) {
                Text("Разрешите доступ к камере для распознавания и AR-осмотра")
                Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text("Разрешить камеру") }
                Text("Если доступ заблокирован, включите его в настройках Android. Ручной выбор доступен на стартовом экране.")
            }
        }
        return
    }
    val previewView = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER; implementationMode = PreviewView.ImplementationMode.COMPATIBLE } }
    AndroidView(factory = { previewView }, modifier = modifier)
    DisposableEffect(owner, previewView) {
        val executor = Executors.newSingleThreadExecutor()
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        val running = AtomicBoolean(false)
        var lastFrameAt = 0L
        var disposed = false
        var provider: ProcessCameraProvider? = null
        var boundPreview: Preview? = null
        var boundAnalysis: ImageAnalysis? = null
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (!disposed) {
                try {
                    provider = future.get()
                    val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
                    val analysis = ImageAnalysis.Builder()
                        .setResolutionSelector(androidx.camera.core.resolutionselector.ResolutionSelector.Builder()
                            .setResolutionStrategy(androidx.camera.core.resolutionselector.ResolutionStrategy(android.util.Size(1280, 960),
                                androidx.camera.core.resolutionselector.ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)).build())
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                    boundPreview = preview; boundAnalysis = analysis
                    analysis.setAnalyzer(executor) { proxy ->
                        val now = android.os.SystemClock.elapsedRealtime()
                        // Не создаём полноразмерные Bitmap для каждого кадра живого превью.
                        if (now - lastFrameAt < 150 || !running.compareAndSet(false, true)) { proxy.close() }
                        else {
                            lastFrameAt = now
                            try {
                                val raw = proxy.toBitmap()
                                val rect = proxy.cropRect
                                val matrix = Matrix().apply { postRotate(proxy.imageInfo.rotationDegrees.toFloat()) }
                                val oriented = Bitmap.createBitmap(raw, rect.left, rect.top, rect.width(), rect.height(), matrix, true)
                                proxy.close()
                                scope.launch {
                                    try { currentFrame(oriented) }
                                    catch (e: CancellationException) { throw e }
                                    catch (e: Exception) { currentError(e.message ?: "Не удалось обработать кадр") }
                                    finally { running.set(false) }
                                }
                            } catch (e: Exception) {
                                proxy.close(); running.set(false)
                                scope.launch { currentError(e.message ?: "Не удалось получить кадр") }
                            }
                        }
                    }
                    previewView.post {
                        if (!disposed) try {
                            val group = UseCaseGroup.Builder().addUseCase(preview).addUseCase(analysis)
                            previewView.viewPort?.let { group.setViewPort(it) }
                            provider?.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, group.build())
                        } catch (e: Exception) { currentError("Камера недоступна: ${e.message}") }
                    }
                } catch (e: Exception) { currentError("Камера недоступна: ${e.message}") }
            }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            disposed = true
            boundAnalysis?.clearAnalyzer()
            boundPreview?.let { preview -> boundAnalysis?.let { analysis -> provider?.unbind(preview, analysis) } }
            scope.cancel(); executor.shutdown()
        }
    }
}
