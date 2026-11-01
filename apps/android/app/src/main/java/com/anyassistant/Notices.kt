// The phone's notifications: its answers and messages from other rooms while the app is in the
// background (in front, the Mac's voice says them), and the Mac's alarms, timers and reminders
// as the phone's own alarms (Alarms).

package com.anyassistant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONObject

object Notices {
    const val ANSWERS = "answers"
    const val LISTENING = "listening"
    const val RINGING = "ringing"
    @Volatile var foreground = true

    fun channels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(ANSWERS, context.getString(R.string.channel_answers), NotificationManager.IMPORTANCE_HIGH))
        manager.createNotificationChannel(NotificationChannel(LISTENING, context.getString(R.string.channel_listening), NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel(RINGING, context.getString(R.string.channel_ringing), NotificationManager.IMPORTANCE_HIGH).apply {
            setSound(null, null)  // the ringing service plays the alarm itself
        })
    }

    fun handle(context: Context, message: JSONObject, name: String) {
        when (message.optString("type")) {
            "timers" -> Alarms.set(context, message.optJSONArray("items"))
            "text" -> {
                val text = message.optString("text")
                if (foreground || message.optString("author") != "assistant" || message.optBoolean("partial") || text.isEmpty()) return
                val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
                val notification = NotificationCompat.Builder(context, ANSWERS)
                    .setSmallIcon(R.drawable.ic_eyes).setContentTitle(name).setContentText(text)
                    .setStyle(NotificationCompat.BigTextStyle().bigText(text)).setContentIntent(open).setAutoCancel(true).build()
                runCatching { NotificationManagerCompat.from(context).notify(text.hashCode(), notification) }
            }
        }
    }
}
