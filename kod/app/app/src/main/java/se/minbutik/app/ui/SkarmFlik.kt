package se.minbutik.app.ui

import android.Manifest
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as rutnatItems
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import se.minbutik.app.Anslutning
import se.minbutik.app.Delning
import se.minbutik.app.Foton
import se.minbutik.app.Lagring
import se.minbutik.app.VantaPaVideo
import java.io.File

private fun JSONArray.lista(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }

@Composable
fun SkarmFlik(lagring: Lagring) {
    var vy by rememberSaveable { mutableIntStateOf(0) }
    LaunchedEffect(Delning.nummer) { if (Delning.nummer > 0) vy = 0 }       // delad bild: till Ny annons
    Column(Modifier.fillMaxSize()) {
        PrimaryTabRow(selectedTabIndex = vy, containerColor = MaterialTheme.colorScheme.surface) {
            listOf(Icons.Rounded.AddCircleOutline to t("Ny annons"), Icons.Rounded.Tv to t("På skärmen")).forEachIndexed { i, (ikon, namn) ->
                Tab(selected = vy == i, onClick = { vy = i },
                    text = { Text(namn, style = MaterialTheme.typography.labelLarge, maxLines = 1) },
                    icon = { Icon(ikon, null) },
                    selectedContentColor = MaterialTheme.colorScheme.primary,
                    unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (vy == 0) NyAnnons(lagring) { vy = 1 } else PaSkarmen(lagring)
    }
}

// ---------- Ny annons (chatt) ----------

private data class Rad(val fran: String, val text: String, val bilder: List<ByteArray> = emptyList(), val antalFoton: Int = 0)

/**
 * Det pappa håller på med i "Ny annons" ligger kvar när han byter flik (Musik och tillbaka) eller
 * appen stängs: allt hålls här i stället för i skärmen, och ärendets id sparas i telefonen.
 * Efter omstart byggs chatten upp igen från butikens kopia (foton visas då som en liten ruta).
 */
private object Pagaende {
    var arendeId by mutableStateOf<String?>(null)
    var lage by mutableStateOf<JSONObject?>(null)
    val chatt = mutableStateListOf<Rad>()
    var visade by mutableIntStateOf(0)
    var text by mutableStateOf("")
    val valda = mutableStateListOf<ByteArray>()
    var skickar by mutableStateOf(false)
    var aterstalld = false

    fun nollstall() { arendeId = null; lage = null; chatt.clear(); visade = 0 }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NyAnnons(lagring: Lagring, visaSkarmen: () -> Unit) {
    val context = LocalContext.current
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    val p = Pagaende
    var arendeId by p::arendeId
    var lage by p::lage
    val chatt = p.chatt
    var visade by p::visade
    var text by p::text
    val valda = p.valda
    var skickar by p::skickar
    LaunchedEffect(arendeId) { lagring.pagaendeAnnons = arendeId }
    // Delat från en annan app (t.ex. bilden i ett Facebook-inlägg): bilderna och texten läggs i fältet,
    // pappa skriver pris om det behövs och trycker Skicka. Pågår en färdig annons börjar en ny.
    LaunchedEffect(Delning.nummer) {
        val (bilder, deltext) = Delning.hamta() ?: return@LaunchedEffect
        if (lage?.optString("status") in listOf("publicerad", "avbruten", "fel")) p.nollstall()
        valda.clear(); valda.addAll(bilder.take(3))
        if (deltext.isNotEmpty()) text = listOf(text, deltext).filter { it.isNotBlank() }.joinToString(" ")
    }
    // Appen har startats om: hämta tillbaka ärendet och chatten från butiken
    LaunchedEffect(Unit) {
        if (p.aterstalld) return@LaunchedEffect
        p.aterstalld = true
        val sparat = lagring.pagaendeAnnons ?: return@LaunchedEffect
        if (arendeId != null) return@LaunchedEffect
        val s = Anslutning.anrop("GET", "/api/annonser/arende/$sparat", null, lagring.nyckel)
        val j = s.json
        if (s.kod != 200 || j == null || j.optString("status") in listOf("publicerad", "avbruten")) {
            lagring.pagaendeAnnons = null; return@LaunchedEffect
        }
        val m = j.optJSONArray("meddelanden")?.lista() ?: emptyList()
        chatt.clear()
        m.forEach { chatt.add(Rad(it.optString("fran"), it.optString("text"), antalFoton = it.optInt("fotos"))) }
        visade = m.size; arendeId = sparat; lage = j
    }
    var gorOm by remember { mutableStateOf(false) }
    val lista = rememberLazyListState()

    val notisTillstand = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    val galleri = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(3)) { uris ->
        uris.take(3 - valda.size).forEach { u -> Foton.jpeg(context, u)?.let { valda.add(it) } }
    }
    var kameraUri by remember { mutableStateOf<Uri?>(null) }
    val kamera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) kameraUri?.let { u -> Foton.jpeg(context, u)?.let { if (valda.size < 3) valda.add(it) } }
    }
    fun taFoto() {
        val fil = File(context.cacheDir, "foton").apply { mkdirs() }.let { File(it, "foto${System.currentTimeMillis()}.jpg") }
        val uri = FileProvider.getUriForFile(context, "se.minbutik.app.filer", fil)
        kameraUri = uri
        try { kamera.launch(uri) } catch (e: Exception) {      // ingen kameraapp: krascha inte
            skop.launch { snack.showSnackbar(t("Kameran gick inte att öppna. Välj en bild i stället.")) }
        }
    }

    fun ta(svar: JSONObject?) {
        svar ?: return
        lage = svar
        val m = svar.optJSONArray("meddelanden")?.lista() ?: emptyList()
        m.drop(visade).filter { it.optString("fran") != "du" }.forEach { chatt.add(Rad("butiken", it.optString("text"))) }
        visade = m.size
        if (svar.optString("status") == "arbetar") {
            VantaPaVideo.starta(context, svar.optString("id"), t("Annonsen"))
        }
    }

    fun atgard(vag: String, kropp: JSONObject? = null) = skop.launch {
        val id = arendeId ?: return@launch
        val s = Anslutning.anrop("POST", "/api/annonser/arende/$id/$vag", kropp, lagring.nyckel)
        when {
            s.kod == 200 -> ta(s.json)
            s.kod == 404 -> { snack.showSnackbar(t("Annonsen finns inte längre i butiken. Börja om.")); p.nollstall() }
            else -> snack.showSnackbar(s.json?.optString("fel")?.takeIf { it.isNotEmpty() } ?: t("Det gick inte"))
        }
    }

    fun skicka() {
        if (skickar || (text.isBlank() && valda.isEmpty())) return
        if (Build.VERSION.SDK_INT >= 33) notisTillstand.launch(Manifest.permission.POST_NOTIFICATIONS)
        val st = lage?.optString("status")
        // Videon är klar och pappa skriver bara text ("priset är 12"): det är en rättelse = Gör om.
        if (st == "klar" && valda.isEmpty() && text.isNotBlank()) {
            val feedback = text.trim()
            text = ""
            chatt.add(Rad("du", tf("Gör om: %s", feedback)))
            atgard("gor-om", JSONObject().put("feedback", feedback))
            return
        }
        val nyttArende = arendeId == null || st in listOf("publicerad", "avbruten", "fel", "klar")
        if (nyttArende && arendeId != null) { chatt.clear(); visade = 0 }      // ny annons: ny chatt
        val t = text.trim()
        val b = valda.toList()
        chatt.add(Rad("du", t, b))
        text = ""; valda.clear(); skickar = true
        skop.launch {
            if (nyttArende) { visade = 0 }
            val s = Anslutning.skicka(if (nyttArende) "/api/annonser/ny?valja=1" else "/api/annonser/arende/$arendeId/svar",
                t, b, lagring.nyckel)
            skickar = false
            if (s.kod == 200 && s.json != null) {
                arendeId = s.json.optString("id"); ta(s.json)
            } else snack.showSnackbar(s.json?.optString("fel")?.takeIf { it.isNotEmpty() } ?: t("Fick ingen kontakt med butiken"))
        }
    }

    // Följ läget medan videon görs
    val status = lage?.optString("status")
    LaunchedEffect(arendeId, status) {
        val id = arendeId ?: return@LaunchedEffect
        if (lage == null) ta(Anslutning.anrop("GET", "/api/annonser/arende/$id", null, lagring.nyckel).json)
        while (lage?.optString("status") == "arbetar") {
            delay(3000)
            val s = Anslutning.anrop("GET", "/api/annonser/arende/$id", null, lagring.nyckel)
            if (s.kod == 200) ta(s.json)
            else if (s.kod == 404) {
                // Butikens server startades om medan den jobbade: annonsen finns inte kvar. Annars fastnar
                // appen på "jobbar" och Skicka går inte att trycka på.
                chatt.add(Rad("butiken", t("Butiken startades om och annonsen avbröts. Skicka den igen.")))
                p.nollstall()
                lagring.pagaendeAnnons = null
                break
            }
        }
    }
    LaunchedEffect(chatt.size, status) { if (chatt.isNotEmpty()) lista.animateScrollToItem(chatt.size + 1) }

    // imePadding: när tangentbordet öppnas flyttas skrivfältet upp ovanför det (annars täcktes texten).
    Column(Modifier.fillMaxSize().imePadding()) {
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = lista,
            contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (chatt.isEmpty()) item { Valkommen() }
            items(chatt) { Bubbla(it) }
            item {
                val l = lage
                when (l?.optString("status")) {
                    "arbetar" -> Arbetar(l.optString("lage").ifEmpty { t("Gör videon …") })
                    "klar" -> Forhandsvisning(l, lagring, onPublicera = { atgard("publicera") },
                        onGorOm = { gorOm = true }, onAvbryt = { atgard("avbryt") })
                    "fragar" -> if (l.optString("behover") == "valj_bild") {
                        BildVal(l, lagring, onValj = { nr -> chatt.add(Rad("du", tf("Bild %s", nr + 1))); atgard("valj-bild", JSONObject().put("nr", nr)) },
                            onFler = { atgard("fler-bilder") })
                    } else if (l.optBoolean("kan_leta_bild")) {
                        OutlinedButton(onClick = { atgard("leta-bild") }, shape = RoundedCornerShape(16.dp)) {
                            Icon(Icons.Rounded.TravelExplore, null); Spacer(Modifier.width(8.dp)); Text(t("Leta bild på nätet i stället"))
                        }
                    }
                    "publicerad" -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(onClick = visaSkarmen, shape = RoundedCornerShape(16.dp)) { Text(t("Se skärmen")) }
                        OutlinedButton(onClick = { p.nollstall() },
                            shape = RoundedCornerShape(16.dp)) { Text(t("Ny annons")) }
                    }
                }
            }
        }
        // Valda foton
        if (valda.isNotEmpty()) LazyRow(Modifier.padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(valda.toList()) { data ->
                Box {
                    val bild = remember(data) { BitmapFactory.decodeByteArray(data, 0, data.size)?.asImageBitmap() }
                    bild?.let { Image(it, null, Modifier.size(72.dp).clip(RoundedCornerShape(12.dp)), contentScale = ContentScale.Crop) }
                    FilledIconButton(onClick = { valda.remove(data) }, Modifier.size(28.dp).align(Alignment.TopEnd)) {
                        Icon(Icons.Rounded.Close, t("Ta bort bilden"), Modifier.size(16.dp))
                    }
                }
            }
        }
        // Skriv och skicka
        Surface(color = MaterialTheme.colorScheme.surfaceContainer, tonalElevation = 2.dp) {
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { taFoto() }, Modifier.size(52.dp), enabled = valda.size < 3) {
                    Icon(Icons.Rounded.PhotoCamera, t("Ta foto"), Modifier.size(28.dp))
                }
                IconButton(onClick = { galleri.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                    Modifier.size(52.dp), enabled = valda.size < 3) {
                    Icon(Icons.Rounded.PhotoLibrary, t("Välj bild"), Modifier.size(28.dp))
                }
                OutlinedTextField(value = text, onValueChange = { text = it }, Modifier.weight(1f),
                    placeholder = { Text(if (lage?.optString("status") == "fragar") t("Svara här") else t("t.ex. redbull 15"), maxLines = 1) },
                    shape = RoundedCornerShape(24.dp), maxLines = 3)
                Spacer(Modifier.width(6.dp))
                FilledIconButton(onClick = { skicka() }, Modifier.size(52.dp),
                    enabled = !skickar && (text.isNotBlank() || valda.isNotEmpty()) && lage?.optString("status") != "arbetar") {
                    if (skickar) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    else Icon(Icons.AutoMirrored.Rounded.Send, t("Skicka"))
                }
            }
        }
    }

    if (gorOm) GorOmArk(onAvbryt = { gorOm = false }) { feedback ->
        gorOm = false
        chatt.add(Rad("du", tf("Gör om: %s", feedback)))
        atgard("gor-om", JSONObject().put("feedback", feedback))
    }
}

