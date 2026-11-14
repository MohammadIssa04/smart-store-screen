package se.minbutik.app.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material3.Icon
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.draw.alpha
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/**
 * Skivomslag till låtarna: låtarna kommer från YouTube, så bilden är videons miniatyr (i.ytimg.com).
 * Telefonen hämtar den själv över internet; Pi:n behöver inte göra något. Svarta kanter (16:9-video
 * i en 4:3-bild) klipps bort, och bilderna sparas i minnet medan appen är öppen.
 * Ingen bild (inget id, ingen internet): en grå ruta med en not.
 */
private val minne = LruCache<String, ImageBitmap>(80)
private val YT_ID = Regex("^[A-Za-z0-9_-]{11}$")

fun omslagAdress(id: String?): String? =
    id?.takeIf { YT_ID.matches(it) }?.let { "https://i.ytimg.com/vi/$it/hqdefault.jpg" }

private suspend fun hamtaOmslag(adress: String): ImageBitmap? = withContext(Dispatchers.IO) {
    runCatching {
        val c = URL(adress).openConnection() as HttpURLConnection
        c.connectTimeout = 8000
        c.readTimeout = 10000
        val data = c.inputStream.use { it.readBytes() }
        c.disconnect()
        var b = BitmapFactory.decodeByteArray(data, 0, data.size) ?: return@runCatching null
        b = utanSvartaKanter(b)
        b.asImageBitmap()
    }.getOrNull()
}

/** hqdefault är 4:3; en 16:9-video har svarta band upptill och nedtill (12,5 % vardera). */
private fun utanSvartaKanter(b: Bitmap): Bitmap {
    val band = (b.height * 0.125f).toInt()
    if (band < 4 || b.width <= b.height) return b
    fun mork(y: Int): Boolean {
        var summa = 0
        val steg = b.width / 8
        for (i in 1..7) {
            val p = b.getPixel(i * steg, y)
            summa += ((p shr 16) and 0xFF) + ((p shr 8) and 0xFF) + (p and 0xFF)
        }
        return summa / (7 * 3) < 24
    }
    return if (mork(band / 2) && mork(b.height - band / 2)) Bitmap.createBitmap(b, 0, band, b.width, b.height - 2 * band)
    else b
}

@Composable
fun Omslag(id: String?, modifier: Modifier, form: Shape, notStorlek: Dp = 40.dp) {
    val adress = omslagAdress(id)
    var bild by remember(adress) { mutableStateOf(adress?.let { minne.get(it) }) }
    LaunchedEffect(adress) {
        if (adress != null && bild == null) hamtaOmslag(adress)?.let { minne.put(adress, it); bild = it }
    }
    Box(modifier.clip(form).background(androidx.compose.material3.MaterialTheme.colorScheme.surfaceContainerHigh), contentAlignment = Alignment.Center) {
        val b = bild
        if (b != null) Image(b, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
        else Icon(Icons.Rounded.MusicNote, null, Modifier.size(notStorlek).alpha(0.6f), tint = androidx.compose.material3.MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
