"""Vault Pro > Extras > "Feet pack" (app/components/vault/VaultPackPickerModal.tsx + packPickerState.ts,
service/vault_pack_picker.candidates / triage): PRECISION ONLY. The queue is exactly the Jev v8 photos
(`_jev.status` ok) that see the feet at score >= FEET_PRESELECT_SCORE (.6), most likely first; nothing else (no
lower-scored row, no describe-word row without Jev, no video: filing one is 400 feet_photos_only). Items already
on a rung come back out of the queue. Each is prefilled from `_jev` alone (lane5 + body answers -> tier, feet_detail
-> covering; an unknown tier never prefilled), and the keyboard files the queue: Enter confirms the prefill, x
rejects, 1/2/3 pick a rung. On a 390px phone the grid is two columns of 44px taps. The free rung (tease) is
refused, server (400 not_free_safe) and UI (disabled), unless Jev filed it free with every body answer "n". A
candidate with a known, safe prefill arrives PRESELECTED (`preselect` true, tile ticked); "File N preselected"
files every ticked tile on its rung in one triage.

World: `agency_inbox`; Creator 0's vault by SQL (seed/vault_feet.py, `vault_feet_items` 300 / 2,000 / 12,000):
keepers = the confident Jev photos (Jev-measured / Jev free / Jev $50 over qwen-covered / Jev free-but-unsure-breasts
+ Jev review (unsafe) / Jev soles with no feet word) mixed with feet photos Jev has not classified (every describe
word and flag says feet), a Jev half-sure .55, a confident Jev feet CLIP, what the old LIKE query also returned
(bystander, text mention, ambiguous payoff-act, Jev-measured-no, Jev-says-not-in-picture) and filler, media ids
shuffled across classes; ~8% of keepers already on `feet-nude`, one unsafe (Jev unsure) + one free-safe Jev keeper
already on `feet-tease` (pre-guard), one no-Jev photo + one clip on `feet-nude` (pre-rule). Every LIKE-set item's
and keeper's full image is a small PNG in the run's still store (lib/vault_collect_relay.py's dirs), so tiles draw
pictures.

Stages:
  rank   (also --no-ui) GET /admin/vault-ai/pack-candidates?limit=2000 by the owner, 5 times (latency).
  desktop (UI) 1440x900: Extras > Feet pack, screenshot `feet-picker-trigger`; click the first tile; Enter x3, x,
        1 (no verdict when tile 5 is not free-safe); screenshot; Save; settles on "Saved", screenshot
        `feet-picker-settled`; scroll to an unsafe Jev tile
        (not one of the five keyed), screenshot `feet-picker-jev-guard`.
  phone (UI) 390x844 touch: Vault Pro on the Creator (last pick, localStorage), Extras > Feet pack; screenshot
        `feet-picker-phone-trigger`; tap the first tile's "nude"; Save; screenshot `feet-picker-phone-settled`.
  preselect (UI; --no-ui: the API flags only) 1440x900, fresh: Extras > Feet pack; read every tick; untick one
        free-safe tile; screenshot `feet-preselect-trigger`; "File N preselected"; settles on "filed N (0 rejected)",
        screenshot `feet-preselect-settled`.
  guard  (also --no-ui; last, so a leak cannot touch the other checks) POST pack-triage [an unsafe Jev keeper ->
        tease, a free-safe Jev keeper -> nude]; POST /admin/vault-ai/folders/<feet-tease>/publish (OF's list side:
        lib/vault_relay.py, `of-vault.json` written); POST .../folders/<feet-nude>/publish (the pre-rule clip skipped).

Checks (lib/vault_feet_picker_faults.py names):
  feet_ranked_above_like_baseline   the unfiled queue's set == the seeded unfiled keepers (precision only: nothing
                                    else); precision@N (N = unfiled keepers) >= PRECISION_MIN and >= the old
                                    query's (LIKE, media_id order; the seeder's oracle) + LIFT_MIN; no pre-filed
                                    item in the queue, each (pre-rule clip + no-Jev photo too) back with its rung.
  feet_prefill_matches_flags        every unfiled keeper's (suggested, tier) == the seeded class's; no non-keeper
                                    prefilled.
  feet_no_free_prefill_without_tier no queue item with tier None or free_ok false is prefilled on the free rung
                                    (tease); the seeded unknown-tier keepers (Jev unsure / review) are in the queue
                                    with tier None.
  feet_jev_selects_and_ranks        the Jev soles rows (no feet word) are in the queue; the no-Jev feet photos, the
                                    Jev .55, measured-no, not-in-picture rows and the feet clips are not; the queue
                                    is score-sorted, every row jev true, kind photo, score >= .6; filing a clip
                                    (unfiled) on nude is 400 feet_photos_only naming it, feet-* members unchanged.
  feet_jev_free_guard               the unsafe Jev keepers are in the queue with tier None, free_ok false (the
                                    free-safe Jev keepers free_ok true); the guard POST is 400
                                    not_free_safe naming the unsafe item, feet-* members unchanged (atomic); UI:
                                    that tile shows the Jev badge, tease disabled, nude enabled. The pre-filed
                                    unsafe tease row (and only it) comes back `unsafe_on_free`; publishing
                                    feet-tease is 200 with `skipped_unsafe` == it, and OF's list gets the free-safe
                                    one, never it. Publishing feet-nude is 200 with `skipped_videos` == the pre-rule
                                    clip, never on its OF list (`pushed` == that list's size).
  feet_keyboard_confirm_members     desktop: >= 1 of tiles 1-3 showed a prefill; one triage POST (200) of exactly
                                    the keyed verdicts (tiles 1-3 the prefill they showed, none if none, tile 4
                                    rejected, tile 5 tease unless free_ok false); DB: the feet-* folders' members
                                    == those + the pre-filed, nothing else.
  feet_phone_layout_tap_save        phone: the Extras drawer shows every tool (none desk-only), screenshot
                                    `extras-drawer-phone`; 2 grid columns, rung + reject buttons >= 44px tall, no horizontal
                                    overflow; one POST [{tile, nude}] (200); DB: that tile on feet-nude only.
  feet_preselect_confirm            the API's preselect set == the seeded PRESELECT keepers not pre-filed, each
                                    suggested on its class's rung; UI: the ticked tiles == those not yet filed (of
                                    the grid's top 600); after one untick, the button says File <rest>, one triage
                                    POST (200) of exactly the rest at their rungs; DB: the feet-* members == before
                                    + those.
  feet_candidates_p95 [budget]      the route's p95 over the 5 reads <= CANDS_P95_MS[scale].

Bypasses (declared): the vault is SQL as Collect + describe + flags leave it (no OF, no LLM); full images written by
the harness into the run's temp still store; the background collector off (VAULT_COLLECT_ENABLED=0); Publish not
pressed in the UI: feet-tease is published by API, OF's list side lib/vault_relay.py's in-process fake. No volume: --scale only resizes the vault.
Break-it-once: feet-rank-like-only (default; server: every Jev score 1, so every Jev photo that sees feet is a
candidate, the .55 / measured-no rows prefilled and preselected: ranked + prefill + jev rank + preselect), --fault=feet-free-prefill-unknown-tier
(server: an unknown Jev tier prefilled from its covering, socks -> the free rung: no-free + prefill + preselect),
--fault=feet-keys-enter-ignores-suggestion (client: Enter only moves: keyboard), --fault=feet-jev-free-guard-off
(server: Jev lane5 free trusted over unsure body answers: jev free guard + prefill),
--fault=feet-preselect-threshold-low (server: Jev gate 0.3, the .55 rows candidates, prefilled and preselected:
preselect + prefill + ranked + jev rank).
"""
from __future__ import annotations

