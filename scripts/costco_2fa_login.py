"""Fully automated Costco sign-in with chat-relayed 2FA.

Fills credentials from private/credentials.json, checks Keep-me-signed-in,
submits, then if a passcode screen appears it writes WAITING_CODE to
private/login_status.txt and polls private/2fa_code.txt (written by Claude when
the user relays the emailed code). Screenshots each phase to the scratchpad.
Holds the browser up to 20 minutes.
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
    page.screenshot(path=os.path.join(SHOTS, "costco_p1_form.png"))

    if not logged_in(page):
        try:
            page.locator("#signInName, input[type=email]").first.fill(CRED["user"])
            page.locator("#password, input[type=password]").first.fill(CRED["pw"])
            cb = page.locator("input[type=checkbox]").first
            if cb.count() and not cb.is_checked():
                cb.check(force=True)
            page.get_by_role("button", name=re.compile("^Sign In$", re.I)).first.click()
            print("credentials submitted")
        except Exception as e:
            status(f"FAILED fill/submit: {str(e)[:120]}")
            ctx.close()
            sys.exit(1)

        # watch what the flow does next: straight in, a code screen, or an error
        code_loc = None
        for i in range(30):  # ~90s
            page.wait_for_timeout(3000)
            if logged_in(page):
                break
            body = ""
            try:
                body = page.evaluate("document.body.innerText.slice(0,3000)")
            except Exception:
                continue
            if re.search(r"(incorrect|unable to sign|try again|locked)", body, re.I):
                page.screenshot(path=os.path.join(SHOTS, "costco_p2_error.png"))
                status("FAILED credentials rejected (see costco_p2_error.png)")
                ctx.close()
                sys.exit(1)
            # some flows need an explicit send-to-email choice
            for sel in ("button:has-text('Email me')", "button:has-text('Send code')",
                        "label:has-text('Email me')"):
                loc = page.locator(sel).first
                try:
                    if loc.count() and loc.is_visible():
                        loc.click()
                        print("clicked", sel)
                        page.wait_for_timeout(2000)
                except Exception:
                    pass
            code_loc = find_code_input(page)
            if code_loc:
                break

        if not logged_in(page) and code_loc:
            page.screenshot(path=os.path.join(SHOTS, "costco_p3_code.png"))
            status("WAITING_CODE")
            deadline = time.time() + 1200
            code = None
            while time.time() < deadline:
                if os.path.exists(CODEFILE):
                    code = open(CODEFILE, encoding="utf-8").read().strip()
                    os.remove(CODEFILE)
                    if code:
                        break
                time.sleep(3)
            if code:
                code_loc = find_code_input(page) or code_loc
                code_loc.fill(code)
                for sel in ("button:has-text('Verify')", "button:has-text('Continue')",
                            "button:has-text('Submit')", "button[type=submit]"):
                    loc = page.locator(sel).first
                    try:
                        if loc.count() and loc.is_visible():
                            loc.click()
                            break
                    except Exception:
                        continue
                print("code submitted")
                for i in range(20):
                    page.wait_for_timeout(3000)
                    if logged_in(page):
                        break

    page.wait_for_timeout(2000)
    page.screenshot(path=os.path.join(SHOTS, "costco_p4_final.png"))
    if logged_in(page):
        status("DONE")
    else:
        status(f"FAILED end state url={page.url.split('?')[0][:90]} (see costco_p4_final.png)")
    ctx.close()
