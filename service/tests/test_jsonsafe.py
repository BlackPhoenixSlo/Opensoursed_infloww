#!/usr/bin/env python3
"""test_jsonsafe.py — the column parser must DEGRADE, never raise.

`jsonsafe` exists so a leaf module can read one of this schema's many JSON TEXT
columns without a try/except at every call site. Its whole contract is one line:
whatever the column holds, the caller gets a usable value back. Nothing in it may
raise, because its callers sit in send paths — `parse_consistency_verdict` runs
BETWEEN generation and send, and its docstring is explicit that failing open is
deliberate: a verifier that can swallow a reply is worse than the contradiction it
exists to catch.

That contract was quietly broken by an exception net that LOOKED tighter and safer:

    except (TypeError, ValueError)

`json.loads` raises RecursionError on deeply nested input — a RuntimeError, not a
ValueError — so a 40KB blob of '[' propagated straight through the one function
whose job is to absorb it. The three hand-rolled parsers this module replaced all
caught bare `Exception`, so folding them in here was a silent narrowing.

  case_nothing_raises_on_any_shape:
      the contract itself, over every shape a column has actually held.
  case_deep_nesting_degrades_instead_of_raising:
      the specific regression, with the input that produces RecursionError.
  case_load_dict_insists_on_an_object:
      a column that holds a list/str/int is 'unset', not something the caller
      should have to isinstance-check before its next .get().

Run: ./venv/bin/python service/tests/test_jsonsafe.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from jsonsafe import PAYLOAD_CAP, dump_capped, load_dict, load_json  # noqa: E402

# Every shape these columns have actually held in this schema, plus the ones a
# corrupt/truncated write produces (the payload size cap trims outliers mid-token).
SHAPES = [
    None, "", "   ", "null", "[]", "{}", "0", "false", "not json at all",
    '{"a":1}', "[1,2]", '"a string"', '{"broken":', '[{"topic":"x"}',
    b'{"a":1}', 123, 4.5, True, {"already": "parsed"}, ["already", "parsed"],
    "﻿{}",                     # BOM-prefixed, as some exports write it
    " {}",                     # NBSP-prefixed — json.loads rejects this
]


async def case_nothing_raises_on_any_shape():
    """No input may escape as an exception. The fallback is the answer."""
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
    """The regression, with the input that actually triggers it.

    RecursionError is a RuntimeError subclass, so a `(TypeError, ValueError)` net
    lets it through. Depth is well past CPython's json recursion limit and the
    text is only ~40KB — comfortably inside the payload size cap, so this is
    reachable by a corrupt column, not a hypothetical."""
    deep = "[" * 20_000 + "]" * 20_000
    assert load_json(deep, "FALLBACK") == "FALLBACK", "deep nesting must degrade"
    assert load_dict(deep) == {}, "deep nesting must degrade to the empty object"

    # And prove the input really is the pathological one, so this case cannot
    # quietly stop testing anything if CPython's limits change.
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
    """`load_json(raw, {})` still hands back whatever parsed; the caller's next
    line is a `.get()` that raises. load_dict is the object-shaped contract."""
    assert load_dict('[1,2]') == {}
    assert load_dict('"a string"') == {}
    assert load_dict("null") == {}
    assert load_dict('{"a":1}') == {"a": 1}
    assert load_dict(["already", "parsed"]) == {}, "an already-parsed LIST is not a dict"
    # load_json keeps the looser promise, on purpose.
    assert load_json('[1,2]', {}) == [1, 2]
    assert load_json("null", "FB") == "FB", "a stored literal null is not a structure"


async def case_capped_dump_never_stores_a_fragment():
    """THE BUG (07-26): the payload cap was `json.dumps(...)[:64 * 1024]`, written
    four times. Slicing JSON at a byte offset makes unparseable text, not smaller
    JSON — 261 of that day's messages.raw_json rows were EXACTLY 65536 bytes, all
    but three of them ppv_send outbound. Nothing crashed, because load_json below
    degrades corrupt text and SQL json_extract returns NULL: half a payload read
    as no payload, silently. Whatever comes back here must PARSE."""
    import json

    small = {"text": "hi", "price": 300}
    assert json.loads(dump_capped(small)) == small, "under the cap: stored verbatim"

    # right at the boundary — the old slice broke exactly here
    exact = {"pad": "x" * (PAYLOAD_CAP - len(json.dumps({"pad": ""})))}
    out = dump_capped(exact)
    assert len(out) == PAYLOAD_CAP and json.loads(out) == exact, len(out)

    # over it: a valid, honest, greppable stub — never a prefix that looks like data
    over = {"media": ["m" * 200] * 1000}
    out = dump_capped(over)
    got = json.loads(out)                       # the assertion that would have failed before
    assert got["_dropped"] == "oversize", got
    assert got["_bytes"] > PAYLOAD_CAP, got
    assert len(out) < 100, "the stub must be small, not a trimmed payload"
    assert load_dict(out) == got, "and it must round-trip through the reader"

    # an unserializable payload is not worth raising into an ingest path
    class Exploding:
        def __repr__(self): raise RuntimeError("boom")
    got = load_dict(dump_capped({"bad": Exploding()}))
    assert got.get("_dropped") == "unserializable", got

    # the cap is a byte budget, so a wide payload of multibyte chars still fits it
    assert len(dump_capped({"s": "\u00e9" * PAYLOAD_CAP})) <= PAYLOAD_CAP


_harness.run(
    case_nothing_raises_on_any_shape,
    case_deep_nesting_degrades_instead_of_raising,
    case_load_dict_insists_on_an_object,
    case_capped_dump_never_stores_a_fragment,
)