import json
import re
import time

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import picture_bytes
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_feet_picker_faults import (JEV_FREE_GUARD, JEV_RANK, KEYS, NO_FREE, PHONE, PREFILL, PRESELECT,
                                              RANKED)
from slop.lib.vault_ui import TOURS_SEEN
from slop.seed import vault_feet

PROFILE = "agency_inbox"
UI = True
FAULT = "feet-rank-like-only"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
VIEWPORT, PHONE_VP = (1440, 900), (390, 844)
WAIT_MS = 120_000
CANDS, TRIAGE = "/admin/vault-ai/pack-candidates", "/admin/vault-ai/pack-triage"
PRECISION_MIN, LIFT_MIN = 0.9, 0.2
ENTERS = 3   # Enter x3, then x, then 1
CANDS_P95_MS = {"small": 400, "medium": 800, "huge": 2_000}   # one read, every Jev feet photo scored (12k vault: ~80 ms in-process)
TAP_MIN_PX = 44
P95_CHECK = "feet_candidates_p95"
SUGGESTED = re.compile(r", suggested (\S+)$")
SAVE = re.compile(r"^Save \d+$")
FREE_RUNG = "tease"   # vault_pack_picker feet rungs[0]: rides free as the preview
GATE = 0.6   # vault_pack_picker.FEET_PRESELECT_SCORE: the candidate gate
JEV_OUT = ("jev_maybe", "measured_no", "jev_absent")   # Jev photos that are no candidate (score / not seen)
JEV_SAFE = ("measured", "jev_free")   # Jev lane5 free, every body answer "n"
FILE = re.compile(r"^File \d+ preselected$")
FILED_NOTE = re.compile(r"^filed \d+ \(\d+ rejected\)$")


