"""Add creator > Browserbase login with OnlyFans 2FA. The owner starts a served
login (POST /admin/login/remote/start); the relay drives a remote Chromium
through OnlyFans' login form until OnlyFans asks for the 2FA code (job state
"otp"); the code typed on the card (POST /admin/login/remote/{id}/otp) is
typed into OnlyFans' own 2FA field by the job's thread. A wrong code comes back
as rejected ("OnlyFans didn't accept that code …") with the job still on the prompt, and the next
code signs in: capture, persist, link to the owner. A flow, not a volume one:
one owner, four logins (three over the API, one through the card in the app).

The outside world is lib/browserbase.py, on loopback: Browserbase's API (a
fresh local Chromium per session, driven by the relay over CDP), its live view
(a stand-in showing that Chromium's tab) and OnlyFans' site (login form, 2FA
prompt, chats page with a signed request and OF's signing module, which the
login extension's interceptor captures). Every OnlyFans page carries a hidden
reCAPTCHA frame; the 2FA page a decoy form whose button is the page's first
submit button; a sent code takes OnlyFans VERIFY_MS ("Verifying…", no field)
to answer. `POST /__slop/browserbase` points the relay at it. Everything
between is the relay's own code.

The logins:
  API    a wrong code (a second one meanwhile is 409), rejected as soon as the
         prompt is back; the right code signs in; then 409 / 400 on the done job.
  AUTO   OnlyFans' 2FA field sends its form itself on the last digit: a wrong
         code is rejected (never "couldn't type"), the right one signs in.
  LATE   a job started with a short window (JOB_WINDOW_S via the hook, declared
         time compression): a code after its deadline is 404, as an expired job.
  card   (UI) the code field with the live view, "1234-5678" pasted is the
         8-digit code (wrong: rejected on the card), the right code links it.

Invariants: the job stops on the 2FA prompt with a live view though a hidden
captcha frame is on the page, and no status ever says "challenge"; a wrong
code is reported as rejected (from the prompt coming back, inside
OTP_VERIFY_S) and the job stays on the prompt; the right code signs in and the
session is saved and linked to the owner (`accounts` + `user_accounts` rows,
GET /admin/accounts); OnlyFans' field got exactly the submitted codes, each
sent with the 2FA form's own VERIFY button (or by the field itself), the
decoy never; one code at a time (409); a code for a finished job is 409, for
an expired one 404; a malformed code or body is 400, never echoed; no 2FA
code (wrong or right, any login) or password in any status, error,
relay.log or next.log; every Browserbase session is released.
Screenshots: card-otp-prompt, card-otp-pasted, card-otp-rejected, card-otp-linked.
Break-it-once: FAULT otp-code-never-consumed (the job never reads the code);
--fault=challenge-counts-hidden-frames (the pre-fix challenge check: any
captcha frame counts, on screen or not).
"""
from __future__ import annotations

import asyncio
import json
import time

from playwright.async_api import async_playwright

from slop.actors import ui
from slop.lib.browserbase import VERIFY_MS, World
from slop.lib.client import Http, Recorder

PROFILE = "agency_inbox"
UI = True
FAULT = "otp-code-never-consumed"
VIEWPORT = (1440, 1000)
PASSWORD = "slop-of-Password-77"
OTP, WRONG = "246810", "135791"
AUTO_WRONG = "975310"
PASTED, PASTED_CODE = "1234-5678", "12345678"  # the card's wrong code, pasted with its dash
API_EMAIL, API_UID = "otp-api@slop.test", "990000101"
UI_EMAIL, UI_UID = "otp-card@slop.test", "990000102"
AUTO_EMAIL, AUTO_UID = "otp-auto@slop.test", "990000103"  # its 2FA field submits itself
LATE_EMAIL, LATE_UID = "otp-late@slop.test", "990000104"  # its job runs out of time on the prompt
OTP_VERIFY_S = 15  # remote_login.OTP_VERIFY_S
CAPTURE_RESERVE_S = 60  # remote_login.CAPTURE_RESERVE_S: no code once past expires_at - this
LATE_WINDOW_S = 80  # the LATE job's JOB_WINDOW_S: its code deadline is 20 s after its start
VERIFY_S = OTP_VERIFY_S + 20  # plus a poll and OnlyFans' answer
# A rejection this soon after the code came from OnlyFans showing the prompt again (VERIFY_MS + a relay poll
# + a status poll), not from the OTP_VERIFY_S timer.
QUICK_S = OTP_VERIFY_S - 5
ASK = "OnlyFans asks for the 2FA code"
REJECTED = "OnlyFans didn't accept that code (or hasn't answered yet) — try again"  # remote_login.OTP_REJECTED
CHECKING = "checking the 2FA code"  # remote_login.OTP_CHECKING
NOT_TYPED = "couldn't type the 2FA code"  # remote_login.OTP_NOT_TYPED (prefix)
CODES = (OTP, WRONG, AUTO_WRONG, PASTED_CODE, PASTED)
TERMINAL = ("done", "error", "cancelled")

