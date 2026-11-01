// The screen: pairing (the 6-digit code), then the face, full screen; the gear for the settings.
// Opened with «Hablar» (the shortcut, the quick settings, the assistant gesture), it listens.

package com.anyassistant

import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val link get() = App.link
    private var paired by mutableStateOf(false)
    private var repairing by mutableStateOf(false)  // «Pair again»: the code screen with a way back (what it had stays)
    private val prefs get() = getSharedPreferences("anyassistant", Context.MODE_PRIVATE)

    private val ask = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { begin() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        paired = link.mac.paired
        WindowCompat.setDecorFitsSystemWindows(window, false)
        link.camera.attach(this)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                if (paired && link.state != Link.State.UNPAIRED) Face() else Pair()
            }
        }
        intent?.let(::opened)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        opened(intent)
    }

    /** «Hablar» (the shortcut, the quick settings, the assistant gesture): it listens. */
    private fun opened(intent: Intent) {
        if (intent.action == TALK || intent.action == Intent.ACTION_ASSIST || intent.action == Intent.ACTION_VOICE_COMMAND) {
            if (link.mac.paired) link.talk()
        }
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

    @Composable
    private fun Face() {
        var settings by remember { mutableStateOf(false) }
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            Box(Modifier.fillMaxSize().clickable(remember { MutableInteractionSource() }, null) { link.tap() }) {
                SkinView(link.face, link.camera)
            }
            Icon(Icons.Outlined.Settings, getString(R.string.settings), tint = Color.White.copy(alpha = 0.35f),
                modifier = Modifier.align(Alignment.BottomEnd).navigationBarsPadding().padding(6.dp).size(56.dp)
                    .clickable { settings = true }.padding(16.dp))
        }
        if (settings) Settings { settings = false }
    }

    @Composable
    private fun Settings(close: () -> Unit) {
        var background by remember { mutableStateOf(prefs.getBoolean("background", true)) }
        var awake by remember { mutableStateOf(prefs.getBoolean("awake", true)) }
        var host by remember { mutableStateOf(link.mac.host) }
        var connectedTo by remember { mutableStateOf(link.mac.host) }  // the address when it opened
        val changed = host != connectedTo
        // Leaving the settings with another address connects to it.
        val leave = { if (changed) link.restart(); close() }
        AlertDialog(onDismissRequest = leave, confirmButton = { TextButton(onClick = leave) { Text(getString(R.string.done)) } },
            title = { Text(getString(R.string.settings)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Toggle(getString(R.string.keep_listening), background) { background = it; prefs.edit().putBoolean("background", it).apply() }
                    Text(getString(R.string.keep_listening_note), fontSize = 13.sp, color = Color.Gray)
                    Toggle(getString(R.string.keep_screen_on), awake) { awake = it; prefs.edit().putBoolean("awake", it).apply(); keepAwake() }
                    OutlinedTextField(host, { host = it; link.mac.host = it }, label = { Text(getString(R.string.mac_address)) },
                        placeholder = { Text(getString(R.string.found_by_itself)) }, singleLine = true)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        // «Connected» (nothing to do) while it is, at this address; «Connect» if not, or it changed.
                        val connected = link.state == Link.State.CONNECTED && !changed
                        TextButton(onClick = { link.restart(); connectedTo = host }, enabled = !connected) {
                            Text(getString(if (connected) R.string.connected else R.string.connect))
                        }
                        TextButton(onClick = {
                            link.stop(); ListenService.stop(this@MainActivity); repairing = true; paired = false; close()
                        }) { Text(getString(R.string.pair_again), color = Color(0xffff6b6b)) }
                    }
                }
            })
    }

    @Composable
    private fun Toggle(text: String, on: Boolean, change: (Boolean) -> Unit) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(text, Modifier.weight(1f))
            Switch(on, change)
        }
    }

    private enum class Step { CHOOSE, MANUAL, CODE }

    /** Pairing in two steps: the server (the ones announcing themselves here, or its host by hand),
     *  then its code; a server that asks for none connects at once. */
    @Composable
    private fun Pair() {
        val context = LocalContext.current
        val servers = remember { Servers(context) }
        DisposableEffect(Unit) { servers.start(); onDispose { servers.stop() } }
        var step by remember { mutableStateOf(Step.CHOOSE) }
        var server by remember { mutableStateOf("") }  // its name, shown with the code
        var busy by remember { mutableStateOf(false) }
        var problem by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()
        val done = { repairing = false; paired = true; begin() }
        val withoutCode = {
            busy = true
            scope.launch {
                problem = try { link.mac.pair(""); done(); null } catch (e: Exception) { context.getString(R.string.mac_not_answering) }
                busy = false
            }
        }
        Column(Modifier.fillMaxSize().background(Color.Black).padding(28.dp), verticalArrangement = Arrangement.Center) {
            when (step) {
                Step.CHOOSE -> {
                    Text(getString(R.string.choose_server), fontSize = 22.sp, color = Color.White)
                    if (servers.found.isEmpty()) {
                        Row(Modifier.padding(vertical = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                            Text(getString(R.string.looking_for_servers), Modifier.padding(start = 12.dp), color = Color.Gray)
                        }
                    }
                    servers.found.forEach { found ->
                        Row(Modifier.fillMaxWidth().padding(top = 12.dp).background(Color(0xff1c1f26), RoundedCornerShape(12.dp))
                            .clickable(enabled = !busy) {
                                link.mac.host = found.address
                                link.mac.port = found.port
                                server = found.computer
                                if (found.pairing) step = Step.CODE else withoutCode()
                            }.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(found.assistant, color = Color.White, fontSize = 17.sp)
                                Text(found.computer, color = Color.Gray, fontSize = 13.sp)
                            }
                            Text("›", color = Color.Gray, fontSize = 22.sp)
                        }
                    }
                    Text(getString(R.string.servers_here), Modifier.padding(top = 16.dp), color = Color.Gray, fontSize = 13.sp)
                    TextButton(onClick = { problem = null; step = Step.MANUAL }, Modifier.padding(top = 8.dp)) {
                        Text(getString(R.string.type_host))
                    }
                }
                Step.MANUAL -> {
                    var host by remember { mutableStateOf(link.mac.host) }
                    var port by remember { mutableStateOf(link.mac.port.toString()) }
                    Text(getString(R.string.server), fontSize = 22.sp, color = Color.White)
                    OutlinedTextField(host, { host = it }, label = { Text(getString(R.string.mac_address)) },
                        placeholder = { Text("anyassistant.local · 192.168.1.10") }, singleLine = true,
                        modifier = Modifier.padding(top = 16.dp).fillMaxWidth())
                    OutlinedTextField(port, { port = it.filter(Char::isDigit).take(5) }, label = { Text(getString(R.string.port)) },
                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.padding(top = 8.dp).fillMaxWidth())
                    Button(onClick = {
                        link.mac.host = host.trim()
                        link.mac.port = port.toIntOrNull() ?: 8080
                        busy = true
                        problem = null
                        scope.launch {
                            when (link.mac.needsCode()) {
                                true -> { server = host.trim(); step = Step.CODE }
                                false -> withoutCode()
                                null -> problem = context.getString(R.string.mac_not_answering)
                            }
                            busy = false
                        }
                    }, enabled = !busy && host.isNotBlank(), modifier = Modifier.padding(top = 16.dp).fillMaxWidth()) {
                        Text(getString(R.string.next))
                    }
                    TextButton(onClick = { problem = null; step = Step.CHOOSE }) { Text(getString(R.string.back)) }
                }
                Step.CODE -> {
                    var code by remember { mutableStateOf("") }
                    val pair = {
                        busy = true
                        problem = null
                        scope.launch {
                            problem = try { link.mac.pair(code); done(); null }
                            catch (e: Mac.WrongCode) { code = ""; context.getString(R.string.wrong_code) }
                            catch (e: Exception) { context.getString(R.string.mac_not_answering) }
                            busy = false
                        }
                    }
                    Text(getString(R.string.code_from_mac), fontSize = 22.sp, color = Color.White)
                    Text(server, color = Color.Gray)
                    // One field, its six digits big and spaced; it pairs by itself with the sixth.
                    OutlinedTextField(code, {
                        code = it.filter(Char::isDigit).take(6)
                        if (code.length == 6 && !busy) pair()
                    }, singleLine = true, placeholder = { Text("000000", letterSpacing = 8.sp, fontSize = 28.sp) },
                        textStyle = androidx.compose.ui.text.TextStyle(fontSize = 28.sp, letterSpacing = 8.sp, color = Color.White,
                            textAlign = TextAlign.Center),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                        modifier = Modifier.padding(top = 20.dp).fillMaxWidth())
                    Button(onClick = { pair() }, enabled = !busy && code.length == 6, modifier = Modifier.padding(top = 16.dp).fillMaxWidth()) {
                        if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text(getString(R.string.pair))
                    }
                    Text(getString(R.string.pair_how), Modifier.padding(top = 16.dp), color = Color.Gray, fontSize = 13.sp)
                    TextButton(onClick = { problem = null; step = Step.CHOOSE }) { Text(getString(R.string.back)) }
                }
            }
            problem?.let { Text(it, Modifier.padding(top = 12.dp), color = Color(0xffff6b6b)) }
            if (repairing) {  // from «Pair again»: back as it was
                TextButton(onClick = { repairing = false; paired = true; begin() }) { Text(getString(R.string.cancel)) }
            }
        }
    }

    companion object {
        const val TALK = "com.anyassistant.TALK"
    }
}
