#!/usr/bin/env python3
"""
Vision sweeps: walk order + one call per duplicate set.

  case_priority_order_table:      fixed rounds: next `fold` folders (newest
                                  first) → next `top` newest → next `bottom`
                                  oldest; first rank wins, no repeats.
  case_priority_folder_rank:      rail order first, then uncached folders by
                                  newest item; no cache → all by newest item.
  case_rail_folder_ids_table:     custom + hasMedia only, page order, deduped.
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
  case_redescribed_source_leaves_former_members:
                                  re-describing B leaves A (marked its copy, no
                                  longer in its set) alone (W30 F8).
  case_click_describe_carries_the_set:
                                  the single describe of a copy calls it and
                                  its whole current set takes the answer.
  case_click_describe_hides_unseen_set_members:
                                  a folder-limited caller's click writes the
                                  whole set; `extra` lists only ids it sees.
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
  case_flags_probe_carries_the_set:
                                  flags-all `media_ids`: the set copies its flags.
  case_sweep_walks_priority_order: describe-all and `_flags_todo` walk
                                  `priority_order`, not created_at desc.
  case_sweep_reads_cached_rail:   the folder rank comes from the cached
                                  /vault/lists pages; no cache → newest item.
  case_describe_all_limit:        `limit` walks the first N in priority order;
                                  the POST passes it (0 / junk = no limit).
  case_describe_all_met_target_is_zero_work:
                                  met `target` → 200 done, nothing started,
                                  claim released, even capped / keyless.
  case_describe_all_bad_target_is_400:
                                  junk target → bad_target; with force /
                                  restage → target_needs_undescribed.
  case_target_sweep_walks_the_remaining_slice:
                                  plan `target_remaining` == the walk: priority
                                  order minus Terminal failures, cut (and `limit`).
  case_target_sweep_never_writes_a_terminal_copy:
                                  a Terminal row marked a copy of a walked
                                  source stays byte-identical; an undescribed
                                  copy past the cut is refreshed (`walked` =
                                  the cut).
  case_target_sweep_skips_terminal_dupe_members:
                                  real dupe sets: a Terminal member is neither
                                  a follower nor a `copy_now` target.

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_describe_priority.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
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
from _jev_fixtures import video_jev  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, VaultItem  # noqa: E402

T0 = datetime(2026, 1, 1)


# ── Pure tables ──────────────────────────────────────────────────────

def _prow(mid, day, folders=None):
    return (mid, T0 + timedelta(days=day) if day is not None else None,
            json.dumps(folders) if folders is not None else None)


def case_priority_order_table() -> None:
    # No folders, top=3 / bottom=2: the same round over and over.
    rows = [_prow(i, i) for i in range(1, 31)]
    got = d.priority_order(rows, top=3, bottom=2)
    want = [30, 29, 28, 1, 2, 27, 26, 25, 3, 4, 24, 23, 22, 5, 6, 21, 20, 19, 7, 8,
            18, 17, 16, 9, 10, 15, 14, 13, 11, 12]
    assert got == want, got
    # Folders lead their round, each newest first; an item already taken
    # (newest AND in a folder) keeps its first rank; '[]' / NULL / bad JSON = no folder.
    rows = [_prow(1, 1, []), _prow(2, 2), (3, T0 + timedelta(days=3), "not json"),
            _prow(4, 4, [7]), _prow(5, 5), _prow(6, 6, [7, 8]), _prow(7, 7), _prow(8, 8, [9])]
    # folders by newest item: 9 (8), 7 (6), 8 (6)
    got = d.priority_order(rows, fold=1, top=1, bottom=1)
    assert got == [8, 7, 1, 6, 4, 5, 2, 3], got
    assert len(got) == len(set(got)) == 8
    # fold=2: two folders before the first newest pull.
    assert d.priority_order(rows, fold=2, top=1, bottom=1) == [8, 6, 4, 7, 1, 5, 2, 3]
    # top=0: folders + oldest only, until the folders run out.
    assert d.priority_order(rows, fold=1, top=0, bottom=1) == [8, 1, 6, 4, 2, 3, 5, 7]
    # top=bottom=0: folders, then the rest newest first (no endless loop).
    assert d.priority_order(rows, fold=1, top=0, bottom=0) == [8, 6, 4, 7, 5, 3, 2, 1]
    # Same-time ties break on media_id desc; NULL created_at is oldest.
    assert d.priority_order([(1, T0, None), (2, T0, None), (3, None, None)],
                            top=1, bottom=1) == [2, 3, 1]
    assert d.priority_order([_prow(1, 1), _prow(2, 2)]) == [2, 1]
    assert d.priority_order([]) == []
    # The defaults: fold 10, top 500, bottom 100.
    assert (d.PRIORITY_FOLD, d.PRIORITY_TOP, d.PRIORITY_BOTTOM) == (10, 500, 100)
    many = [_prow(i, i) for i in range(1, 2001)]
    got = d.priority_order(many)
    assert got[:500] == list(range(2000, 1500, -1))
    assert got[500:600] == list(range(1, 101))
    assert got[600:1100] == list(range(1500, 1000, -1))
    assert got[1100:1200] == list(range(101, 201))
    assert sorted(got) == list(range(1, 2001))
    folders = [_prow(i, i, [1000 + i]) for i in range(1, 26)] + [_prow(i, i) for i in range(26, 1000)]
    got = d.priority_order(folders)
    assert got[:10] == list(range(25, 15, -1)), got[:10]      # 10 folders, newest item first
    assert got[10:510] == list(range(999, 499, -1))
    assert got[510:525] == list(range(1, 16))                  # oldest, incl. folders not reached yet


def case_priority_folder_rank() -> None:
    # 20 items, day == id; folder 100 = {20, 5, 3}, 200 = {12}, 300 = {18}, 400 = {7}.
    fol = {20: [100], 5: [100], 3: [100], 12: [200], 18: [300], 7: [400]}
    rows = [_prow(i, i, fol.get(i)) for i in range(1, 21)]
    kw = {"fold": 1, "top": 1, "bottom": 1}
    # Rail: 200, 100, then 999 (no item here → dropped); 300 / 400 uncached → by newest item.
    got = d.priority_order(rows, [200, 100, 999, 200], **kw)
    assert got == [12, 20, 1, 5, 3, 19, 2, 18, 17, 4, 7, 16, 6, 15, 8, 14, 9, 13, 10, 11], got
    # No cache: every folder by its newest item (100, 300, 200, 400).
    got = d.priority_order(rows, **kw)
    assert got == [20, 5, 3, 19, 1, 18, 17, 2, 12, 16, 4, 7, 15, 6, 14, 8, 13, 9, 11, 10], got
    assert d.priority_order(rows, [], **kw) == got


def case_rail_folder_ids_table() -> None:
    def f(i, type_="custom", media=True):
        return {"id": i, "type": type_, "hasMedia": media}
    pages = [
        {"list": [f(None), f(3), {"type": "messages", "id": 9, "hasMedia": True},
                  f(4, media=False), f(5), "junk", f("x")], "hasMore": True},
        None,
        {"list": [f(5), f("6")]},
        {},
    ]
    assert d.rail_folder_ids(pages) == [3, 5, 6]
    assert d.rail_folder_ids([]) == []


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
    # A named run: each lead is called; the rest of its set follows its first lead, answered or not.
    for groups, leads, followers in (([[1, 3, 9]], [3], {3: [1, 9]}), ([[1, 3, 9]], [9, 1], {9: [3]}),
                                     ([[1, 2], [3, 4]], [4], {4: [3]}), ([[1, 2]], [7], {})):
        p = d.lead_plan(groups, leads)
        assert p.copy_now == {} and p.followers == followers, (groups, leads, p)


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
            # Clips by default, each with a current `_jev` (D54: the qwen describe these
            # sweeps pay for is fed it; flags are stamped from it, never a qwen call — the
            # Jev pass and a photo's reuse live in test_vault_jev).
            extra = {"kind": "video", "duration_seconds": 20, "ai_fields_json": json.dumps({"_jev": video_jev()}),
                     **(cols or {}).get(mid, {})}
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
    assert prog["cost_millicents"] == 5, prog  # 1 describe; flags from the current `_jev`, no call
    assert "describe_flags" not in m.calls, m.calls


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


async def case_redescribed_source_leaves_former_members() -> None:
    aid = await _world([(1, 1, 120, 220), (2, 3, 120, 220)])
    with _Model("first") as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert (await _row(aid, 1)).video_description == "first"
    # B alone needs work again; the dupe scan no longer puts A in B's set (a
    # re-hash / an older seed changed it) — A's old `_copied_from` marker must
    # not write B's new answer over it.
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
    assert a.video_description == "first" and _ai(a)["_copied_from"] == 2, (a.video_description, _ai(a))


async def case_click_describe_carries_the_set() -> None:
    aid = await _world([(1, 1, 125, 225), (2, 3, 125, 225), (3, 2, 125, 225)])
    with _Model("first") as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert _ai(await _row(aid, 1)).get("_copied_from") == 2
    # Click Describe on A, a copy: it is called anyway, and B (its source) and C take the new answer.
    with _Model("second") as m:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 1})
    assert m.n() == 1 and out["ok"], (m.calls, out)
    rows = {i: await _row(aid, i) for i in (1, 2, 3)}
    assert {i: r.video_description for i, r in rows.items()} == {1: "second", 2: "second", 3: "second"}
    assert "_copied_from" not in _ai(rows[1]) and _ai(rows[2])["_copied_from"] == _ai(rows[3])["_copied_from"] == 1
    assert sorted(e["media_id"] for e in out["extra"]) == [2, 3], out


async def case_click_describe_hides_unseen_set_members() -> None:
    """W30 C1: a folder-limited chatter's click still writes the whole set (it shares one answer), but the
    response lists only the members it may see; an unrestricted caller's lists all (above)."""
    import vault_ai_api
    aid = await _world([(1, 1, 126, 226), (2, 3, 126, 226), (3, 2, 126, 226)],
                       cols={1: {"of_folder_ids": "[77]"}, 2: {"of_folder_ids": "[77]"},
                             3: {"of_folder_ids": "[88]"}})
    orig = vault_ai_api.allowed_folder_ids_for_chatter

    async def gate(_account_id):
        return frozenset({77})
    vault_ai_api.allowed_folder_ids_for_chatter = gate
    try:
        with _Model("scoped") as m:
            out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 1})
    finally:
        vault_ai_api.allowed_folder_ids_for_chatter = orig
    assert m.n() == 1 and out["ok"], (m.calls, out)
    rows = {i: await _row(aid, i) for i in (1, 2, 3)}
    assert {i: r.video_description for i, r in rows.items()} == {1: "scoped", 2: "scoped", 3: "scoped"}
    assert [e["media_id"] for e in out["extra"]] == [2], out


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
                            "ai_fields_json": json.dumps({"description": "x", "_jev": video_jev()})}
                        for i in (1, 2, 3)})
    # D54: a clip's flags are stamped from its `_jev` (current here: nothing to pay), never a qwen call; a set's
    # one-Jev-per-duplicate is test_vault_jev's (case_dupe_followers_get_the_leaders_jev).
    with _Model() as m:
        await vault_ai_vision._run_flags_all(aid, await vault_ai_vision._flags_todo(aid))
    assert m.calls == [], m.calls
    a = _ai(await _row(aid, 1))
    assert a["_flags_model"] == "jev" and a["description"] == "x", a
    assert await vault_ai_vision._flags_todo(aid) == [], "a flags copy is not current"
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog


async def case_flags_probe_carries_the_set() -> None:
    """W30 F8: flags-all with `media_ids` stamps the named item and its set's other members copy its flags."""
    aid = await _world([(1, 1, 142, 242), (2, 3, 142, 242), (3, 2, 142, 242)],
                       {i: {"describe_status": "described",
                            "ai_fields_json": json.dumps({"description": "x", "_jev": video_jev()})}
                        for i in (1, 2, 3)})
    with _Model() as m:
        out = await vault_ai_vision.flags_all({"account_id": aid, "media_ids": [1]})
    assert m.calls == [] and out["flagged"] == 1 and out["complete"], (m.calls, out)
    assert [_ai(await _row(aid, i)).get("_flags_copied_from") for i in (1, 2, 3)] == [None, 1, 1]


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


class _NoStop:
    """A walk-order test's visits all fail cheaply (and this box has no NudeNet): neither the breaker nor Jev's
    server stop (`vault_jev_pass.fatal`) is under test here — test_vault_jev / test_vault_sweep_stop own them."""

    def __enter__(self):
        import vault_jev_pass
        import vault_sweep
        self._o = (vault_sweep.BREAK_AFTER, vault_jev_pass.fatal)

        async def _quiet(*_a, **_k):
            return None
        vault_sweep.BREAK_AFTER, vault_jev_pass.fatal = 10**9, _quiet
        return self

    def __exit__(self, *_e):
        import vault_jev_pass
        import vault_sweep
        vault_sweep.BREAK_AFTER, vault_jev_pass.fatal = self._o


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
        with _NoStop():
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
        with _NoStop():
            await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_one = o
        vault_ai_vision._DESCRIBE_CONCURRENCY = o_conc
    want = [3] + list(range(120, 3, -1)) + [2, 1]   # folder, then the top 500 = the rest
    assert seen == want, seen[:5] + ["…"] + seen[-5:]
    # the Jev pass ahead of each describe stamped every clip's flags; the flags walk is the same order
    assert await vault_ai_vision._flags_todo(aid) == []
    assert await vault_ai_vision._flags_todo(aid, force=True) == want