CHECK_NO_CHALLENGE = ("API: a hidden captcha frame on OnlyFans' pages is never reported as a verification check "
                      "(no status says challenge)")
CARD_CHECKS = (
    "card: OnlyFans' 2FA prompt shows the code field (focused) with the live view still on screen",
    'card: a pasted "1234-5678" is the 8-digit code 12345678 (field, Submit on, what OnlyFans got)',
    "card: a wrong code shows the rejection and the field takes another code",
    "card: the right code links the account (job done, user_accounts row)",
)


async def _until(owner: Http, jid: str, cond, timeout: float, seen: list) -> dict:
    """Poll the job's status (as the card does) until cond(status) or timeout; every status is kept in `seen`."""
    deadline = time.monotonic() + timeout
    while True:
        st = (await owner.get(f"/admin/login/remote/{jid}")).json()
        seen.append(st)
        if cond(st) or time.monotonic() > deadline or st.get("state") in TERMINAL:
            return st
        await asyncio.sleep(0.5)


async def _start(ctx, owner: Http, email: str, nickname: str, seen: list) -> str | None:
    r = await owner.post("/admin/login/remote/start", json={
        "email": email, "password": PASSWORD, "backend": "browserbase", "proxy": "none", "nickname": nickname})
    if r.status_code != 200:
        ctx.note(f"start {email}: HTTP {r.status_code} {r.text[:300]}")
        return None
    seen.append(r.json())
    return r.json()["id"]


async def _finish(owner: Http, jid: str, seen: list) -> dict:
    """The job's final status; a job still running is cancelled (and its Browserbase session released)."""
    st = (await owner.get(f"/admin/login/remote/{jid}")).json()
    if st.get("state") not in TERMINAL:
        await owner.post(f"/admin/login/remote/{jid}/cancel")
        st = await _until(owner, jid, lambda s: s["state"] in TERMINAL, 30, seen)
    return st


def _linked(ctx, uid: str) -> tuple:
    con = ctx.world.sql()
    acc = con.execute("SELECT id, nickname FROM accounts WHERE id=?", (uid,)).fetchone()
    link = [u for (u,) in con.execute("SELECT user_id FROM user_accounts WHERE account_id=?", (uid,)).fetchall()]
    return acc, link


