"""Testar app-API:ts säkerhet och inloggning på riktigt (uvicorn + HTTP), i en tillfällig datamapp.
    .venv/bin/python testa_api.py            (kör på Pi:n; rör inga riktiga telefoner eller koder)
Kontrollerar: nyckel krävs överallt, engångskod, spärr efter fel, spärrade telefoner, nätverksfilter,
att API:t nås via lokal adress och Tailscale, och att mDNS-annonsen syns."""
import asyncio
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

os.environ["API_PORT"] = "8485"
import httpx  # noqa: E402
import uvicorn  # noqa: E402

import enheter  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_api_"))
for namn in ("ENHETER", "KODER", "SEDD", "LOGG"):
    setattr(enheter, namn, TMP / getattr(enheter, namn).name)
from api import main, natverk  # noqa: E402

PORT = 8485
resultat = []


def kolla(namn: str, villkor: bool, info: str = "") -> None:
    resultat.append(villkor)
    print(f"{'OK ' if villkor else 'FEL'} {namn}{'  (' + info + ')' if info else ''}")


def starta() -> None:
    server = uvicorn.Server(uvicorn.Config(main.app, host="0.0.0.0", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", PORT), 0.2).close()
            return
        except OSError:
            time.sleep(0.2)


async def test() -> None:
    starta()
    lokal = natverk.lokala_adresser()[0]
    bas = f"http://{lokal}:{PORT}"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{bas}/api/hej")
        kolla("utan nyckel: 401", r.status_code == 401, str(r.status_code))
        r = await c.get(f"{bas}/okand/sida")
        kolla("okänd adress utan nyckel: 401 (avslöjar inget)", r.status_code == 401)
        r = await c.get(f"{bas}/docs")
        kolla("ingen /docs", r.status_code == 401)
        r = await c.get(f"{bas}/api/hej", headers={"Authorization": "Bearer pahittad"})
        kolla("påhittad nyckel: 401", r.status_code == 401)

        # Felaktiga koder från samma adress -> spärr
        enheter.ny_kod()
        for i in range(5):
            r = await c.post(f"{bas}/api/logga-in", json={"kod": f"00000{i}", "namn": "Test"})
        r = await c.post(f"{bas}/api/logga-in", json={"kod": "999999", "namn": "Test"})
        kolla("spärr efter 5 fel", r.status_code == 403 and "kvart" in r.json()["fel"], r.json()["fel"])

        # Rätt kod (spärren gäller adressen; nollställ för testets skull)
        main.inloggning.fel.clear()
        kod = enheter.ny_kod()
        r = await c.post(f"{bas}/api/logga-in", json={"kod": kod, "namn": "Pappas telefon"})
        kolla("rätt kod ger nyckel", r.status_code == 200 and len(r.json().get("nyckel", "")) > 30)
        nyckel, enhet = r.json()["nyckel"], r.json()["enhet"]
        r = await c.post(f"{bas}/api/logga-in", json={"kod": kod, "namn": "Inkräktare"})
        kolla("koden går inte att använda två gånger", r.status_code == 403)
        h = {"Authorization": f"Bearer {nyckel}"}
        r = await c.get(f"{bas}/api/hej", headers=h)
        kolla("nyckel fungerar lokalt", r.status_code == 200 and r.json()["via"] == "lokalt", r.text[:120])
        r = await c.get(f"http://100.101.102.103:{PORT}/api/hej", headers=h)
        kolla("nyckel fungerar via Tailscale", r.status_code == 200 and r.json()["via"] == "tailscale",
              r.json().get("via", ""))
        kolla("nyckeln sparas inte i klartext", nyckel not in enheter.ENHETER.read_text())

        # Spärra telefonen
        enheter.sparra(enhet)
        r = await c.get(f"{bas}/api/hej", headers=h)
        kolla("spärrad telefon: 401", r.status_code == 401)
        enheter.sparra(enhet, False)
        r = await c.get(f"{bas}/api/hej", headers=h)
        kolla("öppnad igen: 200", r.status_code == 200)

        # Utgången kod
        kod = enheter.ny_kod()
        import json
        k = json.loads(enheter.KODER.read_text()); k["giltig_till"] = time.time() - 1
        enheter.KODER.write_text(json.dumps(k))
        r = await c.post(f"{bas}/api/logga-in", json={"kod": kod, "namn": "Sen"})
        kolla("utgången kod nekas", r.status_code == 403)

        # 20 fel totalt (från olika adresser) gör koden ogiltig
        kod = enheter.ny_kod()
        for i in range(20):
            main.inloggning.fel.clear()
            await c.post(f"{bas}/api/logga-in", json={"kod": "123123" if kod != "123123" else "321321"})
        main.inloggning.fel.clear()
        r = await c.post(f"{bas}/api/logga-in", json={"kod": kod, "namn": "Efter 20 fel"})
        kolla("efter 20 fel totalt nekas även rätt kod", r.status_code == 403)

    # Nätverksfiltret
    kolla("containerd/docker-nät avvisas", natverk.via("172.17.0.2") is None)
    kolla("främmande adress avvisas", natverk.via("8.8.8.8") is None)
    kolla("Tailscale släpps in", natverk.via("100.101.102.103") == "tailscale")

    # mDNS: syns tjänsten "Min Butik" på nätet?
    def leta():
        from zeroconf import Zeroconf
        zc = Zeroconf()
        try:
            for _ in range(10):
                i = zc.get_service_info(main.MDNS_TYP, f"Min Butik.{main.MDNS_TYP}", timeout=1000)
                if i:
                    return i
        finally:
            zc.close()
    info = await asyncio.to_thread(leta)
    # Kör den riktiga tjänsten (port 8484) svarar den på namnet; testinstansen får då ett eget namn.
    kolla("mDNS: 'Min Butik' hittas", info is not None and info.port in (PORT, 8484),
          ", ".join(info.parsed_addresses()) if info else "")
    print(f"\n{sum(resultat)}/{len(resultat)} OK. Logg: {enheter.LOGG}")


asyncio.run(test())
