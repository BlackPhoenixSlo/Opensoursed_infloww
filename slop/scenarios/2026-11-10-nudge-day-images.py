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
WAIT_MS = 120_000
CHECKS = (DAY_CHIP, VAULT_ONLY, DAY_SAVED, SHARE_SAVED, DAY_PREVIEW, DAY_NO_5XX)
CONFIG, BULK, PREVIEW = "/admin/nudge-config", "/admin/nudge-config/bulk", "/admin/nudge-config/preview"
UPLOAD_PREFIX = "/api/of/v2/vault/upload/"
SEED_MEDIA = 9001
VAULT = (9001, 9002, 9003)
PICK = 9002
C1_MEDIA = 9101
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
    d = {k: {"text": v["text"], "image": own_night if k == "night" else []} for k, v in DEFAULT_SLOTS.items()}
    return {"default": d, "saturday": {"evening": {"text": [EDITED, *EVENING[1:]], "image": []}}}


async def _flow(ctx, page, chk, cs: list[dict]) -> None:
    c0, c1, c2 = (c["id"] for c in cs)
    calls: list[dict] = []
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
    await page.wait_for_function("(el) => el && el.value === " + json.dumps(NIGHT_LINE),
                                 arg=await night.get_by_placeholder("e.g. hey {name}").first.element_handle(
                                     timeout=WAIT_MS), timeout=WAIT_MS)
    save = dialog.get_by_role("button", name=SAVE_RX).first
    await page.wait_for_function("(b) => b && !b.disabled", arg=await save.element_handle(), timeout=WAIT_MS)

    group = dialog.get_by_role("radiogroup", name="Day")
    await group.scroll_into_view_if_needed()
    chips = await page.evaluate(CHIP_JS, await group.element_handle())
    await ui.shot(ctx, page, "nudge-day-trigger")
    chk(DAY_CHIP, chips["checked"] == ["false", "true", "false"] and chips["every"] == chips["mon"]
        and chips["every"] != chips["sat"], **chips)

    await night.scroll_into_view_if_needed()
    upload_buttons = await night.get_by_role("button", name=re.compile(r"upload", re.I)).count()
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

    chk(VAULT_ONLY, upload_buttons == 0 and file_inputs == 0 and not uploads,
        night_upload_buttons=upload_buttons, night_image_file_inputs=file_inputs, upload_posts=uploads)

    cfgs = {a: _stored(ctx, a) for a in (c0, c1, c2)}
    (ctx.out / "db-nudge-config.json").write_text(json.dumps(cfgs, indent=2, ensure_ascii=False))
    slots = cfgs[c0].get("slots") or {}
    want_sat = {"night": {"text": [], "image": [PICK]}, "evening": {"text": [EDITED, *EVENING[1:]], "image": []}}
    chk(DAY_SAVED, slots.get("saturday") == want_sat and slots.get("default") == DEFAULT_SLOTS
        and sorted(slots) == ["default", "saturday"], saturday=slots.get("saturday"), want_saturday=want_sat,
        default_unchanged=slots.get("default") == DEFAULT_SLOTS, buckets=sorted(slots))

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
