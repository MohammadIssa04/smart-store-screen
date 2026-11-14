package se.minbutik.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File

/**
 * Nya versioner av appen kommer från butikens dator i stället för som APK-fil i chatten.
 * Mohammad lägger appen på Pi:n (data/app/), appen ser det vid start och visar "Ny version finns".
 * Uppdatera: filen hämtas och Android frågar "Vill du uppdatera?" (första gången också om appen får
 * installera appar; det godkänns en gång).
 */
object Uppdatering {
    /** Den nya versionen ({"kod", "namn", "nytt", "storlek_mb"}) om den är nyare än den här, annars null. */
    var ny by mutableStateOf<JSONObject?>(null)
        private set
    /** null = ingen hämtning; 0..1 = hämtar. */
    var framsteg by mutableStateOf<Float?>(null)
        private set
    var fel by mutableStateOf<String?>(null)
        private set

    suspend fun kolla(nyckel: String?) {
        val s = Anslutning.anrop("GET", "/api/app/version", null, nyckel)
        val kod = s.json?.optInt("kod", 0) ?: 0
        ny = if (s.kod == 200 && kod > BuildConfig.VERSION_CODE) s.json else null
    }

    /** Hämtar och startar installationen. */
    suspend fun uppdatera(context: Context, nyckel: String?) {
        if (framsteg != null) return
        fel = null
        // Android 8+: appen behöver tillstånd att installera appar. Saknas det: öppna inställningen (en gång).
        if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            fel = "Slå på \"Tillåt från den här källan\", gå tillbaka och tryck Uppdatera igen."
            return
        }
        val fil = File(context.cacheDir, "apk/minbutik.apk")
        framsteg = 0f
        val ok = Anslutning.laddaNer("/api/app/apk", nyckel, fil) { framsteg = it }
        framsteg = null
        if (!ok) { fel = "Det gick inte att hämta den nya versionen. Försök igen."; return }
        val uri = FileProvider.getUriForFile(context, "se.minbutik.app.filer", fil)
        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
