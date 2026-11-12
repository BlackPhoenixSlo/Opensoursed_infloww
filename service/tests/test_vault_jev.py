#!/usr/bin/env python3
"""
Jev v8 vault flags (`vault_jev`, `vault_jev_rules`, the `vault_jev_pass` / `vault_ai_vision` wiring).
Plain-assert suite (repo convention), no network: TypeSafe and NudeNet are faked
at the module seams (`vault_jev._client`, `_load_detector`, `nudenet_scores`).

Cases:
  golden replay      every bench flags8c s2A..s5B record (set5 = 5dev only) through
                     `vault_jev_rules.final` == the bench's own score8 + settle nn.10
                     (fixture made by .scratch/jev-vault-bench/p8-golden-gen.py)
  question spec      `vault_jev.spec()` == the spec generated from jev_flags8/jev_crop8
  geometry           shrink / crops / enc output sizes == the bench functions'
  pipeline           pass 1 → 2 → L over the fake client: model pin + header, the
                     blob, spend on the `typesafe` cap row + audit row
  setting off        no TypeSafe / NudeNet call at all
  no NudeNet         refuses before any TypeSafe call; status stamped, fields kept
  cap                over the account's daily cap: no call, nothing written, the
                     flags sweep stops
  carry              re-describe keeps `_jev`; describe / flags copies carry it
  wiring             describe runs Jev first (photos only); the flags sweep queues a
                     photo missing `_jev` and skips the qwen call when flags are current

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_jev.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from PIL import Image as PImage  # noqa: E402
from sqlalchemy import select  # noqa: E402

import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as decide  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokDailyCost, VaultItem  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "vault_jev"
GOLDEN = json.load(gzip.open(FIX / "golden.json.gz", "rt"))["images"]
FIELDS = ("lane5", "lane", "breasts_bare", "crotch_bare", "penetration", "settled")


def _jpeg(w: int, h: int) -> bytes:
    b = io.BytesIO()
    PImage.new("RGB", (w, h), (120, 80, 60)).save(b, "JPEG", quality=95)
    return b.getvalue()


def _size(b: bytes) -> list[int]:
    return list(PImage.open(io.BytesIO(b)).size)


# ── Pure: golden, spec, geometry ─────────────────────────────────────

def case_golden_replay():
    assert len(GOLDEN) == 674, len(GOLDEN)   # 337 images × runs A/B
    assert not any(g["img"].startswith("set6/") for g in GOLDEN)
    bad = []
    for g in GOLDEN:
        d = rules.final(g["rec"], g["nn"])
        got = {k: d.get(k) for k in FIELDS[:-1]} | {"settled": d.get("settled") or False}
        if got != g["expect"]:
            bad.append((g["run"], g["img"], got, g["expect"]))
    assert not bad, f"{len(bad)} mismatches, first: {bad[:3]}"
    # The fixture exercises every branch that matters.
    lanes = {g["expect"]["lane5"] for g in GOLDEN}
    assert lanes == {"free", "$10", "$50", "$100"}, lanes
    assert any(g["expect"]["settled"] == "nn.10" for g in GOLDEN)
    assert any("respL" in g["rec"] for g in GOLDEN) and any("resp2" in g["rec"] for g in GOLDEN)


def case_question_spec():
    want = json.load(open(FIX / "spec.json"))
    got = json.loads(json.dumps(vault_jev.spec()))
    for k in want:
        assert got[k] == want[k], f"spec[{k}] drifted from the bench"
    assert set(got) == set(want), set(got) ^ set(want)
    assert vault_jev.MODEL == "jev-1.14.0"
    assert vault_jev.HEADERS == {"TypeSafe-Danger-Zone-Images": "true"}


def case_geometry():
    for g in json.load(open(FIX / "geom.json")):
        data = _jpeg(*g["px"])
        for e, size in g["shrink"].items():
            assert _size(vault_jev.shrink(data, int(e))) == size, (g["px"], e)
        cr = vault_jev.crops(data, "lower")
        assert {k: list(v.size) for k, v in cr.items()} == g["crops"], g["px"]
        assert {k: _size(vault_jev.enc(v, vault_jev.EDGE_L)) for k, v in cr.items()} == g["enc"], g["px"]


def case_merge_keeps_fields_on_failure():
    prev = {"description": "x", "_jev": {"v": rules.VERSION, "status": "ok", "lane5": "$10"}}
    now = datetime(2026, 11, 11)
    out = vault_jev.merge(prev, vault_jev.JevResult(ok=False, status="error", detail="boom"), now)
    assert out["description"] == "x"
    assert out["_jev"]["lane5"] == "$10" and out["_jev"]["status"] == "error", out
    assert out["_jev"]["failed_at"] == now.isoformat()
    assert not rules.current(out)
    assert vault_jev.merge(prev, vault_jev.JevResult(ok=False, status="capped"), now) == prev


# ── Fakes ────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, d):
        self.d = d

    def model_dump(self, mode="json"):
        return json.loads(json.dumps(self.d))


class _FakeClient:
    def __init__(self, rec):
        self.rec, self.calls = rec, []

    async def system_one(self, *, state, questions, model, extra_headers):
        self.calls.append({"state": {k: _size(bytes(v.data)) for k, v in state.items()},
                           "n": len(questions), "model": model, "headers": extra_headers})
        key = {len(vault_jev.Q): "resp", len(vault_jev.Q2): "resp2"}.get(len(questions), "respL")
        return _Resp(self.rec[key])


class _Seams:
    """Patch the Jev seams; restores on exit. `nn=None` → NudeNet unavailable."""

    def __init__(self, rec, nn, *, key="test-key"):
        self.client, self.nn, self.key = _FakeClient(rec), nn, key
        self.nn_calls = 0

    def __enter__(self):
        self.saved = (vault_jev._client, vault_jev._load_detector, vault_jev.nudenet_scores,
                      llm_providers.typesafe_key)
        vault_jev._client = lambda key: self.client

        def _load():
            self.nn_calls += 1
            if self.nn is None:
                raise vault_jev.NudeNetUnavailable("NUDENET_640M_PATH is not set")
            return object()

        async def _scores(data):
            self.nn_calls += 1
            return dict(self.nn)

        vault_jev._load_detector, vault_jev.nudenet_scores = _load, _scores
        llm_providers.typesafe_key = lambda: self.key
        return self

    def __exit__(self, *a):
        (vault_jev._client, vault_jev._load_detector, vault_jev.nudenet_scores,
         llm_providers.typesafe_key) = self.saved


def _golden_with(*passes):
    return next(g for g in GOLDEN if all(p in g["rec"] for p in passes) and g["nn"] is not None)


_N = 0


async def _seed(*, jev: bool | None, cap_cents: int = 1000, kind: str = "photo",
                fields: dict | None = None, mids=(7001,)) -> str:
    global _N
    _N += 1
    aid = f"acc_jev_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=cap_cents, vault_jev_enabled=jev))
        for i, m in enumerate(mids):
            s.add(VaultItem(account_id=aid, media_id=m, kind=kind, tags="[]",
                            created_at=datetime(2026, 6, 1) + timedelta(minutes=i),
                            ai_fields_json=json.dumps(fields) if fields is not None else None))
        await s.commit()
    return aid


async def _fields(aid, mid=7001) -> dict:
    async with get_session() as s:
        it = await s.get(VaultItem, (aid, mid))
        return json.loads(it.ai_fields_json or "{}")


class _Collect:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __enter__(self):
        self.saved = vault_frames.collect

        async def _c(account_id, item, raw, want=1):
            self.calls += 1
            return vault_frames.Collected([vault_ai_vision.vision.img_data_url(self.data)], "ok")
        vault_frames.collect = _c
        return self

    def __exit__(self, *a):
        vault_frames.collect = self.saved


# ── Pipeline + billing ───────────────────────────────────────────────

async def case_pipeline_all_passes_and_spend():
    g = _golden_with("resp2", "respL")
    aid = await _seed(jev=True)
    with _Seams(g["rec"], g["nn"]) as sm:
        res = await vault_jev.run(aid, _jpeg(576, 1024))
    assert res["ok"] and res["status"] == "ok", res
    b = res["blob"]
    assert {k: b[k] for k in FIELDS} == g["expect"], (b, g["expect"])
    assert b["passes"] == ["1", "2", "L"] and b["v"] == "v8+nn.10"
    assert [c["n"] for c in sm.client.calls] == [len(vault_jev.Q), 12, 2]
    assert all(c["model"] == "jev-1.14.0" and c["headers"] == {"TypeSafe-Danger-Zone-Images": "true"}
               for c in sm.client.calls)
    assert sm.client.calls[0]["state"] == {"photo": [576, 1024]}           # ≤ EDGE: no upscale
    assert sm.client.calls[2]["state"] == {"full_photo": [576, 1024], "lower_part": [576, 614]}
    tok = sum(g["rec"][k]["usage"]["input_tokens"] for k in ("resp", "resp2", "respL"))
    assert b["tok"] == tok and res["cost_millicents"] == vault_jev.cost_millicents(tok) > 0
    assert b["nn"] == {"B": g["nn"].get("FEMALE_BREAST_EXPOSED", 0), "G": g["nn"].get("FEMALE_GENITALIA_EXPOSED", 0)}
    async with get_session() as s:
        row = (await s.execute(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).scalars().all()
        call = (await s.execute(select(GrokCall).where(GrokCall.account_id == aid))).scalars().one()
    assert [(r.provider, r.cost_cents, r.call_count) for r in row] == [("typesafe", res["cost_millicents"], 1)], row
    assert call.provider == "typesafe" and call.status == "done" and call.tokens_in == tok
    assert call.purpose == "vault_jev_flags" and int(call.cost_cents) == res["cost_millicents"]


async def case_cap_respected():
    g = _golden_with("resp")
    aid = await _seed(jev=True, cap_cents=0, fields={"description": "kept"})
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        res = await vault_jev_pass.one(aid, 7001)
        assert res["status"] == "jev_capped" and sm.client.calls == [], res
        assert await _fields(aid) == {"description": "kept"}   # capped writes nothing
    async with get_session() as s:
        rows = (await s.execute(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).scalars().all()
    assert all(r.provider == "typesafe" and r.cost_cents == 0 for r in rows), rows


async def case_jev_cap_skips_jev_not_the_sweep():
    """A Jev cap only skips Jev for the rest of the sweep: Jev-only visits count as failed `jev_capped`
    (never `capped`, which would stop the sweep), the qwen work still runs, and only the first photo
    fetches a still / tries to reserve."""
    g = _golden_with("resp")
    aid = await _seed(jev=True, cap_cents=0, mids=(7001, 7002, 7003),
                      fields={"description": "kept", "_flags_v": 99, **_known_flags()})
    async with get_session() as s:   # 7002's flags are missing -> it needs qwen too
        (await s.get(VaultItem, (aid, 7002))).ai_fields_json = json.dumps({"description": "kept"})
        await s.commit()
    visits = []
    o, oc = vault_ai_vision._flags_one, vault_ai_vision._FLAGS_CONCURRENCY

    async def _flags(aid_, mid, **k):
        visits.append(mid)
        return {"media_id": mid, "ok": True, "status": "flagged", "cost_millicents": 3}
    # One at a time, so "after the cap" is well defined (in-flight visits each try once).
    vault_ai_vision._flags_one, vault_ai_vision._FLAGS_CONCURRENCY = _flags, 1
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)) as col:
            todo = await vault_ai_vision._flags_todo(aid)
            assert sorted(todo) == [7001, 7002, 7003], todo
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
    finally:
        vault_ai_vision._flags_one, vault_ai_vision._FLAGS_CONCURRENCY = o, oc
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["capped"] is False and prog["done"] == 3 and prog["failed"] == 2, prog
    assert visits == [7002] and sm.client.calls == [] and col.calls == 1, (visits, col.calls)
    assert "cap" in prog["error"].lower(), prog


def _known_flags() -> dict:
    """A flags blob `flags_current` accepts (the brief's FLAG_KEYS)."""
    import vault_ai_brief
    out = {k: "covered" for k in vault_ai_brief.VIS_REGIONS}
    out["underwear_visible"] = False
    assert vault_ai_brief.flags_known(out), out
    return out


async def case_setting_off_makes_no_calls():
    g = _golden_with("resp")
    for jev in (None, False):
        aid = await _seed(jev=jev, fields={"_flags_v": 99, **_known_flags()})
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)) as col:
            assert await vault_jev_pass.one(aid, 7001) is None
            assert await vault_ai_vision._flags_todo(aid) == []   # flags current, Jev off → nothing to do
            plan = await vault_jev_pass.plan(aid)
        assert sm.client.calls == [] and sm.nn_calls == 0 and col.calls == 0
        assert plan == {"enabled": False, "ready": False, "reason": ""}


