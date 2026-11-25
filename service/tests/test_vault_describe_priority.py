#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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



def _prow(mid, day, folders=None):
    return (mid, T0 + timedelta(days=day) if day is not None else None,
            json.dumps(folders) if folders is not None else None)


def case_priority_order_table() -> None:
    rows = [_prow(i, i) for i in range(1, 31)]
    got = d.priority_order(rows, top=3, bottom=2)
    want = [30, 29, 28, 1, 2, 27, 26, 25, 3, 4, 24, 23, 22, 5, 6, 21, 20, 19, 7, 8,
            18, 17, 16, 9, 10, 15, 14, 13, 11, 12]
    assert got == want, got
    rows = [_prow(1, 1, []), _prow(2, 2), (3, T0 + timedelta(days=3), "not json"),
            _prow(4, 4, [7]), _prow(5, 5), _prow(6, 6, [7, 8]), _prow(7, 7), _prow(8, 8, [9])]
    got = d.priority_order(rows, fold=1, top=1, bottom=1)
    assert got == [8, 7, 1, 6, 4, 5, 2, 3], got
    assert len(got) == len(set(got)) == 8
    assert d.priority_order(rows, fold=2, top=1, bottom=1) == [8, 6, 4, 7, 1, 5, 2, 3]
    assert d.priority_order(rows, fold=1, top=0, bottom=1) == [8, 1, 6, 4, 2, 3, 5, 7]
    assert d.priority_order(rows, fold=1, top=0, bottom=0) == [8, 6, 4, 7, 5, 3, 2, 1]
    assert d.priority_order([(1, T0, None), (2, T0, None), (3, None, None)],
                            top=1, bottom=1) == [2, 3, 1]
    assert d.priority_order([_prow(1, 1), _prow(2, 2)]) == [2, 1]
    assert d.priority_order([]) == []
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
    assert got[:10] == list(range(25, 15, -1)), got[:10]
    assert got[10:510] == list(range(999, 499, -1))
    assert got[510:525] == list(range(1, 16))


