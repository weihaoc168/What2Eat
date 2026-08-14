"""Crop dish regions out of multi-dish photos.

Input: private/crop_plan.json — [{"file": "604298.jpg", "bbox": [x,y,w,h], "out": "604298_1.jpg"}]
with bbox as fractions of the image. Crops use the xl thumbnail when available
(fall back to m), pad the box by 8%, and land in crops/ (gitignored: family photos).
"""
import json
import os
import sys

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "crops")
os.makedirs(OUT, exist_ok=True)
PAD = 0.08

plan = json.load(open(os.path.join(ROOT, "private", "crop_plan.json"), encoding="utf-8"))
done = fail = 0
for item in plan:
    pid = item["file"].split(".")[0]
    src = None
    for sub in ("xl_thumbs", "m_thumbs", "thumbs"):
        p = os.path.join(ROOT, sub, pid + ".jpg")
        if os.path.exists(p):
            src = p
            break
    if not src:
        fail += 1
        continue
    # detection bboxes are in DISPLAY orientation, so normalize pixels first
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    W, H = im.size
    x, y, w, h = item["bbox"]
    x0 = max(0, (x - PAD * w) * W)
    y0 = max(0, (y - PAD * h) * H)
    x1 = min(W, (x + w * (1 + PAD)) * W)
    y1 = min(H, (y + h * (1 + PAD)) * H)
    if x1 - x0 < 40 or y1 - y0 < 40:
        fail += 1
        continue
    im.crop((int(x0), int(y0), int(x1), int(y1))).save(
        os.path.join(OUT, item["out"]), "JPEG", quality=80, optimize=True)
    done += 1
print(f"crops: {done} written, {fail} skipped, dir={OUT}")
