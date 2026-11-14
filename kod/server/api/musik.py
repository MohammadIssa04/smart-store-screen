"""Musik i appen: vad som spelas, styrning, sök, listor per tidsblock.
Spelaren är tjänsten butiksmusik (musik/spelare.py); API:t pratar med den via dess styrsocket."""
from __future__ import annotations

import asyncio
import json
import re

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from musik import bibliotek as bib
from musik import hamtning
import oversatt
from konfig import STYR_SOCK

router = APIRouter(prefix="/api/musik")
ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


async def styr(cmd: str, **varden) -> dict:
    try:
        r, w = await asyncio.wait_for(asyncio.open_unix_connection(STYR_SOCK), 3)
        w.write((json.dumps({"cmd": cmd, **varden}) + "\n").encode())
        await w.drain()
        svar = json.loads(await asyncio.wait_for(r.readline(), 10) or b"{}")
        w.close()
        return svar
    except (OSError, asyncio.TimeoutError, ValueError):
        return {"fel": "Musikspelaren är inte igång"}


def svar(d: dict):
    return JSONResponse(d, status_code=503) if "fel" in d else d


@router.get("/status")
async def status():
    return svar(await styr("status"))


class Styr(BaseModel):
    cmd: str               # paus | spela | nasta | loop
    pa: bool = False


@router.post("/styr")
async def styr_spelaren(data: Styr):
    if data.cmd not in ("paus", "spela", "nasta", "loop"):
        return JSONResponse({"fel": "Okänt kommando"}, status_code=400)
    return svar(await styr(data.cmd, pa=data.pa))


class Volym(BaseModel):
    procent: int


@router.post("/volym")
async def volym(data: Volym, request: Request):
    """Musikspelarens egen volym (sparas). System-/Bluetooth-volymen rörs inte."""
    return svar(await styr("volym", procent=max(0, min(100, data.procent)),
                           telefon=request.state.enhet.get("namn")))


class Startpunkt(BaseModel):
    andra: int = 0             # -10 / +10 sekunder från nuvarande startpunkt
    satt: int | None = None    # exakt sekund (t.ex. förslaget)
    nollstall: bool = False    # från början
    id: str | None = None      # annan låt än den som spelas nu


@router.post("/startpunkt")
async def startpunkt(data: Startpunkt):
    """Var låten ska börja (lång inledning). Sparas per låt; originalfilen ändras aldrig.
    Gäller låten som spelas nu, och den hoppar dit direkt så att pappa hör var den börjar."""
    s = await styr("status")
    lat_id = data.id or s.get("id")
    if not lat_id or not bib.hitta_lat(lat_id):
        return JSONResponse({"fel": oversatt.t("Ingen låt från listan spelas just nu.")}, status_code=409)
    if data.nollstall:
        ny = bib.satt_startpunkt(lat_id, 0)
    elif data.satt is not None:
        ny = bib.satt_startpunkt(lat_id, data.satt)
    else:
        ny = bib.satt_startpunkt(lat_id, bib.startpunkt(lat_id) + data.andra)
    if lat_id == s.get("id"):
        s = await styr("hoppa", sek=ny)
    return {**s, "start": ny, "meddelande": oversatt.t("Börjar från början." if ny == 0 else "Startpunkten ändrad.")}


class Favorit(BaseModel):
    pa: bool
    id: str | None = None


@router.post("/favorit")
async def favorit(data: Favorit):
    """Favoritlåt: kommer oftare tidigt i dagens blandning och byts aldrig ut av den dagliga rotationen."""
    lat_id = data.id
    if not lat_id:
        lat_id = (await styr("status")).get("id")
    if not lat_id or not bib.hitta_lat(lat_id):
        return JSONResponse({"fel": oversatt.t("Ingen låt från listan spelas just nu.")}, status_code=409)
    bib.satt_favorit(lat_id, data.pa)
    return {"ok": True, "id": lat_id, "favorit": data.pa,
            "meddelande": oversatt.t("Sparad som favorit." if data.pa else "Inte favorit längre.")}


@router.get("/sok")
async def sok(q: str):
    q = q.strip()[:100]
    if len(q) < 2:
        return {"traffar": []}
    traffar = [t for t in await asyncio.to_thread(hamtning.sok, q, 10) if t["langd"] >= 60]
    # Vanliga låtar (under 20 min) först, långa mixar sist – men alla får vara med.
    return {"traffar": sorted(traffar, key=lambda t: t["langd"] > 20 * 60)}


class Lat(BaseModel):
    id: str
    titel: str = ""
    kanal: str = ""
    langd: int = 0
    block: str = ""


@router.post("/spela")
async def spela_nu(data: Lat):
    """Spelar en sökträff direkt (strömmas, läggs inte i någon lista)."""
    if not ID.match(data.id):
        return JSONResponse({"fel": "Ogiltig låt"}, status_code=400)
    return svar(await styr("spela_nu", url=f"https://www.youtube.com/watch?v={data.id}", id=data.id,
                           titel=data.titel, artist=data.kanal, langd=data.langd))


@router.post("/lagg-till")
async def lagg_till(data: Lat, bakgrund: BackgroundTasks):
    """Hämtar låten till ett tidsblock (tar några sekunder–en minut, sker i bakgrunden)."""
    b = bib.hitta_block(data.block)
    if not ID.match(data.id) or not b:
        return JSONResponse({"fel": "Ogiltig låt eller lista"}, status_code=400)
    if bib.finns(data.id, b["id"]) and any(l["id"] == data.id for l in bib.latar(b["id"])):
        return {"ok": True, "meddelande": f"Finns redan i {b['namn']}"}
    t = {"id": data.id, "titel": data.titel, "kanal": data.kanal, "langd": data.langd}
    bakgrund.add_task(asyncio.to_thread, hamtning.hamta, t, b["id"], data.kanal or "Eget val", "manuell")
    return {"ok": True, "meddelande": f"Läggs till i {b['namn']}"}


@router.get("/block")
async def block():
    nu = bib.block_nu()
    return {"nu": nu["id"] if nu else None,
            "block": [{"id": b["id"], "namn": b["namn"], "tid": f"{b['fran']:02d}–{b['till']:02d}",
                       "antal": len(bib.latar(b["id"])), "artister": [a["namn"] for a in b["artister"]]}
                      for b in bib.block()]}


@router.get("/block/{block_id}")
async def latar(block_id: str):
    b = bib.hitta_block(block_id)
    if not b:
        return JSONResponse({"fel": "Finns inte"}, status_code=404)
    val = bib.latval()
    return {"id": b["id"], "namn": b["namn"], "tid": f"{b['fran']:02d}–{b['till']:02d}",
            "latar": sorted(({"id": l["id"], "titel": l["titel"], "artist": l["artist"], "langd": l["langd"],
                              "favorit": bool(val.get(l["id"], {}).get("favorit")),
                              "start": int(val.get(l["id"], {}).get("start", 0))}
                             for l in bib.latar(b["id"])), key=lambda l: (not l["favorit"], l["titel"].lower()))}


class TaBort(BaseModel):
    id: str
    block: str


@router.post("/ta-bort")
async def ta_bort(data: TaBort):
    l = bib.ta_bort(data.id, data.block)
    if not l:
        return JSONResponse({"fel": "Finns inte i listan"}, status_code=404)
    return {"ok": True, "meddelande": f"\"{l['titel']}\" togs bort ur listan"}
