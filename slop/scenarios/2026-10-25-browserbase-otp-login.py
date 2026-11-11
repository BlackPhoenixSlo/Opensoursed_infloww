"""Add creator > Browserbase login with OnlyFans 2FA. The owner starts a served
login (POST /admin/login/remote/start); the relay drives a remote Chromium
through OnlyFans' login form until OnlyFans asks for the 2FA code (job state
"otp"); the code typed on the card (POST /admin/login/remote/{id}/otp) is
typed into OnlyFans' own 2FA field by the job's thread. A wrong code comes back
as rejected ("OnlyFans didn't accept that code …") with the job still on the prompt, and the next
code signs in: capture, persist, link to the owner. A flow, not a volume one:
one owner, five logins (three over the API, two through the card in the app:
desktop, then a phone).

The outside world is lib/browserbase.py, on loopback: Browserbase's API (a
fresh local Chromium per session, driven by the relay over CDP), its live view
(a stand-in showing that Chromium's tab) and OnlyFans' site (login form, 2FA
prompt, chats page with a signed request and OF's signing module, which the
login extension's interceptor captures). Every OnlyFans page carries a hidden
reCAPTCHA frame; the 2FA page a decoy form whose button is the page's first
submit button; a sent code takes OnlyFans VERIFY_MS ("Verifying…", no field)
to answer. `POST /__slop/browserbase` points the relay at it. Once linked,
the relay's REAL OFClient reads the account's /users/me from lib/of_wire.py on
loopback (`OF_WIRE`: the relay's OF_API_ORIGIN), whose profile for the card's
Creator (`profiles`) is a realistic one: display name, @username and a photo.
Bypass, declared: the photo is an SVG data URL (as 2026-11-04-creator-avatars'),
so the browser shows it without the relay's /img fetching off-host. Everything
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
  phone  (UI, 390x844 touch) the same Add creator walk on a phone: details,
         platform (Fansly picked first: its desktop-only line, no Done, then
         back to OnlyFans), Browser login, the right code, linked. One more fake
         login (one more local Chromium, as the card's), no wrong code.

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
The card login enters through the Add creator modal as the owner does: details and platform, then two
choices, Browser login (first, checked) and Extension; the Extension panel is
looked at, then Browser login starts with no proxy in its body (the relay's
automatic pick), and Done on the linked screen saves and closes. The OF
profile's display name (OF_NAME) differs from the typed Creator name (UI_NAME):
the linked screen shows the account's OF photo and @username on the chip and
keeps the typed name in the Nickname field; after Done the Creators row shows
the typed name (not the OF name, not "Account <id>"), the photo and the OF user
id in Creator ID, and the stored nickname is the typed name (accounts row,
GET /admin/accounts). If the wizard steps fail, that is recorded on the failing
check and every later card check is skipped (never a crash that hides them); a card
that never links skips the name / row / nickname / persisted checks (its link check
is the red one).
The phone pass: every step up to the 2FA prompt (details, platform, Browser login, 2FA
prompt) fits 390px (the page no wider than the viewport, no element of the dialog past
either edge) with its primary button (Next, Next, Start browser login, Submit code) inside
the viewport as the app leaves it and what a tap on its centre hits (elementFromPoint:
not clipped by the modal's scrolling body); the linked step's fit (Done in view) is part of the
link check, so the fault's red stays on its targets; Fansly on a phone shows its desktop-only line on
the platform and sign-in steps and the sign-in step has no visible Done; the right code
links the account (linked screen, job done, user_accounts row). Not pressed: the
phone's Done (the desktop card covers the save).
Screenshots: trigger-add-creator, add-creator-two-choices, add-creator-extension,
add-creator-browser, card-otp-prompt, card-otp-pasted, card-otp-rejected,
card-otp-linked, add-creator-done; phone-trigger-add-creator, phone-details,
phone-platform, phone-fansly-desktop-only, phone-browser-login, phone-otp-prompt,
phone-linked.
Break-it-once: FAULT otp-code-never-consumed (the job never reads the code);
--fault=challenge-counts-hidden-frames (the pre-fix challenge check: any
captcha frame counts, on screen or not).
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.parse

from playwright.async_api import async_playwright

from slop.actors import ui
from slop.lib.browserbase import VERIFY_MS, World
from slop.lib.client import Http, Recorder

PROFILE = "agency_inbox"
UI = True
FAULT = "otp-code-never-consumed"
OF_WIRE = True
VIEWPORT = (1440, 1000)
PASSWORD = "slop-of-Password-77"
OTP, WRONG = "246810", "135791"
AUTO_WRONG = "975310"
PASTED, PASTED_CODE = "1234-5678", "12345678"  # the card's wrong code, pasted with its dash
API_EMAIL, API_UID = "otp-api@slop.test", "990000101"
UI_EMAIL, UI_UID = "otp-card@slop.test", "990000102"
UI_NAME = "Mia Rose"  # the Creator name typed in the wizard
OF_NAME, UI_HANDLE = "Mia Rose OF", "miarose"  # the card Creator's OF profile (lib/of_wire.py `profiles`)
AUTO_EMAIL, AUTO_UID = "otp-auto@slop.test", "990000103"  # its 2FA field submits itself
LATE_EMAIL, LATE_UID = "otp-late@slop.test", "990000104"  # its job runs out of time on the prompt
PHONE_EMAIL, PHONE_UID = "otp-phone@slop.test", "990000105"  # the phone pass's Creator
PHONE_NAME, PHONE_HANDLE = "Ava Lane", "avalane"
PHONE = (390, 844)
MOBILE_FANSLY_LINE = "The Fansly paste session is desktop-only."  # AddCreatorModal's MOBILE_FANSLY_LINE
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
    "card: after creator details and platform, Browser login (checked, Recommended) first and Extension second; "
    "no proxy step",
    "card: the Extension choice swaps in its panel (Copied cURL, Link account) for Browser login's",
    "card: Start browser login posts /admin/login/remote/start with no proxy (the relay's automatic pick)",
    "card: OnlyFans' 2FA prompt shows the code field (focused) with the live view still on screen",
    'card: a pasted "1234-5678" is the 8-digit code 12345678 (field, Submit on, what OnlyFans got)',
    "card: a wrong code shows the rejection and the field takes another code",
    "card: the right code links the account (job done, user_accounts row)",
    "card: Done on the linked screen (account + account details) saves and closes the modal",
)
PREFILL_CHECKS = (
    "card: the linked screen keeps the entered name, with the OF profile chip photo and @username",
    "card: after Done the Creators row shows the entered name (not the OF name, not \"Account <id>\"), the photo, "
    "and Creator ID = the OF user id",
    "card: the stored nickname is the entered name, not the OF display name (accounts row and GET /admin/accounts)",
)
WIZARD_CHECKS = (
    "wizard: blank creator details cannot advance",
    "wizard: gender is required",
    "wizard: platform defaults to OnlyFans",
    "wizard: back preserves creator details",
)
CHECK_PERSISTED = "wizard: creator details persisted in account settings"
PHONE_CHECKS = (
    "phone: every Add creator step up to the 2FA prompt fits 390px wide (no horizontal overflow) and its "
    "primary button is in view",
    "phone: Fansly on a phone shows the desktop-only line, no Done",
    "phone: Browser login with the right 2FA code links the account (linked screen fits 390px with Done in "
    "view, job done, user_accounts row)",
)


def _photo(uid: str) -> dict:
    """OF's avatar fields, as an SVG data URL (declared bypass: no off-host /img fetch)."""
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='144' height='144'><rect width='144' height='144' "
           "fill='#c2410c'/><circle cx='72' cy='58' r='26' fill='#fed7aa'/><rect x='30' y='94' width='84' "
           "height='50' rx='25' fill='#fed7aa'/></svg>")
    url = "data:image/svg+xml," + urllib.parse.quote(svg) + f"#{uid}"
    return {"avatar": url, "avatarThumbs": {"c50": url, "c144": url}}


