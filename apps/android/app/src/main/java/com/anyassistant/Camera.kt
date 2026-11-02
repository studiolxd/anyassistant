// The front camera (CameraX), for «¿qué ves?» and «lee esto» (the plugin «eyes» on the Mac):
// while it's awake, a frame about once a second goes to the Mac; asleep, the camera is off. When
// the Mac asks for a photo, it takes one at full resolution; «muestra la cámara», live on the face.

package com.anyassistant

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

class Camera(private val context: Context) {
    private val work = Executors.newSingleThreadExecutor()
    private val preview = Preview.Builder().build()
    private val analysis = ImageAnalysis.Builder()
        .setResolutionSelector(ResolutionSelector.Builder().setResolutionStrategy(
            ResolutionStrategy(Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)).build())
        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
        .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
        .build()
    private val capture = ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build()
    private var owner: LifecycleOwner? = null
    private var showing: PreviewView? = null
    private var lastFrame = 0L
    @Volatile private var latest: ByteArray? = null  // the last frame, for a photo that fails
    @Volatile var running = false
        private set

    /** A frame, as JPEG (about once a second while on). */
    var onFrame: ((ByteArray) -> Unit)? = null

    init {
        analysis.setAnalyzer(work) { image ->
            val now = System.currentTimeMillis()
            if (now - lastFrame >= 1000 && onFrame != null) {
                lastFrame = now
                jpeg(upright(image), 960, 70)?.let { latest = it; onFrame?.invoke(it) }
            }
            image.close()
        }
    }

    /** The activity it works with (the camera only works while it's in front). */
    fun attach(owner: LifecycleOwner) {
        this.owner = owner
        bind()
    }

    fun start() { if (!running) { running = true; bind() } }

    fun stop() { if (running) { running = false; bind() } }

    /** «Muestra la cámara»: live in this view (null: not any more). */
    fun preview(view: PreviewView?) {
        showing = view
        preview.surfaceProvider = view?.surfaceProvider
        bind()
    }

    private fun bind() {
        val owner = owner ?: return
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = runCatching { future.get() }.getOrNull() ?: return@addListener
            provider.unbindAll()
            if (!running && showing == null) return@addListener
            val selector = if (provider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)) CameraSelector.DEFAULT_FRONT_CAMERA
                else CameraSelector.DEFAULT_BACK_CAMERA
            runCatching { provider.bindToLifecycle(owner, selector, preview, analysis, capture) }
        }, ContextCompat.getMainExecutor(context))
    }

    /** A photo at full resolution; failed, the last frame (null: no camera). */
    fun photo(done: (ByteArray?) -> Unit) {
        val wasRunning = running
        if (!wasRunning) start()
        capture.takePicture(work, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val bytes = jpeg(upright(image), 4096, 90)
                image.close()
                if (!wasRunning) ContextCompat.getMainExecutor(context).execute { stop() }
                done(bytes ?: latest)
            }

            override fun onError(exception: ImageCaptureException) {
                if (!wasRunning) ContextCompat.getMainExecutor(context).execute { stop() }
                done(latest)
            }
        })
    }

    private fun upright(image: ImageProxy): Bitmap {
        val bitmap = image.toBitmap()
        val degrees = image.imageInfo.rotationDegrees
        if (degrees == 0) return bitmap
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, Matrix().apply { postRotate(degrees.toFloat()) }, true)
    }

    private fun jpeg(bitmap: Bitmap, side: Int, quality: Int): ByteArray? = runCatching {
        val longest = maxOf(bitmap.width, bitmap.height)
        val sized = if (longest > side) Bitmap.createScaledBitmap(bitmap, bitmap.width * side / longest, bitmap.height * side / longest, true) else bitmap
        ByteArrayOutputStream().use { out -> sized.compress(Bitmap.CompressFormat.JPEG, quality, out); out.toByteArray() }
    }.getOrNull()
}
