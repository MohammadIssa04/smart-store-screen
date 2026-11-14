"""Hittar en säljande produktbild från ett namn.

Källor (inga API-nycklar):
  1. Open Food Facts Sverige (se.openfoodfacts.org) – svenska förpackningar
  2. Open Food Facts globalt – fler förpackningsbilder
  3. Openverse – fria foton (bra för frukt, grönt och bröd)
  4. Wikimedia Commons – fria foton
  5. Pixabay – fria foton, ofta på vit bakgrund (bara med PIXABAY_API_KEY, gratis)
  6. Pexels – fria foton (bara med PEXELS_API_KEY, gratis)
Förrådet (data/bildforrad/) har färdiga bilder som nattjobbet (`forbered_bilder.py`) tagit fram.

Alla kandidater laddas ner, bilder i låg upplösning sorteras bort, och AI:n
betygsätter resten (igenkanning.betygsatt). Bara bilder som håller hög nivå
används. Utan API-nyckel används inga nätbilder alls: då ber boten om ett
eget foto, hellre en bild för lite än en ful."""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
from pathlib import Path

import httpx
from PIL import Image

import konfig

log = logging.getLogger("butiksbot.bildsok")

# Wikimedia och Openverse kräver en kontaktpunkt i User-Agent; botens Telegram-länk räcker.
UA = {"User-Agent": "MinButikBot/1.0 httpx"}
MAX_BYTES = 15 * 1024 * 1024
# Upplösningskrav. Burkar och flaskor är höga och smala, så kravet gäller
# främst långsidan (produkten visas upp till ca 900 px hög på skylten).
MIN_LANGSIDA = 1000
MIN_KORTSIDA = 400
MAX_KANDIDATER = 16


def _off_mapp(kod: str) -> str:
    """Open Food Facts bildmapp: 5060335635716 -> 506/033/563/5716."""
    if len(kod) <= 8:
        return kod
    kod = kod.zfill(13)
    return f"{kod[0:3]}/{kod[3:6]}/{kod[6:9]}/{kod[9:]}"


async def _off(c: httpx.AsyncClient, fraga: str, land: str) -> list[str]:
    """Open Food Facts. Först den nya söktjänsten (search.openfoodfacts.org: snabb, träffar bättre),
    den gamla search.pl (ofta 503) bara om den nya inte svarar."""
    try:
        q = fraga + (' countries_tags:"en:sweden"' if land == "se" else "")
        r = await c.get("https://search.openfoodfacts.org/search",
                        params={"q": q, "page_size": 6, "fields": "code,product_name,image_front_url,images"})
        r.raise_for_status()
        return _off_urls(r.json().get("hits") or [])
    except (httpx.HTTPError, ValueError) as e:
        log.info("search.openfoodfacts.org: %s – provar search.pl", e)
    params = {"search_terms": fraga, "search_simple": 1, "action": "process", "json": 1,
              "page_size": 6, "sort_by": "unique_scans_n",
              "fields": "code,product_name,image_front_url,images"}
    for _ in range(3):                                   # tjänsten svarar ibland 503
        r = await c.get(f"https://{land}.openfoodfacts.org/cgi/search.pl", params=params)
        if r.status_code not in (502, 503, 504):
            break
        await asyncio.sleep(3)
    r.raise_for_status()
    return _off_urls(r.json().get("products", []))


def _off_urls(produkter: list[dict]) -> list[str]:
    urls = []
    for p in produkter:
        # Råfotona först: de är inte beskurna, så produkten står mot en bakgrund som går
        # att frilägga. De beskurna "front"-bilderna saknar bakgrund (dåligt för vita burkar).
        kod = str(p.get("code") or "")
        if kod:
            for k in sorted((k for k in (p.get("images") or {}) if k.isdigit()), key=int)[:3]:
                urls.append(f"https://images.openfoodfacts.org/images/products/{_off_mapp(kod)}/{k}.jpg")
        u = p.get("image_front_url")
        if u:
            urls.append(re.sub(r"\.\d+\.jpg$", ".full.jpg", u))   # största versionen
    return urls


