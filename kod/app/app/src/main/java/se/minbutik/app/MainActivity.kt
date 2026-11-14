package se.minbutik.app

import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.rounded.*
import androidx.compose.material.icons.automirrored.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import se.minbutik.app.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()        // statusraden följer temat (mörka ikoner på krämvitt, ljusa i mörkt läge)
        super.onCreate(savedInstanceState)
        val lagring = Lagring(this)
        lagring.sprak?.let { Sprak.kod = it }
        Anslutning.init(this, lagring)
        Delning.ta(this, intent) { runOnUiThread { Delning.meddela() } }
        setContent {
            RosaTema {
                // Arabiska läses från höger till vänster: hela appen speglas.
                CompositionLocalProvider(LocalLayoutDirection provides
                        if (Sprak.arabiska) LayoutDirection.Rtl else LayoutDirection.Ltr) { App(lagring) }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Delning.ta(this, intent) { runOnUiThread { Delning.meddela() } }
    }

    // Aviseringen "Videon är klar" behövs bara när appen inte syns.
    override fun onResume() { super.onResume(); VantaPaVideo.appenSyns = true }
    override fun onPause() { VantaPaVideo.appenSyns = false; super.onPause() }
}

/**
 * Appen öppnas direkt (musiken först). Butiken letas upp i bakgrunden; under tiden står "Ansluter …"
 * högst upp, och hittas den inte visas en rad med "Försök igen" i stället för en hel skärm.
 * Startanimationen och språkvalet visas bara första gången.
 */
@Composable
fun App(lagring: Lagring) {
    val context = LocalContext.current
    val skop = rememberCoroutineScope()
    var sprakValt by remember { mutableStateOf(lagring.sprak != null) }
    var inloggad by remember { mutableStateOf(lagring.nyckel != null) }
    var utloggad by remember { mutableStateOf(false) }
    var animationKlar by remember { mutableStateOf(sprakValt) }
    LaunchedEffect(Unit) { if (!animationKlar) { delay(1900); animationKlar = true } }

    fun anslut() = skop.launch {
        if (Anslutning.anslutVidStart(context, lagring) == null) return@launch
        val n = lagring.nyckel ?: return@launch
        // Spärrad telefon (401): anrop() sätter Anslutning.utloggad, som tar appen till inloggningen.
        Anslutning.anrop("GET", "/api/hej", null, n)
    }
    LaunchedEffect(Unit) { anslut() }
    // Telefonen spärrades (eller nyckeln är ogiltig): logga in på nytt med en ny kod.
    LaunchedEffect(Anslutning.utloggad) {
        if (Anslutning.utloggad) {
            Anslutning.utloggad = false
            lagring.nyckel = null
            utloggad = true
            inloggad = false
        }
    }

    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        if (!animationKlar) { Startbild(soker = false); return@Surface }
        if (!sprakValt) {
            ValjSprak { kod -> Sprak.kod = kod; lagring.sprak = kod; sprakValt = true }
            return@Surface
        }
        if (!inloggad) LoggaIn(lagring, utloggad) { utloggad = false; inloggad = true }
        else Hem(lagring = lagring, forsokIgen = { anslut() }, loggaUt = { lagring.nyckel = null; inloggad = false })
    }
}

@Composable
private fun LoggaIn(lagring: Lagring, utloggad: Boolean, klar: () -> Unit) {
    val skop = rememberCoroutineScope()
    var kod by remember { mutableStateOf("") }
    var fel by remember { mutableStateOf<String?>(null) }
    var vantar by remember { mutableStateOf(false) }

    fun loggaIn() {
        if (kod.length != 6 || vantar) return
        vantar = true
        skop.launch {
            val namn = "${Build.MANUFACTURER} ${Build.MODEL}".trim()
            val s = Anslutning.anrop("POST", "/api/logga-in", JSONObject().put("kod", kod).put("namn", namn), null)
            vantar = false
            when {
                s.kod == 200 && s.json?.has("nyckel") == true -> { lagring.nyckel = s.json.getString("nyckel"); klar() }
                s.kod == 0 -> fel = t("Får ingen kontakt med butiken. Försök igen.")
                else -> fel = s.json?.optString("fel") ?: t("Det gick inte. Försök igen.")
            }
        }
    }

    Mitten {
        Ordmarke(44.sp)
        Spacer(Modifier.height(40.dp))
        Text(t("Logga in"), style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(8.dp))
        Text(if (utloggad) t("Telefonen behöver loggas in igen. Skriv den nya koden med 6 siffror.")
             else t("Skriv koden med 6 siffror som du har fått."),
            style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = kod,
            onValueChange = { kod = it.filter(Char::isDigit).take(6); fel = null },
            singleLine = true,
            isError = fel != null,
            placeholder = { Text("000 000", Modifier.fillMaxWidth(), textAlign = TextAlign.Center, fontSize = 34.sp,
                letterSpacing = 6.sp, color = MaterialTheme.colorScheme.outlineVariant) },
            textStyle = LocalTextStyle.current.copy(fontSize = 34.sp, textAlign = TextAlign.Center,
                letterSpacing = 6.sp, fontWeight = FontWeight.Bold),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { loggaIn() }),
            shape = RoundedCornerShape(18.dp),
            modifier = Modifier.fillMaxWidth(0.85f),
        )
        Box(Modifier.heightIn(min = 56.dp).padding(top = 10.dp), contentAlignment = Alignment.TopCenter) {
            fel?.let {
                Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyLarge)
            }
        }
        StorKnapp(if (vantar) t("Loggar in …") else t("Logga in"), Icons.Rounded.Login, aktiv = kod.length == 6 && !vantar) {
            loggaIn()
        }
    }
}

