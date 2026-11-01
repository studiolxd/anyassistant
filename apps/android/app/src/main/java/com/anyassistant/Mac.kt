// Talking to the Mac: finding it (Bonjour, «_anyassistant._tcp»: many Androids don't resolve
// anyassistant.local), pairing with the code (its cookie), and HTTPS trusting only the Mac's own
// certificate authority, learnt when pairing. The same as the Apple apps' Mac.swift.

package com.anyassistant

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

class Mac(private val context: Context) {
    private val prefs = context.getSharedPreferences("anyassistant", Context.MODE_PRIVATE)

    class Unreachable : Exception()
    class WrongCode : Exception()

    /** How it introduces itself: the Mac's devices tell a phone («Mobile») from a tablet. */
    val agent: String = if (context.resources.configuration.smallestScreenWidthDp >= 600)
        "AnyAssistant Android" else "AnyAssistant Android Mobile"

    /** This device's id for the Mac. */
    val device: String = prefs.getString("device", null) ?: UUID.randomUUID().toString().replace("-", "").also {
        prefs.edit().putString("device", it).apply()
    }

    var paired: Boolean
        get() = prefs.getBoolean("paired", false)
        set(value) = prefs.edit().putBoolean("paired", value).apply()

    /** The Mac's name or address, typed (empty: found by Bonjour). */
    var host: String
        get() = prefs.getString("host", "") ?: ""
        set(value) = prefs.edit().putString("host", value.trim()).apply()

    var port: Int
        get() = prefs.getInt("port", 8080)
        set(value) = prefs.edit().putInt("port", value).apply()

    /** Which server it is paired with (its /status «server», its Bonjour «id»): looking for it by
     *  Bonjour takes that one only, never another server on the same network. */
    private var server: String?
        get() = prefs.getString("server", null)
        set(value) = prefs.edit().putString("server", value).apply()

    /** Its IP, as Bonjour found it last (or as pairing learnt it). */
    private var address: String?
        get() = prefs.getString("address", null)
        set(value) = prefs.edit().putString("address", value).apply()

    private var httpsPort: Int
        get() = prefs.getInt("httpsPort", 0)
        set(value) = prefs.edit().putInt("httpsPort", value).apply()

    private var authority: ByteArray?
        get() = prefs.getString("authority", null)?.let { Base64.decode(it, Base64.DEFAULT) }
        set(value) = prefs.edit().putString("authority", value?.let { Base64.encodeToString(it, Base64.NO_WRAP) }).apply()

    /** The pairing's cookie («jarvis_device=…»), sent with everything. */
    var cookie: String?
        get() = prefs.getString("cookie", null)
        private set(value) = prefs.edit().putString("cookie", value).apply()

    fun unpair() {
        paired = false
        cookie = null
    }

    // --- HTTP ---

    private fun plainClient(seconds: Long) = OkHttpClient.Builder()
        .connectTimeout(seconds, TimeUnit.SECONDS).readTimeout(seconds, TimeUnit.SECONDS).build()

    /** Over HTTPS, only the Mac's authority is trusted (its own: whichever name or IP it is reached by). */
    val client: OkHttpClient get() = clients(90)
    private val quick: OkHttpClient get() = clients(5)
    private val built = mutableMapOf<Pair<Long, String?>, OkHttpClient>()

    @Synchronized
    private fun clients(seconds: Long): OkHttpClient {
        val key = seconds to prefs.getString("authority", null)  // again once pairing learns the authority
        return built.getOrPut(key) { build(seconds) }
    }