async def _openverse(c: httpx.AsyncClient, fraga: str) -> list[str]:
    r = await c.get("https://api.openverse.org/v1/images/",
                    params={"q": fraga, "page_size": 12, "size": "large", "mature": "false"})
    r.raise_for_status()
    return [x["url"] for x in r.json().get("results", [])
            if x.get("url") and max(x.get("width") or 0, x.get("height") or 0) >= MIN_LANGSIDA]


async def _commons(c: httpx.AsyncClient, fraga: str) -> list[str]:
    r = await c.get("https://commons.wikimedia.org/w/api.php", params={
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{fraga} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url|mime|size", "iiurlwidth": 1600,
    })
    r.raise_for_status()
    sidor = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda s: s.get("index", 0))
    urls = []
    for s in sidor:
        info = (s.get("imageinfo") or [{}])[0]
        if info.get("mime") in ("image/jpeg", "image/png", "image/webp") and \
                max(info.get("width", 0), info.get("height", 0)) >= MIN_LANGSIDA:
            urls.append(info.get("thumburl") or info.get("url"))
    return [u for u in urls if u]


async def _pixabay(c: httpx.AsyncClient, fraga: str) -> list[str]:
    """Pixabay (fri att använda i reklam). Kräver PIXABAY_API_KEY (gratis); utan nyckel hoppas den över."""
    nyckel = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not nyckel:
        return []
    r = await c.get("https://pixabay.com/api/", params={
        "key": nyckel, "q": fraga[:100], "image_type": "photo", "per_page": 12, "safesearch": "true",
        "min_width": MIN_KORTSIDA, "min_height": MIN_KORTSIDA, "order": "popular"})
    r.raise_for_status()
    return [x["largeImageURL"] for x in r.json().get("hits", []) if x.get("largeImageURL")]


def _kort(fraga: str) -> str:
    """'ripe bananas isolated white background' -> 'ripe bananas'."""
    k = re.sub(r"(?i)\b(isolated|on|a|white|transparent|background|studio|packshot)\b", " ", fraga)
    return " ".join(k.split()) or fraga


async def _pexels(c: httpx.AsyncClient, fraga: str) -> list[str]:
    """Pexels (fri att använda i reklam). Kräver PEXELS_API_KEY (gratis); utan nyckel hoppas den över."""
    nyckel = os.environ.get("PEXELS_API_KEY", "").strip()
    if not nyckel:
        return []
    r = await c.get("https://api.pexels.com/v1/search", headers={"Authorization": nyckel},
                    params={"query": fraga[:100], "per_page": 10, "size": "large"})
    r.raise_for_status()
    return [x["src"]["large2x"] for x in r.json().get("photos", []) if x.get("src", {}).get("large2x")]


async def sok_urls(sv: str, en: str, farskvara: bool, off_forst: bool = False) -> list[tuple[str, str]]:
    """(URL, källa), varvade mellan källorna. Open Food Facts kommer alltid sist: fotona
    är tagna av privatpersoner och duger bara i nödfall (och då bara rakt framifrån)."""
    async with httpx.AsyncClient(timeout=25, headers=UA, follow_redirects=True) as c:
        jobb = {
            "off_se": _off(c, sv, "se"),
            "off": _off(c, en or sv, "world"),
            # Fotoarkiven hittar inget med långa sökord: bara kärnan ("ripe bananas"), utan "isolated" osv.
            "openverse": _openverse(c, _kort(en or sv)),
            "commons": _commons(c, _kort(en or sv)),
            "pixabay": _pixabay(c, en or sv),
            "pexels": _pexels(c, _kort(en or sv)),
        }
        svar = await asyncio.gather(*jobb.values(), return_exceptions=True)
    listor = {}
    for namn, s in zip(jobb, svar):
        if isinstance(s, Exception):
            log.warning("%s: %s", namn, s)
            s = []
        listor[namn] = s
    log.info("Bildsök %r/%r: %s", sv, en, {k: len(v) for k, v in listor.items()})
    varvat: list[tuple[str, str]] = []
    sedda: set[str] = set()
    grupper = [["pixabay", "pexels", "openverse", "commons"], ["off_se", "off"]]     # OFF-gruppen sist ...
    if off_forst:
        grupper.reverse()        # ... utom vid en viss smak: där har bara OFF rätt produktfoto
    for grupp in grupper:
        for i in range(max((len(listor[k]) for k in grupp), default=0)):
            for k in grupp:
                if i < len(listor[k]) and listor[k][i] not in sedda:
                    sedda.add(listor[k][i])
                    varvat.append((listor[k][i], k))
    return varvat


