#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

from token_bucket import Buckets  # noqa: E402


def case_take_refills_and_says_how_long():
    b = Buckets(max_keys=10)
    assert [b.take("a", 3, 6.0, 0.0) for _ in range(3)] == [None] * 3
    assert b.take("a", 3, 6.0, 0.0) == 6
    assert b.take("a", 3, 6.0, 4.0) == 2
    assert b.take("a", 3, 6.0, 6.0) is None
    assert b.take("b", 3, 6.0, 6.0) is None, "buckets are per key"


def case_a_drained_bucket_is_never_dropped_for_room():
    b = Buckets(max_keys=3)
    assert b.take(("user", "u"), 1, 600.0, 0.0) is None
    for i in range(10):
        assert b.take(("ip", i), 5, 1.0, 0.0) is None
    assert b.take(("user", "u"), 1, 600.0, 0.0) == 600, "the drained bucket was forgotten"
    assert len(b) == 11, len(b)


def case_refilled_buckets_are_dropped_oldest_write_first():
    b = Buckets(max_keys=3)
    for key in ("a", "b", "c"):
        assert b.take(key, 1, 60.0, 0.0) is None
    assert b.take("d", 1, 60.0, 30.0) is None
    assert len(b) == 4, len(b)
    assert b.take("e", 1, 60.0, 61.0) is None
    assert len(b) == 3 and b.take("d", 1, 60.0, 61.0) == 29, len(b)
    b.reset()
    assert len(b) == 0


_harness.run()
