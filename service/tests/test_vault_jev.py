#!/usr/bin/env python3
"""
Jev v8 vault flags (`vault_jev`, `vault_jev_rules`, the `vault_jev_pass` / `vault_ai_vision` wiring) — the
default for every vault photo and clip (no setting); clips: 12 frames, maxF (D53/D54).
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
  nothing to pay     audio, or a photo / clip whose `_jev` is current and flags in sync: no TypeSafe / NudeNet call
  tier column        the pass writes `explicitness_tier` from Jev's reading; a stale one is fixed free; a locked one kept
  no NudeNet         refuses before any TypeSafe call; status stamped, fields kept
  cap                over the account's daily cap: no call, nothing written, the
                     flags sweep stops
  carry              re-describe keeps `_jev`; describe / flags copies carry it
  wiring             describe runs Jev first and never the qwen flags call for a photo / clip; a photo
                     Jev cannot read is skipped (Jev's status, nothing written, no qwen); the flags sweep
                     stamps from Jev (never qwen); reuse needs Jev consistency
  clips              bench combine (top-3 targets by sev, lane = max frame, pack round-trip); run_video:
                     pass 1 + NudeNet ×12, pass 2/L ≤3, spend, last-frame lane, MIN_L_EDGE; a low-res
                     source → `jev_review` dispute; frame source (real ffmpeg): 720 + scrub under the 240
                     hash, over cap → 240, no 720 → 240, both over → posters, 403 → fetch_failed
                     one absolute deadline per clip (thread + ffmpeg inside it, a slow finish kept), short lane wait

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_jev.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
import tempfile  # noqa: E402

# the clip frame source writes scrub frames: a throwaway store, bound before storyboard is imported
os.environ["STORYBOARD_DIR"] = tempfile.mkdtemp(prefix="jev-video-test-sb-")

import asyncio  # noqa: E402
import gzip  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from PIL import Image as PImage  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import admission  # noqa: E402
import llm_client  # noqa: E402
import llm_providers  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as decide  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev  # noqa: E402
import vault_describe_jev  # noqa: E402
import vault_jev_flags  # noqa: E402
import vault_jev_pass  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, GrokCall, GrokDailyCost, VaultItem  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "vault_jev"
GOLDEN = json.load(gzip.open(FIX / "golden.json.gz", "rt"))["images"]
DESCRIBE_GOLD = json.load(gzip.open(FIX.parent / "vault_describe_jev" / "golden.json.gz", "rt"))["cases"]
for _c in DESCRIBE_GOLD:   # bench blobs predate the stored region states: empty = every hidden region covered
    _c["jev"].setdefault("state", {})
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
    prev = {"description": "x", "_jev": {"v": rules.VERSION, "status": "ok", "lane5": "$10", "state": {}}}
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


async def _seed(*, cap_cents: int = 1000, kind: str = "photo",
                fields: dict | None = None, mids=(7001,)) -> str:
    global _N
    _N += 1
    aid = f"acc_jev_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=cap_cents))
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
    """Fake `vault_frames.collect` (a photo's still) and `collect_jev_video` (a clip's frames: `clip`, default
    12 copies of `data`; `review` / `src` as the frame source would report them; [] → `reason`)."""

    def __init__(self, data, clip=None, *, src="720", review=None, reason="fetch_failed"):
        self.data, self.calls, self.clip_calls = data, 0, 0
        self.clip = [data] * 12 if clip is None else clip
        self.src, self.review, self.reason = src, review, reason

    def __enter__(self):
        self.saved = vault_frames.collect, vault_frames.collect_jev_video

        async def _c(account_id, item, raw, want=1):
            self.calls += 1
            return vault_frames.Collected([vault_ai_vision.vision.img_data_url(self.data)], "ok")

        async def _v(account_id, item):
            self.clip_calls += 1
            if not self.clip:
                return vault_frames.JevFrames([], self.reason, "fake: no frames")
            return vault_frames.JevFrames(list(self.clip), "ok", src=self.src, review=self.review, nbytes=1234)
        vault_frames.collect, vault_frames.collect_jev_video = _c, _v
        return self

    def __exit__(self, *a):
        vault_frames.collect, vault_frames.collect_jev_video = self.saved


# ── Pipeline + billing ───────────────────────────────────────────────

async def case_pipeline_all_passes_and_spend():
    g = _golden_with("resp2", "respL")
    aid = await _seed()
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
    aid = await _seed(cap_cents=0, fields={"description": "kept"})
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        res = await vault_jev_pass.one(aid, 7001)
        assert res["status"] == "jev_capped" and sm.client.calls == [], res
        assert await _fields(aid) == {"description": "kept"}   # capped writes nothing
    async with get_session() as s:
        rows = (await s.execute(select(GrokDailyCost).where(GrokDailyCost.account_id == aid))).scalars().all()
    assert all(r.provider == "typesafe" and r.cost_cents == 0 for r in rows), rows


async def case_jev_cap_skips_jev_not_the_sweep():
    """A Jev cap only skips Jev for the rest of the sweep: photo and clip visits count as failed `jev_capped`
    (never `capped`, which would stop the sweep), no qwen flags call for the clip, and only the first item
    fetches a still / clip and tries to reserve."""
    g = _golden_with("resp")
    aid = await _seed(cap_cents=0, mids=(7001, 7002, 7003), fields={"description": "kept"})
    async with get_session() as s:   # a clip whose flags are missing: Jev work too
        s.add(VaultItem(account_id=aid, media_id=7004, kind="video", tags="[]", created_at=datetime(2026, 5, 1)))
        await s.commit()
    oc = vault_ai_vision._FLAGS_CONCURRENCY
    # One at a time, so "after the cap" is well defined (in-flight visits each try once).
    vault_ai_vision._FLAGS_CONCURRENCY = 1
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)) as col:
            todo = await vault_ai_vision._flags_todo(aid)
            assert sorted(todo) == [7001, 7002, 7003, 7004], todo
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
    finally:
        vault_ai_vision._FLAGS_CONCURRENCY = oc
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["capped"] is False and prog["done"] == 4 and prog["failed"] == 4, prog
    assert sm.client.calls == [] and col.calls + col.clip_calls == 1, col.calls
    assert "cap" in prog["error"].lower(), prog


def _known_flags() -> dict:
    """A flags blob `flags_current` accepts (the brief's FLAG_KEYS)."""
    import vault_ai_brief
    out = {k: "covered" for k in vault_ai_brief.VIS_REGIONS}
    out["underwear_visible"] = False
    assert vault_ai_brief.flags_known(out), out
    return out


async def case_nothing_to_pay_makes_no_calls():
    """Audio never gets Jev; a photo or clip whose `_jev` is current with its flags in sync is not re-run (and a
    drifted one is re-stamped for free). A clip's qwen-era flags with no `_jev` are stale (Jev work)."""
    g = _golden_with("resp")
    qwen = await _seed(kind="video", fields={"_flags_v": vault_ai_vision._FLAGS_VERSION, **_known_flags()})
    aud = await _seed(kind="audio")
    blob = {"v": rules.VERSION, "status": "ok", "lane5": "$10", "lane": "$10", "settled": False,
            "breasts_bare": "y", "crotch_bare": "n", "penetration": "n", "tags": {"outfit": "nude"}, "state": {}}
    vblob = {**blob, "kind": "video", "vv": rules.VIDEO_VERSION, "frames": []}
    synced = vault_jev_flags.apply({"description": "d", "_jev": blob}, blob)
    vsynced = vault_jev_flags.apply({"description": "d", "_jev": vblob}, vblob)
    pho = await _seed(fields=synced)
    vid = await _seed(kind="video", fields=vsynced)
    drift = await _seed(fields={**synced, "breasts_vis": "covered", "over_breasts": "red bra"})
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)) as col:
        for aid in (aud, vid, pho, drift):
            assert await vault_jev_pass.one(aid, 7001) is None, aid
        assert await vault_ai_vision._flags_todo(vid) == [] and await vault_ai_vision._flags_todo(pho) == []
        assert await vault_ai_vision._flags_todo(qwen) == [7001]
        assert not rules.current({"_jev": {**vblob, "vv": "old"}}), "a clip blob of another VIDEO_VERSION"
    assert sm.client.calls == [] and sm.nn_calls == 0 and col.calls == col.clip_calls == 0
    assert await _fields(drift) == synced, "a drifted photo was not re-stamped from its `_jev`"


