"""Vault Pro > Extras > "Feet pack" (app/components/vault/VaultPackPickerModal.tsx + packPickerState.ts,
service/vault_pack_picker.candidates / triage): the grid comes back most likely first (structured describe fields,
text as fallback, Jev's `_jev.feet_subject` when the row has one), items already on a rung out of the queue, each
keeper prefilled with its rung from the stored tier (`_jev.lane5`, else qwen flags; priced body -> nude-body; an
unknown tier never on the free rung), and the keyboard files the queue: Enter confirms the prefill, x rejects,
1/2/3 pick a rung. On a 390px phone the grid is two columns of 44px taps.

World: `agency_inbox`; Creator 0's vault by SQL (seed/vault_feet.py, `vault_feet_items` 300 / 2,000 / 12,000):
feet keepers (tease / bare / $10 / $50 / unflagged nude / unflagged socks + bare (unknown tier) / Jev-measured /
Jev free / Jev $50 over qwen-covered) mixed with what the old LIKE query also
returned (bystander, text mention, ambiguous payoff-act, measured-no) and filler, media ids shuffled across
classes; ~8% of keepers already on `feet-nude`. Every LIKE-set item's full image is a small PNG in the run's still
store (lib/vault_collect_relay.py's dirs), so tiles draw pictures.

Stages:
  rank   (also --no-ui) GET /admin/vault-ai/pack-candidates?limit=2000 by the owner, 5 times (latency).
  desktop (UI) 1440x900: Extras > Feet pack, screenshot `feet-picker-trigger`; click the first tile; Enter x3, x,
        1; screenshot; Save; settles on "Saved", screenshot `feet-picker-settled`.
  phone (UI) 390x844 touch: Vault Pro on the Creator (last pick, localStorage), Extras > Feet pack; screenshot
        `feet-picker-phone-trigger`; tap the first tile's "nude"; Save; screenshot `feet-picker-phone-settled`.

Checks (lib/vault_feet_picker_faults.py names):
  feet_ranked_above_like_baseline   precision@N of the unfiled queue (N = unfiled keepers) >= PRECISION_MIN and
                                    >= the old query's (LIKE, media_id order; the seeder's oracle) + LIFT_MIN; no
                                    pre-filed item in the queue, each back with rung "nude".
  feet_prefill_matches_flags        every unfiled keeper's (suggested, tier) == the seeded class's; no non-keeper
                                    prefilled.
  feet_no_free_prefill_without_tier no queue item with tier None is prefilled on the free rung (tease); the seeded
                                    unknown-tier keepers are in the queue with tier None.
  feet_keyboard_confirm_members     desktop: >= 1 of tiles 1-3 showed a prefill; one triage POST (200) of exactly
                                    the keyed verdicts (tiles 1-3 the prefill they showed, none if none, tile 4
                                    rejected, tile 5 tease); DB: the feet-* folders' members == those + the
                                    pre-filed, nothing else.
  feet_phone_layout_tap_save        phone: the Extras drawer shows every tool (none desk-only), screenshot
                                    `extras-drawer-phone`; 2 grid columns, rung + reject buttons >= 44px tall, no horizontal
                                    overflow; one POST [{tile, nude}] (200); DB: that tile on feet-nude only.
  feet_candidates_p95 [budget]      the route's p95 over the 5 reads <= CANDS_P95_MS[scale].

Bypasses (declared): the vault is SQL as Collect + describe + flags leave it (no OF, no LLM); full images written by
the harness into the run's temp still store; the background collector off (VAULT_COLLECT_ENABLED=0); Publish (OF
writes) not pressed. No volume: --scale only resizes the vault.
Break-it-once: feet-rank-like-only (default; server: every likelihood 0 -> media_id order, no prefill: ranked +
prefill + keyboard), --fault=feet-free-prefill-unknown-tier (server: unknown tier prefilled from clothing, socks
-> the free rung: no-free + prefill), --fault=feet-keys-enter-ignores-suggestion (client: Enter only moves:
keyboard).
"""
from __future__ import annotations

import json
import re
import time

from slop.actors import ui
from slop.lib.hold import recorded
from slop.lib.img_relay import picture_bytes
from slop.lib.vault_collect_relay import stills_dir
from slop.lib.vault_feet_picker_faults import KEYS, NO_FREE, PHONE, PREFILL, RANKED
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
CANDS_P95_MS = {"small": 400, "medium": 800, "huge": 2_000}   # one read, whole LIKE set ranked (12k vault: ~80 ms in-process)
TAP_MIN_PX = 44
P95_CHECK = "feet_candidates_p95"
SUGGESTED = re.compile(r", suggested (\S+)$")
SAVE = re.compile(r"^Save \d+$")
FREE_RUNG = "tease"   # vault_pack_picker feet rungs[0]: rides free as the preview


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


