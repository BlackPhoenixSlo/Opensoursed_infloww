"""Vault Pro > Extras > "Build AI folders" > "Topic folders (Jev)" (app/components/vault/VaultAiFoldersModal.tsx,
service/vault_topic_folders.py, vault_scripts.plan_ai_folders(topics=) / apply_ai_folders): opt-in folders per
ticked topic and price (`AI-<name> free/$10/$50/$100` by Jev's lane5), read from `ai_fields_json["_jev"]` only,
photos only, on top of the lanes and scripts. None ticked = today's build; unticking retires; free never holds an
item Jev saw bare or was unsure about. The "Feet" group (slug `feet`, off unless ticked): AI-feet tease / nude /
nude-body, the feet pack's preselect rung (vault_pack_picker.jev_pick: Jev feet score >= .6); tease obeys the free
guard.

World: `agency_inbox`; Creator 0's vault by SQL (seed/vault_topic_folders.py, `vault_topic_items` 150 / 600 /
2,000): one-topic hits at every (topic, allowed price), guarded free-lane items (bare "unsure" / "y"), free-only
topics at paid lanes and toy play at free, review, stale / failed Jev, no Jev, a clip, and feet photos (tease / nude /
nude-body / at the .6 gate / .59 / free-but-unsure). Thumbs are small PNGs in the run's still store.

Stages:
  plan   (also --no-ui) GET /admin/vault-ai/folder-plan without topics, with all 18, with bikini + spread, with
         feet only, and with an unknown slug; POST .../apply with an unknown slug.
  desk   (UI) 1440x900: Extras > Build AI folders; the topic section's coverage line, nothing ticked; tick
         "bikini" and "spread", wait for the re-plan, screenshot `topic-folders-trigger`; "Also create on
         OnlyFans" off; Create; settles on Rebuild ("will create 0 · ... · retire 0"), screenshot
         `topic-folders-settled`. --no-ui: the same apply via POST {confirm, keep 2, topics [bikini, spread],
         mirror_to_of false}.
  untick (also --no-ui) GET the plan with bikini only (spread's folders in `retired`), POST apply with it.

Checks (lib/vault_topic_folders_faults.py names):
  topic_folders_off_by_default         no topics: no `topic` folder, `topics` []; the lanes / scripts with all 18
                                       ticked == without (names and members: additive); `jev` == {enabled true,
                                       photos, with_jev} from SQL; 19 entries in `topic_catalogue` (18 + feet).
  topic_folders_unknown_422            GET and POST with `nope`: 422 {error unknown_topics, unknown [nope]}.
  topic_folders_plan_exact             all 18: topic folder names == the planted hits' names; every hit in exactly
                                       its folder; wrong-price, review, stale, failed, no-Jev, clip in none.
  topic_folders_free_guard             plan (all 18) AND DB: no `free` topic folder holds an item whose planted
                                       bare answers are not all "n"; guarded items in no topic folder; catalogue
                                       counts == planted hits per (general) topic.
  topic_folders_apply_equals_preview   DB after the bikini + spread apply: live topic folders == the preview's
                                       (names and members), no other topic folder live.
  topic_feet_folders                   feet only: exactly AI-feet tease / nude / nude-body, members == the planted
                                       feet rows (.6 in, .59 out); tease holds no item with a bare / unsure answer;
                                       feet rows in no general topic; catalogue feet {group feet, count planted}.
  topic_folders_ticked_from_ui         desk: coverage line "<with_jev> of <photos> photos have Jev data", 0 of 19
                                       ticked at open, one apply POST 200 {topics [bikini, spread], mirror_to_of false},
                                       settled on Rebuild, both screenshots.
  topic_folders_untick_retires         the bikini-only preview retires exactly spread's folders; DB after: those
                                       soft-deleted, bikini's the same live rows.

Bypasses (declared): the vault and its Jev answers are SQL as the Jev pass leaves them (no OF, TypeSafe, NudeNet,
LLM); Jev switched on by SQL (the Extras toggle's column); thumbs written by the harness into the run's still store;
"Also create on OnlyFans" switched off (the OF list writes are not modelled); collector off. No volume: --users
and --scale only resize the vault.
Break-it-once: vault-topics-free-guard-off (default; server: `vault_topic_folders.free_ok` always true:
topic_folders_free_guard), --fault=ai-feet-tease-free-guard-off (server: lane5 free trusted by both the picker's
`jev_tier` and `free_ok`: topic_feet_folders).
"""
from __future__ import annotations

