// The face: the theme Eyes, drawn natively (plugins/page/themes/eyes: the same look; sizes in «v» =
// 1% of the screen's shorter side, as the CSS's vmin); every other theme, the server's page in a
// web view (WebTheme.kt), fed by the app. Eyes too while the server's page can't be had. The same
// as iOS's Themes.swift.

package com.anyassistant

import androidx.camera.view.PreviewView
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.runtime.key
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.layout.onPlaced
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInParent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Alarm
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.delay
import java.util.Date
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

val grey = Color(0xff888888)

/** The face. A tap: it stops talking or wakes up; held: the settings (whatever the theme). */
@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
fun ThemeView(face: FaceState, camera: Camera, web: WebFace, tap: () -> Unit, settings: () -> Unit) {
    // The background to the screen's edges; the face, its words, the clock and the camera inside
    // the safe area (not under the camera's cutout, nor the system bars when they show).
    Box(Modifier.fillMaxSize().background(face.background)) {
        if (web.shows(face.theme)) {
            key(face.theme) { WebTheme(web, camera, face.theme, tap, settings) }  // another theme: another page
        } else {
            Box(Modifier.fillMaxSize().combinedClickable(remember { MutableInteractionSource() }, null,
                onLongClick = settings, onClick = tap)) { ThemeContent(face, camera) }
        }
    }
}

@Composable
private fun ThemeContent(face: FaceState, camera: Camera) {
    BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding()) {
        val v = min(maxWidth.value, maxHeight.value) / 100
        val scope = Sizes(v, maxWidth, maxHeight, maxWidth > maxHeight)
        val end = remember { mutableStateOf(0f) }  // where the theme's face and words end (px, FaceEnd)
        var origin by remember { mutableStateOf(0f) }
        Box(Modifier.fillMaxSize().onGloballyPositioned { origin = it.positionInRoot().y }) {
            CompositionLocalProvider(LocalFaceEnd provides { y -> end.value = y - origin }) {
                EyesTheme(face, scope)
            }
        }
        // «Muestra la cámara»: centred below what the face says, in the space left; the face doesn't move.
        if (face.cameraShown) {
            val density = LocalDensity.current
            val faceEnd = with(density) { end.value.toDp() }
            val top = (if (faceEnd > 0.dp) faceEnd else maxHeight * 0.6f) + scope.dp(2f)
            val area = maxOf(maxHeight - top - scope.dp(3f), maxHeight * 0.2f)
            CameraBox(camera, maxWidth, area, Modifier.offset(y = minOf(top, maxHeight * 0.8f - scope.dp(3f))))
        }
        Windows(face, scope)
    }
}

/** Where the face and its words end: Eyes puts FaceEndMark() last in its column. */
val LocalFaceEnd = staticCompositionLocalOf<(Float) -> Unit> { {} }

@Composable
fun FaceEndMark() {
    val report = LocalFaceEnd.current
    Box(Modifier.size(1.dp).onGloballyPositioned { report(it.positionInRoot().y) })
}

/** The camera live («muestra la cámara»), centred in the space below the face. */
@Composable
fun CameraBox(camera: Camera, areaWidth: Dp, areaHeight: Dp, modifier: Modifier) {
    val height = min(areaHeight.value * 0.88f, areaWidth.value * 0.9f * 3 / 4).dp
    Box(modifier.width(areaWidth).height(areaHeight), contentAlignment = Alignment.Center) {
        AndroidView(
            factory = { context -> PreviewView(context).also { camera.preview(it) } },
            modifier = Modifier.size(height * 4 / 3, height).clip(RoundedCornerShape(10.dp))
                .border(2.dp, hex("#5bc6e8")!!, RoundedCornerShape(10.dp)),
            onRelease = { camera.preview(null) })
    }
}

/** The screen's sizes: v (1% of the shorter side, in dp), and both sides. */
class Sizes(val v: Float, val width: Dp, val height: Dp, val landscape: Boolean) {
    fun dp(n: Float): Dp = (n * v).dp
}

@Composable
fun Sizes.sp(n: Float): TextUnit = with(LocalDensity.current) { dp(n).toSp() }

// --- Motion ---