async def ladda_ner(c: httpx.AsyncClient, url: str, mal: Path) -> bool:
    """Ladda ner och kontrollera: riktig bild, inte för stor, minst MIN_KORTSIDA px."""
    try:
        r = await c.get(url)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return False
        if len(r.content) > MAX_BYTES or len(r.content) < 20_000:
            return False
        with Image.open(io.BytesIO(r.content)) as im:
            # Transparenta PNG-packshots behöver ingen friläggning och får vara lite mindre.
            transparent = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            min_lang = MIN_LANGSIDA * (0.8 if transparent else 1)
            if max(im.size) < min_lang or min(im.size) < MIN_KORTSIDA:
                return False
        mal.write_bytes(r.content)
        return True
    except Exception as e:
        log.debug("Kunde inte hämta %s: %s", url, e)
        return False


async def hamta_kandidater(sv: str, en: str, farskvara: bool, mapp: Path) -> list[Path]:
    """Nedladdade kandidater i tillräcklig upplösning (utan dubbletter)."""
    traffar = (await sok_urls(sv, en, farskvara))[: MAX_KANDIDATER * 2]
    # Källan står först i filnamnet ("off_se_03") så att betygsättningen vet varifrån bilden kom.
    mal = [mapp / f"{kalla}_{i:02d}" for i, (_, kalla) in enumerate(traffar)]
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as c:
        ok = await asyncio.gather(*(ladda_ner(c, u, m) for (u, _), m in zip(traffar, mal)))
    bilder, sedda = [], set()
    for m, lyckades in zip(mal, ok):
        if lyckades:
            h = hashlib.md5(m.read_bytes()).hexdigest()
            if h not in sedda:
                sedda.add(h)
                bilder.append(m)
    return bilder[:MAX_KANDIDATER]


def _avtryck(fil: Path) -> int:
    """64-bitars bildavtryck (medelvärdeshash av den frilagda bilden på grått)."""
    im = Image.open(fil).convert("RGBA")
    grund = Image.new("RGBA", im.size, (128, 128, 128, 255))
    grund.alpha_composite(im)
    liten = grund.convert("L").resize((8, 8), Image.LANCZOS)
    pix = list(liten.tobytes())
    medel = sum(pix) / 64
    return sum(1 << i for i, v in enumerate(pix) if v > medel)


def _avskuren(rgba: Image.Image, original: tuple[int, int] | None = None, grans: float = 0.04) -> bool:
    """Varan går ut över originalfotots kant (t.ex. halva tomater i bildkanten). Friläggningen
    beskär till varan, så mät mot originalets storlek: andelen synliga pixlar längs ytterkanterna."""
    a = rgba.getchannel("A")
    b, h = a.size
    kanter = [a.crop((0, 0, b, 2)), a.crop((0, h - 2, b, h)), a.crop((0, 0, 2, h)), a.crop((b - 2, 0, b, h))]
    synliga = sum(sum(1 for v in k.tobytes() if v > 128) for k in kanter)
    totalt = sum(k.size[0] * k.size[1] for k in kanter)
    if synliga / totalt <= grans:
        return False
    if original is None:
        return True
    # Friläggningen beskär till varan med lite marginal: når den ändå (nästan) hela fotots bredd
    # eller höjd, så fortsätter varan utanför fotot.
    return b >= 0.95 * original[0] or h >= 0.95 * original[1]


