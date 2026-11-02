// The app: one connection with the Mac for everything (App.link), kept alive with the screen off
// by ListenService (Android asks for a notification while it uses the microphone in the
// background), and «Hablar» from the quick settings (TalkTile).

package com.anyassistant

import android.app.Application
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.service.quicksettings.TileService
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

class App : Application() {
    override fun attachBaseContext(base: Context) = super.attachBaseContext(Interface.wrap(base))

    override fun onCreate() {
        super.onCreate()
        Interface.apply(this)  // the interface's language chosen in the app (Android 13 or later: its own)
        Notices.channels(this)
        link = Link(this)
    }

    companion object {
        lateinit var link: Link
            private set
    }
}

/** While it listens: a quiet notification («Eva is listening»), so Android lets it keep the microphone. */
class ListenService : Service() {
    override fun attachBaseContext(base: Context) = super.attachBaseContext(Interface.wrap(base))

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == STOP) {
            App.link.stop()
            stopSelf()
            return START_NOT_STICKY
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, ListenService::class.java).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(this, Notices.LISTENING)
            .setSmallIcon(R.drawable.ic_eyes)
            .setContentTitle(getString(R.string.listening, App.link.face.name))
            .setContentIntent(open).setOngoing(true)
            .addAction(0, getString(R.string.stop_listening), stop).build()
        runCatching {
            ServiceCompat.startForeground(this, 3, notification,
                if (Build.VERSION.SDK_INT >= 30) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0)
        }
        return START_STICKY
    }

    companion object {
        const val STOP = "com.anyassistant.STOP_LISTENING"

        fun start(context: Context) = runCatching { ContextCompat.startForegroundService(context, Intent(context, ListenService::class.java)) }
        fun stop(context: Context) = context.stopService(Intent(context, ListenService::class.java))
    }
}

/** «Hablar» in the quick settings: opens it listening. */
class TalkTile : TileService() {
    override fun onClick() {
        val talk = Intent(this, MainActivity::class.java).setAction(MainActivity.TALK).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 0, talk, PendingIntent.FLAG_IMMUTABLE))
        } else {
            @Suppress("DEPRECATION", "StartActivityAndCollapseDeprecated")
            startActivityAndCollapse(talk)
        }
    }
}
