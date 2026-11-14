package se.minbutik.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material.icons.automirrored.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import org.json.JSONObject
import se.minbutik.app.Anslutning
import se.minbutik.app.BuildConfig
import se.minbutik.app.Lagring
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.outlined.ReportProblem
import androidx.compose.foundation.text.KeyboardOptions
import se.minbutik.app.Uppdatering
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.launch
import java.time.LocalTime
import java.time.format.DateTimeFormatter

/** Fliken Musik: spelaren med omslag, och knappar till musiklistor och sök. En ny version av appen syns överst. */
@Composable
fun Startsida(lagring: Lagring, enkel: Boolean, valj: (String) -> Unit) {
    val context = LocalContext.current
    val skop = rememberCoroutineScope()
    LaunchedEffect(Anslutning.bas) { if (Anslutning.bas != null) Uppdatering.kolla(lagring.nyckel) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Uppdatering.ny?.let { v ->
            NyVersion(v, Modifier.padding(horizontal = 20.dp)) { skop.launch { Uppdatering.uppdatera(context, lagring.nyckel) } }
        }
        Spelare(lagring)
        if (!enkel) Row(Modifier.padding(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MusikKnapp(t("Listor"), Icons.AutoMirrored.Rounded.QueueMusic, Modifier.weight(1f)) { valj("listor") }
            MusikKnapp(t("Sök musik"), Icons.Rounded.Search, Modifier.weight(1f)) { valj("sok") }
        }
    }
}

@Composable
private fun MusikKnapp(namn: String, ikon: ImageVector, modifier: Modifier, onClick: () -> Unit) =
    FilledTonalButton(onClick = onClick, modifier.height(64.dp), shape = RoundedCornerShape(20.dp)) {
        Icon(ikon, null, Modifier.size(26.dp))
        Spacer(Modifier.width(10.dp))
        Text(namn, style = MaterialTheme.typography.titleMedium, maxLines = 1)
    }

/** "Rapportera problem": pappa skriver vad som är fel och det skickas till Mohammad (Telegram, via butikens dator). */
@Composable
fun RapporteraProblem(lagring: Lagring, sida: String, stang: () -> Unit) {
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    var text by rememberSaveable { mutableStateOf("") }
    var skickar by remember { mutableStateOf(false) }
    var fel by remember { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = { if (!skickar) stang() },
        icon = { Icon(Icons.Outlined.ReportProblem, null) },
        title = { Text(t("Rapportera problem")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(t("Skriv vad som är fel. Mohammad får meddelandet direkt."), style = MaterialTheme.typography.bodyMedium)
                OutlinedTextField(value = text, onValueChange = { text = it.take(2000); fel = null }, minLines = 4,
                    placeholder = { Text(t("T.ex. musiken har tystnat")) }, shape = RoundedCornerShape(16.dp),
                    modifier = Modifier.fillMaxWidth())
                fel?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
            }
        },
        confirmButton = {
            Button(enabled = text.isNotBlank() && !skickar, onClick = {
                skickar = true
                skop.launch {
                    val s = Anslutning.anrop("POST", "/api/problem", JSONObject().put("text", text.trim()).put("sida", sida)
                        .put("version", BuildConfig.VERSION_NAME), lagring.nyckel)
                    skickar = false
                    if (s.kod == 200) {
                        text = ""
                        stang()
                        snack.showSnackbar(s.json?.optString("meddelande")?.takeIf { it.isNotEmpty() }
                            ?: t("Tack! Mohammad har fått ditt meddelande."))
                    } else fel = if (s.kod == 0) t("Ingen kontakt med butiken. Försök igen, eller ring Mohammad.")
                                 else s.json?.optString("fel")?.takeIf { it.isNotEmpty() } ?: t("Det gick inte. Försök igen.")
                }
            }) {
                if (skickar) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                else { Icon(Icons.AutoMirrored.Rounded.Send, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)); Text(t("Skicka")) }
            }
        },
        dismissButton = { TextButton(onClick = stang, enabled = !skickar) { Text(t("Avbryt")) } })
}

@Suppress("unused")
@Composable
private fun LitenRuta(namn: String, ikon: ImageVector, modifier: Modifier, onClick: () -> Unit) =
    Surface(onClick = onClick, shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.primaryContainer,
        modifier = modifier.heightIn(min = 104.dp)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(ikon, null, Modifier.size(34.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
            Text(namn, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onPrimaryContainer, maxLines = 1)
        }
    }

/** "Ny version finns": vad som är nytt och en stor Uppdatera-knapp (med förlopp medan den hämtas). */
@Composable
private fun NyVersion(v: JSONObject, modifier: Modifier, uppdatera: () -> Unit) {
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.tertiaryContainer) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.SystemUpdate, null, tint = MaterialTheme.colorScheme.onTertiaryContainer)
                Spacer(Modifier.width(10.dp))
                Text(tf("Ny version %s finns", v.optString("namn")), style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onTertiaryContainer)
            }
            v.optJSONArray("nytt")?.let { nytt ->
                for (i in 0 until nytt.length()) Text("•  " + nytt.optString(i), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer)
            }
            Uppdatering.fel?.let { Text(t(it), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error) }
            val f = Uppdatering.framsteg
            if (f != null) {
                LinearProgressIndicator(progress = { f }, Modifier.fillMaxWidth().height(8.dp), drawStopIndicator = {})
                Text(tf("Hämtar … %s %%", (f * 100).toInt()), style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer)
            } else Button(onClick = uppdatera, Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(18.dp)) {
                Icon(Icons.Rounded.Download, null); Spacer(Modifier.width(8.dp)); Text(t("Uppdatera appen"))
            }
        }
    }
}