private data class Flik(val namn: String, val ikon: ImageVector, val vald: ImageVector)

/**
 * Tre flikar längst ner (Musik, Reklam, Etiketter), musiken först. Uppe till höger: Rapportera problem
 * och Inställningar. Listor, Sök och Inställningar öppnas som egna sidor med tillbaka-pil.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Hem(lagring: Lagring, @Suppress("UNUSED_PARAMETER") forsokIgen: () -> Unit, loggaUt: () -> Unit) {
    var flik by rememberSaveable { mutableIntStateOf(0) }
    var sida by rememberSaveable { mutableStateOf<String?>(null) }   // listor | sok | installningar
    var enkel by remember { mutableStateOf(lagring.enkel) }
    var rapportera by remember { mutableStateOf(false) }
    // Varje flik behåller det man skrivit/valt när man byter flik och kommer tillbaka.
    val minne = rememberSaveableStateHolder()
    LaunchedEffect(Delning.nummer) { if (Delning.nummer > 0) { flik = 1; sida = null } }   // delad bild: till Reklam
    androidx.activity.compose.BackHandler(enabled = sida != null) { sida = null }
    val flikar = listOf(
        Flik(t("Musik"), Icons.Outlined.MusicNote, Icons.Rounded.MusicNote),
        Flik(t("Reklam"), Icons.Outlined.Tv, Icons.Rounded.Tv),
        Flik(t("Etiketter"), Icons.Outlined.Sell, Icons.Rounded.Sell),
    )
    val titel = when (sida) {
        "listor" -> t("Musiklistor"); "sok" -> t("Sök musik"); "installningar" -> t("Inställningar"); else -> null
    }
    val (list, paList) = listFarg()
    val bas = Anslutning.bas
    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = {
                    if (sida != null) IconButton(onClick = { sida = null }) {
                        Icon(Icons.AutoMirrored.Rounded.ArrowBack, t("Tillbaka"), tint = paList)
                    }
                },
                title = {
                    Column {
                        if (titel == null) Ordmarke(26.sp)
                        else Text(titel, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, color = paList)
                    }
                },
                actions = {
                    IconButton(onClick = { rapportera = true }, Modifier.size(56.dp)) {
                        Icon(Icons.Outlined.ReportProblem, t("Rapportera problem"), Modifier.size(28.dp), tint = paList)
                    }
                    if (sida != "installningar") IconButton(onClick = { sida = "installningar" }, Modifier.size(56.dp)) {
                        Icon(Icons.Outlined.Settings, t("Inställningar"), Modifier.size(28.dp), tint = paList)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = list),
            )
        },
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainer) {
                flikar.forEachIndexed { i, f ->
                    val vald = flik == i && sida == null
                    NavigationBarItem(
                        selected = vald, onClick = { flik = i; sida = null },
                        icon = { Icon(if (vald) f.vald else f.ikon, null, Modifier.size(28.dp)) },
                        label = { Text(f.namn, style = MaterialTheme.typography.labelMedium) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = MaterialTheme.colorScheme.onPrimaryContainer,
                            indicatorColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                            selectedTextColor = MaterialTheme.colorScheme.onSurface),
                    )
                }
            }
        },
        snackbarHost = { SnackbarHost(LocalSnackbar.current) },
    ) { inre ->
        Column(Modifier.padding(inre).consumeWindowInsets(inre).fillMaxSize()) {
            // Ingen rad om anslutningen (pappa vill inte se den): appen letar upp butiken själv i bakgrunden.
            Box(Modifier.weight(1f).fillMaxWidth()) {
                val s = sida
                val nyckel = s ?: "flik$flik"
                minne.SaveableStateProvider(nyckel) {
                    when (s) {
                        "listor" -> MusikListor(lagring)
                        "sok" -> MusikSok(lagring)
                        "installningar" -> Installningar(lagring, enkel, { enkel = it; lagring.enkel = it }, loggaUt,
                            rapportera = { rapportera = true })
                        else -> when (flik) {
                            0 -> Startsida(lagring, enkel) { sida = it }
                            1 -> SkarmFlik(lagring)
                            else -> EtikettFlik(lagring)
                        }
                    }
                }
            }
        }
    }
    if (rapportera) RapporteraProblem(lagring, sida ?: listOf("musik", "reklam", "etiketter")[flik]) { rapportera = false }
}

@Suppress("unused")
@Composable
private fun KommerSnart(ikon: ImageVector, namn: String, text: String) = Mitten {
    Surface(shape = RoundedCornerShape(28.dp), color = MaterialTheme.colorScheme.primaryContainer) {
        Icon(ikon, null, Modifier.padding(22.dp).size(52.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
    }
    Spacer(Modifier.height(20.dp))
    Text(namn, style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(8.dp))
    Text(text, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(16.dp))
    Text(t("Kommer snart"), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
}

@Composable
fun Mitten(innehall: @Composable ColumnScope.() -> Unit) =
    Column(Modifier.fillMaxSize().systemBarsPadding().imePadding().padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center, content = innehall)

@Composable
fun StorKnapp(text: String, ikon: ImageVector? = null, aktiv: Boolean = true, onClick: () -> Unit) =
    Button(onClick = onClick, enabled = aktiv, shape = RoundedCornerShape(20.dp),
        modifier = Modifier.fillMaxWidth(0.85f).height(64.dp)) {
        if (ikon != null) { Icon(ikon, null, Modifier.size(26.dp)); Spacer(Modifier.width(10.dp)) }
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
