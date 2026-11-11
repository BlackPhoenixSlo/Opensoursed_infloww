#!/usr/bin/env python3
"""
Vision sweeps: walk order + one call per duplicate set.

  case_priority_order_table:      newest 100 → OF folders → oldest 100 → rest;
                                  overlaps keep their best rank, no repeats.
  case_reuse_plan_table:          copy from a done member, else the best-ranked
                                  walked member (good before failed) leads.
  case_frame_groups_table:        a member joins only if it matches EVERY
                                  member (no two-hop reuse); OF dims must agree
                                  when both rows carry them.
  case_same_frame_measured:       the pixel test on 960x1280 textured frames:
                                  q85-95 re-encodes reuse; q70 does not; 20-60px
                                  sticker / blur patch / crop fail 40/40 each.
  case_copy_builders_table:       copy columns, locks, `_copied_from` stamps,
                                  `_graded` stays the row's own, one flags blob.
  case_own_rerun_clears_copy_markers:
                                  an item's own describe / flags clears its mark.
  case_describe_all_one_call_per_duplicate:
                                  A/B re-upload pair + C (same thumb, other full
                                  frame): 2 describe calls, A copied from B,
                                  progress 3/3, copy carries current flags.
  case_already_described_member_is_the_source:
                                  a new re-upload of a described item: 0 calls.
  case_redescribed_source_refreshes_its_copies:
                                  re-describing B rewrites A (`_copied_from`).
  case_failed_leader_leaves_its_copies_undescribed:
                                  its riders count failed, nothing copied.
  case_raising_leader_still_counts_its_riders:
                                  done == total when the paid visit raises.
  case_up_front_copies_survive_a_cap:
                                  copies of done items are made before the walk.
  case_clips_never_reuse:         same thumb + same preview clips: both called.
  case_dupe_scan_raising_still_sweeps:
                                  `find_duplicates` raising ⇒ every item called.
  case_flags_sweep_one_call_per_duplicate:
                                  flags-all: 1 flags call, follower stamped
                                  `_flags_copied_from`, both current.
  case_sweep_walks_priority_order: describe-all and `_flags_todo` walk
                                  `priority_order`, not created_at desc.

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_describe_priority.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import io  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import llm_client  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as d  # noqa: E402
import vault_dupes  # noqa: E402
import vault_frames  # noqa: E402
import vault_stills  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, VaultItem  # noqa: E402

T0 = datetime(2026, 1, 1)


# ── Pure tables ──────────────────────────────────────────────────────

def case_priority_order_table() -> None:
    def row(mid, day, folders=None):
        return (mid, T0 + timedelta(days=day), json.dumps(folders) if folders is not None else None)

    # 10 items, day == media_id; head=2 so the four ranks are visible.
    rows = [row(i, i) for i in range(1, 11)]
    rows[4] = row(5, 5, [77])     # mid-age, in a folder
    rows[9] = row(10, 10, [77])   # newest AND in a folder → rank 1 only
    rows[0] = row(1, 1, [])       # '[]' is no folder
    rows[1] = row(2, 2, None)     # NULL is no folder
    got = d.priority_order(rows, head=2)
    assert got == [10, 9, 5, 1, 2, 8, 7, 6, 4, 3], got
    assert len(got) == len(set(got)) == 10

    # Oldest-in-folder: rank 2 (folder) beats rank 3 (oldest).
    rows2 = [row(1, 1, [5]), row(2, 2), row(3, 3), row(4, 4)]
    assert d.priority_order(rows2, head=1) == [4, 1, 3, 2], d.priority_order(rows2, head=1)
    # Bad folder JSON reads as no folder; same-time ties break on media_id desc.
    rows3 = [(1, T0, "not json"), (2, T0, None), (3, T0, '["x"]')]
    assert d.priority_order(rows3, head=1) == [3, 1, 2], d.priority_order(rows3, head=1)
    # Fewer items than the head: plain newest first.
    assert d.priority_order([row(1, 1), row(2, 2)]) == [2, 1]
    assert d.priority_order([]) == []
    # The default head is 100.
    many = [row(i, i) for i in range(1, 301)]
    got = d.priority_order(many)
    assert got[:100] == list(range(300, 200, -1))
    assert got[100:200] == list(range(1, 101))
    assert got[200:] == list(range(200, 100, -1))


def case_reuse_plan_table() -> None:
    order = [5, 4, 3, 2, 1]  # walk order: 5 is the best rank
    cases = [
        # (groups, done, bad, copy_now, followers)
        ([[1, 3]], set(), set(), {}, {3: [1]}),                 # best-ranked walked leads
        ([[1, 3, 9]], {9}, set(), {1: 9, 3: 9}, {}),            # done non-walked member is the source
        ([[1, 3, 9]], set(), set(), {}, {3: [1]}),              # 9 not done: ignored
        ([[1, 3]], set(), {3}, {}, {1: [3]}),                   # failed last time: leads last
        ([[8, 9]], {8}, set(), {}, {}),                         # nothing walked
        ([[2, 9]], set(), set(), {}, {}),                       # single walked, no source: plain item
        ([[1, 2], [3, 4, 5]], set(), set(), {}, {2: [1], 5: [4, 3]}),
    ]
    for groups, done, bad, copy_now, followers in cases:
        p = d.reuse_plan(groups, order, done, bad)
        assert p.copy_now == copy_now and p.followers == followers, (groups, done, bad, p)
    p = d.reuse_plan([[1, 2], [3, 4, 5]], order, set())
    assert p.riders() == {1, 4, 3}


def case_frame_groups_table() -> None:
    def m(mid, w=None, h=None):
        return {"media_id": mid, "width": w, "height": h}

    same = {frozenset((1, 3)), frozenset((2, 5)), frozenset((1, 4)), frozenset((3, 4))}

    def S(a, b):
        return frozenset((a["media_id"], b["media_id"])) in same

    G = vault_dupes.frame_groups
    assert G([m(1), m(2), m(3), m(4), m(5)], S) == [[1, 3, 4], [2, 5]]
    # 3 matches 1's frame but OF says it is another shape → its own.
    assert G([m(1, 1080, 1920), m(3, 1920, 1080)], S) == []
    assert G([m(1, 1080, 1920), m(3)], S) == [[1, 3]], "one row without dims: the frame decides"
    assert G([], S) == []
    # 4 matches 1 but not 3: in a greedy-vs-first rule 3 and 4 would share an
    # answer without ever being compared → 4 must stay out.
    same.discard(frozenset((3, 4)))
    assert G([m(1), m(3), m(4)], S) == [[1, 3]]


def _textured(seed: int):
    """A 960x1280 photo-like frame: sharp shapes + sensor-like noise (σ 8)."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    rng = random.Random(seed)
    im = Image.new("RGB", (960, 1280), (rng.randrange(256), 120, rng.randrange(256)))
    dr = ImageDraw.Draw(im)
    for _ in range(30):
        x0, y0 = rng.randrange(960), rng.randrange(1280)
        dr.ellipse([x0, y0, x0 + rng.randrange(40, 400), y0 + rng.randrange(40, 400)],
                   fill=tuple(rng.randrange(256) for _ in range(3)))
    im = im.filter(ImageFilter.GaussianBlur(1))
    noise = Image.effect_noise((960, 1280), 8).convert("RGB")
    return ImageChops.add(ImageChops.subtract(im, Image.new("RGB", im.size, (12, 12, 12))),
                          noise, 2.0, -52)