async def _spy_walk(aid: str, **kw) -> list[int]:
    """The describe sweep's walk, serial, every visit a cheap refusal."""
    seen: list[int] = []
    o, o_conc = vault_ai_vision._describe_one, vault_ai_vision._DESCRIBE_CONCURRENCY

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": False, "status": "error", "detail": "spy"}
    vault_ai_vision._describe_one = _spy
    vault_ai_vision._DESCRIBE_CONCURRENCY = 1
    try:
        with _NoStop():
            await vault_ai_vision._run_describe_all(aid, "undescribed", **kw)
    finally:
        vault_ai_vision._describe_one = o
        vault_ai_vision._DESCRIBE_CONCURRENCY = o_conc
    return seen


async def case_sweep_reads_cached_rail() -> None:
    import vault_cache
    from vault_collect import LISTS_PAGE
    # 5 items; folder 10 = {1}, folder 20 = {2}. Without a cache 20 ranks first (newer item).
    items = [(i, i, 3000 + i, 4000 + i) for i in range(1, 6)]
    cols = {1: {"of_folder_ids": "[10]"}, 2: {"of_folder_ids": "[20]"}}
    aid = await _world(items, cols)
    assert await vault_ai_vision._rail_order(aid) == []
    rows = [(i, T0 + timedelta(days=i), cols.get(i, {}).get("of_folder_ids")) for i in range(1, 6)]
    assert d.priority_order(rows)[:2] == [2, 1]
    # The rail (two cached pages) says 10 before 20.
    key = lambda off: vault_cache.vault_lists_cache_key(view="main", limit=LISTS_PAGE, offset=off)
    now = datetime.utcnow()
    await vault_cache.put(aid, key(0), {"list": [{"id": 10, "type": "custom", "hasMedia": True}],
                                        "hasMore": True}, started_at=now)
    await vault_cache.put(aid, key(LISTS_PAGE), {"list": [{"id": 20, "type": "custom", "hasMedia": True}],
                                                 "hasMore": False}, started_at=now)
    assert await vault_ai_vision._rail_order(aid) == [10, 20]
    seen = await _spy_walk(aid)
    assert seen == d.priority_order(rows, [10, 20]) and seen[:2] == [1, 2], seen
    assert await vault_ai_vision._flags_todo(aid, force=True) == seen


