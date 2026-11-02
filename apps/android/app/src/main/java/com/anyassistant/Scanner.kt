// «Escanear código»: the QR that «Conectar otro dispositivo» shows on the server, read with the
// back camera (CameraX, which the app already has, and ZXing's core: plain Java, no Play Services,
// so it works on old and bare tablets too). It says where the server is and its code (Invitation).

package com.anyassistant

import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** The camera's picture; the first QR that is a server's invitation goes to `found` (once). */
@Composable
fun Scanner(owner: LifecycleOwner, found: (Invitation) -> Unit) {
    val context = LocalContext.current
    val work = remember { Executors.newSingleThreadExecutor() }
    val reader = remember { MultiFormatReader().apply { setHints(mapOf(DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE))) } }
    val done = remember { AtomicBoolean(false) }
    val preview = remember { Preview.Builder().build() }
    val analysis = remember { ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build() }
    AndroidView(factory = { context ->
        PreviewView(context).also { view ->
            preview.surfaceProvider = view.surfaceProvider
            analysis.setAnalyzer(work) { image ->
                if (!done.get()) {
                    val invitation = decode(image, reader)?.let(Invitation::parse)
                    if (invitation != null && done.compareAndSet(false, true)) view.post { found(invitation) }
                }
                image.close()
            }
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener({
                val provider = runCatching { future.get() }.getOrNull() ?: return@addListener
                runCatching { provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis) }
            }, ContextCompat.getMainExecutor(context))
        }
    }, modifier = Modifier.fillMaxWidth().aspectRatio(3f / 4f).clip(RoundedCornerShape(16.dp)))
    DisposableEffect(Unit) {
        onDispose {
            runCatching { ProcessCameraProvider.getInstance(context).get().unbind(preview, analysis) }  // ours only: the face's camera stays
            work.shutdown()
        }
    }
}

/** The QR's text in a frame (its Y plane is the grey picture ZXing reads), or null. */
private fun decode(image: ImageProxy, reader: MultiFormatReader): String? {
    val plane = image.planes[0]
    val buffer = plane.buffer
    val bytes = ByteArray(buffer.remaining()).also { buffer.get(it) }
    val source = PlanarYUVLuminanceSource(bytes, plane.rowStride, image.height, 0, 0, image.width, image.height, false)
    return try { reader.decodeWithState(BinaryBitmap(HybridBinarizer(source))).text }
    catch (e: NotFoundException) { null }
    catch (e: Exception) { null }
    finally { reader.reset() }
}
