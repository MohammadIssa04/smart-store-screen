"""Provar Geminis bildmodell: gör en ren produktbild av varan i pappas eget foto.
    .venv/bin/python prova_bildredigering.py foto.jpg "Potatis" ut.png [modell]"""
import base64
import io
import os
import sys

import httpx
from PIL import Image

foto, namn, ut = sys.argv[1], sys.argv[2], sys.argv[3]
modell = sys.argv[4] if len(sys.argv) > 4 else "gemini-3.1-flash-image"
im = Image.open(foto).convert("RGB")
im.thumbnail((1536, 1536))
buf = io.BytesIO()
im.save(buf, "JPEG", quality=92)
prompt = (f"This is a real photo from a small grocery store showing {namn}. Create a professional product "
          f"photo for an advertisement: take three of the {namn} from THIS photo (keep their real shape, color "
          "and skin texture, do not invent a different variety) and place them together, sharp and well lit, "
          "on a plain pure white background, centered, soft natural shadow, no box, no labels, no text, "
          "no price tag. Photorealistic, not illustrated.")
kropp = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg",
                                                  "data": base64.b64encode(buf.getvalue()).decode()}},
                                 {"text": prompt}]}],
         "generationConfig": {"responseModalities": ["IMAGE"]}}
r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modell}:generateContent",
               headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=kropp, timeout=180)
print(r.status_code)
if r.status_code != 200:
    print(r.text[:400].replace(os.environ["GEMINI_API_KEY"], "…"))
    sys.exit(1)
for del_ in r.json()["candidates"][0]["content"]["parts"]:
    data = del_.get("inlineData") or del_.get("inline_data")
    if data:
        Image.open(io.BytesIO(base64.b64decode(data["data"]))).save(ut)
        print("sparad", ut, Image.open(ut).size)
        break
else:
    print("ingen bild:", str(r.json())[:300])
