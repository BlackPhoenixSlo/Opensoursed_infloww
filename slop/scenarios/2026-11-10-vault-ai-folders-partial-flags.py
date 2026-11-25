from __future__ import annotations

import json
import re

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import picture_bytes
from slop.lib.vault_ai_folders_faults import (COLOURLESS, CREATE_ENABLED, CREATED, PHONE_OFFERED, NO_DUPES,
                                              PAID_ONLY, PLAN, PREVIEW, PREVIEW_SHOWN, SCRIPTS_CAPPED)
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_ui import TOURS_SEEN
from slop.seed import vault_ai_sets, vault_flags_partial

PROFILE = "agency_inbox"
UI = True
FAULT = "ai-folders-dupe-collapse-off"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
VIEWPORT, PHONE = (1440, 900), (390, 844)
WAIT_MS = 120_000
APPLY = "/admin/vault-ai/folder-plan/apply"
NOTE = re.compile(r"(\d+) of (\d+) stills?\b")
CREATE = re.compile(r"^Create \d+ folders( · retire \d+ linked to OnlyFans)?$")
CHANGES = re.compile(r"will create (\d+) · keep (\d+) · retire (\d+)")
AI_CREATOR = "vault_ai_script"


async def _open_extras(ctx, page, creator: dict, *, pick: bool = True) -> None:
    await page.context.add_init_script(TOURS_SEEN + ("" if pick else
                                       f"localStorage.setItem('vault.accountId', '{creator['id']}');"))
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
    if pick:
        await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=WAIT_MS)


async def _modal(ctx, page, creator: dict, got: dict, shot: str):
    await _open_extras(ctx, page, creator)
    await page.get_by_role("button", name="Build AI folders", exact=True).click(timeout=WAIT_MS)
    note = page.get_by_text(NOTE).first
    await note.wait_for(timeout=WAIT_MS)
    got["note"] = (await note.inner_text()).strip()
    line = page.get_by_text(CHANGES).first
    await line.wait_for(timeout=WAIT_MS)
    got["changes_line"] = (await line.inner_text()).strip()
    create = page.get_by_role("button", name=CREATE)
    await create.wait_for(timeout=WAIT_MS)
    got["create_label"] = (await create.inner_text()).strip()
    got["create_enabled"] = await create.is_enabled()
    await page.wait_for_timeout(800)
    got["trigger_shot"] = await ui.shot(ctx, page, shot)
    return create


def _enabled_ok(got: dict, truth: dict) -> bool:
    m = NOTE.search(got.get("note") or "")
    return ("error" not in got and bool(m) and (int(m.group(1)), int(m.group(2))) ==
            (truth["stills"] - truth["flagged"], truth["stills"]) and got.get("create_enabled") is True)


def _counts(text: str | None) -> tuple[int, ...] | None:
    m = CHANGES.search(text or "")
    return tuple(int(g) for g in m.groups()) if m else None


