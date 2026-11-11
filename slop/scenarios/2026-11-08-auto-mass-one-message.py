"""My Automations > Auto Mass: one rule = one message, the rule's "Run every" its only clock, all in ONE popup (the
message's fields inline, no Compose dialog / "Use in rule"), the list showing each rule's message (app/components/
compose/PremadeFields.tsx, premadeRows.ts, automations/ruleEditorForm.ts, readyMadeContent.ts, ReadyMadeRuleEditor.tsx,
RuleTable.tsx).

World: `agency_inbox`. Creator 0 gets three disabled Auto Mass rules (nothing fires) through the real POST
/admin/automation-rules: an older one (two messages, a resend on the first, a delay on the second), a one-message
audience rule the form holds (lists, an exclude list, chat guards) and a one-message rule with keys the form can't hold
(`excluded_users`, `filters`).
Flow, on a 390x844 phone: the owner opens /growth/auto-mass, New auto mass: the popup holds the message box at once
(screenshots `popup-top`, `audience-block`, `more-settings-collapsed`), sets the audience chips and lists
(`online-only-selected`, `-dark`), types a message, Create (`saved`: the new row reads its message and audience); then
Edit + Save changes on the audience rule (`more-settings-opened-from-exclude-list`), Edit + Save changes on the
keys rule (`edit-keeps-notice`), Edit on the older rule (`legacy-notice`), Edit in Raw JSON (`legacy-raw`), Cancel.

Checks (names in lib/auto_mass_faults.py):
  AM_FORM       one popup (no Compose button, no second dialog) with one message and no list / resend / delay field;
                the skip-chatted-with chips with 1h on; More settings closed (its fields hidden); popup and page fit
                the phone.
  AM_STORED     the POST body's payload, the GET route's and the automation_rules row's: exactly the one message.
  AM_AUDIENCE   All fans / Following / Send to online only in one row; the chips and lists saved as user_lists /
                excluded_user_lists / online_only; the list row reads the audience.
  AM_ROUNDTRIP  the audience rule opens in the form with More settings open; Save changes untouched keeps steps_json
                byte for byte.
  AM_EDIT_KEEPS the keys rule opens with the Raw JSON notice, no message fields; Save changes untouched keeps steps_json
                byte for byte (the form would drop excluded_users / filters: other fans get the mass).
  AM_LEGACY     the older rule's notice, no message fields, Raw JSON holds its payload, the row unchanged after Cancel.

FAULT `auto-mass-form-takes-unknown-keys` (client: `formHoldReason` back to "more than one item", the F1 blocker):
AM_EDIT_KEEPS alone. Others (`--fault=`): `auto-mass-online-chip-noop` (the Send to online only chip no longer flips
online_only: AM_AUDIENCE alone), `auto-mass-skip-chatted-off` (AM_FORM, AM_STORED).
UI only (`--no-ui` skips): not a volume path, proven once on the real page.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.auto_mass_faults import AM_AUDIENCE, AM_EDIT_KEEPS, AM_FORM, AM_LEGACY, AM_ROUNDTRIP, AM_STORED

PROFILE = "agency_inbox"
UI = True
FAULT = "auto-mass-form-takes-unknown-keys"
PHONE = (390, 844)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
TEXT = "slop auto mass one"
LEGACY_NAME = "slop legacy drip"
LEGACY = {"messages": [{"text": "slop legacy one", "resend_count": 1, "resend_after_hours": 24},
                       {"text": "slop legacy two", "delay_minutes": 60}]}
WANT = [{"text": TEXT, "user_lists": ["following", "77"], "excluded_user_lists": ["88"],
         "exclude_last_chat_hours": 1}]
# The list row's read-out of WANT (readyMadeContent `summarize`).
SUMMARY = f"Free · {TEXT} · Following + 1 list · excl. 1 list · skips chatted 1h"
GONE = ("Resend this many times", "Wait between resends", "Delay before posting", "Delay after previous")
NOTICE = "Older multi-message rule — edit in Raw JSON."
OLD_NAME = "slop old audience"
# Every key one the form holds, so it opens in the form (More settings open for its guards).
OLD_PAYLOAD = {"messages": [{"text": "old audience", "online_only": True, "user_lists": ["fans", "following"],
                              "excluded_user_lists": ["77"], "exclude_last_chat_hours": 1,
                              "exclude_replied_hours": 2, "recent_chat_limit": 12}]}
KEEPS_NAME = "slop keeps audience"
# One message, but backend audience keys the form doesn't hold: rebuilt from the form, the mass would reach the
# excluded fans and every fan instead of the online ones.
KEEPS_PAYLOAD = {"messages": [{"text": "keeps audience", "user_lists": ["fans"], "excluded_users": [910001, 910002],
                               "filters": {"online": 1}}]}
KEEPS_NOTICE = "Uses settings the Composer can't edit — edit in Raw JSON."
RULES = "/admin/automation-rules"
# The page and each open dialog within the phone's width.
_FITS = """() => ({page: document.documentElement.scrollWidth, vw: innerWidth,
  dialogs: [...document.querySelectorAll('[role=dialog]')].map((d) => {
    const r = d.getBoundingClientRect(); return {left: r.left, right: r.right, sw: d.scrollWidth, cw: d.clientWidth}; })})"""


# Finite animations (a modal's pop in / out) done; a skeleton's endless pulse does not count.
_SETTLED = """() => document.getAnimations().filter((a) => a.playState === 'running'
  && a.effect && a.effect.getComputedTiming().iterations !== Infinity).length === 0"""


async def _shot(ctx, page, name: str) -> str:
    await page.wait_for_function(_SETTLED, timeout=15_000)
    return await ui.shot(ctx, page, name)


def _fits(f: dict) -> bool:
    return f["page"] <= f["vw"] and all(d["left"] >= -0.5 and d["right"] <= f["vw"] + 0.5 and d["sw"] <= d["cw"] + 1
                                        for d in f["dialogs"])


def _row(w, rule_id) -> dict | None:
    """The automation_rules row: its kind, and steps_json as stored (`raw`, for byte checks) and parsed (`payload`)."""
    con = w.sql()
    row = con.execute("SELECT kind, steps_json FROM automation_rules WHERE id=?", (rule_id,)).fetchone()
    con.close()
    return {"kind": row[0], "payload": json.loads(row[1] or "{}"), "raw": row[1]} if row else None


def _raw(w, rule_id) -> str | None:
    row = _row(w, rule_id)
    return row["raw"] if row else None


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    if not ctx.app:
        for n in (AM_FORM, AM_AUDIENCE, AM_STORED, AM_LEGACY, AM_ROUNDTRIP, AM_EDIT_KEEPS):
            ctx.skip(n, "--no-ui")
        return
    aid = w.data["creators"][0]["id"]
    r = await ctx.owner.post(RULES, json={"account_id": aid, "kind": "mass_premade", "name": LEGACY_NAME,
                                          "every_seconds": 86400, "payload": LEGACY, "is_enabled": False})
    r.raise_for_status()
    legacy_id = r.json()["id"]
    old = await ctx.owner.post(RULES, json={"account_id": aid, "kind": "mass_premade", "name": OLD_NAME,
                                            "every_seconds": 86400, "payload": OLD_PAYLOAD, "is_enabled": False})
    old.raise_for_status()
    old_id = old.json()["id"]
    old_before = _raw(w, old_id)
    keeps = await ctx.owner.post(RULES, json={"account_id": aid, "kind": "mass_premade", "name": KEEPS_NAME,
                                              "every_seconds": 86400, "payload": KEEPS_PAYLOAD, "is_enabled": False})
    keeps.raise_for_status()
    keeps_id = keeps.json()["id"]
    keeps_before = _raw(w, keeps_id)

    async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
        # The app's shared fan-list picker reads OF directly; feed the same boundary as its production response so
        # both tabs contain real options in the screenshot and the create flow exercises both payload keys.
        async def audience_lists(route):
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"list": [
                {"id": "77", "name": "Audience list", "type": "custom", "usersCount": 3},
                {"id": "88", "name": "Skip list", "type": "custom", "usersCount": 2},
            ], "hasMore": False}))

        await page.route(lambda u: urlsplit(u).path == "/api/of/v2/lists", audience_lists)
        page.context.set_default_navigation_timeout(WAIT_MS)
        await page.goto(f"{ctx.app}/growth/auto-mass?creator={aid}", wait_until="domcontentloaded")
        await page.get_by_text(LEGACY_NAME, exact=True).first.wait_for(timeout=WAIT_MS)
        await page.get_by_role("button", name="New auto mass").first.click(timeout=WAIT_MS)
        editor = page.get_by_role("dialog", name="New auto mass message")  # the message's fields are in the popup
        box = editor.get_by_placeholder("Broadcast text…")
        await box.wait_for(timeout=WAIT_MS)
        shots = [await _shot(ctx, page, "popup-top")]
        one_popup = {
            "compose_button": await editor.get_by_role("button", name="Compose", exact=True).count(),
            "use_in_rule": await page.get_by_role("button", name="Use in rule").count(),
            "dialogs": await page.get_by_role("dialog").count(),
        }

        chips = editor.get_by_role("radiogroup", name="Skip fans chatted with in last")
        await chips.scroll_into_view_if_needed(timeout=10_000)
        # Keep the real picker in the evidence; don't capture its transient skeleton on the first visit.
        await editor.get_by_role("checkbox", name="Audience list (3)", exact=True).wait_for(timeout=30_000)
        more = editor.get_by_role("button", name="More settings")
        await more.scroll_into_view_if_needed(timeout=10_000)
        shots.append(await _shot(ctx, page, "audience-block"))
        more_collapsed = await _shot(ctx, page, "more-settings-collapsed")
        radios = chips.get_by_role("radio")
        form = {
            "one_popup": one_popup,
            "message_heading": await editor.get_by_role("heading", name="Message 1").count(),
            "add_another": await editor.get_by_role("button", name="Add another message").count(),
            "gone_fields": {g: await editor.get_by_label(g, exact=True).count() for g in GONE},
            "chips": [await x.inner_text() for x in await radios.all()],
            "checked": [await x.inner_text() for x in await radios.all() if await x.get_attribute("aria-checked") == "true"],
            "more_expanded": await more.get_attribute("aria-expanded"),
            "more_fields": await editor.get_by_label("Exclude I replied to", exact=True).count(),
            "fits": await page.evaluate(_FITS),
        }
        ctx.check(AM_FORM, one_popup == {"compose_button": 0, "use_in_rule": 0, "dialogs": 1}
                  and form["message_heading"] == 0 and form["add_another"] == 0
                  and not any(form["gone_fields"].values()) and form["chips"] == ["Off", "1h", "3h", "8h", "24h"]
                  and form["checked"] == ["1h"] and form["more_expanded"] == "false" and form["more_fields"] == 0
                  and _fits(form["fits"]), **form, screenshots=shots)

        send_to = editor.get_by_role("group", name="Send to")
        chip_names = ["All fans", "Following", "Send to online only"]
        audience_buttons = [send_to.get_by_role("button", name=name) for name in chip_names]
        visible_chips = [await button.count() for button in audience_buttons]
        chip_tops = [await button.evaluate("el => el.getBoundingClientRect().top") for button in audience_buttons]
        online = audience_buttons[2]
        await online.click(timeout=10_000)  # off, then on: selected blue after a click
        await online.click(timeout=10_000)
        await online.scroll_into_view_if_needed(timeout=10_000)
        shots.append(await _shot(ctx, page, "online-only-selected"))
        online_color = await online.evaluate("el => getComputedStyle(el).color")
        await page.evaluate("() => document.documentElement.removeAttribute('data-theme')")
        shots.append(await _shot(ctx, page, "online-only-selected-dark"))
        dark_color = await online.evaluate("el => getComputedStyle(el).color")
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'light')")
        list_tabs = editor.get_by_role("tablist", name="Custom lists")
        visible_list_tabs = [await list_tabs.get_by_role("tab", name=name).count() for name in ("Include", "Exclude")]
        await list_tabs.get_by_role("tab", name="Exclude").click(timeout=10_000)
        exclude_tab_visible = await editor.get_by_role("tabpanel", name="Exclude custom lists").count()
        await editor.get_by_role("checkbox", name="Skip list (2)", exact=True).check(timeout=10_000)
        await list_tabs.get_by_role("tab", name="Include").click(timeout=10_000)
        await editor.get_by_role("checkbox", name="Audience list (3)", exact=True).check(timeout=10_000)
        await send_to.get_by_role("button", name="All fans").click(timeout=10_000)
        await send_to.get_by_role("button", name="Send to online only").click(timeout=10_000)
        await chips.get_by_role("radio", name="1h").wait_for(timeout=10_000)
        audience_state = {
            "chips": visible_chips,
            "online_color": online_color,
            "dark_color": dark_color,
            "all_fans_selected": "bg-[#3563ff]/10" in (await send_to.get_by_role("button", name="All fans").get_attribute("class") or ""),
            "following_selected": "bg-[#3563ff]/10" in (await send_to.get_by_role("button", name="Following").get_attribute("class") or ""),
            "online_pressed": await send_to.get_by_role("button", name="Send to online only").get_attribute("aria-pressed"),
        }
        chip_state_ok = visible_chips == [1, 1, 1] and max(chip_tops) - min(chip_tops) < 1 \
            and online_color == dark_color == "rgb(53, 99, 255)" \
            and visible_list_tabs == [1, 1] and exclude_tab_visible == 1 \
            and audience_state["all_fans_selected"] is False \
            and audience_state["following_selected"] is True and audience_state["online_pressed"] == "false"

        await box.fill(TEXT)
        async with page.expect_response(lambda x: x.request.method == "POST" and urlsplit(x.url).path == RULES,
                                        timeout=30_000) as created:
            await editor.get_by_role("button", name="Create", exact=True).click(timeout=10_000)
        resp = await created.value
        status, body, rule = resp.status, resp.request.post_data_json or {}, await resp.json()
        await editor.wait_for(state="hidden", timeout=30_000)
        new_row = page.locator("tr").filter(has=page.get_by_text(rule.get("name") or "Auto mass", exact=True))
        summary_shown = True
        try:
            await new_row.get_by_text(SUMMARY, exact=True).wait_for(timeout=30_000)
        except Exception:  # noqa: BLE001 — the check below says what was missing
            summary_shown = False
        saved = await _shot(ctx, page, "saved")

        listed = (await ctx.owner.get(f"{RULES}?account_id={aid}")).json().get("rules") or []
        route = next((x.get("payload") for x in listed if x.get("id") == rule.get("id")), None)
        db = _row(w, rule.get("id"))
        (ctx.out / "auto-mass-created.json").write_text(json.dumps(
            {"status": status, "body": body, "route": route, "db": db}, indent=2))
        def without_audience(payload):
            payload = json.loads(json.dumps(payload or {}))
            for item in payload.get("messages", []):
                for key in ("online_only", "user_lists", "excluded_user_lists"):
                    item.pop(key, None)
            return payload

        expected_plain = {"messages": [{"text": TEXT, "exclude_last_chat_hours": 1}]}
        ctx.check(AM_STORED, status == 200 and body.get("kind") == "mass_premade" and body.get("account_id") == aid
                  and without_audience(body.get("payload")) == expected_plain
                  and without_audience(route) == expected_plain
                  and db is not None and without_audience(db.get("payload")) == expected_plain,
                  rule_name=body.get("name"), http_status=status, body=body.get("payload"),
                  route=route, db=db, want=expected_plain, screenshots=[saved])
        saved_summary_ok = summary_shown and SUMMARY in await new_row.inner_text()
        actual_message = ((body.get("payload") or {}).get("messages") or [{}])[0]
        ctx.check(AM_AUDIENCE, chip_state_ok and actual_message == WANT[0] and saved_summary_ok,
                  **audience_state, chip_tops=chip_tops, list_tabs=visible_list_tabs, exclude_tab_visible=exclude_tab_visible,
                  posted=actual_message, saved_summary=await new_row.inner_text(), want=WANT[0],
                  screenshots=[more_collapsed, saved])

        old_row = page.locator("tr").filter(has=page.get_by_text(OLD_NAME, exact=True))
        await old_row.get_by_role("button", name="Edit", exact=True).click(timeout=30_000)
        old_editor = page.get_by_role("dialog", name=f"Edit · {OLD_NAME}")
        await old_editor.wait_for(timeout=30_000)
        await old_editor.get_by_role("tab", name="Exclude", exact=False).click(timeout=10_000)
        old_more = old_editor.get_by_role("button", name="More settings")
        more_opened = await old_more.get_attribute("aria-expanded")
        await old_editor.get_by_label("Exclude I replied to", exact=True).scroll_into_view_if_needed(timeout=10_000)
        opened_shot = await _shot(ctx, page, "more-settings-opened-from-exclude-list")
        before_bytes = old_before
        async with page.expect_response(lambda x: x.request.method == "PATCH"
                                        and urlsplit(x.url).path.startswith(RULES + "/"), timeout=30_000) as saved_old:
            await old_editor.get_by_role("button", name="Save changes", exact=True).click(timeout=10_000)
        old_resp = await saved_old.value
        await old_editor.wait_for(state="hidden", timeout=30_000)
        after_bytes = _raw(w, old_id)
        ctx.check(AM_ROUNDTRIP, more_opened == "true" and before_bytes == after_bytes and before_bytes is not None,
                  more_expanded=more_opened, before_bytes=before_bytes, after_bytes=after_bytes,
                  http_status=old_resp.status, screenshots=[opened_shot])

        keeps_row = page.locator("tr").filter(has=page.get_by_text(KEEPS_NAME, exact=True))
        await keeps_row.get_by_role("button", name="Edit", exact=True).click(timeout=30_000)
        keeps_editor = page.get_by_role("dialog", name=f"Edit · {KEEPS_NAME}")
        await keeps_editor.wait_for(timeout=30_000)
        keeps_notice = True
        try:
            await keeps_editor.get_by_text(KEEPS_NOTICE, exact=True).wait_for(timeout=10_000)
        except Exception:  # noqa: BLE001 — the check below says what was missing
            keeps_notice = False
        keeps_fields = await keeps_editor.get_by_placeholder("Broadcast text…").count()
        keeps_shot = await _shot(ctx, page, "edit-keeps-notice")
        async with page.expect_response(lambda x: x.request.method == "PATCH"
                                        and urlsplit(x.url).path == f"{RULES}/{keeps_id}", timeout=30_000) as saved_keeps:
            await keeps_editor.get_by_role("button", name="Save changes", exact=True).click(timeout=10_000)
        keeps_resp = await saved_keeps.value
        await keeps_editor.wait_for(state="hidden", timeout=30_000)
        keeps_after = _raw(w, keeps_id)
        ctx.check(AM_EDIT_KEEPS, keeps_notice and keeps_fields == 0 and keeps_resp.status == 200
                  and keeps_before is not None and keeps_before == keeps_after,
                  notice=keeps_notice, message_fields=keeps_fields, http_status=keeps_resp.status,
                  patched=keeps_resp.request.post_data_json, before_bytes=keeps_before, after_bytes=keeps_after,
                  screenshots=[keeps_shot])

        row = page.locator("tr").filter(has=page.get_by_text(LEGACY_NAME, exact=True))
        await row.get_by_role("button", name="Edit", exact=True).click(timeout=30_000)
        old = page.get_by_role("dialog", name=f"Edit · {LEGACY_NAME}")
        await old.wait_for(timeout=30_000)
        notice = old.get_by_text(NOTICE, exact=True)
        shown = True
        try:
            await notice.wait_for(timeout=10_000)
        except Exception:  # noqa: BLE001 — the check below says what was missing
            shown = False
        legacy_shots = [await _shot(ctx, page, "legacy-notice")]
        fields = await old.get_by_placeholder("Broadcast text…").count()
        raw = None
        if await old.get_by_role("button", name="Edit in Raw JSON").count():
            await old.get_by_role("button", name="Edit in Raw JSON").click(timeout=10_000)
            ta = old.get_by_role("textbox", name="Message JSON")
            await ta.wait_for(timeout=10_000)
            raw = json.loads(await ta.input_value())
            legacy_shots.append(await _shot(ctx, page, "legacy-raw"))
        await old.get_by_role("button", name="Cancel", exact=True).click(timeout=10_000)
        await old.wait_for(state="hidden", timeout=30_000)
        legacy_db = _row(w, legacy_id)
        ctx.check(AM_LEGACY, shown and fields == 0 and raw == LEGACY
                  and legacy_db is not None and legacy_db["kind"] == "mass_premade" and legacy_db["payload"] == LEGACY,
                  notice=shown, message_fields=fields, raw=raw, db=legacy_db, screenshots=legacy_shots)
