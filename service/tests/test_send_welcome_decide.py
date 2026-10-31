#!/usr/bin/env python3
"""
send_welcome_decide.partition + send_welcome._hold_segments — table tests over
send_welcome's two pure halves. No DB, no OF, no clock: every row is data in,
decision out.

  case_partition_reason_table:   one row per reason, first match wins.
  case_precedence_table:         a fan who hits several filters gets the first.
  case_welcomed_never_welcome:   a `welcome_sent` fan is never Welcome, whatever
                                 else holds (test_fan, OF welcome, audience).
  case_established_never_welcome:  the NOT-NEW gate on the notification path.
  case_of_welcome_on:            OF's own welcome on -> Welcome(by_of=True), which
                                 _welcome_one routes to the claim + follow-ups path
                                 (test_send_welcome's after_of_welcome cases drive it);
                                 off / unreadable -> ours.
  case_test_fan_bypasses_feed_filters:  only welcomed + audience apply to it.
  case_order_and_counts:         feed order kept; welcomes/skip_counts helpers.
  case_hold_segments_table:      gif vs text, typing on/off, paced/unpaced,
                                 interruptible split; segments sum to the hold.
  case_hold_segments_clamped_pace:  absurd quiet overrides are clamped by the
                                 sampler and the split still sums to total_s.

Run: ./venv/bin/python service/tests/test_send_welcome_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from collections import Counter  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from random import Random  # noqa: E402

from automations import send_welcome as sw  # noqa: E402
from automations import send_welcome_decide as swd  # noqa: E402
from automations.pacing import Pace, welcome_burst_pace  # noqa: E402
import smart_message_extras as extras  # noqa: E402
from automations.send_welcome_decide import Reads, Skip, Welcome, partition  # noqa: E402

N = datetime(2026, 10, 30, 12, 0, 0)
A = "acct-1"


def m(mins: float) -> datetime:
    return N + timedelta(minutes=mins)


def sub(fid: int, at: datetime | None = None) -> dict:
    return {"id": fid, "username": f"u{fid}", "name": None, "at": at}


def one(s: dict, *, welcomed=(), established=(), of_on=None, payload=None,
        guard=(), restricted=(), audience=None):
    p = payload or {}
    reads = Reads(welcomed=set(welcomed), established=set(established), guard=set(guard),
                  restricted=set(restricted),
                  audience=None if audience is None else set(audience), of_welcome_on=of_on)
    [d] = partition([s], reads, account_id=A, now=N, test_fan=bool(p.get("test_fan")),
                    starts_at=extras.window_start(p), delay=extras.delay_range(p))
    return d


def verdict(d) -> str:
    return "welcome" if isinstance(d, Welcome) else d.reason


def case_partition_reason_table():
    rows = [
        ("fresh sub, no reads", dict(s=sub(1, m(-5))), "welcome"),
        ("unstamped sub", dict(s=sub(1)), "welcome"),
        ("already welcomed", dict(s=sub(1, m(-5)), welcomed={1}), "welcomed"),
        ("before Effective date", dict(s=sub(1, m(-90)),
                                       payload={"starts_at": m(-60).isoformat()}),
         "before_start"),
        ("after Effective date", dict(s=sub(1, m(-30)),
                                      payload={"starts_at": m(-60).isoformat()}),
         "welcome"),
        ("inside random delay", dict(s=sub(1, m(-1)), payload={"delay_range": [5, 10]}),
         "delayed"),
        ("past random delay", dict(s=sub(1, m(-11)), payload={"delay_range": [5, 10]}),
         "welcome"),
        ("future stamp, no delay (clock skew) waits", dict(s=sub(1, m(1))), "delayed"),
        ("established", dict(s=sub(1, m(-5)), established={1}), "established"),
        ("contact guard", dict(s=sub(1, m(-5)), guard={1}), "guard"),
        ("hard-skip restricted", dict(s=sub(1, m(-5)), restricted={1}), "restricted"),
        ("audience excludes", dict(s=sub(1, m(-5)), audience={2}), "audience"),
        ("audience includes", dict(s=sub(1, m(-5)), audience={1}), "welcome"),
        ("audience enforce, empty", dict(s=sub(1, m(-5)), audience=set()), "audience"),
        ("other fans' reads don't bite", dict(s=sub(1, m(-5)), welcomed={2},
                                              established={2}, guard={2},
                                              restricted={2}), "welcome"),
    ]
    bad = []
    for rid, kw, want in rows:
        got = verdict(one(kw.pop("s"), **kw))
        if got != want:
            bad.append(f"{rid}: {got} != {want}")
    assert not bad, "\n  " + "\n  ".join(bad)


def case_precedence_table():
    every = dict(welcomed={1}, established={1}, guard={1}, restricted={1}, audience=set())
    late = {"starts_at": m(-60).isoformat()}
    rows = [
        ("welcomed beats everything", sub(1, m(-90)), dict(every, payload=late), "welcomed"),
        ("before_start beats delay..audience", sub(1, m(-90)),
         dict(every, welcomed=(), payload={**late, "delay_range": [200, 300]}),
         "before_start"),
        ("delayed beats established..audience", sub(1, m(-1)),
         dict(every, welcomed=(), payload={"delay_range": [5, 10]}), "delayed"),
        ("established beats guard..audience", sub(1, m(-5)),
         dict(every, welcomed=()), "established"),
        ("guard beats restricted, audience", sub(1, m(-5)),
         dict(every, welcomed=(), established=()), "guard"),
        ("restricted beats audience", sub(1, m(-5)),
         dict(every, welcomed=(), established=(), guard=()), "restricted"),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, s, kw, want in rows
           if (got := verdict(one(s, **kw))) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def case_welcomed_never_welcome():
    for payload in ({}, {"test_fan": 1}, {"delay_range": [0, 0]}):
        for of_on in (None, False, True):
            for audience in (None, {1}):
                d = one(sub(1, m(-5)), welcomed={1}, of_on=of_on, payload=payload,
                        audience=audience)
                assert d == Skip(sub(1, m(-5)), "welcomed"), (payload, of_on, audience, d)


def case_established_never_welcome():
    for of_on in (None, False, True):
        for audience in (None, {1}):
            d = one(sub(1, m(-5)), established={1}, of_on=of_on, audience=audience)
            assert verdict(d) == "established", (of_on, audience, d)


def case_of_welcome_on():
    # OF's own welcome really on: he is still admitted (a new sub, a max_welcomes
    # slot, a lease), but the run only claims him + queues follow-ups.
    assert one(sub(1, m(-5)), of_on=True) == Welcome(sub(1, m(-5)), by_of=True)
    # Off, or unreadable (None): this rule's own welcome.
    assert one(sub(1, m(-5)), of_on=False) == Welcome(sub(1, m(-5)), by_of=False)
    assert one(sub(1, m(-5)), of_on=None) == Welcome(sub(1, m(-5)), by_of=False)
    # It never rescues a skipped fan.
    assert verdict(one(sub(1, m(-5)), of_on=True, established={1})) == "established"


def case_test_fan_bypasses_feed_filters():
    p = {"test_fan": 1, "starts_at": m(60).isoformat(), "delay_range": [50, 60]}
    s = sub(1, m(-1))
    assert verdict(one(s, payload=p, established={1}, guard={1}, restricted={1})) == "welcome"
    assert verdict(one(s, payload=p, audience={2})) == "audience"
    assert verdict(one(s, payload=p, welcomed={1})) == "welcomed"


def case_order_and_counts():
    subs = [sub(i, m(-5)) for i in range(1, 8)]
    ds = partition(subs, Reads(welcomed={2}, established={3}, guard={4}, restricted={5},
                               audience={1, 2, 3, 4, 5, 7}), account_id=A, now=N)
    assert [d.sub["id"] for d in ds] == list(range(1, 8))
    assert [w.sub["id"] for w in swd.welcomes(ds)] == [1, 7]
    got = swd.skip_counts(ds)
    assert got == Counter(welcomed=1, established=1, guard=1, restricted=1,
                          audience=1), got
    assert got["delayed"] == 0
    assert partition([], Reads(welcomed={1}, established={1}, of_welcome_on=True),
                     account_id=A, now=N) == []


def _shape(segs):
    return [(round(s.seconds, 6), s.indicator, round(s.quiet_s, 6), s.check_after)
            for s in segs]


def case_hold_segments_table():
    G = sw._GIF_HOLD_S
    quiet = Pace(total_s=20.0, quiet_s=12.0, think_at_s=2.0, think_for_s=1.0)
    noquiet = Pace(total_s=6.0)
    rows = [
        # (id, kwargs, [(seconds, indicator, quiet_s, check_after)])
        ("unpaced text, typing on", dict(pace=None, typing_s=4.0, is_gif=False,
                                         typing_on=True, interruptible=False),
         [(4.0, True, 0.0, False)]),
        ("unpaced text, typing off", dict(pace=None, typing_s=4.0, is_gif=False,
                                          typing_on=False, interruptible=True),
         [(4.0, False, 0.0, False)]),
        ("unpaced gif: flat beat, dark", dict(pace=None, typing_s=0.0, is_gif=True,
                                              typing_on=True, interruptible=False),
         [(G, False, 0.0, False)]),
        ("unpaced gif, checked after", dict(pace=None, typing_s=0.0, is_gif=True,
                                            typing_on=True, interruptible=True),
         [(G, False, 0.0, True)]),
        ("paced text, quiet, checked: split", dict(pace=quiet, typing_s=4.0, is_gif=False,
                                                   typing_on=True, interruptible=True),
         [(12.0, False, 0.0, True), (8.0, True, 0.0, False)]),
        ("paced text, quiet, unchecked: one", dict(pace=quiet, typing_s=4.0, is_gif=False,
                                                   typing_on=True, interruptible=False),
         [(20.0, True, 12.0, False)]),
        ("paced text, typing off", dict(pace=quiet, typing_s=4.0, is_gif=False,
                                        typing_on=False, interruptible=True),
         [(12.0, False, 0.0, True), (8.0, False, 0.0, False)]),
        ("paced text, no quiet: one", dict(pace=noquiet, typing_s=4.0, is_gif=False,
                                           typing_on=True, interruptible=True),
         [(6.0, True, 0.0, False)]),
        ("paced gif, checked", dict(pace=Pace(total_s=4.0, quiet_s=4.0), typing_s=0.0,
                                    is_gif=True, typing_on=True, interruptible=True),
         [(4.0, False, 4.0, True)]),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, kw, want in rows
           if (got := _shape(sw._hold_segments(**kw))) != want]
    assert not bad, "\n  " + "\n  ".join(bad)
    # The think phases ride the typing segment of a split.
    segs = sw._hold_segments(pace=quiet, typing_s=4.0, is_gif=False, typing_on=True,
                             interruptible=True)
    assert (segs[1].think_at_s, segs[1].think_for_s) == (2.0, 1.0)
    assert (segs[0].think_at_s, segs[0].think_for_s) == (0.0, 0.0)


def case_hold_segments_clamped_pace():
    # Malformed / absurd raw-JSON quiet bands: the sampler clamps, and the split
    # never adds time to the one number that moves a clock.
    for oq, gq in (([0, 10_000], [-5, 99_999]), (["x", None], "junk"), (None, None)):
        for role, text, has_image in (("opener", "Hey S-S-S-Sexy Sam ! !!", True),
                                      ("gap", "just woke up... it's Friday", False),
                                      ("tail", "what's yours?", False)):
            for seed in range(5):
                pace = welcome_burst_pace(role=role, has_image=has_image, typing_s=3.0,
                                          text=text, rng=Random(f"t:{seed}"),
                                          open_quiet=oq, gap_quiet=gq)
                assert 0 <= pace.quiet_s <= pace.total_s <= sw.INLINE_MAX_S, (role, oq, pace)
                for checked in (False, True):
                    segs = sw._hold_segments(pace=pace, typing_s=3.0, is_gif=False,
                                             typing_on=True, interruptible=checked)
                    assert abs(sum(s.seconds for s in segs) - pace.total_s) < 1e-9
                    assert all(s.seconds >= 0 for s in segs), segs


_harness.run()
