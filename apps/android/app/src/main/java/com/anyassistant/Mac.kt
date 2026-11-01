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
import kotlinx.coroutines.suspendCancellableCoroutine
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
import kotlin.coroutines.resume

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
        fun answers(name: String) = runCatching { quick.newCall(request(base(name) + "/status").build()).execute().use { it.code } }.isSuccess
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

    // --- Bonjour ---

    /** The Mac's IP as Bonjour announces it (and its ports), within a few seconds; null if not found. */
    suspend fun discover(): String? = withContext(Dispatchers.Main) {
        val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        val found = withTimeoutOrNull(4000) { find(nsd) } ?: return@withContext null
        val resolved = withTimeoutOrNull(4000) { resolve(nsd, found) } ?: return@withContext null
        @Suppress("DEPRECATION")
        val ip = (if (Build.VERSION.SDK_INT >= 34) resolved.hostAddresses.firstOrNull() else resolved.host)
            ?.hostAddress?.takeIf { !it.contains(":") } ?: return@withContext null
        address = ip
        if (resolved.port > 0) port = resolved.port
        ip
    }

    private suspend fun find(nsd: NsdManager): NsdServiceInfo = suspendCancellableCoroutine { done ->
        val listener = object : NsdManager.DiscoveryListener {
            override fun onServiceFound(info: NsdServiceInfo) {
                if (done.isActive) done.resume(info)
                runCatching { nsd.stopServiceDiscovery(this) }
            }
            override fun onStartDiscoveryFailed(type: String, code: Int) {}
            override fun onStopDiscoveryFailed(type: String, code: Int) {}
            override fun onDiscoveryStarted(type: String) {}
            override fun onDiscoveryStopped(type: String) {}
            override fun onServiceLost(info: NsdServiceInfo) {}
        }
        nsd.discoverServices("_anyassistant._tcp", NsdManager.PROTOCOL_DNS_SD, listener)
        done.invokeOnCancellation { runCatching { nsd.stopServiceDiscovery(listener) } }
    }

    @Suppress("DEPRECATION")
    private suspend fun resolve(nsd: NsdManager, info: NsdServiceInfo): NsdServiceInfo = suspendCancellableCoroutine { done ->
        nsd.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, code: Int) {}
            override fun onServiceResolved(info: NsdServiceInfo) { if (done.isActive) done.resume(info) }
        })
    }

    // --- Pairing ---

    /** Pairs with the code (if the Mac asks for one) and learns its HTTPS authority. */
    suspend fun pair(code: String) = withContext(Dispatchers.IO) {
        val names = linkedSetOf<String>()
        if (host.isNotEmpty()) names += host
        discover()?.let { names += it }
        address?.let { names += it }
        names += "anyassistant.local"
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
