"""Musikspelaren (tjänsten butiksmusik): spelar blockens låtar i rätt tid, styrs från appen.

- mpv i bakgrunden (bara ljud), styrs via IPC-socketen /tmp/butiksmusik.sock
- Egen styrsocket /tmp/butiksmusik-styr.sock som API:t pratar med (en JSON-rad per kommando):
  status | paus | spela | nasta | loop {"pa": bool} | volym {"procent": n} | spela_nu {"url", "titel", "artist"}
- Spelar bara under öppettid (blocken 10-21). Paus gäller till man trycker spela, eller till nästa dag.
- Spelar INTE så länge den gamla musiken (musik.service) är igång, så att två spelare aldrig låter samtidigt.
- Fyller på blocken med nya låtar varje morgon (och direkt om ett block saknar låtar).
Starta:  .venv/bin/python -m musik.spelare
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import konfig
from musik import bibliotek as bib
from musik import hamtning
from musik import inledning
from musik import volym as vol

log = logging.getLogger("butiksbot.musik")
MPV_SOCK = os.environ.get("BUTIKSMUSIK_MPV_SOCK", "/tmp/butiksmusik.sock")
STYR_SOCK = konfig.STYR_SOCK
SPELAT = bib.DATA / "spelat.jsonl"
FYLL_TIMME = 7            # påfyllning varje morgon före öppning
OPPET_FRAN, OPPET_TILL = 10, 21   # skylten visas: inga tunga musikjobb då
GAMLA = "musik.service"
GAMLA_YT_FLAGGA = "/tmp/yt-spelar"      # gamla musiksidan (musik-kontroll.py) spelar YouTube


class Spelare:
    def __init__(self) -> None:
        self.mpv: asyncio.subprocess.Process | None = None
        self.aktuell: dict | None = None      # låten som spelas (från biblioteket eller "spela nu")
        self.pausad = False
        self.pausad_datum: date | None = None
        self.loop = False
        self.senast_fyllt: date | None = None
        self.fyller = False
        self.gamla_kor = False
        self._las = asyncio.Lock()
        self._gamla_koll = 0.0
        self.senaste_fyllning = -1e9

    # ---------- mpv ----------

    async def starta_mpv(self) -> None:
        if os.path.exists(MPV_SOCK):
            os.remove(MPV_SOCK)
        self.mpv = await asyncio.create_subprocess_exec(
            "mpv", "--idle=yes", "--no-video", "--no-terminal", f"--ao={os.environ.get('BUTIKSMUSIK_AO', 'pipewire')}", f"--volume={vol.spelarvolym()}", "--volume-max=100",
            "--ytdl-format=bestaudio", f"--script-opts=ytdl_hook-ytdl_path={hamtning.YTDLP}",
            f"--input-ipc-server={MPV_SOCK}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        for _ in range(50):
            if os.path.exists(MPV_SOCK):
                return
            await asyncio.sleep(0.1)

    async def ipc(self, *kommando) -> dict:
        try:
            r, w = await asyncio.wait_for(asyncio.open_unix_connection(MPV_SOCK), 2)
            w.write((json.dumps({"command": list(kommando)}) + "\n").encode())
            await w.drain()
            while True:
                rad = await asyncio.wait_for(r.readline(), 2)
                if not rad:
                    return {}
                svar = json.loads(rad)
                if "event" not in svar:          # hoppa över händelser, vänta på svaret
                    w.close()
                    return svar
        except (OSError, asyncio.TimeoutError, ValueError):
            return {}

    async def egenskap(self, namn: str):
        return (await self.ipc("get_property", namn)).get("data")

    # ---------- spela ----------

    async def spela(self, kalla: str, lat: dict) -> None:
        self.aktuell = lat
        # Pappas startpunkt (lång inledning): mpv:s 'start' gäller nästa fil som laddas. Sätts före varje låt,
        # också till 'none', så att en startpunkt aldrig hänger med till nästa låt. Filen ändras inte.
        start = bib.startpunkt(lat.get("id")) if lat.get("kalla") != "nu" else 0
        await self.ipc("set_property", "start", str(start) if start else "none")
        await self.ipc("loadfile", kalla, "replace")
        await self.ipc("set_property", "pause", False)
        if lat.get("id") and lat.get("kalla") != "nu":
            bib.spelad(lat["id"])
        with open(SPELAT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tid": datetime.now().isoformat(timespec="seconds"), "id": lat.get("id"),
                                "titel": lat.get("titel"), "block": lat.get("block")}, ensure_ascii=False) + "\n")
        log.info("Spelar: %s – %s", lat.get("artist", ""), lat.get("titel"))

    async def nasta(self) -> None:
        b = bib.block_nu()
        if not b:
            return
        if self.loop and self.aktuell:
            await self.spela(self.aktuell.get("fil") or self.aktuell["url"], self.aktuell)
            return
        lat = bib.nasta(b["id"])
        if lat and Path(lat["fil"]).is_file():
            await self.spela(lat["fil"], lat)
        elif lat:
            log.warning("Filen saknas: %s", lat["fil"])
        else:
            log.warning("Blocket %s har inga låtar", b["id"])

    async def tick(self) -> None:
        """Körs varje sekund: rätt sak ska spelas just nu."""
        async with self._las:
            if self.pausad and self.pausad_datum and self.pausad_datum != date.today():
                self.pausad = False                     # paus gäller som längst till nästa dag
            if asyncio.get_running_loop().time() - self._gamla_koll > 5:
                self._gamla_koll = asyncio.get_running_loop().time()
                # Den gamla musiken (tjänsten, eller gamla musiksidan som spelar YouTube) går före:
                # två spelare får aldrig låta samtidigt.
                self.gamla_kor = (subprocess.run(["systemctl", "--user", "is-active", "--quiet", GAMLA]).returncode == 0
                                  or os.path.exists(GAMLA_YT_FLAGGA))
            b = bib.block_nu()
            if self.gamla_kor or not b:
                if await self.egenskap("idle-active") is False:
                    await self.ipc("stop")
                    self.aktuell = None
                return
            if self.pausad:
                return
            if await self.egenskap("idle-active"):     # inget spelas (låten slut, start, nytt block)
                await self.nasta()

    # ---------- påfyllning ----------

    async def fyll_vid_behov(self) -> None:
        if self.fyller:
            return
        # Under målet: fyll på varje timme (8 låtar per block och gång) tills listan är full.
        # Varje morgon: 2 nya låtar per block in och de 2 mest spelade till arkivet (listan byts varje dag).
        # Hämtning och ljudanalys (yt-dlp, ffmpeg, Gemini) värmer Pi:n och får skylten att hacka:
        # bara när skylten är av (21-10), aldrig under öppettid.
        if OPPET_FRAN <= datetime.now().hour < OPPET_TILL:
            return
        under_mal = any(len(bib.latar(b["id"])) < b.get("mal", 40) for b in bib.block())
        okontrollerade = any(inledning.behover_kontroll(l) for l in bib.latar())
        timme_sedan = asyncio.get_running_loop().time() - self.senaste_fyllning > 3600
        morgon = datetime.now().hour == FYLL_TIMME and self.senast_fyllt != date.today()
        if not (((under_mal or okontrollerade) and timme_sedan) or morgon):
            return
        self.senaste_fyllning = asyncio.get_running_loop().time()
        self.fyller = True
        try:
            def jobb():
                konfig.lag_prioritet()
                n = hamtning.fyll(byt=morgon)
                # Var börjar sången? Några låtar i taget (de börjar sedan där, se bib.startpunkt).
                inledning.kontrollera_nagra(12)
                return n
            antal = await asyncio.to_thread(jobb)
            log.info("Påfyllning klar: %d nya låtar", antal)
            if morgon:
                self.senast_fyllt = date.today()
        except Exception:
            log.exception("Påfyllningen misslyckades")
        finally:
            self.fyller = False

    # ---------- styrning från API:t ----------

    async def status(self) -> dict:
        b = bib.block_nu()
        pos, langd = await self.egenskap("time-pos"), await self.egenskap("duration")
        a = self.aktuell or {}
        # Volymvakten läser utgången var 5:e sekund: använd det (wpctl två gånger tog ca 400 ms per anrop).
        v = getattr(self, "vakt", None)
        utgang, sysvol = (v.namn, v.vol) if v else await asyncio.to_thread(vol.systemutgang)
        return {"spelar": bool(self.aktuell) and not self.pausad and not self.gamla_kor,
                "pausad": self.pausad, "loop": self.loop, "titel": a.get("titel"), "artist": a.get("artist"),
                "id": a.get("id"), "block": b["id"] if b else None, "block_namn": b["namn"] if b else None,
                "block_tid": f"{b['fran']:02d}–{b['till']:02d}" if b else None,
                "start": bib.startpunkt(a.get("id")) if a.get("kalla") != "nu" else 0,
                "favorit": bib.ar_favorit(a.get("id")), "forslag": bib.auto_start(a) or None,
                "kan_valja": bool(a.get("id")) and a.get("kalla") != "nu",
                "position": round(pos or 0), "langd": round(langd or a.get("langd") or 0), "volym": vol.spelarvolym(),
                "systemvolym": round(sysvol * 100) if sysvol is not None else None,
                "ampen_ansluten": bool(utgang and utgang.startswith("bluez")),
                "gamla_musiken_kor": self.gamla_kor, "fyller_pa": self.fyller, "oppet": b is not None}

    async def kommando(self, k: dict) -> dict:
        cmd = k.get("cmd")
        async with self._las:
            if cmd == "paus":
                self.pausad, self.pausad_datum = True, date.today()
                vol.spara_paus(date.today().isoformat())
                await self.ipc("set_property", "pause", True)
            elif cmd == "spela":
                self.pausad = False
                vol.spara_paus(None)
                await self.ipc("set_property", "pause", False)
            elif cmd == "nasta":
                self.pausad, self.loop = False, False
                await self.nasta()
            elif cmd == "loop":
                self.loop = bool(k.get("pa"))
            elif cmd == "volym":
                # Appen styr bara musikspelarens egen volym; systemvolymen rörs inte.
                p = max(0, min(100, int(k.get("procent", 50))))
                fore = vol.spelarvolym()
                await self.ipc("set_property", "volume", p)
                vol.spara_spelarvolym(p)
                vol.logga("spelarvolym", fran=fore, till=p, orsak="appen", telefon=k.get("telefon"))
            elif cmd == "spela_nu":
                self.pausad = False
                await self.spela(k["url"], {"titel": k.get("titel"), "artist": k.get("artist", ""),
                                            "id": k.get("id"), "url": k["url"], "kalla": "nu",
                                            "langd": k.get("langd")})
            elif cmd == "hoppa":
                # Förhandslyssning: hoppa till startpunkten i låten som spelas nu.
                if self.aktuell:
                    await self.ipc("seek", max(0, int(k.get("sek", 0))), "absolute")
                    if self.pausad:
                        self.pausad = False
                        vol.spara_paus(None)
                        await self.ipc("set_property", "pause", False)
            elif cmd == "fyll":
                asyncio.create_task(self.fyll_vid_behov_tvinga())
            elif cmd != "status":
                return {"fel": "okänt kommando"}
        return await self.status()

    async def fyll_vid_behov_tvinga(self) -> None:
        self.senast_fyllt = None
        if not self.fyller:
            self.fyller = True
            try:
                def jobb():
                    konfig.lag_prioritet()
                    return hamtning.fyll()
                await asyncio.to_thread(jobb)
            finally:
                self.fyller = False

    async def hantera(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            rad = await asyncio.wait_for(r.readline(), 5)
            svar = await self.kommando(json.loads(rad or b"{}"))
        except Exception as e:
            log.exception("Styrkommando misslyckades")
            svar = {"fel": str(e)}
        w.write((json.dumps(svar, ensure_ascii=False) + "\n").encode())
        await w.drain()
        w.close()

    # ---------- huvudloop ----------

    async def kor(self) -> None:
        await self.starta_mpv()
        if os.path.exists(STYR_SOCK):
            os.remove(STYR_SOCK)
        server = await asyncio.start_unix_server(self.hantera, STYR_SOCK)
        os.chmod(STYR_SOCK, 0o600)
        if vol.pausad_datum() == date.today().isoformat():       # pausad i dag: förblir pausad efter omstart
            self.pausad, self.pausad_datum = True, date.today()
        log.info("Musikspelaren startad (volym %d%s)", vol.spelarvolym(), ", pausad" if self.pausad else "")
        vakt = self.vakt = vol.Vakt()
        sekund = 0
        async with server:
            while True:
                if self.mpv.returncode is not None:
                    log.warning("mpv avslutades, startar om")
                    await self.starta_mpv()
                try:
                    await self.tick()
                except Exception:
                    log.exception("Fel i spelaren")
                if sekund % 60 == 5:
                    asyncio.create_task(self.fyll_vid_behov())
                if sekund % 5 == 0:
                    try:                         # byte av utgång / ändringar utifrån loggas (och låset)
                        await asyncio.to_thread(vakt.kontrollera)
                    except Exception:
                        log.exception("Volymvakten")
                sekund += 1
                await asyncio.sleep(1)


def main() -> None:
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=logging.INFO)
    asyncio.run(Spelare().kor())


if __name__ == "__main__":
    main()