async def case_old_blob_without_state_reruns_once():
    """A v8 `_jev` stored before the region states (same VERSION, no `state`) is not current: the next visit pays
    Jev once and stores a blob with `state`; the visit after pays nothing."""
    g = _golden_with("resp")
    old = {"v": rules.VERSION, "status": "ok", "lane5": "$10", "lane": "$10", "settled": False,
           "breasts_bare": "y", "crotch_bare": "n", "penetration": "n", "tags": {"outfit": "nude"}, "at": "old"}
    aid = await _seed(fields={"description": "d", "_jev": old, "_flags_v": 3, **_known_flags()})
    assert not rules.current(await _fields(aid)) and await vault_ai_vision._flags_todo(aid) == [7001]
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        res = await vault_jev_pass.one(aid, 7001)
        paid = len(sm.client.calls)
        assert await vault_jev_pass.one(aid, 7001) is None
    assert res and res["ok"] and paid > 0 and len(sm.client.calls) == paid, (res, paid, sm.client.calls)
    f = await _fields(aid)
    assert rules.current(f) and isinstance(f["_jev"]["state"], dict) and f["_jev"]["at"] != "old", f["_jev"]
    assert vault_jev_flags.in_sync(f, ()) and await vault_ai_vision._flags_todo(aid) == []


async def case_jev_writes_the_tier_column():
    """The Jev pass writes `explicitness_tier` (folder picks / the admin read the column) from its reading: an
    undescribed photo gets it on the paid pass; a stale column beside current flags (a v2 describe's qwen tier)
    is flags work, fixed free with no call; an operator-locked column keeps its value and is not drift."""
    g = _golden_with("resp")

    async def _row(aid):
        async with get_session() as s:
            return await s.get(VaultItem, (aid, 7001))

    async def _set(aid, **vals):
        async with get_session() as s:
            it = await s.get(VaultItem, (aid, 7001))
            for k, v in vals.items():
                setattr(it, k, v)
            await s.commit()

    aid = await _seed(fields={"description": "old"})
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        res = await vault_jev_pass.one(aid, 7001)
        assert res and res["ok"], res
        row = await _row(aid)
        want = json.loads(row.ai_fields_json)["explicitness"]
        assert want and row.explicitness_tier == want, (row.explicitness_tier, want)
        paid = len(sm.client.calls)
        stale = "sfw" if want != "sfw" else "hardcore"
        await _set(aid, explicitness_tier=stale)                     # a pre-Jev describe's tier
        assert await vault_ai_vision._flags_todo(aid) == [7001]
        assert await vault_jev_pass.one(aid, 7001) is None         # re-stamped free
        assert (await _row(aid)).explicitness_tier == want and await vault_ai_vision._flags_todo(aid) == []
        await _set(aid, explicitness_tier=stale, locked_fields_json=json.dumps(["explicitness_tier"]))
        assert await vault_ai_vision._flags_todo(aid) == [], "a locked column read as drift"
        assert await vault_jev_pass.one(aid, 7001) is None
        assert (await _row(aid)).explicitness_tier == stale, "the operator's locked tier was overwritten"
        assert len(sm.client.calls) == paid, "a tier fix paid for Jev"


async def case_no_nudenet_refuses_and_stamps():
    g = _golden_with("resp")
    prev = {"description": "kept", "_jev": {"v": rules.VERSION, "status": "error", "lane5": "$50"}}  # stale → runs
    aid = await _seed(fields=prev)
    with _Seams(g["rec"], None) as sm, _Collect(_jpeg(576, 1024)) as col:
        res = await vault_jev_pass.one(aid, 7001)
        plan = await vault_jev_pass.plan()
    assert res["status"] == "no_nudenet" and not res["ok"] and sm.client.calls == [], res
    assert col.calls == 0, "refused only after fetching the still from OF"
    f = await _fields(aid)
    assert f["description"] == "kept" and f["_jev"]["status"] == "no_nudenet", f
    assert f["_jev"]["lane5"] == "$50" and "failed_at" in f["_jev"] and "NUDENET" in f["_jev"]["error"]
    assert set(plan) == {"ready", "reason"} and not plan["ready"] and "NUDENET" in plan["reason"], plan
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
    aid = await _seed()
    with _Seams(g["rec"], g["nn"], key="") as sm, _Collect(_jpeg(576, 1024)) as col:
        res = await vault_jev_pass.one(aid, 7001)
        plan = await vault_jev_pass.plan()
    assert res["status"] == "no_key" and col.calls == 0 and sm.client.calls == [], res
    assert (await _fields(aid))["_jev"]["status"] == "no_key"
    assert plan == {"ready": False, "reason": "TYPESAFE_API_KEY is not set on this server"}, plan


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
    assert vault_jev._nn_load_lock.acquire(timeout=1)
    asyncio.to_thread = _no_thread
    try:
        assert vault_jev._load_detector() is sentinel
        assert await asyncio.wait_for(vault_jev.preflight(), 1) is None
        assert await vault_jev.nudenet_ready() == (True, "")
        assert await vault_jev_pass.plan() == {"ready": True, "reason": ""}
        vault_jev._nn_det, vault_jev._nn_err = None, "gone"   # a remembered failure: also lock-free
        assert await vault_jev.nudenet_ready() == (False, "gone")
    finally:
        asyncio.to_thread = saved[2]
        vault_jev._nn_load_lock.release()
        vault_jev._nn_det, vault_jev._nn_err, _, llm_providers.typesafe_key = saved
    assert not hasattr(vault_jev, "_nn_lock")


# ── Carry across re-describe / copies ────────────────────────────────

def case_redescribe_and_copies_carry_jev():
    jev = {"v": rules.VERSION, "status": "ok", "lane5": "$10", "state": {}}
    vals = decide.build_describe_update(
        False, {"description": "new"}, prev_ai={"description": "old", "_jev": jev}, locked=set(),
        overrides={}, used_model="qwen3-vl-30b", n_frames=1, pv="v2", fixable=(), call_id=None,
        now=datetime(2026, 11, 11))
    assert json.loads(vals["ai_fields_json"])["_jev"] == jev

    own = {"v": rules.VERSION, "status": "ok", "lane5": "free", "state": {}}
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

