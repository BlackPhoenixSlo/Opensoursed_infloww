"""Vault Pro's Jev v8 pass (service/vault_jev.py: TypeSafe Jev + NudeNet), on by default for every photo and clip with
no setting, as an operator meets it: describe-all, then flags-all, over every Creator's vault on the real relay routes.
A photo's or clip's flags and describe come from Jev only (vault_jev_flags mapper, Jev-fed describe: prose / v6 for a
photo, "vid" for a clip: the V2 describe fed the clip's lane facts, D54); no qwen flags call for either.

World: `agency_inbox` plus seed/vault_items_describe.py (`--set items=`, SCALES `vault_jev_items` 90 / 600 / 2,000),
armed as in 2026-11-01-vault-describe-sweep (DeepInfra fake, still stores, the Agency's dummy key through
`PUT /admin/my-llm-keys`), with these changes made here between the seeder's plan and its write:
  - every photo gets a unique size with both edges in [280, 448], so each Jev pass sends the still at that size
    (lib/vault_jev_relay.py says why) and both fakes tell items apart by it; audio keeps the seeder's.
  - every photo gets a Jev profile (lib/vault_jev_relay.py `PROFILES`): what the fake TypeSafe answers about it.
    Per Creator round robin over its single photos (every profile, `down` included), a planted re-upload set one
    answering profile for all its members (the same picture; never `down`). Creator 0 must hold every profile
    (raises otherwise: raise `--set items=`).
  - every clip gets real mp4s on OF's CDN (lib/img_relay.py, `mp4_frames`), served through the Creator's own
    client.http, and OF's by-id read (`OF.vault_media_by_id`, lib/vault_jev_relay.py) answering them freshly signed:
    a 12 s colour clip, frames 800 x H (H unique, 480-956 step 4, plus a tint past 120 clips), second i a flat colour that
    spells i (`vault_describe_relay.clip_rgb`), so both fakes tell the clip by size + tint and Jev's fake the frame
    by its colour; no seeded storyboard (the product's 720p pass must write it). A recipe per clip (`CLIPS`: a frame
    profile per frame), per Creator round robin over its single clips, a planted clip set one non-down recipe; a
    source per clip (`src`): the first live single clip of each Creator the describe answers (not cached, not
    blank) has no 720p rendition and no `files.full` ("no720": the 240p is read), the second
    (Creators 0-2 only: 50 MB bodies sit in the relay's memory) a 720p over the 50 MB cap ("overcap"), every other a
    720p under it. Every recipe and source must be present (raises otherwise).
Nothing is switched on: the describe plan (`GET /admin/vault-ai/describe-all/plan`, its `jev` block) must say ready
(NudeNet loaded, key set) for every Creator before anything is pressed, else the run stops (INFRA, not a verdict).

Phases (the describe sweep's `_phase`: `--users` owner tabs poll the status route every 2.5 s while it runs):
  pass1  describe-all for every Creator at once: each photo / clip the sweep visits gets Jev first, then the Jev-fed
         describe; one Jev cannot read (`down`) is skipped, not described.
  flags  flags-all {force} for every Creator at once: items with no current `_jev` yet (the seeded earlier
         describes, the `down` ones) get Jev there; a re-upload copy gets its set's.

Clip recipes (`CLIPS`, frame -> photo profile, every other frame `none`), planned from the same answers:
  free  all dressed                                                     -> free
  max   frame 3 topless (`nipple`), frame 6 the `lower` crop's bare vulva -> $50 at frame 6 (pass L there only; a
        clip taking frame 0's lane would be free, one taking any frame's $10)
  top3  frames 1 2 4 5 7 coin flips that clear at 1568 (`p2_clear`)      -> pass 2 on exactly 3 of them (D53 top-3),
        $10 off those (the 2 left unescalated settle free, D42)
  down  TypeSafe answers 400 on every frame                             -> `_jev` error, skipped
Every frame that sets a lane sits in 0-8 (fault `video-jev-reads-9-frames` moves no lane). Every clip's file is 12 s and
OF says 10 s (its `duration`, which the mirror keeps), so the describe asks 6 scrub frames (the duration ladder).

Planned lanes (`WANT`), from what the planted answers say, never from the product's rules. NudeNet is the
product's own (640m.onnx, `NUDENET_640M_PATH`); the seeded stills are flat colour, on which it detects nothing
(measured: no class on 20 flat stills 280-448 px), so every profile is planned with NudeNet at 0.
  none        dressed, nothing bare                              -> free  (pass 1)
  pen         something inserted (.95)                           -> $100  (pass 1)
  vulva       bare vulva (.95)                                   -> $50   (pass 1)
  nipple      topless (.95), crotch dressed                      -> $10   (pass 1)
  lower       topless, crotch hidden; the lower crop: bare vulva -> $50   (pass 1, L)
  p2_clear    nipple a coin flip at 1024 px, plainly at 1568     -> $10   (pass 1, 2)
  unsure      nipple a coin flip at every size, NudeNet nothing  -> free, settled  (pass 1, 2; owner D42: a review
              photo NudeNet sees nothing on settles free)
  pen_unsure  insertion a coin flip at every size                -> $100, settled  (pass 1, 2; D42: an unsure
              insertion settles $100)
  down        TypeSafe answers 400                               -> `_jev` error, no describe, no flags (skipped,
              retried next sweep: one Jev try per sweep)

Jev-fed describe (service/vault_describe_jev.py, D51), planned from the same answers: the coin flips (unsure,
pen_unsure) stay in review -> the v6 recipe (V2 + facts + hedge, 960 px); every other answered photo -> the prose
recipe (640 px), whose fake answer claims nipples, pussy AND insertion (lib/vault_describe_relay.py `PROSE_CLAIMS`):
its `clothing_items` stored as the fake named them (`PROSE_GARMENTS`), the row's `over_` garment names taken from
them only over a region Jev calls covered (bra over breasts, thong over vulva / anus; none on a nude row), and
the stored description must keep exactly the claims its answers spell (`SAYS`: pen -> inserted, vulva -> pussy,
nipple / p2_clear -> nipples, lower -> nipples + pussy, none -> nothing). A clip: the vid recipe, its clip hedge iff
its `_jev.review`; an unhedged clip's stored description is the fake's text plus one clause per claim its stored max
frame's profile spells (the product's scrub appends a hard fact the text lacks).

UI (after the sweeps and their checks, so it changes none of them; one owner, Chromium 1440x900): Vault Pro on
Creator 0; screenshot `vault-jev-described-trigger` (the grid, a pass-1 prose-described photo's tile in view), one
click on it, wait for the item panel's Description box to hold the stored text; screenshot
`vault-jev-described-settled`; then the same for a vid-described clip (`vault-jev-video-trigger` /
`vault-jev-video-settled`). Side effects read back: the row's `_describe.path` / `_flags_model`, and
`GET /admin/vault-ai/items` (the item's `_ai` describe status, description, `fields._describe.path`).

Checks (names in lib/vault_jev_faults.py): JEV_DEFAULT_ON, JEV_PHOTO_NO_QWEN_FLAGS, JEV_PHOTO_NEVER_V2, JEV_LANES,
JEV_BEFORE_DESCRIBE, JEV_COST, JEV_COPY, JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW, the clips' JEV_VIDEO_FRAMES,
JEV_VIDEO_TOP3, JEV_VIDEO_LANE, JEV_VIDEO_NO_QWEN_FLAGS, JEV_VIDEO_OVER_CAP, JEV_VIDEO_NO_720, JEV_VIDEO_SCRUB,
JEV_DESCRIBE_VIDEO, JEV_UI_DESCRIBED / JEV_UI_VIDEO (SKIP with --no-ui), the status routes' p95 budgets and p95 vs
last green (the describe sweep's `STATUS_P95_MS`, `_check_budgets`), plus the stock no 5xx / no unexpected Traceback.
`SLOP_LIVE=1`: every check SKIPs.

Bypasses (declared; the describe sweep's DeepInfra / stills / SQL-vault ones apply unchanged):
  - TypeSafe is lib/vault_jev_relay.py's fake at its System One wire (the product's real `typesafe_sdk` client,
    `TYPESAFE_BASE_URL` → the relay's loopback route; key, cap reservation, grok_calls rows, NudeNet, rules and
    storage are the product's). Answers by item profile and question set; `--set jev_latency_s=` (0.1 s) per call.
    "Jev unavailable" is planted as TypeSafe's 400 per photo; no NudeNet / no key are not run here (the product's
    preflight; unit-tested in service/tests/test_vault_jev.py).
  - NudeNet's weights are read from `NUDENET_640M_PATH` (default /tmp/nn-weights/640m.onnx, md5 checked by the
    product); the stills are synthetic, so NudeNet's veto / promote never fire here (blind spot, declared).
  - Photo sizes are the scenario's (above), not the seeder's; a clip's row width / height are its scrub frames'.
  - OF's CDN is lib/img_relay.py's loopback fake (curl_cffi re-routed at its wire; Policy expiry checked, Signature
    not); the clips are synthetic flat-colour mp4s whose 240p is the same frames as the 720p (a real 240p is
    smaller: here only the source label, `review` and the bytes tell them apart); the over-cap 720p is the clip
    padded past 50 MB with a `free` box (the product refuses it on Content-Length before reading a byte).
  - OF's by-id read is lib/vault_jev_relay.py's `OF.vault_media_by_id` (in-process, not its HTTP); its `duration`
    is 10 s for the 12 s file (the product times Jev's frames by the file's own length), so every clip describes on
    6 frames.
  - The phase helpers are the describe sweep's own, loaded from its file (one copy, not a fork).

Break-it-once: `photo-still-calls-qwen-flags` (the FAULT: a photo's flags step also runs the qwen flags call) turns only
JEV_PHOTO_NO_QWEN_FLAGS red; `--fault=photo-describe-falls-back-to-v2` (a photo with no Jev reading gets the V2
describe) only JEV_PHOTO_NEVER_V2; `--fault=vault-jev-no-settle` (settle blind to NudeNet) only JEV_LANES;
`--fault=vault-jev-describe-ignores-review` (the describe routes a review photo to the prose recipe) only
JEV_DESCRIBE_REVIEW. Videos: `video-still-calls-qwen-flags` only JEV_VIDEO_NO_QWEN_FLAGS; `video-jev-reads-9-frames`
only JEV_VIDEO_FRAMES; `video-escalates-every-frame` (no top-3 cut) only JEV_VIDEO_TOP3; `video-lane-uses-first-frame`
only JEV_VIDEO_LANE; `video-over-cap-auto-free` / `video-missing-720-auto-free` (the 240p reading not marked review)
only JEV_VIDEO_OVER_CAP / JEV_VIDEO_NO_720; `video-scrub-not-published` (the describe re-downloads the 240p) only
JEV_VIDEO_SCRUB; `video-describe-falls-back-to-v2` (a Jev-down clip gets the V2 describe) only JEV_DESCRIBE_VIDEO.
"""
# No `from __future__ import annotations` (lib/cli.py loads a scenario outside sys.modules; see the describe sweep).
import importlib.util
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from slop.lib.img_relay import arm_run as arm_cdn
from slop.lib.vault_describe_relay import (
    FAKE_KEY, PROSE_CLAIMS, PROSE_GARMENTS, arm_run, clip_key, clip_rgb, describe_text,
)
from slop.lib.vault_jev_faults import (
    JEV_BEFORE_DESCRIBE, JEV_COPY, JEV_COST, JEV_DEFAULT_ON, JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW,
    JEV_DESCRIBE_VIDEO, JEV_LANES, JEV_PHOTO_NEVER_V2, JEV_PHOTO_NO_QWEN_FLAGS, JEV_UI_DESCRIBED, JEV_UI_VIDEO,
    JEV_VIDEO_FRAMES, JEV_VIDEO_LANE, JEV_VIDEO_NO_720, JEV_VIDEO_NO_QWEN_FLAGS, JEV_VIDEO_OVER_CAP, JEV_VIDEO_SCRUB,
    JEV_VIDEO_TOP3,
)
from slop.lib.vault_jev_relay import DOWN, PROFILES, arm_jev, clip_keys, photo_sizes, price_mc
from slop.seed import vault_items_describe


