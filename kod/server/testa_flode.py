"""Testar botens flöde utan Telegram, med låtsas-meddelanden.
    .venv/bin/python testa_flode.py foto1 foto2 foto3
Skriver vad boten svarar och var videon hamnar. Publicerar inget."""
import asyncio
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("ALLOWED_IDS", "1")
import bot  # noqa: E402

FOTON = [Path(a) for a in sys.argv[1:]]
SVAR: list[str] = []


class Meddelande:
    _nr = 0

    def __init__(self, text="", caption="", photo=False, mgid=None):
        Meddelande._nr += 1
        self.message_id = Meddelande._nr
        self.chat_id = 1
        self.chat = SimpleNamespace(id=1)
        self.text, self.caption, self.media_group_id = text, caption, mgid
        self.photo = [SimpleNamespace(file_id=f"f{Meddelande._nr}")] if photo else None
        self.document = None

    async def reply_text(self, text, reply_markup=None):
        knappar = [k.text for rad in reply_markup.inline_keyboard for k in rad] if reply_markup else []
        SVAR.append(f"BOT: {text.splitlines()[0]}" + (f"  [knappar: {', '.join(knappar)}]" if knappar else ""))
        return SimpleNamespace(delete=self._noop, edit_text=self._edit)

    async def reply_video(self, fh, caption="", reply_markup=None, **kw):
        knappar = [k.text for rad in reply_markup.inline_keyboard for k in rad] if reply_markup else []
        SVAR.append(f"BOT: [VIDEO {fh.name}] {caption.replace(chr(10), ' | ')}  [knappar: {', '.join(knappar)}]")

    async def _noop(self):
        pass

    async def _edit(self, text):
        SVAR.append(f"BOT (ändrat): {text}")


class Fil:
    def __init__(self, kalla):
        self.kalla = kalla

    async def download_to_drive(self, mal):
        shutil.copy(self.kalla, mal)


filkarta: dict[str, Path] = {}
jobb: list = []


async def get_file(fid):
    return Fil(filkarta[fid])


ctx = SimpleNamespace(bot=SimpleNamespace(get_file=get_file),
                      job_queue=SimpleNamespace(run_once=lambda f, t, data=None: jobb.append((f, data))))


def upd(m):
    return SimpleNamespace(effective_message=m, effective_user=SimpleNamespace(id=1, full_name="test"),
                           callback_query=None)


async def skicka_foto(foto, caption="", mgid=None):
    m = Meddelande(caption=caption, photo=True, mgid=mgid)
    filkarta[m.photo[0].file_id] = foto
    SVAR.append(f"PAPPA: [foto {foto.name}] {caption}")
    await bot.bild(upd(m), ctx)


async def skicka_text(t):
    SVAR.append(f"PAPPA: {t}")
    await bot.text_meddelande(upd(Meddelande(text=t)), ctx)


async def kor_jobb():
    while jobb:
        f, data = jobb.pop(0)
        await f(SimpleNamespace(job=SimpleNamespace(data=data), **vars(ctx)))


async def main():
    print("== 1: text med '3 smaker' och inget foto ==")
    await skicka_text("Monster 19 kr 3 smaker")
    print("\n".join(SVAR)); SVAR.clear()

    print("\n== 2: ett foto i taget (svar på frågan) ==")
    await skicka_foto(FOTON[0])
    print("\n".join(SVAR)); SVAR.clear()
    await skicka_text("avbryt")
    SVAR.clear()

    print("\n== 3: album med 3 foton och text på första ==")
    t = time.time()
    for i, f in enumerate(FOTON[:3]):
        await skicka_foto(f, caption="Monster 19 kr" if i == 0 else "", mgid="album1")
    await kor_jobb()
    print("\n".join(SVAR)); SVAR.clear()
    print(f"(tid: {time.time() - t:.0f} s)")


if __name__ == "__main__":
    asyncio.run(main())
