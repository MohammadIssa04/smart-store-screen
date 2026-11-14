"""Testar den enda volymkontrollen (tyst, tillfällig mapp; systemvolymen rörs inte):
  1. appens volym ändrar bara musikspelaren (mpv), sparas och gäller efter omstart
  2. systemvolymen är oförändrad efteråt
  3. vakten loggar byte av utgång och ändringar utifrån, och låset sätter fast nivå när ampen ansluter
    .venv/bin/python testa_volym.py
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_volym_"))
os.environ.update(BUTIKSMUSIK_AO="null", BUTIKSMUSIK_MPV_SOCK=str(TMP / "mpv.sock"),
                  BUTIKSMUSIK_STYR_SOCK=str(TMP / "styr.sock"))
from musik import bibliotek as bib  # noqa: E402
bib.DATA = TMP
from musik import volym as vol  # noqa: E402
vol.INSTALLNINGAR, vol.LOGG = TMP / "installningar.json", TMP / "volym.jsonl"
from musik import spelare  # noqa: E402
spelare.GAMLA = "finns-inte-test.service"
from api import musik as api_musik  # noqa: E402

res = []


def kolla(namn, ok, info=""):
    res.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}")


async def starta():
    s = spelare.Spelare()
    t = asyncio.create_task(s.kor())
    await asyncio.sleep(3)
    return s, t


async def stoppa(s, t):
    t.cancel()
    if s.mpv and s.mpv.returncode is None:
        s.mpv.terminate()
        await s.mpv.wait()


async def main():
    _, sys_fore = vol.systemutgang()
    s, t = await starta()
    st = await api_musik.styr("volym", procent=60, telefon="Testtelefon")
    kolla("appen sätter 60: spelarens volym 60", await s.egenskap("volume") == 60 and st.get("volym") == 60,
          await s.egenskap("volume"))
    kolla("sparad i installningar.json", json.loads(vol.INSTALLNINGAR.read_text())["volym"] == 60)
    await stoppa(s, t)
    s, t = await starta()
    kolla("efter omstart: fortfarande 60", await s.egenskap("volume") == 60, await s.egenskap("volume"))
    await stoppa(s, t)
    _, sys_efter = vol.systemutgang()
    kolla("systemvolymen orörd", sys_fore == sys_efter, f"{sys_fore} -> {sys_efter}")

    # Vakten med låtsade utgångar (systemet rörs inte)
    forlopp = iter([("alsa_output.x", 0.40), ("alsa_output.x", 0.40), ("alsa_output.x", 0.44),
                    ("bluez_output.41_42", 0.44), ("bluez_output.41_42", 1.0), ("bluez_output.41_42", 0.70)])
    satta = []
    vol.systemutgang = lambda: next(forlopp)
    vol.satt_systemvolym = lambda v: satta.append(v)
    vol.LAST_SYSTEMVOLYM = 1.0
    v = vol.Vakt()
    v.kontrollera()       # oförändrat
    v.kontrollera()       # 0.40 -> 0.44 utifrån
    v.kontrollera()       # ampen ansluter med sparad 44 % -> låset sätter 100 %
    v.kontrollera()       # (systemutgang efter låset läses i samma anrop)
    rader = [json.loads(r) for r in vol.LOGG.read_text().splitlines()]
    h = [r["handelse"] for r in rader]
    kolla("ändring utifrån loggas", "systemvolym_andrad" in h)
    kolla("ampen ansluter loggas", "ny_utgang" in h)
    kolla("låset sätter fast nivå vid anslutning", satta == [1.0] and "systemvolym_last" in h, satta)
    kolla("appens ändring loggad med telefon", any(r.get("orsak") == "appen" and r.get("telefon") == "Testtelefon"
                                                     for r in rader))
    print("\nLogg:")
    for r in rader:
        print("  ", json.dumps(r, ensure_ascii=False))
    print(f"\n{sum(res)}/{len(res)} OK")


asyncio.run(main())
