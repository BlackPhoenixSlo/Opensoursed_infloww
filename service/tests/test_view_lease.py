#!/usr/bin/env python3
"""
view_lease — the View lease registry's public functions (ADR-0031, phase-01 1a). No DB, no loop;
`now` is passed.

  case_renew_and_expiry:        a renewal leases its ids; they lapse TTL_S (60) after the last
                                renewal, and a renewal inside the TTL keeps them.
  case_union_across_holders:    two tabs of one principal and another principal: the union;
                                one holder lapsing keeps the others'.
  case_replace_per_holder:      a renewal replaces that holder's whole set; an empty list
                                releases it.
  case_newly_leased_only:       renew returns only Creators no live holder leased before (not a
                                re-renewal, not one another holder leases), and again after it
                                lapsed.
  case_selected_change:         a changed `selected` is returned even when already leased; the
                                same `selected` again is not; `selected` with no ids still leases it.
  case_selected_is_leased:      `selected` is leased with the ids (it is on screen).
  case_legacy_stream_ids:       a stream leases its clamp minus watchers only when unmarked, from a
                                browser page (Referer) and clamped; a table.
  case_legacy_stream_hold:      an open legacy stream's ids are in leased_ids and count as leased
                                for renew's gains; dropped at its end; lapse TTL_S after the last
                                frame when no end is seen.
  case_legacy_held_lifecycle:   legacy_held holds while frames flow, drops and closes the inner
                                stream when it ends, when it raises, and when the response stops
                                reading it early.

Run: ./venv/bin/python service/tests/test_view_lease.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import view_lease as vl  # noqa: E402

O1 = ("user", "u1", "tab-1")
O2 = ("user", "u1", "tab-2")
C1 = ("chatter", "c1", "tab-1")


def _reset() -> None:
    vl._holders.clear()
    vl._streams.clear()


def case_renew_and_expiry():
    _reset()
    assert vl.TTL_S == 60.0, vl.TTL_S
    assert vl.renew(O1, ["a", "b"], "a", now=0) == ["a", "b"]
    assert vl.leased_ids(30) == {"a", "b"} and vl.is_leased("a", 59.9)
    assert vl.renew(O1, ["a", "b"], "a", now=50) == []
    assert vl.leased_ids(109.9) == {"a", "b"}
    assert vl.leased_ids(110) == set() and not vl.is_leased("a", 110)
    assert O1 not in vl._holders, "expired holders are pruned"


def case_union_across_holders():
    _reset()
    vl.renew(O1, ["a"], None, now=0)
    vl.renew(O2, ["b"], None, now=10)
    vl.renew(C1, ["c", "a"], "c", now=20)
    assert vl.leased_ids(30) == {"a", "b", "c"}
    assert vl.leased_ids(65) == {"a", "b", "c"}, "O1 lapsed, C1 still leases a"
    assert vl.leased_ids(75) == {"a", "c"}
    assert vl.leased_ids(80) == set()


def case_replace_per_holder():
    _reset()
    vl.renew(O1, ["a", "b"], None, now=0)
    vl.renew(O1, ["c"], None, now=1)
    assert vl.leased_ids(2) == {"c"}
    assert vl.renew(O1, [], None, now=3) == []
    assert vl.leased_ids(4) == set() and O1 not in vl._holders


def case_newly_leased_only():
    _reset()
    assert vl.renew(O1, ["a", "b"], None, now=0) == ["a", "b"]
    assert vl.renew(O1, ["a", "b"], None, now=10) == []
    assert vl.renew(C1, ["b", "c"], None, now=11) == ["c"], "b is O1's already"
    assert vl.renew(O2, ["a", "d"], None, now=12) == ["d"]
    # every holder lapsed: a is newly leased again
    assert vl.renew(O1, ["a"], None, now=200) == ["a"]


def case_selected_change():
    _reset()
    assert vl.renew(O1, ["a", "b"], "a", now=0) == ["a", "b"]
    assert vl.renew(O1, ["a", "b"], "a", now=5) == [], "same selected: nothing"
    assert vl.renew(O1, ["a", "b"], "b", now=6) == ["b"], "selected changed, b already leased"
    vl.renew(C1, ["c"], None, now=7)
    assert vl.renew(O1, ["a", "b", "c"], "c", now=8) == ["c"], "c leased by C1, selected here"
    assert vl.renew(O1, ["a", "b", "c"], None, now=9) == [], "deselect refreshes nothing"
    assert vl.renew(O1, [], "a", now=10) == ["a"], "selected alone: leased, and a change from None"
    assert vl.leased_ids(10) == {"a", "c"}, "O1 now leases a alone; C1 still c"
    assert vl.renew(O1, [], None, now=11) == [] and vl.leased_ids(11) == {"c"}, "nothing named: released"


def case_selected_is_leased():
    _reset()
    assert vl.renew(O1, ["a"], "b", now=0) == ["a", "b"], "b newly leased (once, not twice)"
    assert vl.leased_ids(1) == {"a", "b"} and vl.is_leased("b", 1)


def case_legacy_stream_ids():
    acc = frozenset({"a", "b", "w"})
    watcher = lambda a: a == "w"  # noqa: E731
    page = "https://app.example/messages-pro"
    for lease, referer, accounts, want in [
        (None, page, acc, {"a", "b"}),           # a pre-1a tab: its clamp, watchers dropped
        ("1", page, acc, set()),                 # the app since 1a renews its own
        ("0", page, acc, set()),                 # any mark at all
        ("", page, acc, set()),
        (None, None, acc, set()),                # no Referer: desktop main-process notifier, scripts
        (None, "", acc, set()),
        (None, page, None, set()),               # unclamped (anonymous escape hatch): no wildcard
        (None, page, frozenset(), set()),        # no Creators
    ]:
        got = vl.legacy_stream_ids(lease, referer, accounts, watcher)
        assert got == want, (lease, referer, accounts, got)


def case_legacy_stream_hold():
    _reset()
    k1, k2 = object(), object()
    vl.hold_stream(k1, frozenset({"a", "b"}), now=0)
    assert vl.leased_ids(1) == {"a", "b"} and vl.is_leased("a", 1)
    assert vl.renew(O1, ["a", "c"], None, now=2) == ["c"], "a is the legacy stream's already"
    vl.hold_stream(k2, frozenset({"b"}), now=3)
    vl.drop_stream(k1)
    assert vl.leased_ids(4) == {"a", "b", "c"}, "O1 still leases a, k2 b"
    vl.drop_stream(k2)
    vl.drop_stream(k2)                            # twice: a no-op
    assert vl.leased_ids(5) == {"a", "c"}
    vl.hold_stream(k1, frozenset({"d"}), now=10)
    vl.hold_stream(k1, frozenset({"d"}), now=50)  # a frame re-holds
    assert vl.is_leased("d", 109.9)
    assert not vl.is_leased("d", 110) and k1 not in vl._streams, "no end seen: lapses TTL_S after the last frame"


def case_legacy_held_lifecycle():
    import asyncio

    closed: list[str] = []

    async def inner(n, fail=False):
        try:
            for i in range(n):
                yield f"f{i}".encode()
            if fail:
                raise RuntimeError("boom")
        finally:
            closed.append("inner")

    async def run_all(gen):
        out, during = [], []
        async for chunk in gen:
            out.append(chunk)
            during.append(vl.is_leased("a"))
        return out, during

    async def main():
        _reset()
        out, during = await run_all(vl.legacy_held(inner(3), frozenset({"a"})))
        assert out == [b"f0", b"f1", b"f2"] and during == [True] * 3, (out, during)
        assert vl._streams == {} and closed == ["inner"], (vl._streams, closed)

        closed.clear()
        try:
            await run_all(vl.legacy_held(inner(1, fail=True), frozenset({"a"})))
            raise AssertionError("the inner error was swallowed")
        except RuntimeError:
            pass
        assert vl._streams == {} and closed == ["inner"]

        closed.clear()
        gen = vl.legacy_held(inner(5), frozenset({"a"}))
        assert await gen.__anext__() == b"f0" and vl.is_leased("a")
        await gen.aclose()                        # the response stopped reading (client gone)
        assert vl._streams == {} and closed == ["inner"], (vl._streams, closed)

    asyncio.run(main())


_harness.run()
