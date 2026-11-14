-- Min Butik skylt: gäller bara mpv som visar video (inte musikspelaren, som körs med --no-video).
-- 1) Hårdvaruavkodning utan kopiering (v4l2m2m + drmprime). Med drmprime-overlay (mpv.conf) visar
--    skärmkretsen bilden direkt: exakt 60 bilder/s, grafikkretsen gör inget.
-- 2) Skärmkretsen kan inte vrida 90°: skyltens videor sparas därför redan vridna och liggande
--    (skyltvrid.py). Liggande fil -> ingen vridning. Stående fil (inte vriden än) -> ~/skylt/.rotera.
if mp.get_property("options/vid") == "no" then return end
mp.set_property("hwdec", "v4l2m2m")
local rotera = 270
local f = io.open((os.getenv("HOME") or "/home/minbutik") .. "/skylt/.rotera")
if f then
  rotera = tonumber(f:read("*l") or "") or rotera
  f:close()
end
local function satt()
  local w, h = mp.get_property_number("width"), mp.get_property_number("height")
  if w and h and w > h then
    mp.set_property_number("video-rotate", 0)
  else
    mp.set_property_number("video-rotate", rotera)
  end
end
mp.register_event("file-loaded", satt)