    private fun build(seconds: Long): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(seconds.coerceAtMost(8), TimeUnit.SECONDS)
            .readTimeout(seconds, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
        authority?.let { der ->
            val certificate = CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(der)) as X509Certificate
            val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null, null); setCertificateEntry("mac", certificate) }
            val trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(store) }
            val manager = trust.trustManagers.first() as X509TrustManager
            val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf(manager), null) }
            builder.sslSocketFactory(ssl.socketFactory, manager).hostnameVerifier { _, _ -> true }  // the chain is the check
        }
        return builder.build()
    }

    fun base(name: String): String =
        if (authority != null && httpsPort > 0) (if (httpsPort == 443) "https://$name" else "https://$name:$httpsPort")
        else "http://$name:$port"

    fun request(url: String): Request.Builder = Request.Builder().url(url).header("User-Agent", agent).apply {
        cookie?.let { header("Cookie", it) }
    }

    /** Where it answers now: what Bonjour finds, its IP, its name; null if none answers. */
    suspend fun url(): String? = withContext(Dispatchers.IO) {
        fun answers(name: String) = runCatching {
            quick.newCall(request(base(name) + "/status").build()).execute().use { answer ->
                if (answer.code == 200) {
                    val said = runCatching { JSONObject(answer.body.string()).optString("server") }.getOrDefault("")
                    if (said.isNotEmpty()) {
                        if (server == null) server = said  // the first time it answers: it is this one
                        else if (said != server) return@runCatching false  // another server there: not ours
                    }
                }
                true
            }
        }.getOrDefault(false)
        if (exact && host.isNotEmpty()) {  // moved by hand: there or nowhere (not the old one, nor another found)
            return@withContext if (answers(host)) { exact = false; lastGood = host; base(host) } else null
        }
        lastGood?.let { if (answers(it)) return@withContext base(it) }  // the one that answered last: at once
        val names = linkedSetOf<String>()
        if (host.isNotEmpty()) names += host
        address?.let { names += it }
        for (name in names) if (answers(name)) { lastGood = name; return@withContext base(name) }
        val found = discover()  // Bonjour (a few seconds): the Mac's address may have changed
        for (name in listOfNotNull(found, "anyassistant.local")) if (answers(name)) { lastGood = name; return@withContext base(name) }
        null
    }

    @Volatile private var lastGood: String? = null
    @Volatile private var exact = false

    /** Moved by hand (another host or port, in the settings or pairing): the IP it had was the old
     *  server's, and until it answers at the new place nothing else stands in for it. */
    fun moved() {
        address = null
        server = null  // learnt again where it answers now
        lastGood = null
        exact = host.isNotEmpty()
    }

    // --- Bonjour ---

    /** The Mac's IP as Bonjour announces it (and its port), within a few seconds: only the server
     *  it is paired with (its «id»); null if not found or not known yet. */
    suspend fun discover(): String? {
        val wanted = server ?: return null
        val found = withContext(Dispatchers.Main) {
            val servers = Servers(context)
            servers.start()
            try {
                withTimeoutOrNull(5000) {
                    var hit: Servers.Found? = null
                    while (hit == null) {
                        hit = servers.found.firstOrNull { it.server == wanted }
                        if (hit == null) delay(250)
                    }
                    hit
                }
            } finally { servers.stop() }
        } ?: return null
        address = found.address
        port = found.port
        if (Regex("""\d{1,3}(\.\d{1,3}){3}""").matches(host)) host = found.address  // the settings show it where it is
        return found.address
    }

    // --- Pairing ---

    /** Pairs with the code (if the Mac asks for one) and learns its HTTPS authority. */
    /** Whether the server at its host asks for a code (null: it doesn't answer). */
    suspend fun needsCode(): Boolean? = withContext(Dispatchers.IO) {
        runCatching {
            plainClient(8).newCall(Request.Builder().url("http://$host:$port/status").build()).execute().use { it.code == 403 }
        }.getOrNull()
    }

    suspend fun pair(code: String) = withContext(Dispatchers.IO) {
        val names = linkedSetOf<String>()
        if (host.isNotEmpty()) names += host
        if (!exact) {
            discover()?.let { names += it }
            address?.let { names += it }
            names += "anyassistant.local"
        }
        val plainClient = plainClient(8)
        val name = names.firstOrNull { name ->
            runCatching { plainClient.newCall(Request.Builder().url("http://$name:$port/status").build()).execute().close() }.isSuccess
        } ?: throw Unreachable()
        val plain = "http://$name:$port"
        val status = plainClient.newCall(Request.Builder().url("$plain/status").header("User-Agent", agent).build()).execute().use { it.code }
        if (status == 403) {
            val body = JSONObject().put("code", code).toString().toRequestBody("application/json".toMediaType())
            plainClient.newCall(Request.Builder().url("$plain/pair").post(body).header("User-Agent", agent).build()).execute().use { answer ->
                if (answer.code != 200) throw WrongCode()
                cookie = answer.headers("Set-Cookie").firstOrNull { it.startsWith("jarvis_device=") }?.substringBefore(";")
            }
        }
        // HTTPS, if the Mac has it: its authority, to trust it (and nothing else) from now on.
        runCatching {
            val info = plainClient.newCall(Request.Builder().url("$plain/https/info").build()).execute().use {
                if (it.code == 200) JSONObject(it.body.string()) else null
            }
            if (info != null) {
                val der = plainClient.newCall(Request.Builder().url("$plain/https/ca.crt").build()).execute().use {
                    if (it.code == 200) it.body.bytes() else null
                }
                if (der != null) {
                    authority = der
                    httpsPort = info.optInt("port", 443)
                }
                val addresses = info.optJSONArray("addresses")
                for (i in 0 until (addresses?.length() ?: 0)) {
                    val ip = addresses!!.getString(i)
                    if (ip != "127.0.0.1" && !ip.contains(":")) { address = ip; break }
                }
            }
        }
        paired = true
    }
}