async def case_describe_all_limit() -> None:
    items = [(i, i, 5000 + i, 6000 + i) for i in range(1, 31)]
    aid = await _world(items, {7: {"of_folder_ids": "[42]"}})
    full = await _spy_walk(aid)
    assert len(full) == 30 and full[0] == 7
    capped = await _spy_walk(aid, limit=5)
    assert capped == full[:5], (capped, full[:5])
    assert vault_ai_vision._describe_progress[aid]["total"] == 5, vault_ai_vision._describe_progress[aid]
    assert await _spy_walk(aid, limit=0) == full
    assert await _spy_walk(aid, limit=99) == full

    # The POST hands `limit` to the sweep: absent = the default Max, "all" = none, a huge explicit number is the
    # operator's (walks everything); 0 / junk / negative / a float / a decimal string too long to convert (W30 C8)
    # = 400 before any claim (F7: a later start is not 409).
    got: list[int] = []
    o_run, o_budget = vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget

    async def _run(_aid, *_a, limit=0, **_k):
        got.append(limit)

    async def _budget(*_a, **_k):
        return {"key_missing": False, "capped": False}
    vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = _run, _budget
    try:
        for raw, want in ((2000, 2000), ("5", 5), (None, vault_ai_vision.DESCRIBE_MAX_DEFAULT), ("all", 0),
                          (10 ** 100, 10 ** 100)):
            body = {"account_id": aid} if raw is None else {"account_id": aid, "limit": raw}
            r = await vault_ai_vision.describe_all(body)
            assert r["limit"] == want, (raw, r)
            await asyncio.sleep(0)
            assert got[-1] == want, (raw, got)
            vault_ai_vision._describe_running.discard(aid)
        for raw in (0, "x", -3, 1.5, float("inf"), 1e308, True, "9" * 4301):
            try:
                await vault_ai_vision.describe_all({"account_id": aid, "limit": raw})
            except vault_ai_vision.HTTPException as e:
                assert e.status_code == 400 and e.detail == {"error": "bad_limit"}, (raw, e.detail)
            else:
                raise AssertionError(f"limit {raw!r} accepted")
            assert aid not in vault_ai_vision._describe_running, f"claim stranded by {raw!r}"
        # a target sweep with no limit is bounded by its goal
        r = await vault_ai_vision.describe_all({"account_id": aid, "target": 10_000})
        assert r["limit"] == 0, r
        vault_ai_vision._describe_running.discard(aid)
    finally:
        vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = o_run, o_budget
        vault_ai_vision._describe_running.discard(aid)