/** Seconds, a new value each frame (for the themes' continuous motion). */
@Composable
fun clock(): Double {
    val time by produceState(0.0) {
        val start = System.nanoTime()
        while (true) withFrameNanos { value = (it - start) / 1e9 }
    }
    return time
}

private fun ease(f: Double) = if (f < 0.5) 2 * f * f else 1 - (-2 * f + 2).pow(2) / 2

/** A looping track of keyframes (fraction 0…1, x, y): held where two keys are equal, eased between. */
fun track(t: Double, period: Double, keys: List<Triple<Double, Float, Float>>): Offset {
    val p = (t % period) / period
    for (i in 0 until keys.size - 1) {
        val (a, x0, y0) = keys[i]
        val (b, x1, y1) = keys[i + 1]
        if (p in a..b) {
            val e = ease(if (b > a) (p - a) / (b - a) else 0.0).toFloat()
            return Offset(x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)
        }
    }
    return Offset(keys.last().second, keys.last().third)
}

/** 0 → 1 → 0, eased, over a period (CSS «alternate»). */
fun swing(t: Double, period: Double): Float {
    val p = (t % (2 * period)) / period
    return ease(if (p <= 1) p else 2 - p).toFloat()
}

/** 0 → 1 → 0 smoothly, once a period. */
fun beat(t: Double, period: Double, delay: Double = 0.0): Float = (0.5 - 0.5 * cos(2 * PI * (t - delay) / period)).toFloat()

// --- Shared pieces ---

@Composable
fun StatusLine(face: FaceState, size: TextUnit, modifier: Modifier = Modifier) {
    Text(face.status, modifier, color = grey, fontSize = size, textAlign = TextAlign.Center)
}

@Composable
fun TimerLines(face: FaceState, size: TextUnit, modifier: Modifier = Modifier) {
    if (!face.shows("show_timers")) return
    val now by produceState(System.currentTimeMillis()) { while (true) { value = System.currentTimeMillis(); delay(1000) } }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        for (item in face.items.filter { it.at > now / 1000.0 - 1 }) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                val icon = when (item.kind) { "alarm" -> Icons.Outlined.Alarm; "reminder" -> Icons.Outlined.Notifications; else -> Icons.Outlined.Timer }
                Icon(icon, null, tint = Color.White, modifier = Modifier.size(with(LocalDensity.current) { size.toDp() }))
                Spacer(Modifier.width(with(LocalDensity.current) { (size * 0.35f).toDp() }))
                Text(face.line(item, now), color = Color.White, fontSize = size)
            }
        }
    }
}

@Composable
fun CaptionLines(face: FaceState, accent: Color, modifier: Modifier = Modifier) {
    val lastOne = face.captions.lastOrNull()
    WordsArea(lastOne?.let { face.aim(it.id, it.answer, it.text) } ?: Aim("", 0f), lastOne?.id ?: "", modifier,
        Alignment.CenterHorizontally, Arrangement.spacedBy(5.dp)) {
        for (caption in face.captions) {
            val last = caption.id == lastOne?.id
            Text(caption.text, Modifier.word(caption.id).alpha(if (last) 1f else 0.6f),
                color = if (caption.assistant) accent else Color.White,
                fontSize = with(LocalDensity.current) { (if (last) 24f else 17.6f).dp.toSp() }, textAlign = TextAlign.Center)
        }
    }
}

/** Where a WordsArea scrolls to: the word with that key, at that fraction of it (0 its top, 1 its end). */
data class Aim(val key: String, val y: Float)

/** Inside a WordsArea: Modifier.word(key) marks what an Aim can point at. */
class WordsScope(column: ColumnScope, private val places: MutableMap<String, Pair<Float, Float>>) : ColumnScope by column {
    fun Modifier.word(key: String): Modifier = onPlaced { places[key] = it.positionInParent().y to it.size.height.toFloat() }
}

/** The words (the captions, what you said, the answer) in their own area, as the page's: it scrolls
 *  without a bar (a finger) and follows `aim` (FaceState.aim: the end of what you said, the sentence
 *  the voice is saying); dragged by hand, it stops following until back at the end or new words
 *  arrive (`fresh` changes). A fade at the edge where there is more. Its height is the modifier's
 *  (a fixed one, or weight(1f, fill = false): as tall as the words, down to the bottom). */