EXTRAS_TOOLS = ["Re-collect", "Describe all", "Harvest OF", "Duplicates", "Feet pack", "Build AI folders"]


async def _open_picker(ctx, page, creator: dict, *, pick: bool = True, drawer: dict | None = None) -> list[dict]:
    """Vault Pro > the Creator > Extras > Feet pack; the grid's tiles in order [{id, label}]. `pick` False (phone:
    the creator column is off-canvas) opens on the Creator Vault Pro last had (localStorage `vault.accountId`)."""
    await page.context.add_init_script(TOURS_SEEN + ("" if pick else
                                       f"localStorage.setItem('vault.accountId', '{creator['id']}');"))
    await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
    if pick:
        await ui.pick_creator(page, creator["nickname"], timeout_ms=WAIT_MS)
    await page.get_by_role("button", name=re.compile(r" extras$")).first.click(timeout=WAIT_MS)
    if drawer is not None:   # every Extras tool shows at this width (none desk-only)
        await page.get_by_role("button", name="Feet pack", exact=True).wait_for(timeout=WAIT_MS)
        box = page.get_by_role("dialog", name=re.compile(r" extras$"))
        drawer["visible"] = [n for n in EXTRAS_TOOLS
                             if await box.get_by_role("button", name=re.compile("^" + re.escape(n))).first.is_visible()]
        await page.wait_for_timeout(600)   # the sheet's slide-in settles
        drawer["shot"] = await ui.shot(ctx, page, "extras-drawer-phone")
    await page.get_by_role("button", name="Feet pack", exact=True).click(timeout=WAIT_MS)
    await page.locator("[data-pack-tile]").first.wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(800)   # first images drawn
    return await _tiles(page)


async def _tiles(page) -> list[dict]:
    return await page.locator("[data-pack-tile]").evaluate_all(
        "els => els.map(e => ({id: Number(e.dataset.packTile), label: e.getAttribute('aria-label')}))")


def _shown_suggestion(label: str | None) -> str | None:
    """The prefill a tile showed, from its aria-label ("media <id>, suggested <rung>")."""
    m = SUGGESTED.search(label or "")
    return m.group(1) if m else None


async def _save(page) -> None:
    """Save (the POST's body is the verdict oracle, not the button's count), then wait for "Saved"."""
    await page.get_by_role("button", name=SAVE).click(timeout=10_000)
    await page.get_by_role("button", name="Saved", exact=True).wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(500)


def _members(w, aid: str) -> dict[str, set[int]]:
    con = w.sql()
    try:
        rows = con.execute(
            "SELECT f.name, i.media_id FROM vault_folders f JOIN vault_folder_items i ON i.folder_id = f.id "
            "WHERE f.account_id=? AND f.name LIKE 'feet-%' AND f.deleted_at IS NULL", (aid,)).fetchall()
    finally:
        con.close()
    out: dict[str, set[int]] = {}
    for name, mid in rows:
        out.setdefault(name, set()).add(int(mid))
    return out


