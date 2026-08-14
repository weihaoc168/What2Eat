"""Fetch specific thumbnail sizes for a list of photo ids.

Usage: python scripts/fetch_sizes.py m private/multi_files.json
       python scripts/fetch_sizes.py xl private/xl_wanted.json

The JSON file is a list of "<id>.jpg" names (or bare ids). Files land in
m_thumbs/ or xl_thumbs/ and are skipped if already present.
"""
import concurrent.futures
import json
import os
import ssl
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from fetch_gallery import ENV, BASE, PASS, http, thumb_url  # noqa: E402

SIZE = sys.argv[1]
LIST = sys.argv[2]
OUT = os.path.join(ROOT, {"m": "m_thumbs", "xl": "xl_thumbs"}[SIZE])
os.makedirs(OUT, exist_ok=True)

ids = [int(str(x).split(".")[0]) for x in json.load(open(os.path.join(ROOT, LIST), encoding="utf-8"))]
manifest = {m["id"]: m for m in json.load(open(os.path.join(ROOT, "data", "manifest.json"), encoding="utf-8"))}

http(f"{BASE}/mo/sharing/{PASS}", share_header=False)  # sharing_sid cookie

jobs = []
for pid in ids:
    dst = os.path.join(OUT, f"{pid}.jpg")
    if os.path.exists(dst) and open(dst, "rb").read(3) == b"\xff\xd8\xff":
        continue
    m = manifest.get(pid)
    if m:
        jobs.append((pid, thumb_url(m["unit_id"], m["cache_key"], SIZE), dst))


def one(job):
    pid, url, dst = job
    data = http(url)
    if not data.startswith(b"\xff\xd8\xff"):
        return f"FAIL {pid}"
    open(dst, "wb").write(data)
    return None


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    fails = [r for r in ex.map(one, jobs) if r]
print(f"{SIZE}: {len(jobs) - len(fails)} downloaded, {len(fails)} failed, {len(ids) - len(jobs)} already present")
for f in fails[:5]:
    print(" ", f)
