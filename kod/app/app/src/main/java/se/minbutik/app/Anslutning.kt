package se.minbutik.app

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import org.json.JSONObject
import se.minbutik.app.ui.Sprak
import java.net.HttpURLConnection
import java.net.URL
import kotlin.coroutines.resume

/** Svar från Pi:n. kod = HTTP-status (0 = nådde inte fram). */
data class Svar(val kod: Int, val json: JSONObject?)

/**
 * Hittar Pi:n och pratar med API:t. Ordning:
 *  1. butikens wifi: mDNS-tjänsten "Min Butik" (_minbutik._tcp)
 *  2. senast fungerande lokala adress
 *  3. minbutik-tv.local
 *  4. Tailscale (100.64.0.1) – för den som har Tailscale, var som helst
 */
object Anslutning {
    const val PORT = 8484
    const val TAILSCALE = "http://100.64.0.1:$PORT"   // byt till din Pi:s Tailscale-adress
    private const val MDNS_TYP = "_minbutik._tcp."

    /** Adressen som svarar (null = ingen kontakt än). Compose-läge: appen visar "Ingen kontakt" när den saknas. */
    var bas: String? by androidx.compose.runtime.mutableStateOf(null)
        private set

    /** Letar efter butiken just nu (visas som "Ansluter …" högst upp, appen går att använda under tiden). */
    var letar by androidx.compose.runtime.mutableStateOf(false)
        private set

    /** Sätts när butiken svarar 401 på en inloggad telefon (spärrad): appen går till inloggningen. */
    var utloggad by androidx.compose.runtime.mutableStateOf(false)

    private var appContext: Context? = null
    private var appLagring: Lagring? = null
    private var senasteForsok = 0L
    private val ateranslutLas = kotlinx.coroutines.sync.Mutex()

    fun init(context: Context, lagring: Lagring) { appContext = context.applicationContext; appLagring = lagring }

    /** Ingen kontakt: adressen kan ha ändrats (wifi <-> mobildata, ny IP). Leta igen, högst var 20:e sekund. */
    private suspend fun ateranslut(): Boolean {
        val c = appContext ?: return false
        val l = appLagring ?: return false
        return ateranslutLas.withLock {
            if (System.currentTimeMillis() - senasteForsok < 20_000) return@withLock bas != null
            senasteForsok = System.currentTimeMillis()
            letar = true
            try { hitta(c, l) != null } finally { letar = false }
        }
    }

    /** Första anslutningen vid start (i bakgrunden). Under tiden väntar andra anrop på den i stället för att leta själva. */
    suspend fun anslutVidStart(context: Context, lagring: Lagring): String? = ateranslutLas.withLock {
        senasteForsok = System.currentTimeMillis()
        letar = true
        try { hitta(context, lagring) } finally { letar = false }
    }

    private fun kolla401(s: Svar, nyckel: String?): Svar {
        if (s.kod == 401 && nyckel != null) utloggad = true
        return s
    }

    /** Hittar en adress som svarar. Med nyckel krävs att den också godkänns. */
    suspend fun hitta(context: Context, lagring: Lagring): String? {
        // Två försök: första anslutningen via Tailscale kan ta några sekunder att komma igång.
        repeat(2) { forsok ->
            val k = provaAlla(context, lagring, timeoutMs = if (forsok == 0) 6000 else 10000)
            if (k != null) {
                bas = k
                if (k != TAILSCALE) lagring.senasteLokala = k
                return k
            }
        }
        bas = null
        return null
    }

    /** Provar alla vägar samtidigt och väljer den bästa som svarar (butikens wifi före Tailscale). */
    private suspend fun provaAlla(context: Context, lagring: Lagring, timeoutMs: Int): String? = coroutineScope {
        // Bara testbygget i Android-emulatorn: datorns testserver (via adb reverse) används om den svarar.
        if (BuildConfig.DEBUG && android.os.Build.PRODUCT.startsWith("sdk_gphone")) {
            val t = "http://127.0.0.1:$PORT"      // adb reverse tcp:8484 tcp:8484
            val s = anropa(t, "GET", "/api/hej", null, lagring.nyckel, timeoutMs = 3000)
            android.util.Log.d("Anslutning", "testserver: ${s.kod}")
            if (s.kod == 200 || s.kod == 401) return@coroutineScope t
        }
        val fasta = buildList {
            lagring.senasteLokala?.let { add(it) }
            add(TAILSCALE)
        }
        // Lokalt: mDNS-sökningen (högst 3 s) och minbutik-tv.local körs parallellt med de fasta adresserna.
        val mdnsSvar = async { mdns(context) }
        val localSvar = async { withTimeoutOrNull(3000L) { runCatching {
            withContext(Dispatchers.IO) { java.net.InetAddress.getByName("minbutik-tv.local").hostAddress }
        }.getOrNull() } }
        fun svarar(k: String) = async {
            val s = anropa(k, "GET", "/api/hej", null, lagring.nyckel, timeoutMs = timeoutMs)
            // 200 = framme och inloggad; 401 = framme men inte (längre) inloggad
            if (s.kod == 200 || s.kod == 401) k else null
        }
        val fastaProv = fasta.map { svarar(it) }
        val lokala = listOfNotNull(mdnsSvar.await(), localSvar.await()?.let { "http://$it:$PORT" })
            .filter { it !in fasta }.distinct().map { svarar(it) }
        // Prioritet: lokala (mDNS, .local, senaste lokala) före Tailscale.
        val alla = lokala.map { it.await() } + fastaProv.map { it.await() }
        alla.filterNotNull().minByOrNull { if (it == TAILSCALE) 1 else 0 }
    }

