#!/usr/bin/env python3
"""
s4s_decide — table tests over the pure S4S request rules (s4s_common), the
send-body parse, and the post routes' path-id lookup over HTTP:

  case_send_body_refusals:   `slot_at` missing, not a string or malformed →
                             400 with today's texts.
  case_own_post_404:         edit, delete and Primary on an S4S post by path
                             id: own found; not an id, missing, another
                             Creator's → 404 "post not found".
  case_partner_refusal:      self → 400, a block → 404, self first.
  case_request_refusal:      51st send, opted out, no Primary post, past time,
                             open pair, either Daily limit full → 409; OK; and
                             the precedence when several apply.
  case_next_status:          every (status × verb × box held) cell: the new
                             status, 404 (not the verb's party) or 409; an
                             unknown verb is a KeyError.

Run: ./venv/bin/python service/tests/test_s4s_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB)

_harness.bootstrap()

import re  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
from db.models import S4SRequest  # noqa: E402
from s4s_common import next_status, partner_refusal, request_refusal  # noqa: E402
from s4s_requests_api import _parse_send  # noqa: E402

IDS = fx.seed_two_agencies()
NOW = datetime(2026, 10, 31, 12)
LATER = datetime(2026, 11, 2, 6)


def case_send_body_refusals():
    base = {"from_account_id": "1000001", "to_profile_id": 7}
    rows = [
        (None, "slot_at: an ISO-8601 UTC time is required"),
        ("", "slot_at: an ISO-8601 UTC time is required"),
        (123, "slot_at: an ISO-8601 UTC time is required"),
        ("not a time", "slot_at: not an ISO-8601 time"),
        ("2026-11-02T06:00:00", "slot_at: the time needs a zone (end it with Z)"),
    ]
    for raw, detail in rows:
        try:
            _parse_send({**base, "slot_at": raw})
        except HTTPException as exc:
            assert (exc.status_code, exc.detail) == (400, detail), (raw, exc.detail)
        else:
            raise AssertionError(f"no 400 for {raw!r}")
    assert _parse_send({**base, "slot_at": "2026-11-02T08:00:00+02:00"}) == ("1000001", 7, LATER)


def case_own_post_404():
    a, b = IDS["creator_a"], IDS["creator_b"]
    owner_a, owner_b = fx.login_owner("agency_a_owner"), fx.login_owner("agency_b_owner")

    def post(client, aid):
        r = client.post(f"/admin/s4s/profiles/{aid}/posts", json={"caption": f"promo {aid}"})
        assert r.status_code == 200, (r.status_code, r.text)
        return r.json()["id"]

    own, other = post(owner_a, a), post(owner_b, b)
    p = f"/admin/s4s/profiles/{a}/posts"
    routes = (
        ("PATCH", lambda raw: owner_a.patch(f"{p}/{raw}", json={"caption": "edited"})),
        ("primary", lambda raw: owner_a.post(f"{p}/{raw}/primary")),
        ("DELETE", lambda raw: owner_a.delete(f"{p}/{raw}")),
    )
    for label, call in routes:  # not an id, missing, another Creator's
        for raw in ("abc", str(other + 1000), str(other)):
            r = call(raw)
            assert (r.status_code, r.json()) == (404, {"detail": "post not found"}), (label, raw, r.text)
    for label, call in routes:  # own: found (DELETE last)
        r = call(str(own))
        assert r.status_code == 200, (label, r.status_code, r.text)


def case_partner_refusal():
    self_400 = (400, "a Creator cannot send an S4S request to itself")
    rows = [  # (from, partner, blocked) → refusal
        ("A", "A", False, self_400),
        ("A", "A", True, self_400),               # self before block
        ("A", "B", True, (404, "partner not found")),
        ("A", "B", False, None),
    ]
    for from_id, to_id, blocked, want in rows:
        assert partner_refusal(from_id, to_id, blocked) == want, (from_id, to_id, blocked)


def case_request_refusal():
    def p(opted_in=True, daily_limit=2):
        return SimpleNamespace(opted_in=opted_in, daily_limit=daily_limit)

    ok = dict(from_p=p(), to_p=p(), sent_today=0, primaries=True, slot_at=LATER, now=NOW,
              open_pair=False, booked_from=0, booked_to=0)
    sent_409 = (409, "a Creator sends at most 50 S4S requests a day (UTC)")
    opt_409 = (409, "both Creators must be opted in to Share for Share")
    primary_409 = (409, "both Creators need a Primary post")
    past_409 = (409, "the proposed time has passed")
    pair_409 = (409, "an open request to this partner already exists")
    full_409 = (409, "a Daily limit is full on that day")
    rows = [  # overrides of `ok` → refusal
        ({}, None),
        ({"sent_today": 49}, None),
        ({"sent_today": 50}, sent_409),
        ({"sent_today": 53}, sent_409),
        ({"from_p": None}, opt_409),
        ({"from_p": p(opted_in=False)}, opt_409),
        ({"to_p": p(opted_in=False)}, opt_409),
        ({"primaries": False}, primary_409),
        ({"slot_at": NOW}, past_409),
        ({"slot_at": datetime(2026, 10, 30)}, past_409),
        ({"open_pair": True}, pair_409),
        ({"booked_from": 1, "booked_to": 1}, None),
        ({"booked_from": 2}, full_409),
        ({"booked_to": 2}, full_409),
        ({"booked_to": 1, "to_p": p(daily_limit=1)}, full_409),
        # precedence: the earlier refusal wins
        ({"sent_today": 50, "from_p": None, "primaries": False}, sent_409),
        ({"to_p": p(opted_in=False), "primaries": False, "slot_at": NOW}, opt_409),
        ({"primaries": False, "slot_at": NOW, "open_pair": True}, primary_409),
        ({"slot_at": NOW, "open_pair": True, "booked_from": 9, "booked_to": 9}, past_409),
        ({"open_pair": True, "booked_from": 9, "booked_to": 9}, pair_409),
    ]
    for over, want in rows:
        assert request_refusal(**{**ok, **over}) == want, (over, want)


# Every status an S4S request can hold (the model's CHECK, asserted below).
STATUSES = ("pending", "accepted", "declined", "skipped", "cancelled", "expired")
GONE = (409, "this request is no longer pending")
# (status, verb) → the new status or the refusal, for the verb's own party.
MOVES = {
    ("pending", "accept"): "accepted", ("pending", "skip"): "skipped",
    ("pending", "decline"): "declined", ("pending", "cancel"): "cancelled",
    ("skipped", "accept"): GONE, ("skipped", "skip"): GONE,
    ("skipped", "decline"): GONE, ("skipped", "cancel"): "cancelled",
    **{(st, v): GONE for st in ("accepted", "declined", "cancelled", "expired")
       for v in ("accept", "skip", "decline", "cancel")},
}
# The box a verb's party holds the request in.
PARTY = {"accept": "received", "skip": "received", "decline": "received", "cancel": "sent"}


def case_next_status():
    check = next(c for c in S4SRequest.__table__.constraints if c.name == "ck_s4s_requests_status")
    assert set(re.findall(r"'(\w+)'", str(check.sqltext))) == set(STATUSES), check.sqltext
    assert len(MOVES) == len(STATUSES) * len(PARTY)
    for status in STATUSES:
        for verb in PARTY:
            for box in ("received", "sent", None):
                want = MOVES[(status, verb)] if box == PARTY[verb] else (404, "request not found")
                got = next_status(status, verb, box)
                assert got == want, (status, verb, box, got)
    for verb in PARTY:  # a missing row holds no box
        assert next_status(None, verb, None) == (404, "request not found")
    try:
        next_status("pending", "approve", "received")
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown verb moved a request")


_harness.run()
