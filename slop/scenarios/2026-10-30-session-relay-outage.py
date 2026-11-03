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
7. Signed in again by the form; the browser's /auth/me answered 403 at the wire (the blocking
   proxy) -> reload -> the sign-in form with the `[data-auth-blocked]` "Proxy blocked (403)" banner
   (`ms_403_to_banner`: first 403 -> banner); at 390x844 no horizontal scroll, banner, field and
   Login inside the viewport; the username typed, Retry with the 403 still on -> another 403, the
   form never unmounted (the typed username kept); 403 lifted, Retry -> the shell (GET /auth/me 200
   with the owner, `ms_retry_to_shell_after_403`). Screenshots blocked-1440, blocked-390 (the
   trigger), blocked-retry-kept-390, blocked-signed-in-390, blocked-signed-in-1440 (settled).
8. Cold reload (snapshot removed) with /auth/me AND /chatter/me held at the wire, never answered
   -> the sign-in form with the "Relay not answering" banner within ME_SLOW_MS + slack
   (`ms_held_to_banner`: first held /auth/me -> banner), not at the 15 s abort. 8a: the username
   typed, /auth/me answered 200 `null` while /chatter/me stays held -> the plain form, never
   unmounted (the typed username kept), then /chatter/me let through -> still the form. 8b: cold
   reload held again, /auth/me let through to the relay (200 with the owner) while /chatter/me
   stays held -> the shell at once (`ms_release_to_shell`); /chatter/me let through -> the shell
   stays. Screenshots hung-1440 (the trigger), hung-null-kept-1440, hung-released-1440,
   hung-user-shell-1440, hung-signed-in-1440 (settled).

Each step's checks FAIL on their own (with a `failed-<step>` picture) when a step cannot finish;
step 6 reloads into a signed-in shell first, so it does not hang on what earlier steps left.

