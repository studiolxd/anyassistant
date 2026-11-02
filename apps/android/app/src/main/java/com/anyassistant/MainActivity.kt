// The screen: pairing (the 6-digit code), then the face, full screen; «Ajustes» for the settings.
// Opened with «Hablar» (the shortcut, the quick settings, the assistant gesture), it listens.

package com.anyassistant

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.IconButton
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.imePadding
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material.icons.filled.Settings
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.combinedClickable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val link get() = App.link
    private var paired by mutableStateOf(false)
    private var repairing by mutableStateOf(false)  // «Pair again»: the code screen with a way back (what it had stays)
    private var invited by mutableStateOf<Invitation?>(null)  // what the QR or the link said: pairing with it
    private var scanAllowed by mutableStateOf(false)  // the camera, for «Escanear código»
    private val prefs get() = getSharedPreferences("anyassistant", Context.MODE_PRIVATE)

    private val ask = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { begin() }
    private val askCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { scanAllowed = it }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        paired = link.mac.paired
        WindowCompat.setDecorFitsSystemWindows(window, false)
        link.camera.attach(this)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(  // the app's own blue (the theme Eyes'), not Material's purple
                primary = Color(0xff34aff7), onPrimary = Color.Black,
                primaryContainer = Color(0xff34aff7), onPrimaryContainer = Color.Black,
                secondary = Color(0xff34aff7), onSecondary = Color.Black,
                secondaryContainer = Color(0xff123d57), onSecondaryContainer = Color.White,
                tertiary = Color(0xff34aff7), onTertiary = Color.Black)) {
                if (paired && link.state != Link.State.UNPAIRED) Face() else Pair()
            }
        }
        intent?.let(::opened)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        opened(intent)
    }

    /** «Hablar» (the shortcut, the quick settings, the assistant gesture): it listens. Opened by
     *  «Abrir en la app» on the QR's page, or the QR itself (anyassistant://connect?…, http://…/connect):
     *  it pairs with what the link says; paired already, with a way back if it fails. */
    private fun opened(intent: Intent) {
        if (intent.action == TALK || intent.action == Intent.ACTION_ASSIST || intent.action == Intent.ACTION_VOICE_COMMAND) {
            if (link.mac.paired) link.talk()
        }
        if (intent.action == Intent.ACTION_VIEW) {
            val invitation = intent.data?.let(Invitation::parse) ?: return
            intent.data = null  // once
            if (paired) pairAgain()
            invited = invitation
        }
    }

    /** «Pair again» chosen (or a QR's link while paired): the pairing screen, with a way back. What
     *  it had stays until a new pairing works (not even saved: reopening the app, it is still paired). */
    private fun pairAgain() {
        link.stop()
        ListenService.stop(this)
        repairing = true
        paired = false
    }

    /** The face, full screen (a swipe brings the bars back for a moment). */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) WindowInsetsControllerCompat(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onStart() {
        super.onStart()
        Notices.foreground = true
        keepAwake()
        if (paired) begin()
        link.cameraAllowed(true)
    }

    override fun onStop() {
        super.onStop()
        Notices.foreground = false
        link.cameraAllowed(false)
        if (!prefs.getBoolean("background", true)) {
            link.stop()
            ListenService.stop(this)
        }
    }

    private fun keepAwake() {
        if (prefs.getBoolean("awake", true)) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    /** The microphone (and the camera, the notifications) asked for once; then it connects and listens. */
    private fun begin() {
        val wanted = mutableListOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty() && !prefs.getBoolean("asked", false)) {
            prefs.edit().putBoolean("asked", true).apply()
            ask.launch(missing.toTypedArray())
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
        ListenService.start(this)
        link.start()
    }

    @OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
    @Composable
    private fun Face() {
        var settings by remember { mutableStateOf(false) }
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            // A tap: it stops talking or wakes up; held: the settings, always, whatever the theme.
            Box(Modifier.fillMaxSize().combinedClickable(remember { MutableInteractionSource() }, null,
                onLongClick = { settings = true }) { link.tap() }) {
                ThemeView(link.face, link.camera)
            }
            // «Ajustes», only asleep or in error (where it's needed), inside the safe area: where the
            // theme puts it (its options «settings»: bottom, top, bottom-left…) in its colour
            // («settings_color», else its accent), text or icon («settings_style»).
            val face = link.face
            if (face.look == "asleep" || face.look == "error") {
                val tint = face.color("settings_color", face.color("accent", face.color("glow", Color.White)))
                val place = when (face.options["settings"]) {
                    "top" -> Alignment.TopCenter
                    "top-left" -> Alignment.TopStart
                    "top-right" -> Alignment.TopEnd
                    "bottom-left" -> Alignment.BottomStart
                    "bottom-right" -> Alignment.BottomEnd
                    else -> Alignment.BottomCenter
                }
                val where = Modifier.align(place).systemBarsPadding().padding(12.dp)
                if (face.options["settings_style"] == "icon") {
                    Icon(Icons.Filled.Settings, getString(R.string.settings), tint = tint.copy(alpha = 0.8f),
                        modifier = where.size(40.dp).clip(CircleShape).background(tint.copy(alpha = 0.14f))
                            .clickable { settings = true }.padding(9.dp))
                } else {
                    Text(getString(R.string.settings), color = tint.copy(alpha = 0.85f), fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                        modifier = where.clip(RoundedCornerShape(50)).background(tint.copy(alpha = 0.14f))
                            .clickable { settings = true }.padding(horizontal = 18.dp, vertical = 9.dp))
                }
            }
            if (settings) Settings { settings = false }  // over the face, as iOS's sheet
        }
    }

    /** The settings, a page over the face: listening with the screen off, the screen on, the server
     *  (its host and port), «Connect» / «Connected» / «Connecting…» with why not under it, and
     *  «Pair again». «Done» (or back) leaves; left with another address, it connects to it. */
    @Composable
    private fun Settings(close: () -> Unit) {
        var background by remember { mutableStateOf(prefs.getBoolean("background", true)) }
        var awake by remember { mutableStateOf(prefs.getBoolean("awake", true)) }
        var host by remember { mutableStateOf(link.mac.host) }
        var port by remember { mutableStateOf(link.mac.port.toString()) }
        var connectedTo by remember { mutableStateOf(link.mac.host to link.mac.port) }  // where it was when the settings opened
        var checking by remember { mutableStateOf(false) }  // «Connect» pressed: trying it
        var problem by remember { mutableStateOf<String?>(null) }  // it didn't answer there
        val scope = rememberCoroutineScope()
        // The address or port changed here: connecting again is what applies it.
        val changed = host.trim() != connectedTo.first || (port.toIntOrNull() ?: 8080) != connectedTo.second
        val leave = { if (changed) { link.mac.moved(); link.restart() }; close() }
        BackHandler(onBack = leave)
        Column(Modifier.fillMaxSize().background(Color.Black).systemBarsPadding().imePadding()) {
            Row(Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(getString(R.string.settings), Modifier.weight(1f), fontSize = 22.sp, color = Color.White)
                TextButton(onClick = leave) { Text(getString(R.string.done)) }
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Toggle(getString(R.string.keep_listening), background) { background = it; prefs.edit().putBoolean("background", it).apply() }
                Toggle(getString(R.string.keep_screen_on), awake) { awake = it; prefs.edit().putBoolean("awake", it).apply(); keepAwake() }
                Text(getString(R.string.keep_listening_note), fontSize = 13.sp, color = Color.Gray)
                Text(getString(R.string.server), Modifier.padding(top = 16.dp), color = Color.Gray, fontSize = 13.sp)
                ServerFields(host, port, { host = it; link.mac.host = it; problem = null },
                    { port = it; it.toIntOrNull()?.let { number -> link.mac.port = number }; problem = null })
                // «Connected» (nothing to do) while it is, at the address it has; «Connect» if it isn't,
                // or the address or port changed (leaving the settings connects too); «Connecting…»
                // while it tries, and why not if it doesn't answer.
                val connected = link.state == Link.State.CONNECTED && !changed
                Button(onClick = {
                    if (changed) link.mac.moved()
                    connectedTo = link.mac.host to link.mac.port
                    problem = null
                    checking = true
                    link.restart()
                    scope.launch {
                        val answers = link.mac.url() != null
                        checking = false
                        if (!answers) problem = getString(R.string.mac_not_answering)
                    }
                }, enabled = !connected && !checking, modifier = Modifier.fillMaxWidth().padding(top = 8.dp).height(52.dp)) {
                    if (checking) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    Text(getString(if (checking) R.string.connecting else if (connected) R.string.connected else R.string.connect),
                        Modifier.padding(start = if (checking) 12.dp else 0.dp))
                }
                problem?.let { Text(it, fontSize = 13.sp, color = Color(0xffff6b6b)) }
                TextButton(onClick = { pairAgain(); close() }, Modifier.padding(top = 16.dp)) {
                    Text(getString(R.string.pair_again), color = Color(0xffff6b6b))
                }
                Spacer(Modifier.height(16.dp))
            }
        }
    }

    @Composable
    private fun Toggle(text: String, on: Boolean, change: (Boolean) -> Unit) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(text, Modifier.weight(1f), color = Color.White)
            Switch(on, change)
        }
    }

    /** Where the server is: its host (a name or an IP) and its port. */
    @Composable
    private fun ServerFields(host: String, port: String, hostChanged: (String) -> Unit, portChanged: (String) -> Unit) {
        OutlinedTextField(host, hostChanged, label = { Text(getString(R.string.mac_address)) },
            placeholder = { Text("anyassistant.local") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(port, { portChanged(it.filter(Char::isDigit).take(5)) }, label = { Text(getString(R.string.port)) },
            placeholder = { Text("8080") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
    }

    private enum class Step { CHOOSE, SCAN, MANUAL, CODE }

    /** Pairing as Android's own Wi-Fi settings: «Escanear código» (the QR that «Conectar otro
     *  dispositivo» shows on the server: it pairs by itself, as the app opened by the QR page's link
     *  does), the servers announcing themselves here or «Other server…», then the pairing code; a
     *  server that asks for none connects at once. A top bar with back and its title; the step's
     *  action, a filled button at the bottom, over the keyboard. */
    @Composable
    private fun Pair() {
        val context = LocalContext.current
        val servers = remember { Servers(context) }
        DisposableEffect(Unit) { servers.start(); onDispose { servers.stop() } }
        var step by remember { mutableStateOf(Step.CHOOSE) }
        var server by remember { mutableStateOf("") }  // «Eva en MacBook-Air-de-Suvi», or the host typed: never an IP it found
        var host by remember { mutableStateOf(link.mac.host) }
        var port by remember { mutableStateOf(link.mac.port.toString()) }
        var code by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        var connecting by remember { mutableStateOf<String?>(null) }  // the server connecting without a code
        var pairingWith by remember { mutableStateOf<Invitation?>(null) }  // pairing with what a QR or a link said
        var problem by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()
        val done = { repairing = false; paired = true; begin() }
        val notAnswering = context.getString(R.string.mac_not_answering)
        val wrongCode = context.getString(R.string.wrong_code)
        val withoutCode = {
            busy = true
            scope.launch { problem = try { link.mac.pair(""); done(); null } catch (e: Exception) { android.util.Log.w("AnyAssistant", "pairing", e); notAnswering }; busy = false }
        }
        val pair = {
            if (!busy && code.length == 6) {
                busy = true
                problem = null
                scope.launch {
                    problem = try { link.mac.pair(code); done(); null }
                    catch (e: Mac.WrongCode) { code = ""; wrongCode }
                    catch (e: Exception) { android.util.Log.w("AnyAssistant", "pairing", e); notAnswering }
                    busy = false
                }
            }
        }
        val next = {
            link.mac.host = host.trim()
            link.mac.port = port.toIntOrNull() ?: 8080
            link.mac.moved()
            busy = true
            problem = null
            scope.launch {
                when (link.mac.needsCode()) {
                    true -> { server = host.trim(); code = ""; step = Step.CODE }
                    false -> withoutCode()
                    null -> problem = notAnswering
                }
                busy = false
            }
        }
        // What a QR or a link said: where the server is and its code; nothing to type. The first
        // screen shows «Connecting to Eva…» meanwhile, and why not if it fails.
        val invitation = invited
        LaunchedEffect(invitation) {
            if (invitation == null) return@LaunchedEffect
            invited = null
            step = Step.CHOOSE
            pairingWith = invitation
            problem = null
            link.mac.host = invitation.host
            link.mac.port = invitation.port
            link.mac.moved()
            host = invitation.host
            port = invitation.port.toString()
            problem = try { link.mac.pair(invitation.code ?: ""); done(); null }
            catch (e: Mac.WrongCode) { wrongCode }
            catch (e: Exception) { android.util.Log.w("AnyAssistant", "pairing", e); notAnswering }
            pairingWith = null
        }
        val scan = {
            problem = null
            scanAllowed = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
            if (!scanAllowed) askCamera.launch(Manifest.permission.CAMERA)
            step = Step.SCAN
        }
        val back: (() -> Unit)? = when {
            step != Step.CHOOSE -> ({ problem = null; step = Step.CHOOSE })
            repairing -> ({ repairing = false; paired = true; begin() })  // from «Pair again»: as it was
            else -> null
        }
        Column(Modifier.fillMaxSize().background(Color.Black).systemBarsPadding().imePadding()) {
            // The top bar: back (or close, from «Pair again») and the step's title.
            Row(Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                if (back != null) {
                    IconButton(onClick = back) {
                        Icon(if (step == Step.CHOOSE) Icons.Outlined.Close else Icons.AutoMirrored.Outlined.ArrowBack,
                            getString(if (step == Step.CHOOSE) R.string.cancel else R.string.back), tint = Color.White)
                    }
                } else Spacer(Modifier.width(16.dp))
                Text(getString(when (step) { Step.CHOOSE -> R.string.connect; Step.SCAN -> R.string.scan_code; Step.MANUAL -> R.string.other_server; Step.CODE -> R.string.pair }),
                    fontSize = 22.sp, color = Color.White)
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
                when (step) {
                    Step.CHOOSE -> {
                        val with = pairingWith
                        if (with != null) {
                            Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                                Text(getString(R.string.connecting_to, with.name ?: with.host), Modifier.padding(start = 16.dp), color = Color.Gray)
                            }
                        } else ListRow(Icons.Outlined.QrCodeScanner, getString(R.string.scan_code), null, enabled = !busy, onClick = scan)
                        Text(getString(R.string.scan_hint), Modifier.padding(16.dp), color = Color.Gray, fontSize = 13.sp)
                        Text(getString(R.string.servers_here_title), Modifier.padding(start = 16.dp, top = 8.dp, bottom = 8.dp),
                            color = Color.Gray, fontSize = 13.sp)
                        if (servers.found.isEmpty()) {
                            Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                                Text(getString(R.string.searching), Modifier.padding(start = 16.dp), color = Color.Gray)
                            }
                        }
                        servers.found.forEach { found ->
                            ListRow(Icons.Outlined.Dns, found.assistant, found.computer, enabled = !busy, busy = connecting == found.id) {
                                link.mac.host = found.address
                                link.mac.port = found.port
                                link.mac.moved()
                                host = found.address
                                port = found.port.toString()
                                server = context.getString(R.string.on_computer, found.assistant, found.computer)
                                problem = null
                                if (found.pairing) { code = ""; step = Step.CODE } else {
                                    // Pairing is off on that server: nothing to type.
                                    connecting = found.id
                                    scope.launch {
                                        problem = try { busy = true; link.mac.pair(""); done(); null } catch (e: Exception) { android.util.Log.w("AnyAssistant", "pairing", e); notAnswering }
                                        busy = false
                                        connecting = null
                                    }
                                }
                            }
                        }
                        Footer(problem ?: getString(R.string.servers_here), problem != null)
                        ListRow(Icons.Outlined.Add, getString(R.string.other_server_more), null, enabled = !busy) {
                            problem = null; step = Step.MANUAL
                        }
                    }
                    Step.SCAN -> {
                        if (scanAllowed) Scanner(this@MainActivity) { found -> invited = found }
                        else Text(getString(R.string.camera_needed), Modifier.padding(16.dp), color = Color.Gray)
                        Text(getString(R.string.scan_hint), Modifier.padding(16.dp), color = Color.Gray, fontSize = 13.sp)
                    }
                    Step.MANUAL -> {
                        Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            ServerFields(host, port, { host = it; problem = null }, { port = it; problem = null })
                        }
                        Footer(problem ?: getString(R.string.host_hint), problem != null, Modifier.padding(top = 12.dp))
                    }
                    Step.CODE -> {
                        Text(getString(R.string.pairing_code), Modifier.fillMaxWidth().padding(top = 24.dp), fontSize = 22.sp,
                            color = Color.White, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                        Text(server, Modifier.fillMaxWidth().padding(top = 6.dp), color = Color.Gray, textAlign = TextAlign.Center)
                        CodeBoxes(code, { code = it; if (code.length == 6) pair() }, Modifier.padding(top = 28.dp))
                        Footer(problem ?: getString(R.string.pair_how), problem != null,
                            Modifier.fillMaxWidth().padding(top = 16.dp, start = 8.dp, end = 8.dp), TextAlign.Center)
                    }
                }
            }
            // The step's action: a filled button at the bottom, over the keyboard.
            if (step != Step.CHOOSE && step != Step.SCAN) {
                Button(onClick = { if (step == Step.MANUAL) next() else pair() },
                    enabled = !busy && (if (step == Step.MANUAL) host.isNotBlank() else code.length == 6),
                    modifier = Modifier.fillMaxWidth().padding(16.dp).height(52.dp)) {
                    if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    else Text(getString(if (step == Step.MANUAL) R.string.next else R.string.pair))
                }
            }
        }
    }

    /** A hint under a step's fields, or what went wrong, in red. */
    @Composable
    private fun Footer(text: String, wrong: Boolean, modifier: Modifier = Modifier.padding(16.dp), align: TextAlign = TextAlign.Start) {
        Text(text, modifier, color = if (wrong) Color(0xffff6b6b) else Color.Gray, fontSize = 13.sp, textAlign = align)
    }

    /** The pairing code: six boxes, one per digit, over the real field (the keyboard offers a code
     *  from Messages too); it pairs by itself with the sixth. */
    @Composable
    private fun CodeBoxes(code: String, change: (String) -> Unit, modifier: Modifier = Modifier) {
        val focus = remember { FocusRequester() }
        var typing by remember { mutableStateOf(false) }
        LaunchedEffect(Unit) { focus.requestFocus() }
        Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            BasicTextField(code, { change(it.filter(Char::isDigit).take(6)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                textStyle = TextStyle(color = Color.Transparent), cursorBrush = androidx.compose.ui.graphics.SolidColor(Color.Transparent),
                modifier = Modifier.fillMaxWidth().height(58.dp).alpha(0.01f).focusRequester(focus).onFocusChanged { typing = it.isFocused })
            Row(Modifier.clickable(remember { MutableInteractionSource() }, null) { focus.requestFocus() },
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                for (i in 0 until 6) {
                    val accent = MaterialTheme.colorScheme.primary
                    Box(Modifier.size(46.dp, 58.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xff1c1f26))
                        .border(2.dp, if (i == code.length && typing) accent else Color.Transparent, RoundedCornerShape(12.dp)),
                        contentAlignment = Alignment.Center) {
                        Text(if (i < code.length) code[i].toString() else "", color = Color.White, fontSize = 28.sp,
                            fontWeight = FontWeight.SemiBold, fontFamily = FontFamily.Monospace)
                    }
                }
            }
        }
    }

    /** A list item: its icon, a line and maybe a second, the whole row tappable; busy, a spinner at its end. */
    @Composable
    private fun ListRow(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, subtitle: String?,
                        enabled: Boolean, busy: Boolean = false, onClick: () -> Unit) {
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).background(Color(0xff1c1f26), RoundedCornerShape(16.dp))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = Color(0xff8ab4f8))
            Column(Modifier.weight(1f).padding(start = 16.dp)) {
                Text(title, color = Color.White, fontSize = 16.sp)
                subtitle?.let { Text(it, color = Color.Gray, fontSize = 14.sp) }
            }
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        }
    }

    companion object {
        const val TALK = "com.anyassistant.TALK"
    }
}
