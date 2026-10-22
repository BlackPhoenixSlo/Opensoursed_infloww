#!/usr/bin/env python3
"""ATTENDED Browserbase login — one human-solved OnlyFans login attempt.

Creates the session the served login creates (Browserbase's managed proxies,
solveCaptchas false), prints a LIVE-VIEW url where a human watches and solves
any Cloudflare / captcha / 2FA challenge, types the credentials into
OnlyFans' real form, then polls for the logged-in cookie. It PERSISTS NOTHING
and binds nothing; it only proves the login lands. (The persisting login is
the Setup page's "Try Browserbase login", which also attaches the chosen
proxy.)

One attempt per run; never an unattended resubmit loop.

The LIVEVIEW line is flushed at once, so a background run's log can be read
for it and the url handed to the human.

ENV:  BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, OF_EMAIL, OF_PASSWORD
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

import remote_login as rl  # noqa: E402

POLL_WINDOW_S = 270      # under Browserbase's 300 s default session lifetime
TICK_S = 3


def main() -> int:
    email = os.environ.get("OF_EMAIL") or ""
    password = os.environ.get("OF_PASSWORD") or ""
    if not email or not password:
        raise SystemExit("[x] OF_EMAIL and OF_PASSWORD env vars are required")
    try:
        session = rl._bb_create_session()
    except RuntimeError as e:
        raise SystemExit(f"[x] {rl.scrub(e, password)} (failed loud)")
    print("[*] egress: Browserbase managed proxies (nothing persisted)", flush=True)

    sid = session.get("id")
    print(f"[*] session id: {sid}", flush=True)
    print(f"LIVEVIEW: {rl._bb_live_view_url(sid)}", flush=True)
    print("    ^ open this to watch and solve any Cloudflare / 2FA challenge", flush=True)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(session["connectUrl"])
            try:
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                err = rl.open_of(page)
                if err:
                    print(f"\n==> NAVIGATION FAILED: {rl.scrub(err, password)}", flush=True)
                    return 1
                time.sleep(4)
                print("[*] typing credentials ...", flush=True)
                rl._type_credentials(page, email, password)
                deadline = time.time() + POLL_WINDOW_S
                last = None
                while time.time() < deadline:
                    if rl._auth_id(ctx):
                        names = sorted({c.get("name") for c in ctx.cookies() if c.get("name")})
                        print("\n==> LOGIN: SUCCESS (auth_id cookie set)", flush=True)
                        print(f"[*] cookie names: {', '.join(names)}", flush=True)
                        print("[*] (not persisted)", flush=True)
                        return 0
                    if rl._detect_challenge(page):
                        state = "CHALLENGE — solve it in the live view"
                    elif rl._detect_otp(page):
                        state = "OTP — enter the 2FA code in the live view"
                    else:
                        state = "waiting for OnlyFans ..."
                    if state != last:
                        print(f"[*] {state}", flush=True)
                        last = state
                    time.sleep(TICK_S)
                print("\n==> LOGIN: TIMEOUT (no auth cookie within the window)", flush=True)
                return 1
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[x] {rl.scrub(f'{type(e).__name__}: {e}', password)}")
    finally:
        rl._bb_release(sid)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