async def _api_login(ctx, owner: Http, world: World, seen: list) -> None:
    jid = await _start(ctx, owner, API_EMAIL, "Slop 2FA API", seen)
    ctx.check("API: start answers 200", jid is not None)
    if jid is None:
        return
    st = await _until(owner, jid, lambda s: s["state"] == "otp", 90, seen)
    ctx.check("API: the job stops on OnlyFans' 2FA prompt (state otp) with a live view, a hidden captcha frame "
              "on the page",
              st["state"] == "otp" and st["message"].startswith(ASK)
              and (st.get("live_view_url") or "").startswith(f"http://127.0.0.1:{world.api_port}/live/")
              and world.captcha_frames > 0,
              state=st["state"], message=st["message"], live_view_url=st.get("live_view_url"),
              logins=world.logins, captcha_frame_loads=world.captcha_frames)

    sent_at = time.monotonic()
    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": WRONG})
    seen.append(r.json() if r.status_code == 200 else {"status": r.status_code, "text": r.text})
    post_message = r.json().get("message") if r.status_code == 200 else None
    again = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    ctx.check("API: one code at a time — a second code while one is checked is 409, never echoed",
              again.status_code == 409 and OTP not in again.text and post_message == CHECKING,
              http_status=again.status_code, first_post_message=post_message)
    after = len(seen)
    st = await _until(owner, jid, lambda s: s["message"] == REJECTED, VERIFY_S, seen)
    took = time.monotonic() - sent_at
    ctx.check("API: a wrong 2FA code comes back as rejected and the job stays on the 2FA prompt",
              r.status_code == 200 and st["state"] == "otp" and st["message"] == REJECTED,
              post_status=r.status_code, state=st["state"], message=st["message"], of_tries=len(world.otp_tries))
    asked = [s["message"] for s in seen[after:] if s.get("state") == "otp" and s["message"].startswith(ASK)]
    ctx.check("API: the prompt back after a wrong code says rejected at once (inside OTP_VERIFY_S), never a fresh ask",
              st["message"] == REJECTED and took < QUICK_S and not asked,
              rejected_after_s=round(took, 1), budget_s=QUICK_S, fresh_asks=len(asked), of_answer_ms=VERIFY_MS)

    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    seen.append(r.json() if r.status_code == 200 else {"status": r.status_code, "text": r.text})
    st = await _until(owner, jid, lambda s: s["state"] == "done", 60, seen)
    acc, link = _linked(ctx, API_UID)
    listed = [a.get("id") for a in (await owner.get("/admin/accounts")).json().get("accounts", [])]
    session_files = sorted(p.name for p in (ctx.stack.sessions / "accounts" / API_UID).glob("session_*.json"))
    ctx.check("API: the right 2FA code signs in; the session is saved and linked to the owner",
              st["state"] == "done" and st["account_id"] == API_UID and acc is not None
              and link == [ctx.world.user_id] and API_UID in listed and bool(session_files),
              state=st["state"], error=st.get("error"), account_id=st.get("account_id"), accounts_row=acc,
              user_accounts=link, owner_id=ctx.world.user_id, listed=API_UID in listed, session_files=session_files)
    st = await _finish(owner, jid, seen)

    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    ctx.check("API: a 2FA code for a finished job is 409", r.status_code == 409, http_status=r.status_code)
    bad = {"12ab": {"code": "12ab"}, "135792": {"code": 135792}, "135793": ["135793"]}
    answers = {k: await owner.post(f"/admin/login/remote/{jid}/otp", json=v) for k, v in bad.items()}
    ctx.check("API: a malformed 2FA code or body is 400, never echoed",
              all(a.status_code == 400 and k not in a.text for k, a in answers.items()),
              http_status={k: a.status_code for k, a in answers.items()})
    ctx.metric("api_job", {"id": jid, "statuses": len(seen), "final": st})


async def _auto_login(ctx, owner: Http, seen: list) -> None:
    """OnlyFans' 2FA field submits itself on the last digit, so it is gone when the relay reads it back."""
    name = ("API: a 2FA field that submits itself on the last digit: the code counts as sent (never \"couldn't "
            "type\"), a wrong one is rejected, the right one signs in")
    jid = await _start(ctx, owner, AUTO_EMAIL, "Slop 2FA auto", seen)
    if jid is None:
        return ctx.check(name, False, start="refused")
    mine: list[dict] = []
    st = await _until(owner, jid, lambda s: s["state"] == "otp", 90, mine)
    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": AUTO_WRONG})
    wrong = await _until(owner, jid, lambda s: s["message"] in (REJECTED,) or s["message"].startswith(NOT_TYPED),
                         VERIFY_S, mine)
    r2 = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    st = await _until(owner, jid, lambda s: s["state"] == "done", 60, mine)
    st = await _finish(owner, jid, mine)
    seen.extend(mine)
    not_typed = [s["message"] for s in mine if s.get("message", "").startswith(NOT_TYPED)]
    acc, link = _linked(ctx, AUTO_UID)
    ctx.check(name, r.status_code == 200 and wrong["message"] == REJECTED and r2.status_code == 200
              and st["state"] == "done" and st["account_id"] == AUTO_UID and not not_typed
              and link == [ctx.world.user_id],
              wrong_code_post=r.status_code, after_wrong=wrong["message"], right_code_post=r2.status_code,
              state=st["state"], error=st.get("error"), not_typed_statuses=len(not_typed), user_accounts=link)