def _p95(ms: list[float]) -> float:
    s = sorted(ms)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


async def run(ctx):
    w = ctx.world
    await ctx.build(PROFILE)
    creator = w.data["creators"][0]
    aid = creator["id"]
    truth = vault_feet.seed(w, creator, int(ctx.param("items", w.size["vault_feet_items"])))
    images = stills_dir(ctx.stack.tmp) / "images" / aid
    images.mkdir(parents=True, exist_ok=True)
    for mid in truth["like_set"]:
        (images / f"{mid}.jpg").write_bytes(picture_bytes(f"feet/{mid}"))
    keep = set(truth["keepers"]) - set(truth["filed"])
    expect = {int(k): v for k, v in truth["expect"].items()}
    ctx.note(f"Creator {aid}: {len(truth['like_set'])} LIKE candidates, {len(truth['keepers'])} keepers "
             f"({len(truth['filed'])} pre-filed on feet-nude)")

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
    ctx.check(RANKED, r is not None and r.status_code == 200 and p_new >= PRECISION_MIN
              and p_new >= p_old + LIFT_MIN and not leaked and on_rungs == truth["filed"],
              http=getattr(r, "status_code", None), n=n, precision=round(p_new, 3), like_baseline=round(p_old, 3),
              queue=len(queue), filed_leaked=leaked[:5], filed_back=len(on_rungs), filed_want=len(truth["filed"]),
              top=[(c["media_id"], c.get("score")) for c in queue[:5]])
    wrong = [(c["media_id"], c.get("suggested"), c.get("tier"), expect[c["media_id"]]) for c in queue
             if c["media_id"] in keep and (c.get("suggested"), c.get("tier"))
             != (expect[c["media_id"]]["suggested"], expect[c["media_id"]]["tier"])]
    stray = [c["media_id"] for c in queue if c["media_id"] not in keep and c.get("suggested")]
    seen_keep = sum(1 for c in queue if c["media_id"] in keep)
    ctx.check(PREFILL, bool(queue) and seen_keep == min(len(keep), len(queue)) and not wrong and not stray,
              keepers_in_queue=seen_keep, wrong=wrong[:5], wrong_n=len(wrong), stray=stray[:5])
    # The leak: an unknown tier (no _jev lane5, no flags) prefilled on the free preview rung.
    unknown = set(truth["unknown_tier"]) & {c["media_id"] for c in queue}
    free_leak = [c["media_id"] for c in queue if c.get("tier") is None and c.get("suggested") == FREE_RUNG]
    unknown_tiers = sorted({str(c.get("tier")) for c in queue if c["media_id"] in unknown})
    ctx.check(NO_FREE, bool(unknown) and not free_leak and unknown_tiers == ["None"],
              unknown_tier_in_queue=len(unknown), free_leak=free_leak[:5], free_leak_n=len(free_leak),
              unknown_tiers=unknown_tiers)
    ctx.check(P95_CHECK, _p95(ms) <= CANDS_P95_MS[w.scale], budget=True, p95_ms=round(_p95(ms), 1),
              budget_ms=CANDS_P95_MS[w.scale], ms=[round(x, 1) for x in ms])

    if not ctx.app:
        for name in (KEYS, PHONE):
            ctx.skip(name, "--no-ui")
        return

    # ── desktop: the keys ──
    desk: dict = {}
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
                    want_verdicts = sorted(
                        [{"media_id": i, "rung": r} for i, r in shown.items() if r]
                        + [{"media_id": ids[ENTERS], "rung": None}, {"media_id": ids[ENTERS + 1], "rung": "tease"}],
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
    (ctx.out / "feet-picker.json").write_text(json.dumps(
        {"truth": {k: v for k, v in truth.items() if k != "classes"},
         "classes": {k: len(v) for k, v in truth["classes"].items()},
         "precision": {"new": p_new, "like": p_old, "n": n}, "ms": ms,
         "queue_top": queue[:40], "desk_posts": posts, "phone_posts": phone_posts,
         "made": {k: sorted(v) for k, v in after.items()}}, default=str, indent=1))
