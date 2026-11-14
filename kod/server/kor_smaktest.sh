#!/bin/sh
# Kör smaktesterna i bakgrunden: sh kor_smaktest.sh
cd "$(dirname "$0")"
set -a; . ./butiksbot.env; set +a
rm -f /tmp/rbtest/smaker.klar
.venv/bin/python -u testa_smaker.py "redbull olika smaker" "15 + pant" > /tmp/rbtest/smaker_redbull.log 2>&1
.venv/bin/python -u testa_smaker.py "monster olika smaker 19 kr" > /tmp/rbtest/smaker_monster.log 2>&1
touch /tmp/rbtest/smaker.klar
