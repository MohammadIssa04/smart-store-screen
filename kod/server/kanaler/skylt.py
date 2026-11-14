"""TV-skylten: lägger videon i skylt/erbjudanden/ där skylt-play hittar den.

Filnamnet börjar med t<ÅÅÅÅMMDDTTMM>_ = när erbjudandet går ut, så att
skylt-play hoppar över utgångna filer även om boten skulle ligga nere."""
from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

import konfig
from lager import tid

from .bas import Kanal


def _slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "erbjudande"


def _ledigt_namn(mal: Path) -> Path:
    if not mal.exists():
        return mal
    i = 2
    while True:
        kandidat = mal.with_name(f"{mal.stem}-{i}{mal.suffix}")
        if not kandidat.exists():
            return kandidat
        i += 1


class Skylt(Kanal):
    namn = "skylt"

    def publicera(self, post: dict, video: Path) -> dict:
        konfig.ERBJUDANDEN_DIR.mkdir(parents=True, exist_ok=True)
        utgar = tid(post["utgar"])
        namn = f"t{utgar:%Y%m%d%H%M}_{_slug(post['rubrik'] or post['pris'])}_{post['id']}.mp4"
        mal = _ledigt_namn(konfig.ERBJUDANDEN_DIR / namn)
        # Kopiera till .part och byt namn: skylt-play ser aldrig en halvfärdig fil.
        tmp = mal.with_name(mal.name + ".part")
        # Skylten visar videorna liggande och redan vridna (se skyltvrid.py); originalet finns i utkast/.
        # Oftast är den liggande kopian redan gjord medan pappa tittade på förhandsvisningen.
        import skyltvrid
        fardig = skyltvrid.liggande_kopia(Path(video))
        pagar = fardig.with_name(fardig.name + ".tmp.part")
        for _ in range(90):                      # förvridningen pågår: vänta på den i stället för att göra om
            if fardig.is_file() or not pagar.exists():
                break
            time.sleep(1)
        if fardig.is_file() and not skyltvrid.ar_staende(fardig):
            shutil.copy2(fardig, tmp)
        else:
            shutil.copy2(video, tmp)
            skyltvrid.vrid(tmp, arkivera=False)
        os.replace(tmp, mal)
        return {"fil": str(mal)}

    def nytt_slut(self, post: dict, utgar) -> dict:
        """Förlängd annons: byt t<ÅÅÅÅMMDDTTMM>-prefixet i filnamnet (skylt-play läser slutet därifrån)."""
        info = dict(post.get("kanaler", {}).get(self.namn) or {})
        fil = Path(info.get("fil", ""))
        if info.get("fil") and fil.is_file():
            ny = _ledigt_namn(fil.with_name(re.sub(r"^t\d{12}_", f"t{utgar:%Y%m%d%H%M}_", fil.name)))
            os.replace(fil, ny)
            info["fil"] = str(ny)
        return info

    def byt_video(self, post: dict, video: Path) -> dict:
        """Ny video för en publicerad annons (t.ex. ny visningstid): samma filnamn på skylten, den gamla
        filen flyttas till arkivet (raderas inte)."""
        info = dict(post.get("kanaler", {}).get(self.namn) or {})
        fil = Path(info.get("fil", ""))
        if not info.get("fil") or not fil.is_file():
            return self.publicera(post, video)
        import skyltvrid
        tmp = fil.with_name(fil.name + ".part")
        shutil.copy2(video, tmp)
        skyltvrid.vrid(tmp, arkivera=False)
        konfig.ARKIV_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fil, _ledigt_namn(konfig.ARKIV_DIR / f"{fil.stem}.fore{time.strftime('%Y%m%d%H%M%S')}{fil.suffix}"))
        os.replace(tmp, fil)                     # i ett steg: skylt-play ser aldrig en halv fil
        return info

    def ta_bort(self, post: dict) -> None:
        info = post.setdefault("kanaler", {}).setdefault(self.namn, {})
        fil = Path(info.get("fil", ""))
        if info.get("fil") and fil.is_file():
            konfig.ARKIV_DIR.mkdir(parents=True, exist_ok=True)
            mal = _ledigt_namn(konfig.ARKIV_DIR / fil.name)
            shutil.move(str(fil), str(mal))
            info["arkiv"] = str(mal)