# ── Describe target (describe-all `target`, its plan route) ─────────

def _held_terminal() -> dict:
    import vault_jev_pass
    return vault_jev_pass.held_blob({}, 3, "no frames", "2026-11-21", terminal=True)


def _target_vault() -> str:
    """12 clips, day == id (no folders: walk = newest first). 12 described; 11 refused, 9 blocked_drm,
    7 a terminal held clip, 6 gone (4 Terminal failures); 8 failed, 5 fetch_failed (retryable); the rest new."""
    st = {12: "described", 11: "refused", 9: "blocked_drm", 8: "failed", 6: "gone", 5: "fetch_failed"}
    cols = {m: {"describe_status": s} for m, s in st.items()}
    cols[7] = {"ai_fields_json": json.dumps({"_jev": _held_terminal()})}
    return asyncio.run(_world([(i, i, 7000 + i, 8000 + i) for i in range(1, 13)], cols))


class _Started:
    """`_run_describe_all` recorded, never run; the budget answers `budget`."""

    def __init__(self, **budget) -> None:
        self.calls: list[tuple] = []
        self.budget = {"key_missing": False, "capped": False, "blocked_reason": "", **budget}

    def __enter__(self):
        self._o = (vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget)

        async def _run(*a, **k):
            self.calls.append((a, k))

        async def _budget(*_a, **_k):
            return self.budget
        vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = _run, _budget
        return self

    def __exit__(self, *_e):
        vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = self._o


def _post(body: dict):
    return _harness.make_client().post("/admin/vault-ai/describe-all", json=body)


