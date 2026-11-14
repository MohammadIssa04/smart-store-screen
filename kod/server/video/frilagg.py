"""Friläggning av produktbilder (rembg:s modeller, körda direkt med onnxruntime).

Ordning:
  1. Bilden har redan transparent bakgrund -> används som den är.
  2. isnet-general-use (ca 15 s på Pi 4, under 1 GB minne) – bäst kanter.
  3. u2netp (ca 2 s) – reserv.
birefnet-general-lite testades men kräver ca 7 GB minne på Pi:n och används inte.

Varje resultat kontrolleras (andel, kant, fyllnad). Ett godkänt resultat
"fräschas upp" (ljus, kontrast, mättnad, skärpa) och sparas som
<foto>.frilagd.png så att friläggningen bara görs en gång per bild."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

import konfig

log = logging.getLogger("butiksbot.frilagg")

ASSETS = konfig.HEM / "assets"
# namn: (fil, medel, std, storlek, sigmoid)
MODELLER = {
    "isnet-general-use": ("isnet-general-use.onnx", (0.5, 0.5, 0.5), (1.0, 1.0, 1.0), 1024, False),
    "u2netp": ("u2netp.onnx", (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 320, False),
}
ORDNING = ("isnet-general-use", "u2netp")
MIN_FYLLNAD = 0.42      # uppmätt: vit burk där bara loggan togs 0,15-0,34; hel burk 0,93; bananklase 0,52
_sessioner: dict = {}


def _sess(namn: str):
    if namn not in _sessioner:
        import onnxruntime as ort
        import konfig
        konfig.lag_prioritet()      # friläggningstråden: nice 19, ionice idle, kärna 1-3
        so = ort.SessionOptions()
        so.intra_op_num_threads = konfig.RENDER_TRADAR
        so.inter_op_num_threads = 1
        _sessioner[namn] = ort.InferenceSession(str(ASSETS / MODELLER[namn][0]), so,
                                                providers=["CPUExecutionProvider"])
    return _sessioner[namn]


def mask(img: Image.Image, modell: str = "u2netp") -> np.ndarray:
    """Förgrundsmask 0..1 i bildens storlek."""
    _, medel, std, sz, sigmoid = MODELLER[modell]
    rgb = img.convert("RGB")
    a = np.asarray(rgb.resize((sz, sz), Image.LANCZOS)).astype(np.float32)
    a = a / max(float(a.max()), 1e-6)
    a = (a - np.array(medel)) / np.array(std)
    a = a.transpose(2, 0, 1)[None].astype(np.float32)
    s = _sess(modell)
    ut = s.run(None, {s.get_inputs()[0].name: a})[0][0, 0]
    if sigmoid:
        ut = 1 / (1 + np.exp(-ut))
    ut = (ut - ut.min()) / (ut.max() - ut.min() + 1e-6)
    m = Image.fromarray((ut * 255).astype(np.uint8)).resize(rgb.size, Image.LANCZOS)
    return np.asarray(m).astype(np.float32) / 255.0


def _godkand(m: np.ndarray, modell: str) -> bool:
    andel = float((m > 0.5).mean())
    kant = np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]])
    kantandel = float((kant > 0.5).mean())
    ys, xs = np.where(m > 0.5)
    # Fyllnad = hur stor del av det frilagda området (bbox) som täcks. Låg fyllnad betyder
    # oftast att modellen bara tog en logga eller ett mönster (t.ex. Monster-klon på en vit burk).
    fyllnad = float(len(ys) / ((np.ptp(ys) + 1) * (np.ptp(xs) + 1))) if len(ys) else 0.0
    ok = 0.04 < andel < 0.88 and kantandel <= 0.45 and fyllnad >= MIN_FYLLNAD
    log.info("%s: andel %.2f kant %.2f fyllnad %.2f -> %s", modell, andel, kantandel, fyllnad,
             "ok" if ok else "förkastad")
    return ok


def _transparent(img: Image.Image) -> Image.Image | None:
    """Bilder som redan har genomskinlig bakgrund (t.ex. PNG-packshots)."""
    if img.mode not in ("RGBA", "LA", "P"):
        return None
    rgba = img.convert("RGBA")
    a = np.asarray(rgba.getchannel("A"))
    if (a < 10).mean() > 0.05 and (a > 245).mean() > 0.05:
        return rgba
    return None


def fraschna(rgba: Image.Image) -> Image.Image:
    """Mild uppfräschning. Fotots egna reflexer, skuggor och ljus ska vara kvar –
    bara en svag vitbalans, lite lyft i nivåerna och en aning skärpa."""
    alfa = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    arr = np.asarray(rgb).astype(np.float32)
    synlig = np.asarray(alfa) > 128
    if synlig.sum() > 100:
        pix = arr[synlig]
        lum = pix.mean(axis=1)
        # Vitbalans, max ±5 %: tar bort tydliga färgstick men behåller ljusets karaktär.
        ljusa = pix[lum >= np.percentile(lum, 80)]
        medel = ljusa.mean(axis=0)
        arr = arr * np.clip(medel.mean() / np.maximum(medel, 1), 0.95, 1.05)
        # Nivåer: lyft bara om bilden är tydligt mörk/blek, högst 10 %; skuggorna rörs inte.
        hi = np.percentile(arr[synlig].mean(axis=1), 99)
        if hi < 235:
            arr = arr * min(240 / max(hi, 1), 1.10)
        rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    rgb = ImageEnhance.Color(rgb).enhance(1.04)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
    ut = rgb.convert("RGBA")
    ut.putalpha(alfa)
    return ut


def mjuka_kanter(rgba: Image.Image) -> Image.Image:
    """Lätt feather: krymp masken en pixel (bort med bakgrundsfransar) och tona ut kanten,
    så att produkten inte ser urklippt ut."""
    alfa = rgba.getchannel("A")
    r = max(1, round(max(rgba.size) / 900))          # skalar med bildstorleken
    alfa = alfa.filter(ImageFilter.MinFilter(2 * r + 1)).filter(ImageFilter.GaussianBlur(1.2 * r))
    ut = rgba.copy()
    ut.putalpha(alfa)
    return ut


def lutning(rgba: Image.Image) -> float:
    """Produktens lutning i grader (0 = rak), från maskens huvudaxel."""
    a = np.asarray(rgba.getchannel("A")).astype(np.float32) / 255
    ys, xs = np.nonzero(a > 0.5)
    if len(xs) < 200:
        return 0.0
    x, y = xs - xs.mean(), ys - ys.mean()
    cxx, cyy, cxy = (x * x).mean(), (y * y).mean(), (x * y).mean()
    # Vinkel för huvudaxeln mot lodlinjen.
    theta = 0.5 * np.degrees(np.arctan2(2 * cxy, cyy - cxx))
    return float(theta)


def rata_upp(rgba: Image.Image) -> Image.Image:
    """Rätar upp en produkt som lutar lite (1-12°). Bara rotation – ingen förvrängning."""
    v = lutning(rgba)
    if not 1.0 <= abs(v) <= 12:
        return rgba
    log.info("Rätar upp produkten %.1f°", v)
    ut = rgba.rotate(-v, resample=Image.BICUBIC, expand=True)
    bbox = ut.getchannel("A").point(lambda p: 255 if p > 20 else 0).getbbox()
    return ut.crop(bbox) if bbox else ut


def proportion(rgba: Image.Image) -> float:
    """Höjd/bredd för den synliga produkten (efter upprätning)."""
    bbox = rgba.getchannel("A").point(lambda p: 255 if p > 128 else 0).getbbox()
    if not bbox:
        return 0.0
    return (bbox[3] - bbox[1]) / max(1, bbox[2] - bbox[0])


# Höjd/bredd för vanliga burkar (inklusive lock). Används för att upptäcka foton som är
# tagna snett eller för nära (burken ser då kort och "uppblåst" ut).
BURKAR = {
    "500 ml": 2.55,     # t.ex. Monster 50 cl: 168 x 66 mm
    "330 ml": 1.86,     # vanlig läskburk: 115 x 66 mm
    "330 ml smal": 2.60,
    "250 ml smal": 2.50,
    "355 ml smal": 2.75,
}


# Uppmätt 2026-11-12: hela burkar och frukt 1,00 / <1 % / 0; kluven burk 0,93-0,95 / 6-7 % / 0;
# burk med halva locket borta 0,71-0,80 / 9-23 % / 77-166 rader.
MIN_FORM_FYLL = 0.97      # andel täckt mellan vänster- och högerkant, rad för rad
MAX_FORM_HALVT = 0.03     # andel halvgenomskinligt (urtvättade fläckar)


def form(rgba: Image.Image) -> tuple[float, float, int]:
    """(fyllnad, halvgenomskinligt, glapp) för en frilagd produkt. Rad för rad mäts hur mycket
    av spannet mellan vänster- och högerkant som är täckt; glapp = tomma rader mitt i produkten."""
    a = np.asarray(rgba.getchannel("A")).astype(np.float32) / 255
    o = a > 0.5
    rader = np.where(o.any(axis=1))[0]
    if not len(rader):
        return 0.0, 1.0, 0
    fyll = halvt = vikt = 0.0
    glapp = 0
    for y in range(rader[0], rader[-1] + 1):
        xs = np.where(o[y])[0]
        if not len(xs):
            glapp += 1
            continue
        spann = a[y, xs[0]:xs[-1] + 1]
        fyll += float((spann > 0.5).sum())
        halvt += float(((spann > 0.15) & (spann < 0.85)).sum())
        vikt += len(spann)
    return fyll / vikt, halvt / vikt, glapp


def form_ok(rgba: Image.Image) -> bool:
    """False för trasiga friläggningar: hål, genomskinliga fläckar eller en kluven produkt.
    Används för förpackningar (burkar, flaskor, påsar), inte för klasar som har naturliga glapp."""
    fyll, halvt, glapp = form(rgba)
    ok = fyll >= MIN_FORM_FYLL and halvt <= MAX_FORM_HALVT and glapp == 0
    log.info("Form: fyllnad %.3f halvgenomskinligt %.3f glapp %d -> %s", fyll, halvt, glapp, "ok" if ok else "trasig")
    return ok


def proportion_ok(rgba: Image.Image, forpackning: str, tolerans: float = 0.12) -> bool:
    """True om formen stämmer med en riktig burk av den sorten (±12 %) eller sorten är okänd."""
    forvantad = BURKAR.get(forpackning)
    if not forvantad:
        return True
    p = proportion(rgba)
    ok = abs(p - forvantad) / forvantad <= tolerans
    log.info("Proportion %.2f mot %.2f (%s) -> %s", p, forvantad, forpackning, "ok" if ok else "fel")
    return ok


def cache_fil(foto: Path) -> Path:
    """Den rena friläggningen (utan justeringar) sparas bredvid fotot."""
    return foto.with_name(foto.name + ".mask.png")


def frilagg(foto: Path | Image.Image, modeller=ORDNING) -> Image.Image | None:
    """Frilagd RGBA-bild beskuren till produkten (mjuka kanter, mild uppfräschning), eller None."""
    if isinstance(foto, Path) and cache_fil(foto).exists():
        return fraschna(mjuka_kanter(rata_upp(Image.open(cache_fil(foto)).convert("RGBA"))))
    original = foto if isinstance(foto, Image.Image) else Image.open(foto)

    ut = _transparent(original)
    if ut is None:
        img = original.convert("RGB")
        if max(img.size) > 2000:
            img.thumbnail((2000, 2000), Image.LANCZOS)
        for modell in modeller:
            try:
                m = mask(img, modell)
            except Exception:
                log.exception("Friläggning med %s misslyckades", modell)
                continue
            m = np.clip((m - 0.45) / 0.3, 0, 1)          # skarpare kant, inga halvgenomskinliga rester
            if _godkand(m, modell):
                ut = img.copy()
                ut.putalpha(Image.fromarray((m * 255).astype(np.uint8)))
                break
    if ut is None:
        return None

    bbox = ut.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if not bbox:
        return None
    pad = 4   # luft så att mjuka kanter inte klipps
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(ut.width, bbox[2] + pad), min(ut.height, bbox[3] + pad))
    ut = ut.crop(bbox)
    if isinstance(foto, Path):
        ut.save(cache_fil(foto))
    return fraschna(mjuka_kanter(rata_upp(ut)))


def harmonisera(bilder: list[Image.Image]) -> list[Image.Image]:
    """Gör ljus och färg lika mellan produkterna i samma video, så att de ser ut att vara
    fotade tillsammans: samma vitbalans, ljushet och kontrast (mot gruppens median).
    Stegen är begränsade så att ingen produkt ändrar karaktär."""
    if len(bilder) < 2:
        return bilder
    stat = []
    for im in bilder:
        arr = np.asarray(im.convert("RGB")).astype(np.float32)
        syn = np.asarray(im.getchannel("A")) > 200
        pix = arr[syn] if syn.sum() > 100 else arr.reshape(-1, 3)
        lum = pix.mean(axis=1)
        # Vitbalansen mäts bara på NEUTRALA ljusa ytor (vitt, grått, silver, lock): en grön
        # eller blå burk får inte färga de andra. Saknas neutrala ytor hoppas vitbalansen över.
        mx, mn = pix.max(axis=1), pix.min(axis=1)
        neutral = (mx - mn) / np.maximum(mx, 1) < 0.12
        ljusa_neutrala = pix[neutral & (lum >= np.percentile(lum, 60))]
        vb = ljusa_neutrala.mean(axis=0) if len(ljusa_neutrala) > 0.01 * len(pix) else None
        stat.append({"vb": vb, "lo": np.percentile(lum, 5), "hi": np.percentile(lum, 95)})
    vbs = [s["vb"] / s["vb"].mean() for s in stat if s["vb"] is not None]
    mal_rel = np.median(vbs, axis=0) if vbs else None
    mal_lo = float(np.median([s["lo"] for s in stat]))
    mal_hi = float(np.median([s["hi"] for s in stat]))
    ut = []
    for im, s in zip(bilder, stat):
        arr = np.asarray(im.convert("RGB")).astype(np.float32)
        # Vitbalans: neutrala ytor ska få samma färgton i alla produkter (±6 %).
        if s["vb"] is not None and mal_rel is not None and len(vbs) > 1:
            rel = s["vb"] / s["vb"].mean()
            arr = arr * np.clip(mal_rel / rel, 0.94, 1.06)
        # Nivåer: flytta 5:e/95:e percentilen mot gruppens (förstärkning 0,85-1,18).
        skala = np.clip((mal_hi - mal_lo) / max(s["hi"] - s["lo"], 1), 0.85, 1.18)
        arr = (arr - s["lo"]) * skala + mal_lo
        rgb = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
        rgb.putalpha(im.getchannel("A"))
        ut.append(rgb)
    return ut
