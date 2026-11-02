// Every theme but Eyes: the server's page for the apps (/?app&theme=<name>: plugins/page/web, the
// same page a browser shows, so a theme from the community looks the same here) in a WebView, fed
// by the app. The app keeps the microphone, the audio, the camera, the notifications and the
// connection (Link): the page opens none of them. It gets what the server says (forward), the
// voices' levels and the app's own problems, and gives back its taps, holding the face (the
// settings), and where its camera's window is (the app's own camera goes there). The pairing's
// cookie goes with it; over HTTPS only the server's own authority is trusted (Mac.trusts). While
// the page can't be had, ThemeView draws Eyes. The same as iOS's WebTheme.swift.

package com.anyassistant

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color as AndroidColor
import android.net.http.SslError
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONArray
import org.json.JSONObject

class WebFace(private val face: FaceState, private val mac: Mac) {
    /** Where the page has the camera's window (CSS pixels: dp), while it shows it. */
    data class Window(val x: Float, val y: Float, val width: Float, val height: Float)

    /** The server, as the app reaches it, and its pairing's cookie (Link, with each /config). */
    var base by mutableStateOf<String?>(null)
        private set
    private var cookie: String? = null
    /** The page didn't load, or never said it was ready: Eyes, until the next /config. */
    var failed by mutableStateOf(false)
        private set
    var cameraWindow by mutableStateOf<Window?>(null)
        private set
    internal var tap: () -> Unit = {}
    internal var settings: () -> Unit = {}

    private var view: WebView? = null
    private var ready = false
    private val main = Handler(Looper.getMainLooper())
    private var sentVoice = -1f
    private var sentSpeech = -1f
    private var sentProblem: String? = null
    private var problemSent = false

    /** Whether a theme is drawn here (not Eyes, and the page can be had). */
    fun shows(theme: String) = theme != "eyes" && base != null && !failed

    /** The server's address and cookie, with each /config: the page is tried again. */
    fun configured(base: String, cookie: String?) {
        this.base = base
        this.cookie = cookie
        if (failed) failed = false
    }

    // --- The view ---

    @SuppressLint("SetJavaScriptEnabled")
    internal fun makeView(context: Context, theme: String): WebView {
        val view = WebView(context)
        view.settings.javaScriptEnabled = true
        view.settings.domStorageEnabled = true
        view.settings.mediaPlaybackRequiresUserGesture = false
        view.setBackgroundColor(AndroidColor.TRANSPARENT)  // the theme's background, not a white flash
        view.overScrollMode = View.OVER_SCROLL_NEVER
        view.isVerticalScrollBarEnabled = false
        view.isHorizontalScrollBarEnabled = false
        view.isHapticFeedbackEnabled = false
        view.setOnLongClickListener { true }  // holding is the page's (the settings), not selecting
        view.addJavascriptInterface(Bridge(view), "AnyAssistantApp")
        view.webViewClient = Client()
        this.view = view
        ready = false
        cameraWindow = null
        val base = base ?: return view
        val url = base + "/?app&theme=" + android.net.Uri.encode(theme)
        val cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(true)
        val load = { view.loadUrl(url) }
        cookie?.let { cookies.setCookie(base, "$it; path=/") { load() } } ?: load()
        main.postDelayed({ if (this.view === view && !ready) failed = true }, 15000)  // loaded, but never ready
        return view
    }

    internal fun release(view: WebView) {
        if (this.view === view) {
            this.view = null
            ready = false
            cameraWindow = null
        }
        view.destroy()
    }

    // --- To the page ---

    /** A message from the server, as it came (the page draws it as a browser would). */
    fun forward(message: JSONObject) = send(message)

    private fun send(message: JSONObject) {
        if (!ready) return
        view?.evaluateJavascript("AnyAssistant.receive($message)", null)
    }

    /** The page is ready: what is on the face already, then the levels and the problems as they change. */
    private fun began() {
        ready = true
        for (caption in face.captions) {
            val message = JSONObject().put("type", "text").put("text", caption.text)
                .put("author", if (caption.assistant) "assistant" else "user")
            caption.answer?.let { message.put("id", it) }
            send(message)
        }
        face.said?.let { said ->
            val message = JSONObject().put("type", "speaking").put("id", said.id).put("start", said.start)
            said.end?.let { message.put("end", it) }
            send(message)
        }
        val items = JSONArray()
        for (item in face.items) items.put(JSONObject().put("kind", item.kind).put("at", item.at).put("label", item.label))
        send(JSONObject().put("type", "timers").put("items", items))
        send(JSONObject().put("type", "alarm").put("label", face.alarmLabel))
        sendState()
        if (face.cameraShown) send(JSONObject().put("type", "camera").put("on", true))
        problemSent = false
        sentVoice = -1f
        sentSpeech = -1f
        main.removeCallbacks(ticker)
        ticker.run()
    }