async def case_describe_runs_jev_first():
    g = _golden_with("resp")
    order = []
    o_desc = vault_ai_vision._describe_one

    async def _desc(aid, mid, **k):
        order.append("describe")
        f = await _fields(aid, mid)
        # describe sees (and so carries) the `_jev` written just before it
        order.append("jev-before" if "_jev" in f else "no-jev")
        return {"media_id": mid, "ok": True, "status": "described", "cost_millicents": 70}

    vault_ai_vision._describe_one = _desc
    try:
        aid = await _seed()
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            res = await vault_ai_vision._describe_and_flag(aid, 7001)
            assert order == ["describe", "jev-before"], f"a photo got the qwen flags call: {order}"
            assert len(sm.client.calls) >= 1 and res["jev_status"] == "ok", res
            assert res["cost_millicents"] == 70 + res["jev_cost_millicents"] and res["jev_cost_millicents"] > 0
            assert res["jev_lane5"] == g["expect"]["lane5"]
            f = await _fields(aid)
            assert vault_jev_flags.in_sync(f, ()) and f["_flags_model"] == "jev", f   # flags from Jev
            # current → a second describe does not re-run Jev
            n = len(sm.client.calls)
            res2 = await vault_ai_vision._describe_and_flag(aid, 7001)
            assert len(sm.client.calls) == n and "jev_status" not in res2, res2

            order.clear()
            vid = await _seed(kind="video")
            res = await vault_ai_vision._describe_and_flag(vid, 7001)
            assert order == ["describe", "jev-before"], f"a clip got the qwen flags call: {order}"
            assert len(sm.client.calls) >= n + 12 and res["jev_status"] == "ok", res   # pass 1 on 12 frames
            f = await _fields(vid)
            assert f["_jev"]["kind"] == "video" and vault_jev_flags.in_sync(f, ()) and f["_flags_model"] == "jev"
    finally:
        vault_ai_vision._describe_one = o_desc


async def case_describe_skips_photo_jev_cannot_read():
    """No TypeSafe key / no NudeNet / a failed Jev: the photo is skipped with Jev's status — no describe call,
    no qwen flags, describe_status untouched (retried next sweep), never a v2 describe."""
    g = _golden_with("resp")
    o_chat = llm_client.chat

    async def _no(*a, **k):
        raise AssertionError("a photo Jev could not read reached qwen")
    llm_client.chat = _no
    try:
        for seams, want in (((g["rec"], g["nn"]), {"key": ""}), ((g["rec"], None), {})):
            aid = await _seed(fields={"description": "old"})
            with _Seams(*seams, **want), _Collect(_jpeg(576, 1024)):
                res = await vault_ai_vision._describe_and_flag(aid, 7001)
            status = "no_key" if want else "no_nudenet"
            assert not res["ok"] and res["status"] == status and res["jev_status"] == status, res
            assert "jev_skip" not in res and "skipped" in res["detail"], res
            async with get_session() as s:
                row = await s.get(VaultItem, (aid, 7001))
            f = json.loads(row.ai_fields_json)
            assert row.describe_status is None and f["description"] == "old" and "_describe" not in f, f
            assert f["_jev"]["status"] == status and "_flags_v" not in f, f
    finally:
        llm_client.chat = o_chat


async def case_flags_sweep_from_jev_never_qwen():
    g = _golden_with("resp")
    aid = await _seed(mids=(7001, 7002), fields={"_flags_v": vault_ai_vision._FLAGS_VERSION, **_known_flags(),
                                                 "over_breasts": "red bra", "_flags_model": "qwen3-vl-30b"})
    async with get_session() as s:
        s.add(VaultItem(account_id=aid, media_id=7003, kind="video", tags="[]", created_at=datetime(2026, 5, 1)))
        await s.commit()
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        todo = await vault_ai_vision._flags_todo(aid)
        assert sorted(todo) == [7001, 7002, 7003], todo   # qwen-flagged photos are stale: no `_jev`
        vault_ai_vision._flags_running.add(aid)
        await vault_ai_vision._run_flags_all(aid, todo)
        assert len(sm.client.calls) >= 2 + 12
        prog = vault_ai_vision._flags_progress[aid]
        assert prog["failed"] == 0 and prog["jev_cost_millicents"] == prog["cost_millicents"] > 0, prog
        for m in (7001, 7002, 7003):
            f = await _fields(aid, m)
            assert rules.current(f) and vault_jev_flags.in_sync(f, ()) and "over_breasts" not in f, f
        assert (await _fields(aid, 7003))["_jev"]["kind"] == "video"
        assert await vault_ai_vision._flags_todo(aid) == []


async def case_dupe_followers_get_the_leaders_jev():
    g = _golden_with("resp")
    aid = await _seed(mids=(7001, 7002), fields={"_flags_v": 99, **_known_flags()})
    o_groups = vault_ai_vision.vault_dupes.reuse_groups

    async def _groups(account_id, order):
        return [[7001, 7002]]
    vault_ai_vision.vault_dupes.reuse_groups = _groups
    try:
        with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
            todo = await vault_ai_vision._flags_todo(aid)
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
        assert len(sm.client.calls) == len([k for k in ("resp", "resp2", "respL") if k in g["rec"]]), \
            "a duplicate paid for its own Jev call"
        a, b = await _fields(aid, 7001), await _fields(aid, 7002)
        assert rules.current(a) and rules.current(b) and a["_jev"] == b["_jev"], (a, b)
        assert vault_jev_flags.in_sync(a, ()) and vault_jev_flags.in_sync(b, ()), (a, b)
        assert b.get("_flags_copied_from") == 7001 or a.get("_flags_copied_from") == 7002
        assert await vault_ai_vision._flags_todo(aid) == []
    finally:
        vault_ai_vision.vault_dupes.reuse_groups = o_groups


async def case_forced_flags_never_qwen_on_photos_nor_repays_jev():
    """flags-all {force} never calls qwen for a photo and never re-pays a current `_jev`; nor does the named-set
    probe (`_jev_and_flag(force=True)`)."""
    g = _golden_with("resp")
    aid = await _seed(mids=(7001, 7002), fields={"_flags_v": 99, **_known_flags()})
    with _Seams(g["rec"], g["nn"]) as sm, _Collect(_jpeg(576, 1024)):
        todo = await vault_ai_vision._flags_todo(aid, force=True)
        vault_ai_vision._flags_running.add(aid)
        await vault_ai_vision._run_flags_all(aid, todo, force=True)
        n = len(sm.client.calls)
        assert n >= 2, n
        for m in (7001, 7002):
            assert vault_jev_flags.in_sync(await _fields(aid, m), ()), m
        await vault_ai_vision._run_flags_all(aid, await vault_ai_vision._flags_todo(aid, force=True), force=True)
        res = await vault_ai_vision._jev_and_flag(aid, 7001, force=True)   # the grading probe's call
        assert len(sm.client.calls) == n and "jev_status" not in res, res
        assert res["ok"] and res["status"] == "flagged", res


