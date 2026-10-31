#!/usr/bin/env python3
"""
customs_decide — table tests over the customs queue's pure order logic (the shell is
customs_api: `customs_order` reads + strips the thread and the blast groups, then calls
blast_counts / order_span; `customs_brief` merges window + span through brief_msgs, then
brief_skip_reason).
No DB, no LLM:

  case_anchor_table:        only HIS non-tip line opens an order: our outbound "custom" and
                            a tip whose text says "custom" do not -> "no order talk" reason.
  case_gap_table:           walking back from the newest anchor: a 45-day silence stays one
                            order, 46 days ends it (the older order is excluded); 3 anchors
                            0/100/110 and 0/10/100 both open at day 100; at=None bridges.
  case_span_table:          span keeps tips (any length) and own-words lines >= 12 chars; a
                            short line is dropped; our line sent to > 1 fan is dropped, to 1
                            fan kept; HIS line is never blast-filtered.
  case_blast_variants:      3 `<br/>` wrappers of one blast, each to 1 fan, SUM to 3 on the
                            stripped key -> dropped from the span.
  case_spec_filter:         _ORDER_MAX_FULL lines -> whole; _ORDER_MAX_FULL+1 -> truncated,
                            word-boundary spec filter keeps "5 min video", drops "reminded" /
                            "says"; a tip survives the filter.
  case_whole_messages:      a substring quote -> his full message; a miss dropped; two quotes
                            of one message deduped; curly quotes and a trailing "…" match.
  case_brief_msgs:          merge by message_id (span wins), sorted by `at`; brief_skip_reason:
                            no rows / no line of his -> the ok:false reason, else None.

Run: ./venv/bin/python service/tests/test_customs_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from datetime import datetime, timedelta  # noqa: E402

from automation_executor import _strip_html  # noqa: E402
from customs_decide import (  # noqa: E402
    _ORDER_MAX_FULL, _Msg, _whole_messages, blast_counts, brief_msgs, brief_skip_reason,
    order_span,
)

T0 = datetime(2026, 9, 1, 10, 0)
NO_ORDER = "no order talk found in this thread"


def _m(i, direction, text, days=0.0, tip=False):
    return _Msg(i, direction, text, T0 + timedelta(days=days), tip)


def _texts(res):
    return [ln["text"] for ln in res["lines"]]


def case_anchor_table():
    rows = [
        ("outbound custom", [_m(1, "out", "want a custom video babe?")], NO_ORDER),
        ("tip says custom", [_m(1, "in", "custom tip for you", tip=True)], NO_ORDER),
        ("his custom", [_m(1, "in", "can you make me a custom")], None),
        ("his voice note", [_m(1, "in", "send me a voice note please")], None),
        ("no anchor word", [_m(1, "in", "send me a video please")], NO_ORDER),
    ]
    for name, msgs, reason in rows:
        res = order_span(msgs, {})
        assert res.get("reason") == reason, (name, res)
        if reason:
            assert res == {"lines": [], "count": 0, "opened_at": None,
                           "truncated": False, "reason": reason}, (name, res)
        else:
            assert res["count"] == 1 and res["opened_at"] == T0.isoformat(), (name, res)


def case_gap_table():
    # (anchor days oldest-first, None = no timestamp; index of the anchor that opens)
    rows = [
        ([0, 44], 0), ([0, 45], 0), ([0, 46], 1), ([0, 400], 1),
        ([0, 100, 110], 1),                    # old order cut, last two one order
        ([0, 10, 100], 2),                     # walk back from NEWEST: 0/10 is the old one
        ([0, None, 400], 0),                   # a missing `at` never breaks the walk
    ]
    for days, opens in rows:
        msgs = [_Msg(i, "in", f"custom number {i}: wear the hat",
                     None if d is None else T0 + timedelta(days=d), False)
                for i, d in enumerate(days)]
        res = order_span(msgs, {})
        at = msgs[opens].at
        assert res["opened_at"] == (at.isoformat() if at else None), (days, res["opened_at"])
        assert _texts(res) == [m.text for m in msgs[opens:]], (days, _texts(res))


def case_span_table():
    blast = {"unlock it and you get every clip": 2, "only you get this one babe": 1,
             "so you want a custom then": 5}
    msgs = [
        _m(1, "in", "i want a custom where you say my name"),
        _m(2, "in", "ok babe"),                                # 7 chars  -> dropped
        _m(3, "in", "", tip=True),                             # tip      -> kept
        _m(4, "out", "unlock it and you get every clip"),      # blast 2  -> dropped
        _m(5, "out", "only you get this one babe"),            # blast 1  -> kept
        _m(6, "in", "so you want a custom then"),              # HIS line -> kept
        _m(7, "out", "elevenchars"),                           # 11 chars -> dropped
        _m(8, "out", "twelve chars"),                          # 12 chars -> kept
    ]
    res = order_span(msgs, blast)
    assert [ln["message_id"] for ln in res["lines"]] == [1, 3, 5, 6, 8], res["lines"]
    assert res["count"] == 5 and res["truncated"] is False
    tip = res["lines"][1]
    assert tip == {"message_id": 3, "from_fan": True, "is_tip": True, "text": "",
                   "at": T0.isoformat()}, tip
    assert res["lines"][2]["from_fan"] is False


def case_blast_variants():
    copy = "unlock the full bundle"
    rows = [(f"{copy}<br/>every clip", 1), (f"{copy}<br>every clip", 1),
            (f"{copy}<br />every clip", 1), (None, 4)]
    blast = blast_counts(rows, _strip_html)
    key = _strip_html(f"{copy}<br/>every clip")
    assert blast == {key: 3, "": 4}, blast
    assert blast_counts([("x" * 130, 1), ("x" * 125 + "y", 1)], _strip_html) == {"x" * 120: 2}
    msgs = [_m(1, "in", "can you do a custom for me"), _m(2, "out", key)]
    assert _texts(order_span(msgs, blast)) == ["can you do a custom for me"]
    # Assigned instead of summed, the variant scores 1 and leaks in.
    assert key in _texts(order_span(msgs, {key: 1}))


def case_spec_filter():
    msgs = [_m(0, "in", "i want a custom from you")]
    keep = ["5 min video please babe", "wear the red hat for it"]
    drop = ["you reminded me of you", "she says hello to you"]
    filler = [f"filler line number {i}" for i in range(_ORDER_MAX_FULL - len(keep + drop))]
    for i, text in enumerate(keep + drop + filler, start=1):
        msgs.append(_m(i, "in" if i % 2 else "out", text, i / 24))
    assert len(msgs) == _ORDER_MAX_FULL + 1
    full = order_span(msgs[:_ORDER_MAX_FULL], {})
    assert full["truncated"] is False and full["count"] == _ORDER_MAX_FULL
    over = order_span(msgs, {})
    assert over["truncated"] is True, over["count"]
    assert _texts(over) == ["i want a custom from you", *keep], _texts(over)
    res = order_span(msgs + [_m(99, "in", "", 2, tip=True)], {})
    assert res["truncated"] is True, res["count"]
    assert _texts(res) == ["i want a custom from you", *keep, ""], _texts(res)


def case_whole_messages():
    fan = [{"text": "can you do a custom where you say my name"},
           {"text": "I'm your daddy tonight, call me that"},
           {"text": "  ten minutes no cuts  "}]
    rows = [
        (["say my name"], ["can you do a custom where you say my name"]),
        (["nothing he ever said"], []),
        (["say my name", "a custom where"], ["can you do a custom where you say my name"]),
        (["I’m your daddy"], ["I'm your daddy tonight, call me that"]),
        (["“say  MY name…”"], ["can you do a custom where you say my name"]),
        (["no cuts"], ["ten minutes no cuts"]),
        (["", " … "], []),
    ]
    for quotes, want in rows:
        assert _whole_messages(quotes, fan) == want, (quotes, _whole_messages(quotes, fan))


def case_brief_msgs():
    span = [{"message_id": 2, "from_fan": True, "is_tip": False, "text": "SPAN",
             "at": "2026-09-02T10:00:00"}]
    window = [{"message_id": 3, "from_fan": False, "is_tip": False, "text": "w3",
               "at": "2026-09-03T10:00:00"},
              {"message_id": 2, "from_fan": True, "is_tip": False, "text": "WINDOW",
               "at": "2026-09-02T10:00:00"},
              {"message_id": 1, "from_fan": False, "is_tip": False, "text": "w1",
               "at": "2026-09-01T10:00:00"},
              {"message_id": 4, "from_fan": True, "is_tip": True, "text": "",
               "at": None}]
    msgs = brief_msgs(span, window)
    assert [(m["message_id"], m["text"]) for m in msgs] == \
        [(4, ""), (1, "w1"), (2, "SPAN"), (3, "w3")], msgs
    assert brief_skip_reason(msgs) is None
    never = "he never said what he wanted in this window"
    rows = [
        ([], [], "no stored messages around this tip"),
        ([], [window[0], window[2]], never),                   # only US lines
        ([], [window[3]], never),                              # only a tip of his
        (span, [], None),                                      # one line of his
    ]
    for s, w, reason in rows:
        assert brief_skip_reason(brief_msgs(s, w)) == reason, (s, w)


_harness.run()
