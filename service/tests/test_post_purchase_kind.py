#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from transaction_ingest import _classify_kind  # noqa: E402


def case_post_purchase_by_is_ppv_post():
    got = _classify_kind("Post purchase by Jayb")
    assert got == "ppv_post", got
    assert _classify_kind("Post purchase by @VIP PAGE") == "ppv_post"
    assert _classify_kind("Post purchase by u224590315") == "ppv_post"
    assert _classify_kind("<a href='x'>Post purchase by John</a>") == "ppv_post"


def case_legacy_post_from_still_ppv_post():
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