def case_priority_folder_rank() -> None:
    fol = {20: [100], 5: [100], 3: [100], 12: [200], 18: [300], 7: [400]}
    rows = [_prow(i, i, fol.get(i)) for i in range(1, 21)]
    kw = {"fold": 1, "top": 1, "bottom": 1}
    got = d.priority_order(rows, [200, 100, 999, 200], **kw)
    assert got == [12, 20, 1, 5, 3, 19, 2, 18, 17, 4, 7, 16, 6, 15, 8, 14, 9, 13, 10, 11], got
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
    order = [5, 4, 3, 2, 1]
    cases = [
        ([[1, 3]], set(), set(), {}, {3: [1]}),
        ([[1, 3, 9]], {9}, set(), {1: 9, 3: 9}, {}),
        ([[1, 3, 9]], set(), set(), {}, {3: [1]}),
        ([[1, 3]], set(), {3}, {}, {1: [3]}),
        ([[1, 3]], {1}, set(), {}, {1: [3]}),
        ([[1, 3]], {1}, {1}, {}, {1: [3]}),
        ([[8, 9]], {8}, set(), {}, {}),
        ([[2, 9]], set(), set(), {}, {}),
        ([[1, 2], [3, 4, 5]], set(), set(), {}, {2: [1], 5: [4, 3]}),
    ]
    for groups, done, bad, copy_now, followers in cases:
        p = d.reuse_plan(groups, order, done, bad)
        assert p.copy_now == copy_now and p.followers == followers, (groups, done, bad, p)
    p = d.reuse_plan([[1, 2], [3, 4, 5]], order, set())
    assert p.riders() == {1, 4, 3}
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

    v = d.build_copy_update(src, prev_ai={}, locked={"description", "tags", "vulva_vis"},
                            overrides={"vulva_vis": "bare", "description": "mine"},
                            fixable=("vulva_vis",), src_id=11, now=now)
    assert "description" not in v and "video_description" not in v and "tags" not in v, v
    assert json.loads(v["ai_fields_json"])["vulva_vis"] == "bare"

    src_nf = {**src, "ai_fields_json": json.dumps({"description": "d"})}
    prev = {"underwear_visible": False, "vulva_vis": "not_in_frame", "breasts_vis": "covered",
            "anus_vis": "not_in_frame", "_flags_v": 3}
    ai = json.loads(d.build_copy_update(src_nf, prev_ai=prev, locked=(), overrides={},
                                        fixable=(), src_id=11, now=now)["ai_fields_json"])
    assert ai["breasts_vis"] == "covered" and ai["_flags_v"] == 3 and "_flags_copied_from" not in ai, ai

    f = d.build_flags_copy({"description": "own", "breasts_vis": "covered", "_flags_status": "error"},
                           src_ai, locked={"breasts_vis"}, src_id=11)
    assert f["description"] == "own" and f["breasts_vis"] == "covered", f
    assert f["vulva_vis"] == "covered" and f["over_vulva"] == "thong" and f["_flags_v"] == 3
    assert "_flags_status" not in f and f["_flags_copied_from"] == 11, f

    src_t = {**src, "ai_fields_json": json.dumps({**src_ai, "_flags_copied_from": 99})}
    ai = json.loads(d.build_copy_update(src_t, prev_ai={"_flags_copied_from": 5}, locked=(),
                                        overrides={}, fixable=(), src_id=11,
                                        now=now)["ai_fields_json"])
    assert ai["_copied_from"] == 11 and "_flags_copied_from" not in ai, ai
    assert ai["_flags_v"] == 3 and ai["breasts_vis"] == "bare", ai

    src_g = {**src, "ai_fields_json": json.dumps({**src_ai, "_graded": {"v": 3}})}
    ai = json.loads(d.build_copy_update(src_g, prev_ai={}, locked=(), overrides={},
                                        fixable=(), src_id=11, now=now)["ai_fields_json"])
    assert "_graded" not in ai, ai
    ai = json.loads(d.build_copy_update(src_g, prev_ai={"_graded": {"v": 1}}, locked=(),
                                        overrides={}, fixable=(), src_id=11,
                                        now=now)["ai_fields_json"])
    assert ai["_graded"] == {"v": 1}, ai

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
    assert ai["_flags_copied_from"] == 12 and ai["_flags_status"] == "error", ai



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
            extra = {"kind": "video", "duration_seconds": 20, "ai_fields_json": json.dumps({"_jev": video_jev()}),
                     **(cols or {}).get(mid, {})}
            s.add(VaultItem(account_id=aid, media_id=mid, tags="[]",
                            created_at=T0 + timedelta(days=day), **extra))
        await s.commit()
    return aid


_DATA_URL = "data:image/jpeg;base64," + __import__("base64").b64encode(_jpeg(1, (8, 8))).decode()


