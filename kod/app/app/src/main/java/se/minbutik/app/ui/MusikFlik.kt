package se.minbutik.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.rounded.QueueMusic
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import se.minbutik.app.Anslutning
import se.minbutik.app.Lagring

private fun tid(sek: Int): String = "%d:%02d".format(sek / 60, sek % 60)
private fun JSONArray.objekt(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
private fun JSONObject.text(namn: String): String? = optString(namn, "").takeIf { it.isNotEmpty() && it != "null" }

/** Musiklistorna: alla tidsblock, och låtarna i det man trycker på. */
@Composable
fun MusikListor(lagring: Lagring) {
    var oppenLista by rememberSaveable { mutableStateOf<String?>(null) }
    androidx.activity.compose.BackHandler(enabled = oppenLista != null) { oppenLista = null }
    oppenLista?.let { Lista(lagring, it) { oppenLista = null } } ?: Listor(lagring) { oppenLista = it }
}

@Composable
fun MusikSok(lagring: Lagring) = Sok(lagring)

// ---------- Spelaren (startsidan) ----------

/** Det som spelas i butiken: stort omslag, titel, hjärta, paus/nästa och volym. Uppdateras varannan sekund. */
@Composable
fun Spelare(lagring: Lagring) {
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    var status by remember { mutableStateOf<JSONObject?>(null) }
    var fel by remember { mutableStateOf<String?>(null) }
    var visaStart by rememberSaveable { mutableStateOf(false) }

    suspend fun hamta() {
        val s = Anslutning.anrop("GET", "/api/musik/status", null, lagring.nyckel)
        if (s.kod == 200) { status = s.json; fel = null }
        else if (Anslutning.bas != null) fel = s.json?.text("fel") ?: t("Ingen kontakt med butiken")
    }
    fun styr(cmd: String, pa: Boolean = false) = skop.launch {
        val s = Anslutning.anrop("POST", "/api/musik/styr", JSONObject().put("cmd", cmd).put("pa", pa), lagring.nyckel)
        if (s.kod == 200) status = s.json
    }
    fun volym(procent: Int) = skop.launch {
        val s = Anslutning.anrop("POST", "/api/musik/volym", JSONObject().put("procent", procent), lagring.nyckel)
        if (s.kod == 200) status = s.json
    }
    fun startpunkt(kropp: JSONObject) = skop.launch {
        val s = Anslutning.anrop("POST", "/api/musik/startpunkt", kropp, lagring.nyckel)
        if (s.kod == 200) status = s.json
        (s.json?.text("meddelande") ?: s.json?.text("fel"))?.let { snack.showSnackbar(it) }
    }
    fun favorit(pa: Boolean) = skop.launch {
        val s = Anslutning.anrop("POST", "/api/musik/favorit", JSONObject().put("pa", pa), lagring.nyckel)
        if (s.kod == 200) status = status?.put("favorit", pa)
        (s.json?.text("meddelande") ?: s.json?.text("fel"))?.let { snack.showSnackbar(it) }
    }
    // Hämtar bara när butiken är hittad (annars skulle varje försök börja leta på nytt).
    LaunchedEffect(Anslutning.bas) { while (true) { if (Anslutning.bas != null) hamta(); delay(2000) } }

    val st = status
    val titel = st?.text("titel")?.let { renTitel(it, st.text("artist")) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        st?.text("block_namn")?.let { namn ->
            Text("$namn  ·  " + tf("kl %s", st.text("block_tid") ?: ""), style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(12.dp))
        }
        Box(Modifier.fillMaxWidth(0.82f).aspectRatio(1f), contentAlignment = Alignment.Center) {
            Omslag(if (titel != null) st?.text("id") else null, Modifier.fillMaxSize(), RoundedCornerShape(32.dp), 96.dp)
            if (st == null && fel == null) CircularProgressIndicator()
        }
        Spacer(Modifier.height(20.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(titel ?: when {
                    st == null -> fel ?: t("Ansluter …")
                    st.optBoolean("gamla_musiken_kor") -> t("Den gamla musiken spelar just nu")
                    !st.optBoolean("oppet") -> t("Musiken spelar kl 10–21")
                    else -> t("Startar musiken …")
                }, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, maxLines = 2,
                    overflow = TextOverflow.Ellipsis)
                st?.text("artist")?.let {
                    Text(it, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (titel != null && st?.optBoolean("kan_valja") == true) {
                val fav = st.optBoolean("favorit")
                IconToggleButton(checked = fav, onCheckedChange = { favorit(it) }, modifier = Modifier.size(64.dp)) {
                    Icon(if (fav) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder,
                        if (fav) t("Ta bort som favorit") else t("Spara som favorit"), Modifier.size(36.dp),
                        tint = rosaAccent())
                }
            }
        }
        if (st == null) return@Column
        val langd = st.optInt("langd")
        if (titel != null && langd > 0) {
            Spacer(Modifier.height(14.dp))
            LinearProgressIndicator(progress = { (st.optInt("position").toFloat() / langd).coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().height(8.dp), drawStopIndicator = {})
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth()) {
                Text(ltr(tid(st.optInt("position"))), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                Text(ltr(tid(langd)), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.height(8.dp))
        val pausad = st.optBoolean("pausad")
        val loop = st.optBoolean("loop")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.Top) {
            Styrknapp(if (loop) Icons.Rounded.RepeatOne else Icons.Rounded.Repeat,
                if (loop) t("Upprepar") else t("Upprepa"), 64.dp, vald = loop) { styr("loop", !loop) }
            val spelar = st.optBoolean("spelar")
            Styrknapp(if (spelar) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
                if (spelar) t("Paus") else t("Spela"), 96.dp, huvud = true) { styr(if (pausad) "spela" else "paus") }
            Styrknapp(Icons.Rounded.SkipNext, t("Nästa"), 64.dp) { styr("nasta") }
        }
        Spacer(Modifier.height(12.dp))
        val vol = st.optInt("volym", -1)
        Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
            Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                FilledTonalIconButton(onClick = { if (vol >= 0) volym(vol - 5) }, Modifier.size(60.dp)) {
                    Icon(Icons.Rounded.VolumeDown, t("Sänk volymen"), Modifier.size(30.dp))
                }
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(t("Volym"), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(if (vol >= 0) ltr("$vol %") else "–", style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold)
                }
                FilledTonalIconButton(onClick = { if (vol >= 0) volym(vol + 5) }, Modifier.size(60.dp)) {
                    Icon(Icons.Rounded.VolumeUp, t("Höj volymen"), Modifier.size(30.dp))
                }
            }
        }
        if (titel != null && st.optBoolean("kan_valja")) {
            TextButton(onClick = { visaStart = !visaStart }, Modifier.padding(top = 4.dp)) {
                Icon(Icons.Rounded.FastForward, null); Spacer(Modifier.width(8.dp))
                Text(if (st.optInt("start") > 0) tf("Börjar vid %s", ltr(tid(st.optInt("start"))))
                     else t("Lång inledning? Hoppa fram"), style = MaterialTheme.typography.titleSmall)
            }
            if (visaStart) Startpunkt(st, { startpunkt(it) })
        }
        if (st.optBoolean("fyller_pa")) {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text(t("Hämtar nya låtar till listorna …"), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Var låten börjar (lång inledning): -10 s / +10 s, från början, och AI:ns förslag om det finns.
 *  Sparas för just den här låten; filen ändras aldrig. Låten hoppar dit direkt så att man hör. */
@Composable
private fun Startpunkt(st: JSONObject, skicka: (JSONObject) -> Unit) {
    val start = st.optInt("start")
    val forslag = st.optInt("forslag", -1)
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(t("Låten börjar vid"), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(if (start == 0) t("början") else ltr(tid(start)), style = MaterialTheme.typography.headlineMedium)
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                FilledTonalButton(onClick = { skicka(JSONObject().put("andra", -10)) }, Modifier.weight(1f).height(60.dp),
                    enabled = start > 0, shape = RoundedCornerShape(18.dp)) {
                    Text(ltr("−10 s"), style = MaterialTheme.typography.titleMedium)
                }
                FilledTonalButton(onClick = { skicka(JSONObject().put("andra", 10)) }, Modifier.weight(1f).height(60.dp),
                    shape = RoundedCornerShape(18.dp)) {
                    Text(ltr("+10 s"), style = MaterialTheme.typography.titleMedium)
                }
            }
            if (start > 0) TextButton(onClick = { skicka(JSONObject().put("nollstall", true)) }) {
                Icon(Icons.Rounded.Replay, null); Spacer(Modifier.width(6.dp)); Text(t("Från början"))
            }
            if (forslag > 0 && forslag != start) OutlinedButton(onClick = { skicka(JSONObject().put("satt", forslag)) },
                Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp)) {
                Icon(Icons.Rounded.AutoAwesome, null, Modifier.size(20.dp)); Spacer(Modifier.width(8.dp))
                Text(tf("Sången börjar vid %s – använd det", tid(forslag)))
            }
        }
    }
}

@Composable
private fun Styrknapp(ikon: ImageVector, text: String, storlek: Dp, huvud: Boolean = false, vald: Boolean = false,
                      onClick: () -> Unit) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        // Alla knappar står i en lika hög ruta, så att texterna under hamnar på samma linje.
        Box(Modifier.size(96.dp), contentAlignment = Alignment.Center) {
            if (huvud) {
                FilledIconButton(onClick = onClick, Modifier.size(storlek)) { Icon(ikon, text, Modifier.size(storlek * 0.5f)) }
            } else {
                FilledTonalIconToggleButton(checked = vald, onCheckedChange = { onClick() }, Modifier.size(storlek),
                    colors = IconButtonDefaults.filledTonalIconToggleButtonColors(
                        checkedContainerColor = MaterialTheme.colorScheme.primary,
                        checkedContentColor = MaterialTheme.colorScheme.onPrimary)) {
                    Icon(ikon, text, Modifier.size(storlek * 0.5f))
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(text, style = MaterialTheme.typography.labelMedium,
            color = if (vald) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Laddar(fel: String?) = Column(Modifier.fillMaxSize().padding(32.dp),
    horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
    if (fel == null) CircularProgressIndicator()
    else {
        Icon(Icons.Rounded.CloudOff, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.height(16.dp))
        Text(fel, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
    }
}

// ---------- Sök ----------

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Sok(lagring: Lagring) {
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    val fokus = LocalFocusManager.current
    var fraga by rememberSaveable { mutableStateOf("") }
    var traffar by remember { mutableStateOf<List<JSONObject>?>(null) }
    var soker by remember { mutableStateOf(false) }
    var valj by remember { mutableStateOf<JSONObject?>(null) }
    var block by remember { mutableStateOf<List<JSONObject>>(emptyList()) }

    fun sok() {
        if (fraga.isBlank() || soker) return
        fokus.clearFocus()
        soker = true
        skop.launch {
            val s = Anslutning.anrop("GET", "/api/musik/sok?q=" + java.net.URLEncoder.encode(fraga.trim(), "UTF-8"),
                null, lagring.nyckel)
            traffar = s.json?.optJSONArray("traffar")?.objekt() ?: emptyList()
            soker = false
        }
    }
    LaunchedEffect(Unit) {
        block = Anslutning.anrop("GET", "/api/musik/block", null, lagring.nyckel).json?.optJSONArray("block")?.objekt()
            ?: emptyList()
    }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(value = fraga, onValueChange = { fraga = it }, singleLine = true,
            placeholder = { Text(t("Låt eller artist")) }, textStyle = MaterialTheme.typography.bodyLarge,
            leadingIcon = { Icon(Icons.Rounded.Search, null) },
            trailingIcon = {
                if (fraga.isNotEmpty()) IconButton(onClick = { fraga = ""; traffar = null }) {
                    Icon(Icons.Rounded.Close, t("Rensa"))
                }
            },
            shape = RoundedCornerShape(28.dp),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { sok() }),
            modifier = Modifier.fillMaxWidth().padding(16.dp))
        if (soker) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        val t = traffar
        when {
            t == null && !soker -> Tomt(Icons.Rounded.Search, t("Sök efter en låt eller artist"),
                t("Spela den direkt, eller lägg till den i en av listorna."))
            t != null && t.isEmpty() && !soker -> Tomt(Icons.Rounded.SearchOff, t("Hittade inget"), t("Pröva ett annat namn."))
            else -> LazyColumn(contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(t ?: emptyList()) { traff ->
                    ElevatedCard(shape = RoundedCornerShape(20.dp),
                        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLowest)) {
                        Column(Modifier.padding(16.dp)) {
                          Row(verticalAlignment = Alignment.CenterVertically) {
                            Omslag(traff.optString("id"), Modifier.size(72.dp), RoundedCornerShape(14.dp), 28.dp)
                            Spacer(Modifier.width(14.dp))
                            Column(Modifier.weight(1f)) {
                            Text(renTitel(traff.optString("titel"), traff.optString("kanal")), style = MaterialTheme.typography.titleMedium, maxLines = 2,
                                overflow = TextOverflow.Ellipsis)
                            Text("${traff.optString("kanal")}  ·  ${tid(traff.optInt("langd"))}",
                                style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                          }
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Button(onClick = {
                                    skop.launch {
                                        val s = Anslutning.anrop("POST", "/api/musik/spela", traff, lagring.nyckel)
                                        snack.showSnackbar(if (s.kod == 200) tf("Spelar nu: %s", renTitel(traff.optString("titel"), traff.optString("kanal")))
                                            else s.json?.text("fel") ?: t("Det gick inte att spela låten"))
                                    }
                                }, Modifier.weight(1f).height(52.dp), shape = RoundedCornerShape(16.dp)) {
                                    Icon(Icons.Rounded.PlayArrow, null); Spacer(Modifier.width(6.dp)); Text(t("Spela nu"))
                                }
                                OutlinedButton(onClick = { valj = traff }, Modifier.weight(1f).height(52.dp),
                                    shape = RoundedCornerShape(16.dp)) {
                                    Icon(Icons.Rounded.Add, null); Spacer(Modifier.width(6.dp)); Text(t("Lägg till"))
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    valj?.let { traff ->
        Blad(onDismissRequest = { valj = null }) {
            Column(Modifier.padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
                Text(t("Lägg till i vilken lista?"), style = MaterialTheme.typography.titleLarge)
                Text(traff.optString("titel"), style = MaterialTheme.typography.bodyMedium, maxLines = 1,
                    overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(16.dp))
                block.forEach { b ->
                    ListItem(
                        headlineContent = { Text(b.optString("namn"), style = MaterialTheme.typography.titleMedium) },
                        supportingContent = { Text(tf("kl %s", b.optString("tid"))) },
                        leadingContent = { Icon(Icons.Rounded.Schedule, null, tint = MaterialTheme.colorScheme.primary) },
                        modifier = Modifier.clickable {
                            valj = null
                            skop.launch {
                                val s = Anslutning.anrop("POST", "/api/musik/lagg-till",
                                    JSONObject(traff.toString()).put("block", b.optString("id")), lagring.nyckel)
                                snack.showSnackbar(s.json?.text("meddelande") ?: s.json?.text("fel") ?: t("Det gick inte"))
                            }
                        })
                }
            }
        }
    }
}

@Composable
private fun Tomt(ikon: ImageVector, rubrik: String, text: String) = Column(
    Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center) {
    Icon(ikon, null, Modifier.size(56.dp), tint = MaterialTheme.colorScheme.primary.copy(alpha = 0.7f))
    Spacer(Modifier.height(16.dp))
    Text(rubrik, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
    Spacer(Modifier.height(6.dp))
    Text(text, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

// ---------- Listor ----------

@Composable
private fun Listor(lagring: Lagring, oppna: (String) -> Unit) {
    var block by remember { mutableStateOf<List<JSONObject>?>(null) }
    var nu by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        val j = Anslutning.anrop("GET", "/api/musik/block", null, lagring.nyckel).json
        block = j?.optJSONArray("block")?.objekt() ?: emptyList()
        nu = j?.text("nu")
    }
    val b = block ?: run { Laddar(null); return }
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(b) { blk ->
            val spelas = blk.optString("id") == nu
            ElevatedCard(onClick = { oppna(blk.optString("id")) }, shape = RoundedCornerShape(24.dp),
                colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLowest)) {
                ListItem(
                    colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surfaceContainerLowest),
                    overlineContent = {
                        Text(if (spelas) tf("%s  ·  spelas nu", tf("kl %s", blk.optString("tid"))) else tf("kl %s", blk.optString("tid")),
                            style = MaterialTheme.typography.labelMedium,
                            color = if (spelas) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    },
                    headlineContent = { Text(blk.optString("namn"), style = MaterialTheme.typography.titleLarge) },
                    supportingContent = { Text(tf("%s låtar", blk.optInt("antal")), style = MaterialTheme.typography.bodyLarge) },
                    leadingContent = {
                        Surface(shape = RoundedCornerShape(16.dp),
                            color = if (spelas) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.primaryContainer) {
                            Icon(if (spelas) Icons.Rounded.GraphicEq else Icons.AutoMirrored.Rounded.QueueMusic, null,
                                Modifier.padding(12.dp).size(28.dp),
                                tint = if (spelas) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onPrimaryContainer)
                        }
                    },
                    trailingContent = { Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null) },
                    modifier = Modifier.padding(vertical = 6.dp))
            }
        }
    }
}

@Composable
private fun Lista(lagring: Lagring, blockId: String, tillbaka: () -> Unit) {
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var taBort by remember { mutableStateOf<JSONObject?>(null) }
    suspend fun hamta() { data = Anslutning.anrop("GET", "/api/musik/block/$blockId", null, lagring.nyckel).json }
    LaunchedEffect(blockId) { hamta() }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(start = 4.dp, end = 16.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = tillbaka, Modifier.size(56.dp)) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, t("Tillbaka")) }
            Column {
                Text(data?.optString("namn") ?: "", style = MaterialTheme.typography.titleLarge)
                data?.let { Text(tf("kl %s", it.optString("tid")), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
        val latar = data?.optJSONArray("latar")?.objekt()
        when {
            latar == null -> Laddar(null)
            latar.isEmpty() -> Tomt(Icons.AutoMirrored.Rounded.QueueMusic, t("Inga låtar än"),
                t("Nya låtar hämtas automatiskt. Du kan också söka och lägga till."))
            else -> LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
                items(latar, key = { it.optString("id") }) { l ->
                    ListItem(
                        leadingContent = { Omslag(l.optString("id"), Modifier.size(60.dp), RoundedCornerShape(12.dp), 24.dp) },
                        headlineContent = { Text(renTitel(l.optString("titel"), l.optString("artist")), maxLines = 2, overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.titleMedium) },
                        supportingContent = { Text("${l.optString("artist")}  ·  ${tid(l.optInt("langd"))}" +
                            if (l.optInt("start") > 0) "  ·  " + tf("börjar vid %s", tid(l.optInt("start"))) else "") },
                        trailingContent = { Row {
                            val fav = l.optBoolean("favorit")
                            IconButton(onClick = {
                                skop.launch {
                                    val s = Anslutning.anrop("POST", "/api/musik/favorit",
                                        JSONObject().put("pa", !fav).put("id", l.optString("id")), lagring.nyckel)
                                    if (s.kod == 200) hamta()
                                }
                            }, Modifier.size(56.dp)) {
                                Icon(if (fav) Icons.Rounded.Favorite else Icons.Rounded.FavoriteBorder,
                                    if (fav) t("Ta bort som favorit") else t("Spara som favorit"),
                                    tint = rosaAccent())
                            }
                            IconButton(onClick = { taBort = l }, Modifier.size(56.dp)) {
                                Icon(Icons.Rounded.DeleteOutline, t("Ta bort"), tint = MaterialTheme.colorScheme.error)
                            }
                        } })
                    HorizontalDivider(Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.outlineVariant)
                }
            }
        }
    }
    taBort?.let { l ->
        AlertDialog(onDismissRequest = { taBort = null },
            icon = { Icon(Icons.Rounded.DeleteOutline, null) },
            title = { Text(t("Ta bort låten?")) },
            text = { Text("\"${renTitel(l.optString("titel"), l.optString("artist"))}\"" + t(" tas bort ur listan och spelas inte mer.")) },
            confirmButton = {
                Button(onClick = {
                    taBort = null
                    skop.launch {
                        val s = Anslutning.anrop("POST", "/api/musik/ta-bort",
                            JSONObject().put("id", l.optString("id")).put("block", blockId), lagring.nyckel)
                        snack.showSnackbar(s.json?.text("meddelande") ?: t("Det gick inte att ta bort låten"))
                        hamta()
                    }
                }) { Text(t("Ja, ta bort")) }
            },
            dismissButton = { TextButton(onClick = { taBort = null }) { Text(t("Nej")) } })
    }
}
