#!/usr/bin/env python3
"""SMOKE TEST — does OnlyFans' login page render in a Browserbase Chromium
on Browserbase's managed proxies, driven over CDP, or does Cloudflare block
it? Touches no DB, writes nothing.

  1. Reads BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID from the env.
  2. Creates the session the served login creates (remote_login._bb_create_session:
     managed proxies, solveCaptchas false).
  3. connect_over_cdp, opens https://onlyfans.com/, prints the browser's
     egress IP, and PASS (login form) / BLOCKED (challenge or blank body) /
     INCONCLUSIVE. Exit 0 only on PASS; a refused session-create exits 2, a
     failed load of OnlyFans is NAVIGATION FAILED (exit 1).

USAGE
  BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... \\
    ./venv/bin/python service/scripts/browserbase_of_smoketest.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

import remote_login as rl  # noqa: E402

SETTLE_S = 6


def _body_is_blank(page) -> bool:
    try:
        return len((page.evaluate("() => (document.body && document.body.innerText || '').trim()") or "")) < 20
    except Exception:  # noqa: BLE001
        return False


def _egress_ip(page) -> str:
    try:
        page.goto("https://api.ipify.org/", timeout=20_000)
        return page.inner_text("body").strip()[:45]
    except Exception as e:  # noqa: BLE001
        return f"unknown ({type(e).__name__})"


def main() -> int:
    print("[*] egress: Browserbase managed proxies")
    try:
        session = rl._bb_create_session()
    except RuntimeError as e:
        print(f"[x] {e}")
        print("==> VERDICT: SESSION REFUSED")
        return 2
    sid = session.get("id")
    print(f"[*] session id: {sid}")

    from playwright.sync_api import sync_playwright
    verdict = "INCONCLUSIVE"
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(session["connectUrl"])
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                print(f"[*] browser egress IP: {_egress_ip(page)}")
                print(f"[*] navigating to {rl.OF_HOME} over CDP ...")
                err = rl.open_of(page)
                if err:
                    print(f"[x] {err}")
                    verdict = "NAVIGATION FAILED"
                    return 1
                time.sleep(SETTLE_S)
                challenge = rl._detect_challenge(page)
                email = page.query_selector(rl._EMAIL_FIELD) is not None
                blank = _body_is_blank(page)
                print(f"[*] detect_challenge={challenge}  email_input={email}  body_blank={blank}")
                if email and not challenge:
                    verdict = "PASS"
                elif challenge or blank:
                    verdict = "BLOCKED"
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        rl._bb_release(sid)
        print(f"==> VERDICT: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