@Composable
fun WordsArea(aim: Aim, fresh: Any, modifier: Modifier = Modifier, alignment: Alignment.Horizontal = Alignment.Start,
              arrangement: Arrangement.Vertical = Arrangement.Top, content: @Composable WordsScope.() -> Unit) {
    val state = rememberScrollState()
    val places = remember { mutableStateMapOf<String, Pair<Float, Float>>() }
    var following by remember { mutableStateOf(true) }
    var view by remember { mutableStateOf(0f) }
    LaunchedEffect(state) {  // a finger: it stops following
        state.interactionSource.interactions.collect { if (it is DragInteraction.Start) following = false }
    }
    LaunchedEffect(state) {  // back at the end (and still): following again
        snapshotFlow { Triple(state.value, state.maxValue, state.isScrollInProgress) }.collect { (at, end, moving) ->
            if (!following && !moving && at >= end - 2) following = true
        }
    }
    LaunchedEffect(fresh) { following = true }
    val place = places[aim.key]
    LaunchedEffect(aim, following, place, view, state.maxValue) {
        if (!following || place == null) return@LaunchedEffect
        val (top, height) = place
        val target = (top + aim.y * height - aim.y * view).toInt().coerceIn(0, state.maxValue)
        if (target != state.value) state.animateScrollTo(target, tween(450))
    }
    Column(modifier
        .onSizeChanged { view = it.height.toFloat() }
        .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
        .drawWithContent {
            drawContent()
            val edge = 28.dp.toPx()
            if (state.value > 1) drawRect(Brush.verticalGradient(0f to Color.Transparent, 1f to Color.Black, startY = 0f, endY = edge),
                size = Size(size.width, edge), blendMode = BlendMode.DstIn)
            if (state.value < state.maxValue - 1) drawRect(Brush.verticalGradient(0f to Color.Black, 1f to Color.Transparent,
                startY = size.height - edge, endY = size.height), Offset(0f, size.height - edge), Size(size.width, edge), blendMode = BlendMode.DstIn)
        }
        .verticalScroll(state), horizontalAlignment = alignment, verticalArrangement = arrangement) {
        WordsScope(this, places).content()
    }
}

/** The time and the date (the theme lays them out). */
@Composable
fun Clock(face: FaceState, content: @Composable (time: String?, day: String?) -> Unit) {
    val now by produceState(Date()) { while (true) { value = Date(); delay(5000) } }
    content(if (face.shows("show_time")) face.time(now) else null, if (face.shows("show_date")) face.day(now) else null)
}

/** The photo it looks at (with a scanning sweep), over the face: a moment, and what it is looking at. */
@Composable
fun Windows(face: FaceState, s: Sizes) {
    val height = min(s.dp(60f).value, s.height.value * 0.45f).dp
    val width = height * 4 / 3
    Box(Modifier.fillMaxSize().padding(top = s.height * 0.08f), contentAlignment = Alignment.TopCenter) {
        face.photo?.let { photo ->
            val green = hex("#3fe0a8")!!
            val alpha by animateFloatAsState(if (face.photoFading) 0f else 1f, tween(1200), label = "photo")
            Box(Modifier.size(width, height).alpha(alpha).shadow(s.dp(4f), RoundedCornerShape(10.dp), ambientColor = green, spotColor = green)
                .clip(RoundedCornerShape(10.dp)).border(2.dp, green, RoundedCornerShape(10.dp)).background(Color.Black)) {
                Image(photo.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop,
                    colorFilter = ColorFilter.colorMatrix(ColorMatrix().apply {
                        setToSaturation(0.6f)
                        values[4] = -25.5f; values[9] = -25.5f; values[14] = -25.5f  // and a little darker (-0.1)
                    }))
                if (face.scanning) {
                    val t = clock()
                    Canvas(Modifier.fillMaxSize()) {
                        val y = (swing(t, 1.4) - 0.5f) * size.height
                        translate(top = y) {
                            drawRect(Brush.verticalGradient(0f to green.copy(alpha = 0f), 0.44f to green.copy(alpha = 0.08f),
                                0.495f to Color(0xffa0ffdc).copy(alpha = 0.75f), 0.5f to Color.White.copy(alpha = 0.95f),
                                0.506f to green.copy(alpha = 0f), 1f to green.copy(alpha = 0f)))
                        }
                    }
                }
            }
        }
    }
}

