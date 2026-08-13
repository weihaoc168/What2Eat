"""Drive the Costco sign-in with saved credentials, prefer email passcode for 2FA.

Fills email + password from private/credentials.json, checks "Keep me signed in",
submits, and picks the email option if a verification chooser appears. The window
stays open for the passcode: type the code from your email into the window; the
script watches for the account page (up to 8 minutes) and then closes itself.
"""
import io
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRED = json.load(open(os.path.join(ROOT, "private", "credentials.json"), encoding="utf-8"))["costco"]
PROFILE = os.path.join(ROOT, "private", "profiles", "costco")


def first_visible(page, selectors):
    for s in selectors:
        loc = page.locator(s).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def logged_in(page):
    try:
        url = page.url.split("?")[0]
        form = page.evaluate("!!document.querySelector('input[type=password]')")
        return "costco.com/myaccount" in url and not form
    except Exception:
        return False


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, viewport={"width": 1200, "height": 880},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.costco.com/myaccount/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)

    if not logged_in(page):
        email = first_visible(page, ["#signInName", "input[type=email]", "input[autocomplete='username']"])
        pw = first_visible(page, ["#password", "input[type=password]"])
        if email and pw:
            email.fill(CRED["user"])
            pw.fill(CRED["pw"])
            kmsi = first_visible(page, ["input[type=checkbox]"])
            if kmsi:
                try:
                    if not kmsi.is_checked():
                        kmsi.check()
                        print("KMSI checked")
                except Exception as e:
                    print("KMSI:", str(e)[:60])
            btn = first_visible(page, ["button:has-text('Sign In')", "#next", "button[type=submit]"])
            if btn:
                btn.click()
                print("submitted credentials")
        else:
            print("no login form found; maybe already mid-flow")

        # 2FA: prefer the email option if a chooser shows up
        page.wait_for_timeout(8000)
        mail_opt = first_visible(page, [
            "button:has-text('Email')", "label:has-text('Email')",
            "input[type=radio][value*='email' i]", "div[role=button]:has-text('Email')",
        ])
        if mail_opt:
            try:
                mail_opt.click()
                print("chose email 2FA")
                cont = first_visible(page, ["button:has-text('Continue')", "button:has-text('Send')", "button[type=submit]"])
                if cont:
                    cont.click()
                    print("passcode requested")
            except Exception as e:
                print("2FA click:", str(e)[:80])

        print("If a passcode box is showing, enter the code from your email in the window now.")
        for i in range(160):  # up to ~8 min
            page.wait_for_timeout(3000)
            if logged_in(page):
                break
            try:
                if len(ctx.pages) == 0:
                    break
            except Exception:
                break

    if logged_in(page):
        try:
            page.evaluate("document.title = '✅ 登录成功，10 秒后自动关闭'")
        except Exception:
            pass
        page.wait_for_timeout(10000)
        print("LOGIN_DETECTED")
    else:
        print("LOGIN_NOT_DETECTED")
    try:
        ctx.close()
    except Exception:
        pass