    suspend fun anrop(metod: String, vag: String, kropp: JSONObject?, nyckel: String?): Svar {
        val b = bas
        val s = if (b != null) anropa(b, metod, vag, kropp, nyckel) else Svar(0, null)
        if (s.kod == 0 && ateranslut()) {
            return kolla401(anropa(bas ?: return s, metod, vag, kropp, nyckel), nyckel)
        }
        return kolla401(s, nyckel)
    }

    /** Text + foton (JPEG) som formulär, t.ex. en ny annons. Långsammare nät: längre tidsgräns. */
    suspend fun skicka(vag: String, text: String, foton: List<ByteArray>, nyckel: String?): Svar {
        val s = skickaEn(vag, text, foton, nyckel)
        if (s.kod == 0 && ateranslut()) return kolla401(skickaEn(vag, text, foton, nyckel), nyckel)
        return kolla401(s, nyckel)
    }

    private suspend fun skickaEn(vag: String, text: String, foton: List<ByteArray>, nyckel: String?): Svar =
        withContext(Dispatchers.IO) {
            val b = bas ?: return@withContext Svar(0, null)
            try {
                val grans = "minbutik" + System.nanoTime()
                val c = URL(b + vag).openConnection() as HttpURLConnection
                c.requestMethod = "POST"
                c.connectTimeout = 15000
                c.readTimeout = 180000
                c.doOutput = true
                if (nyckel != null) c.setRequestProperty("Authorization", "Bearer $nyckel")
            c.setRequestProperty("X-Sprak", Sprak.kod)
                c.setRequestProperty("Content-Type", "multipart/form-data; boundary=$grans")
                c.outputStream.use { ut ->
                    fun rad(s: String) = ut.write((s + "\r\n").toByteArray())
                    rad("--$grans"); rad("Content-Disposition: form-data; name=\"text\""); rad(""); rad(text)
                    foton.forEachIndexed { i, data ->
                        rad("--$grans")
                        rad("Content-Disposition: form-data; name=\"fotos\"; filename=\"foto$i.jpg\"")
                        rad("Content-Type: image/jpeg"); rad("")
                        ut.write(data); rad("")
                    }
                    rad("--$grans--")
                }
                val kod = c.responseCode
                val svar = (if (kod < 400) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() }
                c.disconnect()
                Svar(kod, svar?.let { runCatching { JSONObject(it) }.getOrNull() })
            } catch (e: Exception) {
                Svar(0, null)
            }
        }

    /** Rå data (t.ex. en bild) med nyckeln. */
    suspend fun hamtaData(vag: String, nyckel: String?): ByteArray? = withContext(Dispatchers.IO) {
        val b = bas ?: return@withContext null
        try {
            val c = URL(b + vag).openConnection() as HttpURLConnection
            c.connectTimeout = 10000
            c.readTimeout = 30000
            if (nyckel != null) c.setRequestProperty("Authorization", "Bearer $nyckel")
            c.setRequestProperty("X-Sprak", Sprak.kod)
            if (c.responseCode != 200) null else c.inputStream.use { it.readBytes() }
        } catch (e: Exception) { null }
    }

