"""Family shared-list server: serves the built app plus a tiny state-sync API,
so everyone opening the NAS URL shares one plan and one grocery check-off list.

Stdlib only (runs on Synology's Python 3.8). State lives in
private/shared_state.json. Concurrency model: a revision counter; bought-item
toggles are sent as ops so two shoppers never clobber each other.

  python scripts/sync_server.py [--port 8125]

API:
  GET  /api/state            -> {"rev": N, "state": {...}}
  POST /api/state {baseRev, state?, boughtOps?: [{item, on}]}
       baseRev == rev  : replace state fields, apply ops, rev+1
       baseRev != rev  : apply ONLY boughtOps (merge), rev+1
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
STORE = os.path.join(ROOT, "private", "shared_state.json")
LOCK = threading.Lock()

PORT = 8125
if "--port" in sys.argv:
    PORT = int(sys.argv[sys.argv.index("--port") + 1])


def load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except (OSError, ValueError):
        return {"rev": 0, "state": {}}


def save(data):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, STORE)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with LOCK:
                return self._json(200, load())
        # static: default document is the app itself
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            path = "/jiali-de-cai.html"
        fp = os.path.realpath(os.path.join(DIST, path.lstrip("/")))
        if not fp.startswith(os.path.realpath(DIST)) or not os.path.isfile(fp):
            self.send_response(404)
            self.end_headers()
            return
        body = open(fp, "rb").read()
        self.send_response(200)
        ctype = "text/html; charset=utf-8" if fp.endswith(".html") else "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/api/state"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n).decode())
        except (ValueError, TypeError):
            return self._json(400, {"error": "bad json"})
        with LOCK:
            data = load()
            state = data.get("state") or {}
            if req.get("baseRev") == data.get("rev") and isinstance(req.get("state"), dict):
                state.update(req["state"])
            bought = set(state.get("bought") or [])
            for op in req.get("boughtOps") or []:
                if not isinstance(op, dict) or "item" not in op:
                    continue
                (bought.add if op.get("on") else bought.discard)(str(op["item"])[:200])
            state["bought"] = sorted(bought)
            data = {"rev": data.get("rev", 0) + 1, "state": state}
            save(data)
            return self._json(200, data)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"What2Eat sync server on :{PORT} (serving {DIST})")
    server.serve_forever()


if __name__ == "__main__":
    main()
