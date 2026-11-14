"""Tester för tolka.py med pappas sätt att skriva. Kör: python testa_tolka.py"""
from datetime import datetime

import tolka

NU = datetime(2026, 11, 12, 10, 0)   # torsdag förmiddag

# text -> (typ, rubrik, pris, dagar, visas t.o.m.)
FALL = {
    "bananer 10/kg 3 dagar":      ("erbjudande", "Bananer", "10 kr/kg", 3, "lördag"),
    "bananer 10kr/kg 3 dagar":    ("erbjudande", "Bananer", "10 kr/kg", 3, "lördag"),
    "bananer 10 kr kg i 3 dagar": ("erbjudande", "Bananer", "10 kr/kg", 3, "lördag"),
    "redbull 15 + pant":          ("erbjudande", "Red Bull", "15 kr + pant", 7, "onsdag"),
    "cola 2 för 30 5 dagar":      ("erbjudande", "Cola", "2 för 30 kr", 5, "måndag"),
    "fynd bröd 10":               ("fynd", "Bröd", "10 kr", 7, "i dag"),
    "bananer 10 kr/kg 3d":        ("erbjudande", "Bananer", "10 kr/kg", 3, "lördag"),
    "bananer 10 kr/kg 3 dag":     ("erbjudande", "Bananer", "10 kr/kg", 3, "lördag"),
    "bananer 10 kr/kg 1 dag":     ("erbjudande", "Bananer", "10 kr/kg", 1, "i dag"),
    "bananer 10 kr/kg 2 dagar":   ("erbjudande", "Bananer", "10 kr/kg", 2, "i morgon (fredag)"),
    "Monster 19 kr 3 dagar":      ("erbjudande", "Monster", "19 kr", 3, "lördag"),
    "Monster 19:- 3 dagar":       ("erbjudande", "Monster", "19:-", 3, "lördag"),
    "äpplen 12 kr per kilo":      ("erbjudande", "Äpplen", "12 kr/kg", 7, "onsdag"),
    "citroner 5 kr/st":           ("erbjudande", "Citroner", "5 kr/st", 7, "onsdag"),
    "fynd bröd 10 kr 2 dagar":    ("fynd", "Bröd", "10 kr", 2, "i morgon (fredag)"),
    "bröd fynd 10":               ("fynd", "Bröd", "10 kr", 7, "i dag"),
    "red bull 15kr +pant 4d":     ("erbjudande", "Red Bull", "15 kr + pant", 4, "söndag"),
    "chips 25":                   ("erbjudande", "Chips", "25 kr", 7, "onsdag"),
    "banan":                      ("erbjudande", "Banan", "", 7, "onsdag"),
    "3 smaker chips 2 för 40":    ("erbjudande", "Chips", "2 för 40 kr", 7, "onsdag"),
    "Pepsi max 1,5 l 20 kr":      ("erbjudande", "Pepsi max 1,5 l", "20 kr", 7, "onsdag"),
}

PRISSVAR = {"10": "10 kr", "15 + pant": "15 kr + pant", "2 för 30": "2 för 30 kr",
            "10/kg": "10 kr/kg", "19:-": "19:-", "12 kronor": "12 kr"}

fel = 0
for text, (typ, rubrik, pris, dagar, tom) in FALL.items():
    t = tolka.tolka(text, NU)
    fick = (t.typ, t.rubrik, t.pris, t.dagar, tolka.till_och_med(t.utgar, NU))
    ok = fick == (typ, rubrik, pris, dagar, tom)
    fel += not ok
    print(f"{'OK ' if ok else 'FEL'} {text!r:32} -> {tolka.sammanfattning(t.rubrik, t.pris, t.utgar, NU)}"
          f"{'' if ok else f'   (väntat {rubrik}, {pris}, {dagar} d, {tom})'}")
for svar, vantat in PRISSVAR.items():
    fick = tolka.tolka_pris(svar)
    fel += fick != vantat
    print(f"{'OK ' if fick == vantat else 'FEL'} prissvar {svar!r:14} -> {fick!r}")
print(f"\n{len(FALL) + len(PRISSVAR) - fel}/{len(FALL) + len(PRISSVAR)} rätt")
raise SystemExit(1 if fel else 0)
