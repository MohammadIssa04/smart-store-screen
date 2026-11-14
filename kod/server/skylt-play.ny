#!/bin/bash
# Skylt-spelare för Min Butik.
# Bygger spellistan var 30:e sekund. När listan ändras skickas den nya listan
# till mpv via IPC-socketen i stället för att starta om mpv (ingen svart blinkning).
# Erbjudanden i erbjudanden/ visas som varannan video. Filer som börjar med
# t<ÅÅÅÅMMDDTTMM>_ hoppas över när den tiden har passerat.
BAS=${SKYLT_BAS:-/home/minbutik/skylt}
ERB="$BAS/erbjudanden"
LISTA=${SKYLT_LISTA:-/tmp/skylt-lista.txt}
SOCK=${SKYLT_SOCK:-/tmp/mpv.sock}
INTERVALL=${SKYLT_INTERVALL:-30}
FILTYPER='\.(jpg|jpeg|png|webp|mp4|mov|mkv)$'
MPV_PID=""
GAMMAL_KVAR=0   # 1 = posten som spelades vid förra listbytet ligger kvar som nr 0
dagar=(måndag tisdag onsdag torsdag fredag lördag söndag)
if [ -n "$SKYLT_TEST" ]; then VO=(--vo=null); else VO=(--fs --vo=gpu --gpu-context=drm); fi

vanliga_filer() {
  local timme=$1 dag d namn s e
  dag=${dagar[$(( $(date +%u) - 1 ))]}
  {
    find "$BAS" -maxdepth 1 -type f
    for d in "$BAS"/*/; do
      [ -d "$d" ] || continue
      namn=$(basename "$d")
      if [ "$namn" = "alltid" ] || [ "$namn" = "$dag" ]; then
        find "$d" -maxdepth 1 -type f
      elif [[ $namn =~ ^([0-9]{1,2})-([0-9]{1,2})$ ]]; then
        s=$((10#${BASH_REMATCH[1]})); e=$((10#${BASH_REMATCH[2]}))
        if [ "$timme" -ge "$s" ] && [ "$timme" -lt "$e" ]; then
          find "$d" -maxdepth 1 -type f
        fi
      fi
    done
  } | grep -iE "$FILTYPER" | sort
}

aktiva_erbjudanden() {
  local nu f namn
  [ -d "$ERB" ] || return
  nu=$(date +%Y%m%d%H%M)
  find "$ERB" -maxdepth 1 -type f | grep -iE "$FILTYPER" | sort | while IFS= read -r f; do
    namn=${f##*/}
    if [[ $namn =~ ^t([0-9]{12})_ ]] && [ "${BASH_REMATCH[1]}" -le "$nu" ]; then continue; fi
    printf '%s\n' "$f"
  done
}

bygg_lista() {
  local timme i n m k
  local -a V E
  timme=$((10#$(date +%H)))
  if [ "$timme" -lt 10 ] || [ "$timme" -ge 21 ]; then return; fi
  mapfile -t V < <(vanliga_filer "$timme")
  mapfile -t E < <(aktiva_erbjudanden)
  n=${#V[@]}; m=${#E[@]}
  if [ "$m" -eq 0 ]; then [ "$n" -gt 0 ] && printf '%s\n' "${V[@]}"; return; fi
  if [ "$n" -eq 0 ]; then printf '%s\n' "${E[@]}"; return; fi
  # Varannan: vanlig, erbjudande, vanlig, erbjudande ... (den kortaste listan går runt)
  k=$(( n > m ? n : m ))
  for ((i = 0; i < k; i++)); do
    printf '%s\n%s\n' "${V[i % n]}" "${E[i % m]}"
  done
}

# ---- mpv via IPC ----
mpv_ipc() { printf '%s\n' "$1" | socat -t 0.5 - "UNIX-CONNECT:$SOCK" 2>/dev/null; }
mpv_ok() { [[ $(mpv_ipc "$1") == *'"error":"success"'* ]]; }
mpv_hamta() { mpv_ipc "{\"command\":[\"get_property\",\"$1\"]}" | grep -o '"data":[0-9-]*' | head -1 | cut -d: -f2; }
json_str() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '"%s"' "$s"; }

byt_lista() {
  # playlist-clear tar bort allt utom det som spelas nu; den nya listan läggs
  # efter. Den gamla posten tas bort när mpv har gått vidare (rensa_gammal).
  mpv_ok '{"command":["playlist-clear"]}' || return 1
  local antal; antal=$(mpv_hamta playlist-count)
  mpv_ok "{\"command\":[\"loadlist\",$(json_str "$LISTA"),\"append-play\"]}" || return 1
  if [ "${antal:-0}" -ge 1 ]; then GAMMAL_KVAR=1; else GAMMAL_KVAR=0; fi
}

rensa_gammal() {
  local pos; pos=$(mpv_hamta playlist-pos)
  if [[ $pos =~ ^[0-9]+$ ]] && [ "$pos" -ge 1 ]; then
    mpv_ok '{"command":["playlist-remove",0]}' && GAMMAL_KVAR=0
  fi
}

starta_mpv() {
  mpv "${VO[@]}" --loop-playlist=inf --image-display-duration=10 \
      --hwdec=v4l2m2m-copy --really-quiet --video-rotate=90 --no-audio \
      --input-ipc-server="$SOCK" --playlist="$LISTA" &
  MPV_PID=$!
  GAMMAL_KVAR=0
}

stoppa_mpv() {
  if [ -n "$MPV_PID" ]; then kill "$MPV_PID" 2>/dev/null; wait "$MPV_PID" 2>/dev/null; fi
  MPV_PID=""
}

trap 'stoppa_mpv; exit 0' TERM INT
gammal=""
while true; do
  ny=$(bygg_lista)
  if [ -z "$ny" ]; then
    stoppa_mpv; gammal=""
  elif [ -z "$MPV_PID" ] || ! kill -0 "$MPV_PID" 2>/dev/null; then
    stoppa_mpv
    printf '%s\n' "$ny" > "$LISTA"
    starta_mpv; gammal="$ny"
  elif [ "$ny" != "$gammal" ]; then
    printf '%s\n' "$ny" > "$LISTA"
    if byt_lista; then
      gammal="$ny"
    else
      logger -t skylt-play "IPC misslyckades, startar om mpv"
      stoppa_mpv; starta_mpv; gammal="$ny"
    fi
  elif [ "$GAMMAL_KVAR" = 1 ]; then
    rensa_gammal
  fi
  sleep "$INTERVALL"
done
