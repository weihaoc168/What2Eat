"""Fetch the Synology Photos shared album: item manifest plus thumbnails.

Usage:
  python scripts/fetch_gallery.py            # refresh manifest + download all sm thumbnails
  python scripts/fetch_gallery.py --m-size   # also fetch m-size (481px) images for dishes
                                             # listed as "best" in data/workflow_result.json

Reads SYNO_HOST / SYNO_PORT / SHARE_PASSPHRASE from .env in the repo root.
The share must be a public link (no password). Thumbnails land in thumbs/ and
m_thumbs/, both gitignored: these are family photos and stay local.
"""
import argparse
import concurrent.futures
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.setdefault("SYNO_HOST", os.environ.get("SYNO_HOST", ""))
    env.setdefault("SYNO_PORT", os.environ.get("SYNO_PORT", "5001"))
    env.setdefault("SHARE_PASSPHRASE", os.environ.get("SHARE_PASSPHRASE", ""))
    if not env["SYNO_HOST"] or not env["SHARE_PASSPHRASE"]:
        sys.exit("Set SYNO_HOST and SHARE_PASSPHRASE in .env (see .env.example)")
    return env


ENV = load_env()
BASE = f"https://{ENV['SYNO_HOST']}:{ENV['SYNO_PORT']}"
PASS = ENV["SHARE_PASSPHRASE"]
CTX = ssl._create_unverified_context()  # Synology self-signed cert on LAN
COOKIE = {}


def http(url, data=None, share_header=True):
    req = urllib.request.Request(url, data=data)
    if share_header:
        # NOTE: the landing page only sets sharing_sid when this header is absent
        req.add_header("X-SYNO-SHARING", PASS)
    if COOKIE:
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in COOKIE.items()))
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        for part in r.headers.get_all("Set-Cookie") or []:
            kv = part.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                COOKIE[k] = v
        return r.read()


def api(params):
    qs = urllib.parse.urlencode({**params, "passphrase": f'"{PASS}"'})
    raw = http(f"{BASE}/mo/sharing/webapi/entry.cgi", qs.encode())
    out = json.loads(raw)
    if not out.get("success"):
        sys.exit(f"API error {out.get('error')} for {params.get('api')}")
    return out["data"]


def list_items():
    http(f"{BASE}/mo/sharing/{PASS}", share_header=False)  # landing page sets the sharing_sid cookie
    items, offset = [], 0
    while True:
        page = api({
            "api": "SYNO.Foto.Browse.Item", "method": "list", "version": 1,
            "offset": offset, "limit": 500,
            "sort_by": '"takentime"', "sort_direction": '"asc"',
            "additional": '["thumbnail","description","tag"]',
        })["list"]
        items += page
        if len(page) < 500:
            return items
        offset += 500


def thumb_url(unit_id, cache_key, size):
    return (f"{BASE}/mo/sharing/webapi/entry.cgi?api=SYNO.Foto.Thumbnail&method=get&version=2"
            f"&id={unit_id}&cache_key=%22{cache_key}%22&type=%22unit%22&size=%22{size}%22"
            f"&passphrase=%22{PASS}%22")


def download(jobs, outdir):
    os.makedirs(outdir, exist_ok=True)
    def one(job):
        pid, url = job
        path = os.path.join(outdir, f"{pid}.jpg")
        data = http(url)
        if not data.startswith(b"\xff\xd8\xff"):
            return f"FAIL {pid}"
        open(path, "wb").write(data)
        return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        fails = [r for r in ex.map(one, jobs) if r]
    print(f"{outdir}: {len(jobs) - len(fails)} ok, {len(fails)} failed")
    for f in fails:
        print(" ", f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m-size", action="store_true",
                    help="fetch m-size images for best files in data/workflow_result.json")
    args = ap.parse_args()

    items = list_items()
    manifest = []
    for i in items:
        t = i["additional"]["thumbnail"]
        # NOTE: thumbnails must be requested by unit_id, not item id (they differ on newer items)
        manifest.append({"id": i["id"], "unit_id": t["unit_id"], "filename": i["filename"],
                         "time": i["time"], "type": i["type"], "cache_key": t["cache_key"]})
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(manifest, open(os.path.join(ROOT, "data", "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"manifest: {len(manifest)} items")

    download([(m["id"], thumb_url(m["unit_id"], m["cache_key"], "sm")) for m in manifest],
             os.path.join(ROOT, "thumbs"))

    if args.m_size:
        result = json.load(open(os.path.join(ROOT, "data", "workflow_result.json"), encoding="utf-8"))
        by_id = {m["id"]: m for m in manifest}
        jobs = []
        for d in result["dishes"]:
            if d.get("best"):
                pid = int(d["best"].split(".")[0])
                if pid in by_id:
                    m = by_id[pid]
                    jobs.append((pid, thumb_url(m["unit_id"], m["cache_key"], "m")))
        download(jobs, os.path.join(ROOT, "m_thumbs"))


if __name__ == "__main__":
    main()
