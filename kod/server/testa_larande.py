"""Testar lärandet utan Telegram och utan att röra skylten:
rätta namn -> synonym, publicera -> produktminne + godkänt exempel,
samma vara igen -> sparad bild + "Annan bild", oklar text och avbrott -> logg.
    .venv/bin/python testa_larande.py foto.jpg
Allt skrivs till en tillfällig mapp; KANALER och lagret byts mot attrapper."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ALLOWED_IDS", "1")
import bot  # noqa: E402
import minne  # noqa: E402
import tjanst  # noqa: E402
import vader  # noqa: E402
import testa_flode as tf  # noqa: E402  (återanvänder låtsas-Telegram)

TMP = Path(tempfile.mkdtemp(prefix="butiksbot_larande_"))
minne.BILDER, minne.PRODUKTER = TMP / "minne/bilder", TMP / "minne/produkter.json"
minne.SYNONYMER, minne.GODKANDA = TMP / "minne/synonymer.json", TMP / "minne/godkanda.jsonl"
minne.OFORSTATT, minne.OVERGANGAR = TMP / "minne/oforstatt.jsonl", TMP / "minne/overgangar.json"


class Lager:
    def __init__(self):
        self.poster = {}

    def spara(self, p):
        self.poster[p["id"]] = p

    def aktiva(self):
        return [p for p in self.poster.values() if p.get("status") == "aktiv"]


bot.lager = tjanst.lager = Lager()
bot.TILLATNA.add(1)          # låtsasanvändaren i testa_flode
vader.VIKT_FIL, vader.LOGG_FIL = TMP / "vikter", TMP / "vader.jsonl"   # rör inte skyltens riktiga vikter


class Attrapp:
    namn = "attrapp"

    def publicera(self, post, video):
        return {"fil": "(inte publicerad, test)"}

    def ta_bort(self, post):
        pass


tjanst.KANALER = [Attrapp()]
bot.konfig.UTKAST_DIR = TMP / "utkast"
FOTO = Path(sys.argv[1])
SVAR = tf.SVAR


async def tryck(typ: str) -> None:
    pid = next(reversed(bot.utkast)) if bot.utkast else ""
    m = tf.Meddelande()

    async def ingen(*a, **k):
        pass

    async def ny_text(caption=None, **k):
        SVAR.append(f"BOT (ändrat): {caption}")
    q = SimpleNamespace(data=f"{typ}:{pid}", message=m, answer=ingen, edit_message_reply_markup=ingen,
                        edit_message_caption=ny_text)
    SVAR.append(f"PAPPA: [trycker {typ}]")
    await bot.knapp(SimpleNamespace(effective_message=m, callback_query=q,
                                    effective_user=SimpleNamespace(id=1, full_name="test")), tf.ctx)


def visa(rubrik: str) -> None:
    print(f"\n== {rubrik} ==")
    print("\n".join(SVAR))
    SVAR.clear()


async def main():
    await tf.skicka_foto(FOTO, caption="redbull 15 + pant")
    visa("1: foto + 'redbull 15 + pant'")
    await tryck("namn")
    await tf.skicka_text("Red Bull Original")
    visa("2: rätta namnet")
    await tryck("pub")
    visa("3: publicera")
    await tf.skicka_text("redbull 12 kr 3d")
    visa("4: samma vara igen, bara text (ska ta bilden ur minnet)")
    await tryck("annan")
    visa("5: Annan bild")
    await tf.skicka_text("avbryt")
    await tf.skicka_text("kan du 12 13 14 15 16 göra")
    visa("6: avbrott och oklar text")
    for f in (minne.SYNONYMER, minne.PRODUKTER, minne.GODKANDA, minne.OFORSTATT, minne.OVERGANGAR):
        print(f"\n--- {f.name} ---")
        print(f.read_text(encoding="utf-8").strip() if f.exists() else "(saknas)")
    print("\nBilder i minnet:", sorted(p.name for p in minne.BILDER.glob("*")))
    print("Övergångar per video:", [p.get("overgang") for p in bot.lager.poster.values()])


asyncio.run(main())