async def _free_guard(ctx, w, aid: str, queue: list[dict], unsafe_ids: set[int], unsafe_q: list[dict],
                      safe_ids: set[int], guard_ui: dict | None, by_id: dict[int, dict], truth: dict) -> dict:
    """`feet_jev_free_guard`: the unsafe Jev keepers come back unprefilled and not free-safe, and a triage putting
    one on the free rung (beside a free-safe one on nude) is refused whole; the pre-filed unsafe tease row is
    flagged and publishing feet-tease skips it (OF's list never gets it). Runs last: a leak writes."""
    safe_q = [c for c in queue if c["media_id"] in safe_ids]
    # The prefill is feet_no_free_prefill_without_tier's (free_ok false never on tease) + the prefill check's.
    flags_bad = [(c["media_id"], c.get("tier"), c.get("free_ok")) for c in unsafe_q
                 if c.get("tier") is not None or c.get("free_ok") is not False]
    safe_bad = [c["media_id"] for c in safe_q if c.get("free_ok") is not True]
    before = _members(w, aid)
    held = set().union(*before.values()) if before else set()
    target = unsafe_q[0]["media_id"] if unsafe_q else None
    buddy = next((c["media_id"] for c in safe_q if c["media_id"] not in held), None)
    verdicts = [{"media_id": target, "rung": FREE_RUNG}] + ([{"media_id": buddy, "rung": "nude"}] if buddy else [])
    r = None
    if target is not None:
        r = await ctx.owner.post(TRIAGE, json={"account_id": aid, "category": "feet", "verdicts": verdicts})
    status = getattr(r, "status_code", None)
    try:
        detail = (r.json() or {}).get("detail") if r is not None else None
    except ValueError:
        detail = None
    after = _members(w, aid)
    refused = (status == 400 and isinstance(detail, dict) and detail.get("error") == "not_free_safe"
               and detail.get("media_ids") == [target] and detail.get("rung") == FREE_RUNG)
    ui_ok = guard_ui is None or ("error" not in guard_ui and guard_ui.get("tile") is not None
                                 and guard_ui.get("badge") and guard_ui.get("tease_disabled")
                                 and guard_ui.get("nude_enabled") and "shot" in guard_ui)
    # The pre-guard free rung: flagged in candidates, skipped by its publish, never on OF's list.
    flagged = sorted(m for m, c in by_id.items() if c.get("unsafe_on_free"))
    con = w.sql()
    try:
        fid = {n: i for n, i in con.execute(
            "SELECT name, id FROM vault_folders WHERE account_id=? AND name IN (?, ?) AND deleted_at IS NULL",
            (aid, f"feet-{FREE_RUNG}", vault_feet.FILED_FOLDER)).fetchall()}
    finally:
        con.close()

    async def publish(name: str):
        r = (await ctx.owner.post(f"/admin/vault-ai/folders/{fid[name]}/publish", json={"account_id": aid})
             if name in fid else None)
        return r, (r.json() if r is not None and r.status_code == 200 else {})

    def on_list(of: dict, body: dict) -> list[int]:
        lid = body.get("of_list_id")
        return sorted({int(x) for c in of.get("lists") or [] if c["list_id"] == lid for x in c["media_ids"]})

    pub, pub_body = await publish(f"feet-{FREE_RUNG}")
    # The pre-rule clip on feet-nude: skipped by its publish (a pack is photos only), never on OF's list.
    npub, npub_body = await publish(vault_feet.FILED_FOLDER)
    of = (await ctx.owner.get("/__slop/vault/fake")).json()
    on_of, on_nude = on_list(of, pub_body), on_list(of, npub_body)
    free_unsafe, free_safe = truth["free_unsafe"], truth["free_safe"]
    clip = sorted(set(truth["pre_rule"]) & set(truth["classes"]["jev_video"]))
    publish_ok = (bool(free_unsafe) and flagged == free_unsafe and getattr(pub, "status_code", None) == 200
                  and pub_body.get("skipped_unsafe") == free_unsafe and not set(on_of) & set(free_unsafe)
                  and set(free_safe) <= set(on_of)
                  and bool(clip) and getattr(npub, "status_code", None) == 200
                  and npub_body.get("skipped_videos") == clip and not set(on_nude) & set(clip)
                  and npub_body.get("pushed") == len(on_nude))
    out = {"unsafe_ids": len(unsafe_ids), "unsafe_in_queue": len(unsafe_q), "flags_bad": flags_bad[:5],
           "free_rung": {"seeded_unsafe": free_unsafe, "seeded_safe": free_safe, "flagged": flagged[:5],
                         "publish_http": getattr(pub, "status_code", None),
                         "skipped_unsafe": pub_body.get("skipped_unsafe"), "on_of": on_of[:10]},
           "pre_rule_clip": {"seeded": clip, "publish_http": getattr(npub, "status_code", None),
                             "skipped_videos": npub_body.get("skipped_videos"), "pushed": npub_body.get("pushed"),
                             "on_of_n": len(on_nude), "clip_on_of": sorted(set(on_nude) & set(clip))},
           "safe_in_queue": len(safe_q), "safe_bad": safe_bad[:5], "sent": verdicts, "http": status,
           "detail": detail, "members_changed": {k: sorted(after.get(k, set()) ^ before.get(k, set()))[:5]
                                                 for k in set(after) | set(before)
                                                 if after.get(k, set()) != before.get(k, set())},
           "ui": guard_ui if guard_ui is not None else "--no-ui"}
    ctx.check(JEV_FREE_GUARD, bool(unsafe_q) and len(unsafe_q) == len(unsafe_ids) and not flags_bad
              and bool(safe_q) and not safe_bad and status is not None and status < 500 and refused
              and after == before and ui_ok and publish_ok, **out)
    return out


