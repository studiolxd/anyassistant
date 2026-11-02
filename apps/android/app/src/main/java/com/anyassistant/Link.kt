// The connection with the Mac (the plugin «stream-api»): a WebSocket with the microphone going up
// and its voice coming down, and the messages both ways, which change the face (FaceState). It
// reconnects by itself (the network drops, the Mac restarts). The same as iOS's Link.swift; it lives
// in the app (App.link), kept running by ListenService while the screen is off.
// Paused while another app has the microphone (a call, a meeting: Android silences this one,
// Audio.onSilenced): the server is told («paused», why; «listening» after), so its face explains
// it and nothing is transcribed; the recorder keeps running (silence) to know when it's given
// back, and then the audio is started again: a call leaves the mode and the route changed.

package com.anyassistant

import android.net.Uri
import android.content.Context
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject

class Link(private val context: Context) {
    enum class State { CONNECTING, CONNECTED, LOST, UNPAIRED }

    val mac = Mac(context)
    val audio = Audio(context)
    val camera = Camera(context)
    val face = FaceState()
    /** Every theme but Eyes: the server's page, fed from here (WebTheme.kt). */
    val web = WebFace(face, mac)
    var state by mutableStateOf(State.CONNECTING)
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    @Volatile private var socket: WebSocket? = null
    private var wanted = false
    private var dialing = false
    private var tapWhenConnected = false
    private var eyes = false  // the Mac has «eyes» on: the camera may be used
    var inFront = true  // the app is on screen (the camera only works then)
        private set
    private var lastLevel = 0L
    /** Why it is paused («microphone», «call») and by which app, if known; null while it listens. */
    var paused: Pair<String, String>? = null
        private set

    init {
        audio.onSpeech = { level -> scope.launch { face.speech = level } }
        audio.onSilenced = { silenced -> scope.launch { if (silenced) pause(if (audio.inCall) "call" else "microphone") else resume() } }
        camera.onFrame = { jpeg -> scope.launch { send(JSONObject().put("type", "frame").put("jpeg", Base64.encodeToString(jpeg, Base64.NO_WRAP))) } }
    }

    // --- Connecting ---

    fun start() {
        wanted = true
        connect()
    }

    fun stop() {
        wanted = false
        socket?.close(1001, null)
        socket = null
        audio.stop()
        camera.stop()
        set(State.LOST)
    }

    fun restart() {
        stop()
        start()
    }

    private fun connect() {
        if (!wanted || socket != null || dialing) return
        dialing = true
        if (state != State.LOST) set(State.CONNECTING)
        scope.launch {
            val base = mac.url()
            dialing = false
            if (!wanted || socket != null) return@launch
            if (base == null) return@launch lost()
            val url = base.replaceFirst("http", "ws") + "/stream?device=" + mac.device
            socket = mac.client.newWebSocket(mac.request(url).build(), Listener())
        }
    }

