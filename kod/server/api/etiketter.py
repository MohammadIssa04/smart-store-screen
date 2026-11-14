"""Prisetiketter i appen (70 x 40 mm, Niimbot B31).

  POST /api/etiketter/las           fotos (ett foto) + text (ev. pris) -> {"namn", "pris"} läst av AI:n (pappa kan rätta)
  POST /api/etiketter/forhandsvisa  {"namn", "pris"} -> PNG, exakt som etiketten skrivs ut
  POST /api/etiketter/skriv-ut      {"namn", "pris", "antal"} -> {"lage", "meddelande"}
  GET  /api/etiketter/senaste       de senaste etiketterna (för att skriva ut samma igen)
  GET  /api/etiketter/lage          {"lage": "test" | "usb" | "bluetooth", "ai": bool}
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import etikett
import igenkanning
import minne
import oversatt
import tolka

log = logging.getLogger("butiksbot.api.etiketter")
router = APIRouter(prefix="/api/etiketter")
MAX_FOTO = 15 * 1024 * 1024
MAX_NAMN = 60


class Etikett(BaseModel):
    namn: str
    pris: str
    antal: int = 1
    ai_namn: str = ""          # namnet AI:n föreslog; rättar pappa det minns butiken rättelsen


def fel(text: str, kod: int = 400):
    return JSONResponse({"fel": oversatt.t(text)}, status_code=kod)


def rensa(e: Etikett) -> tuple[str, str] | JSONResponse:
    namn = " ".join(e.namn.split())[:MAX_NAMN]
    pris = tolka.tolka_pris(e.pris) if e.pris.strip() else ""
    if not namn:
        return fel("Skriv varans namn.")
    if not pris:
        return fel("Skriv priset, t.ex. 19 eller 2 för 30.")
    return namn, pris


@router.get("/lage")
async def lage():
    """Läget och om skrivaren svarar just nu (appen visar grönt/rött)."""
    return {"lage": etikett.installning("ETIKETT_LAGE", "test").lower(), "ai": igenkanning.tillganglig(),
            "skrivare": await asyncio.to_thread(etikett.skrivarstatus)}


@router.post("/las")
async def las(fotos: list[UploadFile] = File(...), text: str = Form("")):
    foto, pris = fotos[0], text
    if not igenkanning.tillganglig():
        return fel("AI:n är inte påslagen. Skriv namnet själv.", 503)
    data = await foto.read(MAX_FOTO + 1)
    if not data or len(data) > MAX_FOTO:
        return fel("Fotot gick inte att läsa.")
    with tempfile.TemporaryDirectory() as mapp:
        fil = Path(mapp) / "foto.jpg"
        fil.write_bytes(data)
        svar = await igenkanning.kanna_igen(fil)
    if not svar:
        return fel("Jag kände inte igen varan. Skriv namnet själv.", 422)
    ai_pris = tolka.snygga_pris(svar["pris"]) if svar.get("pris") else ""
    return {"namn": minne.synonym(svar["namn"])[:MAX_NAMN],
            "pris": tolka.tolka_pris(pris) if pris.strip() else ai_pris}


@router.post("/forhandsvisa")
async def forhandsvisa(e: Etikett):
    r = rensa(e)
    if isinstance(r, JSONResponse):
        return r
    png = await asyncio.to_thread(etikett.forhandsvisning, *r)
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/skriv-ut")
async def skriv_ut(e: Etikett, request: Request):
    r = rensa(e)
    if isinstance(r, JSONResponse):
        return r
    if e.ai_namn.strip() and e.ai_namn.strip().lower() != r[0].lower():
        minne.spara_synonym(e.ai_namn.strip(), r[0])
    try:
        svar = await asyncio.to_thread(etikett.skriv_ut, *r, e.antal, f"app:{request.state.enhet['namn']}")
        return {**svar, "meddelande": oversatt.t(svar["meddelande"])}
    except etikett.SkrivFel as f:
        return fel(str(f), 503)


@router.get("/senaste")
async def senaste():
    ut, sedda = [], set()
    try:
        rader = etikett.LOGG.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        rader = []
    for rad in reversed(rader):
        try:
            d = json.loads(rad)
        except ValueError:
            continue
        nyckel = (d.get("namn", "").lower(), d.get("pris", ""))
        if d.get("resultat") == "fel" or nyckel in sedda:
            continue
        sedda.add(nyckel)
        ut.append({"namn": d["namn"], "pris": d["pris"], "tid": d.get("tid", "")})
        if len(ut) >= 12:
            break
    return {"etiketter": ut}
