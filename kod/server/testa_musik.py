"""Testar musikdelen i en tillfällig mapp, utan ljud och utan att röra den gamla musiken:
  1. spelordningen (blandat, ny ordning varje dag, ingen upprepning förrän alla spelats)
  2. filtret på riktiga YouTube-sökningar per block (vad som skulle hämtas)
  3. hämtning av två riktiga låtar
  4. spelaren (mpv utan ljud) styrd via API:t: status, nästa, paus, spela, loop, spela nu, ta bort
    .venv/bin/python testa_musik.py
"""
import asyncio
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_musik_"))
os.environ.update(BUTIKSMUSIK_AO="null", BUTIKSMUSIK_MPV_SOCK=str(TMP / "mpv.sock"),
                  BUTIKSMUSIK_STYR_SOCK=str(TMP / "styr.sock"))

from musik import bibliotek as bib  # noqa: E402
bib.DATA, bib.FILER = TMP / "data", TMP / "filer"
bib.BLOCK_FIL, bib.BIBLIOTEK_FIL, bib.ORDNING_FIL = (bib.DATA / "block.json", bib.DATA / "bibliotek.json",
                                                     bib.DATA / "ordning.json")
bib.ARKIV = bib.FILER / "arkiv"
from musik import hamtning, spelare  # noqa: E402
hamtning.LOGG = bib.DATA / "hamtning.jsonl"
spelare.SPELAT = bib.DATA / "spelat.jsonl"
spelare.GAMLA = "finns-inte-test.service"        # låtsas att den gamla musiken är avstängd

resultat = []


def kolla(namn, ok, info=""):
    resultat.append(bool(ok))
    print(f"{'OK ' if ok else 'FEL'} {namn}{'  (' + str(info) + ')' if info != '' else ''}")


def test_ordning():
    print("== 1. Spelordning")
    for i in range(6):
        bib.lagg_till({"id": f"lat{i}", "titel": f"Låt {i}", "artist": "Test", "block": "fairouz",
                       "langd": 180, "fil": "/dev/null", "kalla": "test"})
    d = date(2026, 11, 13)
    dag1 = [bib.nasta("fairouz", d)["id"] for _ in range(6)]
    kolla("varv 1: alla sex en gång", sorted(dag1) == [f"lat{i}" for i in range(6)], " ".join(dag1))
    dag1b = [bib.nasta("fairouz", d)["id"] for _ in range(6)]
    kolla("varv 2: alla igen, inte samma låt två gånger i rad", sorted(dag1b) == sorted(dag1) and dag1b[0] != dag1[-1])
    halv = [bib.nasta("fairouz", d)["id"] for _ in range(3)]
    dag2 = [bib.nasta("fairouz", d + timedelta(days=1))["id"] for _ in range(3)]
    kolla("ny dag: resten av varvet, ingen upprepning", not set(halv) & set(dag2) and len(set(halv + dag2)) == 6,
          f"{halv} | {dag2}")
    bib.lagg_till({"id": "ny", "titel": "Ny låt", "artist": "Test", "block": "fairouz", "langd": 180,
                   "fil": "/dev/null", "kalla": "test"})
    nasta7 = [bib.nasta("fairouz", d + timedelta(days=2))["id"] for _ in range(7)]
    kolla("ny låt kommer med i nästa varv/nuvarande", "ny" in nasta7)
    bib.ta_bort("lat0", "fairouz")
    kolla("borttagen låt spelas inte", "lat0" not in [bib.nasta("fairouz", d)["id"] for _ in range(10)])
    o1 = [bib.nasta("klassisk", date(2026, 1, 1)) for _ in range(0)]  # (tomt block)
    kolla("tomt block ger ingen låt", bib.nasta("umm") is None and not o1)


def test_filter():
    print("\n== 2. Filter på riktiga sökningar (inget hämtas)")
    for b in bib.block():
        valda, bort = [], 0
        for artist in b["artister"][:3]:
            for t in hamtning.sok(artist["sok"][0], 15):
                if hamtning.ar_lat(t, artist, b["max_min"]):
                    valda.append(f"{t['titel'][:55]} ({t['langd'] // 60}:{t['langd'] % 60:02d})")
                else:
                    bort += 1
        print(f"  {b['namn']}: {len(valda)} godkända, {bort} bortvalda. Exempel:")
        for v in valda[:4]:
            print("     ", v)
        kolla(f"{b['namn']}: hittar låtar", len(valda) >= 3, len(valda))


async def test_spelare():
    print("\n== 3. Hämtning och 4. spelaren (utan ljud)")
    import musik.spelare as sp
    t = {"id": "5UAMf21kPk4", "titel": "Ana La Habibi", "kanal": "Fairuz", "langd": 181}
    l1 = await asyncio.to_thread(hamtning.hamta, t, "klassisk", "Fairouz", "test")
    t2 = {"id": "BTICpPmf1yA", "titel": "Ya Ana Ya Ana - Fairuz", "kanal": "Fairuzyat", "langd": 143}
    l2 = await asyncio.to_thread(hamtning.hamta, t2, "klassisk", "Fairouz", "test")
    kolla("två låtar hämtade", l1 and l2 and Path(l1["fil"]).stat().st_size > 1_000_000,
          f"{Path(l1['fil']).name if l1 else '-'}, {Path(l2['fil']).name if l2 else '-'}")

    bib.block_nu = lambda nu=None: bib.hitta_block("klassisk")      # låtsas att det är 12-18
    sp.bib.block_nu = bib.block_nu
    s = sp.Spelare()
    uppgift = asyncio.create_task(s.kor())
    await asyncio.sleep(4)
    from api import musik as api_musik
    st = await api_musik.styr("status")
    kolla("spelar en låt i rätt block", st.get("titel") and st.get("block") == "klassisk", st.get("titel"))
    forsta = st.get("id")
    st = await api_musik.styr("nasta")
    kolla("nästa: byter låt", st.get("id") and st.get("id") != forsta, st.get("titel"))
    st = await api_musik.styr("paus")
    await asyncio.sleep(2)
    kolla("paus", st.get("pausad") and await s.egenskap("pause") is True)
    st = await api_musik.styr("spela")
    kolla("spela igen", not st.get("pausad") and await s.egenskap("pause") is False)
    st = await api_musik.styr("loop", pa=True)
    nu = st.get("id")
    await s.ipc("seek", 99999, "absolute")              # spola till slutet: låten tar slut
    await asyncio.sleep(4)
    st = await api_musik.styr("status")
    kolla("loop: samma låt igen när den tagit slut", st.get("id") == nu, st.get("titel"))
    await api_musik.styr("loop", pa=False)
    st = await api_musik.styr("spela_nu", url="https://www.youtube.com/watch?v=-0BI9-CdrMk", id="-0BI9-CdrMk",
                              titel="Kan Endena Tahoun", artist="Fairuzyat", langd=173)
    await asyncio.sleep(10)
    pos = await s.egenskap("time-pos")
    kolla("spela nu (strömmat från YouTube)", st.get("titel") == "Kan Endena Tahoun" and (pos or 0) > 0,
          f"position {pos}")
    uppgift.cancel()
    if s.mpv and s.mpv.returncode is None:
        s.mpv.terminate()


asyncio.run(asyncio.to_thread(test_ordning))
test_filter()
asyncio.run(test_spelare())
print(f"\n{sum(resultat)}/{len(resultat)} OK  (testmapp {TMP})")
