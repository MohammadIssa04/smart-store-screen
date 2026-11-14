package se.minbutik.app.ui

import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import se.minbutik.app.Anslutning
import se.minbutik.app.Foton
import se.minbutik.app.Lagring
import java.io.File

/**
 * Prisetiketter (70 x 40 mm): fota varan -> AI:n läser namnet (pappa kan rätta) -> skriv priset ->
 * förhandsvisningen visar exakt det som skrivs ut -> Skriv ut. Senaste etiketterna kan skrivas ut igen.
 */
@Composable
fun EtikettFlik(lagring: Lagring) {
    val context = LocalContext.current
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    val fokus = LocalFocusManager.current

    var namn by rememberSaveable { mutableStateOf("") }
    var pris by rememberSaveable { mutableStateOf("") }
    var aiNamn by rememberSaveable { mutableStateOf("") }
    var antal by rememberSaveable { mutableIntStateOf(1) }
    var laser by remember { mutableStateOf(false) }
    var skriver by remember { mutableStateOf(false) }
    var bild by remember { mutableStateOf<ImageBitmap?>(null) }
    var prisFel by remember { mutableStateOf(false) }
    var lage by remember { mutableStateOf("") }
    var skrivare by remember { mutableStateOf("") }      // "ansluten" | "inte_ansluten" | "test" | "" (vet inte än)
    var senaste by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }

    suspend fun hamtaSenaste() {
        val s = Anslutning.anrop("GET", "/api/etiketter/senaste", null, lagring.nyckel)
        val a = s.json?.optJSONArray("etiketter") ?: return
        senaste = (0 until a.length()).map { a.getJSONObject(it) }.map { it.optString("namn") to it.optString("pris") }
    }
    LaunchedEffect(Unit) { hamtaSenaste() }
    // Skrivarens läge: frågas när fliken öppnas och sedan var 30:e sekund medan den syns.
    LaunchedEffect(Unit) {
        while (true) {
            val j = Anslutning.anrop("GET", "/api/etiketter/lage", null, lagring.nyckel).json
            lage = j?.optString("lage") ?: lage
            skrivare = j?.optString("skrivare") ?: ""
            delay(30_000)
        }
    }

    // Förhandsvisningen uppdateras en stund efter att pappa slutat skriva
    LaunchedEffect(namn, pris) {
        if (namn.isBlank() || pris.isBlank()) { bild = null; prisFel = false; return@LaunchedEffect }
        delay(450)
        val data = Anslutning.postaForBild("/api/etiketter/forhandsvisa",
            JSONObject().put("namn", namn).put("pris", pris), lagring.nyckel)
        prisFel = data == null
        if (data != null) bild = BitmapFactory.decodeByteArray(data, 0, data.size)?.asImageBitmap()
    }

    fun lasNamn(foto: ByteArray) {
        laser = true
        skop.launch {
            val s = Anslutning.skicka("/api/etiketter/las", pris, listOf(foto), lagring.nyckel)
            laser = false
            if (s.kod == 200 && s.json != null) {
                namn = s.json.optString("namn"); aiNamn = namn
                if (pris.isBlank()) pris = s.json.optString("pris")
            } else snack.showSnackbar(s.json?.optString("fel")?.takeIf { it.isNotEmpty() } ?: t("Fick ingen kontakt med butiken"))
        }
    }
    val galleri = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { u ->
        u?.let { Foton.jpeg(context, it) }?.let { lasNamn(it) }
    }
    var kameraUri by remember { mutableStateOf<Uri?>(null) }
    val kamera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) kameraUri?.let { Foton.jpeg(context, it) }?.let { lasNamn(it) }
    }
    fun taFoto() {
        val fil = File(context.cacheDir, "foton").apply { mkdirs() }.let { File(it, "etikett${System.currentTimeMillis()}.jpg") }
        kameraUri = FileProvider.getUriForFile(context, "se.minbutik.app.filer", fil)
        try { kamera.launch(kameraUri!!) } catch (e: Exception) {
            skop.launch { snack.showSnackbar(t("Kameran gick inte att öppna. Välj en bild i stället.")) }
        }
    }

    fun skrivUt() {
        if (skriver) return
        fokus.clearFocus()
        skriver = true
        skop.launch {
            val s = Anslutning.anrop("POST", "/api/etiketter/skriv-ut",
                JSONObject().put("namn", namn).put("pris", pris).put("antal", antal).put("ai_namn", aiNamn), lagring.nyckel)
            skriver = false
            snack.showSnackbar(s.json?.optString(if (s.kod == 200) "meddelande" else "fel")?.takeIf { it.isNotEmpty() }
                ?: t("Fick ingen kontakt med butiken"))
            if (s.kod == 200) hamtaSenaste()
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {

        // Förhandsvisning: exakt som etiketten blir (70 x 40 mm)
        Surface(Modifier.fillMaxWidth().aspectRatio(583f / 344f), shape = RoundedCornerShape(20.dp),
            color = MaterialTheme.colorScheme.surfaceContainerHigh) {
            val b = bild
            if (b != null) Image(b, t("Förhandsvisning av etiketten"), Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
            else Column(Modifier.fillMaxSize().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                Icon(Icons.Rounded.Sell, null, Modifier.size(44.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.height(10.dp))
                Text(t("Fota varan eller skriv namnet,\nsen priset. Etiketten syns här."),
                    style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (lage == "test") TestlageRad() else if (skrivare.isNotEmpty()) Skrivarstatus(skrivare == "ansluten")

        // Fota varan: AI:n läser namnet
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { taFoto() }, Modifier.weight(1f).height(60.dp), enabled = !laser,
                shape = RoundedCornerShape(18.dp)) {
                if (laser) {
                    CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 3.dp, color = MaterialTheme.colorScheme.onPrimary)
                    Spacer(Modifier.width(10.dp)); Text(t("Läser namnet …"), fontSize = 17.sp)
                } else {
                    Icon(Icons.Rounded.PhotoCamera, null, Modifier.size(26.dp))
                    Spacer(Modifier.width(10.dp)); Text(t("Fota varan"), fontSize = 17.sp)
                }
            }
            FilledTonalIconButton(onClick = { galleri.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                Modifier.size(60.dp), enabled = !laser, shape = RoundedCornerShape(18.dp)) {
                Icon(Icons.Rounded.PhotoLibrary, t("Välj bild"), Modifier.size(26.dp))
            }
        }

        OutlinedTextField(value = namn, onValueChange = { namn = it.take(60) }, Modifier.fillMaxWidth(),
            label = { Text(t("Varans namn")) }, singleLine = true,
            textStyle = MaterialTheme.typography.titleLarge,
            supportingText = if (aiNamn.isNotEmpty() && namn == aiNamn) {
                { Text(t("Läst från fotot. Rätta om det är fel.")) }
            } else null,
            trailingIcon = if (namn.isNotEmpty()) {
                { IconButton(onClick = { namn = ""; aiNamn = "" }) { Icon(Icons.Rounded.Close, t("Töm namnet")) } }
            } else null,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Next),
            shape = RoundedCornerShape(16.dp))

        OutlinedTextField(value = pris, onValueChange = { pris = it.take(30) }, Modifier.fillMaxWidth(),
            label = { Text(t("Pris")) }, singleLine = true,
            textStyle = MaterialTheme.typography.titleLarge,
            isError = prisFel,
            supportingText = { Text(if (prisFel) t("Priset gick inte att läsa. Skriv t.ex. 19 eller 2 för 30.")
                else t("t.ex. 19   19,90/kg   2 för 30   15 + pant")) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            shape = RoundedCornerShape(16.dp))

        // Antal och Skriv ut
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t("Antal"), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            FilledTonalIconButton(onClick = { antal-- }, Modifier.size(52.dp), enabled = antal > 1) {
                Icon(Icons.Rounded.Remove, t("En färre"))
            }
            Text("$antal", Modifier.width(56.dp), style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
            FilledTonalIconButton(onClick = { antal++ }, Modifier.size(52.dp), enabled = antal < 20) {
                Icon(Icons.Rounded.Add, t("En till"))
            }
        }
        Button(onClick = { skrivUt() }, Modifier.fillMaxWidth().height(64.dp),
            enabled = bild != null && !prisFel && !skriver && namn.isNotBlank() && pris.isNotBlank(),
            shape = RoundedCornerShape(20.dp)) {
            if (skriver) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 3.dp, color = MaterialTheme.colorScheme.onPrimary)
            else {
                Icon(Icons.Rounded.Print, null, Modifier.size(28.dp)); Spacer(Modifier.width(12.dp))
                Text(if (antal > 1) tf("Skriv ut %s", antal) else t("Skriv ut"), fontSize = 19.sp, fontWeight = FontWeight.SemiBold)
            }
        }

        // Senaste: tryck för att skriva ut samma igen
        AnimatedVisibility(senaste.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Spacer(Modifier.height(6.dp))
                Text(t("Senaste etiketterna"), style = MaterialTheme.typography.titleMedium)
                senaste.forEach { (n, p) ->
                    Surface(onClick = { namn = n; pris = p; aiNamn = ""; antal = 1 }, Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
                        Row(Modifier.padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(n, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                            Text(ltr(p), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary)
                        }
                    }
                }
            }
        }
    }
}

/** Grön punkt: skrivaren svarar. Röd: den är avstängd, utom räckhåll eller ansluten till en telefon. */
@Composable
private fun Skrivarstatus(ansluten: Boolean) {
    val farg = if (ansluten) androidx.compose.ui.graphics.Color(0xFF2E7D32) else MaterialTheme.colorScheme.error
    Surface(shape = RoundedCornerShape(14.dp), color = farg.copy(alpha = 0.12f)) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(14.dp).background(farg, androidx.compose.foundation.shape.CircleShape))
            Spacer(Modifier.width(10.dp))
            Column {
                Text(if (ansluten) t("Skrivaren är ansluten") else t("Skrivaren är inte ansluten"),
                    style = MaterialTheme.typography.titleSmall, color = farg)
                if (!ansluten) Text(t("Slå på den med knappen och vänta en halv minut."),
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun TestlageRad() {
    Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.secondaryContainer) {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.Info, null, tint = MaterialTheme.colorScheme.onSecondaryContainer)
            Spacer(Modifier.width(10.dp))
            Text(t("Testläge: skrivaren är inte inkopplad än. Etiketten sparas som bild i butiken."),
                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
    }
}
