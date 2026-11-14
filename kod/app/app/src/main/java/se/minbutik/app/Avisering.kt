package se.minbutik.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.delay
import se.minbutik.app.ui.Sprak
import se.minbutik.app.ui.t
import se.minbutik.app.ui.tf

/**
 * Säger till när en video är klar, även om appen är stängd: ett bakgrundsjobb frågar butiken
 * var 10:e sekund (i högst 25 minuter) och visar en avisering när videon är färdig.
 * Ingen Google-tjänst behövs. Är appen öppen syns förhandsvisningen direkt i stället.
 */
class VantaPaVideo(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getString("arende") ?: return Result.success()
        val lagring = Lagring(applicationContext)
        lagring.sprak?.let { Sprak.kod = it }
        val namn = inputData.getString("namn") ?: t("Annonsen")
        if (Anslutning.bas == null && Anslutning.hitta(applicationContext, lagring) == null) return Result.retry()
        repeat(150) {
            val s = Anslutning.anrop("GET", "/api/annonser/arende/$id", null, lagring.nyckel)
            when (s.json?.optString("status")) {
                "klar" -> { visa(applicationContext, t("Videon är klar"), tf("%s – tryck för att titta och publicera.", namn)); return Result.success() }
                "fel" -> { visa(applicationContext, t("Videon kunde inte göras"), t("Öppna appen och försök igen.")); return Result.success() }
                "arbetar" -> Unit
                else -> if (s.kod != 0) return Result.success()
            }
            delay(10_000)
        }
        return Result.success()
    }

    companion object {
        private const val KANAL = "videor"
        @Volatile var appenSyns = false

        fun starta(context: Context, arendeId: String, namn: String) {
            val jobb = OneTimeWorkRequestBuilder<VantaPaVideo>()
                .setInputData(workDataOf("arende" to arendeId, "namn" to namn))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork("video-$arendeId", ExistingWorkPolicy.KEEP, jobb)
        }

        fun visa(context: Context, rubrik: String, text: String) {
            if (appenSyns) return
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context,
                    Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
            val nm = context.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(KANAL, t("Videor"), NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = t("När en reklamvideo är klar") })
            val oppna = PendingIntent.getActivity(context, 0,
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE)
            nm.notify(1, NotificationCompat.Builder(context, KANAL)
                .setSmallIcon(R.drawable.ic_notis)
                .setContentTitle(rubrik).setContentText(text)
                .setContentIntent(oppna).setAutoCancel(true).build())
        }
    }
}
