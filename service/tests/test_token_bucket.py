#!/usr/bin/env python3
"""token_bucket.Buckets: the one store behind login_throttle and the public
tracking-link verify budget.

  case_take_refills_and_says_how_long: capacity, then a wait in whole seconds,
      then one token per refill_s.
  case_a_drained_bucket_is_never_dropped_for_room: past max_keys a drained
      bucket is kept and the store grows (#23).
  case_refilled_buckets_are_dropped_oldest_write_first: refilled buckets at
      the head go once the store is past max_keys.

Run: ./venv/bin/python service/tests/test_token_bucket.py  (exit 0 = pass)
"""
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
    """#23: past max_keys only buckets already refilled are dropped (oldest
    write first); a drained one is kept and the store grows instead, so a flood
    of other keys can never hand a drained key a fresh bucket."""
    b = Buckets(max_keys=3)
    assert b.take(("user", "u"), 1, 600.0, 0.0) is None          # drained, full again at 600
    for i in range(10):                                         # > max_keys other keys
        assert b.take(("ip", i), 5, 1.0, 0.0) is None
    assert b.take(("user", "u"), 1, 600.0, 0.0) == 600, "the drained bucket was forgotten"
    assert len(b) == 11, len(b)                                  # grew past the soft cap


def case_refilled_buckets_are_dropped_oldest_write_first():
    b = Buckets(max_keys=3)
    for key in ("a", "b", "c"):
        assert b.take(key, 1, 60.0, 0.0) is None                 # full again at 60
    assert b.take("d", 1, 60.0, 30.0) is None                    # none refilled: grows
    assert len(b) == 4, len(b)
    assert b.take("e", 1, 60.0, 61.0) is None                    # a, b refilled: dropped back to 3 (c stays)
    assert len(b) == 3 and b.take("d", 1, 60.0, 61.0) == 29, len(b)  # d kept (not refilled)
    b.reset()
    assert len(b) == 0


_harness.run()
