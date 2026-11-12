#!/usr/bin/env python3
"""
The Jev-fed vault describe (`vault_describe_jev`, D51) and its `vault_ai_vision` wiring.
Plain-assert suite (repo convention), no network: frames and `llm_client.chat` are faked.

Cases:
  golden replay      34 bench records (dv6-F-hyb30nm A/B: 6dev incl. 619/649, set4, 5dev; dev ids only) —
                     the PRODUCT blob through the product module: route, facts, prompt, struct and scrub ==
                     the bench's byte for byte (fixture: .scratch/jev-vault-bench/dv6-golden-gen.py)
  route table        fail-safe: Jev off / missing / errored / stale / no `C` / clip / v1 / junk -> v2
  reusable table     a Jev-fed describe is a dupe source only while it still holds the `_jev` it was fed
  prose fields       the lane-feeding fields the prose path adds (explicitness, acts, folder, tags)
  prose garments     the prose path's `clothing_items` (qwen's, robust parse) -> vault_scripts.outfit_key non-empty
  blob C             `vault_jev_rules.blob(answers=...)` keeps the fact Choices; no Choices, not feedable
  wiring prose       Jev on, lane not review: prose prompt @640 on the caller's model, Jev struct, scrubbed prose,
                     garments, `_describe`
  wiring v6          review lane: v2 prompt + facts @960, enforced JSON, `_describe`
  wiring off         Jev off: today's prompt, image as collected, `_describe.path` v2
  reuse              reuse_state + `_copy_describe` refuse a source whose `_jev` moved on (incl. replaced, same v)

Run: cd service/tests && PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_describe_jev.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import gzip  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PIL import Image as PImage  # noqa: E402

import llm_client  # noqa: E402
import vault_ai_vision  # noqa: E402
import vault_ai_vision_decide as decide  # noqa: E402
import vault_describe_jev as vdj  # noqa: E402
import vault_frames  # noqa: E402
import vault_jev_rules as rules  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, VaultItem  # noqa: E402

GOLD = json.load(gzip.open(Path(__file__).parent / "fixtures" / "vault_describe_jev" / "golden.json.gz", "rt"))
CASES = GOLD["cases"]
V2P = vault_ai_vision._DESCRIBE_PROMPT_V2


def _table(rows, fn) -> None:
    bad = [f"{rid}: {got!r} != {want!r}" for rid, args, want in rows if (got := fn(*args)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def _case(path: str, scrubbed: bool = True) -> dict:
    return next(c for c in CASES if c["path"] == path and bool(c["scrub_log"]) == scrubbed)


# ── Pure ─────────────────────────────────────────────────────────────

def case_golden_replay():
    assert hashlib.sha256(V2P.encode()).hexdigest() == GOLD["v2_prompt_sha256"], "product V2 prompt != bench's"
    keys = [c["key"] for c in CASES]
    assert len(CASES) == 34 and {"6dev/619.jpg", "6dev/649.jpg"} <= set(keys)
    assert not any(k.startswith(("5seal", "6seal")) for k in keys)
    bad = []
    for c in CASES:
        j, F = c["jev"], c["facts"]
        base = vdj.PROSE_BENCH if c["path"] == "prose" else V2P
        got = {"route": vdj.route(kind="photo", jev_on=True, fields={"_jev": j})[0],
               "facts": [list(x) for x in vdj.facts(j)],
               "prompt": hashlib.sha256(vdj.build_prompt(base, vdj.facts(j)).encode()).hexdigest()}
        assert vdj.route(kind="photo", jev_on=True, fields={"_jev": j})[1] is j
        if c["path"] == "v6":
            assert vdj.prompt_for("v6", j, V2P) == vdj.build_prompt(V2P, vdj.facts(j))
        F = [tuple(x) for x in F]
        q = vdj.jev_struct(j, F) if c["path"] == "prose" else vdj.enforce(c["parsed"], F)
        text, log = vdj.scrub(c["parsed"].get("description", ""), c["struct"], F)
        ans = (vdj.prose_answer if c["path"] == "prose" else vdj.v6_answer)(c["parsed"], j)
        want = {"route": c["path"], "facts": c["facts"], "prompt": c["prompt_sha256"]}
        for k in want:
            if got[k] != want[k]:
                bad.append((c["key"], c["run"], k))
        if q != c["struct"]:
            bad.append((c["key"], c["run"], "struct"))
        if (text, log) != (c["desc_final"], c["scrub_log"]):
            bad.append((c["key"], c["run"], "scrub", text, c["desc_final"]))
        if ans["description"] != c["desc_final"] or any(ans.get(k) != v for k, v in c["struct"].items()
                                                         if k != "description"):
            bad.append((c["key"], c["run"], "answer"))
    assert not bad, f"{len(bad)} mismatches: {bad[:4]}"
    # The fixture exercises what matters: both paths, hedge, every scrub action.
    assert any(f[0] == "hedge" for c in CASES for f in c["facts"])
    acts = {a for c in CASES for a in c["scrub_log"]}
    assert {"drop_sentence", "append"} <= acts, acts


def _blob(**kw) -> dict:
    return {**_case("prose")["jev"], **kw}


def case_route_table():
    good = _blob(settled=False, lane="$10")
    _table([
        ("prose", (dict(kind="photo", jev_on=True, fields={"_jev": good}),), "prose"),
        ("review lane (settled) -> v6", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "settled": "nn.10"}}),), "v6"),
        ("jev off", (dict(kind="photo", jev_on=False, fields={"_jev": good}),), "v2"),
        ("video", (dict(kind="video", jev_on=True, fields={"_jev": good}),), "v2"),
        ("gif", (dict(kind="gif", jev_on=True, fields={"_jev": good}),), "v2"),
        ("v1 ask", (dict(kind="photo", jev_on=True, fields={"_jev": good}, prompt_version="v1"),), "v2"),
        ("no _jev", (dict(kind="photo", jev_on=True, fields={}),), "v2"),
        ("fields None", (dict(kind="photo", jev_on=True, fields=None),), "v2"),
        ("errored", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "status": "error"}}),), "v2"),
        ("stale version", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "v": "v7"}}),), "v2"),
        ("pre-C blob", (dict(kind="photo", jev_on=True, fields={"_jev": {k: v for k, v in good.items() if k != "C"}}),), "v2"),
        ("C missing a choice", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "C": {"toy": good["C"]["toy"]}}}),), "v2"),
        ("junk blob", (dict(kind="photo", jev_on=True, fields={"_jev": "x"}),), "v2"),
        ("junk C", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "C": {q: 1 for q in vdj.FACT_CHOICES}}}),), "v2"),
        ("C dicts without the keys", (dict(kind="photo", jev_on=True, fields={"_jev": {**good, "C": {q: {} for q in vdj.FACT_CHOICES}}}),), "v2"),
    ], lambda kw: vdj.route(**kw)[0])
    # the bench prompt + exactly the clothing_items ask
    p = vdj.PROSE_BENCH
    for old, new in vdj._CLOTHING_ASK:
        p = p.replace(old, new)
    assert vdj.PROSE_PROMPT == p != vdj.PROSE_BENCH and '"clothing_items"' in vdj.PROSE_PROMPT
    assert vdj.prompt_for("prose", good, V2P) == vdj.build_prompt(vdj.PROSE_PROMPT, vdj.facts(good))


def case_reusable_table():
    j = _blob(settled=False, lane="$10")
    meta = vdj.meta("prose", j, "qwen3-vl-30b")
    assert meta == {"path": "prose", "v": vdj.RECIPE_V, "jev_v": rules.VERSION, "jev_at": j["at"],
                    "model": "qwen3-vl-30b", "px": 640}
    assert vdj.meta("v2", j, "m") == {"path": "v2", "v": vdj.RECIPE_V, "jev_v": None, "jev_at": None,
                                      "model": "m", "px": None}
    _table([
        ("pre-stamp describe", ({"description": "x"},), True),
        ("v2 describe, any jev", ({"_describe": vdj.meta("v2", None, "m"), "_jev": {"status": "error"}},), True),
        ("prose on its own jev", ({"_describe": meta, "_jev": j},), True),
        ("prose, jev now review", ({"_describe": meta, "_jev": {**j, "settled": "nn.10"}},), False),
        ("prose, jev errored", ({"_describe": meta, "_jev": {**j, "status": "error"}},), False),
        ("prose, jev gone", ({"_describe": meta},), False),
        ("prose, jev other version", ({"_describe": {**meta, "jev_v": "v8"}, "_jev": j},), False),
        ("prose, jev replaced (same v, new at)", ({"_describe": meta, "_jev": {**j, "at": "2026-11-12T00:00:00"}},),
         False),
        ("v6 on a review jev", ({"_describe": vdj.meta("v6", j, "m"), "_jev": {**j, "settled": "nn.10"}},), True),
        ("None", (None,), True),
    ], vdj.reusable)


def case_prose_fields_table():
    base = _blob()

    def pf(lane, pen=None, tags=None, F=()):
        j = {**base, "lane": lane, "tags": {**base["tags"], **(tags or {})}}
        return vdj.prose_fields(j, list(F), {"penetration": pen})
    assert pf("$100", "toy")["explicitness"] == "hardcore" and pf("$100", "toy")["acts"] == ["toy_insertion"]
    assert pf("$50")["explicitness"] == pf("$10")["explicitness"] == "explicit"
    assert pf("lingerie")["explicitness"] == pf("mass")["explicitness"] == "suggestive"
    assert pf("$10", "fingers")["acts"] == ["fingering"] and pf("$10", "none")["acts"] == ["posing"]
    assert pf("$10", tags={"feet_focus": "y"})["primary_folder"] == "feet"
    assert pf("$10", tags={"feet_focus": "n"})["primary_folder"] == "boobs"
    assert pf("$100", "toy")["primary_folder"] == "solo_toy" and pf("$50")["primary_folder"] == "nude_stills"
    out = pf("$10", F=[("setting", "bathroom", "x"), ("mirror", "y", "x")])
    assert out["setting"] == "bathroom" and out["camera"] == "mirror"
    assert all("_" not in t for t in out["tags"])

    def cl(outfit, bf, lane="$10"):
        C = {**base["C"], "outfit": {k: (.9 if k == outfit else .02) for k in base["C"]["outfit"]}}
        o = vdj.prose_fields({**base, "lane": lane, "C": C}, [], {"body_focus": bf, "penetration": "none"})
        return o["clothing_state"], o["underwear_visible"], o["nsfw"]
    import vault_ai_brief
    _table([
        ("nude outfit", ("nude", ["nipples", "pussy"], "$50"), ("fully_nude", False, True)),
        ("topless (settle's table)", ("topless_with_bottoms", ["nipples"]),
         (vault_ai_brief._CLOTHING_FOR[(True, False)], True, True)),
        ("vulva only", ("lingerie_or_bodysuit", ["pussy"], "$50"), (vault_ai_brief._CLOTHING_FOR[(False, True)], True, True)),
        ("dressed, free", ("everyday_clothes", [], "mass"), ("dressed", True, False)),
        ("lingerie, free", ("lingerie_or_bodysuit", [], "lingerie"), ("lingerie_on", True, True)),
        ("towel, free", ("sheet_or_towel", [], "implied"), ("dressed", True, True)),
    ], cl)


# Every key the V2 describe prompt asks for (a V2 row's key set).
import re as _re  # noqa: E402

V2_KEYS = set(_re.findall(r'^  "(\w+)":', V2P[V2P.index("{"):V2P.index("RULES\n")], _re.M))
# What downstream reads off a describe row (vault_scripts, vault_pack_picker, vault_ai_brief, the vault modals,
# VaultItemEditor, useVaultCache).
CONSUMER_KEYS = {"description", "tags", "acts", "beats", "penetration", "clothing_state", "clothing_items",
                 "underwear_visible", "body_focus", "toys", "people_count", "partner_visible", "face_visible",
                 "position", "setting", "explicitness", "nsfw", "sellable", "primary_folder"}


def case_prose_key_set():
    assert len(V2_KEYS) == 23 and CONSUMER_KEYS <= V2_KEYS, sorted(V2_KEYS)
    for c in CASES:
        if c["path"] != "prose":
            continue
        got = set(vdj.prose_answer(c["parsed"], c["jev"]))
        missing = V2_KEYS - got
        assert missing <= set(vdj.PROSE_ABSENT), (c["key"], sorted(missing))
        assert CONSUMER_KEYS <= got and not set(vdj.PROSE_ABSENT) & CONSUMER_KEYS, c["key"]


def case_prose_no_self_contradiction():
    import vault_ai_brief
    seen = set()
    for c in CASES:
        if c["path"] != "prose":
            continue
        a = vdj.prose_answer(c["parsed"], c["jev"])
        want = vdj.struct_lane(a)
        # a flags pass that sees what Jev saw
        row = {**a, "breasts_vis": "bare" if want["nipple"] == "y" else "covered",
               "vulva_vis": "bare" if want["vulva"] == "y" else "covered", "anus_vis": "not_in_frame",
               "_flags_v": 3}
        assert vault_ai_brief.flags_known(row), c["key"]
        assert vault_ai_brief.contradictions(row) == [], (c["key"], vault_ai_brief.contradictions(row), a["clothing_state"])
        assert vault_ai_brief.settled_reading(row) is row
        seen.add(a["clothing_state"])
    assert len(seen) >= 3, seen


def case_prose_garments():
    import vault_scripts  # read-only: the outfit groups the prose rows must stay in
    _table([
        ("list", (["  red lace bra ", "red thong"],), ["red lace bra", "red thong"]),
        ("missing", (None,), []),
        ("string", ("red bra",), []),
        ("dict", ({"a": 1},), []),
        ("mixed junk", (["black bodysuit", 3, None, "", "  "],), ["black bodysuit"]),
    ], vdj.garments)
    C = {**_blob()["C"], "outfit": {k: (.9 if k == "lingerie_or_bodysuit" else .02) for k in _blob()["C"]["outfit"]}}
    j = _blob(settled=False, lane="lingerie", breasts_bare="n", crotch_bare="n", penetration="n", C=C)
    assert vdj.route(kind="photo", jev_on=True, fields={"_jev": j})[0] == "prose"
    a = vdj.prose_answer({"description": "She stands in a bedroom.", "clothing_items": ["red lace bra", "red thong"]}, j)
    assert a["clothing_items"] == ["red lace bra", "red thong"] and a["clothing_state"] == "lingerie_on"
    assert vault_scripts.outfit_key(a) == "red lingerie_set", vault_scripts.outfit_key(a)
    # what #501 shipped: no garments -> the photo falls out of every outfit group
    assert vault_scripts.outfit_key(vdj.prose_answer({"description": "x"}, j)) == ""
    assert vdj.prose_answer({"description": "x", "clothing_items": "red bra"}, j)["clothing_items"] == []


def case_blob_c():
    a = {q: {"type": "choice", "choice": "a", "probabilities": {"a": .9, "b": .1}} for q in rules.FACT_CHOICES}
    a["mirror_selfie"] = {"type": "noul", "noul": .2}
    d = {"lane5": "$10", "lane": "$10", "breasts_bare": "y", "crotch_bare": "n", "penetration": "n", "P": {}}
    b = rules.blob(d, {}, passes=["1"], tok=1, px=[1, 1], at="t", answers=a)
    assert b["C"] == {q: {"a": .9, "b": .1} for q in rules.FACT_CHOICES}, b["C"]
    b0 = rules.blob(d, {}, passes=["1"], tok=1, px=[1, 1], at="t", answers={})
    assert b0["C"] == {} and not vdj.feedable(b0)
    rec = {"resp": {"answers": {"x": 1}}, "resp2": {"answers": {"x": 2}}}
    assert rules.overlay(rec, {"need2": True})["x"] == 2 and rules.overlay(rec, {"need2": False})["x"] == 1


# ── Wiring (DB, fake frames + chat) ──────────────────────────────────

_N = 0


def _jpeg(w: int, h: int) -> bytes:
    b = io.BytesIO()
    PImage.new("RGB", (w, h), (120, 80, 60)).save(b, "JPEG", quality=90)
    return b.getvalue()


async def _seed(jev_on: bool, fields: dict, mids=(9001,)) -> str:
    global _N
    _N += 1
    aid = f"acc_vdj_{_N}"
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, daily_cost_cap_cents=1000, vault_jev_enabled=jev_on))
        for m in mids:
            s.add(VaultItem(account_id=aid, media_id=m, kind="photo", tags="[]", created_at=datetime(2026, 6, 1),
                            ai_fields_json=json.dumps(fields)))
        await s.commit()
    return aid


async def _fields(aid, mid=9001) -> dict:
    async with get_session() as s:
        return json.loads((await s.get(VaultItem, (aid, mid))).ai_fields_json or "{}")


class _Fakes:
    """Frames: one 1440×1080 still. chat: records (model, prompt, image size), answers `answer`."""

    def __init__(self, answer: str):
        self.answer, self.calls = answer, []

    def __enter__(self):
        self.saved = vault_frames.collect, llm_client.chat
        img = vault_ai_vision.vision.img_data_url(_jpeg(1440, 1080))

        async def _collect(account_id, item, raw, want=1):
            return vault_frames.Collected([img], "ok")

        async def _chat(*, model, messages, **kw):
            import base64
            c = messages[0]["content"]
            raw = base64.b64decode(c[1]["image_url"]["url"].partition(",")[2])
            self.calls.append({"model": model, "prompt": c[0]["text"], "px": list(PImage.open(io.BytesIO(raw)).size),
                               "max_tokens": kw.get("max_tokens")})
            return SimpleNamespace(content=self.answer, parsed=None, cost_cents=5, call_id=1)
        vault_frames.collect, llm_client.chat = _collect, _chat
        return self

    def __exit__(self, *a):
        vault_frames.collect, llm_client.chat = self.saved


async def case_wiring_prose():
    c = _case("prose")
    aid = await _seed(True, {"_jev": c["jev"]})
    ans = {"description": c["parsed"]["description"], "clothing_items": ["black lace thong"]}
    with _Fakes(json.dumps(ans)) as fk:
        res = await vault_ai_vision._describe_one(aid, 9001)
    assert res["ok"], res
    call, = fk.calls
    assert call["model"] == "qwen3-vl-30b" and max(call["px"]) == 640 and call["max_tokens"] is None
    assert call["prompt"] == vdj.prompt_for("prose", c["jev"], V2P) and '"clothing_items"' in call["prompt"]
    f = await _fields(aid)
    assert f["_describe"] == vdj.meta("prose", c["jev"], "qwen3-vl-30b"), f["_describe"]
    assert f["description"] == c["desc_final"] and f["_jev"] == c["jev"]
    assert f["clothing_items"] == ["black lace thong"]
    for k, v in c["struct"].items():
        assert f[k] == v, k
    assert f["explicitness"] in ("suggestive", "explicit", "hardcore")
    # the operator-picked model is the one called (no prose-only swap)
    aid2 = await _seed(True, {"_jev": c["jev"]})
    with _Fakes(json.dumps({"description": "Nude on a bed."})) as fk:
        await vault_ai_vision._describe_one(aid2, 9001, model="qwen3-vl-235b")
    assert [x["model"] for x in fk.calls] == ["qwen3-vl-235b"]
    assert (await _fields(aid2))["clothing_items"] == []


async def case_wiring_v6():
    c = next(x for x in CASES if x["path"] == "v6" and x["key"] == "6dev/619.jpg")
    aid = await _seed(True, {"_jev": c["jev"]})
    with _Fakes(json.dumps(c["parsed"])) as fk:
        res = await vault_ai_vision._describe_one(aid, 9001)
    assert res["ok"], res
    call, = fk.calls
    assert call["model"] == "qwen3-vl-30b" and max(call["px"]) == 960 and call["max_tokens"] is None
    assert vdj.HEDGE in call["prompt"] and call["prompt"].startswith(V2P[:V2P.index("RULES\n")])
    f = await _fields(aid)
    assert f["_describe"]["path"] == "v6" and f["_describe"]["px"] == 960
    assert f["description"] == c["desc_final"]
    for k, v in c["struct"].items():
        if k != "description":
            assert f[k] == v, k


async def case_wiring_off():
    c = _case("prose")
    aid = await _seed(False, {"_jev": c["jev"]})
    with _Fakes(json.dumps({"description": "A woman.", "tags": ["x"], "explicitness": "sfw"})) as fk:
        res = await vault_ai_vision._describe_one(aid, 9001)
    assert res["ok"], res
    assert fk.calls[0]["prompt"] == V2P and fk.calls[0]["px"] == [1440, 1080]
    f = await _fields(aid)
    assert f["_describe"] == vdj.meta("v2", None, "qwen3-vl-30b") and f["description"] == "A woman."


async def case_reuse_gate():
    c = _case("prose")
    j = c["jev"]
    fed = {"description": "x", "_describe": vdj.meta("prose", j, "m"), "_jev": j}
    moved = {**fed, "_jev": {**j, "status": "error"}}
    replaced = {**fed, "_jev": {**j, "at": "2026-11-12T00:00:00"}}   # re-run Jev: same v, still feedable
    assert vdj.feedable(replaced["_jev"]) and vdj.route(kind="photo", jev_on=True, fields=replaced)[0] == "prose"
    done, _ = decide.reuse_state([(1, "described", fed), (2, "described", moved), (3, "described", {"description": "x"}),
                                  (4, "described", replaced)], flags=False, flags_version=1)
    assert done == {1, 3}, done
    for src in (moved, replaced):
        aid = await _seed(True, src, mids=(9001, 9002))
        async with get_session() as s:
            (await s.get(VaultItem, (aid, 9001))).describe_status = "described"
            await s.commit()
        res = await vault_ai_vision._copy_describe(aid, 9001, 9002)
        assert res["status"] == "source_stale", res


_harness.run()