# The Creators table row of `uid`: the Creator cell (its div titled "<extras>\n<id>\n…"), and the Creator ID cell.
_ROW = """(uid) => {
  const heads = [...document.querySelectorAll('thead th')].map((th) => th.innerText.trim());
  const row = [...document.querySelectorAll('tbody tr')]
    .find((tr) => [...tr.querySelectorAll('div[title]')].some((d) => d.title.split('\\n')[1] === uid));
  if (!row) return null;
  const cell = [...row.querySelectorAll('div[title]')].find((d) => d.title.split('\\n')[1] === uid);
  const td = row.children[heads.indexOf('Creator ID')];
  return {name: cell.innerText.trim(), img: (cell.querySelector('img') || {}).src || null,
          creator_id: td ? td.innerText.trim() : null};
}"""


# The page's width against the viewport, and every element of the dialog that reaches past either edge.
_FITS = """(dlg) => {
  const W = innerWidth, past = [];
  for (const e of [dlg, ...dlg.querySelectorAll('*')]) {
    const r = e.getBoundingClientRect();
    if (r.width && r.height && (r.left < -1 || r.right > W + 1))
      past.push(`${e.tagName.toLowerCase()} ${Math.round(r.left)}..${Math.round(r.right)} ${(e.innerText || '').slice(0, 30)}`);
  }
  return {page_px: document.documentElement.scrollWidth, viewport_px: W, viewport_h: innerHeight, past: past.slice(0, 8)};
}"""


