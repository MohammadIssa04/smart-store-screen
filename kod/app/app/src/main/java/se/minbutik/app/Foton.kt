package se.minbutik.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream

/** Foton från kameran eller galleriet görs till JPEG på högst 2000 px (snabbare att skicka, räcker gott). */
object Foton {
    private const val MAX = 2000

    fun jpeg(context: Context, uri: Uri): ByteArray? = runCatching {
        val r = context.contentResolver
        val storlek = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        r.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, storlek) }
        var skala = 1
        while (maxOf(storlek.outWidth, storlek.outHeight) / (skala * 2) >= MAX) skala *= 2
        var bild = r.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = skala })
        } ?: return null
        // Telefonens foton kan ligga ner: vrid rätt efter EXIF.
        val vrid = r.openInputStream(uri)?.use {
            when (ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        } ?: 0f
        if (vrid != 0f) bild = Bitmap.createBitmap(bild, 0, 0, bild.width, bild.height, Matrix().apply { postRotate(vrid) }, true)
        val s = MAX.toFloat() / maxOf(bild.width, bild.height)
        if (s < 1f) bild = Bitmap.createScaledBitmap(bild, (bild.width * s).toInt(), (bild.height * s).toInt(), true)
        ByteArrayOutputStream().use { ut -> bild.compress(Bitmap.CompressFormat.JPEG, 90, ut); ut.toByteArray() }
    }.getOrNull()
}
