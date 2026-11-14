"""Grafiska lager för skyltvideorna, ritade med Pillow.

Varje design bygger samma lager så att videon kan animera dem i ffmpeg:
  bg      RGB 1080x1920   bakgrund (gradient, strålar, bokeh, ram)
  text    RGBA 1080x1920  logga, etikett, produktnamn
  produkt RGBA + position frilagd produkt med skugga (eller rundad ram)
  pris    RGBA + mittpunkt prisbricka / prisskylt
  glitter RGBA 1080x3840  partiklar som kan rulla uppåt (övre = nedre halvan)
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import konfig

from .bas import typsnitt
from .frilagg import frilagg

B, H = 1080, 1920
FONTER = konfig.HEM / "assets" / "fonts"

KRAM = (255, 246, 236)          # krämvit som i "MIN BUTIK"-videon
MORK = (58, 10, 36)             # mörk aubergine (konturer)
MAGENTA = (214, 36, 110)
GUL = (255, 214, 64)


# ---------- typsnitt ----------

@lru_cache(maxsize=64)
def poppins(vikt: str, storlek: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTER / f"Poppins-{vikt}.ttf"), storlek, layout_engine=ImageFont.Layout.RAQM)


@lru_cache(maxsize=32)
def bitter(storlek: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTER / "Bitter[wght].ttf"), storlek, layout_engine=ImageFont.Layout.RAQM)
    try:
        f.set_variation_by_axes([900])
    except Exception:
        pass
    return f


@lru_cache(maxsize=32)
def arabisk(storlek: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(typsnitt()["arab"], storlek, layout_engine=ImageFont.Layout.RAQM)


def har_arabiska(s: str) -> bool:
    return any(0x0600 <= ord(c) <= 0x06FF or 0xFB50 <= ord(c) <= 0xFEFF for c in s)


def font_for(s: str, vikt: str, storlek: int) -> ImageFont.FreeTypeFont:
    return arabisk(storlek) if har_arabiska(s) else poppins(vikt, storlek)


def passa(text: str, fontfn, maxb: int, start: int, minst: int) -> ImageFont.FreeTypeFont:
    s = start
    while s > minst and fontfn(s).getlength(text) > maxb:
        s -= 4
    return fontfn(s)


def radbryt(text: str, fontfn, maxb: int, start: int, minst: int, maxrader: int = 2):
    """Största storlek där texten ryms på högst maxrader rader."""
    ord_ = text.split()
    for s in range(start, minst - 1, -4):
        f = fontfn(s)
        rader, rad = [], ""
        for o in ord_:
            test = f"{rad} {o}".strip()
            if not rad or f.getlength(test) <= maxb:
                rad = test
            else:
                rader.append(rad)
                rad = o
        rader.append(rad)
        if len(rader) <= maxrader and all(f.getlength(r) <= maxb for r in rader):
            return f, rader
    return fontfn(minst), [text]


def text_med_skugga(bild: Image.Image, xy, text, font, fyll, kant=0, kantfarg=MORK,
                    skugga=(0, 10), skuggalfa=110, ankare="mm"):
    lager = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lager)
    d.text((xy[0] + skugga[0], xy[1] + skugga[1]), text, font=font, fill=(30, 0, 15, skuggalfa),
           anchor=ankare, stroke_width=kant, stroke_fill=(30, 0, 15, skuggalfa))
    lager = lager.filter(ImageFilter.GaussianBlur(6))
    bild.alpha_composite(lager)
    ImageDraw.Draw(bild).text(xy, text, font=font, fill=fyll, anchor=ankare,
                              stroke_width=kant, stroke_fill=kantfarg)


# ---------- bakgrunder ----------

def _gradient(topp, botten) -> np.ndarray:
    t = np.linspace(0, 1, H)[:, None, None]
    return np.array(topp)[None, None] * (1 - t) + np.array(botten)[None, None] * t * np.ones((1, B, 1))


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bakgrund_stralar(topp: str, botten: str, mitt=(540, 860), antal=26, styrka=0.07,
                     seed=1, ljus=False) -> Image.Image:
    """Magenta-gradient med solstrålar, bokeh, hjärtan, gnistor och tunn ram."""
    g = _gradient(_hex(topp), _hex(botten))
    yy, xx = np.mgrid[0:H, 0:B]
    vinkel = np.arctan2(yy - mitt[1], xx - mitt[0])
    stralar = (np.floor((vinkel + np.pi) * antal / (2 * np.pi)) % 2 == 0)
    avst = np.hypot(yy - mitt[1], xx - mitt[0])
    glod = np.clip(1 - avst / 1100, 0, 1) ** 1.5
    g = g + 255 * (stralar * styrka)[..., None] + 255 * (0.18 * glod)[..., None]
    if not ljus:
        kant = np.clip((avst - 700) / 900, 0, 1)
        g = g * (1 - 0.25 * kant[..., None])
    bild = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGBA")
    _dekor(bild, seed, ljus)
    return bild


def bakgrund_ljus(seed=2) -> Image.Image:
    """Ljusrosa med prickmönster, som Monster-videon."""
    g = _gradient(_hex("FDE6F0"), _hex("F7C6DB"))
    bild = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(bild)
    for y in range(40, H, 70):
        for x in range(40 + (y // 70 % 2) * 35, B, 70):
            d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(236, 150, 186, 120))
    _dekor(bild, seed, ljus=True)
    return bild


def _dekor(bild: Image.Image, seed: int, ljus: bool) -> None:
    rnd = random.Random(seed)
    lager = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lager)
    vit = (255, 255, 255)
    for _ in range(14):                                     # bokeh
        r = rnd.randint(18, 60)
        x, y = rnd.randint(0, B), rnd.randint(0, H)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*vit, 22), outline=(*vit, 70), width=3)
    hjarta = ImageFont.truetype(typsnitt()["blandat"], 60)
    for _ in range(9):                                      # hjärtan
        s = rnd.randint(28, 64)
        f = hjarta.font_variant(size=s)
        farg = (236, 120, 170, 140) if ljus else (255, 190, 220, 90)
        d.text((rnd.randint(30, B - 30), rnd.randint(30, H - 30)), "♥", font=f, fill=farg, anchor="mm")
    bild.alpha_composite(lager.filter(ImageFilter.GaussianBlur(1)))
    ram = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    ImageDraw.Draw(ram).rounded_rectangle((24, 24, B - 25, H - 25), radius=40,
                                          outline=(255, 255, 255, 150 if not ljus else 200), width=3)
    bild.alpha_composite(ram)


def glitter(farg=(255, 246, 236), seed=3, antal=26) -> Image.Image:
    """1080x3840 med gnistor; övre och nedre halvan identiska så att den kan rulla sömlöst."""
    halva = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(halva)
    rnd = random.Random(seed)
    f0 = ImageFont.truetype(typsnitt()["blandat"], 40)
    for _ in range(antal):
        s = rnd.randint(18, 54)
        x, y = rnd.randint(40, B - 40), rnd.randint(40, H - 40)
        d.text((x, y), "✦", font=f0.font_variant(size=s), fill=(*farg, rnd.randint(120, 230)), anchor="mm")
    for _ in range(antal):
        r = rnd.randint(2, 5)
        x, y = rnd.randint(0, B), rnd.randint(0, H)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*farg, rnd.randint(90, 200)))
    hel = Image.new("RGBA", (B, 2 * H), (0, 0, 0, 0))
    hel.paste(halva, (0, 0))
    hel.paste(halva, (0, H))
    return hel


# ---------- former ----------

def piller(text: str, bg, fg, hojd=100, storlek=54) -> Image.Image:
    """Rundad etikett, bara svenska: 'ERBJUDANDE' / 'DAGENS FYND'."""
    fs = poppins("ExtraBold", storlek)
    bs = fs.getlength(text)
    bredd = int(bs + hojd * 1.3)
    p = Image.new("RGBA", (bredd + 30, hojd + 30), (0, 0, 0, 0))
    skugga = Image.new("RGBA", p.size, (0, 0, 0, 0))
    ImageDraw.Draw(skugga).rounded_rectangle((15, 21, bredd + 15, hojd + 21), radius=hojd // 2, fill=(30, 0, 15, 90))
    p.alpha_composite(skugga.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(p)
    d.rounded_rectangle((15, 15, bredd + 15, hojd + 15), radius=hojd // 2, fill=bg)
    d.text((15 + bredd / 2, 15 + hojd / 2), text, font=fs, fill=fg, anchor="mm")
    return p


def dela_pris(pris: str) -> tuple[str, str, str]:
    """'2 för 30 kr' -> ('2 för', '30', 'kr'), '19 kr' -> ('', '19', 'kr'), '50%' -> ('', '50%', '')."""
    over = ""
    m = re.match(r"(?i)^(\d+\s*för)\s+(.*)$", pris)
    if m:
        over, pris = m.group(1), m.group(2)
    # "19 kr" -> ('19', 'kr'); "10 kr/kg" -> ('10', 'kr/kg'); "5:-/st" -> ('5', ':-/st')
    m = re.match(r"(?i)^(.*?\d)\s*((?:kr|:-)(?:/\w+)?)$", pris)
    if m:
        return over, m.group(1), m.group(2)
    return over, pris, ""


def rosett(pris: str, diameter: int, fyll, textfarg, ring, over_extra: str = "", tander: int = 22) -> Image.Image:
    """Tandad prisbricka (som '19 kr utan pant' i Monster-videon), ritad i dubbel storlek."""
    k = 2
    D = diameter * k
    pad = 40 * k
    img = Image.new("RGBA", (D + 2 * pad, D + 2 * pad), (0, 0, 0, 0))
    c = D / 2 + pad
    R = D / 2
    form = Image.new("L", img.size, 0)
    df = ImageDraw.Draw(form)
    if tander:
        df.ellipse((c - R * 0.9, c - R * 0.9, c + R * 0.9, c + R * 0.9), fill=255)
    else:                                   # slät cirkel (variant)
        df.ellipse((c - R * 0.98, c - R * 0.98, c + R * 0.98, c + R * 0.98), fill=255)
    for i in range(tander):
        a = 2 * math.pi * i / tander
        x, y = c + R * 0.88 * math.cos(a), c + R * 0.88 * math.sin(a)
        r = R * 0.135 * (22 / tander) ** 0.8          # färre tänder = större bågar
        df.ellipse((x - r, y - r, x + r, y + r), fill=255)
    skugga = Image.new("RGBA", img.size, (30, 0, 15, 0))
    skugga.putalpha(form.point(lambda v: v * 0.5).filter(ImageFilter.GaussianBlur(14 * k)))
    img.alpha_composite(skugga, (0, 14 * k))
    farg = Image.new("RGBA", img.size, (*fyll, 255))
    img.paste(farg, (0, 0), form)
    d = ImageDraw.Draw(img)
    rr = R * 0.76
    d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=ring, width=5 * k)

    # "15 kr + pant": pantraden skrivs liten under priset.
    tillagg = ""
    m = re.search(r"(?i)\s*\+\s*pant\s*$", pris)
    if m:
        tillagg, pris = "+ pant", pris[:m.start()]
    over, stor, under = dela_pris(pris)
    over = over or over_extra
    maxb = R * 1.32
    fstor = passa(stor, lambda s: poppins("Black", s), int(maxb), int(R * (0.68 if tillagg else 0.95)), 40)
    hojd_stor = fstor.getbbox(stor, anchor="ls")[1] * -1
    y_stor = c + hojd_stor / 2 - (R * 0.08 if under and not over else 0) + (R * 0.1 if over and not under else 0)
    if over and under:
        y_stor += R * 0.04
    if tillagg:
        y_stor -= R * 0.2
    d.text((c, y_stor), stor, font=fstor, fill=textfarg, anchor="ms")
    if over:
        d.text((c, y_stor - hojd_stor - R * 0.06), over, font=poppins("ExtraBold", int(R * 0.24)),
               fill=textfarg, anchor="ms")
    if under:
        d.text((c, y_stor + R * 0.08), under, font=poppins("ExtraBold", int(R * 0.27)),
               fill=textfarg, anchor="mt")
    if tillagg:
        y = y_stor + R * (0.08 + 0.27 + 0.06 if under else 0.1)
        d.text((c, y), tillagg, font=poppins("Bold", int(R * 0.17)), fill=textfarg, anchor="mt")
    return img.resize((img.width // k, img.height // k), Image.LANCZOS)


def prisskylt(pris: str, bredd: int, hojd: int, fyll, textfarg, kant, vinkel=-5, rubrik="") -> Image.Image:
    """Klassisk svensk prisskylt: gul skylt, stort '19:-'."""
    k = 2
    W, Hh = bredd * k, hojd * k
    pad = 60 * k
    img = Image.new("RGBA", (W + 2 * pad, Hh + 2 * pad), (0, 0, 0, 0))
    ram = (pad, pad, pad + W, pad + Hh)
    sk = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sk).rounded_rectangle((ram[0], ram[1] + 18 * k, ram[2], ram[3] + 18 * k), radius=28 * k,
                                         fill=(30, 0, 15, 120))
    img.alpha_composite(sk.filter(ImageFilter.GaussianBlur(16 * k)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(ram, radius=28 * k, fill=(*fyll, 255), outline=(*kant, 255), width=12 * k)
    over, stor, under = dela_pris(pris)
    if under.lower() == "kr" and re.fullmatch(r"\d+", stor):
        stor, under = stor + ":-", ""
    topp = over or rubrik
    yt = ram[1] + (60 * k if topp else 0)
    if topp:
        d.text(((ram[0] + ram[2]) / 2, ram[1] + 30 * k), topp.upper(), font=poppins("ExtraBold", 54 * k),
               fill=textfarg, anchor="mt")
    tillg_h = ram[3] - yt - (70 * k if under else 20 * k)
    f = passa(stor, lambda s: poppins("Black", s), int(W * 0.86), int(tillg_h * 1.25), 60)
    d.text(((ram[0] + ram[2]) / 2, yt + tillg_h / 2 + 30 * k), stor, font=f, fill=textfarg, anchor="mm")
    if under:
        d.text((ram[2] - 40 * k, ram[3] - 30 * k), under, font=poppins("ExtraBold", 64 * k),
               fill=textfarg, anchor="rb")
    img = img.rotate(vinkel, resample=Image.BICUBIC, expand=True)
    return img.resize((img.width // k, img.height // k), Image.LANCZOS)


# ---------- produkt ----------

def produkt_lager(foto: Path, maxb: int, maxh: int, ram_farg=(255, 255, 255)) -> tuple[Image.Image, bool]:
    """Frilagd produkt med mjuk skugga; annars fotot i en rundad ram. (bild, frilagd?)"""
    ut = frilagg(foto)
    pad = 70
    if ut is not None:
        ut.thumbnail((maxb, maxh), Image.LANCZOS)
        if ut.width < maxb * 0.6 and ut.height < maxh * 0.6:       # små bilder skalas upp
            f = min(maxb * 0.8 / ut.width, maxh * 0.8 / ut.height)
            ut = ut.resize((int(ut.width * f), int(ut.height * f)), Image.LANCZOS)
        duk = Image.new("RGBA", (ut.width + 2 * pad, ut.height + 2 * pad + 40), (0, 0, 0, 0))
        golv = Image.new("RGBA", duk.size, (0, 0, 0, 0))
        gx, gy = duk.width / 2, pad + ut.height + 10
        ImageDraw.Draw(golv).ellipse((gx - ut.width * 0.42, gy - 22, gx + ut.width * 0.42, gy + 22),
                                     fill=(30, 0, 15, 130))
        duk.alpha_composite(golv.filter(ImageFilter.GaussianBlur(18)))
        skugga = Image.new("RGBA", ut.size, (30, 0, 15, 0))
        skugga.putalpha(ut.getchannel("A").point(lambda v: v * 0.45))
        sk = Image.new("RGBA", duk.size, (0, 0, 0, 0))
        sk.alpha_composite(skugga, (pad + 14, pad + 26))
        duk.alpha_composite(sk.filter(ImageFilter.GaussianBlur(16)))
        duk.alpha_composite(ut, (pad, pad))
        return duk, True

    bild = Image.open(foto).convert("RGB")
    kant = 16
    bild.thumbnail((maxb - 2 * kant, maxh - 2 * kant), Image.LANCZOS)
    w, h = bild.width + 2 * kant, bild.height + 2 * kant
    duk = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sk = Image.new("RGBA", duk.size, (0, 0, 0, 0))
    ImageDraw.Draw(sk).rounded_rectangle((pad + 10, pad + 24, pad + w + 10, pad + h + 24), radius=46,
                                         fill=(30, 0, 15, 140))
    duk.alpha_composite(sk.filter(ImageFilter.GaussianBlur(20)))
    ram = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(ram).rounded_rectangle((0, 0, w - 1, h - 1), radius=46, fill=(*ram_farg, 255))
    mask = Image.new("L", bild.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bild.width - 1, bild.height - 1), radius=32, fill=255)
    ram.paste(bild, (kant, kant), mask)
    duk.alpha_composite(ram, (pad, pad))
    return duk, False


# ---------- designer ----------

@dataclass
class Lager:
    bg: Image.Image
    text: Image.Image
    produkt: Image.Image
    produkt_mitt: tuple[int, int]
    pris: Image.Image
    pris_mitt: tuple[int, int]
    glitter: Image.Image
    frilagd: bool = False
    info: dict = field(default_factory=dict)


def _namn(text: Image.Image, namn: str, y0: int, y1: int, farg, kant, kantfarg, maxb=960, storst=130):
    if not namn:
        return
    fn = (lambda s: arabisk(s)) if har_arabiska(namn) else (lambda s: poppins("ExtraBold", s))
    # Högst så stor att två rader ryms i y0..y1.
    storst = min(storst, int((y1 - y0) / 2.3))
    f, rader = radbryt(namn, fn, maxb, storst, 50)
    if len(rader) == 1:   # en rad får vara större
        f = passa(namn, fn, maxb, min(int((y1 - y0) * 0.75), 140), f.size)
    lh = int(f.size * 1.12)
    start = (y0 + y1) / 2 - lh * (len(rader) - 1) / 2
    for i, r in enumerate(rader):
        text_med_skugga(text, (B / 2, start + i * lh), r, f, farg, kant=kant, kantfarg=kantfarg)


def namnetikett(text: Image.Image, namn: str, y0: int, y1: int, fyll, textfarg, maxb=900):
    """Variant: namnet på en krämvit, rundad etikett (i stället för fri text med kontur)."""
    if not namn:
        return
    fn = (lambda s: arabisk(s)) if har_arabiska(namn) else (lambda s: poppins("ExtraBold", s))
    hojd = min(190, int((y1 - y0) * 0.8))
    f = passa(namn, fn, maxb - hojd, int(hojd * 0.62), 44)
    bredd = int(min(maxb, f.getlength(namn) + hojd * 1.1))
    cy = (y0 + y1) / 2
    ram = (B / 2 - bredd / 2, cy - hojd / 2, B / 2 + bredd / 2, cy + hojd / 2)
    sk = Image.new("RGBA", text.size, (0, 0, 0, 0))
    ImageDraw.Draw(sk).rounded_rectangle((ram[0], ram[1] + 10, ram[2], ram[3] + 10), radius=hojd // 2, fill=(30, 0, 15, 110))
    text.alpha_composite(sk.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(text)
    d.rounded_rectangle(ram, radius=hojd // 2, fill=(*fyll, 255))
    d.text((B / 2, cy), namn, font=f, fill=textfarg, anchor="mm")


def _logga(text: Image.Image, y: int, farg=KRAM, kant=MORK, storlek=170):
    text_med_skugga(text, (B / 2, y), "MIN BUTIK", bitter(storlek), farg, kant=9, kantfarg=kant, skugga=(0, 12))


def design_a(foto: Path, namn: str, pris: str, fynd: bool) -> Lager:
    """'Solsken': som välkomstvideon – magenta strålar, stor serif-logga, tandad prisbricka."""
    bg = bakgrund_stralar("FF5C93", "B0124F", seed=11) if fynd else bakgrund_stralar("E53373", "971251", seed=7)
    text = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    _logga(text, 165)
    _namn(text, namn, 1600, 1850, KRAM, 7, MORK)
    prod, fri = produkt_lager(foto, 780, 900)
    # Färgen skiljer fynd (gul) från vanliga erbjudanden (krämvit) – ingen text behövs.
    rosettfarg = (GUL, (160, 10, 70), (160, 10, 70)) if fynd else (KRAM, MAGENTA, MAGENTA)
    pr = rosett(pris, 580, rosettfarg[0], rosettfarg[1], rosettfarg[2]).rotate(8, Image.BICUBIC, expand=True)
    return Lager(bg, text, prod, (450, 800), pr, (770, 1250), glitter(), fri)


def design_b(foto: Path, namn: str, pris: str, fynd: bool) -> Lager:
    """'Prisskylt': ljusrosa (som Monster-videon), namn som rubrik, stor gul svensk prisskylt."""
    if fynd:
        bg = bakgrund_stralar("FF6FAE", "D81B72", seed=12, styrka=0.06)
        logga_f, logga_k, namnf, namnk = KRAM, MORK, KRAM, MORK
    else:
        bg = bakgrund_ljus()
        logga_f, logga_k, namnf, namnk = (216, 27, 96), (255, 255, 255), (61, 20, 48), (255, 255, 255)
    text = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    _logga(text, 150, logga_f, logga_k, 150)
    _namn(text, namn, 270, 520, namnf, 6, namnk, storst=120)
    prod, fri = produkt_lager(foto, 720, 760)
    # Fynd: gul skylt. Vanligt erbjudande: vit skylt med magenta.
    if fynd:
        skylt = prisskylt(pris, 760, 400, GUL, (200, 16, 46), (200, 16, 46), vinkel=-4)
    else:
        skylt = prisskylt(pris, 760, 400, (255, 255, 255), MAGENTA, MAGENTA, vinkel=-4)
    return Lager(bg, text, prod, (540, 960), skylt, (540, 1610), glitter((255, 255, 255), seed=5), fri)


def design_c(foto: Path, namn: str, pris: str, fynd: bool) -> Lager:
    """'Kontrast': magenta överdel med logga och produkt, mörk underdel med jättepris."""
    bg = bakgrund_stralar("FF5C93" if fynd else "E53373", "B0124F" if fynd else "971251",
                          mitt=(540, 760), seed=9)
    panel_y = 1290
    panel = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    dp = ImageDraw.Draw(panel)
    dp.rounded_rectangle((24, panel_y, B - 25, H - 25), radius=40, fill=(42, 8, 32, 255))
    for i in range(6):   # tunn glänsande kant
        dp.line((60, panel_y + i, B - 60, panel_y + i), fill=(255, 120, 180, 120 - i * 18))
    bg.alpha_composite(panel)
    text = Image.new("RGBA", (B, H), (0, 0, 0, 0))
    _logga(text, 150, storlek=160)
    _namn(text, namn, panel_y + 50, panel_y + 220, (255, 255, 255), 0, MORK, maxb=940, storst=90)
    prod, fri = produkt_lager(foto, 780, 880)
    # Jättepriset ritas som eget lager så att det kan "poppa".
    over, stor, under = dela_pris(pris)
    if under.lower() == "kr" and re.fullmatch(r"\d+", stor):
        stor, under = stor + ":-", ""
    w, h = 1000, 400
    pl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fo = poppins("ExtraBold", 90)
    ow = fo.getlength(over + " ") if over else 0
    f = passa(stor, lambda s: poppins("Black", s), int(880 - ow), 330, 120)
    tw = f.getlength(stor)
    x0 = w / 2 - (ow + tw) / 2
    bas = h / 2 + f.size * 0.36
    if over:   # "2 för" i vitt på samma baslinje, före siffran
        ImageDraw.Draw(pl).text((x0, bas), over + " ", font=fo, fill=(255, 255, 255), anchor="ls")
    prisfarg = GUL if fynd else (255, 122, 184)   # gul = fynd, rosa = vanligt erbjudande
    text_med_skugga(pl, (x0 + ow, bas), stor, f, prisfarg, kant=0, skugga=(0, 14), skuggalfa=160, ankare="ls")
    if under:
        ImageDraw.Draw(pl).text((w / 2 + tw / 2, h - 30), under, font=poppins("ExtraBold", 64),
                                fill=(255, 255, 255), anchor="rb")
    return Lager(bg, text, prod, (540, 740), pl, (540, 1700), glitter(), fri)


DESIGNER = {"A": design_a, "B": design_b, "C": design_c}


def stillbild(l: Lager) -> Image.Image:
    """En bildruta mitt i videon: allt på plats."""
    bild = l.bg.convert("RGBA").copy()
    bild.alpha_composite(l.glitter.crop((0, 400, B, 400 + H)))
    px, py = l.produkt_mitt
    bild.alpha_composite(l.produkt, (int(px - l.produkt.width / 2), int(py - l.produkt.height / 2)))
    bild.alpha_composite(l.text)
    cx, cy = l.pris_mitt
    bild.alpha_composite(l.pris, (int(cx - l.pris.width / 2), int(cy - l.pris.height / 2)))
    return bild.convert("RGB")
