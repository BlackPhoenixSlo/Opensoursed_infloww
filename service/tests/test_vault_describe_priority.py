#!/usr/bin/env python3
"""
Vision sweeps: walk order + one call per duplicate set.

  case_priority_order_table:      newest 100 → OF folders → oldest 100 → rest;
                                  overlaps keep their best rank, no repeats.
  case_reuse_plan_table:          copy from a done member, else the best-ranked
                                  walked member (good before failed) leads.
  case_reuse_groups_are_the_dupe_sets:
                                  reuse sets == `find_duplicates` at threshold
                                  2: distance 2 shares, 3 from the seed does not.
  case_copy_builders_table:       copy columns, locks, `_copied_from` stamps,
                                  `_graded` stays the row's own, one flags blob.
  case_own_rerun_clears_copy_markers:
                                  an item's own describe / flags clears its mark.
  case_describe_all_one_call_per_duplicate:
                                  A/B re-upload pair + C (same thumb, other full
                                  frame): 1 describe call, A + C copied from B,
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
  case_clips_in_one_set_share:    same thumb + duration clips: 1 call.
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
        ([[1, 3]], {1}, set(), {}, {1: [3]}),                   # a done member walked anyway (forced) leads
        ([[1, 3]], {1}, {1}, {}, {1: [3]}),                     # done beats bad
        ([[8, 9]], {8}, set(), {}, {}),                         # nothing walked
        ([[2, 9]], set(), set(), {}, {}),                       # single walked, no source: plain item
        ([[1, 2], [3, 4, 5]], set(), set(), {}, {2: [1], 5: [4, 3]}),
    ]
    for groups, done, bad, copy_now, followers in cases:
        p = d.reuse_plan(groups, order, done, bad)
        assert p.copy_now == copy_now and p.followers == followers, (groups, done, bad, p)
    p = d.reuse_plan([[1, 2], [3, 4, 5]], order, set())
    assert p.riders() == {1, 4, 3}


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
    # copy marked only with its own source (11), not 99.
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
            # Clips by default: the qwen describe + flags these sweeps pay for are a
            # clip's (a photo's are Jev's; its reuse lives in test_vault_jev).
            extra = {"kind": "video", "duration_seconds": 20, **(cols or {}).get(mid, {})}
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
    # A (oldest) and B (newest) are one re-upload; C shares the thumb but not
    # the full frame — the Duplicates screen shows all three as one set, so
    # they share one answer (owner decision 2026-11-11).
    aid = await _world([(1, 1, 100, 200), (2, 3, 100, 200), (3, 2, 100, 300)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.n() == 1, f"a duplicate cost a describe call: {m.calls}"
    a, b, c = [await _row(aid, i) for i in (1, 2, 3)]
    assert all(r.describe_status == "described" for r in (a, b, c))
    # B is the newest → it led (priority, not the oldest seed).
    assert _ai(a).get("_copied_from") == 2 and _ai(c).get("_copied_from") == 2, (_ai(a), _ai(c))
    assert "_copied_from" not in _ai(b)
    assert a.video_description == b.video_description == c.video_description == "a photo"
    assert _ai(a).get("_flags_v") == vault_ai_vision._FLAGS_VERSION, "copy has stale flags"
    assert not {1, 3} & set(await vault_ai_vision._flags_todo(aid)), "copy would be re-flagged"
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog
    assert prog["cost_millicents"] == 5 + 5, prog  # 1 describe + 1 flags


async def case_already_described_member_is_the_source() -> None:
    aid = await _world([(1, 1, 110, 210), (2, 3, 110, 210)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
        assert m.n() == 1
        # A fresh re-upload of the same picture arrives.
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=3, kind="video", duration_seconds=20, tags="[]",
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
    assert (await _row(aid, 1)).video_description == "first"
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
    assert a.video_description == "second" and _ai(a)["_copied_from"] == 2, (a.video_description, _ai(a))


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
            r.describe_status, r.ai_fields_json, r.video_description = None, None, None
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


async def case_clips_in_one_set_share() -> None:
    clip = {"kind": "video", "duration_seconds": 20}
    aid = await _world([(1, 1, 180, 280), (2, 3, 180, 280)], {1: clip, 2: clip})
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.n() == 1, f"a clip set paid twice: {m.calls}"
    assert _ai(await _row(aid, 1)).get("_copied_from") == 2


async def case_reuse_groups_are_the_dupe_sets() -> None:
    # Hashes set directly (current kind → not re-hashed). Seed 1 at 0; 2 is 2
    # bits off (shares); 4 is 2 bits off the seed but 4 off 2 (still shares —
    # sets are seed-based); 3 is 3 bits off the seed (its own item).
    global _N
    _N += 1
    aid = f"reuse{_N}"
    dh = {1: 0b0, 2: 0b11, 3: 0b111, 4: 0b1100, 5: 0xFF00, 6: 0xFF03}
    async with get_session() as s:
        s.add(Account(id=aid))
        for mid, h in dh.items():
            s.add(VaultItem(account_id=aid, media_id=mid, kind="photo", tags="[]",
                            created_at=T0 + timedelta(days=mid),
                            content_hash=vault_dupes.pack_hash(f"{mid:032x}", h, h),
                            content_hash_kind=vault_dupes.HASH_KIND))
        await s.commit()
    res = await vault_dupes.find_duplicates(aid)
    assert res["threshold"] == vault_dupes.DEFAULT_THRESHOLD == 2
    sets = sorted([c["original"]["media_id"], *(x["media_id"] for x in c["dupes"])]
                  for c in res["clusters"])
    assert sets == [[1, 2, 4], [5, 6]], sets
    got = await vault_dupes.reuse_groups(aid, frozenset(dh))
    assert sorted(got) == sets, got
    # Only sets touching the sweep's `want`.
    assert await vault_dupes.reuse_groups(aid, frozenset({4})) == [[1, 2, 4]]
    assert await vault_dupes.reuse_groups(aid, frozenset({3})) == []


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
