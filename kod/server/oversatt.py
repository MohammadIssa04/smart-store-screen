"""Arabiska för appen: butikens meddelanden (frågor, läge, fel) översätts när telefonen har valt arabiska
(rubriken X-Sprak: ar). Texterna skapas på svenska i koden; här finns arabiska för de vanliga.
Okända texter visas på svenska. Varans namn och priset översätts inte."""
from __future__ import annotations

import contextvars
import re

sprak: contextvars.ContextVar[str] = contextvars.ContextVar("sprak", default="sv")

FASTA = {
    "Tittar på bilden …": "أنظر إلى الصورة …",
    "Jag kände inte igen varan.": "لم أتعرّف على السلعة.",
    "Vad heter varan?": "ما اسم السلعة؟",
    "Jag förstod inte riktigt. Skriv vara och pris, t.ex. \"bananer 10/kg 3 dagar\" eller \"redbull 15 + pant\".":
        "لم أفهم تماماً. اكتب السلعة والسعر، مثلاً \"bananer 10/kg 3 dagar\" أو \"redbull 15 + pant\".",
    "Letar bilder på nätet … (kan ta ett par minuter)": "أبحث عن صور في الإنترنت … (قد يستغرق دقيقتين)",
    "Här är förhandsvisningen. Tryck Publicera, eller Gör om och skriv vad som ska ändras.":
        "هذه هي المعاينة. اضغط نشر، أو أعِد واكتب ما يجب تغييره.",
    "Något gick fel när videon skulle göras. Försök igen, eller med en annan bild.":
        "حدث خطأ أثناء صنع الفيديو. حاول مرة أخرى، أو بصورة أخرى.",
    "Skriv vad varan heter eller ta ett foto.": "اكتب اسم السلعة أو التقط صورة.",
    "Ärendet finns inte längre. Börja om.": "هذا الطلب لم يعد موجوداً. ابدأ من جديد.",
    "Ärendet finns inte längre.": "هذا الطلب لم يعد موجوداً.",
    "Vänta, jag håller på.": "انتظر، أنا أعمل على ذلك.",
    "Går inte just nu.": "غير ممكن الآن.",
    "Bra val! Jag gör videon med den bilden.": "اختيار جيد! سأصنع الفيديو بهذه الصورة.",
    "Jag hittade inga fler bra bilder. Välj en av dessa, eller ta ett eget foto.":
        "لم أجد صوراً جيدة أخرى. اختر واحدة من هذه، أو التقط صورة بنفسك.",
    "Det gick inte att söka fler bilder just nu.": "لم يكن البحث عن صور أخرى ممكناً الآن.",
    "Bilden finns inte.": "الصورة غير موجودة.",
    "Klipper ut bilden …": "أقصّ الصورة …",
    "Den bilden gick inte att klippa ut snyggt. Välj en annan.": "لم يكن قصّ هذه الصورة بشكل جميل ممكناً. اختر صورة أخرى.",
    "Ingen av bilderna gick att klippa ut snyggt.": "لم يكن قصّ أي من الصور بشكل جميل ممكناً.",
    "Skriv vad som är fel.": "اكتب ما هي المشكلة.",
    "Tack! Mohammad har fått ditt meddelande.": "شكراً! وصلت رسالتك إلى محمد.",
    "Ingen video än.": "لا يوجد فيديو بعد.",
    "Det finns ingen färdig video att publicera.": "لا يوجد فيديو جاهز للنشر.",
    "Avbrutet.": "أُلغي.",
    "tills vidare": "حتى إشعار آخر",
    "Den här videon kan inte göras om. Gör en ny annons i stället.": "لا يمكن إعادة صنع هذا الفيديو. اصنع إعلاناً جديداً بدلاً من ذلك.",
    "Håller redan på att ändra visningstiden …": "جارٍ تغيير مدة العرض بالفعل …",
    "Startpunkten ändrad.": "تم تغيير نقطة البداية.",
    "Börjar från början.": "يبدأ من البداية.",
    "Sparad som favorit.": "حُفظت كمفضلة.",
    "Inte favorit längre.": "لم تعد مفضلة.",
    "Ingen låt från listan spelas just nu.": "لا تُعزف الآن أغنية من القائمة.",
    "Ingen säkerhetskopia de senaste två nätterna.": "لا توجد نسخة احتياطية في آخر ليلتين.",
    "Skylten (skylt.service) kör inte.": "الشاشة (skylt.service) لا تعمل.",
    "Skylten verkar stå still (videon rör sig inte).": "يبدو أن الشاشة متوقفة (الفيديو لا يتحرك).",
    "Musiken spelar inte (och är inte pausad).": "الموسيقى لا تعمل (وليست متوقفة مؤقتاً).",
    "Musikspelaren svarar inte.": "مشغل الموسيقى لا يستجيب.",
    "Etikettskrivaren svarar inte (avstängd eller utom räckhåll).": "طابعة الملصقات لا تستجيب (مطفأة أو بعيدة).",
    "Gemini (AI:n) har varit överbelastad eller slut på gratiskvot senaste timmen.": "الذكاء الاصطناعي كان مشغولاً أو نفدت حصته المجانية في الساعة الأخيرة.",
    "Visas som vanligt": "يُعرض كالمعتاد",
    "Visas oftare": "يُعرض أكثر",
    "Visas mycket ofta": "يُعرض كثيراً جداً",
    "Välj normalt, oftare eller mycket ofta.": "اختر عادي أو أكثر أو كثيراً جداً.",
    "Visas oftare när det är varmt": "يُعرض أكثر عندما يكون الجو حاراً",
    "Visas oftare när det är kallt": "يُعرض أكثر عندما يكون الجو بارداً",
    "Visas oftare när det regnar eller snöar": "يُعرض أكثر عند المطر أو الثلج",
    "Visas oftare när det är grillväder": "يُعرض أكثر في طقس الشواء",
    "Visas lika ofta oavsett väder": "يُعرض بالتساوي مهما كان الطقس",
    "Visas nu tills vidare": "يُعرض الآن حتى إشعار آخر",
    "Okej, jag letar efter en bild på nätet.": "حسناً، أبحث عن صورة على الإنترنت.",
    "Jag letar en bild på nätet. Vill du hellre använda ett eget foto kan du skicka det.":
        "أبحث عن صورة على الإنترنت. إذا أردت استخدام صورتك يمكنك إرسالها.",
    "Ingen bild var tillräckligt snygg.": "لم تكن أي صورة جميلة بما يكفي.",
    "Bildsökningen gick inte. Ta ett eget foto och skicka det.": "فشل البحث عن الصور. التقط صورة بنفسك وأرسلها.",
    "vanligt väder: alla visas lika ofta": "طقس عادي: كل الإعلانات تظهر بالتساوي",
    "ingen prognos: alla visas lika ofta": "لا توجد توقعات: كل الإعلانات تظهر بالتساوي",
    "Finns inte.": "غير موجود.",
    "Skriv varans namn.": "اكتب اسم السلعة.",
    "Skriv priset, t.ex. 19 eller 2 för 30.": "اكتب السعر، مثلاً 19 أو 2 för 30.",
    "AI:n är inte påslagen. Skriv namnet själv.": "الذكاء الاصطناعي غير مفعّل. اكتب الاسم بنفسك.",
    "Fotot gick inte att läsa.": "تعذّرت قراءة الصورة.",
    "Jag kände inte igen varan. Skriv namnet själv.": "لم أتعرّف على السلعة. اكتب الاسم بنفسك.",
    "Testläge: etiketten sparades som bild (skrivaren är inte inkopplad).":
        "وضع التجربة: حُفظ الملصق كصورة (الطابعة غير موصولة).",
    "Skrivaren svarade inte. Är den på och har etiketter?": "الطابعة لا تستجيب. هل هي مشغّلة وفيها ملصقات؟",
    "Skrivarprogrammet (niimprint) är inte installerat på Pi:n än.": "برنامج الطابعة غير مثبّت بعد.",
    "Läser Facebook-inlägget …": "أقرأ منشور فيسبوك …",
    "Jag kan inte läsa Facebook-länkar. Öppna bilden i inlägget, tryck Dela och välj Min Butik (eller spara bilden och skicka den här), så gör jag annonsen av den.":
        "لا أستطيع قراءة روابط فيسبوك. افتح صورة المنشور، اضغط مشاركة واختر Min Butik (أو احفظ الصورة وأرسلها هنا)، وسأصنع الإعلان منها.",
    "Det där ser inte ut som en länk till ett Facebook-inlägg.": "هذا لا يبدو رابط منشور فيسبوك.",
    "Jag kunde inte öppna inlägget. Är det offentligt? Annars: spara bilden och skicka den här.":
        "لم أستطع فتح المنشور. هل هو عام؟ وإلا: احفظ الصورة وأرسلها هنا.",
}

