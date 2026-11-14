package se.minbutik.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

/** Pappas egna foton på butikens riktiga varor blir de bästa annonserna – om de tas rätt. */
private val TIPS: List<Triple<ImageVector, String, String>> = listOf(
    Triple(Icons.Rounded.Spa, "Frukt och grönt: 3 fina", "Lägg 3 fina exemplar på disken. Fota inte hela lådan eller högen."),
    Triple(Icons.Rounded.CameraAlt, "Rakt framifrån", "Håll telefonen i varans höjd, inte snett uppifrån."),
    Triple(Icons.Rounded.CropFree, "Hela varan i bild", "Lite luft runt om. Inget får vara avklippt."),
    Triple(Icons.Rounded.LightMode, "Bra ljus", "Vid fönstret eller under taklampan. Ingen blixt."),
    Triple(Icons.Rounded.Layers, "Lugn bakgrund", "En ren disk eller vägg bakom. Inga händer eller andra varor."),
    Triple(Icons.Rounded.Share, "Från Facebook", "Dela bilden till Min Butik. Ta ingen skärmdump."),
)

@Composable
fun FotoguideKnapp(modifier: Modifier = Modifier) {
    var visa by remember { mutableStateOf(false) }
    FilledTonalButton(onClick = { visa = true }, modifier.height(52.dp), shape = RoundedCornerShape(16.dp)) {
        Icon(Icons.Rounded.Lightbulb, null)
        Spacer(Modifier.width(8.dp))
        Text(t("Så tar du ett bra foto"), style = MaterialTheme.typography.labelLarge)
    }
    if (visa) Fotoguide { visa = false }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Fotoguide(stang: () -> Unit) {
    Blad(onDismissRequest = stang, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, bottom = 32.dp)) {
            Text(t("Så tar du ett bra foto"), style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(16.dp))
            TIPS.forEach { (ikon, rubrik, text) ->
                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.Top) {
                    Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                        Icon(ikon, null, Modifier.padding(10.dp).size(26.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
                    }
                    Spacer(Modifier.width(14.dp))
                    Column {
                        Text(t(rubrik), style = MaterialTheme.typography.titleMedium)
                        Text(t(text), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Button(onClick = stang, Modifier.fillMaxWidth().height(56.dp), shape = RoundedCornerShape(18.dp)) {
                Text(t("Jag förstår"))
            }
        }
    }
}