# Is the button what a tap on its centre hits (not clipped by the modal's scrolling body, not under its header/footer)?
_HIT = """(e) => {
  const r = e.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return hit ? {ok: hit === e || e.contains(hit), tag: hit.tagName.toLowerCase(), text: (hit.innerText || '').slice(0, 30)}
             : {ok: false, tag: null, text: null};
}"""


async def _fits(page, dlg, primary) -> dict:
    """One step on the phone: no horizontal overflow; the primary button inside the viewport and what a tap on its
    centre hits."""
    got = await dlg.evaluate(_FITS)
    box = await primary.bounding_box()
    got["primary"] = box and {k: round(v) for k, v in box.items()}
    got["hit"] = await primary.evaluate(_HIT) if box else None
    got["ok"] = (got["page_px"] <= got["viewport_px"] and not got["past"] and bool(box)
                 and box["x"] >= 0 and box["y"] >= 0 and box["x"] + box["width"] <= got["viewport_px"]
                 and box["y"] + box["height"] <= got["viewport_h"] and got["hit"]["ok"])
    return got


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


async def _card_login(ctx, world: World, owner: Http, seen: list) -> list[str]:
    """The card's login through the Add creator modal; returns the 2FA codes the card actually submitted."""
    sent: list[str] = []
    # The linked account's /users/me goes through to the relay (its REAL OFClient, lib/of_wire.py behind it).
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=("/api/of/v2/users/me",)) as page:
        await page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ctx.app)
        await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
        add = page.get_by_role("button", name="Add creator").first
        await add.wait_for(timeout=120_000)
        await ui.shot(ctx, page, "trigger-add-creator")
        await add.click()
        dlg = page.get_by_role("dialog", name="Add creator")
        next_step = dlg.get_by_role("button", name="Next", exact=True)
        group = dlg.get_by_role("radiogroup", name="Login method")
        # The wizard's steps never throw past here: a failed step fails the first check not yet recorded and
        # skips every later card check. Each value is awaited before its check takes its name, so a throw leaves
        # the name for the failure.
        wizard = iter((*WIZARD_CHECKS, CARD_CHECKS[0]))
        try:
            await dlg.get_by_label("Creator name", exact=True).wait_for(timeout=30_000)
            blank_blocked = await next_step.is_disabled()
            ctx.check(next(wizard), blank_blocked)
            await dlg.get_by_label("Creator name", exact=True).fill(UI_NAME)
            gender_blocked = await next_step.is_disabled()
            ctx.check(next(wizard), gender_blocked)
            await dlg.get_by_label("Gender", exact=True).select_option("Female")
            await ui.shot(ctx, page, "creator-details-settled")
            await next_step.click()
            platforms = dlg.get_by_role("radiogroup", name="Platform", exact=True)
            await platforms.wait_for()
            on_onlyfans = await platforms.get_by_role("radio", name="OnlyFans").is_checked()
            ctx.check(next(wizard), on_onlyfans)
            await dlg.get_by_role("button", name="Back", exact=True).click()
            kept = (await dlg.get_by_label("Creator name", exact=True).input_value() == UI_NAME
                    and await dlg.get_by_label("Gender", exact=True).input_value() == "Female")
            ctx.check(next(wizard), kept)
            await next_step.click()
            await next_step.click()
            await group.wait_for(timeout=30_000)
        except Exception as e:  # noqa: BLE001
            failed = next(wizard)
            ctx.check(failed, False, error=f"{type(e).__name__}: {str(e)[:300]}")
            for c in dict.fromkeys((*wizard, *CARD_CHECKS, *PREFILL_CHECKS, CHECK_PERSISTED)):
                if c != failed:
                    ctx.skip(c, f"the wizard stopped at: {failed}")
            return sent
        await page.wait_for_timeout(500)  # the modal's pop-in
        radios = group.get_by_role("radio")
        names = [(await r.evaluate("e => e.closest('label').innerText")).split("\n")[0].strip()
                 for r in await radios.all()]
        browser_on = await radios.nth(0).is_checked()
        bb = dlg.get_by_role("region", name="Browserbase login")
        start = dlg.get_by_role("button", name="Start browser login")
        extras = {lb: await dlg.get_by_text(lb).count() for lb in ("Creator name", "Proxy selection", "Still unable")}
        await ui.shot(ctx, page, "add-creator-two-choices")
        ctx.check(CARD_CHECKS[0], names == ["Browser login", "Extension"] and browser_on
                  and await dlg.get_by_text("Recommended").is_visible() and await bb.is_visible()
                  and await start.is_visible() and await dlg.get_by_role("combobox").count() == 0
                  and not any(extras.values()),
                  choices=names, browser_checked=browser_on, old_steps=extras)

        await group.locator("label").filter(has=page.locator("input[value=extension]")).click()
        ext = dlg.get_by_role("region", name="Extension")
        ext_ok = False
        try:
            await ext.wait_for(timeout=10_000)
            ext_ok = (await ext.get_by_label("Copied cURL").is_visible() and not await bb.is_visible()
                      and await dlg.get_by_role("button", name="Link account").is_visible()
                      and await start.count() == 0)
        except Exception:  # noqa: BLE001
            pass
        await ui.shot(ctx, page, "add-creator-extension")
        ctx.check(CARD_CHECKS[1], ext_ok)

        await group.locator("label").filter(has=page.locator("input[value=browser]")).click()
        await bb.wait_for(timeout=10_000)
        await bb.get_by_label("OnlyFans email").fill(UI_EMAIL, timeout=60_000)
        await bb.get_by_label("OnlyFans password").fill(PASSWORD)
        await ui.shot(ctx, page, "add-creator-browser")
        async with page.expect_response(lambda r: r.url.endswith("/admin/login/remote/start")) as started:
            await start.click()
        resp = await started.value
        body = resp.request.post_data_json or {}
        first = await resp.json()
        seen.append(first)
        jid = first.get("id")
        ctx.check(CARD_CHECKS[2], resp.status == 200 and bool(jid) and "proxy" not in body
                  and body.get("backend") == "browserbase" and body.get("email") == UI_EMAIL,
                  http_status=resp.status, body_keys=sorted(body), job_proxy=first.get("proxy"))

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
        ctx.check(CARD_CHECKS[3], prompt and live == 1 and focused == "bb-otp",
                  field=prompt, live_view_iframes=live, focused=focused)
        if not prompt:
            for c in (*CARD_CHECKS[4:], *PREFILL_CHECKS, CHECK_PERSISTED):
                ctx.skip(c, "the card never showed the 2FA field")
            return sent

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
        sent.append(pasted)  # what the field held is what the card sends
        rejected = page.get_by_role("alert").filter(has_text="OnlyFans didn't accept that code")
        try:
            await rejected.wait_for(timeout=VERIFY_S * 1000)
            shown = True
        except Exception:  # noqa: BLE001
            shown = False
        reached = world.otp_tries[tries_before:]
        ctx.check(CARD_CHECKS[4], pasted == PASTED_CODE and submit_on and reached == [PASTED_CODE],
                  field_value=pasted, submit_enabled=submit_on, of_got=reached)
        await ui.shot(ctx, page, "card-otp-rejected")
        ctx.check(CARD_CHECKS[5], shown and await field.is_editable(), rejected_shown=shown)

        try:  # locked while a code is still being checked (not for long, when the first was rejected)
            await field.fill(OTP, timeout=10_000)
            await submit.click(timeout=10_000)
            sent.append(OTP)
        except Exception:  # noqa: BLE001
            pass
        linked = page.get_by_text(UI_UID).first
        try:
            await linked.wait_for(timeout=60_000)
            done = True
        except Exception:  # noqa: BLE001
            done = False
        if not done:  # the link check (CARD_CHECKS[6]) says why; nothing after it can be judged
            for c in (*PREFILL_CHECKS, CHECK_PERSISTED):
                ctx.skip(c, "the card never linked the account")
        nick, chip_img, handle = "", 0, 0
        if done:
            nick_field = dlg.get_by_label("Nickname")
            try:  # the OF profile's chip (photo + @username) lands after the link
                await dlg.get_by_text(f"@{UI_HANDLE}").first.wait_for(timeout=30_000)
                await dlg.locator("img").first.wait_for(timeout=10_000)
            except Exception:  # noqa: BLE001
                pass
            nick = await nick_field.input_value() if await nick_field.count() else ""
            chip_img = await dlg.locator("img").count()
            handle = await dlg.get_by_text(f"@{UI_HANDLE}").count()
        await page.wait_for_timeout(1000)
        await ui.shot(ctx, page, "card-otp-linked")
        if done:
            ctx.check(PREFILL_CHECKS[0], nick == UI_NAME and chip_img >= 1 and handle >= 1,
                      nickname_field=nick, entered=UI_NAME, of_name=OF_NAME, chip_imgs=chip_img, handle_shown=handle)
        card_text = await page.locator("body").inner_text()
        closed, row = False, None
        if done:
            try:
                await dlg.get_by_text("Account details").wait_for(timeout=10_000)
                save = dlg.get_by_role("button", name="Done")
                await save.click(timeout=30_000)
                await dlg.wait_for(state="detached", timeout=30_000)
                closed = True
            except Exception:  # noqa: BLE001
                pass
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                row = await page.evaluate(_ROW, UI_UID)
                if row and row["name"] == UI_NAME and row["img"]:
                    break
                await page.wait_for_timeout(500)
            await page.wait_for_timeout(1000)
            await ui.shot(ctx, page, "add-creator-done")
            ctx.check(PREFILL_CHECKS[1], bool(row) and row["name"] == UI_NAME
                      and (row["img"] or "").endswith(f"#{UI_UID}") and row["creator_id"] == UI_UID,
                      row=row and {**row, "img": bool(row["img"])}, of_name=OF_NAME)
    st = await _finish(owner, jid, seen) if jid else {}
    _acc, link = _linked(ctx, UI_UID)
    ctx.check(CARD_CHECKS[6], done and st.get("state") == "done" and st.get("account_id") == UI_UID and len(link) == 1,
              shown_on_card=done, state=st.get("state"), account_id=st.get("account_id"), user_accounts=link)
    listed = [a.get("id") for a in (await owner.get("/admin/accounts")).json().get("accounts", [])]
    ctx.check(CARD_CHECKS[7], closed and UI_UID in listed, modal_closed=closed, listed=UI_UID in listed)
    (ctx.out / "card-text.txt").write_text(card_text)
    if not done:
        return sent
    acc, _ = _linked(ctx, UI_UID)
    api_nick = next((a.get("nickname") for a in (await owner.get("/admin/accounts")).json().get("accounts", [])
                     if a.get("id") == UI_UID), None)
    ctx.check(PREFILL_CHECKS[2], bool(acc) and acc[1] == UI_NAME and api_nick == UI_NAME,
              accounts_row=acc, api_nickname=api_nick, of_name=OF_NAME)
    settings = (await owner.get("/admin/settings/account")).json()
    creator = settings.get("config", {}).get("creators", {}).get("profiles", {}).get(UI_UID, {})
    ctx.check(CHECK_PERSISTED,
              creator.get("name") == UI_NAME and creator.get("gender") == "Female", creator=creator)
    return sent


