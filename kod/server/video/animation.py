"""Animerad produktvideo med 1-3 produkter (design A "Solsken").

Lagren ritas en gång med Pillow; ffmpeg animerar dem med uttryck per bildruta:
  - produkterna kommer in en och en (vänster, höger, mitten nerifrån) med en liten studs
  - de ställer sig i en grupp på en tänkt yta, mittersta störst och framför
  - därefter gungar de lätt; priset poppar in sist; glitter rullar; en glans sveper förbi
Format som skyltens övriga videor: 1080x1920, H.264, yuv420p, 30 fps, utan ljud."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from .bas import kor_ffmpeg
import logging
log = logging.getLogger("butiksbot.animation")
from .design import (B, GUL, H, KRAM, MAGENTA, MORK, _logga, _namn, bakgrund_stralar, namnetikett,
                     glitter, rosett)
from .frilagg import ORDNING, frilagg, harmonisera

FPS, LANGD = 30, 9      # LANGD = standard; varje annons kan ha egen längd (MIN_LANGD–MAX_LANGD s).
MIN_LANGD, MAX_LANGD = 6, 30
# 30 fps sedan 2026-11-13: halva jobbet för Pi:n (användarens val)
FADE = 0.5       # sekunder för in- och utgång (mot rosa)
ZOOM = 0.55      # sekunder för zoom-övergången
GLID_UT = 0.6    # sekunder för produkterna att glida ut ("glid")
MAX_PRODUKTER = 3
# Level 4.2 räcker till 60 fps; behålls så att 60 fps går att slå på igen.
# ultrafast (sedan 2026-11-14): ffmpeg tar ca 22 s i stället för 44 s per video. Filen blir större men det är
# bara förhandsvisningen: skyltens kopia kodas om ändå (vrids, veryfast crf 18) när annonsen publiceras.
KODNING = [
    "-r", str(FPS), "-c:v", "libx264", "-preset", "ultrafast",
    "-profile:v", "high", "-level:v", "4.2", "-pix_fmt", "yuv420p", "-color_range", "tv",
    "-crf", "21", "-maxrate", "5M", "-bufsize", "10M",
    "-movflags", "+faststart", "-an",
    "-threads", "3",               # högst 3 kärnor: kärna 0 är skyltens och musikens
]


@dataclass
class Plats:
    x: int          # mittpunkt
    golv: int       # var produkten "står" (underkant)
    maxh: int
    maxb: int
    fran: str       # "vanster" | "hoger" | "under"
    start: float    # när den börjar glida in
    djup: float     # 1.0 = främst, <1 = lite mörkare (längre bak)


# Layouten räknas ut från produkternas verkliga form (se placera()).
# Uppifrån: logga (ca 60-250) | produktgrupp som står på GOLV | prisbricka UNDER gruppen
# (täcker aldrig en produkt) | namn längst ner.
MARGINAL = 60                    # minsta avstånd mellan produkt och bildkant
GOLV = 1140                      # ytan gruppen står på
MITT_FRAMFOR = 30                # mittprodukten står lite längre fram (lägre)
OVERLAPP = 0.05                  # högst 5 % av den smalare produktens bredd
LAG_UPPLOSNING = 800             # produktbilder lägre än så räknas som små
MAX_UPPSKALNING = 2.0            # ... och förstoras högst så här mycket
PRIS_D = 470                     # prisbrickans minsta diameter (priset syns på håll)
PRIS_Y = GOLV + MITT_FRAMFOR + 40 + PRIS_D // 2
NAMN = (PRIS_Y + PRIS_D // 2 + 20, 1850)

# Per antal produkter, i ritordning (sist ritas överst = mittenprodukten vid 3).
HOJDER = {1: [880], 2: [800, 800], 3: [680, 680, 820]}
# Största bredd per produkt: runda/breda varor (frukt, påsar) får inte ta över bilden.
BREDDER = {1: [680], 2: [430], 3: [330, 330, 400]}
FRAN = {1: ["under"], 2: ["vanster", "hoger"], 3: ["vanster", "hoger", "under"]}
STARTER = {1: [0.25], 2: [0.20, 0.55], 3: [0.20, 0.50, 0.80]}
DJUP = {1: [1.0], 2: [1.0, 1.0], 3: [0.93, 0.93, 1.0]}
VANSTER_TILL_HOGER = {1: [0], 2: [0, 1], 3: [0, 2, 1]}


INNEHALL_TOPP, INNEHALL_BOTTEN = 280, 1850    # mellan loggan och nederkanten
NAMN_H = 230
PRIS_MAX_D = 560


# ---------- variation: varje annons ser lite olika ut (inom butikens stil) ----------
PALETTER = [("E53373", "971251"), ("F0508A", "A3175A"), ("D6286A", "7E0F45"), ("EC4C7E", "B21E5C"),
            ("E8417F", "8C1A5E")]
PALETTER_FYND = [("FF5C93", "B0124F"), ("FF6A9C", "C21A5E"), ("F84B88", "A30F49")]
VARIANT_VAL = {
    "palett": range(len(PALETTER)),
    "stralar": (18, 26, 34),
    "mitt_y": (760, 860, 960),
    "tander": (0, 16, 22, 30),
    "pris_x": (-110, 0, 110),
    "vinkel": (-10, -6, -3, 3, 6, 10),
    "fran": ("sidor", "under", "ovan"),
    "glitter": (14, 26, 40),
    "namnstil": ("text", "etikett"),
}


def ny_variant(senaste: dict | None = None, slump: random.Random | None = None) -> dict:
    """Slumpad kombination. Ingen egenskap blir samma som förra videons (när det finns alternativ)."""
    slump = slump or random.Random()
    senaste = senaste or {}
    v = {}
    for k, val in VARIANT_VAL.items():
        alt = [x for x in val if x != senaste.get(k)] or list(val)
        v[k] = slump.choice(alt)
    v["seed"] = slump.randrange(1, 10_000)
    return v


def lodrat(platser: list[Plats], pris_faktor: float = 1.0) -> dict:
    """Fördelar grupp, pris och namn lodrätt. När gruppen är låg (små bilder) centreras
    allt och priset får växa, så att det inte blir en tom yta ovanför produkterna."""
    grupp_topp = min(p.golv - p.maxh for p in platser)
    grupp_h = max(p.golv for p in platser) - grupp_topp
    d = PRIS_D * pris_faktor
    tillg = INNEHALL_BOTTEN - INNEHALL_TOPP
    ledigt = tillg - (grupp_h + 40 + d + 20 + NAMN_H)
    if ledigt < 0:
        # Priset är viktigast på håll: krymp hellre produktgruppen än brickan.
        s = (grupp_h + ledigt) / grupp_h
        for p in platser:
            p.maxh, p.maxb = round(p.maxh * s), round(p.maxb * s)
            p.x = round(B / 2 + (p.x - B / 2) * s)
            p.golv = round(grupp_topp + (p.golv - grupp_topp) * s)
        grupp_h = max(p.golv for p in platser) - grupp_topp
        ledigt = tillg - (grupp_h + 40 + d + 20 + NAMN_H)
    if ledigt > 0:
        okning = max(0, min(PRIS_MAX_D * pris_faktor - d, ledigt * 0.4))
        d += okning
        ledigt -= okning
    topp = INNEHALL_TOPP + max(0, ledigt) / 2
    flytt = round(topp - grupp_topp)
    for p in platser:
        p.golv += flytt
    botten = max(p.golv for p in platser)
    pris_y = botten + 40 + d / 2
    return {"pris_d": int(d), "pris_y": int(pris_y),
            "namn": (int(pris_y + d / 2 + 20), int(min(INNEHALL_BOTTEN, pris_y + d / 2 + 20 + NAMN_H)))}


def skala_grupp(platser: list[Plats], f: float, marginal: bool = True) -> None:
    """Hela produktgruppen större/mindre runt bildens mitt; aldrig närmare kanten än MARGINAL
    (marginal=False bara i tester av kvalitetskontrollen, för att göra en medvetet dålig video)."""
    vanster = min(p.x - p.maxb / 2 for p in platser)
    hoger = max(p.x + p.maxb / 2 for p in platser)
    halv = max(B / 2 - vanster, hoger - B / 2)
    f = min(f, (B / 2 - MARGINAL) / halv) if f > 1 and marginal else f
    topp = min(p.golv - p.maxh for p in platser)
    for p in platser:
        p.maxh, p.maxb = round(p.maxh * f), round(p.maxb * f)
        p.x = round(B / 2 + (p.x - B / 2) * f)
        p.golv = round(topp + (p.golv - topp) * f)


MIN_GRUPP_H = int(0.40 * H)      # gruppen tar alltid minst ca 40 % av skärmhöjden

# Hög (lösvikt/styckfrukt): två exemplar bak och ett framför, 20-30 % överlapp.
HOG_OVERLAPP = 0.25
HOG_LYFT = 0.32                  # de bakre står så här mycket högre (andel av höjden)
HOG_BREDD = 470                  # önskad bredd per exemplar innan anpassning
HOG_FRAN = ["vanster", "hoger", "under"]
HOG_DJUP = [0.92, 0.92, 1.0]
# Variation per exemplar så att det inte ser kopierat ut: (spegelvänd, grader, skala)
VARIATION_HOG = [(False, -5, 0.95), (True, 4, 0.92), (False, 0, 1.04)]
VARIATION_SAMMA = [(False, -2, 0.98), (False, 2, 0.98), (False, 0, 1.0)]   # förpackningar: aldrig spegla text
# Drycker (samma burk tre gånger): aldrig spegelvänd (texten), bara en grads vridning,
# lite olika storlek och höjd. De bakre mörkas via DJUP. Sista talet = höjdskillnad i px.
VARIATION_TRIO = [(False, -1.5, 0.96, -14), (False, 1.2, 0.93, 8), (False, 0, 1.0, 0)]
DJUP_TRIO = [0.88, 0.88, 1.0]


def variera(bild: Image.Image, spegel: bool, grader: float) -> Image.Image:
    if spegel:
        bild = ImageOps.mirror(bild)
    if grader:
        bild = bild.rotate(grader, resample=Image.BICUBIC, expand=True)
        bbox = bild.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
        bild = bild.crop(bbox) if bbox else bild
    return bild


def _lagupplost(bilder: list[Image.Image], h: list[float]) -> float:
    """Små bilder förstoras helst högst MAX_UPPSKALNING gånger (hela gruppen lika mycket)."""
    faktor = 1.0
    for i, b in enumerate(bilder):
        if b.height < LAG_UPPLOSNING:
            faktor = min(faktor, b.height * MAX_UPPSKALNING / h[i])
    return faktor


def placera_hog(bilder: list[Image.Image], skalor: list[float]) -> list[Plats]:
    """Tre exemplar i en liten hög: bakre vänster, bakre höger, främre i mitten."""
    ar = [b.width / b.height for b in bilder]
    w = HOG_BREDD
    # Minst MIN_GRUPP_H hög grupp, men aldrig närmare kanten än MARGINAL.
    w_for_hojd = MIN_GRUPP_H * ar[2] / ((1 + HOG_LYFT) * skalor[2])
    w = max(w * _lagupplost(bilder, [w / a for a in ar]), w_for_hojd)
    w_max = (B / 2 - MARGINAL) / (0.5 + (1 - HOG_OVERLAPP) / 2)
    w = min(w, w_max)
    dx = w * (1 - HOG_OVERLAPP) / 2
    platser = []
    for i, (x, fram) in enumerate([(B / 2 - dx, False), (B / 2 + dx, False), (B / 2, True)]):
        bi = w * skalor[i]
        hi = bi / ar[i]
        golv = GOLV + MITT_FRAMFOR - (0 if fram else round(w / ar[2] * HOG_LYFT))
        platser.append(Plats(round(x), golv, round(hi), round(bi) + 2, HOG_FRAN[i], STARTER[3][i], HOG_DJUP[i]))
    return platser


def placera(bilder: list[Image.Image], stil: str = "rad", skalor: list[float] | None = None) -> list[Plats]:
    """Platser för 1-3 produkter: rätt höjd, minst MARGINAL px till kanterna och
    högst OVERLAPP mellan grannar. Gruppen tar minst MIN_GRUPP_H på höjden – även om
    små bilder då måste förstoras mer än MAX_UPPSKALNING (stora lite mjuka produkter
    ser bättre ut än pyttesmå)."""
    n = len(bilder)
    skalor = skalor or [1.0] * n
    if stil == "hog" and n == 3:
        return placera_hog(bilder, skalor)
    h = [float(x) * skalor[i] for i, x in enumerate(HOJDER[n])]
    h = [x * _lagupplost(bilder, h) for x in h]
    offset = [MITT_FRAMFOR if n == 3 and i == 2 else 0 for i in range(n)]
    grupp_h = max(h[i] + offset[i] for i in range(n))
    if grupp_h < MIN_GRUPP_H:
        s = MIN_GRUPP_H / grupp_h
        h = [x * s for x in h]
    w = [h[i] * bilder[i].width / bilder[i].height for i in range(n)]
    for i in range(n):
        maxb = BREDDER[n][min(i, len(BREDDER[n]) - 1)] * skalor[i]
        if w[i] > maxb:
            h[i] *= maxb / w[i]
            w[i] = maxb
    ordning = VANSTER_TILL_HOGER[n]

    def total(ws: list[float]) -> float:
        tw = sum(ws[i] for i in ordning)
        return tw - sum(OVERLAPP * min(ws[a], ws[b]) for a, b in zip(ordning, ordning[1:]))

    tillg = B - 2 * MARGINAL
    if total(w) > tillg:
        s = tillg / total(w)
        h, w = [x * s for x in h], [x * s for x in w]
    x = B / 2 - total(w) / 2
    mitt: dict[int, float] = {}
    for k, idx in enumerate(ordning):
        if k:
            x -= OVERLAPP * min(w[idx], w[ordning[k - 1]])
        mitt[idx] = x + w[idx] / 2
        x += w[idx]
    return [Plats(round(mitt[i]), GOLV + offset[i],
                  round(h[i]), round(w[i]) + 2, FRAN[n][i], STARTER[n][i], DJUP[n][i])
            for i in range(n)]


GLID = 0.7      # sekunder för en inglidning


def layoutfel(produkter: list[dict], pris_mitt: tuple[int, int], pris_d: int) -> list[dict]:
    """Bottens egen, exakta kontroll av var allt hamnar (gratis, kräver ingen AI):
    produkt utanför bildkanten, eller prisbrickan över en produkt. Samma format som
    kvalitetskontrollens problem."""
    fel = []
    cx, cy = pris_mitt
    r = pris_d / 2 * 0.92                 # brickans tandade kant räknas inte
    for i, prod in enumerate(produkter):
        p, w, h = prod["plats"], prod["w"], prod["h"]
        x0, x1, y0, y1 = p.x - w / 2, p.x + w / 2, p.golv - h, p.golv
        if x0 < 0 or x1 > B or y0 < 0 or y1 > H:
            fel.append({"beskrivning": f"Produkt {i + 1} går utanför bildkanten (x {x0:.0f}–{x1:.0f}).",
                        "allvar": "allvarligt", "atgard": "mindre_produkt", "tips": "", "kalla": "egen"})
        nx, ny = min(max(cx, x0), x1), min(max(cy, y0), y1)      # närmaste punkt i produkten
        if (nx - cx) ** 2 + (ny - cy) ** 2 < (r * 0.85) ** 2:
            fel.append({"beskrivning": f"Prisbrickan täcker produkt {i + 1}.",
                        "allvar": "allvarligt", "atgard": "mindre_produkt", "tips": "", "kalla": "egen"})
    return fel


def ladda_produkt(foto: Path, modeller=ORDNING) -> tuple[Image.Image, bool]:
    """Frilagd produkt (True), eller fotot med rundade hörn om friläggningen inte går (False)."""
    ut = frilagg(foto, modeller)
    if ut is not None:
        return ut, True
    ut = Image.open(foto).convert("RGBA")
    m = Image.new("L", ut.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, ut.width - 1, ut.height - 1), radius=int(min(ut.size) * 0.06), fill=255)
    ut.putalpha(m)
    return ut, False


def produktbild(ut: Image.Image, maxb: int, maxh: int, djup: float) -> Image.Image:
    """Skalar produkten till sin plats och mörkar den lite om den står längre bak."""
    f = min(maxb / ut.width, maxh / ut.height)
    ut = ut.resize((max(1, int(ut.width * f)), max(1, int(ut.height * f))), Image.LANCZOS)
    if djup < 1:
        alfa = ut.getchannel("A")
        rgb = ImageEnhance.Brightness(ut.convert("RGB")).enhance(djup)
        rgb = ImageEnhance.Color(rgb).enhance(0.95)
        ut = rgb.convert("RGBA")
        ut.putalpha(alfa)
    return ut


def kontaktskugga(bredd: int) -> Image.Image:
    """Skugga som om produkten står på en yta: en tät, mörk kontaktskugga precis
    under botten plus en mjuk, bredare skugga runt omkring."""
    w, h = int(bredd * 1.8), int(bredd * 0.6)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mjuk = Image.new("RGBA", img.size, (0, 0, 0, 0))
    cx, cy = w / 2, h / 2
    ImageDraw.Draw(mjuk).ellipse((cx - bredd * 0.62, cy - bredd * 0.09, cx + bredd * 0.62, cy + bredd * 0.09),
                                 fill=(35, 0, 18, 110))
    img.alpha_composite(mjuk.filter(ImageFilter.GaussianBlur(bredd * 0.08)))
    tat = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(tat).ellipse((cx - bredd * 0.46, cy - bredd * 0.035, cx + bredd * 0.46, cy + bredd * 0.035),
                                fill=(25, 0, 12, 200))
    img.alpha_composite(tat.filter(ImageFilter.GaussianBlur(max(2, bredd * 0.018))))
    return img


def glans() -> Image.Image:
    """Diagonal ljusstrimma som sveper över bilden."""
    w, h = 420, 2600
    band = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(band)
    for x in range(w):
        v = int(55 * (1 - abs(x - w / 2) / (w / 2)) ** 2)
        d.line((x, 0, x, h), fill=v)
    img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    img.putalpha(band)
    return img.rotate(-22, expand=True, resample=Image.BICUBIC)


def bygg_lager(fotos: list[Path], namn: str, pris: str, fynd: bool, mapp: Path,
               exemplar: int = 1, stil: str = "rad",
               overgang: tuple[str, str] = ("fade", "fade"), glid_hoger: bool = True,
               justering: dict | None = None, variant: dict | None = None) -> dict:
    """exemplar > 1 med ett enda foto: samma vara visas flera gånger (en hög frukt,
    "2 för 30"), med lite variation så att det inte ser kopierat ut."""
    fotos = fotos[:MAX_PRODUKTER]
    duplicerad = len(fotos) == 1 and exemplar > 1
    if duplicerad:
        fotos = fotos * min(exemplar, MAX_PRODUKTER)
    else:
        stil = "rad" if len(fotos) > 1 else stil
    if len(fotos) != 3 and stil in ("hog", "trio"):
        stil = "rad"
    mapp.mkdir(parents=True, exist_ok=True)
    v = variant or {"palett": 0, "stralar": 26, "mitt_y": 860, "tander": 22, "pris_x": 0, "vinkel": 8,
                    "fran": "sidor", "glitter": 26, "seed": 7}
    spec = {"produkter": [], "mapp": mapp, "overgang": tuple(overgang),
            "glid_tecken": 1 if glid_hoger else -1, "variant": v}

    topp, botten = (PALETTER_FYND[v["palett"] % len(PALETTER_FYND)] if fynd else PALETTER[v["palett"] % len(PALETTER)])
    bg = bakgrund_stralar(topp, botten, mitt=(540, v["mitt_y"]), antal=v["stralar"], seed=v["seed"])
    bg.convert("RGB").save(mapp / "bg.png")
    # Videon tonar in från och ut till bakgrundens rosa medelfärg, så att bytet till
    # nästa skyltvideo (som oftast börjar/slutar på en rosa bakgrund) blir mjukt.
    spec["fadefarg"] = "0x%02X%02X%02X" % tuple(round(v) for v in ImageStat.Stat(bg.convert("RGB")).mean)
    logga = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    _logga(logga, 165)
    logga.save(mapp / "logga.png")
    glitter(seed=v["seed"] + 1, antal=v["glitter"]).save(mapp / "glitter.png")
    glans().save(mapp / "glans.png")

    # Justeringar från kvalitetskontrollen: {"produkt": 1.12, "pris": 1.12, "modeller": (...)}
    justering = justering or {}
    laddade = [ladda_produkt(f, justering.get("modeller", ORDNING)) for f in fotos]
    # Samma ljus och färg för alla frilagda produkter i videon.
    frilagda = [im for im, ok in laddade if ok]
    harm = iter(harmonisera(frilagda))
    bilder = [next(harm) if ok else im for im, ok in laddade]
    # Små bilder (under LAG_UPPLOSNING px höga) – boten ber då om en större.
    spec["sma"] = sorted({0} if duplicerad and any(b.height < LAG_UPPLOSNING for b in bilder)
                         else {i for i, b in enumerate(bilder) if b.height < LAG_UPPLOSNING})
    skalor = None
    if duplicerad:
        variation = {"hog": VARIATION_HOG, "trio": VARIATION_TRIO}.get(stil, VARIATION_SAMMA)
        bilder = [variera(b, *variation[i][:2]) for i, b in enumerate(bilder)]
        skalor = [variation[i][2] for i in range(len(bilder))]
    platser = placera(bilder, "rad" if stil == "trio" else stil, skalor)
    if stil == "trio":
        # Som Monster-gruppen (mitten större och framför), plus lite höjdskillnad.
        for i, p in enumerate(platser):
            p.golv += VARIATION_TRIO[i][3]
            p.djup = DJUP_TRIO[i]
    if justering.get("produkt", 1.0) != 1.0:
        skala_grupp(platser, justering["produkt"], not justering.get("test_utan_marginal"))
    lod = lodrat(platser, justering.get("pris", 1.0))
    for p in platser:      # bara för tester: en medvetet dålig video (produkt utanför kanten)
        p.x += justering.get("test_flytta_x", 0)
    if overgang[0] == "glid":
        # Alla produkter kommer från samma sida (och glider ut åt andra hållet).
        for p in platser:
            p.fran = "vanster" if glid_hoger else "hoger"
    elif v["fran"] in ("under", "ovan"):
        for p in platser:              # variant: alla kommer underifrån, eller faller ner ovanifrån
            p.fran = v["fran"]

    namnlager = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    if v.get("namnstil") == "etikett":
        namnetikett(namnlager, namn, *lod["namn"], KRAM, MAGENTA)
    else:
        _namn(namnlager, namn, *lod["namn"], KRAM, 7, MORK)
    namnlager.save(mapp / "namn.png")
    # Fynd = gul bricka, vanligt erbjudande = krämvit. Brickan ligger under gruppen.
    farg = (GUL, (160, 10, 70), (160, 10, 70)) if fynd else (KRAM, MAGENTA, MAGENTA)
    rosett(pris, lod["pris_d"], *farg, tander=v["tander"]).rotate(v["vinkel"], Image.BICUBIC, expand=True).save(mapp / "pris.png")
    # Brickan lite åt sidan (variant), men aldrig närmare kanten än marginalen.
    halv = lod["pris_d"] // 2 + 40
    px = min(max(B // 2 + v["pris_x"], MARGINAL + halv), B - MARGINAL - halv)
    spec["pris"] = (px, lod["pris_y"])

    for i, (bild, p) in enumerate(zip(bilder, platser)):
        prod = produktbild(bild, p.maxb, p.maxh, p.djup)
        prod.save(mapp / f"prod{i}.png")
        kontaktskugga(prod.width).save(mapp / f"skugga{i}.png")
        spec["produkter"].append({"plats": p, "w": prod.width, "h": prod.height})

    spec["layout"] = layoutfel(spec["produkter"], spec["pris"], lod["pris_d"])
    sista = max(p.start for p in platser)
    spec["pris_tid"] = sista + GLID + 0.25
    spec["namn_tid"] = spec["pris_tid"] + 0.35
    return spec


def _ease(start: float) -> str:
    """easeOutBack 0->1 (liten studs förbi målet) som ffmpeg-uttryck."""
    p = f"clip((t-{start})/{GLID},0,1)"
    return f"(1+2.4*pow({p}-1,3)+1.4*pow({p}-1,2))"


def filtergraf(spec: dict) -> tuple[list[str], str]:
    LANGD = spec.get("langd") or globals()["LANGD"]
    m = spec["mapp"]
    infiler = ["bg.png", "glitter.png", "logga.png", "namn.png", "pris.png", "glans.png"]
    for i in range(len(spec["produkter"])):
        infiler += [f"skugga{i}.png", f"prod{i}.png"]
    args: list[str] = []
    for f in infiler:
        args += ["-i", str(m / f)]

    # Varje stillbild avkodas en gång och upprepas i minnet (loop-filtret).
    def stilla(idx: int, namn: str, fmt: str = "yuva420p") -> str:
        return f"[{idx}:v]format={fmt},loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB[{namn}]"

    g = [stilla(0, "bg", "yuv420p"), stilla(1, "gl"), stilla(2, "lo"), stilla(3, "na0"),
         stilla(5, "sh")]
    g.append(f"[4:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB[pr0]")
    g.append(f"[na0]fade=t=in:st={spec['namn_tid']:.2f}:d=0.5:alpha=1[na]")
    g.append("[bg][gl]overlay=x=0:y='-mod(t*45,1920)'[v0]")
    g.append("[v0][lo]overlay=0:0[v1]")
    sist = "v1"

    ing, utg = spec["overgang"]
    if utg == "glid":
        t0 = LANGD - 0.3 - GLID_UT
        ut = f"+{spec['glid_tecken'] * 1500}*pow(clip((t-{t0:.2f})/{GLID_UT},0,1),2)"
    else:
        ut = ""

    for i, prod in enumerate(spec["produkter"]):
        p: Plats = prod["plats"]
        e = _ease(p.start)
        dx = {"vanster": -1100, "hoger": 1100, "under": 0, "ovan": 0}[p.fran]
        # helt under bildkanten innan den glider upp, eller ovanför och faller ner (studsar med easeOutBack)
        dy = {"under": 2000, "ovan": -2000}.get(p.fran, 0)
        x = f"{p.x}-w/2+(1-{e})*({dx}){ut}"
        # Lätt gung när produkten har landat: lyfter några pixlar i otakt med de andra.
        gung = f"7*(1-cos(2*PI*(t-{p.start + GLID:.2f})/2.6+{i * 1.9:.1f}))/2*clip((t-{p.start + GLID:.2f})/0.6,0,1)"
        y = f"{p.golv}-h+(1-{e})*({dy})-{gung}"
        sidx, pidx = 6 + 2 * i, 7 + 2 * i
        g.append(stilla(sidx, f"s{i}a"))
        g.append(f"[s{i}a]fade=t=in:st={p.start + 0.25:.2f}:d=0.45:alpha=1[s{i}]")
        g.append(stilla(pidx, f"p{i}"))
        g.append(f"[{sist}][s{i}]overlay=x='{p.x}-w/2+(1-{e})*({dx}){ut}':y={p.golv}-h/2[a{i}]")
        g.append(f"[a{i}][p{i}]overlay=x='{x}':y='{y}'[b{i}]")
        sist = f"b{i}"

    tp = spec["pris_tid"]
    s = (f"if(lt(t,{tp}),0.02,(1-exp(-5*(t-{tp}))*cos(9*(t-{tp}))))"
         f"*(1+0.025*sin(2*PI*(t-{tp})/1.3)*gte(t,{tp}+0.9))")
    cx, cy = spec["pris"]
    g.append(f"[pr0]scale=w='max(2,trunc(iw*{s}/2)*2)':h='max(2,trunc(ih*{s}/2)*2)':eval=frame,format=yuva420p[pr]")
    g.append(f"[{sist}][pr]overlay=x='{cx}-w/2{ut}':y='{cy}-h/2':enable='gte(t,{tp})'[c0]")
    g.append(f"[c0][na]overlay=x='0{ut}':y=0[c1]")
    # Glans: sveper över bilden två gånger.
    g.append(f"[c1][sh]overlay=x='-900+mod(t-{tp + 0.6:.2f},4.5)*700':y=-300:"
             f"enable='gte(t,{tp + 0.6:.2f})*lt(mod(t-{tp + 0.6:.2f},4.5),2.9)'[c2]")
    g += overgangar_graf("c2", "ut", spec["fadefarg"], ing, utg, LANGD)
    return args, ";".join(g)


def overgangar_graf(inn: str, ut: str, farg: str, ing: str, utg: str, LANGD: float = LANGD) -> list[str]:
    """In- och utgång mot den rosa färgen `farg`. Alla börjar och slutar helt rosa.
    Strömmen klipps till LANGD här, eftersom xfade och concat behöver en ändlig ström."""
    tb = f"fps={FPS},settb=1/{FPS},setsar=1"
    g = [f"[{inn}]format=yuv420p,trim=duration={LANGD},setpts=PTS-STARTPTS,{tb}[k0]"]

    def rosa(namn: str, d: float) -> str:
        return f"color=c={farg}:s={B}x{H}:r={FPS}:d={d:.3f},format=yuv420p,{tb}[{namn}]"

    def zoom(kalla: str, mal: str, inat: bool) -> None:
        """Zoom-del (huvud eller svans) skalad mot mitten över rosa."""
        lt = f"(t/{ZOOM})" if inat else f"(1-t/{ZOOM})"
        s = f"(0.3+0.7*(1-pow(1-{lt},3)))"
        fd = f"fade=t=in:st=0:d={ZOOM * 0.6:.2f}:alpha=1" if inat else              f"fade=t=out:st={ZOOM * 0.4:.2f}:d={ZOOM * 0.6:.2f}:alpha=1"
        g.append(f"[{kalla}]format=yuva420p,scale=w='max(2,trunc({B}*{s}/2)*2)':"
                 f"h='max(2,trunc({H}*{s}/2)*2)':eval=frame,{fd}[{mal}s]")
        g.append(rosa(f"{mal}r", ZOOM))
        g.append(f"[{mal}r][{mal}s]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass,format=yuv420p,{tb}[{mal}]")

    # In
    if ing in ("wipe", "cirkel"):
        g.append(rosa("ri", FADE))
        trans = {"wipe": "wiperight", "cirkel": "circleopen"}[ing]
        g.append(f"[ri][k0]xfade=transition={trans}:duration={FADE}:offset=0,{tb}[k1]")
    elif ing == "zoom":
        g.append("[k0]split[za][zb]")
        g.append(f"[za]trim=duration={ZOOM},setpts=PTS-STARTPTS[zh]")
        zoom("zh", "zi", True)
        g.append(f"[zb]trim=start={ZOOM},setpts=PTS-STARTPTS,{tb}[zt]")
        g.append(f"[zi][zt]concat=n=2:v=1:a=0,{tb}[k1]")
    else:   # fade, glid (produkterna glider redan in; kort tonning från rosa)
        d = FADE if ing == "fade" else 0.3
        g.append(f"[k0]fade=t=in:st=0:d={d}:color={farg}[k1]")

    # Ut
    if utg in ("wipe", "cirkel"):
        g.append(rosa("ru", FADE))
        trans = {"wipe": "wiperight", "cirkel": "circleclose"}[utg]
        g.append(f"[k1][ru]xfade=transition={trans}:duration={FADE}:offset={LANGD - FADE},format=yuv420p[{ut}]")
    elif utg == "zoom":
        g.append("[k1]split[ya][yb]")
        g.append(f"[ya]trim=duration={LANGD - ZOOM},setpts=PTS-STARTPTS,{tb}[yh]")
        g.append(f"[yb]trim=start={LANGD - ZOOM},setpts=PTS-STARTPTS[yt0]")
        zoom("yt0", "yu", False)
        g.append(f"[yh][yu]concat=n=2:v=1:a=0,format=yuv420p[{ut}]")
    else:
        d = FADE if utg == "fade" else 0.3
        g.append(f"[k1]fade=t=out:st={LANGD - d}:d={d}:color={farg},format=yuv420p[{ut}]")
    return g


_hemserver_nere = {"tid": 0.0}


async def _rendera_hemserver(fotos: list[Path], ut: Path, param: dict) -> dict | None:
    """Renderar på hemserverns bildtjänst (BILDSERVER_URL/BILDSERVER_NYCKEL). None om den inte svarar:
    då renderar Pi:n själv (och provar hemservern igen om 5 min)."""
    import base64
    import json
    import os
    url = os.environ.get("BILDSERVER_URL", "").strip().rstrip("/")
    nyckel = os.environ.get("BILDSERVER_NYCKEL", "").strip()
    if not url or not nyckel or time.time() - _hemserver_nere["tid"] < 300:
        return None
    try:
        import httpx
        t0 = time.time()
        filer = [("fotos", (f"foto{i}{Path(f).suffix}", Path(f).read_bytes(), "application/octet-stream"))
                 for i, f in enumerate(fotos)]
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0)) as c:
            r = await c.post(f"{url}/render", headers={"X-Nyckel": nyckel},
                             data={"param": json.dumps(param, default=list)}, files=filer)
        r.raise_for_status()
        info = json.loads(base64.b64decode(r.headers["X-Info"]).decode())
        tmp = ut.with_name(ut.name + ".hem.part")
        tmp.write_bytes(r.content)
        tmp.replace(ut)
        info["video"] = ut
        info["overgang"] = tuple(info.get("overgang") or ())
        log.info("Video renderad på hemservern på %.1f s (%s)", time.time() - t0, ut.name)
        return info
    except Exception as e:
        _hemserver_nere["tid"] = time.time()
        log.warning("Hemservern kunde inte rendera (%s): Pi:n renderar själv i 5 min", type(e).__name__)
        return None


async def rendera(fotos: list[Path], namn: str, pris: str, fynd: bool, ut: Path,
                  exemplar: int = 1, stil: str = "rad",
                  overgang: tuple[str, str] = ("fade", "fade"), glid_hoger: bool = True,
                  justering: dict | None = None, variant: dict | None = None, langd: float | None = None) -> dict:
    """langd: videons längd i sekunder (standard LANGD = 9). {'video': Path, 'sma': [index för bilder i låg upplösning], 'tider': (lager, ffmpeg)}
    Hemservern först (snabbare), annars här på Pi:n."""
    param = {"namn": namn, "pris": pris, "fynd": fynd, "exemplar": exemplar, "stil": stil,
             "overgang": list(overgang), "glid_hoger": glid_hoger, "justering": justering or {},
             "variant": variant, "langd": langd}
    hem = await _rendera_hemserver(list(fotos), ut, param)
    if hem is not None:
        return hem
    return await rendera_har(fotos, namn, pris, fynd, ut, exemplar, stil, overgang, glid_hoger, justering, variant, langd)


async def rendera_har(fotos: list[Path], namn: str, pris: str, fynd: bool, ut: Path,
                      exemplar: int = 1, stil: str = "rad",
                      overgang: tuple[str, str] = ("fade", "fade"), glid_hoger: bool = True,
                      justering: dict | None = None, variant: dict | None = None, langd: float | None = None) -> dict:
    """Renderar på den här datorn (Pi:n, eller hemservern själv)."""
    t0 = time.time()
    # Friläggning och Pillow-ritning tar tid: kör i en tråd så att boten svarar under tiden.
    spec = await asyncio.to_thread(bygg_lager, fotos, namn, pris, fynd, ut.parent / f"lager_{ut.stem}",
                                   exemplar, stil, overgang, glid_hoger, justering, variant)
    t1 = time.time()
    langd = max(MIN_LANGD, min(MAX_LANGD, float(langd or LANGD)))
    spec["langd"] = langd
    args, graf = filtergraf(spec)
    await kor_ffmpeg([*args, "-filter_complex", graf, "-map", "[ut]", "-t", str(langd), *KODNING, str(ut)])
    return {"video": ut, "sma": spec["sma"], "overgang": spec["overgang"], "layout": spec["layout"], "variant": spec["variant"],
            "langd": langd, "tider": (t1 - t0, time.time() - t1)}