    private fun sendState() {
        val message = JSONObject().put("type", "state").put("state", face.state)
        if (face.wake.isNotEmpty()) message.put("wake_phrase", face.wake)
        if (face.pausedWhy.isNotEmpty()) message.put("why", face.pausedWhy)
        if (face.pausedApp.isNotEmpty()) message.put("app", face.pausedApp)
        send(message)
    }

    /** The voices' levels (your voice, its own), and the app's problem when it changes (with the
     *  state: «connecting» is the app's own too); 30 times a second while the page is there. */
    private val ticker = object : Runnable {
        override fun run() {
            if (!ready || view == null) return
            val voice = face.voice
            val speech = face.speech
            if (kotlin.math.abs(voice - sentVoice) > 0.01f || kotlin.math.abs(speech - sentSpeech) > 0.01f) {
                sentVoice = voice
                sentSpeech = speech
                send(JSONObject().put("type", "levels").put("voice", voice.toDouble()).put("speech", speech.toDouble()))
            }
            if (!problemSent || sentProblem != face.problem) {
                problemSent = true
                sentProblem = face.problem
                sendState()
                send(JSONObject().put("type", "problem").put("text", face.problem ?: JSONObject.NULL))
            }
            main.postDelayed(this, 33)
        }
    }

    // --- From the page ---

    private fun received(message: JSONObject) {
        when (message.optString("type")) {
            "ready" -> began()
            "tap" -> tap()
            "settings" -> settings()
            "camera" -> {
                val width = message.optDouble("width", 0.0).toFloat()
                val height = message.optDouble("height", 0.0).toFloat()
                cameraWindow = if (message.optBoolean("on") && width > 0 && height > 0)
                    Window(message.optDouble("x", 0.0).toFloat(), message.optDouble("y", 0.0).toFloat(), width, height) else null
            }
        }
    }

    /** window.AnyAssistantApp.post(json): the page's messages (on another thread: to the main one). */
    private inner class Bridge(private val owner: WebView) {
        @JavascriptInterface
        fun post(json: String) {
            val message = runCatching { JSONObject(json) }.getOrNull() ?: return
            main.post { if (view === owner) received(message) }
        }
    }

    private inner class Client : WebViewClient() {
        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame && view === this@WebFace.view) failed = true
        }

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
            if (request.isForMainFrame && view === this@WebFace.view) failed = true
        }

        /** Over HTTPS, only the server's own authority (learnt when pairing), as the app's connection. */
        @SuppressLint("WebViewClientOnReceivedSslError")
        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            if (mac.trusts(error.certificate)) handler.proceed() else handler.cancel()
        }

        /** The system ended the page (memory): Eyes, and the page again with the next /config. */
        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            if (view === this@WebFace.view) {
                ready = false
                failed = true
            }
            return true
        }
    }
}

/** The theme's page, and the app's camera where the page has its window («muestra la cámara»). */
@Composable
fun WebTheme(web: WebFace, camera: Camera, theme: String, tap: () -> Unit, settings: () -> Unit) {
    SideEffect {
        web.tap = tap
        web.settings = settings
    }
    Box(Modifier.fillMaxSize().safeDrawingPadding()) {
        AndroidView(factory = { context -> web.makeView(context, theme) }, modifier = Modifier.fillMaxSize(),
            onRelease = { web.release(it) })
        web.cameraWindow?.let { window ->
            // Inside the window's frame (the theme's border stays).
            AndroidView(factory = { context -> PreviewView(context).also { camera.preview(it) } },
                modifier = Modifier.offset((window.x + 2).dp, (window.y + 2).dp)
                    .size(maxOf(window.width - 4, 1f).dp, maxOf(window.height - 4, 1f).dp).clip(RoundedCornerShape(8.dp)),
                onRelease = { camera.preview(null) })
        }
    }
}