// --- Eyes ---

/** Two blue eyes that change shape to say how it feels: ovals, happy arcs (^ ^), closed (‿ ‿),
 *  or cut by a lid (sad); floating, looking around, scanning, thinking. */
@Composable
fun EyesTheme(face: FaceState, s: Sizes) {
    val look = face.look
    val accent = face.color("accent", hex("#34aff7")!!)
    var blink by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) { delay((2500 + Random.nextDouble() * 4500).toLong()); blink = true; delay(140); blink = false }
    }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(top = s.height * (if (s.landscape) 0.10f else 0.28f)),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.graphicsLayer { scaleX = if (s.landscape) 0.85f else 1f; scaleY = scaleX }) { EyesFace(face, s, look, accent, blink) }
            StatusLine(face, 22.sp, modifier = Modifier.padding(top = 27.dp))
            TimerLines(face, s.sp(if (s.landscape) 4.5f else 5f), modifier = Modifier.padding(top = s.dp(if (s.landscape) 1.5f else 3f)))
            if (look != "asleep") {  // from 112 up to the space left down to the bottom: the eyes above don't move
                CaptionLines(face, accent, modifier = Modifier.padding(top = 10.dp, bottom = s.dp(2f)).weight(1f, fill = false)
                    .width(s.width * (if (s.landscape) 0.7f else 0.9f)).heightIn(min = if (s.landscape) 0.dp else 112.dp))
            }
            FaceEndMark()
        }
        if (look == "asleep") {
            Clock(face) { time, day ->
                Row(Modifier.fillMaxWidth().padding(horizontal = s.dp(4f)).padding(top = s.dp(3f))) {
                    Text(day ?: "", color = grey, fontSize = s.sp(5f))
                    Spacer(Modifier.weight(1f))
                    Text(time ?: "", color = grey, fontSize = s.sp(5f))
                }
            }
        }
    }
}

