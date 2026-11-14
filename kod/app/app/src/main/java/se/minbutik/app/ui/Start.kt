package se.minbutik.app.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import se.minbutik.app.Mitten
import se.minbutik.app.StorKnapp
import kotlin.math.cos
import kotlin.math.sin


/**
 * Startanimationen: rosa strålar som på skylten vrider sig in, "MIN BUTIK" växer fram och
 * "Gjord av Mohammad Issa" tonar in. Visas medan appen letar efter butiken (minst ca 1,8 s).
 * soker = true visar en liten laddningsrad när animationen är klar men butiken inte hittats än.
 */
@Composable
fun Startbild(soker: Boolean) {
    val tid = remember { Animatable(0f) }
    LaunchedEffect(Unit) { tid.animateTo(1f, tween(1700, easing = LinearOutSlowInEasing)) }
    val snurr by rememberInfiniteTransition(label = "strålar").animateFloat(
        0f, 360f, infiniteRepeatable(tween(24000, easing = LinearEasing)), label = "vinkel")
    val p = tid.value
    fun del(fran: Float, till: Float) = ((p - fran) / (till - fran)).coerceIn(0f, 1f)
    val logga = FastOutSlowInEasing.transform(del(0.15f, 0.6f))
    val signatur = del(0.6f, 1f)

    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            drawRect(Brush.radialGradient(listOf(Skylt, Rosa), center = center, radius = size.maxDimension * 0.75f))
            val n = 16
            val r = size.maxDimension
            val oppna = del(0f, 0.5f)
            for (i in 0 until n) {
                val a = Math.toRadians((snurr + i * 360.0 / n)).toFloat()
                val b = a + (Math.PI / n).toFloat() * oppna
                val path = androidx.compose.ui.graphics.Path().apply {
                    moveTo(center.x, center.y)
                    lineTo(center.x + r * cos(a), center.y + r * sin(a))
                    lineTo(center.x + r * cos(b), center.y + r * sin(b))
                    close()
                }
                drawPath(path, Color.White.copy(alpha = 0.10f))
            }
            drawCircle(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.35f), Color.Transparent),
                center = center, radius = size.minDimension * 0.55f), radius = size.minDimension * 0.55f, center = center)
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Ordmarke(48.sp, Kram, Modifier.scale(0.7f + 0.3f * logga).alpha(logga))
            Spacer(Modifier.height(10.dp))
            Box(Modifier.width((140 * logga).dp).height(4.dp)
                .background(Kram.copy(alpha = 0.8f), RoundedCornerShape(2.dp)))
            Spacer(Modifier.height(36.dp))
            Box(Modifier.height(6.dp).width(140.dp)) {
                if (soker && p >= 1f) LinearProgressIndicator(Modifier.fillMaxSize(), color = Kram,
                    trackColor = Kram.copy(alpha = 0.25f))
            }
        }
        Text(t("Made by Mohammad Issa"), Modifier.align(Alignment.BottomCenter).navigationBarsPadding()
            .padding(bottom = 36.dp).alpha(signatur).offset(y = (12 * (1 - signatur)).dp),
            color = Kram, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
            letterSpacing = 0.5.sp)
    }
}

/** Första gången: välj svenska eller arabiska (kan ändras i menyn ⋮). */
@Composable
fun ValjSprak(valt: (String) -> Unit) = Mitten {
    Ordmarke(40.sp)
    Spacer(Modifier.height(40.dp))
    Text("Välj språk  ·  اختر اللغة", style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(28.dp))
    StorKnapp("Svenska") { valt("sv") }
    Spacer(Modifier.height(14.dp))
    StorKnapp("العربية") { valt("ar") }
}
