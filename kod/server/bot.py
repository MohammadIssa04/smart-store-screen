"""Min Butik Telegram-bot.

Pappa skickar en bild ELLER ett namn (med eller utan pris):
  bild utan text  -> AI känner igen varan (och priset om det syns)
  bara namn       -> boten hämtar en produktbild från nätet
  pris saknas     -> boten frågar "Vilket pris?"
Sedan: video -> förhandsvisning -> Publicera / Annan bild / Avbryt -> TV-skylten.
Svarar bara på ID:n i ALLOWED_IDS."""
from __future__ import annotations

import asyncio
import functools
import logging
import shutil
import sys
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import bildsok
import enheter
import facebook
import igenkanning
import konfig
import tolka
import minne
import halsa
import skyltvrid
import tjanst
import vader
from tjanst import (avpublicera, beskriv, datum, lager, nytt_arende, rubrik_kort, tolka_text,
                    uppdatera_vikter, valj_kandidat)
from lager import tid
from video.animation import MAX_PRODUKTER

log = logging.getLogger("butiksbot")

TILLATNA = konfig.tillatna_id()
utkast: dict[str, dict] = {}     # id -> förhandsvisad post (ej publicerad)
vantar: dict[int, dict] = {}     # chatt -> ärende som väntar på svar (namn/pris/foto)
VANTETID = 1800                  # sekunder innan en obesvarad fråga glöms
album: dict[tuple, dict] = {}    # (chatt, media_group_id) -> bilder som samlas in
ALBUM_VANTETID = 2.5             # sekunder: Telegram skickar albumets bilder strax efter varandra

VECKODAGAR = ["mån", "tis", "ons", "tors", "fre", "lör", "sön"]

FOTOGUIDE = ("Så blir fotot snyggast:\n"
             "• Ställ varan mot en vägg\n"
             "• Håll mobilen rakt framifrån, i samma höjd som varan\n"
             "• Stå ett par steg bort och zooma lite\n"
             "• Bra ljus, ingen blixt")

HJALP = (
    "Hej! Skicka bara:\n\n"
    "📸 ett foto på varan – jag känner igen den själv (bäst!)\n"
    "📸📸📸 flera smaker? Skicka upp till 3 foton på en gång\n"
    "✍️ eller bara namnet, t.ex. \"banan\" – då ber jag om ett foto, eller letar på nätet om du vill\n\n"
    f"{FOTOGUIDE}\n\n"
    "Skriv gärna pris och dagar direkt, hur du vill:\n"
    "  bananer 10/kg 3 dagar\n  redbull 15 + pant\n  cola 2 för 30 5d\n  fynd bröd 10\n"
    "Saknas priset frågar jag. Utan dagar visas det i 7 dagar.\n"
    "Med \"fynd\" blir det Dagens fynd (till kl 21 i dag om du inte skriver dagar).\n\n"
    "Du får se videon först. Inget visas på skylten förrän du trycker Publicera. "
    "\n"
    "/visas – vad som visas just nu\n"
    "/ta_bort – ta bort ett erbjudande i förtid\n"
    "/vader – vädret och vilka varor som visas oftare\n"
    "/kod – inloggningskod till appen\n"
    "/telefoner – se och spärra telefoner som använder appen\n"
    "/avbryt – glöm det jag håller på med"
)


# ---------- behörighet ----------

def behorig(update: Update) -> bool:
    u = update.effective_user
    return u is not None and u.id in TILLATNA


