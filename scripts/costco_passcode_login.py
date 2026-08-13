"""Costco passwordless sign-in: email -> Receive a Passcode -> code from chat.

Writes WAITING_CODE to private/login_status.txt when the code entry shows, then
polls private/2fa_code.txt for the emailed code (relayed through Claude). Uses
human-ish mouse clicks since the plain Sign In submit gets silently swallowed.
"""
import io
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRED = json.load(open(os.path.join(ROOT, "private", "credentials.json"), encoding="utf-8"))["costco"]
PROFILE = os.path.join(ROOT, "private", "profiles", "costco")
STATUS = os.path.join(ROOT, "private", "login_status.txt")
CODEFILE = os.path.join(ROOT, "private", "2fa_code.txt")
SHOTS = r"C:\Users\chenw\AppData\Local\Temp\claude\C--Users-chenw\33f899cb-c26c-4f24-b700-5a653d5a5f07\scratchpad"


def status(msg):
    open(STATUS, "w", encoding="utf-8").write(msg)
    print("STATUS:", msg)


def logged_in(page):
    try:
        return "costco.com/myaccount" in page.url.split("?")[0] and \
            not page.evaluate("!!document.querySelector('input[type=password]')")
    except Exception:
        return False


def human_click(page, loc):
    box = loc.bounding_box()
    if not box:
        loc.click()
        return
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x - 40, y - 20, steps=12)
    page.mouse.move(x, y, steps=8)
    page.wait_for_timeout(300)
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()


def find_code_input(page):
    for sel in ("input[autocomplete='one-time-code']", "input[id*='code' i]",
                "input[name*='code' i]", "input[id*='otp' i]", "input[inputmode='numeric']"):
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


if os.path.exists(CODEFILE):
    os.remove(CODEFILE)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport={"width": 1200, "height": 880},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.costco.com/myaccount/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)

    if not logged_in(page):
        email = page.locator("#signInName, input[type=email]").first
        email.click()
        email.fill(CRED["user"])
        cb = page.locator("input[type=checkbox]").first
        try:
            if cb.count() and not cb.is_checked():
                cb.check(force=True)
        except Exception:
            pass
        page.wait_for_timeout(600)
        btn = page.get_by_role("button", name=re.compile("Receive a Passcode", re.I)).first
        if not btn.count():
            btn = page.locator("button:has-text('Receive a Passcode')").first
        human_click(page, btn)
        print("clicked Receive a Passcode")

        code_loc = None
        for i in range(30):  # ~90s for the code screen
            page.wait_for_timeout(3000)
            code_loc = find_code_input(page)
            if code_loc or logged_in(page):
                break
            # intermediate OTP page asks to confirm sending the code by email
            send = page.get_by_role("button", name=re.compile("Receive a code via Email", re.I)).first
            try:
                if send.count() and send.is_visible():
                    human_click(page, send)
                    print("clicked Receive a code via Email")
                    continue
            except Exception:
                pass
        page.screenshot(path=os.path.join(SHOTS, "costco_pc1.png"))

        if code_loc and not logged_in(page):
            dom = page.evaluate("""(() => {
              const vis = el => el.offsetParent !== null;
              const ins = [...document.querySelectorAll('input')].filter(vis).map(i =>
                `input id=${i.id} name=${i.name} type=${i.type} mode=${i.inputMode} maxlen=${i.maxLength} ph=${i.placeholder}`);
              const btns = [...document.querySelectorAll('button,[role=button]')].filter(vis).map(b =>
                `button "${(b.innerText||'').trim().slice(0,40)}" id=${b.id}`);
              return ins.concat(btns).join('\\n'); })()""")
            open(os.path.join(ROOT, "private", "login_dom.txt"), "w", encoding="utf-8").write(dom)
            print("DOM dumped")
            status("WAITING_CODE")
            deadline = time.time() + 1200
            attempts = 0
            while time.time() < deadline and attempts < 3 and not logged_in(page):
                code = None
                while time.time() < deadline:
                    if os.path.exists(CODEFILE):
                        code = open(CODEFILE, encoding="utf-8").read().strip()
                        os.remove(CODEFILE)
                        if code:
                            break
                    time.sleep(3)
                if not code:
                    break
                attempts += 1
                inputs = page.locator("input[inputmode='numeric'], input[autocomplete='one-time-code'], input[id*='code' i], input[name*='code' i]")
                n = inputs.count()
                vis = [inputs.nth(i) for i in range(n) if inputs.nth(i).is_visible()]
                if len(vis) >= len(code):  # one box per digit
                    for i, ch in enumerate(code):
                        vis[i].click()
                        page.keyboard.type(ch, delay=90)
                elif vis:
                    vis[0].click()
                    page.keyboard.type(code, delay=120)
                else:
                    status("FAILED no code input at fill time")
                    break
                print("code typed, waiting for auto-submit")
                page.wait_for_timeout(8000)
                if not logged_in(page):
                    for name in ("Verify", "Continue", "Submit", "Sign In", "Next"):
                        loc = page.get_by_role("button", name=re.compile(name, re.I)).first
                        try:
                            if loc.count() and loc.is_visible():
                                human_click(page, loc)
                                print("clicked", name)
                                break
                        except Exception:
                            continue
                    else:
                        page.keyboard.press("Enter")
                for i in range(20):
                    page.wait_for_timeout(3000)
                    if logged_in(page):
                        break
                    # B2C shows a Continue button once the code verifies; it must be clicked
                    for sel in ("#continue", "button:has-text('Continue')"):
                        loc = page.locator(sel).first
                        try:
                            if loc.count() and loc.is_visible():
                                human_click(page, loc)
                                print("clicked Continue")
                                page.wait_for_timeout(3000)
                                break
                        except Exception:
                            continue
                    body = ""
                    try:
                        body = page.evaluate("document.body.innerText.slice(0,2500)")
                    except Exception:
                        pass
                    if re.search(r"(invalid|incorrect|expired)", body, re.I):
                        page.screenshot(path=os.path.join(SHOTS, f"costco_badcode{attempts}.png"))
                        status("BAD_CODE need a fresh one")
                        break

    page.wait_for_timeout(2000)
    page.screenshot(path=os.path.join(SHOTS, "costco_pc2_final.png"))
    if logged_in(page):
        status("DONE")
    else:
        status(f"FAILED url={page.url.split('?')[0][:90]} (see costco_pc2_final.png)")
    ctx.close()
