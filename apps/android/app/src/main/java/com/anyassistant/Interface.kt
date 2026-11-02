// The interface's language: the app's setting «Idioma de la interfaz» (Automático: the phone's).
// Not the language the assistant speaks, which is the server's. The app's own texts follow it
// (Android 13 or later: its per-app language, LocaleManager; before: its activity's and services'
// context, wrap), and so do the face's from the server (/config?ui=…); it is kept on the server for
// this device too, so a choice made in the Mac's Devices comes here (Link.configure).

package com.anyassistant

import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.os.LocaleList
import java.util.Locale

object Interface {
    /** The languages the app has texts in. */
    val languages = listOf("en", "es")

    private fun prefs(context: Context) = context.getSharedPreferences("anyassistant", Context.MODE_PRIVATE)

    /** «auto», «es», «en». */
    fun chosen(context: Context): String =
        prefs(context).getString("ui_language", "auto").takeIf { it in languages } ?: "auto"

    /** The language it is in now: the chosen one, or the phone's if the app has texts in it. */
    fun code(context: Context): String = chosen(context).takeIf { it != "auto" }
        ?: Locale.getDefault().language.takeIf { it in languages } ?: "en"

    /** A choice made here that the server doesn't have yet (it was unreachable): sent first next time. */
    fun unsaved(context: Context) = prefs(context).getBoolean("ui_language_unsaved", false)

    fun saved(context: Context) = prefs(context).edit().putBoolean("ui_language_unsaved", false).apply()

    /** Chooses it (from the app's settings, unsaved until the server has it; or from the server). */
    fun choose(context: Context, code: String, fromServer: Boolean = false) {
        prefs(context).edit().putString("ui_language", if (code in languages) code else "auto")
            .putBoolean("ui_language_unsaved", !fromServer).apply()
        apply(context)
    }

    /** Android 13 or later: the app's own language, for all of it (its activity is made again). */
    fun apply(context: Context) {
        if (Build.VERSION.SDK_INT < 33) return
        val chosen = chosen(context)
        val wanted = if (chosen == "auto") LocaleList.getEmptyLocaleList() else LocaleList.forLanguageTags(chosen)
        val manager = context.getSystemService(LocaleManager::class.java) ?: return
        if (manager.applicationLocales != wanted) manager.applicationLocales = wanted
    }

    /** Before Android 13: a context in the chosen language (an activity's or a service's base). */
    fun wrap(base: Context): Context {
        val chosen = chosen(base)
        if (Build.VERSION.SDK_INT >= 33 || chosen == "auto") return base
        val configuration = Configuration(base.resources.configuration)
        configuration.setLocale(Locale.forLanguageTag(chosen))
        return base.createConfigurationContext(configuration)
    }
}