async def case_photo_reuse_needs_jev():
    """A photo is a describe copy source only with a Jev-fed describe on the `_jev` it holds (a pre-Jev / v2
    photo describe never), and a flags source only with flags (and the `explicitness_tier` column) in sync with a
    current `_jev`; a flags copy writes the copy's column too."""
    c = next(x for x in DESCRIBE_GOLD if x["path"] == "prose")
    j = c["jev"]
    fed = vault_jev_flags.apply({"description": "d", "_describe": vault_describe_jev.meta("prose", j, "m"),
                                 "_jev": j}, j)
    o = vault_ai_vision.vault_dupes.reuse_groups

    async def _groups(account_id, order):
        return [[7001, 7002]]
    vault_ai_vision.vault_dupes.reuse_groups = _groups
    try:
        x = fed["explicitness"]
        qwen = "sfw" if x != "sfw" else "hardcore"
        for src, locks, tier, describe_ok, flags_ok in (
                ({"description": "d"}, [], None, False, False),                                       # pre-Jev
                ({"description": "d", "_flags_v": 3, **_known_flags()}, [], None, False, False),      # qwen flags
                (fed, [], x, True, True),
                ({**fed, "breasts_vis": "covered"}, [], x, True, False),                             # flags drifted
                (dict(fed), [], qwen, True, False),                                  # the column kept qwen's tier
                # an operator-locked flag / column is not drift: in sync for the todo, the reuse plan and the copy
                ({**fed, "breasts_vis": "covered"}, ["breasts_vis"], x, True, True),
                (dict(fed), ["explicitness_tier"], qwen, True, True)):
            aid = await _seed(mids=(7001, 7002))
            async with get_session() as s:
                it = await s.get(VaultItem, (aid, 7001))
                it.describe_status, it.ai_fields_json = "described", json.dumps(src)
                it.locked_fields_json, it.explicitness_tier = json.dumps(locks), tier
                await s.commit()
            plan, _ = await vault_ai_vision._reuse(aid, [7002], flags=False)
            assert (7002 in plan.copy_now) == describe_ok, (src, plan)
            plan, _ = await vault_ai_vision._reuse(aid, [7002], flags=True)
            assert (7002 in plan.copy_now) == flags_ok, (src, locks, plan)
            if src is not fed and "_jev" in src:
                todo = await vault_ai_vision._flags_todo(aid)
                assert (7001 not in todo) == flags_ok, (locks, todo)
                res = await vault_ai_vision._copy_flags(aid, 7001, 7002)
                assert (res["status"] == "flags_copied") == flags_ok, (locks, res)
                if flags_ok:
                    async with get_session() as s:
                        assert (await s.get(VaultItem, (aid, 7002))).explicitness_tier == x, "copy left its tier"
    finally:
        vault_ai_vision.vault_dupes.reuse_groups = o


async def case_write_keeps_current_jev():
    """A describe / flags write built from a row read before a concurrent Jev pass landed keeps that
    `_jev` (the other sweep's paid answer) instead of the stale read's."""
    jev = {"v": rules.VERSION, "status": "ok", "lane5": "$10", "state": {}}
    aid = await _seed(fields={"description": "old", "_jev": jev})
    await vault_ai_vision._write_item(aid, 7001, describe_status="described",
                                      ai_fields_json=json.dumps({"description": "new"}))
    assert await _fields(aid) == {"description": "new", "_jev": jev}
    assert vault_jev_pass.keep_current(None, '{"a": 1}') == '{"a": 1}'
    assert json.loads(vault_jev_pass.keep_current(json.dumps({"_jev": jev}),
                                                  json.dumps({"_jev": {"status": "error"}})))["_jev"] == jev
    # a row whose flags are Jev's keeps them too (a stale read's qwen-era flags never win)
    full = {**jev, "lane": "$10", "settled": False, "breasts_bare": "y", "crotch_bare": "n", "tags": {}}
    cur = vault_jev_flags.apply({"description": "old", "_jev": full}, full)
    got = json.loads(vault_jev_pass.keep_current(json.dumps(cur), json.dumps({"description": "new",
                                                                              "breasts_vis": "covered"})))
    assert got["description"] == "new" and got["breasts_vis"] == "bare" and vault_jev_flags.in_sync(got, ()), got
    # a describe's fresh clothing_items name the garments (the photo's only garment source); a lock keeps its value
    got = json.loads(vault_jev_pass.keep_current(json.dumps(cur), json.dumps({"description": "new",
                                                                              "clothing_items": ["black thong"]})))
    assert got["over_vulva"] == "black thong" and "over_breasts" not in got and vault_jev_flags.in_sync(got, ()), got
    got = json.loads(vault_jev_pass.keep_current(json.dumps(cur), json.dumps(
        {"clothing_items": ["black thong"], "over_vulva": "red skirt"}), {"over_vulva"}))
    assert got["over_vulva"] == "red skirt", got
    aid2 = await _seed(fields=cur)
    async with get_session() as s:
        await s.execute(update(VaultItem).where(VaultItem.account_id == aid2)
                        .values(locked_fields_json=json.dumps(["over_vulva"])))
        await s.commit()
    await vault_ai_vision._write_item(aid2, 7001, ai_fields_json=json.dumps(
        {"clothing_items": ["black thong"], "over_vulva": "red skirt"}))
    assert (await _fields(aid2))["over_vulva"] == "red skirt", "_write_item passes the row's locks"


# ── Clips (D53 hr12 maxF, D54) ───────────────────────────────────────

def _p1(g):
    return rules.derive8({"resp": g["rec"]["resp"]})


def _gold(lane5, *, has=("resp",), need=None):
    """A golden record (NudeNet run) of exactly passes `has`, final lane `lane5`; `need` "need2" / "needL" → pass 1
    asks for it, None → pass 1 asks for neither."""
    for g in GOLDEN:
        if g["nn"] is None or set(g["rec"]) != set(has) or g["expect"]["lane5"] != lane5:
            continue
        d = _p1(g)
        if (need is None and not d["need2"] and not d["needL"]) or (need and d[need]):
            return g
    raise AssertionError((lane5, has, need))


class _FrameSeams(_Seams):
    """`_Seams` per frame: `frames` = [(jpeg, golden)]; each TypeSafe / NudeNet call is matched to its frame by the
    size of the image it sends (frames sized so pass 1 / 2 / L send them unscaled). A pass the record lacks (a
    target the bench never called) answers pass 1's own answers to those questions."""

    def __init__(self, frames):
        super().__init__(frames[0][1]["rec"], frames[0][1]["nn"])
        self.frames, self.by, self.scored = frames, {}, 0
        for i, (data, _) in enumerate(frames):
            for b in (data, vault_jev.shrink(data, vault_jev.EDGE), vault_jev.shrink(data, vault_jev.EDGE2)):
                assert self.by.setdefault(tuple(_size(b)), i) == i, "two frames share a size"

        async def system_one(*, state, questions, model, extra_headers):
            img = state.get("photo") or state["full_photo"]
            i = self.by[tuple(_size(bytes(img.data)))]
            key = {len(vault_jev.Q): "resp", len(vault_jev.Q2): "resp2"}.get(len(questions), "respL")
            self.client.calls.append({"frame": i, "pass": key, "n": len(questions), "model": model,
                                      "headers": extra_headers, "state": {k: _size(bytes(v.data))
                                                                          for k, v in state.items()}})
            rec = self.frames[i][1]["rec"]
            if key in rec:
                return _Resp(rec[key])
            a = rec["resp"]["answers"]
            return _Resp({"answers": {q: a[q] for q in questions}, "usage": {"input_tokens": 1000}})
        self.client.system_one = system_one

    def __enter__(self):
        super().__enter__()

        async def _scores(data):
            self.scored += 1
            return dict(self.frames[self.by[tuple(_size(data))]][1]["nn"])
        vault_jev.nudenet_scores = _scores
        return self

    def passes(self, p):
        return sorted(c["frame"] for c in self.client.calls if c["pass"] == p)


def _clip(golds):
    """12 frames (distinct sizes, pass-1 / pass-2 shrink and the lower crops leave them unscaled) for `golds`."""
    return [(_jpeg(600 + 4 * i, 480), g) for i, g in enumerate(golds)]