MONSTER = [
    (r"Gör videon … \(ca (\d+)–(\d+) minuter\)", r"أصنع الفيديو … (حوالي \1–\2 دقائق)"),
    (r"Ta (\d+) foton på (.+), ett per smak, och skicka dem\.", r"التقط \1 صور لـ \2، صورة لكل نكهة، وأرسلها."),
    (r"Ta ett foto på (.+) och skicka det\.", r"التقط صورة لـ \1 وأرسلها."),
    (r"Tack! Skicka (\d+) foto till \(ett per smak\)\.", r"شكراً! أرسل \1 صورة أخرى (صورة لكل نكهة)."),
    (r"Vilket pris har (.+)\? T\.ex\. 19, 10/kg, 2 för 30 eller 15 \+ pant\.",
     r"ما سعر \1؟ مثلاً 19، 10/kg، 2 för 30 أو 15 + pant."),
    (r"Jag använder bilden på (.+) från förra gången\.(.*)", r"أستخدم صورة \1 من المرة الماضية.\2"),
    (r" Vill du ha en ny bild trycker du \"Annan bild\"\.", r" إذا أردت صورة جديدة اضغط \"صورة أخرى\"."),
    (r"Jag hittade bara (\d+) snygga bilder på olika smaker\. Jag gör videon med dem\.",
     r"وجدت \1 صور جميلة فقط لنكهات مختلفة. سأصنع الفيديو بها."),
    (r"Jag hittade ingen tillräckligt snygg bild på (.+)\. Ta ett eget foto och skicka det\.",
     r"لم أجد صورة جميلة بما يكفي لـ \1. التقط صورة بنفسك وأرسلها."),
    (r"✅ Publicerad på skärmen\. (.*)", r"✅ نُشر على الشاشة. \1"),
    (r"^Välj mellan (\d+) och (\d+) sekunder\.$", r"اختر بين \1 و\2 ثانية."),
    (r"^Gör om videon till (\d+) sekunder\. Det tar ungefär en minut\.$", r"أعيد صنع الفيديو بمدة \1 ثانية. يستغرق ذلك حوالي دقيقة."),
    (r"^Söker bilder på olika smaker av (.+) …$", r"أبحث عن صور لنكهات مختلفة من \1 …"),
    (r"^Söker bilder på (.+) …$", r"أبحث عن صور لـ \1 …"),
    (r"^Vilken bild på (.+) är bäst\? Tryck på den\.$", r"أي صورة لـ \1 هي الأفضل؟ اضغط عليها."),
    (r"^Söker fler bilder på (.+) …$", r"أبحث عن صور أخرى لـ \1 …"),
    (r"^Hittade (\d+) till\.$", r"وجدت \1 صور أخرى."),
    (r"^Söker på \"(.+)\" …$", r"أبحث عن «\1» …"),
    (r"^Hittade inga\. Söker på \"(.+)\" i stället …$", r"لم أجد شيئاً. أبحث عن «\1» بدلاً من ذلك …"),
    (r"^Hittade (\d+) bilder\. Väljer de snyggaste …$", r"وجدت \1 صورة. أختار الأجمل …"),
    (r"^Klipper ut bild (\d+) av (\d+) …$", r"أقص الصورة \1 من \2 …"),
    (r"^Hittade färdiga bilder på (.+)\.$", r"وجدت صوراً جاهزة لـ \1."),
    (r"^kallt \((-?\d+) °C\): varma varor x(\d)$", r"بارد (⁦\1 °C⁩): المنتجات الدافئة ×\2"),
    (r"^varmt \((-?\d+) °C\): kalla varor x(\d)$", r"حار (⁦\1 °C⁩): المنتجات الباردة ×\2"),
    (r"^regn/snö (\d+) h: mysvaror x2$", r"مطر/ثلج \1 ساعات: منتجات الدفء ×2"),
    (r"^grillhelg \((.*)\): grillvaror x(\d)$", r"عطلة شواء (\1): منتجات الشواء ×\2"),
    (r"Jag hittade ingen snygg bild på bara (.+), så jag visar ditt foto i en ram\.",
     r"لم أجد صورة جميلة لـ \1 وحدها، لذلك سأعرض صورتك في إطار."),
    (r"(\d+) etiketter? utskrivna?\.", r"طُبع \1 ملصق."),
    (r"Hittade inlägget: (.*)", r"وجدت المنشور: \1"),
]


def ar(text: str) -> str:
    if not text:
        return text
    if text in FASTA:
        return FASTA[text]
    ut = text
    for m, ers in MONSTER:
        ut = re.sub(m, ers, ut)
    return ut


def t(text: str) -> str:
    """Översätter om telefonen bad om arabiska (sätts per anrop i api/main.py)."""
    return ar(text) if sprak.get() == "ar" else text
