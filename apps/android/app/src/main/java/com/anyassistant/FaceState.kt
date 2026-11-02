// What the face shows, as the page has it: the state, the texts in the Mac's language, the theme
// and its colours, the screen settings, what was said, the timers, the photo it looks at. The
// Mac's messages change it (receive), and its /config (configure). The same as iOS's FaceModel.

package com.anyassistant

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class FaceState {
    data class Caption(val id: String, val text: String, val assistant: Boolean)
    data class Item(val kind: String, val at: Double, val label: String)

    var state by mutableStateOf("connecting")
    var problem by mutableStateOf<String?>(null)  // not connected: what to say instead of the state
    var name by mutableStateOf("AnyAssistant")
    var lang by mutableStateOf(Locale.getDefault().language)
    var wake by mutableStateOf("")
    var texts by mutableStateOf<Map<String, String>>(emptyMap())
    var theme by mutableStateOf("eyes")
    var options by mutableStateOf<Map<String, String>>(emptyMap())
    var screen by mutableStateOf<Map<String, Any>>(emptyMap())
    val captions = mutableStateListOf<Caption>()
    var heard by mutableStateOf("")
    var answer by mutableStateOf("")
    var items by mutableStateOf<List<Item>>(emptyList())
    var alarmLabel by mutableStateOf("")
    var photo by mutableStateOf<Bitmap?>(null)
    var scanning by mutableStateOf(false)
    var photoFading by mutableStateOf(false)
    var cameraShown by mutableStateOf(false)
    var voice by mutableFloatStateOf(0f)  // your voice, 0…1
    var speech by mutableFloatStateOf(0f)  // its own

    private val main = Handler(Looper.getMainLooper())

    companion object {
        private val looksLike = mapOf("connected" to "awake", "listening" to "awake", "recording" to "hearing",
            "repeating" to "speaking", "transcribing" to "thinking", "connecting" to "awake")
    }

    /** The state as the themes draw it (several states look the same). */
    val look: String get() = if (problem != null) "error" else looksLike[state] ?: state

    fun text(key: String, values: Map<String, String> = emptyMap()): String {
        var found = texts[key] ?: if (texts.isEmpty()) return "" else key  // nothing until the Mac's texts arrive
        for ((k, v) in values) found = found.replace("{$k}", v)
        return found
    }

    fun shows(key: String, otherwise: Boolean = true): Boolean = screen[key] as? Boolean ?: otherwise

    val history: Int get() = (screen["history"] as? Number)?.toInt() ?: 2

    /** The status line, as the page writes it. */
    val status: String get() {
        problem?.let { return it }
        return when (state) {
            "alarm" -> text("alarm", mapOf("label" to alarmLabel))
            "asleep" -> if (shows("show_hint")) text("asleep", mapOf("wake" to wake.ifEmpty { name })) else ""
            else -> if (shows("show_status") || state == "error") text(state) else ""
        }
    }

    fun color(key: String, otherwise: Color): Color = options[key]?.let { hex(it) } ?: otherwise

    val background: Color get() = color("background", Color.Black)

    fun configure(config: JSONObject) {
        lang = config.optString("lang", lang)
        name = config.optString("name", name)
        wake = config.optString("wake_phrase", wake)
        screen = config.optJSONObject("screen")?.let { o -> o.keys().asSequence().associateWith { o.get(it) } } ?: emptyMap()
        val found = mutableMapOf<String, String>()
        config.optJSONObject("ui")?.let { o -> o.keys().forEach { found[it] = o.optString(it) } }
        val themeInfo = config.optJSONObject("theme") ?: JSONObject()
        themeInfo.optJSONObject("ui")?.let { o -> o.keys().forEach { found[it] = o.optString(it) } }  // the theme's own words
        texts = found
        theme = themeInfo.optString("name", "eyes")
        options = themeInfo.optJSONObject("options")?.let { o -> o.keys().asSequence().associateWith { o.optString(it) } } ?: emptyMap()
    }

    // --- The Mac's messages ---

    fun receive(message: JSONObject) {
        when (message.optString("type")) {
            "state" -> {
                state = message.optString("state", state)
                message.optString("wake_phrase").takeIf { it.isNotEmpty() }?.let { wake = it }
                if (look != "looking" && look != "thinking") photoDone()
                if (look == "asleep") cameraShown = false
            }
            "text" -> caption(message)
            "timers" -> {
                val list = message.optJSONArray("items")
                items = (0 until (list?.length() ?: 0)).mapNotNull { i ->
                    val item = list!!.optJSONObject(i) ?: return@mapNotNull null
                    Item(item.optString("kind", "timer"), item.optDouble("at"), item.optString("label"))
                }
            }
            "alarm" -> alarmLabel = message.optString("label")
            "camera" -> cameraShown = message.optBoolean("on")
        }
    }

    /** What you said and its answer (in pieces with the same id: the same line, updated). */
    private fun caption(message: JSONObject) {
        val text = message.optString("text")
        val assistant = message.optString("author") == "assistant"
        if (!shows(if (assistant) "show_answer" else "show_heard")) return
        if (assistant) answer = text else heard = text
        val id = if (message.has("id")) "a-" + message.get("id") else null
        val index = if (id != null) captions.indexOfFirst { it.id == id } else -1
        if (index >= 0) {
            captions[index] = captions[index].copy(text = text)
            return
        }
        captions.add(Caption(id ?: UUID.randomUUID().toString(), text, assistant))
        while (captions.size > history + 1) captions.removeAt(0)
    }

    /** «¿Qué ves?»: the photo it looks at, with a scanning sweep until it answers. */
    fun showPhoto(image: Bitmap) {
        photo = image
        photoFading = false
        scanning = true
    }

    private fun photoDone() {
        if (photo == null || photoFading) return
        scanning = false
        photoFading = true
        main.postDelayed({ if (photoFading) { photo = null; photoFading = false } }, 1500)
    }

    // --- The clock and the timers, in the Mac's language ---

    private val locale get() = Locale.forLanguageTag(lang)

    fun time(date: Date): String {
        val clock = screen["clock"] as? String ?: "auto"
        val template = when (clock) { "12" -> "hmm"; "24" -> "Hmm"; else -> "jmm" }  // as iOS's and the page's
        return SimpleDateFormat(android.text.format.DateFormat.getBestDateTimePattern(locale, template), locale).format(date)
    }

    fun day(date: Date): String =
        SimpleDateFormat(android.text.format.DateFormat.getBestDateTimePattern(locale, "EEEEdMMMM"), locale).format(date)

    /** «4:59 · pasta», «7:30 · gym»: a countdown for timers, the time for the rest. */
    fun line(item: Item, now: Long): String {
        val whenText = if (item.kind == "timer") {
            val left = maxOf(0, Math.round(item.at - now / 1000.0).toInt())
            val (h, m, s) = Triple(left / 3600, left / 60 % 60, left % 60)
            if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
        } else time(Date((item.at * 1000).toLong()))
        return whenText + if (item.label.isEmpty()) "" else " · " + item.label
    }
}

/** «#34aff7», «#000». */
fun hex(text: String): Color? {
    var digits = text.trim()
    if (!digits.startsWith("#")) return null
    digits = digits.substring(1)
    if (digits.length == 3) digits = digits.map { "$it$it" }.joinToString("")
    if (digits.length != 6) return null
    val value = digits.toLongOrNull(16) ?: return null
    return Color(0xff000000 or value)
}