def _lika(a: int, b: int) -> bool:
    return bin(a ^ b).count("1") <= 6


FORRAD = konfig.DATA_DIR / "bildforrad"
FORRAD_DAGAR = 60


def _forrad_nyckel(namn: str) -> str:
    import minne
    return minne.nyckel(minne.synonym(namn))


def fran_forradet(namn: str, mapp: Path) -> list[Path]:
    """Bilder som nattjobbet redan har hittat, frilagt och kontrollerat (högst FORRAD_DAGAR gamla).
    Kopieras till ärendets mapp tillsammans med friläggningen, så att inget behöver göras om."""
    import json
    import shutil
    import time
    from video.frilagg import cache_fil
    d = FORRAD / _forrad_nyckel(namn)
    try:
        info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if time.time() - info.get("tid", 0) > FORRAD_DAGAR * 86400:
        return []
    ut = []
    for namn_fil in info.get("bilder", []):
        kalla = d / namn_fil
        if kalla.is_file() and cache_fil(kalla).is_file():
            mal = mapp / f"forrad_{namn_fil}"
            shutil.copy(kalla, mal)
            shutil.copy(cache_fil(kalla), cache_fil(mal))
            ut.append(mal)
    if ut:
        log.info("Bildval för %r: %d färdiga bilder från förrådet", namn, len(ut))
    return ut


def spara_i_forradet(namn: str, bilder: list[Path]) -> int:
    """Nattjobbet: sparar godkända bilder (och deras friläggning) i förrådet. Gamla filer ligger kvar."""
    import json
    import shutil
    import time
    from video.frilagg import cache_fil
    d = FORRAD / _forrad_nyckel(namn)
    d.mkdir(parents=True, exist_ok=True)
    stampel = time.strftime("%Y%m%d")
    sparade = []
    for i, b in enumerate(bilder):
        if b.is_file() and cache_fil(b).is_file():
            mal = d / f"{stampel}_{i}"
            shutil.copy(b, mal)
            shutil.copy(cache_fil(b), cache_fil(mal))
            sparade.append(mal.name)
    if sparade:
        (d / "info.json").write_text(json.dumps({"namn": namn, "tid": time.time(), "bilder": sparade},
                                                ensure_ascii=False), encoding="utf-8")
    return len(sparade)


