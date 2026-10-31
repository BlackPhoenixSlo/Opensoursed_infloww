#!/usr/bin/env python3
"""
run_decide — table tests over the scheduled-jobs lane's pure decisions (the shells:
automation_executor.run_once reads the claimed row and the rule's liveness; job_queue.
_park_failed_job reads the attempts and the liveness). No DB, no loop:

  case_payload_rule_id_table:  the payload's `_rule_id` as an int; absent, null, non-int,
                               non-dict or unparsable payload -> None.
  case_bind_claim_table:       a tagged job on a dead rule -> Drop(tagged); a live rule's job
                               binds its rule_id; Run-now (rule_id, untagged) on a disabled rule
                               binds None (a one-shot); a rule-less job binds None.
  case_park_table:             rule off -> Cancelled whatever the attempts; else
                               Retry(JOB_RETRY_BACKOFF_S)
                               below max_attempts, Error at/over it; no rule (None) never
                               cancels.
  case_outcome_table:          ok / words_blocked -> (guard status or ok, done, err), never
                               retried; cancelled / exception -> (error, JOB_RETRY, err);
                               unknown_kind -> (error, error, err); anything else ->
                               AssertionError.
  case_send_once_outcome_table: cancelled / exception x once x wrote: a sweep, or a one-shot
                               with no write OF may have taken -> JOB_RETRY (today's retry);
                               a one-shot once a write is unanswered or accepted -> 'error',
                               the "may have sent" reason heading the run's error.
  case_one_shot_kinds:         scheduled_send / mass_premade / send_mass_message (and their
                               family) send once; every sweep (auto replies, welcome,
                               followup, s4s_post, ...) does not.

Run: ./venv/bin/python service/tests/test_run_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

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
        # (payload_json, job.rule_id, rule_live, decision)
        (J({}), None, None, Bind(None)),                       # one-shot
        (J({}), 5, True, Bind(5)),                             # live rule's job
        (J({}), 5, False, Bind(None)),                         # Run-now on a disabled rule: one-shot
        (J({"_rule_id": 9}), None, True, Bind(None)),          # tagged, live, no row rule
        (J({"_rule_id": 9}), None, False, Drop(9)),            # tagged, rule off -> dropped
        (J({"_rule_id": 9}), 5, False, Drop(9)),
        (J({"_rule_id": 9}), 5, True, Bind(5)),
        (J({FOLLOWUP_MARK: True}), 5, True, Bind(5)),          # follow-on, rule live
        (J({FOLLOWUP_MARK: True}), 5, False, Drop(5)),         # follow-on, rule off -> dropped
        (J({FOLLOWUP_MARK: True}), None, None, Bind(None)),    # marked, no rule: nothing to die with
        ("{bad", 5, False, Bind(None)),
    ]
    for pj, rid, live, want in rows:
        got = bind_claim(pj, rid, live)
        assert got == want, (pj, rid, live, got, want)


def case_park_table():
    retry = Retry(JOB_RETRY_BACKOFF_S)
    rows = [
        # (attempts, rule_live, max_attempts, decision)
        (1, False, 3, Cancelled()),
        (3, False, 3, Cancelled()),                            # off wins over out-of-attempts
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


def case_outcome_table():
    rows = [
        ("ok", None, ("ok", "done")),
        ("ok", "ok", ("ok", "done")),                          # blocked some, let some through
        ("ok", "skipped", ("skipped", "done")),                # blocked all
        ("words_blocked", None, ("ok", "done")),               # never retried
        ("words_blocked", "skipped", ("skipped", "done")),
        ("cancelled", None, ("error", JOB_RETRY)),
        ("exception", None, ("error", JOB_RETRY)),
        ("unknown_kind", None, ("error", "error")),            # consumed, no retry
    ]
    for kind, guard, want in rows:
        got = outcome(kind, guard, "boom")
        assert got == (*want, "boom"), (kind, guard, got, want)
    assert outcome("ok", None) == ("ok", "done", None)
    try:
        outcome("nope", None)  # type: ignore[arg-type]
    except AssertionError:
        pass
    else:
        raise AssertionError("an unknown outcome kind must raise")


def case_send_once_outcome_table():
    took = f"{MAY_HAVE_SENT}: OnlyFans took the send, then the run failed; not resent (boom)"
    unanswered = f"{MAY_HAVE_SENT}: the OnlyFans send got no answer; not resent (boom)"
    retry = ("error", JOB_RETRY, "boom")
    rows = [
        # (once, wrote, (run status, job status, error text)) for cancelled and exception alike
        (False, "none", retry),
        (False, "unanswered", retry),        # a sweep re-reads who is owed: requeue
        (False, "accepted", retry),
        (True, "none", retry),               # no write OF may have taken: retry as today
        (True, "unanswered", ("error", "error", unanswered)),   # read timeout / 5xx / cancel
        (True, "accepted", ("error", "error", took)),           # sent, then a later step failed
    ]
    for kind in ("cancelled", "exception"):
        for once, wrote, want in rows:
            got = outcome(kind, None, "boom", once=once, wrote=wrote)
            assert got == want, (kind, once, wrote, got, want)
    for kind in ("ok", "words_blocked"):       # a finished run never parks
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
