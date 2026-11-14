package se.minbutik.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Telefonens personliga nyckel och senast fungerande adress, krypterat i telefonen. */
class Lagring(context: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "minbutik",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var nyckel: String?
        get() = prefs.getString("nyckel", null)
        set(v) = prefs.edit().apply { if (v == null) remove("nyckel") else putString("nyckel", v) }.apply()

    /** Ärendet pappa håller på med i "Ny annons" (finns kvar i butiken i 24 h). */
    var pagaendeAnnons: String?
        get() = prefs.getString("pagaende", null)
        set(v) = prefs.edit().apply { if (v == null) remove("pagaende") else putString("pagaende", v) }.apply()

    /** "list" eller "rutnat" för På skärmen; "sv" eller "ar" för språket. */
    var skarmVy: String
        get() = prefs.getString("skarmvy", "rutnat") ?: "rutnat"
        set(v) = prefs.edit().putString("skarmvy", v).apply()

    /** Enkelt läge för pappa (standard): Musik visar bara spelaren. */
    var enkel: Boolean
        get() = prefs.getBoolean("enkel", true)
        set(v) = prefs.edit().putBoolean("enkel", v).apply()

    /** Bara för Mohammad: visar butikens dator (temperatur m.m.) i Inställningar. Slås på genom att trycka 7 gånger på versionen. */
    var utvecklare: Boolean
        get() = prefs.getBoolean("utvecklare", false)
        set(v) = prefs.edit().putBoolean("utvecklare", v).apply()

    var sprak: String?
        get() = prefs.getString("sprak", null)
        set(v) = prefs.edit().apply { if (v == null) remove("sprak") else putString("sprak", v) }.apply()

    /** "http://192.168.1.50:8484" – senast fungerande adress på butikens wifi. */
    var senasteLokala: String?
        get() = prefs.getString("lokal", null)
        set(v) = prefs.edit().putString("lokal", v).apply()
}