async def _phone_login(ctx, owner: Http, seen: list) -> list[str]:
    """The Add creator walk in a phone's context (390x844, touch); returns the 2FA codes it submitted."""
    sent: list[str] = []
    steps: dict[str, dict] = {}
    fansly: dict = {}
    jid, linked, error, linked_fit = None, False, None, None
    async with ui.owner_browser(ctx, viewport=PHONE, touch=True, through=("/api/of/v2/users/me",)) as page:
        try:
            await page.goto(f"{ctx.app}/creators", wait_until="domcontentloaded")
            add = page.get_by_role("button", name="Add creator").first
            await add.wait_for(timeout=120_000)
            await ui.shot(ctx, page, "phone-trigger-add-creator")
            await add.click()
            dlg = page.get_by_role("dialog", name="Add creator")
            next_step = dlg.get_by_role("button", name="Next", exact=True)
            await dlg.get_by_label("Creator name", exact=True).fill(PHONE_NAME, timeout=30_000)
            await dlg.get_by_label("Gender", exact=True).select_option("Female")
            await page.wait_for_timeout(500)  # the modal's pop-in
            steps["details"] = await _fits(page, dlg, next_step)
            await ui.shot(ctx, page, "phone-details")
            await next_step.click()
            platforms = dlg.get_by_role("radiogroup", name="Platform", exact=True)
            await platforms.wait_for()
            steps["platform"] = await _fits(page, dlg, next_step)
            await ui.shot(ctx, page, "phone-platform")

            await platforms.locator("label").filter(has=page.locator("input[value=fansly]")).click()
            line = dlg.get_by_text(MOBILE_FANSLY_LINE)
            fansly["platform_line"] = await line.first.is_visible()
            await next_step.click()
            await dlg.get_by_role("button", name="Link an OnlyFans account instead").wait_for(timeout=10_000)
            fansly["login_line"] = await line.first.is_visible()
            fansly["visible_done"] = await dlg.get_by_role("button", name="Done", exact=True).evaluate_all(
                "els => els.filter((e) => e.getClientRects().length).length")
            await ui.shot(ctx, page, "phone-fansly-desktop-only")
            await dlg.get_by_role("button", name="Link an OnlyFans account instead").click()

            bb = dlg.get_by_role("region", name="Browserbase login")
            start = dlg.get_by_role("button", name="Start browser login")
            await bb.wait_for(timeout=10_000)
            await bb.get_by_label("OnlyFans email").fill(PHONE_EMAIL, timeout=60_000)
            await bb.get_by_label("OnlyFans password").fill(PASSWORD)
            steps["browser login"] = await _fits(page, dlg, start)
            await ui.shot(ctx, page, "phone-browser-login")
            async with page.expect_response(lambda r: r.url.endswith("/admin/login/remote/start")) as started:
                await start.click()
            first = await (await started.value).json()
            seen.append(first)
            jid = first.get("id")

            field = page.get_by_label("2FA code")
            await field.wait_for(timeout=90_000)
            await page.wait_for_timeout(2500)  # the live view stand-in's next frame
            submit = page.get_by_role("button", name="Submit code")
            steps["2FA prompt"] = await _fits(page, dlg, submit)
            await ui.shot(ctx, page, "phone-otp-prompt")
            await field.fill(OTP)
            await submit.click()
            sent.append(OTP)

            await dlg.get_by_text(PHONE_UID).first.wait_for(timeout=60_000)
            linked = True
            await page.wait_for_timeout(1000)
            linked_fit = await _fits(page, dlg, dlg.get_by_role("button", name="Done", exact=True))
            await ui.shot(ctx, page, "phone-linked")
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {str(e)[:300]}"
            await ui.shot(ctx, page, "phone-stopped")
    # Up to the prompt: nothing here needs a code consumed (the link, and the linked step's fit, are PHONE_CHECKS[2]'s).
    want = ["details", "platform", "browser login", "2FA prompt"]
    ctx.check(PHONE_CHECKS[0], list(steps) == want and all(v["ok"] for v in steps.values()),
              steps=steps, unmeasured=[s for s in want if s not in steps], error=error)
    ctx.check(PHONE_CHECKS[1], fansly.get("platform_line") is True and fansly.get("login_line") is True
              and fansly.get("visible_done") == 0, **fansly, error=None if len(fansly) == 3 else error)
    st = await _finish(owner, jid, seen) if jid else {}
    _acc, link = _linked(ctx, PHONE_UID)
    ctx.check(PHONE_CHECKS[2], linked and bool(linked_fit) and linked_fit["ok"] and st.get("state") == "done"
              and st.get("account_id") == PHONE_UID and link == [ctx.world.user_id],
              shown_on_phone=linked, linked_fit=linked_fit, state=st.get("state"), account_id=st.get("account_id"),
              user_accounts=link,
              error=None if linked else error)
    return sent