import json
import re

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import picture_bytes
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_topic_folders_faults import (APPLIED, FEET, FREE_GUARD, OFF_BY_DEFAULT, PLAN, RETIRE,
                                                 UI_TICKED, UNKNOWN_422)
from slop.lib.vault_ui import TOURS_SEEN
from slop.seed import vault_topic_folders

PROFILE = "agency_inbox"
UI = True
FAULT = "vault-topics-free-guard-off"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
VIEWPORT = (1440, 900)
WAIT_MS = 120_000
PLAN_URL = "/admin/vault-ai/folder-plan"
APPLY = "/admin/vault-ai/folder-plan/apply"
PICK = ["bikini", "spread"]
CREATE = re.compile(r"^Create \d+ folders( · retire \d+ linked to OnlyFans)?$")
COVERAGE = re.compile(r"(\d+) of (\d+) photos have Jev data")
AI_CREATOR = "vault_ai_script"   # vault_scripts.AI_FOLDER_CREATOR
ALL = list(vault_topic_folders.TOPICS)   # the 18 general topics; the Feet group's `feet` slug is apart
FEET_SLUG = vault_topic_folders.FEET
CATALOGUE_N = len(ALL) + 1


def _members(folders: list[dict], topic: bool) -> dict[str, list[int]]:
    return {f["name"]: [it["media_id"] for it in f.get("items") or []]
            for f in folders if (f.get("source") == "topic") == topic}


def _topic_name(name: str, slugs) -> bool:
    return any(name.startswith(f"AI-{vault_topic_folders.TOPICS[s][0]} ") for s in slugs)


def _db(w, aid: str) -> tuple[dict[str, set[int]], dict[str, int], set[str]]:
    con = w.sql()
    try:
        rows = con.execute(
            "SELECT f.name, i.media_id FROM vault_folders f JOIN vault_folder_items i ON i.folder_id = f.id "
            "WHERE f.account_id=? AND f.created_by=? AND f.deleted_at IS NULL", (aid, AI_CREATOR)).fetchall()
        live = dict(con.execute("SELECT name, id FROM vault_folders WHERE account_id=? AND created_by=? "
                                "AND deleted_at IS NULL", (aid, AI_CREATOR)).fetchall())
        gone = {n for (n,) in con.execute("SELECT name FROM vault_folders WHERE account_id=? AND created_by=? "
                                          "AND deleted_at IS NOT NULL", (aid, AI_CREATOR)).fetchall()}
    finally:
        con.close()
    made: dict[str, set[int]] = {}
    for name, mid in rows:
        made.setdefault(name, set()).add(int(mid))
    return made, live, gone


async def _plan(ctx, aid: str, topics: list[str]) -> tuple[int, dict]:
    q = f"&topics={','.join(topics)}" if topics else ""
    r = await ctx.owner.get(f"{PLAN_URL}?account_id={aid}&keep=2{q}")
    return r.status_code, (r.json() if r.status_code == 200 else {})


