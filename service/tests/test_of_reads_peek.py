#!/usr/bin/env python3
"""OFClient.get_messages `peek`: Background reads must peek (a first-page thread GET marks
the chat read on OF; `id=9223372036854775807` returns the same newest page and leaves it
unread, measured on sandbox OF 80000112).

  case_peek_table: peeked newest-first first page -> Int64-max Peek cursor; peek with an
      older-than cursor -> that cursor; no peek with an older-than cursor (load-older, vault
      poll) -> that cursor, unchanged; peek with an offset page -> no cursor; peek with asc is rejected; no peek
      -> no cursor. One GET each.
  case_pinned_read_peeks: get_pinned_messages always sends filter=pinned plus the Peek
      cursor (without an `id` it marks the chat read too).
  case_fansly_shim_accepts_and_ignores_peek: the Fansly shim takes `peek` and sends the
      same /message request as without it.

Run: ./venv/bin/python service/tests/test_of_reads_peek.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

import fansly_backend  # noqa: E402,F401 — puts ../fansly on sys.path
import of_client  # noqa: E402
import of_reads  # noqa: E402
from fansly_shim import FanslyShimClient  # noqa: E402

PEEK = 9223372036854775807


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.sent = []
    c.get_json = lambda path, params=None: c.sent.append((path, params)) or {"list": []}
    return c


def case_peek_table():
    assert of_reads.PEEK_CURSOR == PEEK
    path = f"{of_client.API_BASE}/chats/42/messages"
    base = {"limit": 50, "order": "desc", "skip_users": "all"}
    asc = {**base, "order": "asc"}
    cases = [
        ({"limit": 50, "peek": True}, {**base, "id": PEEK}),
        ({"limit": 50, "before_id": 777, "peek": True}, {**base, "id": 777}),
        ({"limit": 50, "before_id": 777}, {**base, "id": 777}),
        ({"limit": 50, "offset": 10, "peek": True}, {**base, "offset": 10}),
        ({"limit": 50, "order": "asc", "offset": 0}, {**asc, "offset": 0}),
        ({"limit": 50}, base),
    ]
    for kw, want in cases:
        c = _client()
        c.get_messages(42, **kw)
        assert c.sent == [(path, want)], (kw, c.sent)


def case_peek_rejects_non_desc_before_wire():
    for order in ("asc", "other"):
        c = _client()
        try:
            c.get_messages(42, order=order, peek=True)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid peek accepted")
        assert c.sent == []


def case_pinned_read_peeks():
    c = _client()
    assert c.get_pinned_messages(42) == []
    assert c.sent == [(f"{of_client.API_BASE}/chats/42/messages",
                       {"limit": 50, "order": "desc", "skip_users": "all",
                        "filter": "pinned", "id": PEEK})], c.sent


def case_fansly_shim_accepts_and_ignores_peek():
    sent: list[tuple] = []
    shim = FanslyShimClient.__new__(FanslyShimClient)
    shim.session = type("S", (), {"account_id": "fs1"})()
    shim._as_group_id = lambda chat_id: "g1"
    shim._fan_id_for_group = lambda gid: "f1"
    shim._purchases_by_fan = lambda: {}
    shim._request = lambda method, path, params=None: sent.append((method, path, params)) or {}
    for kw, want in (({}, {"groupId": "g1", "limit": "25"}),
                     ({"before_id": 9}, {"groupId": "g1", "limit": "25", "before": "9"})):
        for peek in ({}, {"peek": True}):
            sent.clear()
            shim.get_messages(42, **kw, **peek)
            assert sent == [("GET", "/message", want)], (kw, peek, sent)


_harness.run()