def case_describe_all_met_target_is_zero_work() -> None:
    aid = _target_vault()   # 1 described
    # Spent cap AND no key: a met target still answers zero work (nothing to do needs no budget).
    with _Started(key_missing=True, capped=True) as started:
        for _ in range(2):   # a second press is not 409: the claim was released
            r = _post({"account_id": aid, "target": 1})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "done" and body["target"] == 1 and body["target_remaining"] == 0, body
            assert aid not in vault_ai_vision._describe_running
    assert started.calls == [], started.calls
    # All 8 reachable items described (4 are Terminal): a target of 1000 is met too.
    async def _describe_rest():
        async with get_session() as s:
            for mid in (10, 8, 5, 4, 3, 2, 1):
                (await s.get(VaultItem, (aid, mid))).describe_status = "described"
            await s.commit()
    asyncio.run(_describe_rest())
    with _Started(capped=True) as started:
        r = _post({"account_id": aid, "target": 1000})
    assert r.status_code == 200 and r.json()["target_remaining"] == 0, r.text
    assert started.calls == [] and aid not in vault_ai_vision._describe_running


def case_describe_all_bad_target_is_400() -> None:
    aid = _target_vault()
    with _Started() as started:
        for raw in ("x", 0, -1, True, 1.5, "5", [3], {}):
            r = _post({"account_id": aid, "target": raw})
            assert r.status_code == 400 and r.json()["detail"]["error"] == "bad_target", (raw, r.text)
        for flag in ("force", "restage"):
            r = _post({"account_id": aid, "target": 5, flag: True})
            assert r.status_code == 400, (flag, r.text)
            assert r.json()["detail"]["error"] == "target_needs_undescribed", (flag, r.text)
        assert started.calls == [] and aid not in vault_ai_vision._describe_running
        for raw in ("x", "²", "0", "-1", "1.5", ""):   # "²".isdigit() is True, int("²") raises
            r = _harness.make_client().get("/admin/vault-ai/describe-all/plan",
                                           params={"account_id": aid, "target": raw})
            assert r.status_code == 400 and r.json()["detail"]["error"] == "bad_target", (raw, r.text)
        # Unmet target: the sweep starts with it, the response echoes target + target_remaining.
        r = _post({"account_id": aid, "target": 4})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "running" and body["target"] == 4 and body["target_remaining"] == 3, body
        assert started.calls and started.calls[-1][1].get("target") == 4, started.calls
        vault_ai_vision._describe_running.discard(aid)


def case_target_sweep_walks_the_remaining_slice() -> None:
    aid = _target_vault()
    client = _harness.make_client()

    def plan(target):
        r = client.get(f"/admin/vault-ai/describe-all/plan?account_id={aid}&target={target}")
        assert r.status_code == 200, r.text
        return r.json()

    p = plan(4)
    assert p["target"] == 4 and p["target_remaining"] == 3, p
    assert p["coverage"] == {"target": 4, "describable": 12, "described": 1, "terminal": 4,
                             "goal": 4, "remaining": 3}, p["coverage"]
    assert p["undescribed"] == 11, p   # the plan's own counts are unchanged
    # Walk = newest first, Terminal failures (11, 9, 7, 6) skipped, `failed` 8 retried, cut to remaining.
    seen = asyncio.run(_spy_walk(aid, target=4))
    assert seen == [10, 8, 5] and len(seen) == p["target_remaining"], seen
    assert vault_ai_vision._describe_progress[aid]["total"] == 3
    # Goal capped by describable − terminal: 8, so 7 remaining.
    assert plan(1000)["target_remaining"] == 7
    assert asyncio.run(_spy_walk(aid, target=1000)) == [10, 8, 5, 4, 3, 2, 1]
    # `limit` cuts further when both are set.
    assert asyncio.run(_spy_walk(aid, target=4, limit=2)) == [10, 8]
    assert asyncio.run(_spy_walk(aid, target=1000, limit=5)) == [10, 8, 5, 4, 3]
    # No target: the plan route answers as before (no coverage keys).
    r = client.get(f"/admin/vault-ai/describe-all/plan?account_id={aid}")
    assert r.status_code == 200 and "coverage" not in r.json() and "target_remaining" not in r.json(), r.text