    private inner class Listener : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (webSocket !== socket) return
            audio.play(bytes.toByteArray())
            if (state != State.CONNECTED) scope.launch { if (webSocket === socket && state != State.CONNECTED) connected() }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            scope.launch {
                if (webSocket !== socket) return@launch
                if (state != State.CONNECTED) connected()
                handle(text)
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val code = response?.code
            scope.launch { if (webSocket === socket) dropped(code) }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            scope.launch { if (webSocket === socket) dropped(null) }
        }
    }

    private fun connected() {
        set(State.CONNECTED)
        startAudio()
        paused?.let { (why, app) -> send(JSONObject().put("type", "paused").put("why", why).put("app", app)) }  // the server is new to it
        scope.launch { configure() }
        if (tapWhenConnected) {
            tapWhenConnected = false
            send(JSONObject().put("type", "tap"))
        }
    }

    private fun startAudio() {
        val listening = audio.start { pcm, level ->
            socket?.send(pcm.toByteString())
            val now = System.currentTimeMillis()
            if (now - lastLevel > 33) { lastLevel = now; scope.launch { face.voice = level } }  // the face follows your voice
        }
        if (!listening) report("no microphone: the recorder didn't start")
    }

    // --- Paused: another app has the microphone ---

    /** Tells the server why («microphone»: another app records; «call»). Nothing if the server
     *  doesn't want it (settings «pause_when_microphone_busy»). */
    fun pause(why: String, app: String = "") {
        if (!face.shows("pause_when_microphone_busy")) return
        if (paused == why to app) return
        if (paused == null) report("paused: $why" + if (app.isEmpty()) "" else " ($app)")
        paused = why to app
        send(JSONObject().put("type", "paused").put("why", why).put("app", app))
    }

    /** The microphone is its again: the audio started afresh (the call changed the mode and the
     *  route), and the server told. */
    fun resume() {
        if (paused == null) return
        paused = null
        report("listening again")
        if (state == State.CONNECTED) { audio.stop(); startAudio() }
        send(JSONObject().put("type", "listening"))
    }

    private fun dropped(code: Int?) {
        socket = null
        camera.stop()
        if (code == 403) {  // unpaired on the Mac
            set(State.UNPAIRED)
            wanted = false
            audio.stop()
            mac.unpair()
            return
        }
        lost()
    }

    private fun lost() {
        socket = null
        set(State.LOST)
        if (!wanted) return
        scope.launch { delay(2000); connect() }
    }

    private fun set(new: State) {
        state = new
        when (new) {
            State.CONNECTED -> face.problem = null
            State.CONNECTING -> { face.problem = null; face.state = "connecting" }
            State.LOST -> face.problem = face.text("connection_lost").takeIf { it.isNotEmpty() && it != "connection_lost" }
                ?: context.getString(R.string.looking_for_mac)
            State.UNPAIRED -> face.problem = context.getString(R.string.pair_again_needed)
        }
    }

    /** The interface's language changed here (the app's screen made again in it), or from the server. */
    var interfaceLanguageShown: (() -> Unit)? = null

    /** The face's texts, theme and screen settings: the Mac's /config (as the page's), for this device's
     *  theme and its interface's language (the app's setting, kept on the server for this device too: a
     *  choice made here goes there; one made there, in the Mac's Devices, comes here). */
    suspend fun configure(again: Boolean = true) {
        val base = mac.url() ?: return
        if (Interface.unsaved(context)) saveInterfaceLanguage(base)
        val prefs = context.getSharedPreferences("anyassistant", Context.MODE_PRIVATE)
        val theme = prefs.getString("theme", null)
        val query = "?device=" + Uri.encode(mac.device) + "&ui=" + Interface.code(context) + (theme?.let { "&theme=" + Uri.encode(it) } ?: "")
        val config = withContext(Dispatchers.IO) {
            runCatching {
                mac.client.newCall(mac.request("$base/config$query").build()).execute()
                    .use { if (it.code == 200) JSONObject(it.body.string()) else null }
            }.getOrNull()
        } ?: return
        val theirs = config.optString("ui_language", "")
        if (again && theirs.isNotEmpty() && theirs != Interface.chosen(context) && !Interface.unsaved(context)) {
            Interface.choose(context, theirs, fromServer = true)  // changed in the Mac's Devices: this app too
            interfaceLanguageShown?.invoke()
            return configure(again = false)
        }
        web.configured(base, mac.cookie)
        face.configure(config)
        web.forward(JSONObject().put("type", "config").put("ui", face.lang))  // the page reads its texts and settings again
        send(JSONObject().put("type", "theme").put("name", face.theme))  // its theme's sounds are played from the Mac
        fetchAlarmSound(base, face.theme)
    }

    /** The interface's language chosen in the app's settings: saved on the server, the face's texts in it. */
    fun interfaceLanguageChanged() {
        scope.launch { configure(again = false) }
    }

    private suspend fun saveInterfaceLanguage(base: String) {
        val body = JSONObject().put("device", mac.device).put("ui_language", Interface.chosen(context)).toString()
        val status = withContext(Dispatchers.IO) {
            runCatching {
                mac.client.newCall(mac.request("$base/devices/ui_language")
                    .post(body.toRequestBody("application/json".toMediaType())).build()).execute().use { it.code }
            }.getOrNull()
        }
        if (status == 200 || status == 404) Interface.saved(context)  // 404: the plugin «devices» is off
    }

    /** The theme's alarm (the Mac's /alarm.wav, as it rings there), kept for the phone's own alarms. */
    private suspend fun fetchAlarmSound(base: String, theme: String) {
        val data = withContext(Dispatchers.IO) {
            runCatching {
                mac.client.newCall(mac.request("$base/alarm.wav?theme=$theme").build()).execute()
                    .use { if (it.code == 200) it.body.bytes() else null }
            }.getOrNull()
        } ?: return
        if (data.size > 44) withContext(Dispatchers.IO) { runCatching { Alarms.soundFile(context).writeBytes(data) } }
    }

    // --- Both ways ---

    fun send(message: JSONObject) {
        socket?.send(message.toString())
    }

    /** A tap on the face: it stops talking (quiet at once here), or wakes up. */
    fun tap() {
        audio.hush()
        send(JSONObject().put("type", "tap"))
    }

    /** «Hablar»: the shortcut, the quick settings tile, the assistant gesture: as a tap on its face. */
    fun talk() {
        if (state == State.CONNECTED) tap() else { tapWhenConnected = true; start() }
    }

    /** An alarm stopped on the phone: if the Mac is ringing, a tap stops it there too. */
    fun stopRinging() {
        if (face.state == "alarm") send(JSONObject().put("type", "tap"))
    }

    private fun handle(text: String) {
        val message = runCatching { JSONObject(text) }.getOrNull() ?: return
        when (val type = message.optString("type")) {
            "hush" -> audio.hush()
            "hello" -> eyes = message.optBoolean("eyes")
            "pong" -> {}
            "photo" -> takePhoto(message.optInt("id"))
            "look" -> if (web.shows(face.theme)) web.forward(message) else scope.launch { showPhoto() }  // the page shows it itself; Eyes, here
            "config" -> scope.launch { configure() }
            "theme" -> {
                val name = message.optString("name")
                val prefs = context.getSharedPreferences("anyassistant", Context.MODE_PRIVATE).edit()
                if (name.isEmpty() || name == "default") prefs.remove("theme") else prefs.putString("theme", name)
                prefs.apply()
                scope.launch { configure() }
            }
            else -> {
                face.receive(message)
                web.forward(message)
                Notices.handle(context, message, face.name)
                if (type == "state" || type == "camera") look()
            }
        }
    }

    /** A line in the Mac's log (stream-api), to see what happens inside the app. */
    fun report(text: String) = send(JSONObject().put("type", "log").put("text", text))

    // --- The camera ---

    /** Awake, it looks (a frame a second); asleep, the camera is off. Shown, it's on whatever the state. */
    private fun look() {
        val state = face.look
        if (inFront && (face.cameraShown || (eyes && state != "asleep" && state != "error"))) camera.start() else camera.stop()
    }

    fun cameraAllowed(front: Boolean) {
        inFront = front
        if (!front) face.cameraShown = false
        look()
    }

    private suspend fun showPhoto() {
        val base = mac.url() ?: return
        val bytes = withContext(Dispatchers.IO) {
            runCatching { mac.client.newCall(mac.request("$base/eyes.jpg").build()).execute().use { if (it.code == 200) it.body.bytes() else null } }.getOrNull()
        } ?: return
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.let { face.showPhoto(it) }
    }

    /** «Lee esto»: a full-resolution photo, to the Mac (POST /photo). */
    private fun takePhoto(id: Int) {
        if (!eyes || !inFront) return
        camera.photo { jpeg ->
            scope.launch {
                if (jpeg == null || jpeg.isEmpty()) return@launch report("photo: none (no camera, or it failed)")
                val base = mac.url() ?: return@launch
                withContext(Dispatchers.IO) {
                    runCatching {
                        mac.client.newCall(mac.request("$base/photo?id=$id&how=photo")
                            .post(jpeg.toRequestBody("image/jpeg".toMediaType())).build()).execute().close()
                    }
                }
            }
        }
    }
}
