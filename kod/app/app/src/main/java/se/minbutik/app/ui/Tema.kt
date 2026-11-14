package se.minbutik.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import se.minbutik.app.R

// Butikens färger, samma som på skylten: magenta, krämvitt och en djup plommonton för text.
val Rosa = Color(0xFFD81B60)          // primär (lite mörkare än skyltens E53373: läsbar vit text på den)
val Skylt = Color(0xFFE53373)
val Kram = Color(0xFFFFF6F0)
val Plommon = Color(0xFF4A0D27)

// 1.4: lugnare färger. Appen är vit/grå med mörk text; rosa bara i loggan och hjärtat (favoriter).
private val Kol = Color(0xFF2B2325)
private val ljust = lightColorScheme(
    primary = Kol, onPrimary = Color.White,
    primaryContainer = Color(0xFFEDE9E8), onPrimaryContainer = Color(0xFF231C1E),
    secondary = Color(0xFF5F5557), onSecondary = Color.White,
    secondaryContainer = Color(0xFFF0ECEB), onSecondaryContainer = Color(0xFF231C1E),
    tertiaryContainer = Color(0xFFE6F0E7), onTertiaryContainer = Color(0xFF16301B),
    background = Color(0xFFFBFAF9), onBackground = Color(0xFF1F1A1C),
    surface = Color(0xFFFBFAF9), onSurface = Color(0xFF1F1A1C),
    surfaceVariant = Color(0xFFEDE9E8), onSurfaceVariant = Color(0xFF5F5759),
    surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFF8F6F5),
    surfaceContainer = Color(0xFFF3F0EF), surfaceContainerHigh = Color(0xFFEEEAE9),
    surfaceContainerHighest = Color(0xFFE8E4E3),
    outline = Color(0xFF8A8284), outlineVariant = Color(0xFFDDD7D8),
    error = Color(0xFFB3261E), errorContainer = Color(0xFFF9DEDC), onErrorContainer = Color(0xFF410E0B),
)

private val morkt = darkColorScheme(
    primary = Color(0xFFF2EDEE), onPrimary = Color(0xFF231C1E),
    primaryContainer = Color(0xFF3A3335), onPrimaryContainer = Color(0xFFF2EDEE),
    secondary = Color(0xFFD3C8CA), onSecondary = Color(0xFF2E2729),
    secondaryContainer = Color(0xFF3A3335), onSecondaryContainer = Color(0xFFF2EDEE),
    tertiaryContainer = Color(0xFF2B4430), onTertiaryContainer = Color(0xFFD9EEDC),
    background = Color(0xFF171415), onBackground = Color(0xFFEDE7E8),
    surface = Color(0xFF171415), onSurface = Color(0xFFEDE7E8),
    surfaceVariant = Color(0xFF433C3E), onSurfaceVariant = Color(0xFFCFC6C8),
    surfaceContainerLowest = Color(0xFF110E0F), surfaceContainerLow = Color(0xFF1F1B1C),
    surfaceContainer = Color(0xFF242021), surfaceContainerHigh = Color(0xFF2E2A2B),
    surfaceContainerHighest = Color(0xFF393436),
    outline = Color(0xFF978E90), outlineVariant = Color(0xFF433C3E),
    error = Color(0xFFF2B8B5),
)

// Bitter Black är butikens logga (som på skylten); Poppins för rubriker och knappar.
val Bitter = FontFamily(
    Font(R.font.bitter, FontWeight.Black, variationSettings = FontVariation.Settings(FontVariation.weight(900))),
)
private val Poppins = FontFamily(
    Font(R.font.poppins_semibold, FontWeight.SemiBold),
    Font(R.font.poppins_bold, FontWeight.Bold),
    Font(R.font.poppins_extrabold, FontWeight.ExtraBold),
)

// Stora texter: appen ska gå att använda i butiken utan glasögon. Brödtext i systemets typsnitt.
private val text = Typography(
    displaySmall = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.ExtraBold, fontSize = 34.sp, lineHeight = 40.sp),
    headlineMedium = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Bold, fontSize = 26.sp, lineHeight = 34.sp),
    headlineSmall = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Bold, fontSize = 23.sp, lineHeight = 31.sp),
    titleLarge = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.Bold, fontSize = 21.sp, lineHeight = 28.sp),
    titleMedium = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, lineHeight = 25.sp),
    bodyLarge = TextStyle(fontSize = 19.sp, lineHeight = 27.sp),
    bodyMedium = TextStyle(fontSize = 17.sp, lineHeight = 24.sp),
    labelLarge = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, lineHeight = 24.sp),
    labelMedium = TextStyle(fontFamily = Poppins, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, lineHeight = 20.sp),
)

/** Snackbar för korta besked ("Spelar nu", "Togs bort ur listan"), nåbar från alla skärmar. */
val LocalSnackbar = staticCompositionLocalOf { SnackbarHostState() }

@Composable
fun RosaTema(innehall: @Composable () -> Unit) {
    val snack = remember { SnackbarHostState() }
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) morkt else ljust, typography = text) {
        CompositionLocalProvider(LocalSnackbar provides snack, content = innehall)
    }
}

/** Listen högst upp: samma lugna färg som resten av appen (inte rosa). */
@Composable
fun listFarg(): Pair<Color, Color> = MaterialTheme.colorScheme.surface to MaterialTheme.colorScheme.onSurface

/** Rosa accent (loggan, hjärtat): ljusare i mörkt läge så att den syns. */
@Composable
fun rosaAccent(): Color = if (isSystemInDarkTheme()) Color(0xFFFF8FB1) else Rosa

/** "MIN BUTIK" i butikens logotypsnitt. */
@Composable
fun Ordmarke(storlek: TextUnit, farg: Color = rosaAccent(), modifier: Modifier = Modifier) =
    Text("MIN BUTIK", fontFamily = Bitter, fontWeight = FontWeight.Black, fontSize = storlek, color = farg,
        letterSpacing = 0.5.sp, modifier = modifier)