@Composable
private fun StorRuta(namn: String, text: String, ikon: ImageVector, huvud: Boolean = false, onClick: () -> Unit) {
    val bg = if (huvud) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.primaryContainer
    val fg = if (huvud) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onPrimaryContainer
    Surface(onClick = onClick, shape = RoundedCornerShape(28.dp), color = bg,
        modifier = Modifier.fillMaxWidth().heightIn(min = 132.dp)) {
        Row(Modifier.padding(24.dp), verticalAlignment = Alignment.CenterVertically) {
            Surface(shape = RoundedCornerShape(22.dp), color = fg.copy(alpha = 0.14f)) {
                Icon(ikon, null, Modifier.padding(16.dp).size(44.dp), tint = fg)
            }
            Spacer(Modifier.width(20.dp))
            Column(Modifier.weight(1f)) {
                Text(namn, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold, color = fg)
                Text(text, style = MaterialTheme.typography.bodyLarge, color = fg.copy(alpha = 0.85f))
            }
            Icon(Icons.AutoMirrored.Rounded.ArrowForwardIos, null, tint = fg.copy(alpha = 0.7f))
        }
    }
}

/** Inställningar: språk, enkelt läge, butikens dator (Pi-status), logga ut. */
@Composable
fun Installningar(lagring: Lagring, enkel: Boolean, andraEnkel: (Boolean) -> Unit, loggaUt: () -> Unit,
                  rapportera: () -> Unit) {
    var fragaUt by remember { mutableStateOf(false) }
    var utvecklare by remember { mutableStateOf(lagring.utvecklare) }
    var tryck by remember { mutableIntStateOf(0) }
    val skop = rememberCoroutineScope()
    val snack = LocalSnackbar.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Rubrik(t("Språk"))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            listOf("sv" to "Svenska", "ar" to "العربية").forEach { (kod, namn) ->
                val vald = Sprak.kod == kod
                Surface(onClick = { Sprak.kod = kod; lagring.sprak = kod }, Modifier.weight(1f).height(64.dp),
                    shape = RoundedCornerShape(18.dp),
                    color = if (vald) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer) {
                    Row(horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                        if (vald) { Icon(Icons.Rounded.CheckCircle, null, tint = MaterialTheme.colorScheme.primary); Spacer(Modifier.width(8.dp)) }
                        Text(namn, style = MaterialTheme.typography.titleMedium)
                    }
                }
            }
        }
        Surface(onClick = { andraEnkel(!enkel) }, shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
            Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.TouchApp, null)
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(t("Enkelt läge"), style = MaterialTheme.typography.titleMedium)
                    Text(t("Musik visar bara spelaren"), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Switch(checked = enkel, onCheckedChange = { andraEnkel(it) })
            }
        }
        Button(onClick = rapportera, Modifier.fillMaxWidth().height(64.dp), shape = RoundedCornerShape(18.dp)) {
            Icon(Icons.Outlined.ReportProblem, null, Modifier.size(26.dp))
            Spacer(Modifier.width(10.dp))
            Text(t("Rapportera problem"), style = MaterialTheme.typography.titleMedium)
        }
        // Butikens dator (temperatur, minne, tjänster) bara för Mohammad: tryck 7 gånger på versionen nedanför.
        if (utvecklare) {
            Spacer(Modifier.height(4.dp))
            Rubrik(t("Butikens dator"))
            PiStatus(lagring)
        }
        Spacer(Modifier.height(4.dp))
        OutlinedButton(onClick = { fragaUt = true }, Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
            Icon(Icons.AutoMirrored.Rounded.Logout, null)
            Spacer(Modifier.width(10.dp))
            Text(t("Logga ut den här telefonen"))
        }
        Text("Min Butik ${BuildConfig.VERSION_NAME}  ·  Made by Mohammad Issa", Modifier.fillMaxWidth()
            .clickable(interactionSource = null, indication = null) {
                tryck++
                if (tryck >= 7) {
                    tryck = 0
                    utvecklare = !utvecklare
                    lagring.utvecklare = utvecklare
                    skop.launch { snack.showSnackbar(if (utvecklare) "Utvecklarläge på" else "Utvecklarläge av") }
                }
            },
            textAlign = TextAlign.Center, style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (fragaUt) AlertDialog(onDismissRequest = { fragaUt = false },
        title = { Text(t("Logga ut?")) },
        text = { Text(t("Du behöver en ny kod för att logga in igen.")) },
        confirmButton = { TextButton(onClick = { fragaUt = false; loggaUt() }) { Text(t("Logga ut")) } },
        dismissButton = { TextButton(onClick = { fragaUt = false }) { Text(t("Avbryt")) } })
}