async def hamta_bilder(namn: str, mapp: Path, antal: int = 1, forrad: bool = True, lage=None,
                       onskat: int | None = None, utom: list[Path] | None = None,
                       bara_kandidater: bool = False, info: dict | None = None) -> list[Path]:
    """Godkända bilder, bästa först. Med antal > 1: en bild per OLIK variant (smak).
    Först förrådet (färdiga bilder från natten), annars sök nu. Tom lista = be om eget foto.
    lage(text) får lägesrapporter som appen visar.
    onskat: hur många alternativ (en produkt; standard 3). utom: bilder som redan visats ("Fler bilder"):
    de och bilder som liknar dem hoppas över.
    bara_kandidater: de bäst betygsatta bilderna direkt, utan friläggning (pappa väljer i appen och bara den
    valda klipps ut, med forbered()). info får {"farskvara": bool}."""
    utom = list(utom or [])
    import igenkanning   # här för att undvika cirkulär import

    def rapport(text: str) -> None:
        log.info("Läge: %s", text)
        if lage:
            lage(text)
    if forrad and antal == 1 and (fardiga := fran_forradet(namn, mapp)):
        rapport(f"Hittade färdiga bilder på {namn}.")
        return fardiga
    if not igenkanning.tillganglig():
        log.info("Ingen API-nyckel: använder inga nätbilder")
        return []
    if antal > 1:
        rapport(f"Söker bilder på olika smaker av {namn} …")
        smaker = await hamta_smaker(namn, mapp, antal)
        if smaker:
            return smaker
    from video.frilagg import cache_fil, form_ok, frilagg, proportion_ok
    rapport(f"Söker bilder på {namn} …")
    ord_ = await igenkanning.sokord(namn, antal)
    rapport(f"Söker på \"{ord_['en']}\" …")
    kandidater = await hamta_kandidater(ord_["sv"], ord_["en"], ord_["farskvara"], mapp)
    if not kandidater and ord_["en"] != namn:
        rapport(f"Hittade inga. Söker på \"{namn}\" i stället …")
        kandidater = await hamta_kandidater(namn, namn, ord_["farskvara"], mapp)
    rapport(f"Hittade {len(kandidater)} bilder. Väljer de snyggaste …")
    # Bakgrunden tas alltid bort (frilagg), så den ska inte fälla en annars bra bild; den räknas
    # bara som plus vid rangordningen. Friläggningen och formen kontrolleras efteråt.
    godkanda = await igenkanning.betygsatt(namn, kandidater, ord_["farskvara"], frilaggs=True)
    if info is not None:
        info["farskvara"] = ord_["farskvara"]
    if bara_kandidater and antal == 1:
        sedda = {p.name for p in utom}
        ut, avtr = [], [_avtryck(p) for p in utom if p.is_file()]
        for p, _ in godkanda:
            if p.name in sedda:
                continue
            try:
                a = _avtryck(p)
            except Exception:
                continue
            if any(_lika(a, x) for x in avtr):
                continue                        # samma bild igen (t.ex. beskuren och hel version)
            ut.append(p)
            avtr.append(a)
            if len(ut) >= (onskat or 4):
                break
        rapport(f"Hittade {len(ut)} bilder att välja mellan.")
        return ut
    # Nätbilder måste gå att frilägga snyggt – ingen ram runt en dålig bild – och
    # förpackningen måste ha rätt proportioner (inte "uppblåst" av perspektiv).
    # isnet tar ca 15-20 s per bild på Pi 4, så antalet försök är begränsat.
    if antal > 1:
        onskat = antal
    else:
        onskat = onskat or 3                    # en produkt: upp till 3 alternativ för "Annan bild"
    sedda_namn = {p.name for p in utom}
    godkanda = [(p, v) for p, v in godkanda if p.name not in sedda_namn]
    max_forsok = min(len(godkanda), 6 if antal > 1 else max(5, onskat + 3))
    klara: list[Path] = []
    avtrycken: list[int] = []
    for p in utom:                              # redan visade: liknande bilder räknas som dubbletter
        try:
            avtrycken.append(_avtryck(cache_fil(p) if cache_fil(p).is_file() else p))
        except Exception:
            pass
    varianter: set[str] = set()
    if not godkanda:
        rapport("Ingen bild var tillräckligt snygg.")
    for nr, (p, variant) in enumerate(godkanda[:max_forsok], 1):
        if len(klara) >= onskat:
            break
        rapport(f"Klipper ut bild {nr} av {min(len(godkanda), max_forsok)} …")
        if antal > 1 and variant and variant in varianter:
            continue                            # samma smak finns redan
        ut = await asyncio.to_thread(frilagg, p)
        if ut is None:
            continue
        # Förpackningar ska vara hela: inga hål, genomskinliga fläckar eller kluvna burkar.
        if not ord_["farskvara"] and not form_ok(Image.open(cache_fil(p)).convert("RGBA")):
            continue
        if ord_["farskvara"] and _avskuren(Image.open(cache_fil(p)).convert("RGBA"), Image.open(p).size):
            log.info("Färskvarubilden är avskuren vid bildkanten: %s", p.name)
            continue
        avtryck = _avtryck(cache_fil(p))
        if any(_lika(avtryck, a) for a in avtrycken):
            continue                            # samma bild en gång till (t.ex. beskuren och hel version)
        kontroll = await igenkanning.kontrollera_frilaggning(namn, cache_fil(p), ord_["farskvara"])
        if kontroll["ok"] and proportion_ok(ut, kontroll["forpackning"]):
            klara.append(p)
            avtrycken.append(avtryck)
            varianter.add(variant)
    log.info("Bildval för %r: %d frilagda och godkända (önskat %d)", namn, len(klara), onskat)
    return klara