def bara_behoriga(f):
    @functools.wraps(f)
    async def inre(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if behorig(update):
            return await f(update, context)
        u = update.effective_user
        log.warning("Obehörig: id=%s namn=%s", u.id if u else None, u.full_name if u else None)
        # Inställningsläge: tills tillåtelselistan är ifylld svarar boten med ID:t.
        if not TILLATNA and u and update.effective_message:
            await update.effective_message.reply_text(f"Ej behörig.\nDitt Telegram-ID: {u.id}")
        elif update.callback_query:
            await update.callback_query.answer("Ej behörig", show_alert=True)
    return inre


# ---------- ärenden ----------

def fotobeskrivning(a: dict) -> str:
    if a["antal"] > 1:
        return (f"📸 Ta {a['antal']} foton på {a['rubrik']}, ett per smak, och skicka dem "
                "– gärna alla på en gång (markera flera bilder).")
    return f"📸 Ta ett foto på {a['rubrik']} och skicka det."


def hamta_vantande(chatt: int) -> dict | None:
    a = vantar.get(chatt)
    if a and datetime.now().timestamp() - a["tid"] > VANTETID:
        vantar.pop(chatt, None)
        return None
    return a


async def fortsatt(msg: Message, context: ContextTypes.DEFAULT_TYPE, a: dict) -> None:
    """Fråga efter det som saknas, annars gör videon."""
    chatt = msg.chat_id
    a["tid"] = datetime.now().timestamp()

    if not a["rubrik"]:
        minne.logga_oforstatt("namn_saknas", a["text"])
        a["steg"] = "namn"
        vantar[chatt] = a
        await msg.reply_text("Vad heter varan?")
        return

    if not a["fotos"] and not a.get("webb") and not a.get("ny_bild"):
        # Varan har publicerats förut: återanvänd samma (redan frilagda) bild.
        sparad = minne.hitta_produkt(a["rubrik"])
        if sparad and len(sparad["bilder"]) >= a["antal"]:
            a["fotos"] = sparad["bilder"][:MAX_PRODUKTER]
            a["fran_minne"] = True
            a["fyller"] = False
            a["vartyp"] = a.get("vartyp") or sparad.get("vartyp")
            a["antal"] = max(a["antal"], len(a["fotos"]))
            await msg.reply_text(f"📦 Jag använder bilden på {sparad['namn']} från förra gången. "
                                 "Vill du ha en ny trycker du \"Annan bild\" under videon.")

    if not a["fotos"]:
        # Pappas egna foton på riktiga varor ser mest äkta ut, så de är förstahandsvalet.
        # Nätet är en reserv som han själv får välja.
        if a["antal"] > 1 and not a.get("webb") and not a.get("ny_bild") and igenkanning.tillganglig():
            a["webb"] = True
            await msg.reply_text(f"🔍 Letar bilder på {a['antal']} olika smaker av {a['rubrik']} … "
                                 "(tar några minuter). Vill du hellre använda egna foton går det bra att skicka dem.")
        if not a.get("webb"):
            a["steg"] = "foto"
            vantar[chatt] = a
            knappar = InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Leta bild på nätet i stället",
                                                                  callback_data="webb:")]])
            await msg.reply_text(f"{fotobeskrivning(a)}\n\n{FOTOGUIDE}", reply_markup=knappar)
            return
        if a.get("eget_foto"):
            await msg.reply_text(f"Fotot visar en hel låda. Jag letar en snygg bild på bara {a['rubrik']} i stället.")
        status = await msg.reply_text(f"🔍 Letar efter bilder på {a['rubrik']} … (kan ta ett par minuter)"
                                      if a["antal"] == 1 else "🔍 Letar …")
        hittade = [str(p) for p in await bildsok.hamta_bilder(a["rubrik"], Path(a["mapp"]), a["antal"])]
        await status.delete()
        if a["antal"] > 1:
            a["fotos"], a["kandidater"] = (hittade if len(hittade) >= 2 else []), []
            if len(hittade) >= 2 and len(hittade) < a["antal"]:
                await msg.reply_text(f"Jag hittade bara {len(hittade)} snygga bilder på olika smaker. "
                                     "Jag gör videon med dem.")
        else:
            a["kandidater"], a["nr"] = hittade, 0
            if valj_kandidat(a):
                a["fyller"] = False
            elif tjanst.tillbaka_till_eget_foto(a):
                await msg.reply_text(f"Jag hittade ingen snygg bild på bara {a['rubrik']}, "
                                     "så jag visar ditt foto i en ram.")
        if not a["fotos"]:
            a["steg"] = "foto"
            vantar[chatt] = a
            if a["antal"] > 1:
                await msg.reply_text(f"Jag hittade inte tillräckligt snygga bilder på olika smaker av {a['rubrik']}. "
                                     f"Ta ett foto per smak och skicka dem – gärna alla på en gång.\n\n{FOTOGUIDE}")
            else:
                await msg.reply_text(f"Jag hittade ingen tillräckligt snygg bild på {a['rubrik']}. "
                                     f"Ta egna foton och skicka dem, så använder jag dem.\n\n{FOTOGUIDE}")
            return

    if len(a["fotos"]) < a["antal"] and not a.get("webb") and not a.get("racker"):
        # Han har sagt "3 smaker" men skickat färre foton: vänta på resten.
        a["steg"] = "foto"
        vantar[chatt] = a
        kvar = a["antal"] - len(a["fotos"])
        knappar = InlineKeyboardMarkup([[InlineKeyboardButton(
            f"▶️ Gör videon med {len(a['fotos'])} {'bild' if len(a['fotos']) == 1 else 'bilder'}",
            callback_data="racker:")]])
        await msg.reply_text(f"Tack! Skicka {kvar} foto till (en per smak).", reply_markup=knappar)
        return

    if not a["pris"]:
        minne.logga_oforstatt("pris_saknas", a["text"], rubrik=a["rubrik"])
        a["steg"] = "pris"
        vantar[chatt] = a
        await msg.reply_text(f"Vilket pris har {a['rubrik']}?\nT.ex. 19, 10/kg, 2 för 30 eller 15 + pant.")
        return

    vantar.pop(chatt, None)
    await gor_utkast(msg, context, a)