@Composable
private fun Rubrik(text: String) =
    Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)

/** Pi:ns läge: uppdateras var 15:e sekund medan sidan är öppen. */
@Composable
fun PiStatus(lagring: Lagring) {
    var s by remember { mutableStateOf<JSONObject?>(null) }
    var kontakt by remember { mutableStateOf<Boolean?>(null) }
    var senast by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        while (true) {
            val svar = Anslutning.anrop("GET", "/api/status", null, lagring.nyckel)
            if (svar.kod == 200 && svar.json != null) {
                s = svar.json; kontakt = true
                senast = LocalTime.now().format(DateTimeFormatter.ofPattern("HH:mm:ss"))
            } else kontakt = false
            delay(15_000)
        }
    }
    val gron = Color(0xFF2E7D32)
    val rod = MaterialTheme.colorScheme.error
    Surface(shape = RoundedCornerShape(22.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(if (kontakt == false) Icons.Rounded.CloudOff else Icons.Rounded.Dns, null,
                    tint = if (kontakt == false) rod else gron)
                Spacer(Modifier.width(10.dp))
                Text(when (kontakt) {
                    null -> t("Kollar …")
                    true -> t("Butikens dator är igång")
                    false -> t("Ingen kontakt med butikens dator")
                }, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            }
            senast?.let { Text(tf("Senaste kontakt: %s", it), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant) }
            val d = s ?: return@Column
            HorizontalDivider()
            val temp = d.optDouble("temp", Double.NaN)
            if (!temp.isNaN()) Matrad(Icons.Rounded.Thermostat, t("Temperatur"), "${temp.toInt()} °C",
                if (temp >= 75) rod else null)
            if (d.has("cpu") && !d.isNull("cpu")) Matrad(Icons.Rounded.Speed, t("Belastning"), "${d.optInt("cpu")} %",
                if (d.optInt("cpu") >= 90) rod else null)
            d.optJSONObject("ram")?.let {
                Matrad(Icons.Rounded.Memory, t("Minne"), tf("%s av %s GB", it.optString("anvant_gb"), it.optString("totalt_gb")))
            }
            d.optJSONObject("disk")?.let {
                Matrad(Icons.Rounded.Storage, t("Ledigt utrymme"), "${it.optString("ledigt_gb")} GB",
                    if (it.optDouble("ledigt_gb") < 5) rod else null)
            }
            val tj = d.optJSONObject("tjanster")
            Tjanstrad(t("Skärmen (skylt.service)"), tj?.optBoolean("skylt"), gron, rod)
            Tjanstrad(t("Ampen (x25-vakt.service)"), tj?.optBoolean("x25-vakt"), gron, rod)
            if (!d.isNull("ampen_ansluten") && d.has("ampen_ansluten"))
                Tjanstrad(t("Ampen ansluten"), d.optBoolean("ampen_ansluten"), gron, rod, t("Ja"), t("Nej"))
            Tjanstrad(t("Musiken"), tj?.optBoolean("musik"), gron, rod)
            Matrad(Icons.Rounded.Backup, t("Säkerhetskopia"),
                d.optString("backup").takeIf { it.isNotEmpty() && it != "null" }?.replace("T", " ") ?: t("ingen än"))
            val problem = d.optJSONArray("problem")
            if (problem != null && problem.length() > 0) {
                HorizontalDivider()
                for (i in 0 until problem.length()) Row(verticalAlignment = Alignment.Top) {
                    Icon(Icons.Rounded.Warning, null, tint = rod, modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(problem.optString(i), style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

@Composable
private fun Matrad(ikon: ImageVector, namn: String, varde: String, farg: Color? = null) =
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(ikon, null, Modifier.size(22.dp), tint = farg ?: MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(12.dp))
        Text(namn, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Text(ltr(varde), style = MaterialTheme.typography.titleMedium, color = farg ?: MaterialTheme.colorScheme.onSurface)
    }

@Composable
private fun Tjanstrad(namn: String, ok: Boolean?, gron: Color, rod: Color,
                      ja: String = t("Igång"), nej: String = t("Av")) =
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(if (ok == true) Icons.Rounded.CheckCircle else Icons.Rounded.Cancel, null, Modifier.size(22.dp),
            tint = if (ok == true) gron else rod)
        Spacer(Modifier.width(12.dp))
        Text(namn, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Text(if (ok == true) ja else nej, style = MaterialTheme.typography.titleMedium,
            color = if (ok == true) gron else rod)
    }