async def _preselect(ctx, w, aid: str, creator: dict, want_pre: dict[int, str], api_pre: dict[int, str | None],
                     safe_ids: set[int]) -> dict:
    """`feet_preselect_confirm`: the API's `preselect` set == the seeded PRESELECT keepers (unfiled), each on its
    suggestion; UI (desktop, fresh): exactly the unfiled ones arrive ticked; untick one free-safe tile (so the guard
    stage keeps a buddy); "File N preselected" sends one triage of the rest at their rungs; DB: those land there."""
    out: dict = {"api_extra": sorted(set(api_pre) - set(want_pre))[:5],
                 "api_missing": sorted(set(want_pre) - set(api_pre))[:5],
                 "api_wrong_rung": [(m, api_pre[m], r) for m, r in want_pre.items()
                                    if m in api_pre and api_pre[m] != r][:5]}
    api_ok = bool(want_pre) and api_pre == want_pre
    if not ctx.app:
        ctx.check(PRESELECT, api_ok, ui="--no-ui", **out)
        return out
    before = _members(w, aid)
    held = set().union(*before.values()) if before else set()
    want_ticked = {m: r for m, r in want_pre.items() if m not in held}
    got: dict = {}
    want_post: list[dict] = []
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        with recorded(page, "POST", TRIAGE) as sent:
            try:
                tiles = await _open_picker(ctx, page, creator)
                shown = {t["id"] for t in tiles}
                ticks = await page.locator("[data-pack-tick]").evaluate_all(
                    "els => els.map(e => ({id: Number(e.dataset.packTick), on: e.checked}))")
                got["ticked"] = sorted(t["id"] for t in ticks if t["on"])
                # The grid holds the top `limit` (600) only: the oracle is the preselected keepers it shows.
                want_ui = {m: r for m, r in want_ticked.items() if m in shown}
                got["want_ticked"] = sorted(want_ui)
                got["not_shown"] = len(want_ticked) - len(want_ui)
                untick = next((m for m in sorted(want_ui) if m in safe_ids), None)
                got["untick"] = untick
                if untick is not None:
                    await page.locator(f'[data-pack-tick="{untick}"]').uncheck(timeout=10_000)
                want_post = sorted(({"media_id": m, "rung": r} for m, r in want_ui.items() if m != untick),
                                   key=lambda v: v["media_id"])
                btn = page.get_by_role("button", name=FILE)
                got["button"] = (await btn.inner_text(timeout=10_000)).strip()
                got["trigger_shot"] = await ui.shot(ctx, page, "feet-preselect-trigger")
                await btn.click(timeout=10_000)
                await page.get_by_text(FILED_NOTE).first.wait_for(timeout=WAIT_MS)
                await page.wait_for_timeout(500)
                got["settled_shot"] = await ui.shot(ctx, page, "feet-preselect-settled")
            except Exception as e:  # noqa: BLE001 — the check reports it
                got["error"] = f"{type(e).__name__}: {e}"[:600]
                got["failed_shot"] = await ui.shot(ctx, page, "failed-feet-preselect")
            posts = list(sent)
    after = _members(w, aid)
    want_made = {k: set(v) for k, v in before.items()}
    for v in want_post:
        want_made.setdefault(f"feet-{v['rung']}", set()).add(v["media_id"])
    body = (posts[0]["body"] or {}) if posts else {}
    sent_v = sorted(body.get("verdicts") or [], key=lambda v: v.get("media_id", 0))
    out.update(ui={k: v for k, v in got.items() if not k.endswith("_shot")},
               shots=[got.get("trigger_shot"), got.get("settled_shot")], want=want_post[:8], sent=sent_v[:8],
               sent_n=len(sent_v), want_n=len(want_post), posts=[{k: p[k] for k in ("status", "url")} for p in posts],
               diff={k: sorted(after.get(k, set()) ^ want_made.get(k, set()))[:5]
                     for k in set(after) | set(want_made) if after.get(k, set()) != want_made.get(k, set())})
    ctx.check(PRESELECT, api_ok and "error" not in got and bool(want_post) and got.get("untick") is not None
              and got.get("ticked") == got.get("want_ticked")
              and got.get("button") == f"File {len(want_post)} preselected"
              and len(posts) == 1 and posts[0]["status"] == 200 and sent_v == want_post and after == want_made
              and "settled_shot" in got, **out)
    return out


def _p95(ms: list[float]) -> float:
    s = sorted(ms)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


