"""API för Min Butik-appen. Återanvänder butiksbots moduler (samma logik som Telegram-boten).

Säkerhet:
- Svarar bara på Tailscale och Pi:ns lokala nät (api/natverk.py); allt annat får 403.
- Allt utom /api/logga-in kräver en personlig nyckel (Authorization: Bearer ...); annars 401.
- Inloggning med engångskod från Telegram-botens /kod; spärr efter flera felaktiga koder.
- Ingen /docs eller /openapi.json (beskriver inte API:t för andra på samma wifi).
Hittas på det lokala nätet via mDNS-tjänsten _minbutik._tcp ("Min Butik").

Starta:  .venv/bin/python -m api.main      (port: API_PORT, standard 8484)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import enheter
import etikett
import konfig
import oversatt
from api import annonser, etiketter, musik, natverk, system, appen, problem

log = logging.getLogger("butiksbot.api")
PORT = int(os.environ.get("API_PORT", "8484"))
VERSION = "0.4"
MDNS_TYP = "_minbutik._tcp.local."
inloggning = enheter.Inloggning()


# ---------- mDNS: appen hittar Pi:n på butikens wifi ----------

async def mdns_annonsera() -> None:
    """Annonserar API:t som 'Min Butik' på det lokala nätet och uppdaterar om adressen ändras."""
    from zeroconf import IPVersion, ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf
    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    info, adresser = None, None
    try:
        while True:
            nya = sorted(natverk.lokala_adresser())
            if nya != adresser:
                ny_info = ServiceInfo(MDNS_TYP, f"Min Butik.{MDNS_TYP}", port=PORT,
                                      addresses=[socket.inet_aton(a) for a in nya],
                                      properties={"version": VERSION}, server="minbutik-api.local.")
                if info:
                    await zc.async_unregister_service(info)
                if nya:
                    await zc.async_register_service(ny_info, allow_name_change=True)
                    log.info("mDNS: Min Butik på %s:%d", ", ".join(nya), PORT)
                info, adresser = (ny_info if nya else None), nya
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        if info:
            await zc.async_unregister_service(info)
        await zc.async_close()


async def hall_skrivaren_vaken() -> None:
    """Etikettskrivaren stänger av sig efter 60 min: en kort kontakt var 55:e minut, dygnet runt."""
    await asyncio.sleep(60)
    while True:
        ok = await asyncio.to_thread(etikett.hall_vaken)
        log.info("Etikettskrivaren väckt: %s", "ok" if ok else "svarade inte")
        await asyncio.sleep(etikett.VAKEN_MINUTER * 60)


@asynccontextmanager
async def livstid(app: FastAPI):
    uppgift = asyncio.create_task(mdns_annonsera())
    vaken = asyncio.create_task(hall_skrivaren_vaken())
    yield
    uppgift.cancel()
    vaken.cancel()


app = FastAPI(title="Min Butik", docs_url=None, redoc_url=None, openapi_url=None, lifespan=livstid)
app.include_router(musik.router)
app.include_router(annonser.router)
app.include_router(etiketter.router)
app.include_router(system.router)
app.include_router(appen.router)
app.include_router(problem.router)


@app.middleware("http")
async def vakt(request: Request, call_next):
    ip = request.client.host if request.client else ""
    vag = natverk.via(ip)
    if vag is None:
        log.warning("Avvisad (fel nätverk): %s %s", ip, request.url.path)
        return JSONResponse({"fel": "Fel nätverk"}, status_code=403)
    request.state.via = vag
    oversatt.sprak.set("ar" if request.headers.get("x-sprak", "").lower() == "ar" else "sv")
    if request.url.path == "/api/logga-in" and request.method == "POST":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    enhet = enheter.kontrollera(auth[7:].strip() if auth.lower().startswith("bearer ") else "")
    if enhet is None:
        return JSONResponse({"fel": "Inte inloggad"}, status_code=401)
    request.state.enhet = enhet
    enheter.sedd(enhet["id"], ip, vag)
    return await call_next(request)


class LoggaIn(BaseModel):
    kod: str
    namn: str = "Telefon"


@app.post("/api/logga-in")
async def logga_in(data: LoggaIn, request: Request):
    try:
        nyckel, enhet = inloggning.logga_in(data.kod, data.namn, request.client.host)
    except enheter.InloggningsFel as e:
        return JSONResponse({"fel": str(e)}, status_code=403)
    return {"nyckel": nyckel, "enhet": enhet["id"], "namn": enhet["namn"]}


@app.get("/api/hej")
async def hej(request: Request):
    """Appen kollar anslutningen och ser hur den når Pi:n."""
    return {"butik": "Min Butik", "version": VERSION, "telefon": request.state.enhet["namn"],
            "via": request.state.via, "tid": datetime.now().isoformat(timespec="seconds")}


def main() -> None:
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # Som boten: lägsta prioritet på kärna 1-3. API:t gör samma tunga jobb (friläggning, rendering, bildsök)
    # när pappa gör annonser i appen, och kärna 0 är skyltens och musikens.
    konfig.lag_prioritet()
    # Lyssnar på alla adresser men vakt() släpper bara igenom Tailscale och det lokala nätet.
    uvicorn.run(app, host="0.0.0.0", port=PORT, proxy_headers=False, server_header=False,
                log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