def _load_sweep():
    path = Path(__file__).with_name("2026-11-01-vault-describe-sweep.py")
    spec = importlib.util.spec_from_file_location("slop_vault_describe_sweep_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load_sweep()

PROFILE = "agency_inbox"
UI = True
FAULT = "photo-still-calls-qwen-flags"
NUDENET = os.environ.get("NUDENET_640M_PATH") or "/tmp/nn-weights/640m.onnx"
RELAY_ENV = {"NUDENET_640M_PATH": NUDENET}
P95_VS_LAST = S.P95_VS_LAST
P95_VS_LAST_MIN_N = S.P95_VS_LAST_MIN_N
CONFIG = "/admin/account-config"
ITEMS = "/admin/vault-ai/items"
REVIEW_Q = "/admin/vault-ai/flags-review"
JEV_COUNT, JEV_CALLS = "/__slop/vault-jev/count", "/__slop/vault-jev/calls"
CDN_CALLS = "/__slop/img/calls"
CHECKS = (JEV_DEFAULT_ON, JEV_PHOTO_NO_QWEN_FLAGS, JEV_PHOTO_NEVER_V2, JEV_LANES, JEV_BEFORE_DESCRIBE, JEV_COST,
          JEV_COPY, JEV_DESCRIBE_PROSE, JEV_DESCRIBE_REVIEW, JEV_VIDEO_FRAMES, JEV_VIDEO_TOP3, JEV_VIDEO_LANE,
          JEV_VIDEO_NO_QWEN_FLAGS, JEV_VIDEO_OVER_CAP, JEV_VIDEO_NO_720, JEV_VIDEO_SCRUB, JEV_DESCRIBE_VIDEO,
          JEV_UI_DESCRIBED, JEV_UI_VIDEO)
# profile -> (lane5, passes the fake must see, settled); the module docstring says why each.
WANT = {"none": ("free", ["1"], False), "pen": ("$100", ["1"], False), "vulva": ("$50", ["1"], False),
        "nipple": ("$10", ["1"], False), "lower": ("$50", ["1", "L"], False),
        "p2_clear": ("$10", ["1", "2"], False), "unsure": ("free", ["1", "2"], "nn.10"),
        "pen_unsure": ("$100", ["1", "2"], "nn.10")}
assert set(WANT) | {DOWN} == set(PROFILES)
# Jev-fed describe (D51), from the same planted answers: the coin flips stay in review (v6 recipe); every other
# profile gets the prose recipe and keeps exactly the claims its answers spell (`PROSE_CLAIMS` keys).
REVIEW_PROFILES = {"unsure", "pen_unsure"}
SAYS = {"none": set(), "pen": {"pen"}, "vulva": {"vulva"}, "nipple": {"nipple"}, "lower": {"nipple", "vulva"},
        "p2_clear": {"nipple"}}
assert set(SAYS) | REVIEW_PROFILES == set(WANT)
PX = {"prose": 640, "v6": 960}
FLAG_KEYS = ("breasts_vis", "vulva_vis", "anus_vis", "underwear_visible")
# A prose row's garment names (`over_`), from the fake's PROSE_GARMENTS (["red lace bra", "black thong"]): the bra
# can cover only the breasts, the thong only the vulva / anus (service/vault_jev_flags.garments).
OVER = {"over_breasts": ("breasts_vis", PROSE_GARMENTS[0]), "over_vulva": ("vulva_vis", PROSE_GARMENTS[1]),
        "over_anus": ("anus_vis", PROSE_GARMENTS[1])}
# Clips (D54): 12 frames, 800 x (480 + 4j) (j < CLIP_SPAN; a tint per further CLIP_SPAN clips, 8 tints), so pass 1 /
# 2 / L keep the frame's size (lib/vault_jev_relay.py) and the 400 px scrub frame is 400 x (240 + 2j) (ffmpeg's
# `scale=400:-2` keeps it even), never a photo's.
FRAMES = 12
CLIP_W, CLIP_H0, CLIP_SPAN, TINTS = 800, 480, 120, 8
CLIP_OF_S = 10              # OF's `duration` (the seeder's 10 s ladder step); the file is FRAMES s
DESCRIBE_FRAMES = 6         # the duration ladder on a 10 s clip (service/vault_ai_vision_decide.py, < 30 s)
OVER_CAP_BYTES = 50_000_001  # D54: the 720p download cap is 50 MB
OVER_CAP_CREATORS = 3
SOURCES = ("no720", "overcap")  # a Creator's first live single clips, in this order; every other clip "720"


def _at(**frames) -> list[str]:
    out = ["none"] * FRAMES
    for i, p in frames.items():
        out[int(i[1:])] = p
    return out


# recipe -> (frame profiles, planned lane, frames asking pass 2, frames asking pass L); the module docstring says why.
_TOP3 = (1, 2, 4, 5, 7)
CLIPS = {"free": (_at(), "free", set(), set()),
         "max": (_at(f3="nipple", f6="lower"), "$50", set(), {6}),
         "top3": (_at(**{f"f{i}": "p2_clear" for i in _TOP3}), "$10", set(_TOP3), set()),
         DOWN: ([DOWN] * FRAMES, None, set(), set())}
MAX_FRAME = 6   # "max": the frame whose lane the clip must take


def _profiles(items) -> None:
    """Per Creator, round robin of every profile over its single photos and of WANT's (never `down`) over its
    planted sets (a set is one unit: one picture)."""
    singles, sets = defaultdict(list), defaultdict(dict)
    for it in items:
        if it["kind"] == "photo":
            if it["dupe_set"]:
                sets[it["account_id"]].setdefault(it["dupe_set"], []).append(it)
            else:
                singles[it["account_id"]].append(it)
    for its in singles.values():
        for k, it in enumerate(its):
            it["jev"] = list(PROFILES)[k % len(PROFILES)]
    for us in sets.values():
        for k, members in enumerate(us.values()):
            for it in members:
                it["jev"] = list(WANT)[k % len(WANT)]


def _clips(items, aids) -> None:
    """Every clip its frames' size + tint, scrub size, a recipe (`it["clip"]`, its `frames` profiles) and a source
    (`it["src"]`); no seeded storyboard (module docstring)."""
    clips = [it for it in items if it["kind"] == "video"]
    if len(clips) > CLIP_SPAN * TINTS:
        raise ValueError(f"slop: {len(clips)} clips > {CLIP_SPAN * TINTS} (size, tint) pairs")
    for c, it in enumerate(clips):
        h = CLIP_H0 + 4 * (c % CLIP_SPAN)
        it.update(frame_size=(CLIP_W, h), size=(CLIP_W // 2, h // 2), tint=c // CLIP_SPAN, storyboard=False,
                  src="720", duration=CLIP_OF_S)
    singles, sets = defaultdict(list), defaultdict(dict)
    for it in clips:
        if it["dupe_set"]:
            sets[it["account_id"]].setdefault(it["dupe_set"], []).append(it)
        else:
            singles[it["account_id"]].append(it)
    for aid, its in singles.items():
        for k, it in enumerate(its):
            it["clip"] = list(CLIPS)[k % len(CLIPS)]
        live = [it for it in its if it["clip"] != DOWN and not it["cached"] and it["outcome"] != "blank"]
        for k, src in enumerate(SOURCES[:1 if aids.index(aid) >= OVER_CAP_CREATORS else 2]):
            if k < len(live):
                live[k]["src"] = src
    live_recipes = [r for r in CLIPS if r != DOWN]
    for us in sets.values():
        for k, members in enumerate(us.values()):
            for it in members:
                it["clip"] = live_recipes[k % len(live_recipes)]
    for it in clips:
        it["frames"] = CLIPS[it["clip"]][0]
    missing = (set(CLIPS) - {it["clip"] for it in clips}) | ({"720", *SOURCES} - {it["src"] for it in clips})
    if missing:
        raise ValueError(f"slop: no clip planned for {sorted(missing)}; raise --set items=")


def _cdn_plan(items) -> tuple[dict, dict, dict]:
    """(assets, mp4_frames, mp4_sizes) for lib/img_relay.py: each clip's 240p / 720p / files.full mp4, its colour
    clip, the over-cap 720p padded past the cap."""
    assets, frames, big = {}, {}, {}
    for it in items:
        if it.get("frames") is None:
            continue
        keys = clip_keys(it)
        clip = {"size": list(it["frame_size"]), "rgb": [list(clip_rgb(it["tint"], i)) for i in range(FRAMES)]}
        for k in keys.values():
            if k:
                assets[k], frames[k] = {"size": 1}, clip
        if it["src"] == "overcap":
            big[keys["720"]] = OVER_CAP_BYTES
    return assets, frames, big


async def _jev_count(ctx) -> int:
    return (await ctx.owner.get(JEV_COUNT)).json()["n"]


async def _jev_calls(ctx, since: int) -> list[dict]:
    return (await ctx.owner.get(f"{JEV_CALLS}?since={since}")).json()["calls"]


def _key(c: dict) -> str | None:
    return vault_items_describe.key(c["account_id"], c["media_id"]) if c["account_id"] is not None else None


def _by_item(calls) -> dict:
    out = defaultdict(list)
    for c in calls:
        if _key(c):
            out[_key(c)].append(c)
    return out


def _jev_of(row: dict) -> dict | None:
    j = (row["ai"] or {}).get("_jev")
    return j if isinstance(j, dict) else None


def _jpeg_width(p: Path) -> int | None:
    from PIL import Image

    try:
        with Image.open(p) as im:
            return im.width
    except Exception:  # noqa: BLE001 — the check reports it
        return None


def _sql(ctx, q: str) -> list:
    con = ctx.world.sql()
    try:
        return con.execute(q).fetchall()
    finally:
        con.close()


async def _ui_described(ctx, creator: dict, cands: list[tuple[int, str]], kind: str, shot: str) -> dict:
    """Vault Pro on `creator`: the first candidate `kind` item whose tile is in the grid; trigger shot, one click on
    it, settled shot once its panel's Description box holds the stored text."""
    aid, ui = creator["id"], S.ui
    got: dict = {"account_id": aid, "kind": kind, "candidates": len(cands)}
    async with ui.owner_browser(ctx, viewport=S.VIEWPORT) as page:
        await page.context.add_init_script(S.TOURS_SEEN)
        await page.route(S.IMG, lambda r: r.abort())  # the grid's OF CDN tiles: OF is unreachable (declared)
        try:
            await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=S.WAIT_MS)
            await ui.pick_creator(page, creator["nickname"], timeout_ms=S.WAIT_MS)
            await page.locator(f"[title*=' · {kind}']").first.wait_for(timeout=S.WAIT_MS)
            tile = None
            for mid, text in cands:
                # a clip's title also carries its duration (`#id · video · 0:12`)
                loc = page.locator(f"[title='#{mid} · {kind}'], [title^='#{mid} · {kind} · ']")
                if await loc.count():
                    tile, got["media_id"], got["want_text"] = loc.first, mid, text
                    break
            if tile is None:
                raise RuntimeError(f"no Jev-described {kind} of this Creator has a tile in the grid")
            await tile.scroll_into_view_if_needed(timeout=10_000)
            got["trigger_shot"] = await ui.shot(ctx, page, f"{shot}-trigger")
            await tile.click(timeout=10_000)
            box = page.get_by_placeholder("Full description…")
            await box.wait_for(timeout=30_000)
            for _ in range(60):  # the item's `_ai` lands in the editor's draft
                got["settled_text"] = await box.input_value()
                if got["settled_text"] == got["want_text"]:
                    break
                await page.wait_for_timeout(250)
            got["header"] = await page.get_by_text(re.compile(rf"^#{got['media_id']} · {kind}( · .*)?$")).count()
            got["settled_shot"] = await ui.shot(ctx, page, f"{shot}-settled")
        except Exception as e:  # noqa: BLE001 — the check reports it
            got["error"] = f"{type(e).__name__}: {e}"[:600]
            try:
                got["failed_shot"] = await ui.shot(ctx, page, f"failed-{shot}")
            except Exception:  # noqa: BLE001
                pass
    mid = got.get("media_id")
    if mid is not None:
        ((raw,),) = _sql(ctx, f"SELECT ai_fields_json FROM vault_items WHERE account_id = '{aid}' "
                              f"AND media_id = {int(mid)}")
        ai = json.loads(raw or "{}")
        got["db"] = {"path": (ai.get("_describe") or {}).get("path"), "flags_model": ai.get("_flags_model")}
        r = await ctx.owner.get(f"{ITEMS}?account_id={aid}&type={kind}&limit=1000")
        hit = [m for m in (r.json().get("list") or []) if m.get("id") == mid] if r.status_code == 200 else []
        a = (hit[0].get("_ai") or {}) if hit else {}
        got["api"] = {"http": r.status_code, "found": bool(hit), "describe_status": a.get("describe_status"),
                      "description": a.get("description") or a.get("video_description"),
                      "path": ((a.get("fields") or {}).get("_describe") or {}).get("path")}
    return got


def _check_ui(ctx, name: str, path: str, got: dict | None) -> None:
    if got is None:
        ctx.skip(name, "--no-ui")
        return
    api, want = got.get("api") or {}, got.get("want_text")
    ctx.check(name, not got.get("error") and bool(want) and got.get("settled_text") == want
              and got.get("header", 0) > 0 and got.get("db") == {"path": path, "flags_model": "jev"}
              and api.get("found") is True and api.get("describe_status") == "described"
              and api.get("description") == want and api.get("path") == path, **got)


async def run(ctx) -> None:
    if os.environ.get("SLOP_LIVE") == "1":
        for c in CHECKS:
            ctx.skip(c, "SLOP_LIVE=1: this scenario runs on the TypeSafe / DeepInfra fakes only")
        return
    if not Path(NUDENET).is_file():
        raise RuntimeError(f"slop: NudeNet weights not at {NUDENET} (set NUDENET_640M_PATH): Jev refuses without them")
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    c0 = aids[0]
    r = await ctx.owner.put("/admin/my-llm-keys", json={"deepinfra": FAKE_KEY})
    ctx.metric("agency_deepinfra_key", {"status": r.status_code})

    t0 = time.time()
    items = vault_items_describe.plan(w, creators, ctx.param("items", w.size["vault_jev_items"]))
    photo_sizes(items)
    _profiles(items)
    missing = set(PROFILES) - {it["jev"] for it in items if it["account_id"] == c0 and it.get("jev")}
    if missing:
        raise ValueError(f"slop: Creator 0 got no photo for profiles {sorted(missing)}; raise --set items=")
    _clips(items, aids)
    armed = await arm_run(ctx.owner, ctx.stack.tmp, items, ctx.param("llm_latency_s", 0.05))
    await arm_jev(ctx.owner, ctx.stack.tmp, items, ctx.param("jev_latency_s", 0.1))
    assets, mp4_frames, big = _cdn_plan(items)
    await arm_cdn(ctx.owner, ctx.stack.tmp, assets, ctx.param("cdn_latency_s", 0.02), mp4_sizes=big,
                  mp4_frames=mp4_frames)
    await vault_items_describe.seed(w, items, armed)
    by_key = {i["key"]: i for i in items}
    rows0 = S._rows(ctx)
    ctx.metric("vault_seed", {"seconds": round(time.time() - t0, 2), "items": len(items),
                              "photos": dict(Counter(it["jev"] for it in items if it.get("jev"))),
                              "clips": dict(Counter(f"{it['clip']}:{it['src']}" for it in items if it.get("clip")))})

    plans0 = await S._plans(ctx, aids)
    jev_plan = {aid: plans0[aid].get("jev") for aid in aids}
    if not all((jev_plan[a] or {}).get("ready") for a in aids):
        raise RuntimeError(f"slop: Jev not ready on the relay: {jev_plan}")

    async def press_describe() -> "S.Pressed":
        plan = await S._plans(ctx, aids)
        res = await S._post_all(ctx, S.DESCRIBE, aids, lambda a: {"account_id": a})
        return S.Pressed({aid: S._undesc(plan[aid]) for aid in aids}, {a: x.status_code for a, x in res.items()},
                         plan)

    async def press_flags() -> "S.Pressed":
        res = await S._post_all(ctx, S.FLAGS_ALL, aids, lambda a: {"account_id": a, "force": True})
        starts = {a: {**(x.json() if x.status_code == 200 else {}), "http": x.status_code} for a, x in res.items()}
        return S.Pressed({a: int(s.get("candidates") or 0) for a, s in starts.items()}, starts)

    n0 = await _jev_count(ctx)
    p1 = await S._phase(ctx, "pass1", S.STATUS, aids, press_describe)
    j1 = await _jev_calls(ctx, n0)
    pf = await S._phase(ctx, "flags", S.FLAGS_STATUS, aids, press_flags)
    jf = await _jev_calls(ctx, n0 + len(j1))
    cdn = (await ctx.owner.get(f"{CDN_CALLS}?since=0")).json()["calls"]  # before the UI (its hovers fetch 240p)
    (ctx.out / "calls-cdn.json").write_text(json.dumps(cdn))
    ctx.rec.stage = None
    phases = ((p1, j1), (pf, jf))
    every = j1 + jf
    ok_calls = [c for c in every if c["status"] == 200]
    for p, jc in phases:
        (ctx.out / f"calls-{p.stage}.json").write_text(json.dumps(p.calls))
        (ctx.out / f"calls-jev-{p.stage}.json").write_text(json.dumps(jc))
    photos = [it for it in items if it["kind"] == "photo"]
    read = [it for it in photos if it["jev"] != DOWN]      # every photo Jev answers about
    down = [it for it in photos if it["jev"] == DOWN]
    clips = [it for it in items if it["kind"] == "video"]
    live_clips = [it for it in clips if it["clip"] != DOWN]   # every clip Jev answers about
    down_clips = [it for it in clips if it["clip"] == DOWN]
    read_all = read + live_clips
    own = _by_item(ok_calls)                                   # the items Jev billed, their calls
    paid_clips = [it for it in live_clips if it["key"] in own]
    (ctx.out / "jev-rows.json").write_text(json.dumps(
        {it["key"]: {"profile": it.get("jev") or it.get("clip"), "src": it.get("src"),
                     "want": WANT.get(it["jev"]) if it.get("jev") else CLIPS[it["clip"]][1],
                     "dupe_set": it["dupe_set"], "cached": it["cached"], "_jev": _jev_of(pf.rows[it["key"]])}
         for it in photos + clips}, indent=1, default=str))
    (ctx.out / "sweep-status.json").write_text(json.dumps(
        {"jev_plan": jev_plan, **{p.stage: {"want": p.want, "presses": p.presses, "status": p.status}
                                  for p, _ in phases}}, indent=2, default=str))
    timed_out = p1.timed_out + pf.timed_out
    presses_bad = {f"{p.stage}:{a}": s for p, _ in phases for a, s in p.presses.items()
                   if (s if isinstance(s, int) else s.get("http")) != 200}
    di_calls = [(p.stage, c) for p, _ in phases for c in p.calls if _key(c)]

    # JEV_DEFAULT_ON
    wrong_calls = [c for c in every if (by_key.get(_key(c)) or {}).get("kind") not in ("photo", "video")]
    wrong_rows = [k for k, row in pf.rows.items() if _jev_of(row) is not None and by_key[k]["kind"] == "audio"]
    not_ok = {it["key"]: (_jev_of(pf.rows[it["key"]]) or {}).get("status") for it in read_all
              if (_jev_of(pf.rows[it["key"]]) or {}).get("status") != "ok"}
    plan_bad = {aid: jev_plan[aid] for aid in aids
                if set(jev_plan[aid] or {}) != {"ready", "reason"} or jev_plan[aid]["ready"] is not True}
    cfg = {aid: await ctx.owner.get(f"{CONFIG}?account_id={aid}") for aid in aids}
    cfg_bad = {aid: x.status_code for aid, x in cfg.items()
               if x.status_code != 200 or "vault_jev_enabled" in x.json()["config"]}
    column = [n for (n,) in _sql(ctx, "SELECT name FROM pragma_table_info('account_ai_config')")
              if n == "vault_jev_enabled"]
    per_creator = Counter(it["account_id"] for it in read_all if it["key"] not in not_ok)
    ctx.check(JEV_DEFAULT_ON, bool(ok_calls) and bool(live_clips) and not wrong_calls and not wrong_rows
              and not not_ok and not plan_bad and not cfg_bad and not column and all(per_creator[a] > 0 for a in aids),
              read_photos=len(read), read_clips=len(live_clips), ok_by_creator={str(a): per_creator[a] for a in aids},
              wrong_calls=len(wrong_calls), sample=wrong_calls[:3], wrong_rows=wrong_rows[:5],
              not_ok=dict(list(not_ok.items())[:5]), n_not_ok=len(not_ok), plan_bad=plan_bad, config_bad=cfg_bad,
              column=column)

    # JEV_PHOTO_NO_QWEN_FLAGS
    # JEV_PHOTO_NO_QWEN_FLAGS / JEV_VIDEO_NO_QWEN_FLAGS
    for name, kind, its in ((JEV_PHOTO_NO_QWEN_FLAGS, "photo", read), (JEV_VIDEO_NO_QWEN_FLAGS, "video", live_clips)):
        flag_calls = [{"stage": s, "media_id": c["media_id"], "account_id": c["account_id"]}
                      for s, c in di_calls if c["purpose"] == "flags" and by_key[_key(c)]["kind"] == kind]
        flag_bad = {}
        for it in its:
            ai = pf.rows[it["key"]]["ai"] or {}
            if ai.get("_flags_model") != "jev" or ai.get("_flags_v") != 3 or any(k not in ai for k in FLAG_KEYS):
                flag_bad[it["key"]] = {k: ai.get(k) for k in ("_flags_model", "_flags_v", *FLAG_KEYS)}
        ctx.check(name, bool(its) and not flag_calls and not flag_bad, flag_calls=len(flag_calls),
                  sample_calls=flag_calls[:5], flags_not_jev=len(flag_bad), sample_rows=dict(list(flag_bad.items())[:5]))

    # JEV_PHOTO_NEVER_V2
    v2_calls = [{"stage": s, "media_id": c["media_id"], "account_id": c["account_id"]} for s, c in di_calls
                if c["purpose"] == "describe" and by_key[_key(c)]["kind"] == "photo" and c.get("recipe") == "v2"]
    v2_rows = [it["key"] for it in photos for p, _ in phases
               if ((p.rows[it["key"]]["ai"] or {}).get("_describe") or {}).get("path") == "v2"]
    jev_by_phase = [_by_item(jc) for _, jc in phases]
    down_bad = {}
    for it in down:
        k = it["key"]
        tries = [len(jp.get(k, [])) for jp in jev_by_phase]
        # describe calls only: a flags call on any photo is JEV_PHOTO_NO_QWEN_FLAGS's (one check per fault)
        di = [c["purpose"] for _, c in di_calls if _key(c) == k and c["purpose"] == "describe"]
        j = _jev_of(pf.rows[k]) or {}
        statuses = [p.rows[k]["status"] for p, _ in phases]
        if (j.get("status") != "error" or di or max(tries) > 1 or sum(tries) < 1
                or statuses != [rows0[k]["status"]] * len(phases)):
            down_bad[k] = {"jev": {x: j.get(x) for x in ("status", "error")}, "deepinfra": di, "tries": tries,
                           "status": statuses, "seeded": rows0[k]["status"]}
    ctx.check(JEV_PHOTO_NEVER_V2, bool(down) and not v2_calls and not v2_rows and not down_bad and not timed_out,
              v2_calls=len(v2_calls), sample_calls=v2_calls[:5], v2_rows=v2_rows[:5], down=len(down),
              down_bad=len(down_bad), sample_down=dict(list(down_bad.items())[:5]))

    # JEV_LANES
    stray = [c for c in every if not c["auth"] or not c["danger"]
             or c["status"] != (400 if c["profile"] == DOWN else 200)]
    bad, paid_profiles = {}, Counter()
    for it in read:
        lane, passes, settled = WANT[it["jev"]]
        j, seen = _jev_of(pf.rows[it["key"]]), [c["pass"] for c in own.get(it["key"], [])]
        if seen:
            paid_profiles[it["jev"]] += 1
        good = (j is not None and j.get("status") == "ok" and j.get("lane5") == lane
                and j.get("settled") == settled and (seen == passes and j.get("passes") == passes
                                                     or (not seen and it["dupe_set"] is not None)))
        if not good:
            bad[it["key"]] = {"profile": it["jev"], "want": [lane, passes, settled], "seen": seen,
                              "jev": {k: (j or {}).get(k) for k in ("status", "lane5", "lane", "settled", "passes",
                                                                    "error")}}
    pass_n = Counter(c["pass"] for c in ok_calls)
    ctx.check(JEV_LANES, bool(read) and not bad and not stray and set(paid_profiles) == set(WANT)
              and pass_n["2"] > 0 and pass_n["L"] > 0 and not timed_out and not presses_bad,
              photos=len(read), bad=len(bad), sample=dict(list(bad.items())[:5]), stray=stray[:5],
              paid_by_profile=dict(paid_profiles), passes=dict(pass_n), timed_out=timed_out,
              presses_not_200=presses_bad)

    # Clips (D54). A paid clip's calls by pass -> its frames; its `_jev`'s packed frames.
    def frames_of(k: str, pss: str) -> list[int]:
        return sorted(c["frame"] for c in own.get(k, []) if c["pass"] == pss)

    def blob_frames(j: dict | None) -> list[dict]:
        fr = (j or {}).get("frames")
        return fr if isinstance(fr, list) else []

    # JEV_VIDEO_FRAMES (a down clip: every try asks all 12 frames, one try per sweep)
    fr_bad, paid_recipes = {}, Counter()
    for it in paid_clips:
        k, j = it["key"], _jev_of(pf.rows[it["key"]]) or {}
        p1f, fr = frames_of(k, "1"), blob_frames(j)
        paid_recipes[it["clip"]] += 1
        good = (p1f == list(range(FRAMES)) and j.get("kind") == "video" and j.get("vv") == "jv1"
                and len(fr) == FRAMES and all(isinstance(f, dict) and "1" in f and len(f.get("nn") or []) == 2
                                              and f.get("lane5") and f.get("px") == list(it["frame_size"])
                                              for f in fr))
        if not good:
            fr_bad[k] = {"clip": it["clip"], "pass1_frames": p1f, "kind": j.get("kind"), "vv": j.get("vv"),
                         "frames": len(fr), "sample_frame": fr[:1]}
    for it in down_clips:
        tries = [sorted(c["frame"] for c in jp.get(it["key"], [])) for jp in jev_by_phase]
        if any(t not in ([], list(range(FRAMES))) for t in tries) or not any(tries):
            fr_bad[it["key"]] = {"clip": DOWN, "tries": tries}
    ctx.check(JEV_VIDEO_FRAMES, set(paid_recipes) == set(CLIPS) - {DOWN} and bool(down_clips) and not fr_bad,
              paid=dict(paid_recipes), down=len(down_clips), bad=len(fr_bad), sample=dict(list(fr_bad.items())[:4]))

    # JEV_VIDEO_TOP3
    top_bad, esc = {}, Counter()
    for it in paid_clips:
        k, fr = it["key"], blob_frames(_jev_of(pf.rows[it["key"]]))
        _, _, need2, need_l = CLIPS[it["clip"]]
        got = {"2": frames_of(k, "2"), "L": frames_of(k, "L")}
        ok = True
        for pss, need in (("2", need2), ("L", need_l)):
            fs = got[pss]
            esc[pss] += len(fs)
            ok = ok and (len(fs) == min(3, len(need)) and len(set(fs)) == len(fs) and set(fs) <= need
                         and {i for i, f in enumerate(fr) if isinstance(f, dict) and pss in f} == set(fs))
        if not ok:
            top_bad[k] = {"clip": it["clip"], "need2": sorted(need2), "needL": sorted(need_l), "seen": got,
                          "blob": {p: [i for i, f in enumerate(fr) if isinstance(f, dict) and p in f] for p in "2L"}}
    ctx.check(JEV_VIDEO_TOP3, bool(paid_clips) and esc["2"] > 0 and esc["L"] > 0 and not top_bad,
              paid=len(paid_clips), escalations=dict(esc), bad=len(top_bad), sample=dict(list(top_bad.items())[:4]))

    # JEV_VIDEO_LANE (copies included: a set's members carry its one reading)
    lane_bad, lanes_seen = {}, Counter()
    for it in live_clips:
        j = _jev_of(pf.rows[it["key"]]) or {}
        lane, top, fr = CLIPS[it["clip"]][1], j.get("frame"), blob_frames(j)
        at = fr[top] if isinstance(top, int) and 0 <= top < len(fr) and isinstance(fr[top], dict) else {}
        lanes_seen[j.get("lane5")] += 1
        good = (j.get("lane5") == lane and isinstance(top, int) and at.get("lane5") == lane
                and (it["clip"] != "max" or top == MAX_FRAME) and (it["clip"] != "top3" or "2" in at))
        if not good:
            lane_bad[it["key"]] = {"clip": it["clip"], "want": lane, "lane5": j.get("lane5"), "frame": top,
                                   "frame_lanes": [f.get("lane5") for f in fr if isinstance(f, dict)]}
    ctx.check(JEV_VIDEO_LANE, bool(live_clips) and not lane_bad, clips=len(live_clips), lanes=dict(lanes_seen),
              bad=len(lane_bad), sample=dict(list(lane_bad.items())[:4]))

    # JEV_VIDEO_OVER_CAP / JEV_VIDEO_NO_720: the source, review, bytes, and the review route's codes
    got_by, bytes_by, codes = Counter(), {}, {}
    for c in cdn:
        if c.get("status") == 200:
            got_by[c["key"]] += 1
            bytes_by[c["key"]] = c.get("bytes")
    for aid in aids:
        r = await ctx.owner.get(f"{REVIEW_Q}?account_id={aid}&limit=5000")
        for x in (r.json().get("items") or []) if r.status_code == 200 else []:
            codes[vault_items_describe.key(aid, x["media_id"])] = x.get("codes") or []
    full_gets = [c["key"] for c in cdn if c["key"] in {clip_keys(it)["full"] for it in clips}]

    def src_bad(it: dict) -> dict | None:
        j, keys = _jev_of(pf.rows[it["key"]]) or {}, clip_keys(it)
        disputed = "jev_review" in codes.get(it["key"], [])
        if it["src"] == "720":
            want = {"src": "720", "review": None, "bytes": bytes_by.get(keys["720"]), "disputed": False}
        else:
            want = {"src": "240", "review": "over_cap" if it["src"] == "overcap" else "no_720",
                    "bytes": bytes_by.get(keys["240"]), "disputed": True}
        got = {"src": j.get("src"), "review": j.get("review"), "bytes": j.get("bytes"), "disputed": disputed}
        answered = it["src"] != "overcap" or got_by[keys["720"]] >= 1
        return None if got == want and want["bytes"] and answered else {"want": want, "got": got,
                                                                        "720_gets": got_by[keys["720"] or ""]}

    for name, srcs in ((JEV_VIDEO_OVER_CAP, ("overcap",)), (JEV_VIDEO_NO_720, ("no720", "720"))):
        its = [it for it in paid_clips if it["src"] in srcs]
        bad = {it["key"]: b for it in its if (b := src_bad(it))}
        extra = {"full_gets": full_gets[:5]} if name == JEV_VIDEO_OVER_CAP else {}
        ctx.check(name, {it["src"] for it in its} == set(srcs) and not bad
                  and (name != JEV_VIDEO_OVER_CAP or not full_gets),
                  clips=dict(Counter(it["src"] for it in its)), bad=len(bad), sample=dict(list(bad.items())[:4]),
                  **extra)

    # JEV_VIDEO_SCRUB (cdn read before the UI)
    sb_root = Path(armed["dirs"]["storyboard"])
    scrub_bad = {}
    for it in paid_clips:
        j = _jev_of(pf.rows[it["key"]]) or {}
        d = sb_root / armed["hashes"][it["url"]]
        names = sorted(p.name for p in d.glob("*.jpg")) if d.is_dir() else []
        widths = sorted({_jpeg_width(d / n) or 0 for n in names})
        n240 = got_by[clip_keys(it)["240"]]
        want240 = 0 if j.get("src") == "720" else 1
        if names != sorted(f"{i}.jpg" for i in range(FRAMES)) or widths != [400] or n240 != want240:
            scrub_bad[it["key"]] = {"src": j.get("src"), "frames": len(names), "widths": widths,
                                    "240_gets": n240, "want_240_gets": want240}
    ctx.check(JEV_VIDEO_SCRUB, bool(paid_clips) and not scrub_bad, clips=len(paid_clips), bad=len(scrub_bad),
              sample=dict(list(scrub_bad.items())[:4]))

    # JEV_BEFORE_DESCRIBE
    d1, o1 = p1.by_item("describe"), _by_item(j1)
    describe_t = defaultdict(list)
    for c in p1.calls:
        if c["purpose"] == "describe" and c["account_id"] is not None:
            describe_t[vault_items_describe.key(c["account_id"], c["media_id"])].append(c["t"])
    order_bad = {}
    for it in read_all:
        if it["key"] in d1:
            jt = [c["t"] for c in o1.get(it["key"], [])]
            if not jt or max(jt) >= min(describe_t[it["key"]]):
                order_bad[it["key"]] = {"jev_t": jt, "describe_t": describe_t[it["key"]]}
    n_described = Counter(it["kind"] for it in read_all if it["key"] in d1)
    ctx.check(JEV_BEFORE_DESCRIBE, n_described["photo"] > 0 and n_described["video"] > 0 and not order_bad,
              described=dict(n_described), bad=len(order_bad), sample=dict(list(order_bad.items())[:5]))

    # JEV_COST (billed = the fake's 200 answers; a 400 bills nothing)
    def priced(calls) -> Counter:
        tok, out = Counter(), Counter()
        for c in calls:
            if _key(c) and c["status"] == 200:
                tok[(c["account_id"], _key(c))] += c["tokens_in"]
        for (aid, _), t in tok.items():
            out[aid] += price_mc(t)
        return out

    sweeps = {}
    for p, jc in phases:
        want_jev, di = priced(jc), p.billed("describe", "flags")
        sweeps[p.stage] = {aid: {"jev_reported": S._prog(p.status[aid]).get("jev_cost_millicents", 0),
                                 "jev_billed": want_jev[aid], "total_reported": p.reported(aid),
                                 "total_billed": di[aid] + want_jev[aid]} for aid in aids}
    rows = {a: [int(c or 0), int(n or 0)] for a, c, n in _sql(
        ctx, "SELECT account_id, SUM(cost_cents), SUM(call_count) FROM grok_daily_cost WHERE provider = 'typesafe' "
             "GROUP BY account_id")}
    audit = {a: [int(c or 0), int(t or 0), int(n)] for a, c, t, n in _sql(
        ctx, "SELECT account_id, SUM(cost_cents), SUM(tokens_in), COUNT(*) FROM grok_calls WHERE provider = "
             "'typesafe' AND purpose = 'vault_jev_flags' AND status = 'done' GROUP BY account_id")}
    total, tokens = priced(every), Counter()
    for c in ok_calls:
        if _key(c):
            tokens[c["account_id"]] += c["tokens_in"]
    paid_items = Counter(by_key[k]["account_id"] for k in own)
    spend = {aid: {"billed": total[aid], "daily_row": rows.get(aid, [0, 0])[0],
                   "audit": audit.get(aid, [0, 0, 0]), "tokens": tokens[aid], "photos_paid": paid_items[aid]}
             for aid in aids}
    ok_sweeps = all(v["jev_reported"] == v["jev_billed"] and v["total_reported"] == v["total_billed"]
                    for s in sweeps.values() for v in s.values())
    ok_spend = all(s["daily_row"] == s["billed"] and s["audit"] == [s["billed"], s["tokens"], s["photos_paid"]]
                   for s in spend.values())
    ctx.check(JEV_COST, all(total[a] > 0 for a in aids) and ok_sweeps and ok_spend, sweeps=sweeps, spend=spend,
              billed_mc=sum(total.values()))

    # JEV_COPY
    sets = defaultdict(list)
    for it in read_all:
        if it["dupe_set"]:
            sets[(it["account_id"], it["dupe_set"])].append(it)
    copy_bad, n_copies = {}, 0
    for sid, ms in sets.items():
        paid = [m for m in ms if m["key"] in own]
        ids = {m["media_id"] for m in ms}
        src = _jev_of(pf.rows[paid[0]["key"]]) if len(paid) == 1 else None
        wrong = []
        for m in ms:
            if m in paid:
                continue
            ai = pf.rows[m["key"]]["ai"] or {}
            marks = {ai.get(S.COPY_MARK), ai.get(S.FLAGS_COPY_MARK)} & ids
            if src is None or _jev_of(pf.rows[m["key"]]) != src or not marks:
                wrong.append({"media_id": m["media_id"], "marks": [ai.get(S.COPY_MARK), ai.get(S.FLAGS_COPY_MARK)],
                              "lane5": (_jev_of(pf.rows[m["key"]]) or {}).get("lane5")})
            else:
                n_copies += 1
        if len(paid) != 1 or wrong:
            copy_bad[f"{sid[0]}:{sid[1]}"] = {"members": sorted(ids), "paid": [m["media_id"] for m in paid],
                                              "wrong": wrong}
    ctx.check(JEV_COPY, n_copies > 0 and not copy_bad, sets=len(sets), copies=n_copies,
              bad=dict(list(copy_bad.items())[:5]))

    # JEV_DESCRIBE_PROSE / _REVIEW / _VIDEO: pass 1's own describe calls (copies and blanks have none / no row; the
    # `down` photos are JEV_PHOTO_NEVER_V2's, the `down` clips JEV_DESCRIBE_VIDEO's below)
    dcalls = defaultdict(list)
    for c in p1.calls:
        if c["purpose"] == "describe" and _key(c) and DOWN not in (by_key[_key(c)].get("jev"),
                                                                    by_key[_key(c)].get("clip")):
            dcalls[_key(c)].append(c)
    groups = {"prose": {}, "v6": {}, "vid": {}}
    for k, cs in dcalls.items():
        it, row = by_key[k], p1.rows[k]
        if row["status"] != "described":
            continue
        photo = it["kind"] == "photo"
        path = ("v6" if it["jev"] in REVIEW_PROFILES else "prose") if photo else "vid"
        ai, model = row["ai"] or {}, cs[-1]["model"]
        marker = describe_text(it["account_id"], it["media_id"], model)
        j = _jev_of(row) or {}
        jv = j.get("v")
        hedge = path == "v6" or (path == "vid" and bool(j.get("review")))
        if path == "prose":
            text = " ".join([marker + ".", *(s for c, s in PROSE_CLAIMS.items() if c in SAYS[it["jev"]])])
        elif path == "vid" and not hedge:
            # an unhedged clip's facts are its stored max frame's: the scrub appends each hard claim they spell
            # that the fake's text lacks (its planted profile's SAYS), in PROSE_CLAIMS' order
            top = j.get("frame")
            says = SAYS.get(it["frames"][top], set()) if isinstance(top, int) and 0 <= top < FRAMES else {"?"}
            text = " ".join([marker, *(s for c, s in PROSE_CLAIMS.items() if c in says)])
        else:
            text = marker
        want = {"path": path, "jev_v": jv, "model": model, "px": PX.get(path)}
        d = ai.get("_describe") if isinstance(ai.get("_describe"), dict) else {}
        got = {"recipes": [c.get("recipe") for c in cs], "hedge": [c.get("hedge") for c in cs],
               "images": [c.get("images") for c in cs], "keys": [c.get("key") for c in cs],
               "describe": {x: d.get(x) for x in want}, "description": ai.get("description"), "text": row["text"],
               "garments": ai.get("clothing_items"), "over": {o: ai.get(o) for o in OVER}}
        # the row's garment names come from those garments, only over a region Jev calls covered (never nude)
        want_over = {o: (name if ai.get(region) == "covered" and ai.get("clothing_state") != "fully_nude" else None)
                     for o, (region, name) in OVER.items()}
        # a clip: its scrub frames (400 px, its tint: the fake's key), as many as the duration ladder asks
        clip_ok = photo or (got["images"] == [DESCRIBE_FRAMES] * len(cs)
                            and got["keys"] == [clip_key(it["size"], it["tint"])] * len(cs))
        good = (got["recipes"] == [path] * len(cs) and got["hedge"] == [hedge] * len(cs) and clip_ok
                and (path != "prose" or (got["garments"] == PROSE_GARMENTS and got["over"] == want_over))
                and got["describe"] == want and got["description"] == text and jv is not None
                and row["text"] == text)
        groups[path][k] = (good, {"profile": it.get("jev") or it.get("clip"), "kind": it["kind"],
                                  "account_id": it["account_id"], "media_id": it["media_id"], "hedged": hedge,
                                  "want": {**want, "text": text, "hedge": hedge}, **got})
    # Coverage: a seeded (cached) or copied photo has no pass-1 describe, so not every profile need show up; the
    # prose rows must still keep AND drop each claim at least once, and both coin flips must reach v6.
    for name, path in ((JEV_DESCRIBE_PROSE, "prose"), (JEV_DESCRIBE_REVIEW, "v6")):
        g = groups[path]
        bad = {k: v for k, (ok, v) in g.items() if not ok}
        covered = {v["profile"] for _, v in g.values()}
        if path == "prose":
            kept = set().union(*(SAYS[p] for p in covered)) if covered else set()
            dropped = set().union(*(set(PROSE_CLAIMS) - SAYS[p] for p in covered)) if covered else set()
            enough = kept == dropped == set(PROSE_CLAIMS)
        else:
            enough = covered == REVIEW_PROFILES
        ctx.check(name, enough and not bad and not timed_out, rows=len(g), bad=len(bad),
                  covered=sorted(covered), sample=dict(list(bad.items())[:4]))
    # JEV_DESCRIBE_VIDEO: the vid rows (hedged and not), and every down clip skipped: `_jev` error, no describe call
    # in either sweep, its describe status untouched
    g = groups["vid"]
    bad = {k: v for k, (ok, v) in g.items() if not ok}
    hedged = Counter(v["hedged"] for _, v in g.values())
    for it in down_clips:
        k = it["key"]
        di = [s for s, c in di_calls if _key(c) == k and c["purpose"] == "describe"]
        j = _jev_of(pf.rows[k]) or {}
        statuses = [p.rows[k]["status"] for p, _ in phases]
        if j.get("status") != "error" or di or statuses != [rows0[k]["status"]] * len(phases):
            bad[k] = {"clip": DOWN, "jev": {x: j.get(x) for x in ("status", "error")}, "describe_calls": di,
                      "status": statuses, "seeded": rows0[k]["status"]}
    ctx.check(JEV_DESCRIBE_VIDEO, hedged[True] > 0 and hedged[False] > 0 and bool(down_clips) and not bad
              and not timed_out, rows=len(g), hedged=hedged[True], unhedged=hedged[False], down=len(down_clips),
              bad=len(bad), sample=dict(list(bad.items())[:4]))

    # JEV_UI_DESCRIBED / JEV_UI_VIDEO (last: opening an item changes nothing above)
    for name, path, kind, shot in ((JEV_UI_DESCRIBED, "prose", "photo", "vault-jev-described"),
                                   (JEV_UI_VIDEO, "vid", "video", "vault-jev-video")):
        if ctx.app is None:
            _check_ui(ctx, name, path, None)
            continue
        cands = [(v["media_id"], v["want"]["text"]) for ok, v in groups[path].values()
                 if ok and v["account_id"] == c0]
        got = await _ui_described(ctx, creators[0], cands, kind, shot)
        (ctx.out / f"ui-{shot}.json").write_text(json.dumps(got, indent=2, default=str))
        _check_ui(ctx, name, path, got)

    S._check_budgets(ctx)
    ctx.metric("phases", {f"{p.stage}_s": p.seconds for p, _ in phases})
    ctx.metric("vault_jev", {"calls": dict(Counter(f"{c['pass']}:{c['profile']}" for c in every)),
                             "pass1_calls": len(j1), "flags_calls": len(jf), "billed_mc": sum(total.values()),
                             "jev_plan": jev_plan})
