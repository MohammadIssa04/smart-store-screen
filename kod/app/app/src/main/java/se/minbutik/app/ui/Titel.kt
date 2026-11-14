package se.minbutik.app.ui

/**
 * Snyggar till låttitlar från YouTube för visning:
 *  "Fairuz - Kifak Inta (Lyric Video) | فيروز - كيفك إنت"      -> "Kifak Inta"  (artisten visas separat)
 *  "محمد عبد الوهاب - هان الود  - جودة عالية - كلمات الأغنية"     -> "محمد عبد الوهاب - هان الود"
 * Originaltiteln ändras inte på Pi:n.
 */
private val skrap = listOf(
    Regex("""\((official|lyric|lyrics|audio|video|hd|hq|4k|full|live)[^)]*\)""", RegexOption.IGNORE_CASE),
    Regex("""\[[^\]]*]"""),
    Regex("""\b(official (music )?video|lyric video|lyrics|official audio|audio|hd|hq|4k|high quality)\b""", RegexOption.IGNORE_CASE),
    Regex("""جودة عالية|كلمات الأغنية|كلمات الاغنية|بدون اعلانات|بدون إعلانات|مع الكلمات|الأغنية كاملة|كاملة|كامله|حصريا|حصريًا"""),
    Regex("""#\S+"""),
)

fun renTitel(titel: String, artist: String? = null): String {
    var t = titel.split(" | ", "｜").first()
    skrap.forEach { t = t.replace(it, " ") }
    t = t.replace(Regex("""\s*[-–—]\s*([-–—]\s*)*$"""), "")           // kvarlämnade bindestreck i slutet
        .replace(Regex("""\s{2,}"""), " ").trim(' ', '-', '–', '—', '|', ',')
    // "Artist - Låt" när artisten redan står under titeln
    if (artist != null && " - " in t) {
        val (fore, efter) = t.split(" - ", limit = 2)
        // Samma artist trots olika stavning: "Fairuz" / "Fairouz", "Oum Kalthoum" / "Umm Kulthum".
        fun nyckel(x: String) = x.lowercase().filter { it.isLetter() }.replace("ou", "u").replace("oo", "u")
        val a = nyckel(artist)
        val f = nyckel(fore)
        if (fore.isNotBlank() && efter.isNotBlank() && f.length >= 4 && a.length >= 4 &&
            (a.contains(f) || f.contains(a) || a.take(4) == f.take(4))) t = efter.trim()
    }
    return t.ifBlank { titel }
}