async def _desk(ctx, page, creator: dict, got: dict) -> None:
    await page.context.add_init_script(TOURS_SEEN)
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
    await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=WAIT_MS)
    await page.get_by_role("button", name="Build AI folders", exact=True).click(timeout=WAIT_MS)
    section = page.get_by_test_id("ai-folders-topics")
    cov = section.get_by_text(COVERAGE).first
    await cov.wait_for(timeout=WAIT_MS)
    got["coverage"] = (await cov.inner_text()).strip()
    boxes = section.get_by_role("checkbox")
    await boxes.first.wait_for(timeout=WAIT_MS)
    got["boxes"] = await boxes.count()
    got["ticked_at_open"] = sum([await boxes.nth(i).is_checked() for i in range(got["boxes"])])
    for slug in PICK:
        await section.get_by_role("checkbox", name=re.compile(rf"^{re.escape(vault_topic_folders.TOPICS[slug][0])}\b")
                                  ).check(timeout=10_000)
    await page.get_by_text(re.compile(r"\d+ topic\)")).first.wait_for(timeout=WAIT_MS)   # the re-plan landed
    create = page.get_by_role("button", name=CREATE)
    await create.wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(800)
    got["trigger_shot"] = await ui.shot(ctx, page, "topic-folders-trigger")
    sw = page.get_by_role("switch", name="Also create on OnlyFans")
    if await sw.get_attribute("aria-checked") == "true":
        await sw.click(timeout=10_000)
    await create.click(timeout=10_000)
    await page.get_by_role("button", name="Rebuild", exact=True).wait_for(timeout=WAIT_MS)
    await page.get_by_text(re.compile(r"will create 0 · keep \d+ · retire 0")).first.wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(800)
    got["settled_shot"] = await ui.shot(ctx, page, "topic-folders-settled")


