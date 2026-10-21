#!/usr/bin/env python3
"""
transaction_ingest — feed-post sale classification (regression for the
"post revenue always 0" bug).

OF's ledger records feed-post unlocks with the description prefix
"Post purchase by <name>", but KIND_CATALOG only carried "Post from " — so
every real post sale fell through to kind='unknown' and never reached
posts_cents (fans.py sums kind='ppv_post', FanDrawer renders it). In the
prod DB all 86 "Post purchase by …" rows sat as 'unknown'. These cases pin
the added prefix and prove the neighbours still classify.

Run: ./venv/bin/python service/tests/test_post_purchase_kind.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from transaction_ingest import _classify_kind  # noqa: E402


def case_post_purchase_by_is_ppv_post():
    got = _classify_kind("Post purchase by Jayb")
    assert got == "ppv_post", got
    assert _classify_kind("Post purchase by @VIP PAGE") == "ppv_post"
    assert _classify_kind("Post purchase by u224590315") == "ppv_post"
    # HTML-wrapped variant still classifies (catalog strips tags first).
    assert _classify_kind("<a href='x'>Post purchase by John</a>") == "ppv_post"


def case_legacy_post_from_still_ppv_post():
    # Keep the older "Post from " prefix working alongside the new one.
    assert _classify_kind("Post from Zack") == "ppv_post"


def case_neighbours_unaffected():
    assert _classify_kind("Payment for message from X") == "ppv_message"
    assert _classify_kind("Tip on post from X") == "tip_post"
    assert _classify_kind("Tip from X") == "tip"
    assert _classify_kind("Subscription from X") == "subscription"
    assert _classify_kind("Recurring subscription from X") == "rebill"
    assert _classify_kind("Totally unrecognised memo") == "unknown"


_harness.run(
    case_post_purchase_by_is_ppv_post,
    case_legacy_post_from_still_ppv_post,
    case_neighbours_unaffected,
)
