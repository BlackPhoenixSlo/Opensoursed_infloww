"""Add creator > Browserbase login with OnlyFans 2FA. The owner starts a served
login (POST /admin/login/remote/start); the relay drives a remote Chromium
through OnlyFans' login form until OnlyFans asks for the 2FA code (job state
"otp"); the code typed on the card (POST /admin/login/remote/{id}/otp) is
typed into OnlyFans' own 2FA field by the job's thread. A wrong code comes back
as rejected ("OnlyFans didn't accept that code …") with the job still on the prompt, and the next
code signs in: capture, persist, link to the owner. A flow, not a volume one:
one owner, two logins (one over the API, one through the card in the app).

The outside world is lib/browserbase.py, on loopback: Browserbase's API (a
fresh local Chromium per session, driven by the relay over CDP), its live view
(a stand-in showing that Chromium's tab) and OnlyFans' site (login form, 2FA
prompt, chats page with a signed request and OF's signing module, which the
login extension's interceptor captures). `POST /__slop/browserbase` points the
relay at it. Everything between is the relay's own code.

Invariants: the job stops on the 2FA prompt with a live view; a wrong code is
reported as rejected and the job stays on the prompt; the right code signs in
and the session is saved and linked to the owner (`accounts` + `user_accounts`
rows, GET /admin/accounts); OnlyFans' field got exactly the submitted codes;
one code at a time (a second one while the first is checked is 409); a code for
a finished job is 409; a malformed code or body is 400, never echoed; no 2FA code or password in any status or in
relay.log; the Browserbase session is released. The card (UI): the 2FA field
appears with the live view still on screen, a wrong code shows the rejection,
the right one links the account.
Screenshots: card-otp-prompt, card-otp-rejected, card-otp-linked.
Break-it-once: FAULT otp-code-never-consumed (the job never reads the code).
"""
from __future__ import annotations

import asyncio
import json
import time

from playwright.async_api import async_playwright

from slop.actors import ui
from slop.lib.browserbase import World
from slop.lib.client import Http, Recorder

PROFILE = "agency_inbox"
UI = True
FAULT = "otp-code-never-consumed"
VIEWPORT = (1440, 1000)
PASSWORD = "slop-of-Password-77"
OTP, WRONG = "246810", "135791"
API_EMAIL, API_UID = "otp-api@slop.test", "990000101"
UI_EMAIL, UI_UID = "otp-card@slop.test", "990000102"
VERIFY_S = 15 + 20  # remote_login.OTP_VERIFY_S, plus a poll and OnlyFans' answer
ASK = "OnlyFans asks for the 2FA code"
REJECTED = "OnlyFans didn't accept that code (or hasn't answered yet) — try again"  # remote_login.OTP_REJECTED
CHECKING = "checking the 2FA code"  # remote_login.OTP_CHECKING


async def _until(owner: Http, jid: str, cond, timeout: float, seen: list) -> dict:
    """Poll the job's status (as the card does) until cond(status) or timeout; every status is kept in `seen`."""
    deadline = time.monotonic() + timeout
    while True:
        st = (await owner.get(f"/admin/login/remote/{jid}")).json()
        seen.append(st)
        if cond(st) or time.monotonic() > deadline or st.get("state") in ("done", "error", "cancelled"):
            return st
        await asyncio.sleep(0.5)