async def forbered(namn: str, p: Path, farskvara: bool = False) -> bool:
    """Frilägger och kontrollerar en bild som pappa valt (samma krav som vid automatiskt val).
    Färdiga bilder från förrådet är redan kontrollerade."""
    import igenkanning
    from video.frilagg import cache_fil, form_ok, frilagg, proportion_ok
    if p.name.startswith("forrad_") and cache_fil(p).is_file():
        return True
    ut = await asyncio.to_thread(frilagg, p)
    if ut is None:
        return False
    rgba = Image.open(cache_fil(p)).convert("RGBA")
    if not farskvara and not form_ok(rgba):
        return False
    if farskvara and _avskuren(rgba, Image.open(p).size):
        return False
    kontroll = await igenkanning.kontrollera_frilaggning(namn, cache_fil(p), farskvara)
    return bool(kontroll["ok"] and proportion_ok(ut, kontroll["forpackning"]))


PER_SMAK = 3          # kandidater per smak (en gemensam betygsättning för alla)
MAX_MARKE = 14        # produkter från varumärkessökningen som betygsätts


def _tagg(text: str) -> str:
    """'Red Bull' -> 'red-bull', 'Monster Energy' -> 'monster-energy' (Open Food Facts taggar)."""
    return re.sub(r"[^0-9a-zåäö]+", "-", text.lower()).strip("-")


def _nyckel(text: str) -> str:
    return re.sub(r"[^0-9a-zåäö]", "", (text or "").lower())


MARKE_CACHE_DAGAR = 30


async def _off_marke(c: httpx.AsyncClient, marke: str) -> list[tuple[str, str, str]]:
    """(bild-URL, produktnamn, kod) för varumärkets produkter, mest skannade först.
    Listan sparas i data/cache i MARKE_CACHE_DAGAR dagar, eftersom Open Food Facts ofta svarar 503;
    en äldre sparad lista används hellre än ingen alls."""
    import json
    import time
    import konfig
    cache = konfig.CACHE_DIR / f"off_marke_{_tagg(marke)}.json"
    sparad = None
    if cache.exists():
        try:
            sparad = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            sparad = None
    if sparad and time.time() - sparad.get("tid", 0) < MARKE_CACHE_DAGAR * 86400:
        return [tuple(x) for x in sparad["produkter"]]
    ny = await _off_marke_hamta(c, marke)
    if ny:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"tid": time.time(), "produkter": ny}, ensure_ascii=False), encoding="utf-8")
        return ny
    if sparad:
        log.info("Open Food Facts svarar inte: använder sparad produktlista för %r", marke)
        return [tuple(x) for x in sparad["produkter"]]
    return []


async def _off_marke_hamta(c: httpx.AsyncClient, marke: str) -> list[tuple[str, str, str]]:
    params = {"brands_tags": _tagg(marke), "fields": "code,product_name,image_front_url",
              "page_size": 60, "sort_by": "unique_scans_n"}
    ut: list[tuple[str, str, str]] = []
    for land in ("se", "world"):            # Sverige först (svenska förpackningar), sedan hela världen
        r = None
        for forsok in range(4):                 # 503 är vanligt: vänta allt längre
            try:
                r = await c.get(f"https://{land}.openfoodfacts.org/api/v2/search", params=params)
            except httpx.HTTPError:
                r = None
            if r is not None and r.status_code not in (502, 503, 504):
                break
            await asyncio.sleep(3 + 5 * forsok)
        if r is None or r.status_code != 200:
            log.warning("OFF varumärkessök %s %s: %s", land, marke, r.status_code if r else "-")
            continue
        koder = {k for _, _, k in ut}
        for p in r.json().get("products", []):
            u, namn = p.get("image_front_url"), (p.get("product_name") or "").strip()
            if u and namn and str(p.get("code")) not in koder:
                ut.append((re.sub(r"\.\d+\.jpg$", ".full.jpg", u), namn, str(p.get("code"))))
    return ut


