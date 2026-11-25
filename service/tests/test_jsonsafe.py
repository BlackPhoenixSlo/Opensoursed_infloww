#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from jsonsafe import PAYLOAD_CAP, dump_capped, load_dict, load_json  # noqa: E402

SHAPES = [
    None, "", "   ", "null", "[]", "{}", "0", "false", "not json at all",
    '{"a":1}', "[1,2]", '"a string"', '{"broken":', '[{"topic":"x"}',
    b'{"a":1}', 123, 4.5, True, {"already": "parsed"}, ["already", "parsed"],
    "﻿{}",
    " {}",
]


async def case_nothing_raises_on_any_shape():
    raised = []
    for s in SHAPES:
        for label, call in (("load_json", lambda s=s: load_json(s, "FB")),
                            ("load_dict", lambda s=s: load_dict(s))):
            try:
                call()
            except BaseException as e:          # noqa: BLE001 — that is the point
                raised.append((label, repr(s)[:40], type(e).__name__))
    assert not raised, ("jsonsafe raised instead of degrading", raised)


async def case_deep_nesting_degrades_instead_of_raising():
    deep = "[" * 20_000 + "]" * 20_000
    assert load_json(deep, "FALLBACK") == "FALLBACK", "deep nesting must degrade"
    assert load_dict(deep) == {}, "deep nesting must degrade to the empty object"

    import json
    try:
        json.loads(deep)
        raised = None
    except BaseException as e:                  # noqa: BLE001
        raised = type(e).__name__
    assert raised == "RecursionError", (
        "the fixture no longer produces RecursionError — pick a deeper input, "
        "otherwise this case is vacuous", raised)


async def case_load_dict_insists_on_an_object():
    assert load_dict('[1,2]') == {}
    assert load_dict('"a string"') == {}
    assert load_dict("null") == {}
    assert load_dict('{"a":1}') == {"a": 1}
    assert load_dict(["already", "parsed"]) == {}, "an already-parsed LIST is not a dict"
    assert load_json('[1,2]', {}) == [1, 2]
    assert load_json("null", "FB") == "FB", "a stored literal null is not a structure"


async def case_capped_dump_never_stores_a_fragment():
    import json

    small = {"text": "hi", "price": 300}
    assert json.loads(dump_capped(small)) == small, "under the cap: stored verbatim"

    exact = {"pad": "x" * (PAYLOAD_CAP - len(json.dumps({"pad": ""})))}
    out = dump_capped(exact)
    assert len(out) == PAYLOAD_CAP and json.loads(out) == exact, len(out)

    over = {"media": ["m" * 200] * 1000}
    out = dump_capped(over)
    got = json.loads(out)
    assert got["_dropped"] == "oversize", got
    assert got["_bytes"] > PAYLOAD_CAP, got
    assert len(out) < 100, "the stub must be small, not a trimmed payload"
    assert load_dict(out) == got, "and it must round-trip through the reader"

    class Exploding:
        def __repr__(self): raise RuntimeError("boom")
    got = load_dict(dump_capped({"bad": Exploding()}))
    assert got.get("_dropped") == "unserializable", got

    assert len(dump_capped({"s": "\u00e9" * PAYLOAD_CAP})) <= PAYLOAD_CAP


_harness.run(
    case_nothing_raises_on_any_shape,
    case_deep_nesting_degrades_instead_of_raising,
    case_load_dict_insists_on_an_object,
    case_capped_dump_never_stores_a_fragment,
)
