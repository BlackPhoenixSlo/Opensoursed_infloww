"""My Automations > Auto Post: one rule = one post, the rule's "Run every" its only clock, all in ONE popup (the post's
fields inline, no Compose dialog / "Use in rule"), and the list shows each rule's post (app/components/compose/
PremadeFields.tsx, premadeRows.ts, automations/ruleEditorForm.ts, readyMadeContent.ts, ReadyMadeRuleEditor.tsx,
RuleTable.tsx). The Auto Mass twin is 2026-11-08-auto-mass-one-message (same shared files, another page and key).

World: `agency_inbox`. Creator 0 gets an older Auto Post rule through the real POST /admin/automation-rules (two
posts, a delay on the second, a repost cycle; disabled, so nothing fires).
Flow, on a 390x844 phone: the owner opens /growth/auto-post, New auto post: the popup holds the caption box at once
(screenshot `popup-top`), types a caption, sets Price 12 (`popup-media-price`: the free preview pool appears) and
Auto-delete after 6 (`popup-bottom`: no More settings, no repost cycle; with no image Create waits, `ppv-wait`),
clears the price (no vault media in this world to attach), Create (`saved`: the new row reads its post);
then Edit on the older rule (`legacy-notice`), Edit in Raw JSON (`legacy-raw`), Cancel.

Checks (names in lib/auto_post_faults.py):
  AP_FORM    one popup: the post's fields inline (no Compose button, no second dialog, no Use in rule); one post and no
             list / delay / repost field, no More settings; caption, media pool, price, auto-delete shown; preview
             pool only once paid; the popup and page fit the phone.
  AP_STORED  the POST body's payload, the GET route's and the automation_rules row's: exactly the one post, no
             resend_* / delay_minutes key; the rule's list row reads its post.
  AP_LEGACY  the older rule's notice, no post fields, Raw JSON holds its payload, the row unchanged after Cancel.

FAULT `auto-post-legacy-composer` (client: `formHoldReason` always null): AP_LEGACY goes red, alone.
UI only (`--no-ui` skips): not a volume path, proven once on the real page.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.auto_post_faults import AP_FORM, AP_LEGACY, AP_STORED

PROFILE = "agency_inbox"
UI = True
FAULT = "auto-post-legacy-composer"
PHONE = (390, 844)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
TEXT = "slop auto post one"
LEGACY_NAME = "slop legacy post drip"
LEGACY = {"posts": [{"text": "slop legacy one", "hours_to_live": 6},
                    {"text": "slop legacy two", "delay_minutes": 30}],
          "resend_count": 1, "resend_after_hours": 24}
WANT = [{"text": TEXT, "hours_to_live": 6}]
SUMMARY = f"Free · {TEXT} · deletes after 6h"
# A priced post with no image never posts (auto_posts `paid_no_media`): Create waits with this line.
PPV_HELP = "A paid post needs an image: add one or a vault folder, or make it free, to enable Create."
TIMER_KEYS = ("resend_count", "resend_after_hours", "delay_minutes")
GONE = ("Delay before posting", "Delay after previous", "Repost whole list after", "Repost this many times")
NOTICE = "Older multi-post rule — edit in Raw JSON."
RULES = "/admin/automation-rules"
# The page and each open dialog within the phone's width.
_FITS = """() => ({page: document.documentElement.scrollWidth, vw: innerWidth,
  dialogs: [...document.querySelectorAll('[role=dialog]')].map((d) => {
    const r = d.getBoundingClientRect(); return {left: r.left, right: r.right, sw: d.scrollWidth, cw: d.clientWidth}; })})"""
# Finite animations (a modal's pop in / out) done; a skeleton's endless pulse does not count.
_SETTLED = """() => document.getAnimations().filter((a) => a.playState === 'running'
  && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length === 0"""



async def _row_edit(page, row) -> None:
    """A phone rule row's Edit: its "⋯" menu (the wide row's links are desktop only)."""
    await row.get_by_role("button", name=re.compile(r"^More actions for ")).click(timeout=30_000)
    await row.get_by_role("menuitem", name="Edit", exact=True).click(timeout=10_000)

async def _shot(ctx, page, name: str) -> str:
    await page.wait_for_function(_SETTLED, timeout=15_000)
    return await ui.shot(ctx, page, name)


def _fits(f: dict) -> bool:
    return f["page"] <= f["vw"] and all(d["left"] >= -0.5 and d["right"] <= f["vw"] + 0.5 and d["sw"] <= d["cw"] + 1
                                        for d in f["dialogs"])


def _timer_keys(payload) -> list[str]:
    """Every resend_* / delay_minutes key on the payload or any of its posts."""
    if not isinstance(payload, dict):
        return []
    items = [payload, *[p for p in payload.get("posts") or [] if isinstance(p, dict)]]
    return sorted({k for it in items for k in TIMER_KEYS if k in it})


def _row(w, rule_id) -> dict | None:
    con = w.sql()
    row = con.execute("SELECT kind, steps_json FROM automation_rules WHERE id=?", (rule_id,)).fetchone()
    con.close()
    return {"kind": row[0], "payload": json.loads(row[1] or "{}")} if row else None


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    if not ctx.app:
        for n in (AP_FORM, AP_STORED, AP_LEGACY):
            ctx.skip(n, "--no-ui")
        return
    aid = w.data["creators"][0]["id"]
    r = await ctx.owner.post(RULES, json={"account_id": aid, "kind": "auto_posts", "name": LEGACY_NAME,
                                          "every_seconds": 86400, "payload": LEGACY, "is_enabled": False})
    r.raise_for_status()
    legacy_id = r.json()["id"]

    async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
        page.context.set_default_navigation_timeout(WAIT_MS)
        await page.goto(f"{ctx.app}/growth/auto-post?creator={aid}", wait_until="domcontentloaded")
        await page.get_by_text(LEGACY_NAME, exact=True).first.wait_for(timeout=WAIT_MS)
        await page.get_by_role("button", name="New auto post").first.click(timeout=WAIT_MS)
        editor = page.get_by_role("dialog", name="New auto post")
        box = editor.get_by_placeholder("Post caption…")
        await box.wait_for(timeout=WAIT_MS)  # the fields are in the popup itself
        shots = [await _shot(ctx, page, "popup-top")]
        one_popup = {
            "compose_button": await editor.get_by_role("button", name="Compose", exact=True).count(),
            "use_in_rule": await page.get_by_role("button", name="Use in rule").count(),
            "dialogs": await page.get_by_role("dialog").count(),
        }
        free_preview = await editor.get_by_role("button", name="Pick preview pool").count()
        folder_pools = await editor.get_by_text("Folder pool", exact=True).count()  # free: the media pool's alone

        await box.fill(TEXT)
        price = editor.get_by_placeholder("0 (free)")
        await price.fill("12")
        pick_preview = editor.get_by_role("button", name="Pick preview pool")
        await pick_preview.wait_for(timeout=10_000)
        await price.scroll_into_view_if_needed(timeout=10_000)
        shots.append(await _shot(ctx, page, "popup-media-price"))
        ttl = editor.get_by_label("Auto-delete after", exact=True)
        await ttl.fill("6")
        await pick_preview.scroll_into_view_if_needed(timeout=10_000)
        shots.append(await _shot(ctx, page, "popup-bottom"))
        create = editor.get_by_role("button", name="Create", exact=True)
        ppv_help = editor.get_by_text(PPV_HELP, exact=True)
        ppv_wait = {"create_disabled": await create.is_disabled(), "help": await ppv_help.count()}
        if ppv_wait["help"]:
            await ppv_help.scroll_into_view_if_needed(timeout=10_000)
        shots.append(await _shot(ctx, page, "ppv-wait"))
        form = {
            "one_popup": one_popup,
            "post_heading": await editor.get_by_role("heading", name="Post 1").count(),
            "repost_heading": await editor.get_by_role("heading", name="Repost cycle").count(),
            "add_another": await editor.get_by_role("button", name="Add another post").count(),
            "gone_fields": {g: await editor.get_by_label(g, exact=True).count() for g in GONE},
            "more_settings": await editor.get_by_role("button", name="More settings").count(),
            "shown": {
                "caption": await box.count(), "folder_pool": folder_pools,
                "image_pool": await editor.get_by_role("button", name="Pick image pool").count(),
                "price": await price.count(), "auto_delete": await ttl.count(),
            },
            "preview_pool_free": free_preview,
            "preview_pool_paid": await pick_preview.count(),
            "ppv_wait": ppv_wait,
            "fits": await page.evaluate(_FITS),
        }
        ctx.check(AP_FORM, one_popup == {"compose_button": 0, "use_in_rule": 0, "dialogs": 1}
                  and form["post_heading"] == 0 and form["repost_heading"] == 0 and form["add_another"] == 0
                  and not any(form["gone_fields"].values()) and form["more_settings"] == 0
                  and all(v == 1 for v in form["shown"].values()) and form["preview_pool_free"] == 0
                  and form["preview_pool_paid"] == 1 and ppv_wait == {"create_disabled": True, "help": 1}
                  and _fits(form["fits"]), **form, screenshots=shots)
        await price.fill("")  # free: no vault media in this world to attach

        async with page.expect_response(lambda x: x.request.method == "POST" and urlsplit(x.url).path == RULES,
                                        timeout=30_000) as created:
            await create.click(timeout=10_000)
        resp = await created.value
        status, body, rule = resp.status, resp.request.post_data_json or {}, await resp.json()
        await editor.wait_for(state="hidden", timeout=30_000)
        new_row = page.locator("tr").filter(has=page.get_by_text(rule.get("name") or "Auto post", exact=True))
        summary = new_row.get_by_text(SUMMARY, exact=True)
        summary_shown = True
        try:
            await summary.wait_for(timeout=30_000)
        except Exception:  # noqa: BLE001 — the check below says what was missing
            summary_shown = False
        saved = await _shot(ctx, page, "saved")

        listed = (await ctx.owner.get(f"{RULES}?account_id={aid}")).json().get("rules") or []
        route = next((x.get("payload") for x in listed if x.get("id") == rule.get("id")), None)
        db = _row(w, rule.get("id"))
        sent = body.get("payload") or {}
        (ctx.out / "auto-post-created.json").write_text(json.dumps(
            {"status": status, "body": body, "route": route, "db": db}, indent=2))
        timers = {"body": _timer_keys(sent), "route": _timer_keys(route), "db": _timer_keys((db or {}).get("payload"))}
        ctx.check(AP_STORED, summary_shown and status == 200 and body.get("kind") == "auto_posts"
                  and body.get("account_id") == aid and sent == {"posts": WANT} and route == {"posts": WANT}
                  and db == {"kind": "auto_posts", "payload": {"posts": WANT}} and not any(timers.values()),
                  row_summary=summary_shown, rule_name=body.get("name"), http_status=status, body=sent, route=route,
                  db=db, want=WANT, timer_keys=timers, screenshots=[saved])

        row = page.locator("tr").filter(has=page.get_by_text(LEGACY_NAME, exact=True))
        await _row_edit(page, row)
        old = page.get_by_role("dialog", name=f"Edit · {LEGACY_NAME}")
        await old.wait_for(timeout=30_000)
        notice = old.get_by_text(NOTICE, exact=True)
        shown = True
        try:
            await notice.wait_for(timeout=10_000)
        except Exception:  # noqa: BLE001 — the check below says what was missing
            shown = False
        legacy_shots = [await _shot(ctx, page, "legacy-notice")]
        fields = await old.get_by_placeholder("Post caption…").count()
        raw = None
        if await old.get_by_role("button", name="Edit in Raw JSON").count():
            await old.get_by_role("button", name="Edit in Raw JSON").click(timeout=10_000)
            ta = old.get_by_role("textbox", name="Post JSON")
            await ta.wait_for(timeout=10_000)
            raw = json.loads(await ta.input_value())
            legacy_shots.append(await _shot(ctx, page, "legacy-raw"))
        await old.get_by_role("button", name="Cancel", exact=True).click(timeout=10_000)
        await old.wait_for(state="hidden", timeout=30_000)
        legacy_db = _row(w, legacy_id)
        ctx.check(AP_LEGACY, shown and fields == 0 and raw == LEGACY
                  and legacy_db == {"kind": "auto_posts", "payload": LEGACY},
                  notice=shown, post_fields=fields, raw=raw, db=legacy_db, screenshots=legacy_shots)