async def run(ctx) -> None:
    await ctx.build(PROFILE)
    async with async_playwright() as p:
        chromium = p.chromium.executable_path
    hooks = Http(ctx.relay, Recorder())  # the hook calls are not actor calls
    seen: list[dict] = []
    accounts = {API_EMAIL: API_UID, UI_EMAIL: UI_UID, AUTO_EMAIL: AUTO_UID, LATE_EMAIL: LATE_UID,
                PHONE_EMAIL: PHONE_UID}
    ctx.of_wire.profiles[UI_UID] = {"name": OF_NAME, "username": UI_HANDLE, **_photo(UI_UID)}
    ctx.of_wire.profiles[PHONE_UID] = {"name": f"{PHONE_NAME} OF", "username": PHONE_HANDLE, **_photo(PHONE_UID)}
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
        card_sent: list[str] = []  # the codes the card submitted (none when its flow stopped before the prompt)
        phone_sent: list[str] = []  # likewise, the phone pass's
        if ctx.app is None:
            for c in (*WIZARD_CHECKS, *CARD_CHECKS, *PREFILL_CHECKS, CHECK_PERSISTED, *PHONE_CHECKS):
                ctx.skip(c, "--no-ui")
        else:
            card_sent = await _card_login(ctx, world, ctx.owner, seen)
            phone_sent = await _phone_login(ctx, ctx.owner, seen)
        got = {uid: [t["code"] for t in world.otp_sends if t["uid"] == uid]
               for uid in (API_UID, AUTO_UID, LATE_UID, UI_UID, PHONE_UID)}
        want = {API_UID: [WRONG, OTP], AUTO_UID: [AUTO_WRONG, OTP], LATE_UID: [],
                UI_UID: card_sent, PHONE_UID: phone_sent}
        ctx.check("OnlyFans' 2FA field received exactly the codes submitted, in order", got == want,
                  of_got=got, submitted=want)
        via = {uid: [t["via"] for t in world.otp_sends if t["uid"] == uid] for uid in got}
        clicked = [v for uid in (API_UID, UI_UID, PHONE_UID) for v in via[uid]]
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