async def _api_login(ctx, owner: Http, world: World, seen: list) -> None:
    r = await owner.post("/admin/login/remote/start", json={
        "email": API_EMAIL, "password": PASSWORD, "backend": "browserbase", "proxy": "none",
        "nickname": "Slop 2FA API"})
    ctx.check("API: start answers 200", r.status_code == 200, http_status=r.status_code, body=r.text[:300])
    if r.status_code != 200:
        return
    seen.append(r.json())
    jid = r.json()["id"]
    st = await _until(owner, jid, lambda s: s["state"] == "otp", 90, seen)
    ctx.check("API: the job stops on OnlyFans' 2FA prompt (state otp) with a live view",
              st["state"] == "otp" and st["message"].startswith(ASK)
              and (st.get("live_view_url") or "").startswith(f"http://127.0.0.1:{world.api_port}/live/"),
              state=st["state"], message=st["message"], live_view_url=st.get("live_view_url"),
              logins=world.logins)

    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": WRONG})
    seen.append(r.json() if r.status_code == 200 else {"status": r.status_code, "text": r.text})
    post_message = r.json().get("message") if r.status_code == 200 else None
    again = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    ctx.check("API: one code at a time — a second code while one is checked is 409, never echoed",
              again.status_code == 409 and OTP not in again.text and post_message == CHECKING,
              http_status=again.status_code, first_post_message=post_message)
    st = await _until(owner, jid, lambda s: s["message"] == REJECTED, VERIFY_S, seen)
    ctx.check("API: a wrong 2FA code comes back as rejected and the job stays on the 2FA prompt",
              r.status_code == 200 and st["state"] == "otp" and st["message"] == REJECTED,
              post_status=r.status_code, state=st["state"], message=st["message"], of_tries=len(world.otp_tries))

    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    seen.append(r.json() if r.status_code == 200 else {"status": r.status_code, "text": r.text})
    st = await _until(owner, jid, lambda s: s["state"] == "done", 60, seen)
    owner_id = ctx.world.user_id
    con = ctx.world.sql()
    acc = con.execute("SELECT id, nickname FROM accounts WHERE id=?", (API_UID,)).fetchone()
    link = con.execute("SELECT user_id FROM user_accounts WHERE account_id=?", (API_UID,)).fetchall()
    listed = [a.get("id") for a in (await owner.get("/admin/accounts")).json().get("accounts", [])]
    session_files = sorted(p.name for p in (ctx.stack.sessions / "accounts" / API_UID).glob("session_*.json"))
    ctx.check("API: the right 2FA code signs in; the session is saved and linked to the owner",
              st["state"] == "done" and st["account_id"] == API_UID and acc is not None
              and [u for (u,) in link] == [owner_id] and API_UID in listed and bool(session_files),
              state=st["state"], error=st.get("error"), account_id=st.get("account_id"), accounts_row=acc,
              user_accounts=link, owner_id=owner_id, listed=API_UID in listed, session_files=session_files)
    if st["state"] != "done":  # a stuck job: stop it so the checks below see a finished job
        await owner.post(f"/admin/login/remote/{jid}/cancel")
        await _until(owner, jid, lambda s: s["state"] in ("done", "error", "cancelled"), 30, seen)

    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    ctx.check("API: a 2FA code for a finished job is 409", r.status_code == 409, http_status=r.status_code)
    bad = {"12ab": {"code": "12ab"}, "135792": {"code": 135792}, "135793": ["135793"]}
    answers = {k: await owner.post(f"/admin/login/remote/{jid}/otp", json=v) for k, v in bad.items()}
    ctx.check("API: a malformed 2FA code or body is 400, never echoed",
              all(a.status_code == 400 and k not in a.text for k, a in answers.items()),
              http_status={k: a.status_code for k, a in answers.items()})
    ctx.metric("api_job", {"id": jid, "statuses": len(seen), "final": st})