class _Model:

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
    aid = await _world([(1, 1, 100, 200), (2, 3, 100, 200), (3, 2, 100, 300)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
    assert m.n() == 1, f"a duplicate cost a describe call: {m.calls}"
    a, b, c = [await _row(aid, i) for i in (1, 2, 3)]
    assert all(r.describe_status == "described" for r in (a, b, c))
    assert _ai(a).get("_copied_from") == 2 and _ai(c).get("_copied_from") == 2, (_ai(a), _ai(c))
    assert "_copied_from" not in _ai(b)
    assert a.video_description == b.video_description == c.video_description == "a photo"
    assert _ai(a).get("_flags_v") == vault_ai_vision._FLAGS_VERSION, "copy has stale flags"
    assert not {1, 3} & set(await vault_ai_vision._flags_todo(aid)), "copy would be re-flagged"
    prog = vault_ai_vision._describe_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog
    assert prog["cost_millicents"] == 5, prog
    assert "describe_flags" not in m.calls, m.calls


async def case_already_described_member_is_the_source() -> None:
    aid = await _world([(1, 1, 110, 210), (2, 3, 110, 210)])
    with _Model() as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed")
        assert m.n() == 1
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
    with _Model("second") as m:
        out = await vault_ai_vision.describe_one({"account_id": aid, "media_id": 1})
    assert m.n() == 1 and out["ok"], (m.calls, out)
    rows = {i: await _row(aid, i) for i in (1, 2, 3)}
    assert {i: r.video_description for i, r in rows.items()} == {1: "second", 2: "second", 3: "second"}
    assert "_copied_from" not in _ai(rows[1]) and _ai(rows[2])["_copied_from"] == _ai(rows[3])["_copied_from"] == 1
    assert sorted(e["media_id"] for e in out["extra"]) == [2, 3], out


async def case_click_describe_hides_unseen_set_members() -> None:
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
    with _Model() as m:
        await vault_ai_vision._run_flags_all(aid, await vault_ai_vision._flags_todo(aid))
    assert m.calls == [], m.calls
    a = _ai(await _row(aid, 1))
    assert a["_flags_model"] == "jev" and a["description"] == "x", a
    assert await vault_ai_vision._flags_todo(aid) == [], "a flags copy is not current"
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["total"] == prog["done"] == 3 and prog["failed"] == 0, prog


async def case_flags_probe_carries_the_set() -> None:
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
    assert await vault_dupes.reuse_groups(aid, frozenset({4})) == [[1, 2, 4]]
    assert await vault_dupes.reuse_groups(aid, frozenset({3})) == []


async def case_sweep_walks_priority_order() -> None:
    items = [(i, i, 1000 + i, 2000 + i) for i in range(1, 121)]
    aid = await _world(items, {3: {"of_folder_ids": "[42]"}})
    seen: list[int] = []
    o = vault_ai_vision._describe_one

    async def _spy(_aid, mid, **_k):
        seen.append(int(mid))
        return {"media_id": mid, "ok": False, "status": "error", "detail": "spy"}
    vault_ai_vision._describe_one = _spy
    o_conc = vault_ai_vision._DESCRIBE_CONCURRENCY
    vault_ai_vision._DESCRIBE_CONCURRENCY = 1
    try:
        with _NoStop():
            await vault_ai_vision._run_describe_all(aid, "undescribed")
    finally:
        vault_ai_vision._describe_one = o
        vault_ai_vision._DESCRIBE_CONCURRENCY = o_conc
    want = [3] + list(range(120, 3, -1)) + [2, 1]
    assert seen == want, seen[:5] + ["…"] + seen[-5:]
    assert await vault_ai_vision._flags_todo(aid) == []
    assert await vault_ai_vision._flags_todo(aid, force=True) == want



async def _spy_walk(aid: str, **kw) -> list[int]:
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
    items = [(i, i, 3000 + i, 4000 + i) for i in range(1, 6)]
    cols = {1: {"of_folder_ids": "[10]"}, 2: {"of_folder_ids": "[20]"}}
    aid = await _world(items, cols)
    assert await vault_ai_vision._rail_order(aid) == []
    rows = [(i, T0 + timedelta(days=i), cols.get(i, {}).get("of_folder_ids")) for i in range(1, 6)]
    assert d.priority_order(rows)[:2] == [2, 1]
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
        r = await vault_ai_vision.describe_all({"account_id": aid, "target": 10_000})
        assert r["limit"] == 0, r
        vault_ai_vision._describe_running.discard(aid)
    finally:
        vault_ai_vision._run_describe_all, vault_ai_vision._vision_budget = o_run, o_budget
        vault_ai_vision._describe_running.discard(aid)



def _held_terminal() -> dict:
    import vault_jev_pass
    return vault_jev_pass.held_blob({}, 3, "no frames", "2026-11-21", terminal=True)


def _target_vault() -> str:
    st = {12: "described", 11: "refused", 9: "blocked_drm", 8: "failed", 6: "gone", 5: "fetch_failed"}
    cols = {m: {"describe_status": s} for m, s in st.items()}
    cols[7] = {"ai_fields_json": json.dumps({"_jev": _held_terminal()})}
    return asyncio.run(_world([(i, i, 7000 + i, 8000 + i) for i in range(1, 13)], cols))


class _Started:

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
    aid = _target_vault()
    with _Started(key_missing=True, capped=True) as started:
        for _ in range(2):
            r = _post({"account_id": aid, "target": 1})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "done" and body["target"] == 1 and body["target_remaining"] == 0, body
            assert aid not in vault_ai_vision._describe_running
    assert started.calls == [], started.calls
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
# "²".isdigit() is True, int("²") raises
        for raw in ("x", "²", "0", "-1", "1.5", ""):
            r = _harness.make_client().get("/admin/vault-ai/describe-all/plan",
                                           params={"account_id": aid, "target": raw})
            assert r.status_code == 400 and r.json()["detail"]["error"] == "bad_target", (raw, r.text)
        r = _post({"account_id": aid, "target": 8})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "running" and body["target"] == 8 and body["target_remaining"] == 3, body
        assert started.calls and started.calls[-1][1].get("target") == 8, started.calls
        vault_ai_vision._describe_running.discard(aid)


def case_target_sweep_walks_the_remaining_slice() -> None:
    aid = _target_vault()
    client = _harness.make_client()

    def plan(target):
        r = client.get(f"/admin/vault-ai/describe-all/plan?account_id={aid}&target={target}")
        assert r.status_code == 200, r.text
        return r.json()

    p = plan(8)
    assert p["target"] == 8 and p["target_remaining"] == 3, p
    assert p["coverage"] == {"target": 8, "describable": 12, "described": 1, "terminal": 4,
                             "goal": 4, "remaining": 3}, p["coverage"]
    assert p["undescribed"] == 11, p
    seen = asyncio.run(_spy_walk(aid, target=8))
    assert seen == [10, 8, 5] and len(seen) == p["target_remaining"], seen
    assert vault_ai_vision._describe_progress[aid]["total"] == 3
    assert plan(1000)["target_remaining"] == 7
    assert asyncio.run(_spy_walk(aid, target=1000)) == [10, 8, 5, 4, 3, 2, 1]
    assert asyncio.run(_spy_walk(aid, target=8, limit=2)) == [10, 8]
    assert asyncio.run(_spy_walk(aid, target=1000, limit=5)) == [10, 8, 5, 4, 3]
    r = client.get(f"/admin/vault-ai/describe-all/plan?account_id={aid}")
    assert r.status_code == 200 and "coverage" not in r.json() and "target_remaining" not in r.json(), r.text


async def case_target_sweep_never_writes_a_terminal_copy() -> None:
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
        return [[1, 2, 3, 4]]
    vault_dupes.reuse_groups = _one_set
    try:
        with _Model("fresh") as m:
            await vault_ai_vision._run_describe_all(aid, "undescribed", target=3)
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
    aid = await _world([(1, 6, 130, 230), (2, 5, 130, 230), (4, 4, 130, 230),
                        (6, 9, 140, 240), (7, 11, 140, 240)], {
        1: {"describe_status": "refused"}, 7: {"describe_status": "blocked_drm"}})

    def snap(row):
        return {c.name: getattr(row, c.name) for c in VaultItem.__table__.columns
                if c.name not in ("content_hash", "content_hash_kind")}
    before = {mid: snap(await _row(aid, mid)) for mid in (1, 7)}
    with _Model("first") as m:
        await vault_ai_vision._run_describe_all(aid, "undescribed", target=3)
        assert m.n() == 1, m.calls
        assert (await _row(aid, 6)).describe_status == "described"
        async with get_session() as s:
            s.add(VaultItem(account_id=aid, media_id=8, kind="video", duration_seconds=20, tags="[]",
                            ai_fields_json=json.dumps({"_jev": video_jev()}),
                            created_at=T0 + timedelta(days=10)))
            await s.commit()
        for root in (vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR):
            (root / aid / "8.jpg").write_bytes(_jpeg(140 if root == vault_stills.THUMB_DIR else 240))
        m.calls.clear()
        m.text = "fresh"
        await vault_ai_vision._run_describe_all(aid, "undescribed", target=1000)
    assert m.n() == 1, m.calls
    r4, r8 = await _row(aid, 4), await _row(aid, 8)
    assert _ai(r4).get("_copied_from") == 2 and r4.video_description == "fresh", _ai(r4)
    assert _ai(r8).get("_copied_from") == 6 and r8.video_description == "first", _ai(r8)
    for mid in (1, 7):
        assert snap(await _row(aid, mid)) == before[mid], f"Terminal dupe member {mid} was written"


async def case_coverage_counts_rejected_images() -> None:
    for stamp in ({"status": "jev_rejected"},
                  {"status": "error", "error": "Invalid image: TypeSafeBadRequestError"},
                  {"status": "ok", "gave_up": True}):
        aid = await _world([])
        async with get_session() as s:
            s.add_all(VaultItem(account_id=aid, media_id=i, kind="photo", created_at=T0, describe_status="described")
                      for i in range(1, 1000))
            s.add(VaultItem(account_id=aid, media_id=1000, kind="photo", created_at=T0,
                            ai_fields_json=json.dumps({"_jev": stamp})))
            await s.commit()
        assert (await vault_ai_vision.describe_coverage(aid, 1000))["remaining"] == 0


_harness.run()