def case_same_frame_measured() -> None:
    """The numbers in `vault_dupes`' FRAME_MAX_DIFF comment, re-run on synthetic
    frames (the real-photo half of that measurement is not shipped)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageStat
    rng = random.Random(7)
    root = _TMP / "frames"
    root.mkdir(parents=True, exist_ok=True)
    n = 0

    def save(im, q) -> Path:
        nonlocal n
        n += 1
        p = root / f"{n}.jpg"
        im.save(p, format="JPEG", quality=q)
        return p

    origs = []
    for i in range(4):
        p = save(_textured(i), 85)
        origs.append((p, Image.open(p).convert("RGB")))
    # One cluster: each member's file read once, pixels decoded at most once,
    # however many pairs are compared (reuse_groups' path).
    opened: list = []
    real_open = Image.open

    def counting_open(fp, *a, **k):
        opened.append(fp)
        return real_open(fp, *a, **k)

    Image.open = counting_open
    try:
        frames = [vault_dupes.load_frame(p) for p, _ in origs]
        for fa in frames:
            for fb in frames:
                vault_dupes.frames_match(fa, fb)
    finally:
        Image.open = real_open
    assert len(opened) == 2 * len(origs), ("header + one decode per member", opened)

    for p, im in origs:
        assert vault_dupes.same_frame(p, p)
        for q in (85, 90, 95):
            assert vault_dupes.same_frame(p, save(im, q)), f"q{q} re-encode refused"
        assert not vault_dupes.same_frame(p, save(im, 70)), "q70 re-encode is 'unsure' → no reuse"
    fails = {"sticker": 0, "blur": 0, "crop": 0}
    for t in range(40):
        p, o = origs[t % len(origs)]
        s = rng.randrange(20, 61)
        x, y = rng.randrange(0, 960 - s), rng.randrange(0, 1280 - s)
        e = o.copy()
        ImageDraw.Draw(e).rectangle([x, y, x + s, y + s], fill=tuple(rng.randrange(256) for _ in range(3)))
        fails["sticker"] += not vault_dupes.same_frame(p, save(e, rng.choice((70, 85, 95))))
        # a censor goes over detail: the busiest of 20 candidate spots
        x, y = max(((rng.randrange(0, 960 - s), rng.randrange(0, 1280 - s)) for _ in range(20)),
                   key=lambda c: sum(ImageStat.Stat(o.crop((c[0], c[1], c[0] + s, c[1] + s))).stddev))
        e = o.copy()
        box = (x, y, x + s, y + s)
        e.paste(o.crop(box).filter(ImageFilter.GaussianBlur(rng.choice((4, 6, 8)))), box)
        fails["blur"] += not vault_dupes.same_frame(p, save(e, rng.choice((70, 85, 95))))
        c = rng.uniform(0.02, 0.10)
        e = o.crop((int(960 * c), int(1280 * c), 960, 1280)).resize((960, 1280), Image.LANCZOS)
        fails["crop"] += not vault_dupes.same_frame(p, save(e, rng.choice((70, 85, 95))))
    assert fails == {"sticker": 40, "blur": 40, "crop": 40}, fails
    # other size / unreadable / missing → no
    small = save(origs[0][1].resize((480, 640)), 85)
    assert not vault_dupes.same_frame(origs[0][0], small)
    bad = root / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert not vault_dupes.same_frame(origs[0][0], bad)
    assert not vault_dupes.same_frame(origs[0][0], root / "missing.jpg")


def case_copy_builders_table() -> None:
    src_ai = {"description": "d", "_prompt_version": "v2", "underwear_visible": True,
              "vulva_vis": "covered", "breasts_vis": "bare", "anus_vis": "not_in_frame",
              "over_vulva": "thong", "_flags_v": 3, "_flags_model": "m"}
    src = {"ai_fields_json": json.dumps(src_ai), "describe_model": "qwen3-vl-30b",
           "describe_call_id": 7, "frames_sampled": None, "tip_vault_flag": True,
           "tags": '["a"]', "explicitness_tier": "explicit", "description": "d",
           "video_description": None, "search_text": "d a"}
    now = datetime(2026, 11, 10)
    v = d.build_copy_update(src, prev_ai={"breasts_vis": "covered"}, locked=(),
                            overrides={}, fixable=("vulva_vis",), src_id=11, now=now)
    assert set(v) == {"describe_status", "describe_model", "describe_call_id",
                      "describe_generated_at", "ai_fields_json", "frames_sampled",
                      "tip_vault_flag", "tags", "explicitness_tier", "description",
                      "video_description", "search_text"}, sorted(v)
    ai = json.loads(v["ai_fields_json"])
    assert ai["_copied_from"] == 11 and ai["_flags_v"] == 3 and ai["breasts_vis"] == "bare", ai
    assert v["describe_status"] == "described" and v["tags"] == '["a"]' and v["describe_generated_at"] == now

    # The copy's own locks + locked dispute fixes win.
    v = d.build_copy_update(src, prev_ai={}, locked={"description", "tags", "vulva_vis"},
                            overrides={"vulva_vis": "bare", "description": "mine"},
                            fixable=("vulva_vis",), src_id=11, now=now)
    assert "description" not in v and "video_description" not in v and "tags" not in v, v
    assert json.loads(v["ai_fields_json"])["vulva_vis"] == "bare"

    # A source never flagged keeps the copy's own flags.
    src_nf = {**src, "ai_fields_json": json.dumps({"description": "d"})}
    prev = {"underwear_visible": False, "vulva_vis": "not_in_frame", "breasts_vis": "covered",
            "anus_vis": "not_in_frame", "_flags_v": 3}
    ai = json.loads(d.build_copy_update(src_nf, prev_ai=prev, locked=(), overrides={},
                                        fixable=(), src_id=11, now=now)["ai_fields_json"])
    assert ai["breasts_vis"] == "covered" and ai["_flags_v"] == 3 and "_flags_copied_from" not in ai, ai

    # Flags copy: merge, locks kept, failure stamps dropped, marker stamped.
    f = d.build_flags_copy({"description": "own", "breasts_vis": "covered", "_flags_status": "error"},
                           src_ai, locked={"breasts_vis"}, src_id=11)
    assert f["description"] == "own" and f["breasts_vis"] == "covered", f
    assert f["vulva_vis"] == "covered" and f["over_vulva"] == "thong" and f["_flags_v"] == 3
    assert "_flags_status" not in f and f["_flags_copied_from"] == 11, f

    # Never transitive: a source that itself holds flags copied from 99 gives a
    # copy marked only with the item it was compared with (11), not 99.
    src_t = {**src, "ai_fields_json": json.dumps({**src_ai, "_flags_copied_from": 99})}
    ai = json.loads(d.build_copy_update(src_t, prev_ai={"_flags_copied_from": 5}, locked=(),
                                        overrides={}, fixable=(), src_id=11,
                                        now=now)["ai_fields_json"])
    assert ai["_copied_from"] == 11 and "_flags_copied_from" not in ai, ai
    assert ai["_flags_v"] == 3 and ai["breasts_vis"] == "bare", ai

    # `_graded` is the row's own: never the source's, the copy keeps its own.
    src_g = {**src, "ai_fields_json": json.dumps({**src_ai, "_graded": {"v": 3}})}
    ai = json.loads(d.build_copy_update(src_g, prev_ai={}, locked=(), overrides={},
                                        fixable=(), src_id=11, now=now)["ai_fields_json"])
    assert "_graded" not in ai, ai
    ai = json.loads(d.build_copy_update(src_g, prev_ai={"_graded": {"v": 1}}, locked=(),
                                        overrides={}, fixable=(), src_id=11,
                                        now=now)["ai_fields_json"])
    assert ai["_graded"] == {"v": 1}, ai

    # One flags blob: a source's failure record travels with its flags; a
    # copy's old one does not survive a copy from a source without one.
    src_fail = {**src, "ai_fields_json": json.dumps({**src_ai, "_flags_status": "unparsed"})}
    ai = json.loads(d.build_copy_update(src_fail, prev_ai={}, locked=(), overrides={},
                                        fixable=(), src_id=11, now=now)["ai_fields_json"])
    assert ai["_flags_status"] == "unparsed", ai
    ai = json.loads(d.build_copy_update(src, prev_ai={"_flags_status": "error"}, locked=(),
                                        overrides={}, fixable=(), src_id=11,
                                        now=now)["ai_fields_json"])
    assert "_flags_status" not in ai, ai
    assert set(d.FLAGS_BLOB_KEYS) >= {"_flags_v", "_flags_status", "_flags_copied_from",
                                      "over_vulva", "vulva_vis"}


def case_own_rerun_clears_copy_markers() -> None:
    prev = {"description": "copied", "_copied_from": 11, "_flags_copied_from": 12,
            "underwear_visible": False, "vulva_vis": "covered", "breasts_vis": "covered",
            "anus_vis": "not_in_frame", "_flags_v": 3, "_flags_status": "error"}
    vals = d.build_describe_update(
        False, {"description": "own", "tags": []}, prev_ai=prev, locked=set(), overrides={},
        used_model="m", n_frames=1, pv="v2", fixable=(), call_id=1, now=datetime(2026, 11, 10))
    ai = json.loads(vals["ai_fields_json"])
    assert "_copied_from" not in ai, "an own describe still claims to be a copy"
    # the flags it kept are still the copied ones, failure record included
    assert ai["_flags_copied_from"] == 12 and ai["_flags_status"] == "error", ai
    f = d.build_flags_fields(prev, [{"underwear_visible": True, "vulva_vis": "bare",
                                     "breasts_vis": "bare", "anus_vis": "not_in_frame"}],
                             locked=set(), is_video=False, model="m", version=3)
    assert "_flags_copied_from" not in f and "_flags_status" not in f, f
    assert f["_copied_from"] == 11, "the description is still the copied one"


# ── DB cases (real describe/flags paths, faked frames + LLM) ─────────

_TMP = Path(tempfile.mkdtemp(prefix="vault-reuse-"))
vault_stills.THUMB_DIR = _TMP / "thumbs"
vault_stills.IMAGE_DIR = _TMP / "images"


async def _key(*_a, **_k) -> bool:
    return True


llm_client.llm_key_available = _key


def _jpeg(seed: int, size=(64, 48)) -> bytes:
    from PIL import Image
    rng = random.Random(seed)
    im = Image.new("RGB", size)
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(size[0] * size[1])])
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


_N = 0


async def _world(items: list[tuple[int, int, int, int]], cols: dict | None = None) -> str:
    """items: (media_id, day, thumb_seed, full_seed). Returns the account id."""
    global _N
    _N += 1
    aid = f"reuse{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1000))
        for mid, day, ts, fs in items:
            for root, seed in ((vault_stills.THUMB_DIR, ts), (vault_stills.IMAGE_DIR, fs)):
                (root / aid).mkdir(parents=True, exist_ok=True)
                (root / aid / f"{mid}.jpg").write_bytes(_jpeg(seed))
            extra = {"kind": "photo", **(cols or {}).get(mid, {})}
            s.add(VaultItem(account_id=aid, media_id=mid, tags="[]",
                            created_at=T0 + timedelta(days=day), **extra))
        await s.commit()
    return aid


_DATA_URL = "data:image/jpeg;base64," + __import__("base64").b64encode(_jpeg(1, (8, 8))).decode()


class _Model:
    """Fake `llm_client.chat` + `vault_frames.collect`: counts calls per purpose."""

    def __init__(self, text: str = "a photo") -> None:
        self.calls: list[str] = []
        self.text = text

    async def chat(self, **kw):
        self.calls.append(kw["purpose"])
        if kw["purpose"] == "describe_flags":
            body = {"underwear_visible": False, "vulva_vis": "not_in_frame",
                    "breasts_vis": "covered", "anus_vis": "not_in_frame",
                    "over_breasts": "black top"}
        else:
            body = {"description": self.text, "tags": ["t"], "explicitness": "suggestive"}

        class R:
            content = json.dumps(body)
            cost_cents = 5
            call_id = 1
        return R()

    async def collect(self, *_a, **_k):
        return vault_frames.Collected([_DATA_URL], "ok")

    def __enter__(self):
        self._o = (llm_client.chat, vault_frames.collect)
        llm_client.chat, vault_frames.collect = self.chat, self.collect
        return self

    def __exit__(self, *_):
        llm_client.chat, vault_frames.collect = self._o

    def n(self, purpose: str = "describe_media") -> int:
        return sum(1 for c in self.calls if c == purpose)


async def _row(aid: str, mid: int) -> VaultItem:
    async with get_session() as s:
        return await s.get(VaultItem, (aid, mid))


def _ai(row: VaultItem) -> dict:
    return json.loads(row.ai_fields_json or "{}")


async def case_describe_all_one_call_per_duplicate() -> None:
    # A (oldest) and B (newest) are one re-upload; C shares the thumb only.
    aid = await _world([(1, 1, 100, 200), (2, 3, 100, 200), (3, 2, 100, 300)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.n() == 2, f"a duplicate cost a describe call: {m.calls}"
    a, b, c = [await _row(aid, i) for i in (1, 2, 3)]
    assert all(r.describe_status == "described" for r in (a, b, c))
    # B is the newest → it led (priority, not the oldest seed).
    assert _ai(a).get("_copied_from") == 2, _ai(a)
    assert "_copied_from" not in _ai(b) and "_copied_from" not in _ai(c)
    assert a.description == b.description == "a photo"
    assert _ai(a).get("_flags_v") == vault_ai_vision._FLAGS_VERSION, "copy has stale flags"
    assert 1 not in await vault_ai_vision._flags_todo(aid), "copy would be re-flagged"
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog
    assert prog["cost_millicents"] == 2 * 5 + 2 * 5, prog  # 2 describes + 2 flags


async def case_already_described_member_is_the_source() -> None:
    aid = await _world([(1, 1, 110, 210), (2, 3, 110, 210)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
        assert m.n() == 1
        # A fresh re-upload of the same picture arrives.
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=3, kind="photo", tags="[]",
                            created_at=T0 + timedelta(days=9)))
            await s.commit()
        for root in (vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR):
            (root / aid / "3.jpg").write_bytes(_jpeg(110 if root == vault_stills.THUMB_DIR else 210))
        m.calls.clear()
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.calls == [], f"the new re-upload was paid for: {m.calls}"
    r3 = await _row(aid, 3)
    assert r3.describe_status == "described" and _ai(r3)["_copied_from"] in (1, 2), _ai(r3)
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 1 and prog["cost_millicents"] == 0, prog


async def case_redescribed_source_refreshes_its_copies() -> None:
    aid = await _world([(1, 1, 120, 220), (2, 3, 120, 220)])
    with _Model("first") as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert (await _row(aid, 1)).description == "first"
    # B alone needs work again; the dupe scan finds nothing this time — the
    # `_copied_from` marker alone must carry the refresh.
    async with get_session() as s:
        (await s.get(VaultItem, (aid, 2))).describe_status = None
        await s.commit()
    o = vault_dupes.reuse_groups

    async def _none(_aid, _want):
        return []
    vault_dupes.reuse_groups = _none
    try:
        with _Model("second") as m:
            await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_dupes.reuse_groups = o
    assert m.n() == 1
    a = await _row(aid, 1)
    assert a.description == "second" and _ai(a)["_copied_from"] == 2, (a.description, _ai(a))


async def case_dupe_scan_raising_still_sweeps() -> None:
    aid = await _world([(1, 1, 130, 230), (2, 3, 130, 230)])
    o = vault_dupes.find_duplicates

    async def _boom(*_a, **_k):
        raise RuntimeError("PIL exploded")
    vault_dupes.find_duplicates = _boom
    try:
        with _Model() as m:
            await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_dupes.find_duplicates = o
    assert m.n() == 2, f"no-dupe fallback should describe both: {m.calls}"
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 2 and not prog.get("aborted"), prog


async def case_flags_sweep_one_call_per_duplicate() -> None:
    aid = await _world([(1, 1, 140, 240), (2, 3, 140, 240), (3, 2, 141, 241)],
                       {i: {"describe_status": "described",
                            "ai_fields_json": json.dumps({"description": "x"})} for i in (1, 2, 3)})
    with _Model() as m:
        await vault_ai_vision._run_flags_all(aid, await vault_ai_vision._flags_todo(aid))
    assert m.n("describe_flags") == 2, m.calls
    a = _ai(await _row(aid, 1))
    assert a.get("_flags_copied_from") == 2 and a["description"] == "x", a
    assert await vault_ai_vision._flags_todo(aid) == [], "a flags copy is not current"
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog


async def case_failed_leader_leaves_its_copies_undescribed() -> None:
    aid = await _world([(1, 1, 150, 250), (2, 3, 150, 250)])
    o = vault_ai_vision._describe_one
    seen: list[int] = []

    async def _fail(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": False, "status": "error", "detail": "provider 502"}
    vault_ai_vision._describe_one = _fail
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_one = o
    assert seen == [2], seen
    assert (await _row(aid, 1)).describe_status is None
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 2 and prog["failed"] == 2, prog
    assert prog["error"] == "provider 502", prog


async def case_raising_leader_still_counts_its_riders() -> None:
    aid = await _world([(1, 1, 160, 260), (2, 3, 160, 260)])
    o = vault_ai_vision._describe_and_flag

    async def _boom(_aid, mid, **_k):
        raise RuntimeError("OF read blew up")
    vault_ai_vision._describe_and_flag = _boom
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_and_flag = o
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 2 and prog["failed"] == 2, prog
    assert "RuntimeError" in prog["error"], prog


async def case_up_front_copies_survive_a_cap() -> None:
    # 1 is described; 2 is its re-upload; 3 is unrelated and trips the cap.
    aid = await _world([(1, 1, 170, 270), (2, 3, 170, 270), (3, 5, 171, 271)])
    with _Model():
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    async with get_session() as s:
        for mid in (2, 3):
            r = await s.get(VaultItem, (aid, mid))
            r.describe_status, r.ai_fields_json, r.description = None, None, None
        await s.commit()
    o = vault_ai_vision._describe_one
    seen: list[int] = []

    async def _capped(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": False, "status": "capped", "detail": "cap"}
    vault_ai_vision._describe_one = _capped
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_one = o
    assert seen == [3], seen
    r2 = await _row(aid, 2)
    assert r2.describe_status == "described" and _ai(r2)["_copied_from"] == 1, _ai(r2)
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["capped"] and prog["total"] == prog["done"] == 2 and prog["failed"] == 1, prog


async def case_clips_never_reuse() -> None:
    clip = {"kind": "video", "duration_seconds": 20}
    aid = await _world([(1, 1, 180, 280), (2, 3, 180, 280)], {1: clip, 2: clip})
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.n() == 2, f"a clip shared an answer off one poster: {m.calls}"
    assert "_copied_from" not in _ai(await _row(aid, 1))


async def case_sweep_walks_priority_order() -> None:
    # 120 distinct items, newest = highest id; 3 is in a folder.
    items = [(i, i, 1000 + i, 2000 + i) for i in range(1, 121)]
    aid = await _world(items, {3: {"of_folder_ids": "[42]"}})
    seen: list[int] = []
    o = vault_ai_vision._describe_one

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": False, "status": "error", "detail": "spy"}
    vault_ai_vision._describe_one = _spy
    o_conc = vault_ai_vision._DESCRIBE_CONCURRENCY
    vault_ai_vision._DESCRIBE_CONCURRENCY = 1  # serial, so arrival order == walk order
    try:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_one = o
        vault_ai_vision._DESCRIBE_CONCURRENCY = o_conc
    want = list(range(120, 20, -1)) + [3] + list(range(1, 3)) + list(range(4, 21))
    assert seen == want, seen[:5] + ["…"] + seen[98:105]
    assert await vault_ai_vision._flags_todo(aid) == want


_harness.run()
