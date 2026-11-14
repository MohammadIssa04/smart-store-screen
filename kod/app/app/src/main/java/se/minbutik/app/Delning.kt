package se.minbutik.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue

/**
 * "Dela till Min Butik": pappa öppnar en bild (Facebook, galleriet, en annan app), trycker Dela och väljer
 * Min Butik. Bilderna (högst 3) och ev. text hamnar i Ny annons, så slipper han skärmdumpar.
 * Delningen ligger här tills Ny annons har tagit den (även om appen först måste logga in eller hitta butiken).
 */
object Delning {
    var nummer by mutableIntStateOf(0)        // ökar för varje ny delning: skärmarna reagerar på den
        private set
    private var bilder: List<ByteArray> = emptyList()
    private var text: String = ""

    fun ta(context: Context, intent: Intent?, klar: () -> Unit) {
        if (intent == null || intent.action !in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return
        val uris = buildList {
            if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
                val lista = if (Build.VERSION.SDK_INT >= 33)
                    intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
                else @Suppress("DEPRECATION") intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
                lista?.let { addAll(it) }
            } else {
                val en = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
                else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)
                en?.let { add(it) }
            }
        }
        val delText = (intent.getStringExtra(Intent.EXTRA_TEXT) ?: "").trim()
        intent.action = null                          // samma delning ska inte tas två gånger (t.ex. vid vridning)
        Thread {
            val jpeg = uris.take(3).mapNotNull { runCatching { Foton.jpeg(context, it) }.getOrNull() }
            if (jpeg.isEmpty() && delText.isEmpty()) return@Thread
            synchronized(this) { bilder = jpeg; text = delText }
            klar()
        }.start()
    }

    /** Anropas på huvudtråden när bilderna är klara. */
    fun meddela() { nummer++ }

    /** Ny annons hämtar delningen (en gång). */
    fun hamta(): Pair<List<ByteArray>, String>? = synchronized(this) {
        if (bilder.isEmpty() && text.isEmpty()) null
        else (bilder to text).also { bilder = emptyList(); text = "" }
    }
}
