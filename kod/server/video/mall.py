"""Grundlayouten för en produktvideo (ren stil):

    MIN BUTIK            <- överst
    [ produktbild ]      <- med lätt inzoomning
          (pris)         <- rund prisbricka över bildens nedre hörn
    Produktnamn          <- nederst, stort

Erbjudande och Dagens fynd använder samma layout med olika Stil."""
from __future__ import annotations

import re
from pathlib import Path

from .bas import (BREDD, FPS, KODNING, LANGD, RUTOR, Stil, Text, anpassa,
                  bakgrund, bredd, drawtext, kor_ffmpeg, rundad_mask,
                  rundad_ruta, typsnitt)

MARKE_Y = 120
LINJE_Y = 232
FOTO, FOTO_Y = 960, 300
BRICKA = 400
BRICKA_X = BREDD - 40 - BRICKA                  # 640
BRICKA_Y = FOTO_Y + FOTO - BRICKA + 70          # 930
NAMN_TOPP, NAMN_BOTTEN = FOTO_Y + FOTO + 110, 1820   # 1370-1820
ETIKETT_B, ETIKETT_H = 440, 86


def _in(start: float, langd: float = 0.4) -> str:
    return f"clip((t-{start})/{langd},0,1)"


def dela_pris(pris: str) -> tuple[str, str, str]:
    """(liten rad över, stor siffra, liten rad under): '2 för 30 kr' -> ('2 för', '30', 'kr')."""
    over = ""
    m = re.match(r"(?i)^(\d+\s*för)\s+(.*)$", pris)
    if m:
        over, pris = m.group(1), m.group(2)
    m = re.match(r"(?i)^(.*?\d)\s*(kr)$", pris)
    if m:
        return over, m.group(1), m.group(2)
    return over, pris, ""


async def rendera(foto: Path, rubrik: str, pris: str, stil: Stil, ut: Path) -> Path:
    mapp = ut.parent / "delar"
    mapp.mkdir(parents=True, exist_ok=True)
    font = typsnitt()["latin"]

    loop = ["-loop", "1", "-framerate", str(FPS), "-t", str(LANGD), "-i"]
    indata = [bakgrund(stil), foto, rundad_mask(FOTO, FOTO, 36),
              rundad_ruta(120, 8, 4, stil.text)]
    if pris:
        indata.append(rundad_ruta(BRICKA, BRICKA, BRICKA // 2, stil.bricka_bg))
    if stil.etikett:
        indata.append(rundad_ruta(ETIKETT_B, ETIKETT_H, ETIKETT_H // 2, stil.etikett_bg))
    args: list[str] = []
    for fil in indata:
        args += loop + [str(fil)]
    nr_bricka = 4
    nr_etikett = 5 if pris else 4

    g = [
        # Hela produkten ska synas: skala in i rutan och fyll ut med vitt (ingen beskärning).
        f"[1:v]scale={int(2 * FOTO * 0.9)}:{int(2 * FOTO * 0.9)}:force_original_aspect_ratio=decrease,"
        f"pad={2 * FOTO}:{2 * FOTO}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,"
        f"zoompan=z='1+0.08*on/{RUTOR}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={FOTO}x{FOTO}:fps={FPS},"
        f"format=rgba[foto]",
        "[2:v]format=gray[mask]",
        "[foto][mask]alphamerge,fade=t=in:st=0:d=0.5:alpha=1[fotor]",
        "[0:v]format=rgba[bg]",
        f"[bg][fotor]overlay=x=(W-w)/2:y={FOTO_Y}[a]",
        f"[a][3:v]overlay=x=(W-w)/2:y={LINJE_Y}[b]",
    ]
    sista = "b"
    if pris:
        g.append(f"[{nr_bricka}:v]format=rgba,fade=t=in:st=0.6:d=0.35:alpha=1[br]")
        g.append(f"[{sista}][br]overlay=x={BRICKA_X}:y={BRICKA_Y}[c]")
        sista = "c"

    texter: list[Text] = [Text("MIN BUTIK", 84, stil.text, str(MARKE_Y), font=font)]

    # Etikett (Dagens fynd) direkt under bilden, namnet under den.
    namn_topp = NAMN_TOPP
    if stil.etikett:
        ety = NAMN_TOPP - 20
        g.append(f"[{nr_etikett}:v]format=rgba,fade=t=in:st=0.3:d=0.4:alpha=1[et]")
        g.append(f"[{sista}][et]overlay=x=(W-w)/2:y={ety}[d]")
        sista = "d"
        texter.append(Text(stil.etikett, 48, stil.etikett_text, f"{ety}+({ETIKETT_H}-th)/2",
                           alpha=_in(0.3), font=font))
        namn_topp = ety + ETIKETT_H + 40

    if rubrik:
        storlek, rader = anpassa(rubrik, 980, NAMN_BOTTEN - namn_topp, 130, 56)
        radhojd = int(storlek * 1.2)
        start = namn_topp + max(0, (NAMN_BOTTEN - namn_topp - len(rader) * radhojd) // 2)
        for i, rad in enumerate(rader):
            texter.append(Text(rad, storlek, stil.text, str(start + i * radhojd),
                               alpha=_in(0.3 + 0.12 * i)))

    if pris:
        over, stor, under = dela_pris(pris)
        cx = f"{BRICKA_X}+({BRICKA}-text_w)/2"
        ss = int(min(190, 300 / max(bredd(stor, 1), 0.1)))
        mitt = BRICKA_Y + BRICKA // 2
        yst = mitt - ss // 2 - (14 if under and not over else 0) + (14 if over and not under else 0)
        a = _in(0.6, 0.35)
        texter.append(Text(stor, ss, stil.bricka_text, str(yst), x=cx, alpha=a, font=font))
        if over:
            texter.append(Text(over, 54, stil.bricka_text, str(yst - 66), x=cx, alpha=a, font=font))
        if under:
            texter.append(Text(under, 60, stil.bricka_text, str(yst + int(ss * 0.95)), x=cx, alpha=a, font=font))

    kedja = ",".join(drawtext(t, mapp, i) for i, t in enumerate(texter))
    # Kedjan är RGBA, så format=yuv420p ger tv-range; -color_range tv i KODNING
    # ser till att filen märks så (annars ärvs "full range" från mobilfoton).
    g.append(f"[{sista}]{kedja},format=yuv420p[ut]")

    args += ["-filter_complex", ";".join(g), "-map", "[ut]", "-t", str(LANGD), *KODNING, str(ut)]
    await kor_ffmpeg(args)
    return ut
