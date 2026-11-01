// The Mac's alarms, timers and reminders as the phone's own alarms: the system's alarm clock
// (AlarmManager.setAlarmClock, shown in the status bar), ringing on the alarm channel (even on
// silent), full screen over the lock screen, with the app closed. Stopped on the phone, the Mac
// stops ringing too; stopped on the Mac («para»), it goes from the phone.

package com.anyassistant

import android.app.AlarmManager
import android.app.KeyguardManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

object Alarms {
    private const val KEY = "alarms"  // «<kind>-<at>» → its request code

    fun title(context: Context, kind: String, label: String): String =
        context.getString(when (kind) { "alarm" -> R.string.alarm; "reminder" -> R.string.reminder; else -> R.string.timer }) +
            if (label.isEmpty()) "" else " · $label"

    /** The Mac's running timers, alarms and reminders, as the phone's (each time they change). */
    fun set(context: Context, items: JSONArray?) {
        val prefs = context.getSharedPreferences("anyassistant", Context.MODE_PRIVATE)
        val known = JSONObject(prefs.getString(KEY, "{}") ?: "{}")
        val manager = context.getSystemService(AlarmManager::class.java)
        val now = System.currentTimeMillis() / 1000.0
        val wanted = mutableMapOf<String, Triple<Double, String, String>>()
        for (i in 0 until (items?.length() ?: 0)) {
            val item = items!!.optJSONObject(i) ?: continue
            val at = item.optDouble("at")
            if (at.isNaN() || at <= now + 1) continue
            val kind = item.optString("kind", "timer")
            wanted["$kind-${at.toLong()}"] = Triple(at, kind, item.optString("label"))
        }
        for (name in known.keys().asSequence().toList()) {
            if (name !in wanted) {  // stopped, done or removed on the Mac
                manager.cancel(pending(context, known.getInt(name), "", ""))
                known.remove(name)
            }
        }
        for ((name, value) in wanted) {
            if (known.has(name)) continue
            val (at, kind, label) = value
            val code = name.hashCode()
            val ring = pending(context, code, kind, label)
            val millis = (at * 1000).toLong()
            val open = PendingIntent.getActivity(context, code, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            if (Build.VERSION.SDK_INT < 31 || manager.canScheduleExactAlarms()) {
                manager.setAlarmClock(AlarmManager.AlarmClockInfo(millis, open), ring)
            } else {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, millis, ring)  // not exact: the best it may
            }
            known.put(name, code)
        }
        prefs.edit().putString(KEY, known.toString()).apply()
    }

    private fun pending(context: Context, code: Int, kind: String, label: String): PendingIntent =
        PendingIntent.getBroadcast(context, code, Intent(context, AlarmReceiver::class.java).putExtra("kind", kind).putExtra("label", label),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}

/** It's time: it rings. */
class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val ring = Intent(context, RingingService::class.java)
            .putExtra("title", Alarms.title(context, intent.getStringExtra("kind") ?: "timer", intent.getStringExtra("label") ?: ""))
        ContextCompat.startForegroundService(context, ring)
    }
}

/** Rings (the phone's alarm sound, on the alarm channel) until stopped, or for 5 minutes. */
class RingingService : Service() {
    private var player: MediaPlayer? = null
    private val main = Handler(Looper.getMainLooper())

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        val title = intent?.getStringExtra("title") ?: getString(R.string.timer)
        val full = PendingIntent.getActivity(this, 1, Intent(this, RingingActivity::class.java).putExtra("title", title)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 2, Intent(this, RingingService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, Notices.RINGING)
            .setSmallIcon(R.drawable.ic_eyes).setContentTitle(title)
            .setCategory(NotificationCompat.CATEGORY_ALARM).setPriority(NotificationCompat.PRIORITY_MAX)
            .setFullScreenIntent(full, true).setContentIntent(full).setOngoing(true)
            .addAction(0, getString(R.string.stop), stop).build()
        ServiceCompat.startForeground(this, 7, notification,
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK else 0)
        if (player == null) {
            val sound = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            player = runCatching {
                MediaPlayer().apply {
                    setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                    setDataSource(this@RingingService, sound)
                    isLooping = true
                    prepare()
                    start()
                }
            }.getOrNull()
            main.postDelayed({ stopSelf() }, 5 * 60 * 1000L)
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        player?.let { runCatching { it.stop() }; it.release() }
        player = null
        App.link.stopRinging()  // the Mac stops ringing too
        sendBroadcast(Intent(STOPPED).setPackage(packageName))
        super.onDestroy()
    }

    companion object {
        const val STOP = "com.anyassistant.STOP_RINGING"
        const val STOPPED = "com.anyassistant.RINGING_STOPPED"
    }
}

/** Full screen, over the lock screen: what is ringing, and «Stop». */
class RingingActivity : ComponentActivity() {
    private val stopped = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) = finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            getSystemService(KeyguardManager::class.java).requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        }
        ContextCompat.registerReceiver(this, stopped, android.content.IntentFilter(RingingService.STOPPED), ContextCompat.RECEIVER_NOT_EXPORTED)
        val title = intent.getStringExtra("title") ?: ""
        setContent {
            Column(Modifier.fillMaxSize().background(Color.Black).padding(32.dp), verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text(title, color = Color.White, fontSize = 34.sp, textAlign = TextAlign.Center)
                Button(onClick = { stop() }, Modifier.padding(top = 48.dp)) { Text(getString(R.string.stop), fontSize = 24.sp) }
            }
        }
    }

    private fun stop() {
        startService(Intent(this, RingingService::class.java).setAction(RingingService.STOP))
        finish()
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(stopped) }
        super.onDestroy()
    }
}