async def gor_utkast(msg: Message, context: ContextTypes.DEFAULT_TYPE, a: dict) -> None:
    n = len(a["fotos"])
    status = await msg.reply_text(f"🎬 Gör videon … (ca {1 + n // 2}–{2 + n // 2} minuter)")

    async def visa_status(text: str) -> None:
        try:
            await status.edit_text(text)
        except Exception:
            pass
    try:
        # Samma väg som appen: uppställning, övergång, rendering och Geminis kvalitetskontroll.
        u = await tjanst.gor_video(a, status=visa_status)
    except Exception:
        log.exception("Kunde inte skapa video")
        await status.edit_text("😕 Något gick fel när videon skulle göras. Försök igen, eller med en annan bild.")
        return
    post, notiser, video = u.post, u.notiser, u.post["video"]
    post["av"], post["chatt"] = msg.chat.id, msg.chat_id
    utkast[post["id"]] = {"post": post, "arende": a}
    rad1 = [InlineKeyboardButton("✅ Publicera", callback_data=f"pub:{post['id']}"),
            InlineKeyboardButton("✖️ Avbryt", callback_data=f"avb:{post['id']}")]
    knappar = [rad1]
    rad2 = [InlineKeyboardButton("✏️ Rätta namn", callback_data=f"namn:{post['id']}")]
    if a["nr"] + 1 < len(a["kandidater"]):
        rad2.append(InlineKeyboardButton("🔄 Annan bild", callback_data=f"ny:{post['id']}"))
    elif a.get("fran_minne"):
        rad2.append(InlineKeyboardButton("🔄 Annan bild", callback_data=f"annan:{post['id']}"))
    knappar.append(rad2)
    with open(video, "rb") as fh:
        await msg.reply_video(fh, caption="Förhandsvisning\n" + beskriv(post),
                              reply_markup=InlineKeyboardMarkup(knappar),
                              supports_streaming=True, width=1080, height=1920, duration=9)
    await status.delete()
    for notis in notiser:
        await msg.reply_text(f"💡 {notis}")


# ---------- kommandon ----------

@bara_behoriga
async def hjalp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HJALP)


@bara_behoriga
async def visa_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Ditt Telegram-ID: {update.effective_user.id}")


@bara_behoriga
async def avbryt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    a = vantar.pop(update.effective_message.chat_id, None)
    if a:
        minne.logga_oforstatt("avbruten", a.get("text", ""), steg=a.get("steg"), rubrik=a.get("rubrik"))
    await update.effective_message.reply_text("Okej, glömt. Skicka en ny bild eller ett namn när du vill.")