/** Bilderna från nätet att välja mellan (2 per rad). Tryck på den bästa; "Visa fler" söker nya. */
@Composable
private fun BildVal(l: JSONObject, lagring: Lagring, onValj: (Int) -> Unit, onFler: () -> Unit) {
    val antal = l.optInt("bilder")
    val id = l.optString("id")
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        (0 until antal).chunked(2).forEach { rad ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                rad.forEach { nr ->
                    Surface(onClick = { onValj(nr) }, Modifier.weight(1f).aspectRatio(1f), shape = RoundedCornerShape(20.dp),
                        border = androidx.compose.foundation.BorderStroke(2.dp, MaterialTheme.colorScheme.outlineVariant)) {
                        Box {
                            NatBild("/api/annonser/arende/$id/kandidat/$nr", lagring.nyckel, Modifier.fillMaxSize())
                            Surface(Modifier.padding(8.dp).align(Alignment.TopStart), shape = RoundedCornerShape(50),
                                color = MaterialTheme.colorScheme.primary) {
                                Text("${nr + 1}", Modifier.padding(horizontal = 12.dp, vertical = 4.dp),
                                    style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimary)
                            }
                        }
                    }
                }
                if (rad.size == 1) Spacer(Modifier.weight(1f))
            }
        }
        if (l.optBoolean("kan_fler")) OutlinedButton(onClick = onFler, Modifier.fillMaxWidth().height(56.dp),
            shape = RoundedCornerShape(16.dp)) {
            Icon(Icons.Rounded.Refresh, null); Spacer(Modifier.width(8.dp)); Text(t("Visa fler bilder"))
        }
        Text(t("Eller ta ett eget foto med kameran nedanför."), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Valkommen() = Column(Modifier.fillMaxWidth().padding(vertical = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
    Surface(shape = RoundedCornerShape(28.dp), color = MaterialTheme.colorScheme.primaryContainer) {
        Icon(Icons.Rounded.AddAPhoto, null, Modifier.padding(20.dp).size(48.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
    }
    Spacer(Modifier.height(16.dp))
    Text(t("Ny annons till skärmen"), style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(8.dp))
    Text(t("Ta ett foto på varan och skriv namn och pris, till exempel \"redbull 15 + pant\" eller \"bananer 10/kg 3 dagar\"."),
        style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(12.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Rounded.Share, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(6.dp))
        Text(t("Från Facebook: öppna bilden i inlägget, tryck Dela och välj Min Butik."), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Spacer(Modifier.height(16.dp))
    FotoguideKnapp()
}

@Composable
private fun Bubbla(r: Rad) {
    val du = r.fran == "du"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (du) Arrangement.End else Arrangement.Start) {
        Surface(shape = RoundedCornerShape(20.dp, 20.dp, if (du) 6.dp else 20.dp, if (du) 20.dp else 6.dp),
            color = if (du) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceContainerHigh,
            modifier = Modifier.widthIn(max = 320.dp)) {
            Column(Modifier.padding(12.dp)) {
                if (r.bilder.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    r.bilder.forEach { data ->
                        val bild = remember(data) { BitmapFactory.decodeByteArray(data, 0, data.size)?.asImageBitmap() }
                        bild?.let { Image(it, null, Modifier.size(88.dp).clip(RoundedCornerShape(12.dp)), contentScale = ContentScale.Crop) }
                    }
                }
                if (r.bilder.isEmpty() && r.antalFoton > 0) Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.Image, null, Modifier.size(20.dp),
                        tint = if (du) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                    Spacer(Modifier.width(6.dp))
                    Text(if (r.antalFoton == 1) t("1 foto") else tf("%s foton", r.antalFoton), style = MaterialTheme.typography.labelLarge,
                        color = if (du) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                }
                if (r.text.isNotBlank()) {
                    if (r.bilder.isNotEmpty() || r.antalFoton > 0) Spacer(Modifier.height(6.dp))
                    Text(r.text, style = MaterialTheme.typography.bodyLarge,
                        color = if (du) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                }
            }
        }
    }
}

@Composable
private fun Arbetar(text: String) = Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.secondaryContainer) {
    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
        Spacer(Modifier.width(14.dp))
        Column {
            // Punkterna rör sig hela tiden, så att man ser att butiken jobbar (texten byts när läget ändras).
            var punkter by remember { mutableIntStateOf(0) }
            LaunchedEffect(Unit) { while (true) { delay(450); punkter = (punkter + 1) % 4 } }
            val bas = text.trimEnd(' ', '…', '.')
            Text(bas + " " + ".".repeat(punkter).padEnd(3, ' '), style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer)
            Text(t("Du får en avisering när den är klar."), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
    }
}

@Composable
private fun Forhandsvisning(l: JSONObject, lagring: Lagring, onPublicera: () -> Unit, onGorOm: () -> Unit, onAvbryt: () -> Unit) =
    // Videon bredvid knapparna (inte ovanför): allt får plats på skärmen utan att man behöver skrolla.
    ElevatedCard(shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLowest)) {
        Column(Modifier.padding(14.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Skyltvideo("/api/annonser/arende/${l.optString("id")}/video", lagring.nyckel,
                    Modifier.width(150.dp).aspectRatio(9f / 16f), reserv = "/api/annonser/arende/${l.optString("id")}/bild")
                Column(Modifier.weight(1f).height(150.dp * 16 / 9), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(l.optString("sammanfattning").lines().first(), style = MaterialTheme.typography.titleMedium,
                        maxLines = 3, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    l.optString("sammanfattning").lines().getOrNull(1)?.let {
                        Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Spacer(Modifier.weight(1f))
                    Button(onClick = onPublicera, Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(16.dp),
                        contentPadding = PaddingValues(horizontal = 10.dp)) {
                        Icon(Icons.Rounded.CheckCircle, null); Spacer(Modifier.width(6.dp)); Text(t("Publicera"), maxLines = 1)
                    }
                    OutlinedButton(onClick = onGorOm, Modifier.fillMaxWidth().height(52.dp), shape = RoundedCornerShape(16.dp),
                        contentPadding = PaddingValues(horizontal = 10.dp)) {
                        Icon(Icons.Rounded.Refresh, null); Spacer(Modifier.width(6.dp)); Text(t("Gör om"), maxLines = 1)
                    }
                    TextButton(onClick = onAvbryt, Modifier.fillMaxWidth().height(44.dp)) { Text(t("Avbryt")) }
                }
            }
            l.optJSONArray("notiser")?.let { n ->
                (0 until n.length()).forEach { i ->
                    Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.Top) {
                        Icon(Icons.Rounded.Lightbulb, null, Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(6.dp))
                        Text(n.getString(i), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }

@OptIn(ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun GorOmArk(onAvbryt: () -> Unit, onGorOm: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    Blad(onDismissRequest = onAvbryt) {
        Column(Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
            Text(t("Vad ska ändras?"), style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(12.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(t("Större pris"), t("Större vara"), t("Mindre vara"), t("Annan bild"), t("Fula kanter")).forEach { f ->
                    AssistChip(onClick = { onGorOm(f) }, label = { Text(f, style = MaterialTheme.typography.labelLarge) },
                        modifier = Modifier.height(48.dp))
                }
            }
            Spacer(Modifier.height(16.dp))
            OutlinedTextField(value = text, onValueChange = { text = it }, Modifier.fillMaxWidth(),
                placeholder = { Text(t("Eller skriv själv, t.ex. \"priset är 12 kr\"")) }, shape = RoundedCornerShape(18.dp))
            Spacer(Modifier.height(12.dp))
            Button(onClick = { onGorOm(text.trim().ifEmpty { t("Gör om") }) }, Modifier.fillMaxWidth().height(56.dp),
                shape = RoundedCornerShape(18.dp)) { Text(t("Gör om videon")) }
        }
    }
}

// ---------- På skärmen ----------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PaSkarmen(lagring: Lagring) {
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    var annonser by remember { mutableStateOf<List<JSONObject>?>(null) }
    var vader by remember { mutableStateOf<JSONObject?>(null) }
    var ingenKontakt by remember { mutableStateOf(false) }
    var taBort by remember { mutableStateOf<JSONObject?>(null) }
    var vaderVal by remember { mutableStateOf<JSONObject?>(null) }
    var val_ by remember { mutableStateOf<Pair<String, JSONObject>?>(null) }     // ("extra"|"forlang", annons)
    suspend fun hamta() {
        val j = Anslutning.anrop("GET", "/api/annonser", null, lagring.nyckel).json
        val lista = j?.optJSONArray("annonser")?.lista()
        ingenKontakt = lista == null
        if (lista != null) { annonser = lista; vader = j.optJSONObject("vader") }
        else if (annonser == null) annonser = emptyList()
    }
    fun atgard(vag: String, kropp: JSONObject? = null) = skop.launch {
        val s = Anslutning.anrop("POST", vag, kropp, lagring.nyckel)
        snack.showSnackbar(s.json?.optString("meddelande")?.takeIf { it.isNotEmpty() } ?: s.json?.optString("fel") ?: t("Det gick inte"))
        hamta()
    }
    LaunchedEffect(Unit) { while (true) { hamta(); delay(60_000) } }      // uppdateras varje minut

    val a = annonser
    when {
        a == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        a.isEmpty() -> Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center) {
            Icon(if (ingenKontakt) Icons.Rounded.WifiOff else Icons.Rounded.Tv, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.height(16.dp))
            if (ingenKontakt) {
                Text(t("Fick ingen kontakt med butiken"), style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
                Spacer(Modifier.height(12.dp))
                Button(onClick = { skop.launch { hamta() } }, shape = RoundedCornerShape(16.dp)) { Text(t("Försök igen")) }
            } else {
                Text(t("Inga annonser visas just nu"), style = MaterialTheme.typography.titleLarge)
                Text(t("Gör en under \"Ny annons\"."), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        else -> {
            var vy by remember { mutableStateOf(lagring.skarmVy) }
            var oppen by remember { mutableStateOf<JSONObject?>(null) }
            Column(Modifier.fillMaxSize()) {
                Vaderkort(vader)
                Totalt(a)
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                    listOf("rutnat" to t("Rutnät"), "bladdra" to t("Bläddra")).forEachIndexed { i, (id, namn) ->
                        SegmentedButton(selected = vy == id, onClick = { vy = id; lagring.skarmVy = id },
                            shape = SegmentedButtonDefaults.itemShape(i, 2),
                            icon = { Icon(if (id == "rutnat") Icons.Rounded.GridView else Icons.Rounded.ViewCarousel, null) }) {
                            Text(namn, style = MaterialTheme.typography.labelLarge)
                        }
                    }
                }
                if (vy == "rutnat") {
                    LazyVerticalGrid(GridCells.Adaptive(150.dp), Modifier.weight(1f),
                        contentPadding = PaddingValues(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        rutnatItems(a, key = { it.optString("id") }) { ann -> Ruta(ann, lagring) { oppen = ann } }
                    }
                } else {
                    val sida = rememberPagerState { annonser?.size ?: 0 }    // läser listan på nytt (inte en gammal kopia)
                    Text(tf("%s av %s  ·  svep för nästa", sida.currentPage + 1, a.size), Modifier.align(Alignment.CenterHorizontally),
                        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    HorizontalPager(sida, Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 24.dp), pageSpacing = 12.dp) { i ->
                        if (i >= a.size) return@HorizontalPager          // annonsen togs nyss bort
                        AnnonsSida(a[i], lagring, i == sida.currentPage,
                            onExtra = { val_ = "extra" to a[i] }, onForlang = { val_ = "forlang" to a[i] }, onTaBort = { taBort = a[i] },
                            onVader = { vaderVal = a[i] })
                    }
                }
            }
            oppen?.let { ann ->
                Blad(onDismissRequest = { oppen = null }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
                    AnnonsSida(ann, lagring, true, Modifier.padding(horizontal = 24.dp),
                        onExtra = { oppen = null; val_ = "extra" to ann }, onForlang = { oppen = null; val_ = "forlang" to ann },
                        onTaBort = { oppen = null; taBort = ann }, onVader = { oppen = null; vaderVal = ann })
                }
            }
        }
    }

    vaderVal?.let { ann ->
        VaderValBlad(ann.optString("vadertyp_kod", "neutral"), stang = { vaderVal = null }) { typ ->
            vaderVal = null
            atgard("/api/annonser/${ann.optString("id")}/vader", JSONObject().put("typ", typ))
        }
    }
    taBort?.let { ann ->
        AlertDialog(onDismissRequest = { taBort = null }, icon = { Icon(Icons.Rounded.DeleteOutline, null) },
            title = { Text(t("Ta bort från skärmen?")) },
            text = { Text(tf("\"%s\" slutar visas direkt. Videon sparas i arkivet.", ann.optString("rubrik"))) },
            confirmButton = { Button(onClick = { taBort = null; atgard("/api/annonser/${ann.optString("id")}/ta-bort") }) { Text(t("Ja, ta bort")) } },
            dismissButton = { TextButton(onClick = { taBort = null }) { Text(t("Nej")) } })
    }
    val_?.takeIf { it.first == "extra" }?.let { (_, ann) ->
        HurOftaBlad(ann, lagring, stang = { val_ = null }) { vag, kropp -> val_ = null; atgard(vag, kropp) }
    }
    val_?.takeIf { it.first == "forlang" }?.let { (typ, ann) ->
        Blad(onDismissRequest = { val_ = null }) {
            Column(Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
                Text(if (typ == "extra") t("Visa oftare – hur länge?") else t("Förläng – hur länge till?"), style = MaterialTheme.typography.titleLarge)
                Text(ann.optString("rubrik"), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(16.dp))
                listOf(1 to (if (typ == "extra") t("I dag") else t("En dag till")), 3 to t("3 dagar"), 7 to t("En vecka")).forEach { (dagar, namn) ->
                    Button(onClick = {
                        val_ = null
                        atgard("/api/annonser/${ann.optString("id")}/" + if (typ == "extra") "extra" else "forlang",
                            JSONObject().put("dagar", dagar))
                    }, Modifier.fillMaxWidth().height(56.dp).padding(vertical = 4.dp), shape = RoundedCornerShape(16.dp)) {
                        Text(namn)
                    }
                }
                if (typ != "extra") OutlinedButton(onClick = {
                    val_ = null
                    atgard("/api/annonser/${ann.optString("id")}/tills-vidare")
                }, Modifier.fillMaxWidth().height(56.dp).padding(vertical = 4.dp), shape = RoundedCornerShape(16.dp)) {
                    Icon(Icons.Rounded.AllInclusive, null); Spacer(Modifier.width(8.dp)); Text(t("Tills vidare"))
                }
            }
        }
    }
}

/** Hur ofta annonsen visas: alltid (normalt / oftare / mycket ofta, med ungefär hur många gånger i timmen)
 *  eller extra en tid (i dag, 3 dagar, en vecka). Vädret kan höja men aldrig sänka pappas val. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HurOftaBlad(ann: JSONObject, lagring: Lagring, stang: () -> Unit, valt: (String, JSONObject?) -> Unit) {
    val id = ann.optString("id")
    var info by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(id) { info = Anslutning.anrop("GET", "/api/annonser/$id/visningar", null, lagring.nyckel).json }
    val vald = info?.optInt("vald") ?: ann.optInt("vikt_val", 1)
    Blad(onDismissRequest = stang) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
            Text(t("Hur ofta ska den synas?"), style = MaterialTheme.typography.titleLarge)
            Text(ann.optString("rubrik"), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(14.dp))
            listOf(1 to t("Normalt"), 2 to t("Oftare"), 3 to t("Mycket ofta")).forEach { (vikt, namn) ->
                val per = info?.optJSONObject("per_timme")?.optInt(vikt.toString())
                Surface(onClick = { valt("/api/annonser/$id/visningar", JSONObject().put("vikt", vikt)) },
                    Modifier.fillMaxWidth().padding(vertical = 4.dp), shape = RoundedCornerShape(16.dp),
                    color = if (vikt == vald) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer) {
                    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(namn, style = MaterialTheme.typography.titleMedium)
                            Text(if (per != null && per > 0) tf("ca %s gånger i timmen", per) else " ",
                                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (vikt == vald) Icon(Icons.Rounded.CheckCircle, t("Valt"), tint = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            Spacer(Modifier.height(18.dp))
            Text(t("Extra en tid (sedan som vanligt)"), style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(1 to t("I dag"), 3 to t("3 dagar"), 7 to t("En vecka")).forEach { (dagar, namn) ->
                    OutlinedButton(onClick = { valt("/api/annonser/$id/extra", JSONObject().put("dagar", dagar)) },
                        Modifier.weight(1f).height(52.dp), shape = RoundedCornerShape(14.dp), contentPadding = PaddingValues(4.dp)) {
                        Text(namn, maxLines = 1)
                    }
                }
            }
            // Hur länge annonsen syns varje gång (videons längd). Standard 9 s; videon görs om (ca en minut).
            Spacer(Modifier.height(18.dp))
            Text(t("Hur länge varje gång"), style = MaterialTheme.typography.titleMedium)
            val nuLangd = ann.optInt("langd", 9)
            if (ann.optBoolean("langd_andras")) Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp); Spacer(Modifier.width(8.dp))
                Text(t("Videon görs om just nu …"), style = MaterialTheme.typography.bodyMedium)
            }
            if (!ann.optBoolean("kan_andra_langd")) {
                Text(t("Den här videon kan inte göras om. Gör en ny annons i stället."), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                var egen by remember { mutableStateOf("") }
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(6, 9, 12, 15).forEach { sek ->
                        val vald = sek == nuLangd
                        FilterChip(selected = vald, onClick = { if (!vald) valt("/api/annonser/$id/langd", JSONObject().put("sekunder", sek)) },
                            label = { Text(ltr("$sek s"), Modifier.fillMaxWidth(), textAlign = TextAlign.Center, maxLines = 1) },
                            modifier = Modifier.weight(1f).height(48.dp))
                    }
                }
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(egen, { egen = it.filter(Char::isDigit).take(2) }, Modifier.weight(1f),
                        label = { Text(t("Egen tid (6–30 sekunder)")) }, singleLine = true,
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Number))
                    Spacer(Modifier.width(8.dp))
                    val ok = egen.toIntOrNull()?.let { it in 6..30 } == true
                    Button(onClick = { valt("/api/annonser/$id/langd", JSONObject().put("sekunder", egen.toInt())) },
                        enabled = ok, modifier = Modifier.height(56.dp), shape = RoundedCornerShape(14.dp)) { Text(t("Spara")) }
                }
                if (egen.isNotEmpty() && egen.toIntOrNull()?.let { it in 6..30 } != true)
                    Text(t("Välj mellan 6 och 30 sekunder."), color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodyMedium)
                Text(tf("Nu: %s sekunder", nuLangd), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** "Syns 9 s · 81 ggr/tim" – hur skyltens spellista visar annonsen just nu. */
private fun visningstext(ann: JSONObject, kort: Boolean = false): String {
    val v = ann.optJSONObject("visning") ?: return ""
    if (!v.has("sek")) return ""
    val min = (v.optInt("sek_per_timme") + 30) / 60
    return if (kort) tf("%s s · %s ggr/tim", v.optInt("sek"), v.optInt("per_timme"))
    else tf("Syns %s sekunder åt gången, ca %s gånger i timmen (%s min per timme).", v.optInt("sek"), v.optInt("per_timme"), min)
}

/** Pappa väljer själv vid vilket väder annonsen ska visas oftare (2 eller 3 gånger så ofta). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VaderValBlad(nu: String, stang: () -> Unit, valt: (String) -> Unit) = Blad(onDismissRequest = stang) {
    Column(Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
        Text(t("Visa oftare vid vilket väder?"), style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))
        listOf(
            Triple("kall", Icons.Rounded.WbSunny, t("Varmt väder (kalla varor, glass, dricka)")),
            Triple("varm", Icons.Rounded.AcUnit, t("Kallt väder (varma varor, soppa, te)")),
            Triple("mys", Icons.Rounded.Umbrella, t("Regn eller snö (mys, godis, bakning)")),
            Triple("grill", Icons.Rounded.OutdoorGrill, t("Grillväder på helgen")),
            Triple("neutral", Icons.Rounded.Block, t("Inte efter väder")),
        ).forEach { (kod, ikon, text) ->
            val vald = kod == nu
            Surface(onClick = { valt(kod) }, Modifier.fillMaxWidth().padding(vertical = 4.dp), shape = RoundedCornerShape(16.dp),
                color = if (vald) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer) {
                Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(ikon, null, Modifier.size(28.dp), tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(14.dp))
                    Text(text, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                    if (vald) Icon(Icons.Rounded.CheckCircle, t("Valt"), tint = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

/** Vädret i dag och vilka annonser det gör att skylten visar oftare. */
@Composable
private fun Vaderkort(v: JSONObject?) {
    v ?: return
    val typer = v.optJSONArray("typer")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
    val ikon = when {
        "grill" in typer -> Icons.Rounded.OutdoorGrill
        "kall" in typer -> Icons.Rounded.WbSunny
        "varm" in typer -> Icons.Rounded.AcUnit
        "mys" in typer -> Icons.Rounded.Umbrella
        else -> Icons.Rounded.Cloud
    }
    val regler = v.optJSONArray("regler")?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
    Surface(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp), shape = RoundedCornerShape(18.dp),
        color = MaterialTheme.colorScheme.secondaryContainer) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(ikon, null, Modifier.size(32.dp), tint = MaterialTheme.colorScheme.onSecondaryContainer)
            Spacer(Modifier.width(12.dp))
            Column {
                val temp = if (v.isNull("temp")) "" else "${v.optInt("temp")} °C"
                Text(listOf(t("Vädret i dag"), ltr(temp)).filter { it.isNotEmpty() }.joinToString(": "),
                    style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
                regler.forEach {
                    Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
                }
                if (!v.optBoolean("aktivt", true)) {
                    Text(t("Obs: skylten använder inte vädret än (väderversionen är inte installerad)."),
                        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

/** "×2 i dag (varm vara)" när vädret eller Visa extra gör att annonsen visas oftare. */
private fun viktText(ann: JSONObject): String {
    val vikt = ann.optInt("vikt", 1)
    if (vikt <= 1) return ""
    val orsak = if (ann.optBoolean("extra")) t("Visa extra") else ann.optString("vadertyp").let { if (it.isEmpty()) t("vädret") else t(it) }
    return tf("Visas %s gånger oftare i dag (%s)", vikt, orsak)
}

@Composable
private fun Totalt(a: List<JSONObject>) {
    val andel = a.sumOf { it.optJSONObject("visning")?.optInt("andel") ?: 0 }
    if (andel <= 0) return
    Text(tf("%s annonser · syns %s %% av tiden på skärmen", a.size, andel.coerceAtMost(100)),
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp),
        style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, textAlign = TextAlign.Center)
}

@Composable
private fun Ruta(ann: JSONObject, lagring: Lagring, onClick: () -> Unit) =
    ElevatedCard(onClick = onClick, shape = RoundedCornerShape(20.dp)) {
        Box {
            NatBild("/api/annonser/${ann.optString("id")}/bild", lagring.nyckel, Modifier.fillMaxWidth().aspectRatio(9f / 16f))
            val vikt = ann.optInt("vikt", 1)
            if (vikt > 1 || ann.optBoolean("extra")) Surface(Modifier.padding(8.dp).align(Alignment.TopEnd), shape = RoundedCornerShape(50),
                color = MaterialTheme.colorScheme.primary) {
                Row(Modifier.padding(horizontal = 8.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(if (ann.optBoolean("extra")) Icons.Rounded.Bolt else Icons.Rounded.Thermostat, viktText(ann),
                        Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onPrimary)
                    if (vikt > 1) Text(ltr("×$vikt"), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onPrimary)
                }
            }
        }
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(ann.optString("rubrik"), style = MaterialTheme.typography.titleMedium, maxLines = 1)
            Text(ltr(ann.optString("pris")), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary, maxLines = 1)
            Text(if (ann.optBoolean("tills_vidare")) t("Tills vidare") else tf("t.o.m. %s", ann.optString("slutar")), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            visningstext(ann, kort = true).takeIf { it.isNotEmpty() }?.let {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.Timer, null, Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(4.dp))
                    Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
        }
    }

@Composable
private fun AnnonsSida(ann: JSONObject, lagring: Lagring, spelas: Boolean, modifier: Modifier = Modifier,
                       onExtra: () -> Unit, onForlang: () -> Unit, onTaBort: () -> Unit, onVader: () -> Unit = {}) =
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        if (spelas) Skyltvideo("/api/annonser/${ann.optString("id")}/video", lagring.nyckel, Modifier.height(400.dp),
            reserv = "/api/annonser/${ann.optString("id")}/bild")
        else NatBild("/api/annonser/${ann.optString("id")}/bild", lagring.nyckel,
            Modifier.height(400.dp).aspectRatio(9f / 16f).clip(RoundedCornerShape(20.dp)))
        Spacer(Modifier.height(14.dp))
        Text(ltr(listOf(ann.optString("rubrik"), ann.optString("pris")).filter { it.isNotEmpty() }.joinToString(", ")),
            style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        Text(if (ann.optBoolean("tills_vidare")) t("Visas tills vidare") else tf("Visas t.o.m. %s", ann.optString("slutar")), style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        visningstext(ann).takeIf { it.isNotEmpty() }?.let {
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Timer, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(6.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
        }
        viktText(ann).takeIf { it.isNotEmpty() && !ann.optBoolean("extra") }?.let {
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Thermostat, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(6.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
        }
        if (ann.optBoolean("extra")) {
            Spacer(Modifier.height(6.dp))
            Surface(shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.primaryContainer) {
                Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.Bolt, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
                    Spacer(Modifier.width(4.dp))
                    Text(tf("Visas extra till %s", ann.optString("extra_till")), style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onPrimaryContainer)
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Atgardsknapp(Icons.Rounded.Speed, t("Hur ofta"), Modifier.weight(1f), onClick = onExtra)
            Atgardsknapp(Icons.Rounded.EventRepeat, t("Förläng"), Modifier.weight(1f), onClick = onForlang)
            Atgardsknapp(Icons.Rounded.WbSunny, t("Väder"), Modifier.weight(1f), onClick = onVader)
            Atgardsknapp(Icons.Rounded.DeleteOutline, t("Ta bort"), Modifier.weight(1f), fara = true, onClick = onTaBort)
        }
        Spacer(Modifier.height(16.dp))
    }

@Composable
private fun Atgardsknapp(ikon: androidx.compose.ui.graphics.vector.ImageVector, text: String, modifier: Modifier,
                         fara: Boolean = false, onClick: () -> Unit) =
    FilledTonalButton(onClick = onClick, modifier.height(72.dp), shape = RoundedCornerShape(18.dp),
        contentPadding = PaddingValues(4.dp),
        colors = if (fara) ButtonDefaults.filledTonalButtonColors(containerColor = MaterialTheme.colorScheme.errorContainer,
            contentColor = MaterialTheme.colorScheme.onErrorContainer) else ButtonDefaults.filledTonalButtonColors()) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(ikon, null, Modifier.size(26.dp))
            Text(text, style = MaterialTheme.typography.labelMedium, maxLines = 1)
        }
    }
