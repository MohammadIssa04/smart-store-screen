"""Byggstenar för skyltvideor: format, typsnitt, grafik och ffmpeg.

Allt görs lokalt med ffmpeg. Text ritas med drawtext (libharfbuzz +
libfribidi) så att å/ä/ö och arabiska formas och vänds rätt."""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import konfig

# Samma format som videorna i skylt/alltid: 1080x1920, H.264 High 4.0,
# yuv420p, 30 fps, ca 2 Mbit/s, inget ljud.
BREDD, HOJD, FPS, LANGD = 1080, 1920, 30, 9
RUTOR = FPS * LANGD
KODNING = [
    "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
    "-profile:v", "high", "-level:v", "4.0", "-pix_fmt", "yuv420p", "-color_range", "tv",
    "-crf", "21", "-maxrate", "3M", "-bufsize", "6M",
    "-movflags", "+faststart", "-an",
]


@dataclass(frozen=True)
class Stil:
    namn: str
    bakgrund: str          # enfärgad, ljus
    text: str              # "MIN BUTIK" och produktnamnet
    bricka_bg: str         # prisbrickan
    bricka_text: str
    etikett: str = ""      # t.ex. "DAGENS FYND" (tom = ingen etikett)
    etikett_bg: str = "0x111111"
    etikett_text: str = "0xFFFFFF"


# ---------- typsnitt ----------

def _fc(monster: str) -> str:
    try:
        return subprocess.run(["fc-match", "-f", "%{file}", monster],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def typsnitt() -> dict[str, str]:
    dejavu = _fc("DejaVu Sans:bold") or "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    latin = _fc("Noto Sans:bold")
    arab = _fc("Noto Sans Arabic:bold")
    return {
        "latin": latin if "NotoSans" in latin else dejavu,
        "arab": arab if "Arabic" in arab else dejavu,
        "blandat": dejavu,  # DejaVu har både latinska och arabiska tecken + symboler
    }


def _arabisk(c: str) -> bool:
    o = ord(c)
    return (0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF
            or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF)


def typsnitt_for(rad: str) -> str:
    t = typsnitt()
    har_ar = any(_arabisk(c) for c in rad)
    har_latin = any(c.isalnum() and not _arabisk(c) for c in rad)
    if har_ar and har_latin:
        return t["blandat"]
    return t["arab"] if har_ar else t["latin"]


# ---------- textmått och radbrytning (uppskattning) ----------

def bredd(text: str, storlek: float) -> float:
    def b(c: str) -> float:
        if c.isupper() or c.isdigit() or c in "%@WMwm":
            return 0.72
        if c in " .,:;!'iljt|()-":
            return 0.34
        return 0.6
    return storlek * sum(b(c) for c in text)


def radbryt(text: str, storlek: int, maxb: float) -> list[str]:
    rader, rad = [], ""
    for ord_ in text.split():
        test = f"{rad} {ord_}".strip()
        if not rad or bredd(test, storlek) <= maxb:
            rad = test
        else:
            rader.append(rad)
            rad = ord_
    if rad:
        rader.append(rad)
    return rader


def anpassa(text: str, maxb: float, maxh: float, storst: int, minst: int) -> tuple[int, list[str]]:
    for s in range(storst, minst - 1, -2):
        rader = radbryt(text, s, maxb)
        if all(bredd(r, s) <= maxb for r in rader) and len(rader) * s * 1.2 <= maxh:
            return s, rader
    return minst, radbryt(text, minst, maxb)


# ---------- grafik (genereras en gång och cachas) ----------

def _kor(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=180)


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.replace("0x", "").replace("#", "")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rund_alfa(b: int, h: int, r: int) -> str:
    return (f"255*clip({r}+0.5-hypot(max(max({r}-X,X-{b - 1 - r}),0),"
            f"max(max({r}-Y,Y-{h - 1 - r}),0)),0,1)")


def rundad_ruta(b: int, h: int, r: int, farg: str) -> Path:
    fil = konfig.CACHE_DIR / f"ruta_{b}x{h}_r{r}_{farg.replace('0x', '')}.png"
    if not fil.exists():
        fil.parent.mkdir(parents=True, exist_ok=True)
        R, G, B = _rgb(farg)
        _kor(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
              f"color=c=black:s={b}x{h},format=rgba,geq=r={R}:g={G}:b={B}:a='{_rund_alfa(b, h, r)}'",
              "-frames:v", "1", str(fil)])
    return fil


def rundad_mask(b: int, h: int, r: int) -> Path:
    fil = konfig.CACHE_DIR / f"mask_{b}x{h}_r{r}.png"
    if not fil.exists():
        fil.parent.mkdir(parents=True, exist_ok=True)
        _kor(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
              f"color=c=black:s={b}x{h},format=gray,geq=lum='{_rund_alfa(b, h, r)}'",
              "-frames:v", "1", str(fil)])
    return fil


def bakgrund(stil: Stil) -> Path:
    """Ren, enfärgad bakgrund."""
    fil = konfig.CACHE_DIR / f"bg_{stil.bakgrund.replace('0x', '')}.png"
    if not fil.exists():
        fil.parent.mkdir(parents=True, exist_ok=True)
        _kor(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
              f"color=c={stil.bakgrund}:s={BREDD}x{HOJD}", "-frames:v", "1", str(fil)])
    return fil


# ---------- drawtext ----------

@dataclass
class Text:
    rad: str
    storlek: int
    farg: str
    y: str
    alpha: str = "1"
    x: str = "(w-text_w)/2"
    kant: int = 0
    kantfarg: str = "0x000000"
    font: str | None = None


def drawtext(t: Text, mapp: Path, nr: int) -> str:
    fil = mapp / f"text{nr}.txt"
    fil.write_text(t.rad, encoding="utf-8")
    delar = [
        f"fontfile={t.font or typsnitt_for(t.rad)}",
        f"textfile={fil}",
        "expansion=none",
        f"fontsize={t.storlek}",
        f"fontcolor={t.farg}",
        f"x={t.x}",
        f"y={t.y}",
        f"alpha='{t.alpha}'",
    ]
    if t.kant:
        delar += [f"borderw={t.kant}", f"bordercolor={t.kantfarg}"]
    return "drawtext=" + ":".join(delar)


async def kor_ffmpeg(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *konfig.lag_prioritet_prefix(), "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-filter_complex_threads", str(konfig.RENDER_TRADAR), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, fel = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg misslyckades: " + fel.decode(errors="replace")[-3000:])
