"""Send one command to browser_bridge and print its result. Usage:
python scripts/bridge_send.py '{"op":"click","selector":"#foo"}'
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMD = os.path.join(ROOT, "private", "cmd.txt")
OUT = os.path.join(ROOT, "private", "cmd_out.txt")

cmd = json.loads(sys.argv[1])
cmd["seq"] = int(time.time() * 1000) % 1000000
if os.path.exists(OUT):
    os.remove(OUT)
open(CMD, "w", encoding="utf-8").write(json.dumps(cmd, ensure_ascii=False))
for _ in range(60):
    time.sleep(1.5)
    if os.path.exists(OUT):
        try:
            res = json.loads(open(OUT, encoding="utf-8").read())
        except Exception:
            continue
        if res.get("seq") == cmd["seq"]:
            print(json.dumps(res, ensure_ascii=False, indent=1)[:2500])
            sys.exit(0)
print("TIMEOUT waiting for bridge")
sys.exit(1)