/** The servers announcing themselves on this network (Bonjour «_anyassistant._tcp»), as they come
 *  and go: for the first pairing step. Android resolves one at a time: they queue. */
class Servers(context: Context) {
    data class Found(val id: String, val assistant: String, val computer: String, val address: String,
                     val port: Int, val pairing: Boolean, val server: String?)

    val found = androidx.compose.runtime.mutableStateListOf<Found>()
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val waiting = ArrayDeque<NsdServiceInfo>()
    private var resolving = false
    private var listener: NsdManager.DiscoveryListener? = null
    private val main = android.os.Handler(android.os.Looper.getMainLooper())

    fun start() {
        if (listener != null) return
        val made = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(info: NsdServiceInfo) = main.post { waiting.add(info); next() }.let {}
            override fun onServiceLost(info: NsdServiceInfo) = main.post { found.removeAll { it.id == info.serviceName } }.let {}
            override fun onDiscoveryStarted(type: String) {}
            override fun onDiscoveryStopped(type: String) {}
            override fun onStartDiscoveryFailed(type: String, code: Int) {}
            override fun onStopDiscoveryFailed(type: String, code: Int) {}
        }
        listener = made
        nsd.discoverServices("_anyassistant._tcp", NsdManager.PROTOCOL_DNS_SD, made)
    }

    fun stop() {
        listener?.let { runCatching { nsd.stopServiceDiscovery(it) } }
        listener = null
    }

    private fun next() {
        if (resolving) return
        val info = waiting.removeFirstOrNull() ?: return
        resolving = true
        @Suppress("DEPRECATION")
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, code: Int) = main.post { resolving = false; next() }.let {}
            override fun onServiceResolved(info: NsdServiceInfo) = main.post {
                val text = { key: String -> info.attributes[key]?.let { String(it) } }
                val address = text("address") ?: (if (Build.VERSION.SDK_INT >= 34) info.hostAddresses.firstOrNull() else info.host)
                    ?.hostAddress?.takeIf { !it.contains(":") }
                if (address != null) {
                    found.removeAll { it.id == info.serviceName }
                    found.add(Found(info.serviceName, text("name") ?: "AnyAssistant",
                        text("computer") ?: info.serviceName.removePrefix("AnyAssistant on "), address,
                        text("port")?.toIntOrNull() ?: info.port, text("pairing") != "0", text("id")))
                }
                resolving = false
                next()
            }.let {}
        })
    }
}