async def _card_login(ctx, world: World, owner: Http) -> None:
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
        await page.get_by_role("button", name="Add creator").first.click(timeout=120_000)
        dlg = page.get_by_role("dialog", name="Add creator")
        await dlg.get_by_label("Creator name").fill("Slop Card")
        await dlg.get_by_label("Gender").select_option(index=1)
        await dlg.get_by_role("button", name="Next: Link creator account").click()
        await page.get_by_role("button", name="Next", exact=True).click(timeout=30_000)  # OnlyFans
        await page.get_by_role("button", name="Connect OnlyFans").click(timeout=30_000)
        await page.get_by_label("OnlyFans email").fill(UI_EMAIL, timeout=60_000)
        await page.get_by_label("OnlyFans password").fill(PASSWORD)
        async with page.expect_response(lambda r: r.url.endswith("/admin/login/remote/start")) as started:
            await page.get_by_role("button", name="Try Browserbase login").click()
        jid = (await (await started.value).json()).get("id")

        field = page.get_by_label("2FA code")
        prompt = True
        try:
            await field.wait_for(timeout=90_000)
            await page.wait_for_timeout(2500)  # the live view stand-in's next frame
        except Exception:  # noqa: BLE001
            prompt = False
        live = await page.get_by_title("Browserbase live view").count()
        focused = await page.evaluate("document.activeElement && document.activeElement.id")
        await page.get_by_title("Browserbase live view").first.scroll_into_view_if_needed() if live else None
        await field.scroll_into_view_if_needed() if prompt else None
        await ui.shot(ctx, page, "card-otp-prompt")
        ctx.check("card: OnlyFans' 2FA prompt shows the code field (focused) with the live view still on screen",
                  prompt and live == 1 and focused == "bb-otp", field=prompt, live_view_iframes=live, focused=focused)
        if not prompt:
            return

        submit = page.get_by_role("button", name="Submit code")
        await field.fill(WRONG)
        await submit.click()
        rejected = page.get_by_role("alert").filter(has_text="OnlyFans didn't accept that code")
        try:
            await rejected.wait_for(timeout=VERIFY_S * 1000)
            shown = True
        except Exception:  # noqa: BLE001
            shown = False
        await ui.shot(ctx, page, "card-otp-rejected")
        ctx.check("card: a wrong code shows the rejection and the field takes another code", shown
                  and await field.is_editable(), rejected_shown=shown)

        await field.fill(OTP)
        try:  # disabled while a code is still being checked (never, when the first was rejected)
            await submit.click(timeout=10_000)
        except Exception:  # noqa: BLE001
            pass
        linked = page.get_by_text(UI_UID).first
        try:
            await linked.wait_for(timeout=60_000)
            done = True
        except Exception:  # noqa: BLE001
            done = False
        await page.wait_for_timeout(1000)
        await ui.shot(ctx, page, "card-otp-linked")
    st = (await owner.get(f"/admin/login/remote/{jid}")).json() if jid else {}
    if jid and st.get("state") not in ("done", "error", "cancelled"):  # stuck: stop it (and its BB session)
        await owner.post(f"/admin/login/remote/{jid}/cancel")
        await _until(owner, jid, lambda s: s["state"] in ("done", "error", "cancelled"), 30, [])
    row = ctx.world.sql().execute("SELECT user_id FROM user_accounts WHERE account_id=?", (UI_UID,)).fetchall()
    ctx.check("card: the right code links the account (job done, user_accounts row)",
              done and st.get("state") == "done" and st.get("account_id") == UI_UID and len(row) == 1,
              shown_on_card=done, state=st.get("state"), account_id=st.get("account_id"), user_accounts=row)


async def run(ctx) -> None:
    await ctx.build(PROFILE)
    async with async_playwright() as p:
        chromium = p.chromium.executable_path
    hooks = Http(ctx.relay, Recorder())  # the hook call is not an actor call
    seen: list[dict] = []
    with World(ctx.stack.tmp, accounts={API_EMAIL: API_UID, UI_EMAIL: UI_UID}, otp=OTP, password=PASSWORD,
               chromium=chromium) as world:
        r = await hooks.post("/__slop/browserbase", json={"api": world.api, "chunk_url_tpl": world.chunk_url_tpl})
        assert r.status_code == 200, r.text
        await hooks.aclose()
        await _api_login(ctx, ctx.owner, world, seen)
        ctx.check("OnlyFans' 2FA field received exactly the codes submitted, in order",
                  world.otp_tries == [WRONG, OTP], of_tries=world.otp_tries)
        if ctx.app is None:
            for c in ("card: OnlyFans' 2FA prompt shows the code field (focused) with the live view still on screen",
                      "card: a wrong code shows the rejection and the field takes another code",
                      "card: the right code links the account (job done, user_accounts row)"):
                ctx.skip(c, "--no-ui")
        else:
            await _card_login(ctx, world, ctx.owner)
        await asyncio.sleep(1)  # the job thread's release call
        sessions = {sid: s["released"] for sid, s in world.sessions.items()}
        ctx.check("every Browserbase session the relay created was released", bool(sessions)
                  and all(sessions.values()), sessions=sessions)
        ctx.metric("browserbase_calls", world.calls)
        ctx.metric("of_logins", world.logins)

    (ctx.out / "api-job-statuses.json").write_text(json.dumps(seen, indent=2))
    relay_log = (ctx.out / "relay.log").read_text(errors="replace") if (ctx.out / "relay.log").exists() else ""
    blob = json.dumps(seen) + relay_log
    leaks = [s for s in (OTP, WRONG, PASSWORD) if s in blob]
    ctx.check("no 2FA code or password in any status or in relay.log", not leaks, leaked=len(leaks),
              statuses=len(seen), relay_log_bytes=len(relay_log))