async def case_no_nudenet_refuses_and_stamps():
    g = _golden_with("resp")
    prev = {"description": "kept", "_jev": {"v": rules.VERSION, "status": "error", "lane5": "$50"}}  # stale → runs
    aid = await _seed(jev=True, fields=prev)
    with _Seams(g["rec"], None) as sm, _Collect(_jpeg(576, 1024)) as col:
        res = await vault_jev_pass.one(aid, 7001)
        plan = await vault_jev_pass.plan(aid)
    assert res["status"] == "no_nudenet" and not res["ok"] and sm.client.calls == [], res
    assert col.calls == 0, "refused only after fetching the still from OF"
    f = await _fields(aid)
    assert f["description"] == "kept" and f["_jev"]["status"] == "no_nudenet", f
    assert f["_jev"]["lane5"] == "$50" and "failed_at" in f["_jev"] and "NUDENET" in f["_jev"]["error"]
    assert plan["enabled"] and not plan["ready"] and "NUDENET" in plan["reason"], plan
    async with get_session() as s:
        assert (await s.execute(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).first() is None

    # The real loader, no weights configured: refuses (and remembers it).
    saved = (vault_jev._nn_det, vault_jev._nn_err, os.environ.pop(vault_jev.NUDENET_PATH_ENV, None))
    vault_jev._nn_det = vault_jev._nn_err = None
    try:
        ok, why = vault_jev.nudenet_status()
        assert not ok and vault_jev.NUDENET_PATH_ENV in why, why
        os.environ[vault_jev.NUDENET_PATH_ENV] = "/nonexistent/640m.onnx"
        assert not vault_jev.nudenet_status()[0]   # cached failure
    finally:
        vault_jev._nn_det, vault_jev._nn_err = saved[0], saved[1]
        os.environ.pop(vault_jev.NUDENET_PATH_ENV, None)
        if saved[2] is not None:
            os.environ[vault_jev.NUDENET_PATH_ENV] = saved[2]


async def case_no_key_refuses_before_fetch():
    g = _golden_with("resp")
    aid = await _seed(jev=True)
    with _Seams(g["rec"], g["nn"], key="") as sm, _Collect(_jpeg(576, 1024)) as col:
        res = await vault_jev_pass.one(aid, 7001)
    assert res["status"] == "no_key" and col.calls == 0 and sm.client.calls == [], res
    assert (await _fields(aid))["_jev"]["status"] == "no_key"


async def case_loaded_detector_takes_no_lock_or_thread():
    """Once NudeNet is loaded, `_load_detector` / `preflight` / `plan` never touch the load lock or the
    default thread pool (a held lock here would hang them)."""
    import asyncio
    saved = (vault_jev._nn_det, vault_jev._nn_err, asyncio.to_thread, llm_providers.typesafe_key)
    sentinel = object()
    vault_jev._nn_det, vault_jev._nn_err = sentinel, None

    async def _no_thread(*a, **k):
        raise AssertionError("to_thread used while loaded")
    llm_providers.typesafe_key = lambda: "k"
    aid = await _seed(jev=True)
    assert vault_jev._nn_load_lock.acquire(timeout=1)
    asyncio.to_thread = _no_thread
    try:
        assert vault_jev._load_detector() is sentinel
        assert await asyncio.wait_for(vault_jev.preflight(), 1) is None
        assert await vault_jev.nudenet_ready() == (True, "")
        assert (await vault_jev_pass.plan(aid))["ready"] is True
        vault_jev._nn_det, vault_jev._nn_err = None, "gone"   # a remembered failure: also lock-free
        assert await vault_jev.nudenet_ready() == (False, "gone")
    finally:
        asyncio.to_thread = saved[2]
        vault_jev._nn_load_lock.release()
        vault_jev._nn_det, vault_jev._nn_err, _, llm_providers.typesafe_key = saved
    assert not hasattr(vault_jev, "_nn_lock")


# ── Carry across re-describe / copies ────────────────────────────────

def case_redescribe_and_copies_carry_jev():
    jev = {"v": rules.VERSION, "status": "ok", "lane5": "$10"}
    vals = decide.build_describe_update(
        False, {"description": "new"}, prev_ai={"description": "old", "_jev": jev}, locked=set(),
        overrides={}, used_model="qwen3-vl-30b", n_frames=1, pv="v2", fixable=(), call_id=None,
        now=datetime(2026, 11, 11))
    assert json.loads(vals["ai_fields_json"])["_jev"] == jev

    own = {"v": rules.VERSION, "status": "ok", "lane5": "free"}
    src_cols = {"ai_fields_json": json.dumps({"description": "d", "_jev": jev})}
    vals = decide.build_copy_update(src_cols, prev_ai={"_jev": own}, locked=set(), overrides={},
                                    fixable=(), src_id=1, now=datetime(2026, 11, 11))
    assert json.loads(vals["ai_fields_json"])["_jev"] == jev          # source's good answer
    vals = decide.build_copy_update({"ai_fields_json": json.dumps({"description": "d"})},
                                    prev_ai={"_jev": own}, locked=set(), overrides={},
                                    fixable=(), src_id=1, now=datetime(2026, 11, 11))
    assert json.loads(vals["ai_fields_json"])["_jev"] == own          # source has none: keep own
    failed = {**jev, "status": "error"}
    vals = decide.build_copy_update({"ai_fields_json": json.dumps({"_jev": failed})},
                                    prev_ai={}, locked=set(), overrides={},
                                    fixable=(), src_id=1, now=datetime(2026, 11, 11))
    assert "_jev" not in json.loads(vals["ai_fields_json"])           # a failure is not copied

    assert decide.build_flags_copy({"_jev": own}, {"_flags_v": 3, "_jev": jev}, locked=set(),
                                   src_id=1)["_jev"] == jev
    assert decide.build_flags_copy({"_jev": own}, {"_flags_v": 3}, locked=set(), src_id=1)["_jev"] == own


# ── Wiring ───────────────────────────────────────────────────────────

async def case_describe_runs_jev_first_photos_only():
    g = _golden_with("resp")
    order = []
    o_desc, o_flags = vault_ai_vision._describe_one, vault_ai_vision._flags_one

    async def _desc(aid, mid, **k):
        order.append("describe")
        f = await _fields(aid, mid)
        # describe sees (and so carries) the `_jev` written just before it
        order.append("jev-before" if "_jev" in f else "no-jev")
        return {"media_id": mid, "ok": True, "status": "described", "cost_millicents": 70}

    async def _flags(aid, mid, **k):
        order.append("flags")
        return {"media_id": mid, "ok": True, "status": "flagged", "cost_millicents": 3}

    vault_ai_vision._describe_one, vault_ai_vision._flags_one = _desc, _flags
    try:
        aid = await _seed(jev=True)
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            res = await vault_ai_vision._describe_and_flag(aid, 7001)
            assert order == ["describe", "jev-before", "flags"], order
            assert len(sm.client.calls) >= 1 and res["jev_status"] == "ok", res
            assert res["cost_millicents"] == 73 + res["jev_cost_millicents"] and res["jev_cost_millicents"] > 0
            assert res["jev_lane5"] == g["expect"]["lane5"]
            # current → a second describe does not re-run Jev
            n = len(sm.client.calls)
            res2 = await vault_ai_vision._describe_and_flag(aid, 7001)
            assert len(sm.client.calls) == n and "jev_status" not in res2, res2

            order.clear()
            vid = await _seed(jev=True, kind="video")
            await vault_ai_vision._describe_and_flag(vid, 7001)
            assert len(sm.client.calls) == n and order == ["describe", "no-jev", "flags"], order
    finally:
        vault_ai_vision._describe_one, vault_ai_vision._flags_one = o_desc, o_flags


async def case_flags_sweep_queues_missing_jev_and_skips_current_flags():
    g = _golden_with("resp")
    aid = await _seed(jev=True, mids=(7001, 7002), fields={"_flags_v": 99, **_known_flags()})
    flagged = []
    o = vault_ai_vision._flags_one

    async def _flags(aid_, mid, **k):
        flagged.append(mid)
        return {"media_id": mid, "ok": True, "status": "flagged", "cost_millicents": 3}
    vault_ai_vision._flags_one = _flags
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            todo = await vault_ai_vision._flags_todo(aid)
            assert sorted(todo) == [7001, 7002], todo
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
            assert flagged == [], f"qwen flags re-ran on current flags: {flagged}"
            assert len(sm.client.calls) >= 2
            prog = vault_ai_vision._flags_progress[aid]
            assert prog["failed"] == 0 and prog["jev_cost_millicents"] == prog["cost_millicents"] > 0, prog
            for m in (7001, 7002):
                assert rules.current(await _fields(aid, m)), m
            assert await vault_ai_vision._flags_todo(aid) == []
    finally:
        vault_ai_vision._flags_one = o


async def case_dupe_followers_get_the_leaders_jev():
    g = _golden_with("resp")
    aid = await _seed(jev=True, mids=(7001, 7002), fields={"_flags_v": 99, **_known_flags()})
    o_groups, o_flags = vault_ai_vision.vault_dupes.reuse_groups, vault_ai_vision._flags_one

    async def _groups(account_id, order):
        return [[7001, 7002]]

    async def _flags(*a, **k):
        raise AssertionError("flags are current")
    vault_ai_vision.vault_dupes.reuse_groups, vault_ai_vision._flags_one = _groups, _flags
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            todo = await vault_ai_vision._flags_todo(aid)
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
        assert len(sm.client.calls) == len([k for k in ("resp", "resp2", "respL") if k in g["rec"]]), \
            "a duplicate paid for its own Jev call"
        a, b = await _fields(aid, 7001), await _fields(aid, 7002)
        assert rules.current(a) and rules.current(b) and a["_jev"] == b["_jev"], (a, b)
        assert b.get("_flags_copied_from") == 7001 or a.get("_flags_copied_from") == 7002
    finally:
        vault_ai_vision.vault_dupes.reuse_groups, vault_ai_vision._flags_one = o_groups, o_flags


async def case_forced_flags_rerun_qwen_without_forcing_jev():
    """flags-all {force} on a Jev-on account re-runs qwen on every photo — also the ones that needed Jev —
    and the named-set probe (`_jev_and_flag(force=True)`) never re-pays a current `_jev`."""
    g = _golden_with("resp")
    aid = await _seed(jev=True, mids=(7001, 7002), fields={"_flags_v": 99, **_known_flags()})
    flagged = []
    o = vault_ai_vision._flags_one

    async def _flags(aid_, mid, **k):
        flagged.append(mid)
        return {"media_id": mid, "ok": True, "status": "flagged", "cost_millicents": 3}
    vault_ai_vision._flags_one = _flags
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            todo = await vault_ai_vision._flags_todo(aid, force=True)
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo, force=True)
            assert sorted(flagged) == [7001, 7002], f"forced sweep skipped qwen: {flagged}"
            n = len(sm.client.calls)
            assert n >= 2
            for m in (7001, 7002):
                assert rules.current(await _fields(aid, m)), m
            flagged.clear()
            res = await vault_ai_vision._jev_and_flag(aid, 7001, force=True)   # the grading probe's call
            assert flagged == [7001] and len(sm.client.calls) == n and "jev_status" not in res, res
    finally:
        vault_ai_vision._flags_one = o