async def run(ctx):
    w = ctx.world
    await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    aid = creator["id"]
    truth = vault_feet.seed(w, creator, int(ctx.param("items", w.size["vault_feet_items"])))
    (ctx.stack.tmp / "of-vault.json").write_text("{}")   # lib/vault_relay.py answers the feet-tease publish
    images = stills_dir(ctx.stack.tmp) / "images" / aid
    images.mkdir(parents=True, exist_ok=True)
    for mid in set(truth["like_set"]) | set(truth["keepers"]):
        (images / f"{mid}.jpg").write_bytes(picture_bytes(f"feet/{mid}"))
    keep = set(truth["keepers"]) - set(truth["filed"])
    expect = {int(k): v for k, v in truth["expect"].items()}
    ctx.note(f"Creator {aid}: {len(truth['like_set'])} LIKE candidates, {len(truth['keepers'])} keepers "
             f"({len(truth['filed'])} pre-filed: feet-nude + {FREE_RUNG} {truth['free_unsafe'] + truth['free_safe']}"
             f" + pre-rule {truth['pre_rule']})")

    # ── rank ──
    ms, r = [], None
    for _ in range(5):
        t0 = time.perf_counter()
        r = await ctx.owner.get(f"{CANDS}?account_id={aid}&category=feet&limit=2000")
        ms.append((time.perf_counter() - t0) * 1000)
    data = r.json() if r is not None and r.status_code == 200 else {}
    cands = data.get("candidates") or []
    queue = [c for c in cands if not c.get("rung")]
    on_rungs = {c["media_id"]: c["rung"] for c in cands if c.get("rung")}
    n = max(1, min(len(keep), len(queue)))
    p_new = len({c["media_id"] for c in queue[:n]} & keep) / n
    p_old = len(set(truth["like_set"][:n]) & keep) / n
    ctx.metric("feet_precision_new", round(p_new, 3))
    ctx.metric("feet_precision_like", round(p_old, 3))
    ctx.metric("feet_candidates_p95_ms", round(_p95(ms), 1))
    leaked = sorted(set(truth["filed"]) & {c["media_id"] for c in queue})
    q_ids = {c["media_id"] for c in queue}
    ctx.check(RANKED, r is not None and r.status_code == 200 and q_ids == keep and p_new >= PRECISION_MIN
              and p_new >= p_old + LIFT_MIN and not leaked and on_rungs == truth["filed"],
              http=getattr(r, "status_code", None), n=n, precision=round(p_new, 3), like_baseline=round(p_old, 3),
              queue=len(queue), keepers=len(keep), extra=sorted(q_ids - keep)[:5], missing=sorted(keep - q_ids)[:5],
              filed_leaked=leaked[:5], filed_back=len(on_rungs), filed_want=len(truth["filed"]),
              top=[(c["media_id"], c.get("score")) for c in queue[:5]])
    wrong = [(c["media_id"], c.get("suggested"), c.get("tier"), expect[c["media_id"]]) for c in queue
             if c["media_id"] in keep and (c.get("suggested"), c.get("tier"))
             != (expect[c["media_id"]]["suggested"], expect[c["media_id"]]["tier"])]
    stray = [c["media_id"] for c in queue if c["media_id"] not in keep and c.get("suggested")]
    seen_keep = sum(1 for c in queue if c["media_id"] in keep)
    ctx.check(PREFILL, bool(queue) and seen_keep == min(len(keep), len(queue)) and not wrong and not stray,
              keepers_in_queue=seen_keep, wrong=wrong[:5], wrong_n=len(wrong), stray=stray[:5])
    # The leak: an unknown Jev tier (review / an unsure body) prefilled on the free preview rung.
    unknown = set(truth["unknown_tier"]) & {c["media_id"] for c in queue}
    free_leak = [c["media_id"] for c in queue if c.get("suggested") == FREE_RUNG
                 and (c.get("tier") is None or c.get("free_ok") is False)]
    unknown_tiers = sorted({str(c.get("tier")) for c in queue if c["media_id"] in unknown})
    ctx.check(NO_FREE, bool(unknown) and not free_leak and unknown_tiers == ["None"],
              unknown_tier_in_queue=len(unknown), free_leak=free_leak[:5], free_leak_n=len(free_leak),
              unknown_tiers=unknown_tiers)

    # Selected and ranked from `_jev` alone: Jev photos at the gate, nothing else.
    cls, filed = truth["classes"], set(truth["filed"])
    by_id = {c["media_id"]: c for c in cands}
    soles_missing = [m for m in cls["jev_soles"] if m not in filed and m not in q_ids]
    out_back = {k: sorted(set(cls[k]) & q_ids)[:5]
                for k in (*JEV_OUT, *vault_feet.NO_JEV, *vault_feet.VIDEO) if set(cls[k]) & q_ids}
    scores = [c.get("score") or 0 for c in queue]
    bad_rows = [(c["media_id"], c.get("kind"), c.get("jev"), c.get("score")) for c in queue
                if c.get("kind") != "photo" or not c.get("jev") or (c.get("score") or 0) < GATE]
    # No videos in feet: filing an unfiled clip is refused whole (nothing written).
    clip = next((m for m in cls["jev_video"] if m not in filed), None)
    before = _members(w, aid)
    vr = (await ctx.owner.post(TRIAGE, json={"account_id": aid, "category": "feet",
                                             "verdicts": [{"media_id": clip, "rung": "nude"}]})
          if clip is not None else None)
    try:
        vdetail = (vr.json() or {}).get("detail") if vr is not None else None
    except ValueError:
        vdetail = None
    video_refused = (getattr(vr, "status_code", None) == 400 and isinstance(vdetail, dict)
                     and vdetail.get("error") == "feet_photos_only" and vdetail.get("media_ids") == [clip]
                     and _members(w, aid) == before)
    ctx.check(JEV_RANK, bool(queue) and not soles_missing and not out_back and scores == sorted(scores, reverse=True)
              and not bad_rows and video_refused,
              soles_missing=soles_missing[:5], out_back=out_back, bad_rows=bad_rows[:5],
              sorted=scores == sorted(scores, reverse=True),
              video={"media_id": clip, "http": getattr(vr, "status_code", None), "detail": vdetail})
    unsafe_ids = {m for k in vault_feet.JEV_UNSAFE for m in cls[k]} - filed
    unsafe_q = [c for c in queue if c["media_id"] in unsafe_ids]
    safe_ids = {m for k in JEV_SAFE for m in cls[k]} - filed
    want_pre = {int(m): r for m, r in truth["preselect"].items() if int(m) not in filed}
    api_pre = {c["media_id"]: c.get("suggested") for c in queue if c.get("preselect")}
    ctx.check(P95_CHECK, _p95(ms) <= CANDS_P95_MS[w.scale], budget=True, p95_ms=round(_p95(ms), 1),
              budget_ms=CANDS_P95_MS[w.scale], ms=[round(x, 1) for x in ms])

    if not ctx.app:
        for name in (KEYS, PHONE):
            ctx.skip(name, "--no-ui")
        await _preselect(ctx, w, aid, creator, want_pre, api_pre, safe_ids)
        await _free_guard(ctx, w, aid, queue, unsafe_ids, unsafe_q, safe_ids, None, by_id, truth)
        return

    # ── desktop: the keys ──
    desk: dict = {}
    guard_ui: dict = {}
    ids: list[int] = []
    want_verdicts: list[dict] | None = None
    async with ui.owner_browser(ctx, viewport=VIEWPORT) as page:
        with recorded(page, "POST", TRIAGE) as sent:
            try:
                tiles = await _open_picker(ctx, page, creator)
                desk["tiles"] = tiles[:ENTERS + 2]
                desk["trigger_shot"] = await ui.shot(ctx, page, "feet-picker-trigger")
                ids = [t["id"] for t in tiles[:ENTERS + 2]]
                if len(ids) == ENTERS + 2:
                    # What the grid SHOWED is the oracle: Enter files a shown prefill, moves past a tile with none.
                    shown = {t["id"]: _shown_suggestion(t["label"]) for t in tiles[:ENTERS]}
                    desk["enter_prefills"] = sum(1 for r in shown.values() if r)
                    # "1" on a tile the server says is not free-safe files nothing (packPickerState.canFile).
                    t5 = ids[ENTERS + 1]
                    desk["tile5_free_ok"] = (by_id.get(t5) or {}).get("free_ok")
                    want_verdicts = sorted(
                        [{"media_id": i, "rung": r} for i, r in shown.items() if r]
                        + [{"media_id": ids[ENTERS], "rung": None}]
                        + ([{"media_id": t5, "rung": FREE_RUNG}] if desk["tile5_free_ok"] is not False else []),
                        key=lambda v: v["media_id"])
                    await page.locator(f'[data-pack-tile="{ids[0]}"]').click(position={"x": 30, "y": 60})
                    for key in ["Enter"] * ENTERS + ["x", "1"]:
                        await page.keyboard.press(key)
                        await page.wait_for_timeout(120)
                    desk["keyed_shot"] = await ui.shot(ctx, page, "feet-picker-keyed")
                    await _save(page)
                    desk["settled_shot"] = await ui.shot(ctx, page, "feet-picker-settled")
            except Exception as e:  # noqa: BLE001 — the check reports it
                desk["error"] = f"{type(e).__name__}: {e}"[:600]
                desk["failed_shot"] = await ui.shot(ctx, page, "failed-feet-picker")
            # The Jev free guard on screen: an unsafe tile the keys left alone.
            try:
                gid = next((c["media_id"] for c in unsafe_q if c["media_id"] not in ids), None)
                guard_ui["tile"] = gid
                if gid is not None:
                    tile = page.locator(f'[data-pack-tile="{gid}"]')
                    await tile.scroll_into_view_if_needed(timeout=WAIT_MS)
                    await page.wait_for_timeout(300)
                    guard_ui["badge"] = await tile.get_by_text("Jev", exact=True).count() > 0
                    guard_ui["tease_disabled"] = await tile.get_by_role(
                        "button", name=FREE_RUNG, exact=True).is_disabled()
                    guard_ui["nude_enabled"] = await tile.get_by_role("button", name="nude", exact=True).is_enabled()
                    guard_ui["shot"] = await ui.shot(ctx, page, "feet-picker-jev-guard")
            except Exception as e:  # noqa: BLE001 — the check reports it
                guard_ui["error"] = f"{type(e).__name__}: {e}"[:600]
            posts = list(sent)
    made = _members(w, aid)
    want_made: dict[str, set[int]] = {}
    for mid, rung in truth["filed"].items():
        want_made.setdefault(f"feet-{rung}", set()).add(mid)
    for v in want_verdicts or []:
        if v["rung"]:
            want_made.setdefault(f"feet-{v['rung']}", set()).add(v["media_id"])
    body = (posts[0]["body"] or {}) if posts else {}
    got_verdicts = sorted(body.get("verdicts") or [], key=lambda v: v.get("media_id", 0))
    # Not vacuous: the top tiles must have shown a prefill for Enter to confirm (the ranking's job).
    ctx.check(KEYS, "error" not in desk and want_verdicts is not None and desk.get("enter_prefills", 0) >= 1
              and len(posts) == 1
              and posts[0]["status"] == 200 and got_verdicts == want_verdicts and made == want_made
              and "settled_shot" in desk,
              want=want_verdicts, sent=got_verdicts, posts=[{k: p[k] for k in ("status", "url")} for p in posts],
              made={k: len(v) for k, v in made.items()},
              diff={k: sorted(made.get(k, set()) ^ want_made.get(k, set()))[:5] for k in set(made) | set(want_made)},
              ui=desk)

    # ── phone: layout + one tap ──
    phone: dict = {}
    async with ui.owner_browser(ctx, viewport=PHONE_VP, touch=True) as page:
        with recorded(page, "POST", TRIAGE) as sent:
            try:
                tiles = await _open_picker(ctx, page, creator, pick=False, drawer=phone.setdefault("drawer", {}))
                first = tiles[0]["id"]
                phone["tile"] = first
                tile = page.locator(f'[data-pack-tile="{first}"]')
                phone["layout"] = await tile.evaluate(
                    """t => { const g = t.parentElement; const bs = [...t.querySelectorAll('button')];
                       return { cols: getComputedStyle(g).gridTemplateColumns.split(' ').filter(Boolean).length,
                                tap_h: Math.min(...bs.map(b => b.getBoundingClientRect().height)),
                                tap_w_reject: bs[bs.length - 1].getBoundingClientRect().width,
                                buttons: bs.length,
                                scroll_w: document.documentElement.scrollWidth, inner_w: window.innerWidth,
                                tile_right: t.getBoundingClientRect().right }; }""")
                phone["trigger_shot"] = await ui.shot(ctx, page, "feet-picker-phone-trigger")
                await tile.get_by_role("button", name="nude", exact=True).tap(timeout=10_000)
                await _save(page)
                phone["settled_shot"] = await ui.shot(ctx, page, "feet-picker-phone-settled")
            except Exception as e:  # noqa: BLE001 — the check reports it
                phone["error"] = f"{type(e).__name__}: {e}"[:600]
                phone["failed_shot"] = await ui.shot(ctx, page, "failed-feet-picker-phone")
            phone_posts = list(sent)
    lay = phone.get("layout") or {}
    after = _members(w, aid)
    tile_in = sorted(k for k, v in after.items() if phone.get("tile") in v)
    pbody = (phone_posts[0]["body"] or {}) if phone_posts else {}
    ctx.check(PHONE, "error" not in phone and lay.get("cols") == 2 and lay.get("buttons") == 4
              and (lay.get("tap_h") or 0) >= TAP_MIN_PX and (lay.get("tap_w_reject") or 0) >= TAP_MIN_PX
              and lay.get("scroll_w", 1e9) <= lay.get("inner_w", 0) and lay.get("tile_right", 1e9) <= PHONE_VP[0]
              and len(phone_posts) == 1 and phone_posts[0]["status"] == 200
              and pbody.get("verdicts") == [{"media_id": phone.get("tile"), "rung": "nude"}]
              and tile_in == ["feet-nude"] and "settled_shot" in phone
              and (phone.get("drawer") or {}).get("visible") == EXTRAS_TOOLS,
              layout=lay, sent=pbody.get("verdicts"), tile_in=tile_in, ui=phone)
    pre = await _preselect(ctx, w, aid, creator, want_pre, api_pre, safe_ids)
    guard = await _free_guard(ctx, w, aid, queue, unsafe_ids, unsafe_q, safe_ids, guard_ui, by_id, truth)
    (ctx.out / "feet-picker.json").write_text(json.dumps(
        {"truth": {k: v for k, v in truth.items() if k != "classes"},
         "classes": {k: len(v) for k, v in truth["classes"].items()},
         "precision": {"new": p_new, "like": p_old, "n": n}, "ms": ms,
         "queue_top": queue[:40], "desk_posts": posts, "phone_posts": phone_posts,
         "made": {k: sorted(v) for k, v in after.items()}, "preselect": pre, "jev_free_guard": guard},
        default=str, indent=1))
