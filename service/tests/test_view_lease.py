#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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


def case_refresh_plan():
    cur = {"c"}
    fresh = {"f"}
    for gains, selected, opened, want in [
        (["a", "b"], None, False, ([], ["a", "b"])),
        (["a", "b"], "a", False, (["a"], ["b"])),
        (["a", "c"], None, False, ([], ["a"])),
        (["c"], "c", False, (["c"], [])),
        (["f"], "f", False, ([], [])),
        (["a", "b"], "a", True, (["a"], [])),
        (["f", "b"], "f", True, ([], [])),
        ([], None, False, ([], [])),
    ]:
        got = vl.refresh_plan(gains, selected, opened=opened, current=cur.__contains__, fresh=fresh.__contains__)
        assert got == want, (gains, selected, opened, got)


def case_legacy_stream_ids():
    acc = frozenset({"a", "b", "w"})
    watcher = lambda a: a == "w"  # noqa: E731
    page = "https://app.example/messages-pro"
    for lease, referer, accounts, want in [
        (None, page, acc, {"a", "b"}),
        ("1", page, acc, set()),
        ("0", page, acc, set()),
        ("", page, acc, set()),
        (None, None, acc, set()),
        (None, "", acc, set()),
        (None, page, None, set()),
        (None, page, frozenset(), set()),
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
    vl.drop_stream(k2)
    assert vl.leased_ids(5) == {"a", "c"}
    vl.hold_stream(k1, frozenset({"d"}), now=10)
    vl.hold_stream(k1, frozenset({"d"}), now=50)
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
        await gen.aclose()
        assert vl._streams == {} and closed == ["inner"], (vl._streams, closed)

    asyncio.run(main())


_harness.run()