async def case_target_sweep_never_writes_a_terminal_copy() -> None:
    # 2 is new (walked); 1 refused, marked a copy of 2 (Terminal); 3 described, marked a copy of 2,
    # outside the walk — its refresh still happens, as past a `limit`. 4 is new, marked a copy of 2,
    # and past the cut (target 2, 1 described → remaining 1 → the walk is [2]): not this sweep's, so
    # refreshed too.
    copy_of_2 = json.dumps({"_jev": video_jev(), "_copied_from": 2, "description": "old"})
    aid = await _world([(1, 1, 9101, 9201), (2, 3, 9102, 9202), (3, 2, 9103, 9203), (4, 0, 9104, 9204)], {
        1: {"describe_status": "refused", "ai_fields_json": copy_of_2},
        3: {"describe_status": "described", "video_description": "old", "ai_fields_json": copy_of_2},
        4: {"ai_fields_json": copy_of_2}})

    def snap(row):
        return {c.name: getattr(row, c.name) for c in VaultItem.__table__.columns}
    before = snap(await _row(aid, 1))
    o = vault_dupes.reuse_groups

    async def _one_set(_aid, _want):
        return [[1, 2, 3, 4]]   # still one set: a marker refreshes only a current member (W30 F8)
    vault_dupes.reuse_groups = _one_set
    try:
        with _Model("fresh") as m:
            await vault_ai_vision._run_describe_all(aid, "undescribed", target=2)
    finally:
        vault_dupes.reuse_groups = o
    assert m.n() == 1, m.calls
    assert (await _row(aid, 2)).describe_status == "described"
    assert (await _row(aid, 3)).video_description == "fresh", "propagation outside the walk stopped"
    r4 = await _row(aid, 4)
    assert r4.video_description == "fresh" and _ai(r4).get("_copied_from") == 2, \
        "a copy past the target cut was left stale (`walked` is not the cut)"
    assert snap(await _row(aid, 1)) == before, "a Terminal failure was written by propagation"


async def case_target_sweep_skips_terminal_dupe_members() -> None:
    # Real dupe sets (same thumb + full frame), no stubbed `reuse_groups`.
    # Set A: 2, 4 new, 1 refused (Terminal, newest of A). Set B: 6 new, 7 blocked_drm (Terminal,
    # newest of all) — each Terminal member outranks its set, so only the skip keeps it out of the cut.
    aid = await _world([(1, 6, 130, 230), (2, 5, 130, 230), (4, 4, 130, 230),
                        (6, 9, 140, 240), (7, 11, 140, 240)], {
        1: {"describe_status": "refused"}, 7: {"describe_status": "blocked_drm"}})

    def snap(row):   # the dupe scan's own hash cache aside: the scan, not a copy, writes it
        return {c.name: getattr(row, c.name) for c in VaultItem.__table__.columns
                if c.name not in ("content_hash", "content_hash_kind")}
    before = {mid: snap(await _row(aid, mid)) for mid in (1, 7)}
    with _Model("first") as m:
        # Target 1, nothing described: the walk is [6] (7 skipped); 7, its dupe, must not ride as a follower.
        await vault_ai_vision._run_describe_all(aid, "undescribed", target=1)
        assert m.n() == 1, m.calls
        assert (await _row(aid, 6)).describe_status == "described"
        # A new re-upload 8 of set B arrives: 6 is now a done source, so 8 is a `copy_now` copy.
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=8, kind="video", duration_seconds=20, tags="[]",
                            ai_fields_json=json.dumps({"_jev": video_jev()}),
                            created_at=T0 + timedelta(days=10)))
            await s.commit()
        for root in (vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR):
            (root / aid / "8.jpg").write_bytes(_jpeg(140 if root == vault_stills.THUMB_DIR else 240))
        m.calls.clear()
        m.text = "fresh"
        # 6 describable, 2 terminal, 1 described: target 1000 → remaining 3, the walk [8, 2, 4].
        await vault_ai_vision._run_describe_all(aid, "undescribed", target=1000)
    assert m.n() == 1, m.calls   # 2 leads set A; 8 is copied up front from 6
    r4, r8 = await _row(aid, 4), await _row(aid, 8)
    assert _ai(r4).get("_copied_from") == 2 and r4.video_description == "fresh", _ai(r4)   # a follower
    assert _ai(r8).get("_copied_from") == 6 and r8.video_description == "first", _ai(r8)   # copy_now
    for mid in (1, 7):
        assert snap(await _row(aid, mid)) == before[mid], f"Terminal dupe member {mid} was written"


_harness.run()
