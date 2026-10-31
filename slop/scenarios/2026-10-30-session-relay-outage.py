"""Auth session survives a relay outage (app/contexts/userSessionReducer.ts, 0357a072c) on the real
path: the relay process killed and restarted (`crash_relay` / `start_relay`, same DB, port, env),
`next dev` proxying /auth/me to it, one owner in Chromium (1440x900), `agency_inbox`. A rule
flow, not a volume one: `--users` and `--scale` change nothing, so no latency budget; the
outage's timings are metrics (`ms_*`).

1. Signed-out browser on `/` -> the sign-in form; the seeded owner types username + password,
   Login -> the app shell (`nav[aria-label="Main"]`). Side effects: the browser's GET /auth/me
   200 with the owner, the auth snapshot in localStorage. Screenshots login-form, signed-in.
2. Relay SIGKILLed; window focus + visibilitychange -> the revalidate's /auth/me fails (Next's
   proxy answers 5xx) -> the shell stays, no sign-in form, no retry screen, snapshot kept.
   Screenshot revalidate-relay-down.
3. Relay restarted; focus -> /auth/me 200, shell stays. Screenshot revalidate-relay-back.
4. Relay SIGKILLed; reload (boot with the relay down) -> the retry screen `[data-auth-unreachable]`,
   not the sign-in form, snapshot kept; a focus there sends no /auth/me. Screenshot boot-relay-down.
5. Relay restarted; Retry -> the shell; GET /auth/me 200 with the owner. Screenshots
   retry-clicked (the trigger), retry-signed-in (the settled end state).
6. Relay up: POST /auth/logout from the browser's session (another tab signing out clears the
   shared cookie), focus -> /auth/me 200 `null` -> the sign-in form, snapshot cleared.
   Screenshot logout-revalidate.

Each step's checks FAIL on their own (with a `failed-<step>` picture) when a step cannot finish;
step 6 reloads into a signed-in shell first, so it does not hang on what earlier steps left.

Bypasses (declared): the outage is the relay's process group SIGKILLed on loopback, not a network
partition (Next answers the browser's /auth/me 5xx instead of the browser's fetch throwing; both
are NetErr in `probeAction`). Focus and visibilitychange are dispatched as DOM events (headless
Chromium has no window manager). Step 6's logout clears the cookie (the relay's logout is
stateless); it stands in for a revoked session, which the relay also answers with a 200 `null`.

Faults (client side, `lib/session_faults.py`): `outage-revalidate-signs-out` (the scenario's:
`revalidateNetErr` signs out) and `outage-boot-signs-out` (`bootNetErr` signs out, the old rule);
each turns only its own checks red.
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.session_faults import BOOT_RETRY, LOGIN, LOGOUT_OUT, REVAL_BACK, REVAL_KEEP, RETRY_IN
from slop.seed.agency import PASSWORD

PROFILE = "agency_inbox"
UI = True
FAULT = "outage-revalidate-signs-out"
VIEWPORT = (1440, 900)
WAIT_MS = 180_000  # the first visit compiles the page in next dev; the machine may be loaded
SNAPSHOT_KEY = "chatterly:auth-snapshot:v1"  # app/lib/authSnapshot.ts
SHELL = 'nav[aria-label="Main"]'
FORM = 'section[aria-label="Sign in"]'
RETRY = "[data-auth-unreachable]"


async def _until(cond, timeout_s: float) -> bool:
    loop = asyncio.get_running_loop()
    t_end = loop.time() + timeout_s
    while not await cond() and loop.time() < t_end:
        await asyncio.sleep(0.1)
    return await cond()


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    owner = w.data["agency"]
    steps = {"login": (LOGIN,), "reval-down": (REVAL_KEEP,), "reval-back": (REVAL_BACK,),
             "boot-down": (BOOT_RETRY,), "retry": (RETRY_IN,), "logout": (LOGOUT_OUT,)}
    if ctx.app is None:
        for checks in steps.values():
            for c in checks:
                ctx.skip(c, "--no-ui")
        return

    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.context.clear_cookies()  # owner_browser signs in by cookie: this flow signs in by the form
        me: list[tuple[float, int | None]] = []  # every /auth/me the page sent: (epoch s, status; None = failed)
        page.on("response", lambda r: me.append((time.time(), r.status))
                if urlsplit(r.url).path == "/auth/me" else None)
        page.on("requestfailed", lambda r: me.append((time.time(), None))
                if urlsplit(r.url).path == "/auth/me" else None)

        async def seen() -> dict:
            snap = await page.evaluate(f"() => JSON.parse(localStorage.getItem('{SNAPSHOT_KEY}') || 'null')")
            return {"signin_form": await page.locator(FORM).count(),
                    "shell": await page.locator(SHELL).count() > 0 and await page.locator(SHELL).first.is_visible(),
                    "retry_screen": await page.locator(RETRY).count(),
                    "snapshot_user": ((snap or {}).get("user") or {}).get("user_id")}

        async def browser_me() -> dict:
            r = await page.request.get(f"{ctx.app}/auth/me", headers={"Accept": "application/json"})
            try:
                body = await r.json()
            except Exception:  # noqa: BLE001
                body = (await r.text())[:200]
            return {"status": r.status, "user_id": (body or {}).get("user_id") if isinstance(body, dict) else body}

        async def focus(n0: int) -> list:
            """Focus + visibilitychange until one /auth/me went out after index n0 (a revalidation in
            flight swallows a focus); then the answer's render. The /auth/me records since n0."""
            for _ in range(10):
                await page.evaluate("() => { window.dispatchEvent(new Event('focus'));"
                                    " document.dispatchEvent(new Event('visibilitychange')); }")
                if await _until(lambda: _true(len(me) > n0), 3):
                    break
            await page.wait_for_timeout(1500)
            return me[n0:]

        async def step(name: str, fn) -> None:
            done: set[str] = set()

            def chk(c: str, ok: bool, **detail) -> None:
                done.add(c)
                ctx.check(c, ok, **detail)
            try:
                await fn(chk)
            except Exception as e:  # noqa: BLE001 — a step that cannot finish is its checks' FAIL
                try:
                    await ui.shot(ctx, page, f"failed-{name}")
                except Exception:  # noqa: BLE001
                    pass
                for c in steps[name]:
                    if c not in done:
                        ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600], step=name)

        relay_up = {"v": True}

        def kill() -> float:
            relay_up["v"] = False
            return ctx.stack.crash_relay()

        async def revive() -> float:
            t = time.time()
            await asyncio.to_thread(ctx.stack.start_relay)
            relay_up["v"] = True
            return (time.time() - t) * 1000

        async def login(chk) -> None:
            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded", timeout=WAIT_MS)
            await page.locator(FORM).wait_for(timeout=WAIT_MS)
            await ui.shot(ctx, page, "login-form")
            await page.locator('input[autocomplete="username"]').fill(owner["username"])
            await page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
            await page.get_by_role("button", name="Login").click()
            await page.locator(SHELL).first.wait_for(timeout=WAIT_MS)
            await page.wait_for_function(f"() => localStorage.getItem('{SNAPSHOT_KEY}') !== null", timeout=30_000)
            await page.wait_for_timeout(1000)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "signed-in")
            chk(LOGIN, s == {"signin_form": 0, "shell": True, "retry_screen": 0, "snapshot_user": owner["user_id"]}
                and bme == {"status": 200, "user_id": owner["user_id"]}, seen=s, browser_me=bme)

        async def reval_down(chk) -> None:
            kill()
            sent = await focus(len(me))
            s = await seen()
            await ui.shot(ctx, page, "revalidate-relay-down")
            failed = [st for _, st in sent if st is None or st >= 500]
            chk(REVAL_KEEP, len(failed) >= 1 and s == {"signin_form": 0, "shell": True, "retry_screen": 0,
                                                     "snapshot_user": owner["user_id"]},
                me_during_outage=sent and [st for _, st in sent], seen=s)

        async def reval_back(chk) -> None:
            ctx.metric("ms_relay_restart_1", round(await revive()))
            sent = await focus(len(me))
            await page.locator(SHELL).first.wait_for(timeout=30_000)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "revalidate-relay-back")
            chk(REVAL_BACK, 200 in [st for _, st in sent]
                and s == {"signin_form": 0, "shell": True, "retry_screen": 0, "snapshot_user": owner["user_id"]}
                and bme == {"status": 200, "user_id": owner["user_id"]},
                me_after_restart=[st for _, st in sent], seen=s, browser_me=bme)

        async def boot_down(chk) -> None:
            kill()
            n0, t0 = len(me), time.time()
            await page.reload(wait_until="domcontentloaded", timeout=WAIT_MS)
            # settled: the retry screen, or the sign-in form (the old rule), whichever the boot shows
            await _until(lambda: _any(page, (RETRY, FORM)), 60)
            ctx.metric("ms_reload_to_settled_relay_down", round((time.time() - t0) * 1000))
            await page.wait_for_timeout(1000)
            booted = me[n0:]
            s1 = await seen()
            n1 = len(me)
            await page.evaluate("() => { window.dispatchEvent(new Event('focus'));"
                                " document.dispatchEvent(new Event('visibilitychange')); }")
            await page.wait_for_timeout(2000)
            s2, focus_sent = await seen(), me[n1:]
            await ui.shot(ctx, page, "boot-relay-down")
            want = {"signin_form": 0, "shell": False, "retry_screen": 1, "snapshot_user": owner["user_id"]}
            chk(BOOT_RETRY, any(st is None or st >= 500 for _, st in booted) and s1 == want and s2 == want
                and not focus_sent, me_at_boot=[st for _, st in booted], seen=s1, after_focus=s2,
                me_after_focus=[st for _, st in focus_sent])

        async def retry(chk) -> None:
            ctx.metric("ms_relay_restart_2", round(await revive()))
            n0 = len(me)
            btn = page.locator(RETRY).get_by_role("button", name="Retry")
            await btn.wait_for(timeout=10_000)
            await ui.shot(ctx, page, "retry-clicked")
            t0 = time.time()
            await btn.click()
            await page.locator(SHELL).first.wait_for(timeout=60_000)
            ctx.metric("ms_retry_to_shell", round((time.time() - t0) * 1000))
            await page.wait_for_timeout(1500)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "retry-signed-in")
            chk(RETRY_IN, 200 in [st for _, st in me[n0:]]
                and s == {"signin_form": 0, "shell": True, "retry_screen": 0, "snapshot_user": owner["user_id"]}
                and bme == {"status": 200, "user_id": owner["user_id"]},
                me_after_retry=[st for _, st in me[n0:]], seen=s, browser_me=bme)

        async def logout(chk) -> None:
            if not relay_up["v"]:
                await revive()
            await page.reload(wait_until="domcontentloaded", timeout=WAIT_MS)
            await page.locator(SHELL).first.wait_for(timeout=WAIT_MS)
            r = await page.request.post(f"{ctx.app}/auth/logout")
            cookies = [c["name"] for c in await page.context.cookies()]
            sent = await focus(len(me))
            await page.locator(FORM).wait_for(timeout=15_000)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "logout-revalidate")
            chk(LOGOUT_OUT, r.status == 200 and 200 in [st for _, st in sent]
                and s == {"signin_form": 1, "shell": False, "retry_screen": 0, "snapshot_user": None}
                and bme == {"status": 200, "user_id": None},
                logout_status=r.status, cookies_after_logout=cookies, me_after=[st for _, st in sent],
                seen=s, browser_me=bme)

        for name, fn in (("login", login), ("reval-down", reval_down), ("reval-back", reval_back),
                         ("boot-down", boot_down), ("retry", retry), ("logout", logout)):
            await step(name, fn)
        if not relay_up["v"]:
            await revive()
        ctx.metric("auth_me_statuses", [st for _, st in me])
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))


async def _true(v: bool) -> bool:
    return v


async def _any(page, sels) -> bool:
    for s in sels:
        if await page.locator(s).count():
            return True
    return False
