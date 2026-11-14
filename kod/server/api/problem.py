"""'Rapportera problem' i appen: pappa skriver vad som är fel, och det skickas till ägaren på Telegram
(samma bot och samma mottagare som hälsokontrollen). Rapporten sparas också i data/problem.jsonl,
så att inget försvinner om Telegram inte svarar. Telefonens namn, appversion, sidan man var på och
kända problem på Pi:n skickas med automatiskt."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import halsa
import konfig
import oversatt

log = logging.getLogger("butiksbot.api.problem")
# httpx skriver annars hela adressen i loggen på INFO-nivå, och Telegram-adressen innehåller bottens nyckel.
logging.getLogger("httpx").setLevel(logging.WARNING)
router = APIRouter(prefix="/api", tags=["problem"])
FIL = konfig.DATA_DIR / "problem.jsonl"


class Rapport(BaseModel):
    text: str
    sida: str = ""
    version: str = ""


async def _telegram(text: str) -> bool:
    token = konfig.token()
    mottagare = konfig.tillatna_id()
    if not token or not mottagare:
        return False
    skickat = False
    async with httpx.AsyncClient(timeout=15) as c:
        for chatt in mottagare:
            try:
                r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chatt, "text": text})
                skickat = skickat or r.status_code == 200
            except httpx.HTTPError:
                log.warning("Kunde inte skicka problemrapporten till Telegram")     # aldrig adressen: den har nyckeln
    return skickat


async def _ntfy(titel: str, text: str) -> bool:
    """Push till ntfy om NTFY_AMNE finns i butiksbot.env (ämnet är hemligt: loggas aldrig)."""
    import os
    amne = os.environ.get("NTFY_AMNE", "").strip()
    if not amne:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{server}/{amne}", content=text.encode("utf-8"),
                             headers={"Title": titel.encode("utf-8"), "Tags": "warning", "Priority": "high"})
        return r.status_code == 200
    except httpx.HTTPError:
        log.warning("Kunde inte skicka problemrapporten till ntfy")
        return False


@router.post("/problem")
async def rapportera(data: Rapport, request: Request):
    text = data.text.strip()[:2000]
    if not text:
        return JSONResponse({"fel": oversatt.t("Skriv vad som är fel.")}, status_code=400)
    telefon = request.state.enhet.get("namn", "?")
    nu = datetime.now()
    try:
        kanda = (await asyncio.to_thread(halsa.matvarden)).get("problem", [])
    except Exception:
        kanda = []
    rad = {"tid": nu.isoformat(timespec="seconds"), "telefon": telefon, "version": data.version[:20],
           "sida": data.sida[:30], "text": text, "kanda_problem": kanda}
    FIL.parent.mkdir(parents=True, exist_ok=True)
    with FIL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rad, ensure_ascii=False) + "\n")
    meddelande = "\n".join(
        [f"🛠 Problem rapporterat från appen ({telefon}, {nu:%d/%m %H:%M})", "", text, "",
         f"Sida: {data.sida or '?'} · App {data.version or '?'}"]
        + (["", "Pi:n vet om:"] + [f"• {p}" for p in kanda] if kanda else []))
    skickat = await _telegram(meddelande)
    push = await _ntfy(f"Problem i Min Butik ({telefon})", meddelande.split("\n", 2)[-1].strip())
    log.info("Problemrapport från %s (Telegram: %s, ntfy: %s)", telefon, skickat, push)
    return {"ok": True, "meddelande": oversatt.t("Tack! Mohammad har fått ditt meddelande.")}