async def run(ctx):
    w = ctx.world
    await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    aid = creator["id"]
    truth = vault_flags_partial.seed(w, creator, int(ctx.param("items", w.size["vault_ai_items"])))
    vault_ai_sets.seed(w, creator, truth)
    copies = {int(c): int(o) for c, o in truth["copies"].items()}
    thumbs = stills_dir(ctx.stack.tmp) / "thumbs" / aid
    thumbs.mkdir(parents=True, exist_ok=True)
    cls_of = {mid: cls for cls in ("ten", "fifty", "ten_raw", "fifty_raw", "soft", "videos") for mid in truth[cls]}
    for mid, cls in cls_of.items():
        (thumbs / f"{mid}.jpg").write_bytes(picture_bytes(f"{cls}/{mid}"))
    for copy, orig in copies.items():
        (thumbs / f"{copy}.jpg").write_bytes(picture_bytes(f"{cls_of[orig]}/{orig}"))
    for mid in truth["colourless"]:
        (thumbs / f"{mid}.jpg").write_bytes(picture_bytes(f"colourless/{mid}"))
    for room in ("bedroom", "bathroom"):
        for mid in truth["big_shoot"][room]:
            (thumbs / f"{mid}.jpg").write_bytes(picture_bytes(f"big-{room}/{mid}"))
    ten, fifty = set(truth["ten"]), set(truth["fifty"])
    raw = set(truth["ten_raw"]) | set(truth["fifty_raw"])
    ctx.note(f"Creator {aid}: {truth['stills']} stills ({truth['flagged']} flagged), {len(truth['videos'])} videos; "
             f"$10 {len(ten)}, $50 {len(fifty)}, unflagged paid {len(raw)}; {len(copies)} dupe copies, "
             f"colourless shoot {truth['colourless']}")

    r = await ctx.owner.get(f"/admin/vault-ai/folder-plan?account_id={aid}&keep=10")
    plan = r.json() if r.status_code == 200 else {}
    folders = plan.get("folders") or []
    lanes = {f.get("lane"): {it["media_id"] for it in f.get("items") or []} for f in folders}
    flags = plan.get("flags") or {}
    want_flags = {"stills": truth["stills"], "flagged": truth["flagged"],
                  "missing": truth["stills"] - truth["flagged"], "ready": False}
    got_flags = {k: flags.get(k) for k in want_flags}
    ctx.check(PLAN, r.status_code == 200 and got_flags == want_flags and lanes.get("tease_10") == ten
              and lanes.get("tease_50") == fifty and not (raw & (lanes.get("tease_10", set()) | lanes.get("tease_50", set())))
              and raw <= lanes.get("explicit_rest", set()),
              http=r.status_code, flags=got_flags, want_flags=want_flags,
              lanes={k: len(v) for k, v in lanes.items()},
              ten_diff=sorted(lanes.get("tease_10", set()) ^ ten)[:5],
              fifty_diff=sorted(lanes.get("tease_50", set()) ^ fifty)[:5],
              raw_in_paid=sorted(raw & (lanes.get("tease_10", set()) | lanes.get("tease_50", set())))[:5],
              raw_not_in_rest=sorted(raw - lanes.get("explicit_rest", set()))[:5])

    plan_members = {f["name"]: [it["media_id"] for it in f.get("items") or []] for f in folders}
    plan_scripts = {f["name"]: [it["media_id"] for it in f.get("items") or []]
                    for f in folders if f.get("source") == "script"}
    script_specs = {f["name"]: f for f in folders if f.get("source") == "script"}
    changes = plan.get("changes") or {}
    want_changes = {"create": len(folders) - 1, "keep": 1, "retire": 1, "retire_on_of": 1}
    stories_change = next((f.get("change") for f in folders if f["name"] == "AI-stories"), None)

    applied: list[dict] = []
    if ctx.app:
        phone: dict = {}
        async with ui.owner_browser(ctx, viewport=PHONE, touch=True) as page:
            try:
                await _open_extras(ctx, page, creator, pick=False)
                await page.get_by_text(re.compile(r"^\s*\S*\s*\d+ cached$")).first.wait_for(timeout=WAIT_MS)
                await page.wait_for_timeout(800)
                phone["build_visible"] = await page.get_by_role("button", name="Build AI folders", exact=True).is_visible()
                phone["drawer_shot"] = await ui.shot(ctx, page, "ai-folders-phone-drawer")
            except Exception as e:  # noqa: BLE001 — the check reports it
                phone["error"] = f"{type(e).__name__}: {e}"[:600]
                phone["failed_shot"] = await ui.shot(ctx, page, "failed-ai-folders-phone")
        ctx.check(PHONE_OFFERED, "error" not in phone and phone.get("build_visible") is True, ui=phone)

        desk: dict = {}
        async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
            with recorded(page, "POST", APPLY) as sent:
                try:
                    create = await _modal(ctx, page, creator, desk, "ai-folders-trigger")
                    if desk["create_enabled"]:
                        sw = page.get_by_role("switch", name="Also create on OnlyFans")
                        if await sw.get_attribute("aria-checked") == "true":
                            await sw.click(timeout=10_000)
                        desk["mirror_switch"] = await sw.get_attribute("aria-checked")
                        await create.click(timeout=10_000)
                        await page.get_by_role("button", name="Rebuild", exact=True).wait_for(timeout=WAIT_MS)
                        await page.get_by_text(re.compile(r"will create 0 · keep \d+ · retire 0")).first.wait_for(
                            timeout=WAIT_MS)
                        desk["settled_line"] = (await page.get_by_text(CHANGES).first.inner_text()).strip()
                        await page.wait_for_timeout(800)
                        desk["settled_shot"] = await ui.shot(ctx, page, "ai-folders-settled")
                except Exception as e:  # noqa: BLE001 — the check reports it
                    desk["error"] = f"{type(e).__name__}: {e}"[:600]
                    desk["failed_shot"] = await ui.shot(ctx, page, "failed-ai-folders")
                applied = list(sent)
        ctx.check(CREATE_ENABLED, _enabled_ok(desk, truth), ui=desk)
        body = (applied[0]["body"] or {}) if applied else {}
        ctx.check(CREATED, "error" not in desk and len(applied) == 1 and applied[0]["status"] == 200
                  and body.get("confirm") is True and body.get("mirror_to_of") is False
                  and int(body.get("keep") or 0) == 10 and not body.get("solo") and "settled_shot" in desk,
                  posts=applied, ui={k: v for k, v in desk.items() if not k.endswith("_shot")},
                  shots=[desk.get("trigger_shot"), desk.get("settled_shot")])
        want_line = (want_changes["create"], want_changes["keep"], want_changes["retire"])
        ctx.check(PREVIEW_SHOWN, "error" not in desk and _counts(desk.get("changes_line")) == want_line
                  and (desk.get("create_label") or "").endswith("· retire 1 linked to OnlyFans")
                  and _counts(desk.get("settled_line")) == (0, len(folders), 0),
                  changes_line=desk.get("changes_line"), want_line=want_line, create_label=desk.get("create_label"),
                  settled_line=desk.get("settled_line"), folders=len(folders),
                  shots=[desk.get("trigger_shot"), desk.get("settled_shot")])
    else:
        r = await ctx.owner.post(APPLY, json={"account_id": aid, "confirm": True, "keep": 10, "solo": False,
                                              "mirror_to_of": False})
        applied = [{"status": r.status_code, "body": None}]
        for name in (CREATE_ENABLED, PHONE_OFFERED, CREATED, PREVIEW_SHOWN):
            ctx.skip(name, "--no-ui")

    con = w.sql()
    try:
        rows = con.execute(
            "SELECT f.name, i.media_id, i.manual_order FROM vault_folders f JOIN vault_folder_items i "
            "ON i.folder_id = f.id WHERE f.account_id=? AND f.created_by=? AND f.deleted_at IS NULL "
            "ORDER BY f.name, i.manual_order", (aid, AI_CREATOR)).fetchall()
        live = dict(con.execute("SELECT name, id FROM vault_folders WHERE account_id=? AND created_by=? "
                                "AND deleted_at IS NULL", (aid, AI_CREATOR)).fetchall())
        gone = {n for (n,) in con.execute("SELECT name FROM vault_folders WHERE account_id=? AND created_by=? "
                                          "AND deleted_at IS NOT NULL", (aid, AI_CREATOR)).fetchall()}
    finally:
        con.close()
    made: dict[str, set[int]] = {}
    ordered: dict[str, list[int]] = {}
    for name, mid, _ in rows:
        made.setdefault(name, set()).add(int(mid))
        ordered.setdefault(name, []).append(int(mid))
    t10, t50, rest = made.get("AI-tease 10", set()), made.get("AI-tease 50", set()), made.get("AI-explicit 1:1", set())
    ctx.check(PAID_ONLY, bool(applied) and t10 == ten and t50 == fifty and not (raw & (t10 | t50)) and raw <= rest,
              folders={k: len(v) for k, v in made.items()}, ten_diff=sorted(t10 ^ ten)[:5],
              fifty_diff=sorted(t50 ^ fifty)[:5], raw_in_paid=sorted(raw & (t10 | t50))[:5],
              raw_not_in_rest=sorted(raw - rest)[:5])

    copy_ids, originals = set(copies), set(copies.values())
    plan_placed = {m for ids in plan_members.values() for m in ids}
    db_placed = {m for ids in made.values() for m in ids}
    ctx.check(NO_DUPES, bool(applied) and not (copy_ids & plan_placed) and not (copy_ids & db_placed)
              and originals <= plan_placed and originals <= db_placed
              and sorted(plan.get("dupes_collapsed") or []) == sorted(copy_ids),
              copies=len(copy_ids), copies_in_plan=sorted(copy_ids & plan_placed)[:5],
              copies_in_db=sorted(copy_ids & db_placed)[:5],
              folders_with_copy=sorted({n for n, ids in made.items() if copy_ids & ids})[:5],
              originals_missing=sorted(originals - db_placed)[:5],
              dupes_collapsed=len(plan.get("dupes_collapsed") or []))

    shoot, cl_name = truth["colourless"], truth["colourless_name"]
    ctx.check(COLOURLESS, plan_scripts.get(cl_name) == shoot and ordered.get(cl_name) == shoot,
              script=cl_name, plan_scripts=sorted(plan_scripts), plan=plan_scripts.get(cl_name),
              db=ordered.get(cl_name), want=shoot)

    big = truth["big_shoot"]
    bed_ids, bath_ids = set(big["bedroom"]), set(big["bathroom"])
    bed, bath = script_specs.get(big["names"]["bedroom"]) or {}, script_specs.get(big["names"]["bathroom"]) or {}
    bed_items, bath_items = bed.get("items") or [], bath.get("items") or []
    bed_got, bath_got = [it["media_id"] for it in bed_items], [it["media_id"] for it in bath_items]
    lent = [it for it in bath_items if it.get("borrowed")]
    ctx.check(SCRIPTS_CAPPED, bool(applied) and 3 <= len(bed_got) <= 10 and set(bed_got) <= bed_ids
              and any(h.startswith("capped from ") for h in bed.get("health") or [])
              and len(lent) == 1 and bath_items[-1:] == lent and lent[0]["media_id"] in bed_ids - set(bed_got)
              and lent[0].get("closes") is True and set(bath_got[:-1]) <= bath_ids
              and "borrowed closer" in (bath.get("health") or [])
              and all(isinstance(f.get("health"), list) for f in script_specs.values())
              and ordered.get(big["names"]["bedroom"]) == bed_got and ordered.get(big["names"]["bathroom"]) == bath_got,
              names=big["names"], scripts=sorted(script_specs), bedroom=bed_got, bedroom_health=bed.get("health"),
              bathroom=bath_got, bathroom_health=bath.get("health"), borrowed=[it["media_id"] for it in lent],
              db_bedroom=ordered.get(big["names"]["bedroom"]), db_bathroom=ordered.get(big["names"]["bathroom"]))

    got_changes = {k: changes.get(k) for k in want_changes}
    retired_names = [x.get("name") for x in changes.get("retired") or []]
    ctx.check(PREVIEW, got_changes == want_changes and retired_names == ["AI-old lane"] and stories_change == "keep"
              and bool(applied) and "AI-old lane" in gone and "AI-old lane" not in live
              and live.get("AI-stories") == truth["kept_folder"]["AI-stories"],
              changes=got_changes, want=want_changes, retired=retired_names, stories_change=stories_change,
              db_live_stories=live.get("AI-stories"), seeded_stories=truth["kept_folder"]["AI-stories"],
              db_gone=sorted(gone))
    (ctx.out / "ai-folders.json").write_text(json.dumps(
        {"truth": truth, "plan_flags": flags, "plan_changes": changes, "lanes": {k: sorted(v) for k, v in lanes.items()},
         "made": {k: sorted(v) for k, v in made.items()}, "applied": applied}, default=str, indent=1))
