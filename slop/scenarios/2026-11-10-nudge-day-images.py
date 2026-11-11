"""Nudge online's day picker, vault-only slot images and Share to models (app/components/settings/NudgeSlotPools.tsx,
NudgeOnlineTab.tsx `share`, nudgeDayBuckets.ts; the relay's PUT /admin/nudge-config, PUT /admin/nudge-config/bulk
`_with_own_images`, the preview's per-field `_pick_pool` and `weekday`) on the real UI and the real relay routes: one
owner, one browser (1440x900), `agency_inbox` (3+ Creators; only Creators 0-2 are used). A layout flow, not a volume
one: `--users` and `--scale` change nothing, so no latency budget.

Seeded by SQL (product-writable rows only):
  - Creator 0: `account_ai_config.nudge_config_json` as PUT /admin/nudge-config stores it, `{"enabled": true,
    "delay_minutes": 7, "slots": {"default": ...}}` with one line per time (two for Evening) and vault image 9001 on
    Night; its vault mirror: `vault_items` 9001-9003 (seed/vault_week.import_stub) plus one finished manual walk
    (`vault_cache_runs` status done, phase done, no error), so /admin/vault-ai/cache/summary reads `complete` and
    the Vault picker lists the mirror (GET /admin/vault-ai/items), no OnlyFans read. Night has ONE line on purpose:
    the preview picks a random line and the image at that line's index, so the preview check is exact.
  - Creator 1: its own saved config (enabled false, delay_minutes 25, other lines, its own image 9101 on Night) and
    `vault_items` 9101. Creator 2: nothing.

Flow (Smart Messages > New Message > Nudge > Next; the editor's account select set to Creator 0):
  1. the Day picker's "Sat", clicked in the page (`el.click()`), and the three chips' computed border colours read
     as soon as Sat reads aria-checked (microtasks / 0 ms timers, no frame; screenshot nudge-day-trigger);
  2. on "Night (21–5)" "Add from vault" (the Vault picker), tile 9002, Attach (screenshot nudge-day-night-picked);
     "Edit for Saturdays" on "Evening (18–21)" and its first line retyped;
  3. under "Share to models" Creator 1's and Creator 2's switches on, "Share to 2 models" (the form is dirty, so it
     saves Creator 0 first), until "Shared to 2 models" shows (screenshot nudge-day-settled).
Expected:
  - DAY_CHIP: Every day's border colour == Mon's (unselected) != Sat's, at the first read after the click;
  - VAULT_ONLY: the Night card has no Upload button and no image file input (Import captions' text-file input is
    not one); no POST /api/of/v2/vault/upload/* left the browser during the flow;
  - DAY_SAVED: Creator 0's row: saturday = {night: {text: [], image: [9002]}, evening: {text: the every-day lines
    with the first edited, image: []}}; default = the seeded one; no other bucket;
  - SHARE_SAVED: exactly one PUT /admin/nudge-config (Creator 0) and one PUT /admin/nudge-config/bulk
    (account_ids [Creator 1, Creator 2]), the first answered 200 before the second was sent, the bulk 200 with
    count 2 / enabled true; Creator 1's and 2's rows: every setting = Creator 0's stored one (delay_minutes 7), the
    lines = Creator 0's (default + saturday.evening's edit; saturday.night, no lines and no own image there, absent),
    the images their own (Creator 1 default.night [9101], all else []; Creator 2 all []), no Creator 0 vault id
    anywhere; one nudge_online `automation_rules` row each, is_enabled 1;
  - DAY_PREVIEW: POST /admin/nudge-config/preview (owner cookie) on Creator 0's stored config, hour 23: weekday
    saturday answers [{text: the every-day night line, media: [9002]}] (lines from Every day, image Saturday's own:
    the per-field fallback), weekday monday [{same line, media: [9001]}];
  - DAY_NO_5XX: no 5xx answered to the browser.

Bypasses (declared): the vault mirror is seeded rows, not a Collect walk (no OnlyFans at its wire); every
`/api/of/*` read stays held (ui.py), so the picker's folder list and the slots' by-id reads (`useVaultMediaByIds`)
never answer: the picker shows the mirror's tiles (their /admin/vault-ai/thumb stills 404, no picture) and the slots
draw "#9001" / "#9002". The Sat click is a DOM `click()` in the page (no mouse move), so the chip read is not
racing Playwright's actionability waits.

Faults (`lib/nudge_day_faults.py`): `nudge-share-copies-source-images` (relay: the bulk route writes the source's
slots, vault ids included) turns only SHARE_SAVED red; `nudge-day-chip-fades` (client: the chips' `transition-colors`
back) turns only DAY_CHIP red.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlsplit

from slop.actors import ui
from slop.lib.nudge_day_faults import DAY_CHIP, DAY_NO_5XX, DAY_PREVIEW, DAY_SAVED, SHARE_SAVED, VAULT_ONLY
from slop.seed import ts, vault_week

PROFILE = "agency_inbox"
UI = True
FAULT = "nudge-share-copies-source-images"
VIEWPORT = (1440, 900)
WAIT_MS = 120_000  # first visit of a page compiles it in next dev
CHECKS = (DAY_CHIP, VAULT_ONLY, DAY_SAVED, SHARE_SAVED, DAY_PREVIEW, DAY_NO_5XX)
CONFIG, BULK, PREVIEW = "/admin/nudge-config", "/admin/nudge-config/bulk", "/admin/nudge-config/preview"
UPLOAD_PREFIX = "/api/of/v2/vault/upload/"
SEED_MEDIA = 9001  # Creator 0's every-day Night image
VAULT = (9001, 9002, 9003)  # Creator 0's mirror
PICK = 9002  # the tile picked for Saturday's Night
C1_MEDIA = 9101  # Creator 1's own Night image
NIGHT_LINE = "slop every-day night line"
EVENING = ["slop every-day evening one", "slop every-day evening two"]
EDITED = "slop saturday evening edited"
DEFAULT_SLOTS = {
    "morning_1": {"text": ["slop every-day morning early"], "image": []},
    "morning_2": {"text": ["slop every-day morning late"], "image": []},
    "afternoon_1": {"text": ["slop every-day afternoon early"], "image": []},
    "afternoon_2": {"text": ["slop every-day afternoon late"], "image": []},
    "evening": {"text": EVENING, "image": []},
    "night": {"text": [NIGHT_LINE], "image": [SEED_MEDIA]},
}
C0_CONFIG = {"enabled": True, "delay_minutes": 7, "slots": {"default": DEFAULT_SLOTS}}
C1_CONFIG = {"enabled": False, "delay_minutes": 25, "slots": {"default": {
    "morning_1": {"text": ["c1 own morning"], "image": []},
    "evening": {"text": ["c1 own evening"], "image": []},
    "night": {"text": ["c1 own night"], "image": [C1_MEDIA]},
}}}
SAVE_RX = re.compile(r"^(Create automation|Save changes|Saving…)$")
# Click Sat in the page, then read the chips' border colours as soon as React committed (microtasks, then 0 ms
# timers): a colour transition started by that commit is still at its start value then.
CHIP_JS = """async (group) => {
  const chip = (t) => [...group.querySelectorAll('[role=radio]')].find((b) => b.textContent.trim() === t);
  const sat = chip('Sat'), every = chip('Every day'), mon = chip('Mon');
  const t0 = performance.now();
  sat.click();
  let micro = 0, timers = 0;
  while (sat.getAttribute('aria-checked') !== 'true' && micro < 50) { await Promise.resolve(); micro++; }
  while (sat.getAttribute('aria-checked') !== 'true' && timers < 200) {
    await new Promise((r) => setTimeout(r, 0));
    timers++;
  }
  const bc = (el) => getComputedStyle(el).borderTopColor;
  const out = { every: bc(every), sat: bc(sat), mon: bc(mon), ms: performance.now() - t0, micro, timers,
                checked: [every, sat, mon].map((el) => el.getAttribute('aria-checked')),
                transition: getComputedStyle(every).transition };
  return out;
}"""


def _seed(w, c0: str, c1: str) -> None:
    """Creator 0's config and complete vault mirror, Creator 1's own config and image (as the product writes them)."""
    for mid in VAULT:
        vault_week.import_stub(w, c0, mid)
    vault_week.import_stub(w, c1, C1_MEDIA)
    now = ts(w.now)
    con = w.sql()
    with con:
        con.execute("INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, "
                    "started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
                    (c0, "done", "done", len(VAULT), len(VAULT), 1, now, now))
        for aid, cfg in ((c0, C0_CONFIG), (c1, C1_CONFIG)):
            con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                        " VALUES (?, 0, 100)", (aid,))
            con.execute("UPDATE account_ai_config SET nudge_config_json=? WHERE account_id=?", (json.dumps(cfg), aid))
    con.close()


def _card(dialog, label: str):
    """A time slot's editor card: the parent of its label."""
    return dialog.get_by_text(label, exact=True).locator("xpath=..")