async def run(ctx):
    w = ctx.world
    await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    aid = creator["id"]
    truth = vault_topic_folders.seed(w, creator, int(ctx.param("items", w.size["vault_topic_items"])))
    want: dict[int, str] = {int(k): v for k, v in truth["want"].items()}
    none = {cls: set(ids) for cls, ids in truth["none"].items()}
    bare = set(truth["bare"])
    thumbs = stills_dir(ctx.stack.tmp) / "thumbs" / aid
    thumbs.mkdir(parents=True, exist_ok=True)
    feet_truth = {int(k): v for k, v in truth["feet"].items()}
    for mid in [*want, *(m for ids in none.values() for m in ids), *feet_truth]:
        (thumbs / f"{mid}.jpg").write_bytes(picture_bytes(f"topic/{mid}"))
    ctx.note(f"Creator {aid}: {truth['photos']} photos ({truth['with_jev']} with current Jev), {len(want)} hits "
             f"in {len(truth['want_names'])} folders; none: {({k: len(v) for k, v in none.items()})}")

    # ── plan ──
    s0, off = await _plan(ctx, aid, [])
    s1, every = await _plan(ctx, aid, ALL)
    s2, picked = await _plan(ctx, aid, PICK)
    lanes_off, lanes_all = _members(off.get("folders") or [], False), _members(every.get("folders") or [], False)
    want_jev = {"enabled": True, "photos": truth["photos"], "with_jev": truth["with_jev"]}
    ctx.check(OFF_BY_DEFAULT, s0 == s1 == 200 and not _members(off.get("folders") or [], True)
              and off.get("topics") == [] and lanes_off == lanes_all and off.get("jev") == want_jev
              and len(off.get("topic_catalogue") or []) == CATALOGUE_N,
              http=[s0, s1], topics=off.get("topics"), jev=off.get("jev"), want_jev=want_jev,
              topic_folders_off=sorted(_members(off.get("folders") or [], True)),
              lanes_differ=sorted(n for n in set(lanes_off) | set(lanes_all) if lanes_off.get(n) != lanes_all.get(n)),
              catalogue=len(off.get("topic_catalogue") or []))

    r = await ctx.owner.get(f"{PLAN_URL}?account_id={aid}&keep=2&topics=bikini,nope")
    rp = await ctx.owner.post(APPLY, json={"account_id": aid, "confirm": True, "keep": 2, "topics": ["nope"],
                                           "mirror_to_of": False})
    bodies = [(x.json() or {}).get("detail") if x.status_code == 422 else None for x in (r, rp)]
    want_422 = {"error": "unknown_topics", "unknown": ["nope"]}
    ctx.check(UNKNOWN_422, r.status_code == rp.status_code == 422 and all(
        {k: (b or {}).get(k) for k in want_422} == want_422 for b in bodies),
        http=[r.status_code, rp.status_code], bodies=bodies)

    topic_all = _members(every.get("folders") or [], True)
    where: dict[int, list[str]] = {}
    for name, ids in topic_all.items():
        for m in ids:
            where.setdefault(m, []).append(name)
    misplaced = {m: (where.get(m), n) for m, n in want.items() if where.get(m) != [n]}
    nowhere = {cls: sorted(ids & set(where)) for cls, ids in none.items() if cls != "guard" and ids & set(where)}
    ctx.check(PLAN, s1 == 200 and sorted(topic_all) == truth["want_names"] and not misplaced and not nowhere,
              names_extra=sorted(set(topic_all) - set(truth["want_names"])),
              names_missing=sorted(set(truth["want_names"]) - set(topic_all)),
              misplaced=dict(list(misplaced.items())[:5]), in_topic_but_should_not=nowhere,
              hits=len(want), topic_folders=len(topic_all))

    # ── the Feet group: three AI-feet folders, the pack picker's preselect rungs ──
    s4, feetp = await _plan(ctx, aid, [FEET_SLUG])
    feet_plan = {n: sorted(ids) for n, ids in _members(feetp.get("folders") or [], True).items()}
    want_feet: dict[str, list[int]] = {}
    for m, n in feet_truth.items():
        if n:
            want_feet.setdefault(n, []).append(m)
    want_feet = {n: sorted(v) for n, v in want_feet.items()}
    unsafe = set(bare) | set(truth["feet_unsafe"])
    tease_unsafe = sorted(set(feet_plan.get("AI-feet tease") or []) & unsafe)
    feet_cat = next((t for t in off.get("topic_catalogue") or [] if t.get("slug") == FEET_SLUG), {})
    feet_in_topics = sorted(set(feet_truth) & set(where))
    ctx.check(FEET, s4 == 200 and sorted(feet_plan) == sorted(vault_topic_folders.FEET_NAMES)
              and feet_plan == want_feet and not tease_unsafe and not feet_in_topics
              and feet_cat.get("group") == "feet" and feet_cat.get("count") == sum(len(v) for v in want_feet.values()),
              http=s4, names=sorted(feet_plan), counts={n: len(v) for n, v in feet_plan.items()},
              want_counts={n: len(v) for n, v in want_feet.items()},
              differ={n: sorted(set(feet_plan.get(n, [])) ^ set(want_feet.get(n, [])))[:5]
                      for n in set(feet_plan) | set(want_feet) if feet_plan.get(n) != want_feet.get(n)},
              unsafe_in_tease=tease_unsafe[:5], feet_in_general_topics=feet_in_topics[:5],
              catalogue=feet_cat)

    # ── apply bikini + spread (UI, else the same POST) ──
    applied: list[dict] = []
    desk: dict = {}
    if ctx.app:
        async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
            with recorded(page, "POST", APPLY) as sent:
                try:
                    await _desk(ctx, page, creator, desk)
                except Exception as e:  # noqa: BLE001 — the check reports it
                    desk["error"] = f"{type(e).__name__}: {e}"[:600]
                    desk["failed_shot"] = await ui.shot(ctx, page, "failed-topic-folders")
                applied = list(sent)
        body = (applied[0]["body"] or {}) if applied else {}
        m = COVERAGE.search(desk.get("coverage") or "")
        ctx.check(UI_TICKED, "error" not in desk and bool(m)
                  and (int(m.group(1)), int(m.group(2))) == (truth["with_jev"], truth["photos"])
                  and desk.get("ticked_at_open") == 0 and desk.get("boxes") == CATALOGUE_N
                  and len(applied) == 1 and applied[0]["status"] == 200 and body.get("confirm") is True
                  and sorted(body.get("topics") or []) == sorted(PICK) and body.get("mirror_to_of") is False
                  and "settled_shot" in desk,
                  posts=applied, ui={k: v for k, v in desk.items() if not k.endswith("_shot")},
                  shots=[desk.get("trigger_shot"), desk.get("settled_shot")])
    else:
        rp = await ctx.owner.post(APPLY, json={"account_id": aid, "confirm": True, "keep": 2, "solo": False,
                                               "topics": PICK, "mirror_to_of": False})
        applied = [{"status": rp.status_code, "body": None}]
        ctx.skip(UI_TICKED, "--no-ui")

    made, live, _ = _db(w, aid)
    topic_picked = {n: set(ids) for n, ids in _members(picked.get("folders") or [], True).items()}
    topic_db = {n: ids for n, ids in made.items() if _topic_name(n, ALL)}
    ctx.check(APPLIED, s2 == 200 and bool(applied) and applied[0]["status"] == 200 and bool(topic_picked)
              and topic_db == topic_picked and all(_topic_name(n, PICK) for n in topic_picked),
              preview={n: len(v) for n, v in topic_picked.items()}, db={n: len(v) for n, v in topic_db.items()},
              differ=sorted(n for n in set(topic_db) | set(topic_picked) if topic_db.get(n) != topic_picked.get(n)))

    free_plan = {n: set(ids) & bare for n, ids in topic_all.items() if n.endswith(" free")}
    free_db = {n: ids & bare for n, ids in topic_db.items() if n.endswith(" free")}
    guard = none.get("guard", set())
    counts = {t["slug"]: t["count"] for t in off.get("topic_catalogue") or []}
    want_counts = {s: sum(1 for n in want.values() if _topic_name(n, [s])) for s in ALL}
    ctx.check(FREE_GUARD, not any(free_plan.values()) and not any(free_db.values()) and bool(guard)
              and not (guard & set(where)) and not (guard & {m for ids in topic_db.values() for m in ids})
              and {s: counts.get(s) for s in ALL} == want_counts,
              bare_in_free_plan={n: sorted(v)[:5] for n, v in free_plan.items() if v},
              bare_in_free_db={n: sorted(v)[:5] for n, v in free_db.items() if v},
              guarded_placed=sorted(guard & set(where))[:5],
              counts_differ={s: (counts.get(s), want_counts[s]) for s in ALL if counts.get(s) != want_counts[s]})

    # ── untick spread ──
    s3, one = await _plan(ctx, aid, ["bikini"])
    retired = sorted(x.get("name") for x in (one.get("changes") or {}).get("retired") or [])
    spread_names = sorted(n for n in topic_db if _topic_name(n, ["spread"]))
    bikini_ids = {n: live.get(n) for n in topic_db if _topic_name(n, ["bikini"])}
    rp = await ctx.owner.post(APPLY, json={"account_id": aid, "confirm": True, "keep": 2, "solo": False,
                                           "topics": ["bikini"], "mirror_to_of": False})
    _, live2, gone2 = _db(w, aid)
    ctx.check(RETIRE, s3 == 200 and rp.status_code == 200 and bool(spread_names) and retired == spread_names
              and set(spread_names) <= gone2 and not (set(spread_names) & set(live2))
              and all(live2.get(n) == fid for n, fid in bikini_ids.items()) and bool(bikini_ids),
              http=[s3, rp.status_code], retired=retired, want=spread_names,
              still_live=sorted(set(spread_names) & set(live2)),
              bikini_before=bikini_ids, bikini_after={n: live2.get(n) for n in bikini_ids})

    (ctx.out / "topic-folders.json").write_text(json.dumps(
        {"truth": truth, "plan_all": topic_all, "plan_picked": {n: sorted(v) for n, v in topic_picked.items()},
         "db": {n: sorted(v) for n, v in topic_db.items()}, "feet_plan": feet_plan,
         "retired": retired, "applied": applied}, default=str, indent=1))
