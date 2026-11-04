"""Settings > Your Preferences "Disable free trial popup": the owner of an expired trial turns off
the "Free trial exceeded" nag (FreeTrialExpiredModal). A settings flow, not a volume one: one
owner, one browser, the real routes (`GET`/`PUT /admin/settings/preferences`,
`GET /admin/settings/applied`, `/auth/me`) on the slop temp DB.

World: `agency_inbox`; the owner's `users.created_at` set 10 days back by SQL (registered 10 days
ago, a row the product writes), so the 7-day trial is over.

Invariants: Applied reads `hide_trial_popup` false before any save; in the browser the nag shows
with the switch off (stored absent), the switch saves `hide_trial_popup: true` (PUT 200), GET
/admin/settings/preferences, the `user_settings` row and the Applied read then say true, the shell
after a reload shows no nag; stored `false` (PUT through the route) brings it back on the next
load. Screenshots: modal-switch-off (the trigger page), switch-on, preferences-saved,
shell-no-modal (settled end state), modal-back-switch-false. --no-ui: the route checks only.

Fault `applied-drops-hide-trial-popup` (the Applied read always says false) must turn exactly the
Applied check and the no-nag check red; the nag-shows checks stay green.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from slop.actors import ui
from slop.seed import ts

PROFILE = "agency_inbox"
UI = True
FAULT = "applied-drops-hide-trial-popup"
VIEWPORT = (1440, 900)

DIALOG = "Free trial exceeded"
SWITCH = "Disable free trial popup"
APPLIED_OFF = "GET /admin/settings/applied: hide_trial_popup false before any save"
SAVED = "PUT /admin/settings/preferences with hide_trial_popup true answered 200"
STORED = "hide_trial_popup true in GET /admin/settings/preferences and the user_settings row"
APPLIED_ON = "GET /admin/settings/applied: hide_trial_popup true after the save"
UI_SHOWN = "UI: expired trial, switch off: the Free trial exceeded dialog shows"
UI_HIDDEN = "UI: switch on, shell reloaded: no Free trial exceeded dialog"
UI_BACK = "UI: stored false, shell reloaded: the dialog shows again"


async def _dialog_after_load(page, url: str, want_shown: bool) -> bool:
    """Load `url`, let the shell settle (its Applied read, or the snapshot), report whether the nag shows."""
    try:
        async with page.expect_response(lambda r: "/admin/settings/applied" in r.url, timeout=60_000):
            await page.goto(url, wait_until="domcontentloaded")
    except Exception:  # noqa: BLE001 — a fresh snapshot may answer without a request
        pass
    dlg = page.get_by_role("dialog", name=DIALOG)
    if want_shown:
        try:
            await dlg.wait_for(timeout=30_000)
        except Exception:  # noqa: BLE001
            return False
        return True
    await page.wait_for_timeout(4_000)
    return await dlg.count() > 0


async def _stored(ctx) -> tuple:
    got = (await ctx.owner.get("/admin/settings/preferences")).json().get("config", {})
    row = ctx.world.sql().execute("SELECT config_json FROM user_settings WHERE user_id=? AND tab='preferences'",
                                  (ctx.world.user_id,)).fetchone()
    db = json.loads(row[0]) if row else {}
    (ctx.out / "preferences-after.json").write_text(json.dumps({"route": got, "row": db}, indent=2))
    return got.get("hide_trial_popup"), db.get("hide_trial_popup")


async def _applied(ctx):
    r = await ctx.owner.get("/admin/settings/applied")
    return r.status_code, (r.json().get("preferences") or {}).get("hide_trial_popup")


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    con = w.sql()
    with con:
        con.execute("UPDATE users SET created_at=? WHERE id=?",
                    (ts(datetime.utcnow() - timedelta(days=10)), w.user_id))
    con.close()

    st, val = await _applied(ctx)
    ctx.check(APPLIED_OFF, st == 200 and val is False, http_status=st, got=val)

    if ctx.app is None:
        for c in (UI_SHOWN, UI_HIDDEN, UI_BACK):
            ctx.skip(c, "--no-ui")
        cfg = (await ctx.owner.get("/admin/settings/preferences")).json().get("config", {})
        r = await ctx.owner.put("/admin/settings/preferences", json={**cfg, "hide_trial_popup": True})
        ctx.check(SAVED, r.status_code == 200, http_status=r.status_code, body=r.text[:200])
    else:
        async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
            shown = await _dialog_after_load(page, f"{ctx.app}/settings/preferences", True)
            await page.wait_for_timeout(500)
            await ui.shot(ctx, page, "modal-switch-off")
            ctx.check(UI_SHOWN, shown)
            if shown:
                await page.get_by_role("button", name="Continue").click()
            sw = page.get_by_role("switch", name=SWITCH)
            await sw.wait_for(timeout=60_000)
            save = page.get_by_role("button", name=re.compile(r"^Save$"))
            await page.wait_for_function(
                "() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === 'Save' && !b.disabled)",
                timeout=30_000)
            await sw.click()
            await page.get_by_role("switch", name=SWITCH, checked=True).wait_for(timeout=5_000)
            await page.wait_for_timeout(400)  # the switch's colour transition
            await ui.shot(ctx, page, "switch-on")
            async with page.expect_response(lambda r: r.request.method == "PUT"
                                            and "/admin/settings/preferences" in r.url) as put:
                await save.first.click(timeout=5_000)
            resp = await put.value
            body = await resp.json() if resp.ok else {}
            ctx.check(SAVED, resp.status == 200 and body.get("config", {}).get("hide_trial_popup") is True,
                      http_status=resp.status, config=body.get("config"))
            await page.wait_for_timeout(500)
            await ui.shot(ctx, page, "preferences-saved")

            hidden = not await _dialog_after_load(page, f"{ctx.app}/", False)
            await ui.shot(ctx, page, "shell-no-modal")
            ctx.check(UI_HIDDEN, hidden)

        await _checks_after_save(ctx)
        cfg = (await ctx.owner.get("/admin/settings/preferences")).json().get("config", {})
        r = await ctx.owner.put("/admin/settings/preferences", json={**cfg, "hide_trial_popup": False})
        # A fresh browser: the first one's saved Applied answer (IndexedDB) is fresh for 60 s, and this
        # save went through the route, not its Preferences page (whose save refreshes it).
        async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
            back = await _dialog_after_load(page, f"{ctx.app}/", True)
            await page.wait_for_timeout(500)
            await ui.shot(ctx, page, "modal-back-switch-false")
            ctx.check(UI_BACK, r.status_code == 200 and back, put_status=r.status_code)
        return
    await _checks_after_save(ctx)


async def _checks_after_save(ctx) -> None:
    route, db = await _stored(ctx)
    ctx.check(STORED, route is True and db is True, route=route, db=db)
    st, val = await _applied(ctx)
    ctx.check(APPLIED_ON, st == 200 and val is True, http_status=st, got=val)