async def smaker_via_marke(namn: str, marke: str, mapp: Path, antal: int) -> list[Path]:
    import igenkanning
    from video.frilagg import cache_fil, form_ok, frilagg, proportion_ok
    async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as c:
        try:
            produkter = await _off_marke(c, marke)
        except Exception as e:
            log.warning("OFF varumärkessök: %s", e)
            produkter = []
        if not produkter:
            return []
        # Ett foto per produktnamn (samma namn finns ofta i flera storlekar/länder).
        unika, sedda_namn = [], set()
        for u, pnamn, kod in produkter:
            if _nyckel(pnamn) not in sedda_namn:
                sedda_namn.add(_nyckel(pnamn))
                unika.append((u, pnamn, kod))
        # AI:n väljer olika smaker ur namnlistan (bara text). Smaken avgörs alltså av produkten,
        # inte av vad bilden ser ut att föreställa – så samma smak kommer inte med två gånger.
        valda = await igenkanning.valj_smaker(namn, [n for _, n, _ in unika], antal)
        if valda:
            unika = [(unika[i][0], unika[i][1], v["smak"]) for v in valda for i in v["nr"]]
        else:
            unika = [(u, n, n) for u, n, _ in unika[: MAX_MARKE]]
        unika = unika[: MAX_MARKE + 4]
        mal = [mapp / f"m{i:02d}" for i in range(len(unika))]
        ok = await asyncio.gather(*(ladda_ner(c, u, m) for (u, _, _), m in zip(unika, mal)))
    kandidater = [(m, pnamn, smak) for m, lyckades, (_, pnamn, smak) in zip(mal, ok, unika) if lyckades]
    log.info("Varumärket %r: %d produkter, %d foton att bedöma: %s", marke, len(produkter), len(kandidater),
             [n for _, n, _ in kandidater])
    if len(kandidater) < 2:
        return []
    produktnamn = {m: n for m, n, _ in kandidater}
    smak_av = {m: s for m, _, s in kandidater}
    godkanda = await igenkanning.betygsatt(
        f"{namn} – olika smaker. Produktnamn per bild: " + "; ".join(
            f"bild {i + 1}: {n}" for i, (_, n, _) in enumerate(kandidater)),
        [m for m, _, _ in kandidater], False, bara_nordiska=False, frilaggs=True)
    klara: list[Path] = []
    tagna: set[str] = set()
    forsok = 0
    for p, ai_smak in godkanda:
        if len(klara) >= antal or forsok >= 8:
            break
        # Samma smak = samma valda smak (eller samma AI-smak/produktnamn om valet saknas).
        nycklar = {_nyckel(smak_av[p])} if valda else {_nyckel(ai_smak), _nyckel(produktnamn[p])} - {""}
        if nycklar & tagna:
            continue
        forsok += 1
        ut = await asyncio.to_thread(frilagg, p)
        if ut is None:
            continue
        # Egen, exakt formkontroll först (gratis): hål, genomskinliga fläckar, kluven burk.
        if not form_ok(Image.open(cache_fil(p)).convert("RGBA")):
            continue
        kontroll = await igenkanning.kontrollera_frilaggning(namn, cache_fil(p))
        if kontroll["ok"] and proportion_ok(ut, kontroll["forpackning"]):
            klara.append(p)
            tagna |= nycklar
            log.info("Vald smak: %s (%s)", produktnamn[p], ai_smak)
    log.info("Smakbilder via varumärket %r: %d av önskade %d", marke, len(klara), antal)
    return klara
OFF_PAUS = 4          # sekunder mellan smaksökningar (Open Food Facts begränsar söktakten)