    /** POST med JSON som svarar med en bild (t.ex. etikettens förhandsvisning). Fel ger null. */
    suspend fun postaForBild(vag: String, kropp: JSONObject, nyckel: String?): ByteArray? = withContext(Dispatchers.IO) {
        val b = bas ?: return@withContext null
        try {
            val c = URL(b + vag).openConnection() as HttpURLConnection
            c.requestMethod = "POST"
            c.connectTimeout = 10000
            c.readTimeout = 20000
            c.doOutput = true
            if (nyckel != null) c.setRequestProperty("Authorization", "Bearer $nyckel")
            c.setRequestProperty("X-Sprak", Sprak.kod)
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(kropp.toString().toByteArray()) }
            if (c.responseCode != 200) null else c.inputStream.use { it.readBytes() }
        } catch (e: Exception) { null }
    }

    fun adress(vag: String): String? = bas?.let { it + vag }

    /** Laddar ner en stor fil (t.ex. en ny version av appen) till mal. framsteg(0..1) under tiden. */
    suspend fun laddaNer(vag: String, nyckel: String?, mal: java.io.File, framsteg: (Float) -> Unit): Boolean =
        withContext(Dispatchers.IO) {
            val b = bas ?: return@withContext false
            try {
                val c = URL(b + vag).openConnection() as HttpURLConnection
                c.connectTimeout = 15000
                c.readTimeout = 60000
                if (nyckel != null) c.setRequestProperty("Authorization", "Bearer $nyckel")
                if (c.responseCode != 200) return@withContext false
                val total = c.contentLengthLong.takeIf { it > 0 } ?: -1L
                mal.parentFile?.mkdirs()
                val tmp = java.io.File(mal.path + ".del")
                var klart = 0L
                c.inputStream.use { inn ->
                    tmp.outputStream().use { ut ->
                        val buf = ByteArray(64 * 1024)
                        while (true) {
                            val n = inn.read(buf)
                            if (n < 0) break
                            ut.write(buf, 0, n)
                            klart += n
                            if (total > 0) framsteg(klart.toFloat() / total)
                        }
                    }
                }
                c.disconnect()
                if (total > 0 && klart != total) return@withContext false
                tmp.renameTo(mal)
            } catch (e: Exception) { false }
        }

    private suspend fun anropa(
        bas: String, metod: String, vag: String, kropp: JSONObject?, nyckel: String?,
        timeoutMs: Int = 15000,
    ): Svar = withContext(Dispatchers.IO) {
        try {
            val c = URL(bas + vag).openConnection() as HttpURLConnection
            c.requestMethod = metod
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            if (nyckel != null) c.setRequestProperty("Authorization", "Bearer $nyckel")
            c.setRequestProperty("X-Sprak", Sprak.kod)
            if (kropp != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(kropp.toString().toByteArray()) }
            }
            val kod = c.responseCode
            val text = (if (kod < 400) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() }
            c.disconnect()
            Svar(kod, text?.let { runCatching { JSONObject(it) }.getOrNull() })
        } catch (e: Exception) {
            Svar(0, null)
        }
    }

    /** Letar efter "Min Butik" på wifi:t i högst 3 sekunder. */
    private suspend fun mdns(context: Context): String? {
        val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        var aktiv: NsdManager.DiscoveryListener? = null
        val svar = withTimeoutOrNull(3000) {
            suspendCancellableCoroutine { fortsatt ->
                val lyssnare = object : NsdManager.DiscoveryListener {
                    override fun onServiceFound(info: NsdServiceInfo) {
                        if (!info.serviceName.startsWith("Min Butik")) return
                        @Suppress("DEPRECATION")
                        nsd.resolveService(info, object : NsdManager.ResolveListener {
                            override fun onResolveFailed(i: NsdServiceInfo, fel: Int) {}
                            override fun onServiceResolved(i: NsdServiceInfo) {
                                val ip = if (Build.VERSION.SDK_INT >= 34)
                                    i.hostAddresses.firstOrNull { it.address.size == 4 }?.hostAddress
                                else @Suppress("DEPRECATION") i.host?.hostAddress
                                if (ip != null && fortsatt.isActive) fortsatt.resume("http://$ip:${i.port}")
                            }
                        })
                    }
                    override fun onServiceLost(info: NsdServiceInfo) {}
                    override fun onDiscoveryStarted(typ: String) {}
                    override fun onDiscoveryStopped(typ: String) {}
                    override fun onStartDiscoveryFailed(typ: String, fel: Int) {
                        if (fortsatt.isActive) fortsatt.resume(null)
                    }
                    override fun onStopDiscoveryFailed(typ: String, fel: Int) {}
                }
                aktiv = lyssnare
                nsd.discoverServices(MDNS_TYP, NsdManager.PROTOCOL_DNS_SD, lyssnare)
            }
        }
        // Sökningen stoppas alltid, oavsett om Pi:n hittades eller tiden gick ut.
        aktiv?.let { runCatching { nsd.stopServiceDiscovery(it) } }
        return svar
    }
}