async def _late_login(ctx, owner: Http, hooks: Http, world: World, seen: list) -> None:
    """A job that runs out of its window on the 2FA prompt takes no code: 404, as an expired job."""
    name = "API: a 2FA code for a job past its window is 404 (expired) and never reaches OnlyFans"
    hook = {"api": world.api, "chunk_url_tpl": world.chunk_url_tpl}
    assert (await hooks.post("/__slop/browserbase", json={**hook, "job_window_s": LATE_WINDOW_S})).status_code == 200
    try:
        jid = await _start(ctx, owner, LATE_EMAIL, "Slop 2FA late", seen)
    finally:  # only this job gets the short window
        assert (await hooks.post("/__slop/browserbase", json=hook)).status_code == 200
    if jid is None:
        return ctx.check(name, False, start="refused")
    mine: list[dict] = []
    st = await _until(owner, jid, lambda s: s["state"] == "otp", 90, mine)
    on_prompt = st["state"] == "otp"
    deadline = st["expires_at"] - CAPTURE_RESERVE_S
    await asyncio.sleep(max(0.0, deadline - time.time()) + 1.5)
    r = await owner.post(f"/admin/login/remote/{jid}/otp", json={"code": OTP})
    gone = await owner.get("/admin/login/remote/no-such-job")
    st = await _until(owner, jid, lambda s: s["state"] in TERMINAL, 30, mine)
    seen.extend(mine)
    reached = [t for t in world.otp_sends if t["uid"] == LATE_UID]
    ctx.check(name, on_prompt and r.status_code == 404 and r.json() == gone.json() and OTP not in r.text
              and not reached,
              was_on_prompt=on_prompt, http_status=r.status_code, body=r.text[:200], expired_body=gone.text[:200],
              posted_after_deadline_s=round(time.time() - deadline, 1), of_got=len(reached), final=st.get("state"),
              error=st.get("error"))


async def _card_login(ctx, world: World, owner: Http, seen: list) -> None:
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        await page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ctx.app)
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
        first = await (await started.value).json()
        seen.append(first)
        jid = first.get("id")

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
        ctx.check(CARD_CHECKS[0], prompt and live == 1 and focused == "bb-otp",
                  field=prompt, live_view_iframes=live, focused=focused)
        if not prompt:
            return

        # A real paste: the clipboard holds "1234-5678", Ctrl/Cmd+V in the focused field.
        submit = page.get_by_role("button", name="Submit code")
        await field.click()
        await page.evaluate("(t) => navigator.clipboard.writeText(t)", PASTED)
        await page.keyboard.press("ControlOrMeta+V")
        pasted = await field.input_value()
        submit_on = await submit.is_enabled()
        await ui.shot(ctx, page, "card-otp-pasted")
        tries_before = len(world.otp_tries)
        await submit.click()
        rejected = page.get_by_role("alert").filter(has_text="OnlyFans didn't accept that code")
        try:
            await rejected.wait_for(timeout=VERIFY_S * 1000)
            shown = True
        except Exception:  # noqa: BLE001
            shown = False
        reached = world.otp_tries[tries_before:]
        ctx.check(CARD_CHECKS[1], pasted == PASTED_CODE and submit_on and reached == [PASTED_CODE],
                  field_value=pasted, submit_enabled=submit_on, of_got=reached)
        await ui.shot(ctx, page, "card-otp-rejected")
        ctx.check(CARD_CHECKS[2], shown and await field.is_editable(), rejected_shown=shown)

        try:  # locked while a code is still being checked (not for long, when the first was rejected)
            await field.fill(OTP, timeout=10_000)
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
        card_text = await page.locator("body").inner_text()
    st = await _finish(owner, jid, seen) if jid else {}
    _acc, link = _linked(ctx, UI_UID)
    ctx.check(CARD_CHECKS[3], done and st.get("state") == "done" and st.get("account_id") == UI_UID and len(link) == 1,
              shown_on_card=done, state=st.get("state"), account_id=st.get("account_id"), user_accounts=link)
    (ctx.out / "card-text.txt").write_text(card_text)