async def case_describe_sweep_copies_from_pre_jev_photos():
    """The `_jev` copy-source filter is the flags sweep's only: a photo described before Jev stays a
    describe copy source (no fresh paid describe for its duplicate)."""
    aid = await _seed(jev=True, mids=(7001, 7002))
    async with get_session() as s:
        it = await s.get(VaultItem, (aid, 7001))
        it.describe_status, it.ai_fields_json = "described", json.dumps({"description": "d"})
        await s.commit()
    o = vault_ai_vision.vault_dupes.reuse_groups

    async def _groups(account_id, order):
        return [[7001, 7002]]
    vault_ai_vision.vault_dupes.reuse_groups = _groups
    try:
        plan, _ = await vault_ai_vision._reuse(aid, [7002], flags=False)
        assert 7002 in plan.copy_now, plan
        plan, _ = await vault_ai_vision._reuse(aid, [7002], flags=True)
        assert 7002 not in plan.copy_now, plan   # flags sweep: no current `_jev` -> not a source
    finally:
        vault_ai_vision.vault_dupes.reuse_groups = o


async def case_write_keeps_current_jev():
    """A describe / flags write built from a row read before a concurrent Jev pass landed keeps that
    `_jev` (the other sweep's paid answer) instead of the stale read's."""
    jev = {"v": rules.VERSION, "status": "ok", "lane5": "$10"}
    aid = await _seed(jev=True, fields={"description": "old", "_jev": jev})
    await vault_ai_vision._write_item(aid, 7001, describe_status="described",
                                      ai_fields_json=json.dumps({"description": "new"}))
    assert await _fields(aid) == {"description": "new", "_jev": jev}
    assert vault_jev_pass.keep_current(None, '{"a": 1}') == '{"a": 1}'
    assert json.loads(vault_jev_pass.keep_current(json.dumps({"_jev": jev}),
                                                  json.dumps({"_jev": {"status": "error"}})))["_jev"] == jev


_harness.run()