def case_video_pure_combine():
    """The bench combine (jv-jev.py / jv-score.py): top-3 targets by `sev` among frames derive8 asks for (else the
    pass-1 max record's ask → top-3 overall, else none); lane = the max frame's, ties to the higher sev; packed
    answers derive the same as the raw ones (every golden record)."""
    free, p100, p10 = _gold("free"), _gold("$100"), _gold("$10")
    need = [g for g in GOLDEN if g["nn"] is not None and _p1(g)["need2"]][:5]
    recs = [{"resp": (need[i // 2] if i % 2 and i // 2 < 5 else free)["rec"]["resp"]} for i in range(12)]
    asking = [i for i in range(12) if rules.derive8(recs[i])["need2"]]
    assert len(asking) == 5, asking
    top = sorted(asking, key=lambda i: -rules.sev(rules.derive8(recs[i])))[:3]
    assert rules.video_targets(recs, "need2") == top, (rules.video_targets(recs, "need2"), top)
    only_free = [{"resp": free["rec"]["resp"]}] * 12
    assert rules.video_targets(only_free, "need2") == [] == rules.video_targets(only_free, "needL")
    assert rules.video_targets([], "need2") == []

    sc = [free["nn"]] * 12
    recs = [{"resp": free["rec"]["resp"]}] * 12
    recs = recs[:4] + [{"resp": p10["rec"]["resp"]}] + recs[5:7] + [{"resp": p100["rec"]["resp"]}] + recs[8:]
    sc = sc[:4] + [p10["nn"]] + sc[5:7] + [p100["nn"]] + sc[8:]
    ds, i = rules.video_final(recs, sc)
    assert i == 7 and ds[i]["lane5"] == "$100" and ds[4]["lane5"] == "$10", (i, [d["lane5"] for d in ds])
    ds, i = rules.video_final([{"resp": free["rec"]["resp"]}] * 3, [free["nn"]] * 3)
    assert i == 0 and ds[0]["lane5"] == "free"   # all tied: the first

    o1, o2 = vault_jev.ORDER["1"], vault_jev.ORDER["2"]
    for g in GOLDEN:
        rec = {"resp": {"answers": rules.unpack(rules.pack(g["rec"]["resp"]["answers"], o1), o1)}}
        if "resp2" in g["rec"]:
            rec["resp2"] = {"answers": rules.unpack(rules.pack(g["rec"]["resp2"]["answers"], o2), o2)}
        if "respL" in g["rec"]:
            oL = vault_jev.ORDER["L"]
            rec["respL"] = {"answers": rules.unpack(rules.pack(g["rec"]["respL"]["answers"], oL), oL)}
        d = rules.final(rec, g["nn"])
        assert {k: d.get(k) for k in FIELDS[:-1]} | {"settled": d.get("settled") or False} == g["expect"], g["img"]


async def case_video_pipeline_maxF_top3_and_spend():
    """`run_video` over 12 frames: pass 1 + NudeNet on every frame, pass 2 / L only on ≤3 targets, lane = the max
    frame's; the blob is the max frame's photo blob + every frame packed (re-derives the same lane), spend on one
    `typesafe` hold; the flags mapper reads it."""
    free, p50 = _gold("free"), _gold("$50", has=("resp", "resp2"), need="need2")
    golds = [free] * 12
    golds[7] = p50
    frames = _clip(golds)
    aid = await _seed(kind="video")
    with _FrameSeams(frames) as sm:
        res = await vault_jev.run_video(aid, [f for f, _ in frames], src="720", review=None, nbytes=4321)
    assert res["ok"], res
    b = res["blob"]
    assert sm.passes("resp") == list(range(12)) and sm.scored == 12, (sm.scored, sm.client.calls)
    assert 7 in sm.passes("resp2") and len(sm.passes("resp2")) <= 3 and len(sm.passes("respL")) <= 3
    assert b["lane5"] == "$50" and b["frame"] == 7 and b["kind"] == "video" and b["vv"] == rules.VIDEO_VERSION
    assert b["src"] == "720" and b["review"] is None and b["bytes"] == 4321 and len(b["frames"]) == 12
    assert [f["lane5"] for f in b["frames"]].count("$50") >= 1 and b["frames"][7]["lane5"] == "$50"
    assert "2" in b["frames"][7] and all("2" not in f for i, f in enumerate(b["frames"]) if i not in sm.passes("resp2"))
    assert rules.current({"_jev": b}) and vault_jev_flags.reading(b) is not None
    recs, scores = vault_jev.frame_recs(json.loads(json.dumps(b)))   # as stored
    ds, top = rules.video_final(recs, scores)
    assert top == 7 and [d["lane5"] for d in ds] == [f["lane5"] for f in b["frames"]]
    tok = sum(sm.frames[c["frame"]][1]["rec"].get(c["pass"], {"usage": {"input_tokens": 1000}})["usage"]["input_tokens"]
              for c in sm.client.calls)
    assert b["tok"] == tok and res["cost_millicents"] == vault_jev.cost_millicents(tok)
    async with get_session() as s:
        calls = (await s.execute(select(GrokCall).where(GrokCall.account_id == aid))).scalars().all()
    assert [(c.provider, c.status, c.tokens_in) for c in calls] == [("typesafe", "done", tok)], calls


async def case_video_first_frame_is_not_the_lane():
    """A clip whose only paid frame is the last one takes that frame's lane, never the first frame's."""
    free, p100 = _gold("free"), _gold("$100")
    frames = _clip([free] * 11 + [p100])
    aid = await _seed(kind="video")
    with _FrameSeams(frames):
        res = await vault_jev.run_video(aid, [f for f, _ in frames], src="720", review=None, nbytes=1)
    assert res["blob"]["lane5"] == "$100" and res["blob"]["frame"] == 11, res["blob"]["frame"]


async def case_video_min_dimension_skips_pass_l():
    """A frame whose lower crops would be under MIN_L_EDGE (Jev 400s on 400x202) skips pass L, recorded."""
    gl = _gold("$10", has=("resp", "respL"), need="needL")
    aid = await _seed(kind="video")
    small = [(_jpeg(400, 202), gl)]
    with _FrameSeams(small) as sm:
        res = await vault_jev.run_video(aid, [small[0][0]], src="240", review="over_cap", nbytes=1)
    assert res["ok"] and sm.passes("respL") == [] and res["blob"]["frames"][0]["Ls"] == "small", res
    assert res["blob"]["review"] == "over_cap" and res["blob"]["src"] == "240"
    big = _clip([gl])[:1]
    with _FrameSeams(big) as sm:
        res = await vault_jev.run_video(aid, [big[0][0]], src="720", review=None, nbytes=1)
    assert sm.passes("respL") == [0] and "Ls" not in res["blob"]["frames"][0], sm.client.calls
    assert all(min(s) >= vault_jev.MIN_L_EDGE for s in sm.client.calls[-1]["state"].values())


async def case_video_pass_review_and_no_frames():
    """`vault_jev_pass.one` on a clip: frames from `collect_jev_video` → `_jev` (kind video) + Jev flags; a
    low-res source (`review`) makes the clip disputed (never a free lane: `vault_ai_brief`) and, under $100, its
    `lane5` "review" — an unknown tier the pack picker never prefills free — its flags still read off the lane it
    read (`read_lane5`); a $100 review clip keeps $100; no frames → nothing written, no Jev call, the frame
    source's status."""
    import vault_ai_brief
    import vault_pack_picker
    free = _gold("free")
    frames = _clip([free] * 12)
    aid = await _seed(kind="video")
    with _FrameSeams(frames) as sm, _Collect(b"", [f for f, _ in frames], src="240", review="no_720") as col:
        res = await vault_jev_pass.one(aid, 7001)
    assert res["ok"] and res["lane5"] == "review" and col.clip_calls == 1 and col.calls == 0, res
    f = await _fields(aid)
    assert f["_jev"]["review"] == "no_720" and f["_flags_model"] == "jev" and vault_jev_flags.in_sync(f, ())
    assert f["_jev"]["read_lane5"] == "free" and vault_jev_flags.reading(f["_jev"]) is not None
    assert vault_pack_picker.price_tier(f) is None, "a review clip priced as a known free tier"
    assert vault_ai_vision._flags_todo is not None and await vault_jev_pass.one(aid, 7001) is None   # current, in sync
    p100 = _clip([_gold("$100")] * 12)
    aid100 = await _seed(kind="video")
    with _FrameSeams(p100), _Collect(b"", [f for f, _ in p100], src="240", review="over_cap"):
        res = await vault_jev_pass.one(aid100, 7001)
    f100 = await _fields(aid100)
    assert res["lane5"] == "$100" and "read_lane5" not in f100["_jev"] and vault_pack_picker.price_tier(f100) == 100
    assert vault_ai_brief.contradictions(f) == ["jev_review"] and vault_ai_brief.is_disputed(f)
    assert any("jev_review" not in n and "lane may be too low" in n for n in vault_ai_brief.settled_notes(f))
    aid2 = await _seed(kind="video")
    with _FrameSeams(frames), _Collect(b"", [f for f, _ in frames]):
        await vault_jev_pass.one(aid2, 7001)
    assert vault_ai_brief.contradictions(await _fields(aid2)) == [], "a 720p clip is disputed"
    aid3 = await _seed(kind="video", fields={"description": "kept"})
    with _FrameSeams(frames) as sm, _Collect(b"", [], reason="no_variant"):
        res = await vault_jev_pass.one(aid3, 7001)
    assert res["status"] == "blocked_drm" and not res["ok"] and sm.client.calls == [], res
    assert await _fields(aid3) == {"description": "kept"}


def _mp4(w: int, h: int, secs: int = 12, rate: int = 4) -> bytes:
    """A real clip (`rate` frames a second). A short one needs a real frame rate: at 4 fps the last of 12 seeks
    into a 3 s clip lands past its last frame (11/12, a short set)."""
    import subprocess
    out = Path(tempfile.mkdtemp()) / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=size={w}x{h}:rate={rate}:duration={secs}", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


class _HttpResp:
    def __init__(self, status, body, *, length=True):
        self.status_code, self.body = status, body
        self.headers = {"content-length": str(len(body))} if length else {}

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def close(self):
        pass


class _FakeOF:
    """The account's client (`http.get` per url) + `resolve_fresh` + posters, patched into vault_frames."""

    def __init__(self, media, bodies, posters=0):
        self.media, self.bodies, self.posters, self.gets = media, bodies, posters, []
        self.http, self.timeout_s = self, 5

    def get(self, url, timeout=None, stream=False):
        self.gets.append(url)
        b = self.bodies[url]
        return b if isinstance(b, _HttpResp) else _HttpResp(200, b)

    def __enter__(self):
        import vault_stills
        self.saved = (vault_frames.ax._make_client, vault_stills.resolve_fresh, vault_frames._poster_stills)

        async def fresh(account_id, media_id, client, **k):
            return vault_stills.Fresh(self.media, "ok")

        async def posters(account_id, media_id, media, want, warm):
            imgs = [vault_ai_vision.vision.img_data_url(_jpeg(300, 300 + i)) for i in range(min(want, self.posters))]
            return vault_frames.Collected(imgs, "ok" if imgs else "no_variant")
        vault_frames.ax._make_client = lambda aid: self
        vault_stills.resolve_fresh, vault_frames._poster_stills = fresh, posters
        return self

    def __exit__(self, *a):
        import vault_stills
        vault_frames.ax._make_client, vault_stills.resolve_fresh, vault_frames._poster_stills = self.saved


async def case_video_frame_source():
    """`collect_jev_video` (real ffmpeg): the 720p mp4 → 12 native frames, and the 400px scrub frames written
    under the 240p url's storyboard hash; 720p over the cap → the 240p frames, `over_cap`; no 720p and no
    `files.full` → 240p, `no_720`; both over the cap → posters, `poster_only`; a 720p 403 → the 240p,
    `src_failed`; every mp4 403 → posters, `poster_only`, and with no posters either `fetch_failed` (retried); a
    full storyboard is left alone."""
    import storyboard
    v720, v240 = _mp4(160, 96), _mp4(64, 40)
    u720, u240 = "https://cdn.test/files/a/720.mp4?sig=1", "https://cdn.test/files/a/240.mp4?sig=1"
    item = VaultItem(account_id="acc_fs", media_id=1, kind="video", duration_seconds=12)
    media = {"duration": 12, "videoSources": {"720": u720, "240": u240}}
    h = storyboard._video_path_hash(u240)
    with _FakeOF(media, {u720: v720, u240: v240}) as of:
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert got.reason == "ok" and got.src == "720" and got.review is None and got.nbytes == len(v720), got[1:]
    assert len(got.frames) == 12 and {tuple(_size(f)) for f in got.frames} == {(160, 96)} and of.gets == [u720]
    assert storyboard._storyboard_all_frames_present(h)
    assert _size(storyboard._storyboard_frame_path(h, 0).read_bytes()) == [400, 240]
    mtime = storyboard._storyboard_frame_path(h, 3).stat().st_mtime_ns
    with _FakeOF(media, {u720: v720, u240: v240}):
        await vault_frames.collect_jev_video("acc_fs", item)
    assert storyboard._storyboard_frame_path(h, 3).stat().st_mtime_ns == mtime, "a full storyboard was rewritten"

    saved = vault_frames.JEV_VIDEO_CAP_BYTES
    vault_frames.JEV_VIDEO_CAP_BYTES = len(v720) - 1
    try:
        with _FakeOF(media, {u720: v720, u240: v240}) as of:
            got = await vault_frames.collect_jev_video("acc_fs", item)
        assert got.src == "240" and got.review == "over_cap" and of.gets == [u720, u240], (got[1:], of.gets)
        assert {tuple(_size(f)) for f in got.frames} == {(64, 40)}
        with _FakeOF(media, {u720: _HttpResp(200, v720, length=False), u240: v240}) as of:
            got = await vault_frames.collect_jev_video("acc_fs", item)
        assert got.src == "240" and got.review == "over_cap", "no content-length pulled an uncapped file"
        vault_frames.JEV_VIDEO_CAP_BYTES = len(v240) - 1
        with _FakeOF(media, {u720: v720, u240: v240}, posters=9):
            got = await vault_frames.collect_jev_video("acc_fs", item)
        assert got.src == "poster" and got.review == "poster_only" and len(got.frames) == 9, got[1:]
    finally:
        vault_frames.JEV_VIDEO_CAP_BYTES = saved
    with _FakeOF({"duration": 12, "videoSources": {"720": None, "240": u240}}, {u240: v240}):
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert got.src == "240" and got.review == "no_720" and len(got.frames) == 12, got[1:]
    with _FakeOF(media, {u720: _HttpResp(403, b""), u240: v240}) as of:
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert got.reason == "ok" and got.src == "240" and got.review == "src_failed" and len(got.frames) == 12 \
        and of.gets == [u720, u240], (got[1:], of.gets)
    dead = {u720: _HttpResp(403, b""), u240: _HttpResp(403, b"")}
    with _FakeOF(media, dead, posters=9) as of:
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert got.src == "poster" and got.review == "poster_only" and of.gets == [u720, u240], (got[1:], of.gets)
    with _FakeOF(media, dead, posters=0):
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert got.reason == "fetch_failed" and not got.frames and "240p download failed" in got.detail, got
    with _FakeOF({"duration": 12, "videoSources": {}, "files": {}}, {}, posters=0):
        got = await vault_frames.collect_jev_video("acc_fs", item)
    assert not got.frames and got.reason == "no_variant", got


async def case_video_short_frame_set_never_priced():
    """A source that lands fewer than 12 frames (ffmpeg exits 0 short) is not read: the next source is (`review`
    src_failed); with every source short, the fullest set is read, `review` few_frames, and the clip lands in the
    "review" lane (never priced free)."""
    import vault_pack_picker
    v720, v240 = _mp4(160, 96), _mp4(64, 40)
    u720, u240 = "https://cdn.test/files/s/720.mp4?sig=1", "https://cdn.test/files/s/240.mp4?sig=1"
    item = VaultItem(account_id="acc_sf", media_id=5, kind="video", duration_seconds=12)
    media = {"duration": 12, "videoSources": {"720": u720, "240": u240}}
    real, keep = vault_frames._extract_jev, []

    def short(*a, **k):
        got = real(*a, **k)
        return got[:keep.pop(0)] if keep else got
    vault_frames._extract_jev = short
    try:
        keep[:] = [7]
        with _FakeOF(media, {u720: v720, u240: v240}) as of:
            got = await vault_frames.collect_jev_video("acc_sf", item)
        assert got.src == "240" and got.review == "src_failed" and len(got.frames) == 12 \
            and of.gets == [u720, u240], (got[1:], of.gets)
        keep[:] = [7, 3]
        with _FakeOF(media, {u720: v720, u240: v240}):
            got = await vault_frames.collect_jev_video("acc_sf", item)
        assert got.reason == "ok" and got.src == "720" and got.review == "few_frames" and len(got.frames) == 7, got[1:]
    finally:
        vault_frames._extract_jev = real
    frames = _clip([_gold("free")] * 7)
    aid = await _seed(kind="video")
    with _FrameSeams(frames), _Collect(b"", [f for f, _ in frames], review="few_frames"):
        res = await vault_jev_pass.one(aid, 7001)
    f = await _fields(aid)
    assert res["lane5"] == "review" and vault_pack_picker.price_tier(f) is None, (res, f["_jev"].get("lane5"))


async def case_jev_outage_stops_jev_for_the_sweep():
    """`DOWN_AFTER` Jev call failures in a row (an outage) stop Jev for the rest of the sweep like the cap: every
    later item is `jev_down` with no still / clip fetched; a success in between resets the count."""
    sw = vault_jev_pass.Sweep()
    for r in ({"status": "error", "call_failed": True},) * 2 + ({"ok": True, "status": "ok"},):
        sw.note(r)
    assert not sw.skip and sw.failed_in_row == 0
    sw.note({"status": "error", "detail": "unreadable frame"})   # the item's image, not the call
    assert sw.failed_in_row == 0
    clips = tuple(range(7301, 7307))
    aid = await _seed(kind="video", mids=clips)
    o_vid, o_conc = vault_jev.run_video, vault_ai_vision._FLAGS_CONCURRENCY
    calls = []

    async def down(account_id, frames, **k):
        calls.append(1)
        return vault_jev.JevResult(ok=False, status="error", detail="ConnectError: down", cost_millicents=0,
                                   tok=0, call_failed=True)
    vault_jev.run_video, vault_ai_vision._FLAGS_CONCURRENCY = down, 1   # one at a time: "in a row" is exact
    try:
        with _Seams(*(lambda g: (g["rec"], g["nn"]))(_golden_with("resp"))), _Collect(_jpeg(576, 1024)) as col:
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, list(clips))
    finally:
        vault_jev.run_video, vault_ai_vision._FLAGS_CONCURRENCY = o_vid, o_conc
    prog = vault_ai_vision._flags_progress[aid]
    assert len(calls) == vault_jev_pass.DOWN_AFTER and col.clip_calls == vault_jev_pass.DOWN_AFTER, \
        (len(calls), col.clip_calls)
    assert prog["done"] == len(clips) and prog["failed"] == len(clips) and prog["capped"] is False, prog
    assert admission.JEV_VIDEO.busy == 0


async def case_video_no_720_reads_full_first():
    """No 720p rendition (probe 11-12: 3/30, natives 640x480 / 564x360, `files.full` the native file): `full` is
    tried before the 240p; off `full` the reading is `review` no_720 only when its frames' short side < 480; off
    the 240p (no `full`, or `full` over the cap) always no_720. A 720p clip never reaches `full` while 240 reads."""
    u240, ufull = "https://cdn.test/files/b/240.mp4?sig=1", "https://cdn.test/files/b/full.mp4?sig=1"
    v240, hi, lo = _mp4(64, 40), _mp4(640, 480, 3, 24), _mp4(564, 360, 3, 24)
    item = VaultItem(account_id="acc_nf", media_id=2, kind="video", duration_seconds=3)

    def media(full=True):
        m = {"duration": 3, "videoSources": {"720": None, "240": u240}}
        if full:
            m["files"] = {"full": {"url": ufull}}
        return m
    for body, review, px in ((hi, None, (640, 480)), (lo, "no_720", (564, 360))):
        with _FakeOF(media(), {ufull: body, u240: v240}) as of:
            got = await vault_frames.collect_jev_video("acc_nf", item)
        assert got.reason == "ok" and got.src == "full" and got.review == review and of.gets == [ufull], \
            (px, got[1:], of.gets)
        assert got.nbytes == len(body) and {tuple(_size(f)) for f in got.frames} == {px}, got[1:]
    with _FakeOF(media(full=False), {u240: v240}) as of:
        got = await vault_frames.collect_jev_video("acc_nf", item)
    assert got.src == "240" and got.review == "no_720" and of.gets == [u240], (got[1:], of.gets)
    saved = vault_frames.JEV_VIDEO_CAP_BYTES
    vault_frames.JEV_VIDEO_CAP_BYTES = len(hi) - 1
    try:
        with _FakeOF(media(), {ufull: hi, u240: v240}) as of:
            got = await vault_frames.collect_jev_video("acc_nf", item)
        assert got.src == "240" and got.review == "no_720" and of.gets == [ufull, u240], (got[1:], of.gets)
    finally:
        vault_frames.JEV_VIDEO_CAP_BYTES = saved
    with _FakeOF(media(), {ufull: _HttpResp(403, b""), u240: v240}) as of:
        got = await vault_frames.collect_jev_video("acc_nf", item)
    assert got.src == "240" and got.review == "no_720" and of.gets == [ufull, u240], (got[1:], of.gets)
    u720 = "https://cdn.test/files/b/720.mp4?sig=1"
    m720 = {**media(), "videoSources": {"720": u720, "240": u240}}
    with _FakeOF(m720, {u720: _mp4(160, 96, 3, 24), u240: v240, ufull: hi}) as of:
        got = await vault_frames.collect_jev_video("acc_nf", item)
    assert got.src == "720" and got.review is None and of.gets == [u720], (got[1:], of.gets)


async def case_video_one_deadline():
    """One absolute deadline per clip, set when `collect_jev_video` starts: the download + ffmpeg thread gets that
    same deadline (not lane entry + budget), ffmpeg's timeout never runs past it, and a slow clip that the thread
    still finishes is used, never thrown away as `fetch_failed` by an outer timer; the lane waits briefly (the
    visit holds a vision slot meanwhile)."""
    import time
    import vault_stills
    t = time.monotonic()
    assert vault_frames._ffmpeg_timeout(t + 500) == vault_frames._JEV_FFMPEG_TIMEOUT_S
    assert 15 <= vault_frames._ffmpeg_timeout(t + 20) <= 20 and vault_frames._ffmpeg_timeout(t - 5) == 1.0
    assert admission.JEV_VIDEO.wait_s <= 5, admission.JEV_VIDEO.wait_s
    u720 = "https://cdn.test/files/d/720.mp4?sig=1"
    item = VaultItem(account_id="acc_dl", media_id=4, kind="video", duration_seconds=12)
    seen = {}
    saved = vault_frames.JEV_VIDEO_TIMEOUT_S, vault_frames._jev_frames_sync

    def slow(client, media, dur, deadline):
        seen["deadline"] = deadline
        time.sleep(max(0.0, deadline - time.monotonic()) + 0.3)   # finishes just past the budget
        return vault_frames.JevFrames([_jpeg(160, 96)] * 12, "ok", src="720")
    vault_frames.JEV_VIDEO_TIMEOUT_S, vault_frames._jev_frames_sync = 1, slow
    try:
        with _FakeOF({"duration": 12, "videoSources": {"720": u720}}, {}):
            real = vault_stills.resolve_fresh

            async def fresh(*a, **k):
                await asyncio.sleep(0.3)   # the re-sign eats into the same budget
                return await real(*a, **k)
            vault_stills.resolve_fresh = fresh
            t0 = time.monotonic()
            got = await vault_frames.collect_jev_video("acc_dl", item)
    finally:
        vault_frames.JEV_VIDEO_TIMEOUT_S, vault_frames._jev_frames_sync = saved
    assert abs(seen["deadline"] - (t0 + 1)) < 0.2, (seen["deadline"] - t0)
    assert got.reason == "ok" and got.src == "720" and len(got.frames) == 12, got[1:]
    assert admission.JEV_VIDEO.busy == 0, "the lane slot leaked"


async def case_sweep_clips_queue_for_the_lane():
    """More clips than `JEV_VIDEO` slots in one sweep: every clip waits for its lane slot BEFORE its vision slot
    (`vault_jev_pass.clip_lane`) — none fails "lane full" however short the lane's own wait — the frame reads never
    exceed the lane's cap, photos (walked after the newer clips) are visited while clips still queue, no slot leaks."""
    import threading
    import time
    g = _golden_with("resp")
    cap = admission.JEV_VIDEO.cap
    clips = tuple(range(7101, 7101 + cap + 3))
    aid = await _seed(kind="video", mids=clips)
    async with get_session() as s:
        for i, m in enumerate((7201, 7202)):
            s.add(VaultItem(account_id=aid, media_id=m, kind="photo", tags="[]",
                            created_at=datetime(2026, 5, 1) + timedelta(minutes=i)))
        await s.commit()
    lock, live, seen = threading.Lock(), [0], {"peak": 0, "reads": 0, "photo_during_clips": False}

    def slow(client, media, dur, deadline):
        with lock:
            live[0] += 1
            seen["peak"], seen["reads"] = max(seen["peak"], live[0]), seen["reads"] + 1
        try:
            time.sleep(0.3)
            return vault_frames.JevFrames([_jpeg(576, 1024)] * 12, "ok", src="720", nbytes=1234)
        finally:
            with lock:
                live[0] -= 1

    async def photo(account_id, item, raw, want=1):
        seen["photo_during_clips"] |= live[0] > 0 or bool(admission.JEV_VIDEO._waiters)   # clips still queued
        return vault_frames.Collected([vault_ai_vision.vision.img_data_url(_jpeg(576, 1024))], "ok")
    saved = (vault_frames._jev_frames_sync, vault_frames.collect, admission.JEV_VIDEO.wait_s,
             vault_ai_vision._FLAGS_CONCURRENCY, admission.JEV_VIDEO.rejected)
    vault_frames._jev_frames_sync, vault_frames.collect = slow, photo
    # any lane wait inside a visit fails; one sweep slot past the lane's: a queued clip holding it would stall photos
    admission.JEV_VIDEO.wait_s, vault_ai_vision._FLAGS_CONCURRENCY = 0.01, cap + 1
    try:
        with _Seams(g["rec"], g["nn"]), _FakeOF({"duration": 12, "videoSources": {"720": "https://cdn.test/v.mp4"}}, {}):
            todo = await vault_ai_vision._flags_todo(aid)
            assert sorted(todo) == sorted(clips + (7201, 7202)), todo
            vault_ai_vision._flags_running.add(aid)
            await vault_ai_vision._run_flags_all(aid, todo)
        rejected = admission.JEV_VIDEO.rejected - saved[4]
    finally:
        (vault_frames._jev_frames_sync, vault_frames.collect, admission.JEV_VIDEO.wait_s,
         vault_ai_vision._FLAGS_CONCURRENCY) = saved[:4]
    prog = vault_ai_vision._flags_progress[aid]
    assert prog["failed"] == 0 and prog["done"] == len(clips) + 2, prog
    assert rejected == 0, f"{rejected} clips found the lane full"
    assert seen["reads"] == len(clips) and seen["peak"] <= cap, seen
    assert seen["photo_during_clips"], "photos waited behind the clips"
    for m in clips:
        f = await _fields(aid, m)
        assert f["_jev"]["status"] == "ok" and f["_jev"]["kind"] == "video", f["_jev"]
    assert admission.JEV_VIDEO.busy == 0, "the lane slot leaked"


def case_video_cap_env_and_budget():
    """`JEV_VIDEO_CAP_BYTES` env overrides the 50 MB cap (unset / junk / <= 0 → default); the per-clip budget
    covers a cap-sized file at ~1 MB/s (240 s at 50 MB, as before) and stays bounded."""
    import os
    saved = os.environ.pop("JEV_VIDEO_CAP_BYTES", None)
    try:
        assert vault_frames._env_cap_bytes() == 50_000_000
        for raw, want in (("120000000", 120_000_000), ("junk", 50_000_000), ("0", 50_000_000),
                          ("-5", 50_000_000), ("", 50_000_000)):
            os.environ["JEV_VIDEO_CAP_BYTES"] = raw
            assert vault_frames._env_cap_bytes() == want, (raw, vault_frames._env_cap_bytes())
    finally:
        os.environ.pop("JEV_VIDEO_CAP_BYTES", None)
        if saved is not None:
            os.environ["JEV_VIDEO_CAP_BYTES"] = saved
    assert vault_frames._budget_s(50_000_000) == 240
    assert vault_frames._budget_s(200_000_000) == 390 and vault_frames._budget_s(10**10) == 900
    if saved is None:
        assert vault_frames.JEV_VIDEO_CAP_BYTES == 50_000_000 and vault_frames.JEV_VIDEO_TIMEOUT_S == 240


_harness.run()