async def run(ctx) -> None:
    await ctx.build(PROFILE)
    async with async_playwright() as p:
        chromium = p.chromium.executable_path
    hooks = Http(ctx.relay, Recorder())  # the hook calls are not actor calls
    seen: list[dict] = []
    accounts = {API_EMAIL: API_UID, UI_EMAIL: UI_UID, AUTO_EMAIL: AUTO_UID, LATE_EMAIL: LATE_UID}
    with World(ctx.stack.tmp, accounts=accounts, otp=OTP, password=PASSWORD, chromium=chromium,
               autosubmit=frozenset({AUTO_EMAIL})) as world:
        r = await hooks.post("/__slop/browserbase", json={"api": world.api, "chunk_url_tpl": world.chunk_url_tpl})
        assert r.status_code == 200, r.text
        await _api_login(ctx, ctx.owner, world, seen)
        await _auto_login(ctx, ctx.owner, seen)
        await _late_login(ctx, ctx.owner, hooks, world, seen)
        await hooks.aclose()
        ctx.check(CHECK_NO_CHALLENGE, bool(seen) and world.captcha_frames > 0
                  and not [s for s in seen if s.get("state") == "challenge"],
                  statuses=len(seen), challenge_statuses=len([s for s in seen if s.get("state") == "challenge"]),
                  captcha_frame_loads=world.captcha_frames)
        if ctx.app is None:
            for c in CARD_CHECKS:
                ctx.skip(c, "--no-ui")
        else:
            await _card_login(ctx, world, ctx.owner, seen)
        got = {uid: [t["code"] for t in world.otp_sends if t["uid"] == uid]
               for uid in (API_UID, AUTO_UID, LATE_UID, UI_UID)}
        want = {API_UID: [WRONG, OTP], AUTO_UID: [AUTO_WRONG, OTP], LATE_UID: [],
                UI_UID: [PASTED_CODE, OTP] if ctx.app else []}
        ctx.check("OnlyFans' 2FA field received exactly the codes submitted, in order", got == want,
                  of_got=got, submitted=want)
        via = {uid: [t["via"] for t in world.otp_sends if t["uid"] == uid] for uid in got}
        clicked = [v for uid in (API_UID, UI_UID) for v in via[uid]]
        ctx.check("every 2FA code was sent with the 2FA form's own VERIFY button (by the field itself where it "
                  "submits itself); the page's first button never",
                  bool(clicked) and set(clicked) == {"click"} and via[AUTO_UID]
                  and set(via[AUTO_UID]) == {"auto"} and world.decoys == 0,
                  via=via, decoy_sends=world.decoys)
        await asyncio.sleep(1)  # the job thread's release call
        sessions = {sid: s["released"] for sid, s in world.sessions.items()}
        ctx.check("every Browserbase session the relay created was released", bool(sessions)
                  and all(sessions.values()), sessions=sessions)
        ctx.metric("browserbase_calls", world.calls)
        ctx.metric("of_logins", world.logins)
        ctx.metric("of_otp_sends", [{"uid": t["uid"], "via": t["via"]} for t in world.otp_sends])

    (ctx.out / "api-job-statuses.json").write_text(json.dumps(seen, indent=2))
    logs = "".join((ctx.out / f).read_text(errors="replace") for f in ("relay.log", "next.log")
                   if (ctx.out / f).exists())
    blob = json.dumps(seen) + logs
    leaks = [s for s in (*CODES, PASSWORD) if s in blob]
    ctx.check("no 2FA code (wrong or right, any login) or password in any status, error, relay.log or next.log",
              not leaks, leaked=len(leaks), statuses=len(seen), log_bytes=len(logs))
