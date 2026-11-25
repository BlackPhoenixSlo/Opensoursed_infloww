#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from types import SimpleNamespace  # noqa: E402

from automations._funnel_routing import resolve_next, step_number_index, strip_html  # noqa: E402


def _facts(replied=False, bought=False, substantive=False, reply_text=""):
    return SimpleNamespace(replied=replied, bought=bought, substantive=substantive,
                           reply_text=reply_text)


def case_strip_html():
    rows = [
        (None, "", "None"),
        ("", "", "empty"),
        ("  hi  ", "hi", "plain trimmed"),
        ("<p>hey</p>", "hey", "p tag"),
        ("<p> a <b>b</b> </p>", "a b", "nested tags, outer trim only"),
        ("a<br/>b", "ab", "br removed, no newline inserted"),
        ("&amp; <i>x</i>", "&amp; x", "entities NOT unescaped"),
        ("1 < 2", "1 < 2", "lone < kept (no closing >)"),
        ("a <3 b>", "a", "'<3 b>' looks like a tag and is eaten"),
    ]
    for raw, exp, label in rows:
        got = strip_html(raw)
        assert got == exp, f"strip_html[{label}]: got {got!r}, expected {exp!r}"


def case_step_number_index():
    rows = [
        ([], {}, "no steps"),
        ([{"step": 1}, {"step": 2}, {"step": 3}], {1: 0, 2: 1, 3: 2}, "linear"),
        ([{"step": "2"}, {"step": 1}], {2: 0, 1: 1}, "str number, out of order"),
        ([{"step": None}, {}, {"step": "x"}, {"step": 4}], {4: 3}, "bad/missing skipped"),
        ([{"step": 1}, {"step": 1}], {1: 1}, "duplicate number: last index wins"),
        ([{"step": 2.9}], {2: 0}, "float truncates"),
    ]
    for steps, exp, label in rows:
        got = step_number_index(steps)
        assert got == exp, f"step_number_index[{label}]: got {got!r}, expected {exp!r}"


_NUM = {n: n - 1 for n in range(1, 7)}
_FULL = {"next": {"keyword": {"more": 5, "no": 6}, "bought": 4, "ignored": 3, "default": 2}}


def case_resolve_next():
    F = _facts
    C = 5
    rows = [
        ({}, F(), 0, 1, "no next -> +1"),
        ({"next": None}, F(replied=True), 2, 3, "next None -> +1"),
        ({"next": [3]}, F(), 2, 3, "next not dict -> +1"),
        ({"next": {}}, F(replied=True), 2, 3, "empty dict -> +1"),
        (_FULL, F(replied=True, substantive=True, reply_text="<p>send MORE pls</p>"),
         C, 4, "keyword wins, case-insensitive, html stripped"),
        (_FULL, F(replied=True, bought=True, substantive=True, reply_text="more"),
         C, 4, "keyword beats bought"),
        (_FULL, F(replied=True, bought=True, substantive=False, reply_text="more"),
         C, 3, "non-substantive reply skips keyword -> bought"),
        (_FULL, F(replied=True, substantive=True, reply_text="now"),
         C, 1, "'no' does not hit 'now' -> default"),
        (_FULL, F(replied=True, substantive=True, reply_text="no, more"),
         C, 4, "first DICT key that hits wins (more before no)"),
        (_FULL, F(replied=True, substantive=True, reply_text="no thanks"),
         C, 5, "second keyword"),
        (_FULL, F(replied=False, bought=True), C, 3, "bought beats ignored"),
        (_FULL, F(replied=False), C, 2, "ignored"),
        (_FULL, F(replied=True), C, 1, "replied, nothing else -> default"),
        ({"next": {"bought": 4}}, F(replied=True), 1, 2, "no matching branch, no default -> +1"),
        ({"next": {"ignored": 3}}, F(replied=True), 3, 4, "ignored set but replied -> +1"),
        ({"next": {"default": 99}}, F(replied=True), 1, 2, "unknown target -> +1"),
        ({"next": {"default": "x"}}, F(replied=True), 1, 2, "non-int target -> +1"),
        ({"next": {"default": "5"}}, F(replied=True), 1, 4, "str target number resolves"),
        ({"next": {"default": 0}}, F(replied=True), 3, 4, "target 0 is unknown step -> +1"),
        ({"next": {"bought": None, "default": 2}}, F(bought=True, replied=True),
         3, 1, "bought None skipped -> default"),
        ({"next": {"keyword": {"": 5, "  ": 6}, "default": 2}},
         F(replied=True, substantive=True, reply_text="anything"), 3, 1, "blank keywords never hit"),
        ({"next": {"keyword": ["more"], "default": 2}},
         F(replied=True, substantive=True, reply_text="more"), 3, 1, "keyword not dict ignored"),
        ({"next": {"keyword": {"c++": 5}, "default": 2}},
         F(replied=True, substantive=True, reply_text="i like c++"), 3, 1,
         "keyword ending in non-word char needs \\b after it -> no hit (today)"),
        ({"next": {"keyword": {"more": 5}, "default": 2}},
         F(replied=True, substantive=True, reply_text=None), 3, 1, "None reply text -> no hit"),
        ({"next": {"keyword": {"more": 99}, "default": 2}},
         F(replied=True, substantive=True, reply_text="more"), 3, 4,
         "keyword hit with unknown target -> +1 (does NOT fall through to default)"),
        ({"next": {"keyword": {"Ñoño": 5}}},
         F(replied=True, substantive=True, reply_text="ÑOÑO!"), 0, 4, "unicode casefold"),
    ]
    for step, facts, cur, exp, label in rows:
        got = resolve_next(step, facts, _NUM, cur)
        assert got == exp, f"resolve_next[{label}]: got {got!r}, expected {exp!r}"


_harness.run(case_strip_html, case_step_number_index, case_resolve_next)
