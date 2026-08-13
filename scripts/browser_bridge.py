"""Remote-controlled browser: Claude drives it step by step through command files.

Holds a persistent profile context for up to 30 minutes. Poll loop:
  private/cmd.txt   JSON {"seq": n, "op": ..., ...} written by Claude
  private/cmd_out.txt  JSON result {seq, ok, ...} written back
Every op ends with a screenshot at the scratchpad bridge_shot.png.

Ops: goto{url} click{selector} fill{selector,text} type{text} press{key}
     shot{} dump{} eval{js} status{} quit{}
"""
import io
import json
import os
import sys
import time
import traceback

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETAILER = sys.argv[1] if len(sys.argv) > 1 else "costco"
CHANNEL = sys.argv[2] if len(sys.argv) > 2 else None  # e.g. chrome / msedge
PROFILE = os.path.join(ROOT, "private", "profiles", RETAILER + (f"_{CHANNEL}" if CHANNEL else ""))
CMD = os.path.join(ROOT, "private", "cmd.txt")
OUT = os.path.join(ROOT, "private", "cmd_out.txt")
SHOT = r"C:\Users\chenw\AppData\Local\Temp\claude\C--Users-chenw\33f899cb-c26c-4f24-b700-5a653d5a5f07\scratchpad\bridge_shot.png"

for f in (CMD, OUT):
    if os.path.exists(f):
        os.remove(f)


def human_click(page, loc):
    box = loc.bounding_box()
    if not box:
        loc.click(timeout=8000)
        return
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x - 40, y - 15, steps=10)
    page.mouse.move(x, y, steps=6)
    page.wait_for_timeout(250)
    page.mouse.down()
    page.wait_for_timeout(80)
    page.mouse.up()


with sync_playwright() as p:
    kw = dict(headless=False, viewport={"width": 1200, "height": 880},
              args=["--disable-blink-features=AutomationControlled"])
    if CHANNEL:
        kw["channel"] = CHANNEL
    ctx = p.chromium.launch_persistent_context(PROFILE, **kw)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    print("bridge up")
    deadline = time.time() + 1800
    while time.time() < deadline:
        if not os.path.exists(CMD):
            time.sleep(1.5)
            continue
        try:
            cmd = json.loads(open(CMD, encoding="utf-8").read())
        except Exception:
            time.sleep(0.5)
            continue
        os.remove(CMD)
        res = {"seq": cmd.get("seq"), "ok": True}
        try:
            op = cmd["op"]
            if op == "goto":
                page.goto(cmd["url"], timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(cmd.get("wait", 5000))
            elif op == "click":
                loc = page.locator(cmd["selector"]).first
                human_click(page, loc)
                page.wait_for_timeout(cmd.get("wait", 2500))
            elif op == "fill":
                loc = page.locator(cmd["selector"]).first
                loc.click(timeout=8000)
                loc.fill(cmd["text"])
                page.wait_for_timeout(500)
            elif op == "type":
                page.keyboard.type(cmd["text"], delay=cmd.get("delay", 110))
                page.wait_for_timeout(500)
            elif op == "press":
                page.keyboard.press(cmd["key"])
                page.wait_for_timeout(1500)
            elif op == "dump":
                res["dump"] = page.evaluate("""(() => {
                  const vis = el => el.offsetParent !== null;
                  const ins = [...document.querySelectorAll('input')].filter(vis).map(i =>
                    `INPUT id=${i.id} name=${i.name} type=${i.type} maxlen=${i.maxLength} value_len=${(i.value||'').length}`);
                  const btns = [...document.querySelectorAll('button,[role=button],a.btn')].filter(vis).map(b =>
                    `BTN "${(b.innerText||'').trim().slice(0,50)}" id=${b.id} disabled=${b.disabled}`);
                  const txt = document.body.innerText.slice(0, 900);
                  return {inputs: ins, buttons: btns, text: txt}; })()""")
            elif op == "eval":
                res["value"] = page.evaluate(cmd["js"])
            elif op == "status":
                pass
            elif op == "quit":
                res["url"] = page.url
                page.screenshot(path=SHOT)
                open(OUT, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False))
                break
            res["url"] = page.url
            try:
                res["logged_in"] = "costco.com/myaccount" in page.url.split("?")[0] and \
                    not page.evaluate("!!document.querySelector('input[type=password]')")
            except Exception:
                res["logged_in"] = None
            page.screenshot(path=SHOT)
        except Exception as e:
            res["ok"] = False
            res["error"] = str(e)[:300]
            traceback.print_exc()
            try:
                page.screenshot(path=SHOT)
            except Exception:
                pass
        open(OUT, "w", encoding="utf-8").write(json.dumps(res, ensure_ascii=False))
    try:
        ctx.close()
    except Exception:
        pass
    print("bridge down")