def _stored(ctx, aid: str) -> dict:
    con = ctx.world.sql()
    row = con.execute("SELECT nudge_config_json FROM account_ai_config WHERE account_id=?", (aid,)).fetchone()
    con.close()
    return json.loads(row[0]) if row and row[0] else {}


def _rules(ctx, aids: list[str]) -> dict:
    con = ctx.world.sql()
    rows = con.execute("SELECT account_id, is_enabled FROM automation_rules WHERE kind='nudge_online' AND account_id"
                       f" IN ({','.join('?' * len(aids))})", aids).fetchall()
    con.close()
    out: dict = {a: [] for a in aids}
    for a, en in rows:
        out[a].append(int(en))
    return out


def _ids(slots: dict) -> set:
    return {i for day in slots.values() if isinstance(day, dict) for e in day.values() if isinstance(e, dict)
            for i in e.get("image") or []}


def _want_target(own_night: list[int]) -> dict:
    """A Share target's slots: Creator 0's lines (Saturday's evening edit too), the target's own images."""
    d = {k: {"text": v["text"], "image": own_night if k == "night" else []} for k, v in DEFAULT_SLOTS.items()}
    return {"default": d, "saturday": {"evening": {"text": [EDITED, *EVENING[1:]], "image": []}}}


async def _flow(ctx, page, chk, cs: list[dict]) -> None:
    c0, c1, c2 = (c["id"] for c in cs)
    calls: list[dict] = []  # PUT config / bulk, request and response times
    uploads: list[dict] = []

    def on_request(req):
        p = urlsplit(req.url).path
        if req.method == "POST" and p.startswith(UPLOAD_PREFIX):
            uploads.append({"t": time.time() * 1000, "path": p})
        if req.method == "PUT" and p in (CONFIG, BULK):
            try:
                body = json.loads(req.post_data or "{}")
            except ValueError:
                body = {"raw": (req.post_data or "")[:300]}
            calls.append({"path": p, "sent": time.time() * 1000, "body": body, "req": req})

    def on_response(resp):
        for c in calls:
            if c["req"] is resp.request:
                c["answered"], c["status"] = time.time() * 1000, resp.status

    page.on("request", on_request)
    page.on("response", on_response)
    await page.goto(f"{ctx.app}/growth/smart-messages", wait_until="domcontentloaded")
    await page.get_by_role("button", name="New Message").first.click(timeout=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r"^Nudge")).first.click(timeout=30_000)
    await page.get_by_role("button", name="Next", exact=True).click(timeout=10_000)
    dialog = page.get_by_role("dialog").filter(has=page.get_by_role("heading", name="Nudge online", exact=True))
    await dialog.locator("select").filter(has=page.locator(f'option[value="{c0}"]')).first.select_option(
        c0, timeout=WAIT_MS)
    night = _card(dialog, "Night (21–5)")
    evening = _card(dialog, "Evening (18–21)")
    # Hydrated with the seeded config: Every day's Night line is in its field, and Save is allowed.
    await page.wait_for_function("(el) => el && el.value === " + json.dumps(NIGHT_LINE),
                                 arg=await night.get_by_placeholder("e.g. hey {name}").first.element_handle(
                                     timeout=WAIT_MS), timeout=WAIT_MS)
    save = dialog.get_by_role("button", name=SAVE_RX).first
    await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=WAIT_MS)

    # 1. the day chips, read in the same task as the click
    group = dialog.get_by_role("radiogroup", name="Day")
    await group.scroll_into_view_if_needed()
    chips = await page.evaluate(CHIP_JS, await group.element_handle())
    await ui.shot(ctx, page, "nudge-day-trigger")
    chk(DAY_CHIP, chips["checked"] == ["false", "true", "false"] and chips["every"] == chips["mon"]
        and chips["every"] != chips["sat"], **chips)

    # 2. Saturday's Night image from the vault, Evening's lines made Saturday's own
    await night.scroll_into_view_if_needed()
    upload_buttons = await night.get_by_role("button", name=re.compile(r"upload", re.I)).count()
    # An image file input (the removed upload's); Import captions' text-file input is not one.
    file_inputs = await night.locator('input[type=file][accept*="image"]').count()
    await night.get_by_role("button", name="Add image from vault").click(timeout=10_000)
    picker = page.get_by_role("dialog", name="Vault picker")
    await picker.locator(f'[data-tile-id="{PICK}"]').click(timeout=WAIT_MS)
    await picker.get_by_role("button", name="Attach", exact=True).click(timeout=10_000)
    await picker.wait_for(state="hidden", timeout=10_000)
    await night.get_by_text(f"#{PICK}", exact=True).wait_for(timeout=10_000)
    await ui.shot(ctx, page, "nudge-day-night-picked")
    await evening.get_by_role("button", name="Edit for Saturdays").click(timeout=10_000)
    await evening.get_by_placeholder("e.g. hey {name}").first.fill(EDITED)

    # 3. Share to Creators 1 and 2 (the dirty form saves Creator 0 first)
    for c in cs[1:]:
        sw = dialog.get_by_role("switch", name=c["nickname"], exact=True)
        await sw.scroll_into_view_if_needed()
        await sw.click(timeout=10_000)
    share = dialog.get_by_role("button", name="Share to 2 models", exact=True)
    await share.click(timeout=10_000)
    msg = dialog.get_by_text(re.compile(r"^(Shared to \d+ models?|Not shared|Failed)"))
    await msg.first.wait_for(timeout=60_000)
    shared_msg = await msg.first.inner_text()
    await msg.first.scroll_into_view_if_needed()
    await page.wait_for_timeout(300)
    await ui.shot(ctx, page, "nudge-day-settled")
    for c in calls:
        c.pop("req", None)
    (ctx.out / "requests.json").write_text(json.dumps({"puts": calls, "uploads": uploads}, indent=2))

    # VAULT_ONLY
    chk(VAULT_ONLY, upload_buttons == 0 and file_inputs == 0 and not uploads,
        night_upload_buttons=upload_buttons, night_image_file_inputs=file_inputs, upload_posts=uploads)

    # DAY_SAVED: Creator 0's row
    cfgs = {a: _stored(ctx, a) for a in (c0, c1, c2)}
    (ctx.out / "db-nudge-config.json").write_text(json.dumps(cfgs, indent=2, ensure_ascii=False))
    slots = cfgs[c0].get("slots") or {}
    want_sat = {"night": {"text": [], "image": [PICK]}, "evening": {"text": [EDITED, *EVENING[1:]], "image": []}}
    chk(DAY_SAVED, slots.get("saturday") == want_sat and slots.get("default") == DEFAULT_SLOTS
        and sorted(slots) == ["default", "saturday"], saturday=slots.get("saturday"), want_saturday=want_sat,
        default_unchanged=slots.get("default") == DEFAULT_SLOTS, buckets=sorted(slots))

    # SHARE_SAVED: the PUT sequence, the targets' rows, their rules
    puts = [c for c in calls if c["path"] == CONFIG]
    bulks = [c for c in calls if c["path"] == BULK]
    seq_ok = (len(puts) == 1 and len(bulks) == 1 and puts[0]["body"].get("account_id") == c0
              and puts[0].get("status") == 200 and bulks[0].get("status") == 200
              and puts[0].get("answered", 1e18) <= bulks[0]["sent"]
              and bulks[0]["body"].get("account_ids") == [c1, c2])
    settings = {a: {k: v for k, v in cfgs[a].items() if k != "slots"} for a in (c0, c1, c2)}
    want = {c1: _want_target([C1_MEDIA]), c2: _want_target([])}
    got = {a: cfgs[a].get("slots") for a in (c1, c2)}
    leaked = {a: sorted(_ids(got[a] or {}) & set(VAULT)) for a in (c1, c2)}
    rules = _rules(ctx, [c1, c2])
    chk(SHARE_SAVED, seq_ok and settings[c1] == settings[c0] == settings[c2] and settings[c0].get("delay_minutes") == 7
        and got == want and not any(leaked.values()) and all(v == [1] for v in rules.values())
        and shared_msg.startswith("Shared to 2 models (on)"),
        sequence=[{k: c.get(k) for k in ("path", "sent", "answered", "status")} | {
            "account": c["body"].get("account_id") or c["body"].get("account_ids")} for c in calls],
        settings=settings, slots=got, want_slots=want, creator0_ids_in_targets=leaked, rules=rules,
        message=shared_msg)

    # DAY_PREVIEW: by day, on Creator 0's stored config
    pv = {}
    for day in ("saturday", "monday"):
        r = await ctx.owner.post(PREVIEW, json={"account_id": c0, "config": cfgs[c0], "hour": 23, "weekday": day})
        pv[day] = {"status": r.status_code, **(r.json() if r.status_code == 200 else {"body": r.text[:300]})}
    (ctx.out / "preview.json").write_text(json.dumps(pv, indent=2, ensure_ascii=False))
    msgs = {d: [{"text": m.get("text"), "media": m.get("media")} for m in v.get("messages") or []]
            for d, v in pv.items()}
    want_pv = {"saturday": [{"text": NIGHT_LINE, "media": [PICK]}], "monday": [{"text": NIGHT_LINE,
                                                                           "media": [SEED_MEDIA]}]}
    chk(DAY_PREVIEW, msgs == want_pv and all(v.get("slot") == "night" for v in pv.values()), got=msgs,
        want=want_pv, slots=[v.get("slot") for v in pv.values()], statuses=[v["status"] for v in pv.values()])

    # DAY_NO_5XX
    bad = [[s, u] for s, u in page.slop["statuses"] if s >= 500][:10]
    chk(DAY_NO_5XX, not bad, five_xx=bad, responses=len(page.slop["statuses"]))
    (ctx.out / "day-flow.json").write_text(json.dumps({"chips": chips, "message": shared_msg}, indent=2))


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    cs = w.data["creators"][:3]
    _seed(w, cs[0]["id"], cs[1]["id"])
    if ctx.app is None:
        for c in CHECKS:
            ctx.skip(c, "--no-ui")
        return
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        done: set[str] = set()

        def chk(name: str, ok: bool, **detail) -> None:
            done.add(name)
            ctx.check(name, ok, **detail)

        try:
            await _flow(ctx, page, chk, cs)
        except Exception as e:  # noqa: BLE001 — a UI step that cannot complete is its checks' FAIL
            try:
                await ui.shot(ctx, page, "failed-nudge-day")
            except Exception:  # noqa: BLE001
                pass
            for c in CHECKS:
                if c not in done:
                    ctx.check(c, False, error=f"{type(e).__name__}: {e}"[:600])
        ctx.metric("held_of_reads", len(page.slop["held_of_reads"]))
        ctx.metric("offhost_aborted", len(page.slop["offhost_aborted"]))
