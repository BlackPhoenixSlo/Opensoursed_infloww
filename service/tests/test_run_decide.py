#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import json  # noqa: E402

from run_decide import (  # noqa: E402
    FOLLOWUP_MARK, JOB_RETRY, JOB_RETRY_BACKOFF_S, MAY_HAVE_SENT, ONE_SHOT_KINDS, ORPHAN_REASON,
    Bind, Cancelled, Drop, Error, Retry,
    bind_claim, one_shot_family, outcome, park, payload_rule_id, sends_once,
)


def J(d) -> str:
    return json.dumps(d)


def case_payload_rule_id_table():
    rows = [
        (J({"_rule_id": 7}), 7),
        (J({"_rule_id": "7"}), 7),
        (J({"_rule_id": 7.9}), 7),
        (J({"_rule_id": None}), None),
        (J({"_rule_id": "x"}), None),
        (J({}), None),
        (J([1]), None),
        (J([]), None),
        ("{not json", None),
        ("", None),
        (None, None),
    ]
    for pj, want in rows:
        assert payload_rule_id(pj) == want, (pj, payload_rule_id(pj), want)


def case_bind_claim_table():
    rows = [
        (J({}), None, None, Bind(None)),
        (J({}), 5, True, Bind(5)),
        (J({}), 5, False, Bind(None)),
        (J({"_rule_id": 9}), None, True, Bind(None)),
        (J({"_rule_id": 9}), None, False, Drop(9)),
        (J({"_rule_id": 9}), 5, False, Drop(9)),
        (J({"_rule_id": 9}), 5, True, Bind(5)),
        (J({FOLLOWUP_MARK: True}), 5, True, Bind(5)),
        (J({FOLLOWUP_MARK: True}), 5, False, Drop(5)),
        (J({FOLLOWUP_MARK: True}), None, None, Bind(None)),
        ("{bad", 5, False, Bind(None)),
    ]
    for pj, rid, live, want in rows:
        got = bind_claim(pj, rid, live)
        assert got == want, (pj, rid, live, got, want)


def case_park_table():
    retry = Retry(JOB_RETRY_BACKOFF_S)
    rows = [
        (1, False, 3, Cancelled()),
        (3, False, 3, Cancelled()),
        (0, None, 3, retry),
        (1, None, 3, retry),
        (2, True, 3, retry),
        (3, True, 3, Error()),
        (4, None, 3, Error()),
        (1, True, 1, Error()),
    ]
    for attempts, live, mx, want in rows:
        got = park(attempts, live, mx)
        assert got == want, (attempts, live, mx, got, want)
    assert park(3, None, 4, 300) == Retry(300)
    assert park(4, True, 4, 300) == Error()
    assert park(1, False, 4, 300) == Cancelled()


def case_defers_refusal_table():
    from run_decide import ONE_SHOT_KINDS, PROXY_DEFER_KINDS, defers_refusal, proxy_tries
    assert PROXY_DEFER_KINDS <= ONE_SHOT_KINDS, "only one-shots wait out the proxy"
    rows = [
        ("send_mass_message", True, "none", True),
        ("mass_premade", True, "none", True),
        ("scheduled_send", True, "none", False),        # a chatter's DM: the plain retry
        ("send_mass_message", False, "none", False),    # not a refusal
        ("send_mass_message", True, "accepted", False),  # OF may have it: send once parks
        ("send_mass_message", True, "unanswered", False),
    ]
    for kind, refused, wrote, want in rows:
        assert defers_refusal(kind, refused, wrote) is want, (kind, refused, wrote)
    for reason, n in (("proxy_retry:2", 2), ("proxy_retry:3 (ProxyError(...))", 3), ("proxy_refused (x)", 0),
                      ("RuntimeError()", 0), (None, 0), ("proxy_retry:x", 0)):
        assert proxy_tries(reason) == n, (reason, n)
    from run_decide import proxy_refused_reason, proxy_retry_reason
    for n in (1, 2, 3):
        assert proxy_tries(proxy_retry_reason(n, "ProxyError('CONNECT 403: x y')")) == n
    assert proxy_tries(proxy_refused_reason("ProxyError()")) == 0


def case_outcome_table():
    rows = [
        ("ok", None, ("ok", "done")),
        ("ok", "ok", ("ok", "done")),
        ("ok", "skipped", ("skipped", "done")),
        ("words_blocked", None, ("ok", "done")),
        ("words_blocked", "skipped", ("skipped", "done")),
        ("cancelled", None, ("error", JOB_RETRY)),
        ("exception", None, ("error", JOB_RETRY)),
        ("unknown_kind", None, ("error", "error")),
    ]
    for kind, guard, want in rows:
        got = outcome(kind, guard, "boom")
        assert got == (*want, "sensitive_words" if guard == "skipped" else "boom"), (kind, guard, got, want)
    assert outcome("ok", None) == ("ok", "done", None)
    try:
        outcome("nope", None)  # type: ignore[arg-type]
    except AssertionError:
        pass
    else:
        raise AssertionError("an unknown outcome kind must raise")


def case_platform_outcome_table():
    lack = "platform_lacks:send_mass_message"
    rows = [
        ("ok", None, lack, ("skipped", "done", lack)),
        ("ok", None, "no_targets", ("ok", "done", None)),
        ("ok", None, 7, ("ok", "done", None)),
        ("ok", "skipped", lack, ("skipped", "done", "sensitive_words")),
        ("words_blocked", "skipped", None, ("skipped", "done", "sensitive_words")),
        ("ok", "ok", None, ("ok", "done", None)),
    ]
    for kind, guard, reason, want in rows:
        assert outcome(kind, guard, plugin_reason=reason) == want


def case_send_once_outcome_table():
    took = f"{MAY_HAVE_SENT}: OnlyFans took the send, then the run failed; not resent (boom)"
    unanswered = f"{MAY_HAVE_SENT}: the OnlyFans send got no answer; not resent (boom)"
    retry = ("error", JOB_RETRY, "boom")
    rows = [
        (False, "none", retry),
        (False, "unanswered", retry),
        (False, "accepted", retry),
        (True, "none", retry),
        (True, "unanswered", ("error", "error", unanswered)),
        (True, "accepted", ("error", "error", took)),
    ]
    for kind in ("cancelled", "exception"):
        for once, wrote, want in rows:
            got = outcome(kind, None, "boom", once=once, wrote=wrote)
            assert got == want, (kind, once, wrote, got, want)
    for kind in ("ok", "words_blocked"):
        assert outcome(kind, None, None, once=True, wrote="accepted") == ("ok", "done", None)
    try:
        outcome("exception", None, "boom", once=True, wrote="in_flight")  # type: ignore[arg-type]
    except AssertionError:
        pass
    else:
        raise AssertionError("an unknown write state must raise")


def case_one_shot_kinds():
    assert ONE_SHOT_KINDS == {"scheduled_send", "mass_premade", "send_mass_message"}, ONE_SHOT_KINDS
    assert ORPHAN_REASON == "interrupted, may have sent"
    family = set(one_shot_family())
    for kind in sorted(ONE_SHOT_KINDS):
        assert sends_once(kind), kind
        assert kind in family, (kind, family)
    for kind in ("auto_reply", "send_welcome", "send_followup",
                 "priority_mass", "unsend_messages", "auto_posts", "s4s_post",
                 "scrape_chats", "reply_mass_funnel", "nope"):
        assert not sends_once(kind), kind
        assert kind not in family, kind


_harness.run()