@bara_behoriga
async def visas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    aktiva = lager.aktiva()
    if not aktiva:
        await update.effective_message.reply_text("Inga erbjudanden visas just nu.")
        return
    rader = [f"{i}. {'⭐ ' if p['typ'] == 'fynd' else ''}{rubrik_kort(p)} – t.o.m. {datum(tid(p['utgar']))}"
             for i, p in enumerate(aktiva, 1)]
    await update.effective_message.reply_text("På skylten nu:\n" + "\n".join(rader))


@bara_behoriga
async def ta_bort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    aktiva = lager.aktiva()
    if not aktiva:
        await update.effective_message.reply_text("Inga erbjudanden visas just nu.")
        return
    knappar = [[InlineKeyboardButton(f"🗑 {rubrik_kort(p)[:40]}", callback_data=f"rm:{p['id']}")]
               for p in aktiva]
    await update.effective_message.reply_text("Vilket ska bort från skylten?",
                                              reply_markup=InlineKeyboardMarkup(knappar))


# ---------- bilder och text ----------

@bara_behoriga
async def bild(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
    text = (msg.caption or "").strip()

    if msg.media_group_id:
        # Album: Telegram skickar varje bild som ett eget meddelande. Samla dem en kort
        # stund och behandla albumet som ett erbjudande (texten sitter på en av bilderna).
        nyckel = (msg.chat_id, msg.media_group_id)
        ny = nyckel not in album
        al = album.setdefault(nyckel, {"file_ids": [], "text": "", "msg": msg})
        al["file_ids"].append(file_id)
        if text:
            al["text"] = text
        if ny:
            context.job_queue.run_once(album_klart, ALBUM_VANTETID, data=nyckel)
        return
    await ta_emot_fotos(msg, context, [file_id], text)


async def album_klart(context: ContextTypes.DEFAULT_TYPE) -> None:
    al = album.pop(context.job.data, None)
    if al:
        await ta_emot_fotos(al["msg"], context, al["file_ids"], al["text"])


async def ta_emot_fotos(msg: Message, context: ContextTypes.DEFAULT_TYPE, file_ids: list[str], text: str) -> None:
    # Svar på "skicka ett foto" behåller namn, pris och redan skickade foton; annars ett nytt ärende.
    a = hamta_vantande(msg.chat_id)
    if not (a and a["steg"] == "foto"):
        a = nytt_arende()
    vantar.pop(msg.chat_id, None)
    if text:
        await tolka_text(a, text)
    if a.get("webb"):                     # egna foton går alltid före nätbilder
        a["fotos"], a["webb"] = [], False
    a["kandidater"], a["nr"] = [], 0

    plats = MAX_PRODUKTER - len(a["fotos"])
    if len(file_ids) > plats:
        await msg.reply_text(f"Max {MAX_PRODUKTER} produkter per video – jag tar de {plats} första bilderna.")
    for fid in file_ids[:plats]:
        foto = Path(a["mapp"]) / f"foto{len(a['fotos'])}"
        fil = await context.bot.get_file(fid)
        await fil.download_to_drive(foto)
        a["fotos"].append(str(foto))
    # Fler foton än han sa "smaker" (eller inget sagt): antalet foton bestämmer.
    a["antal"] = max(a["antal"], len(a["fotos"]))

    if (not a["rubrik"] or not a["pris"]) and igenkanning.tillganglig():
        status = await msg.reply_text("🔍 Tittar på " + ("bilden …" if len(a["fotos"]) == 1 else "bilderna …"))
        svar = await igenkanning.kanna_igen([Path(f) for f in a["fotos"]])
        await status.delete()
        if svar:
            a["rubrik"] = a["rubrik"] or minne.synonym(svar["namn"])
            a["pris"] = a["pris"] or tolka.snygga_pris(svar["pris"])
            a["vartyp"] = svar.get("vartyp")
            tjanst.anpassa_foto(a, svar)
        elif not a["rubrik"]:
            minne.logga_oforstatt("ej_igenkand", text, fotos=a["fotos"])
            await msg.reply_text("Jag kände inte igen varan.")
    await fortsatt(msg, context, a)


@bara_behoriga
async def text_meddelande(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    text = (msg.text or "").strip()
    if text.lower() in ("avbryt", "stopp", "nej"):
        await avbryt(update, context)
        return

    a = hamta_vantande(msg.chat_id)
    if a and a["steg"] == "pris":
        pris = tolka.tolka_pris(text)
        if not pris:
            minne.logga_oforstatt("pris_oforstatt", text, rubrik=a["rubrik"])
            await msg.reply_text("Skriv bara priset, t.ex. 19 kr eller 2 för 30. (Eller \"avbryt\".)")
            return
        a["pris"] = pris
        await fortsatt(msg, context, a)
        return
    if a and a["steg"] == "rattnamn":
        # Pappas rättelse sparas som synonym: nästa gång blir det rätt direkt.
        minne.spara_synonym(a["gammalt_namn"], text)
        minne.logga_oforstatt("namn_rattat", text, fran=a["gammalt_namn"])
        a["rubrik"] = text
        vantar.pop(msg.chat_id, None)
        await msg.reply_text(f"👍 Jag kommer ihåg att det heter {text}.")
        await fortsatt(msg, context, a)
        return
    if a and a["steg"] == "namn":
        await tolka_text(a, text)
        if not a["rubrik"]:
            a["rubrik"] = text
        await fortsatt(msg, context, a)
        return

    if a and a["steg"] == "foto" and a["fotos"] and text.lower() in ("klar", "kör", "kor", "ok", "gör videon"):
        a["racker"] = True               # gör videon med de foton som redan kommit
        await fortsatt(msg, context, a)
        return

    # Nytt ärende från bara text: "banan", "banan 15 kr", "fynd 50% bröd", "Monster 19 kr 3 smaker"
    vantar.pop(msg.chat_id, None)
    a = nytt_arende()
    if lank := facebook.hitta_lank(text):           # länk till ett Facebook-inlägg: annons av inlägget
        status = await msg.reply_text("Läser Facebook-inlägget …")
        try:
            inlagg = await facebook.hamta(lank)
        except facebook.FacebookFel as f:
            await status.edit_text(str(f))
            return
        if inlagg["bild"]:
            foto = Path(a["mapp"]) / "foto0"
            foto.write_bytes(inlagg["bild"])
            a["fotos"].append(str(foto))
            a["antal"] = 1
        a["facebook"] = inlagg["lank"]
        text = (facebook.LANK.sub(" ", text) + " " + inlagg["text"]).strip()
        await status.edit_text("Hittade inlägget. Jag gör en annons av det och frågar innan något publiceras.")
        if text:
            await tolka_text(a, text)
        if a["fotos"] and (not a["rubrik"] or not a["pris"]) and igenkanning.tillganglig():
            svar = await igenkanning.kanna_igen([Path(f) for f in a["fotos"]])
            if svar:
                a["rubrik"] = a["rubrik"] or minne.synonym(svar["namn"])
                a["pris"] = a["pris"] or tolka.snygga_pris(svar["pris"])
                a["vartyp"] = svar.get("vartyp")
        a.pop("oklar", None)
        await fortsatt(msg, context, a)
        return
    await tolka_text(a, text)
    if a.get("oklar"):
        await msg.reply_text("Jag förstod inte riktigt. Skriv vara och pris, t.ex. "
                             "\"bananer 10/kg 3 dagar\" eller \"redbull 15 + pant\", eller skicka ett foto.")
        return
    if not a["rubrik"]:
        minne.logga_oforstatt("namn_saknas", text)
        await msg.reply_text("Skriv vad varan heter, t.ex. \"banan 15 kr\", eller skicka en bild.")
        return
    await fortsatt(msg, context, a)


async def halsa_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Varje timme: är något fel skriver boten till ägaren (inte till pappa – han har inte Telegram)."""
    try:
        meddelanden = await asyncio.to_thread(halsa.kontrollera)
    except Exception:
        log.exception("Hälsokontrollen misslyckades")
        return
    if meddelanden:
        text = "Min Butik hälsokontroll\n" + "\n".join(meddelanden)
        for chatt in TILLATNA:
            try:
                await context.bot.send_message(chatt, text)
            except Exception:
                log.warning("Kunde inte skicka hälsokontrollen")


async def vrid_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if vridna := await asyncio.to_thread(skyltvrid.vrid_alla):
            log.info("Skylten: vred %s", vridna)
    except Exception:
        log.exception("Kunde inte vrida skyltens videor")


async def forbered_bilder_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kör forbered_bilder.py som egen process med lägsta prioritet (kärna 1-3), högst 1 timme."""
    try:
        p = await asyncio.create_subprocess_exec(
            *konfig.lag_prioritet_prefix(), sys.executable, str(Path(__file__).with_name("forbered_bilder.py")),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, fel_ut = await asyncio.wait_for(p.communicate(), timeout=3600)
        log.info("Bildförrådet klart (kod %s)", p.returncode)
        if p.returncode:
            log.warning("Bildförrådet: %s", fel_ut.decode(errors="ignore")[-300:])
    except asyncio.TimeoutError:
        p.kill()
        log.warning("Bildförrådet tog över en timme och avbröts")
    except Exception:
        log.exception("Bildförrådet misslyckades")


async def backup_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nattlig säkerhetskopia (backup.py) som egen process med lägsta prioritet. Misslyckas den två nätter
    i rad syns det i hälsokontrollen (senaste kopian är för gammal)."""
    try:
        p = await asyncio.create_subprocess_exec(
            *konfig.lag_prioritet_prefix(), sys.executable, str(Path(__file__).with_name("backup.py")),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, fel_ut = await asyncio.wait_for(p.communicate(), timeout=1800)
        if p.returncode:
            log.warning("Säkerhetskopian misslyckades: %s", fel_ut.decode(errors="ignore")[-300:])
    except Exception:
        log.exception("Säkerhetskopian misslyckades")


# ---------- knappar ----------

@bara_behoriga
async def knapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    typ, _, pid = (q.data or "").partition(":")

    if typ in ("webb", "racker"):
        a = hamta_vantande(q.message.chat_id)
        if not a or a["steg"] != "foto":
            await q.answer("Det finns inget att göra just nu.", show_alert=True)
            return
        await q.edit_message_reply_markup(None)
        if typ == "webb":
            await q.answer("Letar på nätet …")
            a["webb"] = True
        else:
            await q.answer("Gör videon …")
            a["racker"] = True          # gör videon med de foton som finns
        await fortsatt(q.message, context, a)
        return

    if typ in ("pub", "avb", "ny", "annan", "namn"):
        u = utkast.pop(pid, None)
        if not u:
            await q.answer("Utkastet finns inte längre. Skicka bilden eller namnet igen.", show_alert=True)
            await q.edit_message_reply_markup(None)
            return
        post, a = u["post"], u["arende"]

        if typ == "annan":
            # Bilden kom från produktminnet: be om en ny (foto eller nätet).
            minne.logga_oforstatt("annan_bild", a["text"], rubrik=a["rubrik"])
            await q.answer()
            await q.edit_message_caption(caption="🔄 Ny bild önskas ↓")
            a["fotos"], a["fran_minne"], a["ny_bild"] = [], False, True
            await fortsatt(q.message, context, a)
            return

        if typ == "namn":
            await q.answer()
            await q.edit_message_caption(caption="✏️ Rättar namnet ↓")
            a["steg"], a["gammalt_namn"] = "rattnamn", a["rubrik"]
            vantar[q.message.chat_id] = a
            await q.message.reply_text(f"Vad ska varan heta i stället för \"{a['rubrik']}\"?")
            return

        if typ == "ny":
            await q.answer("Hämtar en annan bild …")
            a["nr"] += 1
            if not valj_kandidat(a):
                await q.edit_message_caption(caption="Inga fler bilder hittades. Skicka ett foto i stället.")
                return
            await q.edit_message_caption(caption="🔄 Byttes mot en annan bild ↓")
            await fortsatt(q.message, context, a)
            return

        if typ == "pub":
            try:
                await q.answer("Lägger ut på skärmen …")
                # Skyltens kopia vrids (ca en halv minut): i en tråd, så att boten inte står still.
                await asyncio.to_thread(tjanst.publicera, tjanst.Utkast(post, a), f"telegram:{update.effective_user.id}")
            except Exception:
                log.exception("Publicering misslyckades")
                utkast[pid] = u
                # Knappen är redan besvarad ("Lägger ut …"): ett nytt meddelande i stället.
                await q.message.reply_text("Publiceringen misslyckades, försök igen.")
                return
            await q.edit_message_caption(caption="✅ Publicerad på skylten (syns inom 30 s)\n" + beskriv(post))
        else:
            tjanst.avbryt(tjanst.Utkast(post, a))
            await q.answer("Avbrutet")
            await q.edit_message_caption(caption="✖️ Avbrutet – visas inte på skylten.")
        return

    if typ in ("sp", "op"):
        e = enheter.sparra(pid, sparrad=(typ == "sp"))
        if not e:
            await q.answer("Telefonen finns inte.", show_alert=True)
            return
        await q.answer("Spärrad" if typ == "sp" else "Öppnad")
        alla = enheter.lista()
        knappar = [[InlineKeyboardButton(f"{'✅ Öppna' if x.get('sparrad') else '🚫 Spärra'} {x['namn'][:30]}",
                                         callback_data=f"{'op' if x.get('sparrad') else 'sp'}:{x['id']}")]
                   for x in alla]
        await q.edit_message_text("Inloggade telefoner:\n" + "\n".join(_telefon_rad(x) for x in alla),
                                  reply_markup=InlineKeyboardMarkup(knappar))
        return

    if typ == "rm":
        post = lager.hamta(pid)
        if not post or post.get("status") != "aktiv":
            await q.answer("Redan borttaget.")
            await q.edit_message_reply_markup(None)
            return
        avpublicera(post, "borttagen")
        await q.answer("Borttaget")
        await q.edit_message_text(f"🗑 Borttaget från skylten (flyttat till arkivet): {rubrik_kort(post)}")


# ---------- utgångna erbjudanden ----------

# ---------- appen: inloggningskoder och telefoner ----------

@bara_behoriga
async def kod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Engångskod till Min Butik-appen. Ägaren ger den till den som ska logga in."""
    k = enheter.ny_kod()
    await update.effective_message.reply_text(
        f"Kod till Min Butik-appen: {k[:3]} {k[3:]}\n\n"
        f"Gäller i {enheter.KOD_GILTIG // 60} minuter och bara en gång. Tidigare koder slutar gälla.\n"
        "/telefoner visar vilka telefoner som är inloggade.")


def _telefon_rad(e: dict) -> str:
    sedd = e.get("sedd") or {}
    nar = sedd.get("tid", e.get("skapad", ""))[:16].replace("T", " ")
    via = {"lokalt": "butikens wifi", "tailscale": "Tailscale"}.get(sedd.get("via"), "–")
    return f"{'🚫' if e.get('sparrad') else '📱'} {e['namn']} – senast {nar} ({via})"


@bara_behoriga
async def telefoner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    alla = enheter.lista()
    if not alla:
        await update.effective_message.reply_text("Ingen telefon har loggat in än. Skriv /kod för att få en kod.")
        return
    knappar = [[InlineKeyboardButton(f"{'✅ Öppna' if e.get('sparrad') else '🚫 Spärra'} {e['namn'][:30]}",
                                     callback_data=f"{'op' if e.get('sparrad') else 'sp'}:{e['id']}")]
               for e in alla]
    await update.effective_message.reply_text("Inloggade telefoner:\n" + "\n".join(_telefon_rad(e) for e in alla),
                                              reply_markup=InlineKeyboardMarkup(knappar))


# ---------- väderstyrd skylt ----------

async def vader_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    await vader.hamta_prognos()
    uppdatera_vikter()


async def vikt_jobb(context: ContextTypes.DEFAULT_TYPE) -> None:
    uppdatera_vikter()


async def klassa_befintliga(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Annonser från innan väderstyrningen fanns får en vädertyp. Hämtar sedan prognosen."""
    for post in lager.aktiva():
        if not post.get("vadertyp"):
            post["vadertyp"] = await vader.klassa(post.get("rubrik", ""))
            lager.spara(post)
            log.info("Vädertyp %s: %s", post.get("rubrik"), post["vadertyp"])
    await vader_jobb(context)


@bara_behoriga
async def visa_vader(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    L = vader.lage(vader.las_prognos())
    rader = [vader.beskriv(L)]
    oftare = [p for p in lager.aktiva() if L.vikter.get(p.get("vadertyp") or "neutral", 1) > 1]
    if oftare:
        rader += ["", "Visas oftare nu:"] + [
            f"• {rubrik_kort(p)} (x{L.vikter[p['vadertyp']]})" for p in oftare]
    await update.effective_message.reply_text("\n".join(rader))


async def rensa_utgangna(context: ContextTypes.DEFAULT_TYPE) -> None:
    nu = datetime.now()
    for post in lager.aktiva():
        if tid(post["utgar"]) <= nu:
            avpublicera(post, "utgangen")
            log.info("Utgånget: %s", post["id"])
            try:
                await context.bot.send_message(
                    post["chatt"], f"⌛ {rubrik_kort(post)} har gått ut och flyttats till arkivet.")
            except Exception:
                log.exception("Kunde inte skicka utgångsmeddelande")


async def fel(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Fel i boten", exc_info=context.error)


def main() -> None:
    # Först av allt: boten och allt den startar (ffmpeg, friläggning) får lägsta prioritet och
    # kärna 1-3, så att skylten och musiken alltid har kärna 0 för sig själva.
    konfig.lag_prioritet()
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=logging.INFO)
    for brus in ("httpx", "httpx2", "apscheduler"):
        logging.getLogger(brus).setLevel(logging.WARNING)
    tok = konfig.token()
    if not tok:
        raise SystemExit("TELEGRAM_TOKEN saknas i butiksbot.env")
    for d in (konfig.UTKAST_DIR, konfig.CACHE_DIR, konfig.ERBJUDANDEN_DIR, konfig.ARKIV_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if TILLATNA:
        log.info("Tillåtna ID:n: %s", ", ".join(map(str, sorted(TILLATNA))))
    else:
        log.warning("ALLOWED_IDS är tom: inställningsläge, boten svarar bara med användarens ID")
    log.info("AI: %s", igenkanning.leverantor() or "AV (GEMINI_API_KEY saknas)")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg saknas")

    app = (Application.builder().token(tok).concurrent_updates(True)
           .connect_timeout(30).read_timeout(60).write_timeout(180).build())
    app.add_handler(CommandHandler(["start", "hjalp", "help"], hjalp))
    app.add_handler(CommandHandler("id", visa_id))
    app.add_handler(CommandHandler("avbryt", avbryt))
    app.add_handler(CommandHandler("visas", visas))
    app.add_handler(CommandHandler("ta_bort", ta_bort))
    app.add_handler(CommandHandler("vader", visa_vader))
    app.add_handler(CommandHandler("kod", kod))
    app.add_handler(CommandHandler("telefoner", telefoner))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, bild))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_meddelande))
    app.add_handler(CallbackQueryHandler(knapp))
    app.add_error_handler(fel)
    app.job_queue.run_repeating(rensa_utgangna, interval=60, first=10)
    # Väder: klassa gamla annonser och hämta prognosen vid start, sedan SMHI var 3:e timme
    # och nya vikter var 30:e minut (dygnet går, prognosen ändras).
    app.job_queue.run_once(klassa_befintliga, 5)
    app.job_queue.run_repeating(vader_jobb, interval=3 * 3600, first=3 * 3600)
    app.job_queue.run_repeating(vikt_jobb, interval=1800, first=1800)
    # Varje natt: förbered snygga bilder på vanliga varor (Gemini-kvoten är ledig, ingen renderar).
    # Skylten visar bara liggande, förvridna videor: vrid nya stående filer (t.ex. inlagda för hand).
    app.job_queue.run_repeating(vrid_jobb, interval=300, first=120)
    app.job_queue.run_repeating(halsa_jobb, interval=3600, first=600)
    app.job_queue.run_daily(forbered_bilder_jobb, time=dtime(2, 30, tzinfo=ZoneInfo("Europe/Stockholm")))
    app.job_queue.run_daily(backup_jobb, time=dtime(3, 30, tzinfo=ZoneInfo("Europe/Stockholm")))
    app.run_polling(allowed_updates=Update.ALL_TYPES, bootstrap_retries=-1)


if __name__ == "__main__":
    main()
