package se.minbutik.app.ui

import android.graphics.BitmapFactory
import androidx.annotation.OptIn
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.material.icons.rounded.Close
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.material.icons.rounded.Tv
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import se.minbutik.app.Anslutning

/** Skärmens video (9:16) som loopar utan ljud, som på skylten. Hämtas med telefonens nyckel. */
@OptIn(UnstableApi::class)
@Composable
fun Skyltvideo(vag: String, nyckel: String?, modifier: Modifier = Modifier, reserv: String? = null,
               helskarm: Boolean = true) {
    var stor by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val adress = remember(vag) { Anslutning.adress(vag) }
    // Telefonens videoavkodare kan ge upp (svart ruta för alltid): prova en gång till, sedan en stillbild.
    var fel by remember(adress) { mutableStateOf(false) }
    var forsok by remember(adress) { mutableIntStateOf(0) }
    val spelare = remember(adress) {
        ExoPlayer.Builder(context).build().apply {
            val kalla = DefaultHttpDataSource.Factory()
                .setDefaultRequestProperties(mapOf("Authorization" to "Bearer ${nyckel ?: ""}"))
            if (adress != null) setMediaSource(ProgressiveMediaSource.Factory(kalla).createMediaSource(MediaItem.fromUri(adress)))
            repeatMode = Player.REPEAT_MODE_ALL
            volume = 0f
            playWhenReady = true
            prepare()
        }
    }
    DisposableEffect(spelare) {
        val lyssnare = object : Player.Listener {
            override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                if (forsok++ < 1) { spelare.prepare(); spelare.play() } else fel = true
            }
        }
        spelare.addListener(lyssnare)
        onDispose { spelare.removeListener(lyssnare) }
    }
    if (fel) {
        if (reserv != null) NatBild(reserv, nyckel, modifier.aspectRatio(9f / 16f).clip(RoundedCornerShape(20.dp)))
        else Box(modifier.aspectRatio(9f / 16f).clip(RoundedCornerShape(20.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center) {
            androidx.compose.material3.Text(t("Videon går inte att visa på den här telefonen. Den syns ändå på skärmen."),
                Modifier.padding(20.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
        return
    }
    DisposableEffect(spelare) { onDispose { spelare.release() } }
    Box(modifier.aspectRatio(9f / 16f).clip(RoundedCornerShape(20.dp)).background(MaterialTheme.colorScheme.surfaceVariant)) {
        AndroidView(factory = { ctx ->
            PlayerView(ctx).apply {
                player = spelare
                useController = false
                resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
            }
        }, modifier = Modifier.fillMaxSize())
        // Tryck på videon: helskärm (svart bakgrund). Tryck igen eller tillbaka: stäng.
        if (helskarm) Box(Modifier.matchParentSize().clickable { stor = true })
    }
    if (stor) Dialog(onDismissRequest = { stor = false },
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Box(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color.Black).clickable { stor = false },
            contentAlignment = Alignment.Center) {
            Skyltvideo(vag, nyckel, Modifier.fillMaxHeight().padding(vertical = 24.dp), reserv, helskarm = false)
            androidx.compose.material3.FilledTonalIconButton(onClick = { stor = false },
                Modifier.align(Alignment.TopEnd).systemBarsPadding().padding(12.dp).size(56.dp)) {
                androidx.compose.material3.Icon(androidx.compose.material.icons.Icons.Rounded.Close, t("Stäng"),
                    Modifier.size(30.dp))
            }
        }
    }
}

/** En bild (t.ex. en bildruta ur videon) hämtad med nyckeln. */
@Composable
fun NatBild(vag: String, nyckel: String?, modifier: Modifier = Modifier) {
    var bild by remember(vag) { mutableStateOf<ImageBitmap?>(null) }
    var misslyckad by remember(vag) { mutableStateOf(false) }
    LaunchedEffect(vag) {
        bild = Anslutning.hamtaData(vag, nyckel)?.let { BitmapFactory.decodeByteArray(it, 0, it.size)?.asImageBitmap() }
        misslyckad = bild == null                  // ingen bild: visa en ikon i stället för att snurra för alltid
    }
    Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
        bild?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
            ?: if (misslyckad) androidx.compose.material3.Icon(androidx.compose.material.icons.Icons.Rounded.Tv, null,
                Modifier.size(40.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            else CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 3.dp)
    }
}