async def hamta_smaker(namn: str, mapp: Path, antal: int) -> list[Path]:
    """En bild per OLIK smak: AI:n föreslår smaker som säljs i Sverige, varje smak söks för
    sig (Open Food Facts först, där finns produktfoton per smak), alla kandidater betygsätts
    i ett anrop och den bästa godkända bilden per smak friläggs och kontrolleras."""
    import igenkanning
    from video.frilagg import cache_fil, frilagg, proportion_ok
    marke, smaker = await igenkanning.varianter(namn, antal + 2)   # några extra om någon saknar bra bild

    # 1) Bäst: Open Food Facts produkter för varumärket – varje produkt är en egen smak med
    #    riktigt namn och framsidesfoto. Smaken avgörs av produkten, inte av en gissning.
    marke_bilder = await smaker_via_marke(namn, marke, mapp, antal)
    if len(marke_bilder) >= min(antal, 2):
        return marke_bilder
    if len(smaker) < 2:
        return marke_bilder
    async def ladda(traffar: list[tuple[str, str]], prefix: str, max_antal: int) -> list[Path]:
        mal = [mapp / f"{prefix}_{kalla}_{i:02d}" for i, (_, kalla) in enumerate(traffar)]
        async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as c:
            ok = await asyncio.gather(*(ladda_ner(c, u, m) for (u, _), m in zip(traffar, mal)))
        return [m for m, lyckades in zip(mal, ok) if lyckades][:max_antal]

    async def per_smak(j: int, v: dict) -> list[Path]:
        traffar = (await sok_urls(v["sok"], v["en"], False, off_forst=True))[: PER_SMAK * 3]
        return await ladda(traffar, f"s{j}", PER_SMAK)
    # En smak i taget med paus: Open Food Facts söktjänst svarar 503 vid många samtidiga sökningar.
    listor = []
    for j, v in enumerate(smaker):
        if j:
            await asyncio.sleep(OFF_PAUS)
        listor.append(await per_smak(j, v))
    kandidater, sedda = [], set()
    for lista in listor:
        for m in lista:
            h = hashlib.md5(m.read_bytes()).hexdigest()
            if h not in sedda:
                sedda.add(h)
                kandidater.append(m)
    log.info("Smaker %s: %s kandidater", [v["sok"] for v in smaker], [len(x) for x in listor])
    if sum(1 for x in listor if x) < antal:
        # Smaksökningen gav för lite (Open Food Facts klarar ibland inte långa sökningar):
        # sök på bara varumärket – träffarna är oftast olika smaker – och låt AI:n avgöra
        # vilken smak varje bild visar.
        await asyncio.sleep(OFF_PAUS)
        allmant = await ladda((await sok_urls(namn, namn, False, off_forst=True))[:MAX_KANDIDATER * 2], "g",
                              MAX_KANDIDATER - len(kandidater))
        for m in allmant:
            h = hashlib.md5(m.read_bytes()).hexdigest()
            if h not in sedda:
                sedda.add(h)
                kandidater.append(m)
        log.info("Allmän sökning på %r: %d kandidater till", namn, len(allmant))
    godkanda = await igenkanning.betygsatt(namn + " (olika smaker: " + ", ".join(v["sok"] for v in smaker) + ")",
                                           kandidater, False, bara_nordiska=False, frilaggs=True)
    klara: list[Path] = []
    tagna: set[str] = set()
    from video.frilagg import form_ok
    forsok = 0
    for p, ai_smak in godkanda:
        smak = p.name.split("_", 1)[0]            # "s2" = sökt smak, "g" = allmän sökning
        if smak == "g":
            smak = "ai:" + (ai_smak or p.name)    # smaken som AI:n såg på bilden
        if len(klara) >= antal or forsok >= 6:
            break
        if smak in tagna:
            continue
        forsok += 1
        ut = await asyncio.to_thread(frilagg, p)
        if ut is None or not form_ok(Image.open(cache_fil(p)).convert("RGBA")):
            continue
        kontroll = await igenkanning.kontrollera_frilaggning(namn, cache_fil(p))
        if kontroll["ok"] and proportion_ok(ut, kontroll["forpackning"]):
            klara.append(p)
            tagna.add(smak)
    log.info("Smakbilder för %r: %d av önskade %d", namn, len(klara), antal)
    return klara