@Composable
private fun EyesFace(face: FaceState, s: Sizes, look: String, accent: Color, blink: Boolean) {
    val t = clock()
    val v = s.v
    data class Eye(val w: Float, val h: Float, val cover: Float?, val lid: Float?)
    fun shape(left: Boolean): Eye = when (look) {
        "asleep" -> Eye(26f, 11f, -3.5f, null)
        "hearing" -> Eye(28f, 20f, null, null)
        "looking" -> Eye(27f, 22f, null, null)
        "speaking" -> Eye(26f, 13f, 4f, null)
        "question" -> if (left) Eye(28f, 23f, null, null) else Eye(26f, 13f, 4f, null)
        "alarm" -> Eye(28f, 23f, null, null)
        "error" -> Eye(26f, 17f, null, if (left) -16f else 16f)
        else -> Eye(26f, 17f, null, null)
    }
    val left = shape(true)
    val right = shape(false)
    val lw by animateFloatAsState(left.w, tween(200), label = "lw")
    val lh by animateFloatAsState(left.h, tween(200), label = "lh")
    val rw by animateFloatAsState(right.w, tween(200), label = "rw")
    val rh by animateFloatAsState(right.h, tween(200), label = "rh")
    val lc by animateFloatAsState(left.cover ?: 0f, tween(200), label = "lc")
    val rc by animateFloatAsState(right.cover ?: 0f, tween(200), label = "rc")
    val squint by animateFloatAsState(if (blink) 0.1f else 1f, tween(70), label = "blink")
    val move = when (look) {
        "awake" -> track(t, 9.0, listOf(Triple(0.0, 0f, 0f), Triple(0.22, 0f, 0f), Triple(0.25, -7f, 1.5f), Triple(0.45, -7f, 1.5f),
            Triple(0.48, 6f, -3f), Triple(0.60, 6f, -3f), Triple(0.63, 1f, 3f), Triple(0.80, 1f, 3f), Triple(0.83, 7f, 1f),
            Triple(0.97, 7f, 1f), Triple(1.0, 0f, 0f)))
        "thinking" -> track(t, 4.0, listOf(Triple(0.0, -6f, -4f), Triple(0.3, -6f, -4f), Triple(0.5, 6f, -4f), Triple(0.8, 6f, -4f), Triple(1.0, -6f, -4f)))
        "looking" -> track(t, 2.4, listOf(Triple(0.0, -9f, 0f), Triple(0.15, -9f, 0f), Triple(0.5, 9f, 0f), Triple(0.65, 9f, 0f), Triple(1.0, -9f, 0f)))
        "error" -> Offset(0f, 3f)
        else -> Offset.Zero
    }
    val scale = when (look) {
        "hearing" -> 1 + face.voice * 0.25f
        "alarm" -> 1 + 0.1f * beat(t, 0.6)
        else -> 1f
    }
    val hover = if (look == "asleep") 0f else -2f * swing(t, 3.2)
    Column(Modifier.offset(y = s.dp(hover)), horizontalAlignment = Alignment.CenterHorizontally) {
        Canvas(Modifier.width(s.width).height(s.dp(32f))) {
            val unit = v.dp.toPx()
            val center = Offset(size.width / 2 + move.x * unit, size.height / 2 + move.y * unit)
            scale(scale, center) {
                drawEye(Offset(center.x - (5f + lw / 2) * unit, center.y), lw * unit, lh * unit, -7f, left.cover?.let { lc * unit },
                    left.lid, squint, accent, face.background)
                drawEye(Offset(center.x + (5f + rw / 2) * unit, center.y), rw * unit, rh * unit, 7f, right.cover?.let { rc * unit },
                    right.lid, squint, accent, face.background)
            }
        }
        Box(Modifier.padding(top = s.dp(3f)).height(s.dp(10f)).width(s.width), contentAlignment = Alignment.Center) {
            if (look == "speaking") {
                Canvas(Modifier.fillMaxSize()) {
                    val unit = v.dp.toPx()
                    val step = t * 60
                    val loud = min(face.speech * 1.6f, 1f)
                    for (i in 0 until 5) {
                        val bar = 0.15f + loud * (0.55f + 0.45f * sin(step / 3 + i * 1.7).toFloat())
                        val x = size.width / 2 + (i - 2) * 4.2f * unit
                        val h = 9 * unit * bar
                        drawRoundRect(accent, Offset(x - 1.2f * unit, size.height / 2 - h / 2), Size(2.4f * unit, h),
                            androidx.compose.ui.geometry.CornerRadius(1.2f * unit))
                    }
                }
            }
            if (look == "thinking") {
                Canvas(Modifier.fillMaxSize()) {
                    val unit = v.dp.toPx()
                    for (i in 0 until 3) {
                        val p = ((t - i * 0.2) % 1.2) / 1.2
                        val lit = when { p < 0 -> 0.2; p < 0.4 -> 0.2 + 0.8 * p / 0.4; p < 0.8 -> 1 - 0.8 * (p - 0.4) / 0.4; else -> 0.2 }
                        drawCircle(accent.copy(alpha = lit.toFloat()), 1.3f * unit,
                            Offset(size.width / 2 + (i - 1) * 5f * unit, size.height - 1.3f * unit))
                    }
                }
            }
        }
    }
}

/** One eye: the oval, what covers part of it (a crescent: ‿ or ^; a lid: sad), tilted, blinking. */
private fun DrawScope.drawEye(center: Offset, w: Float, h: Float, tilt: Float, cover: Float?, lid: Float?, squint: Float,
                              color: Color, background: Color) {
    rotate(tilt, center) {
        scale(1f, squint, center) {
            val corner = Offset(center.x - w / 2, center.y - h / 2)
            drawOval(color, corner, Size(w, h))
            if (cover != null) drawOval(background, Offset(corner.x - w * 0.005f, corner.y + cover), Size(w * 1.01f, h))
            if (lid != null) {
                val lidCenter = Offset(center.x, center.y - 0.62f * h)
                rotate(lid, lidCenter) { drawRect(background, Offset(lidCenter.x - 0.9f * w, lidCenter.y - h / 2), Size(1.8f * w, h)) }
            }
        }
    }
}