Bypasses (declared): the outage is the relay's process group SIGKILLed on loopback, not a network
partition (Next answers the browser's /auth/me 5xx instead of the browser's fetch throwing; both
are NetErr in `probeAction`). Focus and visibilitychange are dispatched as DOM events (headless
Chromium has no window manager). Step 6's logout clears the cookie (the relay's logout is
stateless); it stands in for a revoked session, which the relay also answers with a 200 `null`.
Steps 7-8 answer or hold the browser's /auth/me and /chatter/me with Playwright routes on the
browser context: the blocking proxy and the silent relay in front of the app are out of reach
(a 403 from the proxy, a TCP connection that never answers). The relay stays up behind them;
the released requests go on to it unchanged, except 8a's /auth/me, answered 200 `null` at the
wire (a signed-out cookie's answer, standing in for a session revoked meanwhile). Step 8 removes
the auth snapshot first: a warm boot paints the shell from it instead of the form (a fresh
device has none).

Faults (client side, `lib/session_faults.py`): `outage-revalidate-signs-out` (the scenario's:
`revalidateNetErr` signs out), `outage-boot-signs-out` (`bootNetErr` signs out, the old rule),
`auth-403-as-unreachable` (a boot 403 is NetErr: the retry screen), `auth-me-waits-15s` (no
`probeSlow`: the gate waits for the 15 s abort), `gate-waits-chatter-probe` (gateScreen asks the
chatter probe first) and `late-answer-drops-form` (a late boot answer puts the gate back to
waiting on the hung chatter probe); each turns only its own checks red. Each of steps 7-8's
checks records its `parts` and the `red` ones.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.session_faults import (
    BLOCKED_LOGIN, BOOT_RETRY, HUNG_LOGIN, LOGIN, LOGOUT_OUT, REVAL_BACK, REVAL_KEEP, RETRY_IN,
)
from slop.seed.agency import PASSWORD

PROFILE = "agency_inbox"
UI = True
FAULT = "outage-revalidate-signs-out"
VIEWPORT = (1440, 900)
PHONE = (390, 844)  # phone portrait, step 7
WAIT_MS = 180_000  # the first visit compiles the page in next dev; the machine may be loaded
SNAPSHOT_KEY = "chatterly:auth-snapshot:v1"  # app/lib/authSnapshot.ts
SHELL = 'nav[aria-label="Main"]'
FORM = 'section[aria-label="Sign in"]'
RETRY = "[data-auth-unreachable]"
BANNER = "[data-auth-blocked]"
ME_SLOW_MS = 3_000  # app/contexts/UserContext.tsx
SLOW_SLACK_MS = 2_000  # the timer's render + Playwright's polling on a loaded machine


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
             "boot-down": (BOOT_RETRY,), "retry": (RETRY_IN,), "logout": (LOGOUT_OUT,),
             "blocked": (BLOCKED_LOGIN,), "hung": (HUNG_LOGIN,)}
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

        signed_in = {"signin_form": 0, "shell": True, "retry_screen": 0, "snapshot_user": owner["user_id"]}

        def since(n: int) -> list:
            """The statuses of the /auth/me records from index n on."""
            return [st for _, st in me[n:]]

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
            flight swallows a focus); then the answer's render. The /auth/me statuses since n0."""
            for _ in range(10):
                await page.evaluate("() => { window.dispatchEvent(new Event('focus'));"
                                    " document.dispatchEvent(new Event('visibilitychange')); }")
                if await _until(lambda: _true(len(me) > n0), 3):
                    break
            await page.wait_for_timeout(1500)
            return since(n0)

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

        async def banner() -> dict:
            b = page.locator(BANNER)
            if not await b.count():
                return {"kind": None, "text": None, "role": None}
            return {"kind": await b.first.get_attribute("data-auth-blocked"), "text": await b.first.text_content(),
                    "role": await b.first.get_attribute("role")}

        async def fill_login(password: bool = True) -> None:
            await page.locator('input[autocomplete="username"]').fill(owner["username"])
            if password:
                await page.locator('input[autocomplete="current-password"]').fill(PASSWORD)
                await page.get_by_role("button", name="Login").click()

        @contextlib.asynccontextmanager
        async def wire(handler, *pats: str):
            """`pats` routed to `handler` on the browser context (the stand-in proxy / silent relay)
            for the block; unrouted on exit."""
            for pat in pats:
                await page.context.route(pat, handler)
            try:
                yield
            finally:
                for pat in pats:
                    await page.context.unroute(pat, handler)

        def verdict(parts: dict) -> tuple[bool, dict]:
            return all(parts.values()), {"parts": parts, "red": [k for k, v in parts.items() if not v]}

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
            await fill_login()
            await page.locator(SHELL).first.wait_for(timeout=WAIT_MS)
            await page.wait_for_function(f"() => localStorage.getItem('{SNAPSHOT_KEY}') !== null", timeout=30_000)
            await page.wait_for_timeout(1000)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "signed-in")
            chk(LOGIN, s == signed_in
                and bme == {"status": 200, "user_id": owner["user_id"]}, seen=s, browser_me=bme)

        async def reval_down(chk) -> None:
            kill()
            sent = await focus(len(me))
            s = await seen()
            await ui.shot(ctx, page, "revalidate-relay-down")
            failed = [st for st in sent if st is None or st >= 500]
            chk(REVAL_KEEP, len(failed) >= 1 and s == signed_in,
                me_during_outage=sent, seen=s)

        async def reval_back(chk) -> None:
            ctx.metric("ms_relay_restart_1", round(await revive()))
            sent = await focus(len(me))
            await page.locator(SHELL).first.wait_for(timeout=30_000)
            s, bme = await seen(), await browser_me()
            await ui.shot(ctx, page, "revalidate-relay-back")
            chk(REVAL_BACK, 200 in sent
                and s == signed_in
                and bme == {"status": 200, "user_id": owner["user_id"]},
                me_after_restart=sent, seen=s, browser_me=bme)

        async def boot_down(chk) -> None:
            kill()
            n0, t0 = len(me), time.time()
            await page.reload(wait_until="domcontentloaded", timeout=WAIT_MS)
            # settled: the retry screen, or the sign-in form (the old rule), whichever the boot shows
            await _until(lambda: _any(page, (RETRY, FORM)), 60)
            ctx.metric("ms_reload_to_settled_relay_down", round((time.time() - t0) * 1000))
            await page.wait_for_timeout(1000)
            booted = since(n0)
            s1 = await seen()
            n1 = len(me)
            await page.evaluate("() => { window.dispatchEvent(new Event('focus'));"
                                " document.dispatchEvent(new Event('visibilitychange')); }")
            await page.wait_for_timeout(2000)
            s2, focus_sent = await seen(), since(n1)
            await ui.shot(ctx, page, "boot-relay-down")
            want = {"signin_form": 0, "shell": False, "retry_screen": 1, "snapshot_user": owner["user_id"]}
            chk(BOOT_RETRY, any(st is None or st >= 500 for st in booted) and s1 == want and s2 == want
                and not focus_sent, me_at_boot=booted, seen=s1, after_focus=s2,
                me_after_focus=focus_sent)

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
            chk(RETRY_IN, 200 in since(n0) and s == signed_in
                and bme == {"status": 200, "user_id": owner["user_id"]},
                me_after_retry=since(n0), seen=s, browser_me=bme)

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
            chk(LOGOUT_OUT, r.status == 200 and 200 in sent
                and s == {"signin_form": 1, "shell": False, "retry_screen": 0, "snapshot_user": None}
                and bme == {"status": 200, "user_id": None},
                logout_status=r.status, cookies_after_logout=cookies, me_after=sent,
                seen=s, browser_me=bme)

        async def signed_in_shell() -> None:
            """The shell, signed in by the form if the boot settles on it (what step 6 leaves)."""
            if not relay_up["v"]:
                await revive()
            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded", timeout=WAIT_MS)
            await _until(lambda: _any(page, (SHELL, FORM)), WAIT_MS / 1000)
            await page.wait_for_timeout(1500)  # a painted snapshot's shell may still turn into the form
            if await page.locator(FORM).count():
                await fill_login()
            await page.locator(SHELL).first.wait_for(timeout=WAIT_MS)
            await page.wait_for_function(f"() => localStorage.getItem('{SNAPSHOT_KEY}') !== null", timeout=30_000)

        async def blocked(chk) -> None:
            await signed_in_shell()
            hits: list[float] = []  # epoch s of each 403 the "proxy" answered

            async def r403(route) -> None:
                hits.append(time.time())
                await route.fulfill(status=403, content_type="text/html", body="<h1>403 Forbidden</h1>")
            b_want = {"kind": "blocked", "text": "Proxy blocked (403)—Retry", "role": "status"}
            try:
                async with wire(r403, "**/auth/me"):
                    await page.reload(wait_until="domcontentloaded", timeout=WAIT_MS)
                    await _until(lambda: _any(page, (BANNER, RETRY)), 60)
                    t_banner = time.time()
                    b1, s1 = await banner(), await seen()
                    if hits and b1["kind"] == "blocked":
                        ctx.metric("ms_403_to_banner", round((t_banner - hits[0]) * 1000))
                    await ui.shot(ctx, page, "blocked-1440")
                    parts = {"banner_blocked": b1 == b_want,
                             "form_not_shell": s1["signin_form"] == 1 and s1["retry_screen"] == 0 and not s1["shell"]}
                    if b1["kind"] is None:
                        chk(BLOCKED_LOGIN, False, **verdict(parts)[1], banner=b1, seen=s1, me_403s=len(hits))
                        return
                    await page.set_viewport_size({"width": PHONE[0], "height": PHONE[1]})
                    await page.wait_for_timeout(500)
                    phone = await page.evaluate("""() => {
                        const vw = window.innerWidth;
                        const fits = (sel) => { const e = document.querySelector(sel); if (!e) return null;
                            const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= 0 && r.right <= vw; };
                        return { vw, scroll_w: document.documentElement.scrollWidth, banner: fits('[data-auth-blocked]'),
                                 username: fits('input[autocomplete="username"]'), login: fits('button[type="submit"]') };
                    }""")
                    parts["phone_fits"] = (phone["scroll_w"] <= phone["vw"] and phone["banner"] and phone["username"]
                                           and phone["login"]) is True
                    await ui.shot(ctx, page, "blocked-390")
                    await fill_login(password=False)
                    n1, h1 = len(me), len(hits)
                    await page.locator(BANNER).get_by_role("button", name="Retry").click()
                    await _until(lambda: _true(len(hits) > h1 and 403 in since(n1)), 10)
                    await page.wait_for_timeout(1000)
                    kept = {"username": await page.locator('input[autocomplete="username"]').input_value(),
                            **await banner(), "signin_form": await page.locator(FORM).count(),
                            "retry_screen": await page.locator(RETRY).count()}
                    retry_sent = since(n1)
                    parts["retry_403_form_kept"] = 403 in retry_sent and kept == {
                        "username": owner["username"], **b_want, "signin_form": 1, "retry_screen": 0}
                    await ui.shot(ctx, page, "blocked-retry-kept-390")
                n2, t0 = len(me), time.time()
                await page.locator(BANNER).get_by_role("button", name="Retry").click()
                await _until(lambda: _true(200 in since(n2)), 30)
                await page.locator(FORM).wait_for(state="detached", timeout=30_000)
                ctx.metric("ms_retry_to_shell_after_403", round((time.time() - t0) * 1000))
                await page.wait_for_timeout(1000)
                await ui.shot(ctx, page, "blocked-signed-in-390")
                await page.set_viewport_size({"width": VIEWPORT[0], "height": VIEWPORT[1]})
                await page.locator(SHELL).first.wait_for(timeout=30_000)
                await page.wait_for_timeout(500)
                s3, bme, b3 = await seen(), await browser_me(), await banner()
                await ui.shot(ctx, page, "blocked-signed-in-1440")
                parts["lifted_retry_signs_in"] = (200 in since(n2) and b3["kind"] is None and s3 == signed_in
                                                  and bme == {"status": 200, "user_id": owner["user_id"]})
                ok, why = verdict(parts)
                chk(BLOCKED_LOGIN, ok, **why, banner=b1, seen=s1, phone=phone, after_retry_403=kept,
                    me_retry_403=retry_sent, me_retry_lifted=since(n2), seen_end=s3, browser_me=bme)
            finally:
                await page.set_viewport_size({"width": VIEWPORT[0], "height": VIEWPORT[1]})

        async def hung(chk) -> None:
            budget = ME_SLOW_MS + SLOW_SLACK_MS
            want = {"kind": "slow", "text": "Relay not answering—Retry", "role": "status"}
            parts: dict[str, bool] = {}
            detail: dict = {"budget_ms": budget}

            async def held_boot(tag: str) -> None:
                """A cold reload with /auth/me and /chatter/me held (`held`: route, epoch s, path; never
                answered until released); the banner and the gate as they settle (`parts`, `detail`)."""
                held.clear()  # what a former page left unanswered dies with the reload
                await page.evaluate(f"() => localStorage.removeItem('{SNAPSHOT_KEY}')")
                await page.reload(wait_until="domcontentloaded", timeout=WAIT_MS)
                # long enough to see a gate that waits for the 15 s abort miss the budget, not to sit it out
                await _until(lambda: _any(page, (BANNER, RETRY)), budget / 1000 + 5)
                t_banner = time.time()
                b, s = await banner(), await seen()
                t_me = [t for _, t, p in held if p == "/auth/me"]
                ms = round((t_banner - t_me[0]) * 1000) if t_me and b["kind"] == "slow" else None
                if tag == "a" and ms is not None:
                    ctx.metric("ms_held_to_banner", ms)
                parts[f"{tag}_banner_slow_in_budget"] = b == want and ms is not None and ms <= budget
                parts[f"{tag}_form_not_shell"] = s["signin_form"] == 1 and s["retry_screen"] == 0 and not s["shell"]
                detail[f"{tag}_banner"], detail[f"{tag}_seen"], detail[f"{tag}_ms_held_to_banner"] = b, s, ms

            async def release(path: str, null: bool = False) -> list:
                """Answer the held `path` requests: 200 `null` at the wire, or let them through to the relay."""
                out = []
                for h in [h for h in held if h[2] == path]:
                    held.remove(h)
                    try:
                        if null:
                            await h[0].fulfill(status=200, content_type="application/json", body="null")
                        else:
                            await h[0].continue_()
                        out.append(path)
                    except Exception as e:  # noqa: BLE001 — the page aborted it (the 15 s timeout)
                        out.append(f"{path}: {type(e).__name__}")
                return out

            async def form_state() -> dict:
                return {"username": (await page.locator('input[autocomplete="username"]').input_value()
                                     if await page.locator(FORM).count() else None),
                        "banner": (await banner())["kind"], **await seen()}

            held: list[tuple[object, float, str]] = []

            async def hold(route) -> None:
                held.append((route, time.time(), urlsplit(route.request.url).path))
            await signed_in_shell()
            try:
                # 8a: a late signed-out answer while the chatter probe hangs: the form stays up
                async with wire(hold, "**/auth/me", "**/chatter/me"):
                    await held_boot("a")
                    await ui.shot(ctx, page, "hung-1440")
                    if not parts["a_form_not_shell"]:
                        ok, why = verdict(parts)
                        chk(HUNG_LOGIN, False, **why, **detail)
                        return
                    await fill_login(password=False)
                    n0 = len(me)
                    detail["a_released_me"] = await release("/auth/me", null=True)
                    await _until(lambda: _true(200 in since(n0)), 10)
                    await page.wait_for_timeout(1000)
                    k1 = await form_state()
                    await ui.shot(ctx, page, "hung-null-kept-1440")
                    plain = {"username": owner["username"], "banner": None, "signin_form": 1, "shell": False,
                             "retry_screen": 0, "snapshot_user": None}
                    parts["a_late_null_form_kept"] = k1 == plain
                    detail["a_released_chatter"] = await release("/chatter/me")
                    await page.wait_for_timeout(1500)
                    k2 = await form_state()
                    await ui.shot(ctx, page, "hung-released-1440")
                    parts["a_chatter_released_form_kept"] = k2 == plain
                    detail["a_after_null"], detail["a_after_chatter"] = k1, k2
                # 8b: a late signed-in answer while the chatter probe hangs: the shell at once
                async with wire(hold, "**/auth/me", "**/chatter/me"):
                    await held_boot("b")
                    n1, t0 = len(me), time.time()
                    detail["b_released_me"] = await release("/auth/me")
                    shell = await _until(lambda: _visible(page, SHELL), 15)
                    if shell:
                        ctx.metric("ms_release_to_shell", round((time.time() - t0) * 1000))
                    await ui.shot(ctx, page, "hung-user-shell-1440")
                    parts["b_late_user_shell_chatter_hung"] = shell and 200 in since(n1)
                    detail["b_released_chatter"] = await release("/chatter/me")
                await page.locator(SHELL).first.wait_for(timeout=30_000)
                await page.wait_for_timeout(1000)
                s2, bme, b2 = await seen(), await browser_me(), await banner()
                await ui.shot(ctx, page, "hung-signed-in-1440")
                parts["b_settled_shell"] = (b2["kind"] is None and s2 == signed_in
                                            and bme == {"status": 200, "user_id": owner["user_id"]})
                ok, why = verdict(parts)
                chk(HUNG_LOGIN, ok, **why, **detail, me_after_release=since(n1), seen_end=s2, browser_me=bme)
            finally:
                for h in held:
                    try:
                        await h[0].continue_()
                    except Exception:  # noqa: BLE001
                        pass

        for name, fn in (("login", login), ("reval-down", reval_down), ("reval-back", reval_back),
                         ("boot-down", boot_down), ("retry", retry), ("logout", logout),
                         ("blocked", blocked), ("hung", hung)):
            await step(name, fn)
        if not relay_up["v"]:
            await revive()
        ctx.metric("auth_me_statuses", [st for _, st in me])
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))


async def _true(v: bool) -> bool:
    return v


async def _visible(page, sel) -> bool:
    loc = page.locator(sel)
    return await loc.count() > 0 and await loc.first.is_visible()


async def _any(page, sels) -> bool:
    for s in sels:
        if await page.locator(s).count():
            return True
    return False
