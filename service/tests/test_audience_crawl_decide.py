#!/usr/bin/env python3
"""
audience_crawl_decide — table tests over the pure rules of the Audience crawl
(docs/spec/phase-02-audience-crawl.md). No DB, no OF.

  case_ladder_table:        OF's ask wins when longer (uncapped); else first x 2^attempt,
                            capped at max; attempt 0 after a reset is the first rung again.
  case_asked_wait_table:    Retry-After header (seconds) first, else the body's
                            "allow N seconds" (of_pacing.allow_s), uncapped; neither: None.
  case_resume_offset_table: one page back, clamped at 0.
  case_refusal_table:       filters / online -> online (checked first); a list name other
                            than fans / following / a numeric id, or a non-numeric exclude
                            list -> unknown_list; else None.
  case_knobs_defaults_and_fallback: the spec's seven defaults + P2b's two (COMPLETE_MIN 0.95,
                            REPROBE_S 24 h); a malformed or non-positive value warns and falls
                            back; mode values.
  case_needs_table:         one request's include sources, the exclude lists it must read and
                            the verified ones it reuses (never read).
  case_needers_table:       a round's sources, each once, first seen, with the requests needing
                            each in round order.
  case_coalesced_table:     the other requests of the round sharing at least one read.
  case_audience_key_table:  comparable sends: include and exclude lists normalized, deduped,
                            sorted; no roster or explicit ids: None (comparable to nothing).
  case_lists_first_table:   every list (include or exclude) before the rosters, each in order.
  case_complete_table:      the gate on this send's own OF count: n / sent >= COMPLETE_MIN
                            recorded, under it incomplete; no count (or OF's 0): `no_count`, ratio
                            None, never recorded. (A roster's repeat end goes through the same gate:
                            test_audience_crawl_p2b case_roster_repeat_at_end.)
  case_skips_table:         skip after incomplete / deadline younger than REPROBE_S only.

Run: ./venv/bin/python service/tests/test_audience_crawl_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import logging  # noqa: E402

import audience_crawl_decide as acd  # noqa: E402

K = acd.Knobs()   # the defaults: first 30 s, cap 300 s


def _table(rows, fn) -> None:
    bad = []
    for rid, args, want in rows:
        got = fn(*args)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_ladder_table():
    _table([
        ("first rung", (0, None, K), 30.0),
        ("doubling", (1, None, K), 60.0),
        ("doubling again", (2, None, K), 120.0),
        ("cap", (4, None, K), 300.0),
        ("far past the cap", (20, None, K), 300.0),
        ("OF asks longer: the ask", (0, 120.0, K), 120.0),
        ("OF asks longer than the cap: uncapped", (5, 600.0, K), 600.0),
        ("OF asks shorter: the ladder", (1, 1.0, K), 60.0),
        ("after a reset: the first rung", (0, 2.0, K), 30.0),
        ("other knobs", (2, None, acd.Knobs(first_s=1.0, max_s=3.0)), 3.0),
    ], acd.next_wait)


def case_asked_wait_table():
    _table([
        ("header", ("120", None), 120.0),
        ("header wins over body", ("5", 1.0), 5.0),
        ("body", (None, 45.0), 45.0),
        ("body uncapped", (None, 600.0), 600.0),
        ("malformed header: body", ("soon", 3.0), 3.0),
        ("negative header: body", ("-1", 3.0), 3.0),
        ("nothing", (None, None), None),
    ], acd.asked_wait)


def case_resume_offset_table():
    _table([
        ("one page back", (150, 50), 100),
        ("first page failed", (0, 50), 0),
        ("clamped", (30, 50), 0),
        ("list page", (300, 100), 200),
    ], acd.resume_offset)


def case_refusal_table():
    _table([
        ("plain lists", (["fans", "following", "123"], None, False), None),
        ("no lists (explicit ids)", ([], None, False), None),
        ("online only", (["fans"], None, True), "online"),
        ("filters", (["fans"], {"online": 1}, False), "online"),
        ("online beats unknown", (["recent"], {"online": 1}, False), "online"),
        ("unknown list name", (["fans", "recent"], None, False), "unknown_list"),
        ("case and spaces", ([" FANS ", "Following"], None, False), None),
        ("numeric exclude lists", (["fans"], None, False, [50, "60", " 70 "]), None),
        ("named exclude list (Composer allows names)", (["fans"], None, False, [50, "VIP"]), "unknown_list"),
        ("named exclude list, explicit ids", ([], None, False, ["VIP"]), "unknown_list"),
        ("online beats a named exclude list", (["fans"], None, True, ["VIP"]), "online"),
    ], acd.refusal)


def case_knobs_defaults_and_fallback():
    k = acd.knobs({})
    assert k == acd.Knobs(mode="paced", deadline_s=900.0, first_s=30.0, max_s=300.0, page_tries=3,
                          max_pages=1000, roster_page=50, complete_min=1.0, complete_max=1.15,
                          reprobe_s=86400.0), k
    env = {"AUDIENCE_CRAWL_MODE": "legacy", "AUDIENCE_CRAWL_DEADLINE_S": "60",
           "AUDIENCE_CRAWL_429_FIRST_S": "0.5", "AUDIENCE_CRAWL_429_MAX_S": "4",
           "AUDIENCE_CRAWL_PAGE_TRIES": "5", "AUDIENCE_CRAWL_MAX_PAGES": "20",
           "AUDIENCE_CRAWL_ROSTER_PAGE": "100", "AUDIENCE_CRAWL_COMPLETE_MIN": "0.9",
           "AUDIENCE_CRAWL_COMPLETE_MAX": "1.3", "AUDIENCE_CRAWL_REPROBE_S": "3600"}
    assert acd.knobs(env) == acd.Knobs(mode="legacy", deadline_s=60.0, first_s=0.5, max_s=4.0, page_tries=5,
                                       max_pages=20, roster_page=100, complete_min=0.9, complete_max=1.3,
                                       reprobe_s=3600.0), acd.knobs(env)
    assert acd.knobs({"AUDIENCE_CRAWL_MODE": " PACED "}).mode == "paced"

    seen: list[str] = []

    class H(logging.Handler):
        def emit(self, rec):
            seen.append(rec.getMessage())
    h = H()
    logging.getLogger("of-relay.audience_crawl_decide").addHandler(h)
    try:
        bad = {"AUDIENCE_CRAWL_MODE": "fast", "AUDIENCE_CRAWL_DEADLINE_S": "soon",
               "AUDIENCE_CRAWL_429_FIRST_S": "-1", "AUDIENCE_CRAWL_429_MAX_S": "0",
               "AUDIENCE_CRAWL_PAGE_TRIES": "2.5", "AUDIENCE_CRAWL_MAX_PAGES": "", "AUDIENCE_CRAWL_ROSTER_PAGE": "x",
               "AUDIENCE_CRAWL_COMPLETE_MIN": "0", "AUDIENCE_CRAWL_COMPLETE_MAX": "-1",
               "AUDIENCE_CRAWL_REPROBE_S": "daily"}
        assert acd.knobs(bad) == acd.Knobs(), acd.knobs(bad)
    finally:
        logging.getLogger("of-relay.audience_crawl_decide").removeHandler(h)
    # Every malformed value named once; an empty one is "unset", not malformed.
    named = {m.split("name=")[1].split()[0] for m in seen if "name=" in m}
    assert named == set(bad) - {"AUDIENCE_CRAWL_MAX_PAGES"}, (named, seen)


def case_needs_table():
    V = {50: frozenset({1, 2})}
    _table([
        ("rosters, one exclude list", (["fans", "following"], [77], {}),
         (("fans", "following"), (("list", 77),), ())),
        ("verified exclude reused, not read", (["fans"], [50, 77], V), (("fans",), (("list", 77),), (50,))),
        ("only verified", (["fans"], ["50"], V), (("fans",), (), (50,))),
        ("numeric include list, deduped", (["FANS", "123", "fans"], [77, 77], {}),
         (("fans", ("list", 123)), (("list", 77),), ())),
        ("verified id not excluded: ignored", (["fans"], [], V), (("fans",), (), ())),
        ("explicit ids only", ([], [], {}), ((), (), ())),
    ], acd.needs)


def case_needers_table():
    F, FO, L7, L9 = "fans", "following", ("list", 7), ("list", 9)
    _table([   # as (source, needers) pairs: the order is part of the rule
        ("one request", ({0: (F, FO, L7)},), [(F, [0]), (FO, [0]), (L7, [0])]),
        ("two share the rosters: read once", ({0: (F, FO, L7), 1: (F, FO, L9)},),
         [(F, [0, 1]), (FO, [0, 1]), (L7, [0]), (L9, [1])]),
        ("first seen order", ({0: (L9,), 1: (F, L9), 2: (FO,)},), [(L9, [0, 1]), (F, [1]), (FO, [2])]),
        ("include and exclude the same list: one needer", ({0: (L7, L7)},), [(L7, [0])]),
        ("nothing to read", ({0: (), 1: ()},), []),
    ], lambda need: list(acd.needers(need).items()))


def case_coalesced_table():
    by_src = acd.needers({0: ("fans", "following"), 1: ("fans", "following"), 2: (("list", 9),), 3: ()})
    _table([
        ("shares the rosters with one other", (0, by_src), 1),
        ("the same from the other side", (1, by_src), 1),
        ("its own list only", (2, by_src), 0),
        ("no reads", (3, by_src), 0),
        ("alone in its round", (0, {"fans": [0]}), 0),
        ("shares different sources with two", (0, {"fans": [0, 1], ("list", 9): [0, 2]}), 2),
    ], acd.coalesced)


def case_audience_key_table():
    FF = ("fans", "following")
    _table([
        ("normalized, deduped, sorted", (["Following", " fans ", "FANS"],), (FF, ())),
        ("an include list beside a roster", ([123, "fans"],), (("123", "fans"), ())),
        ("exclude lists are part of it", (["fans"], [77, "5", "77"]), (("fans",), ("5", "77"))),
        ("excluded ids are not (they ride on Auto_Exclude)", (["fans"], [], []), (("fans",), ())),
        ("explicit ids: none", (["fans"], [], [1]), None),
        ("a list-only audience: none", (["77"],), None),
        ("none", (None,), None),
        ("empty", ([],), None),
    ], acd.audience_key)


def case_lists_first_table():
    F, FO, L7, L9 = "fans", "following", ("list", 7), ("list", 9)
    _table([   # as (source, needers) pairs: the order is the rule
        ("a list moves ahead of the rosters", ({F: [0], FO: [0], L7: [0]},), [(L7, [0]), (F, [0]), (FO, [0])]),
        ("lists keep their order, rosters theirs", ({FO: [0], L9: [0], F: [1], L7: [1]},),
         [(L9, [0]), (L7, [1]), (FO, [0]), (F, [1])]),
        ("rosters only: unchanged", ({F: [0], FO: [1]},), [(F, [0]), (FO, [1])]),
        ("nothing", ({},), []),
    ], lambda by_src: list(acd.lists_first(by_src).items()))


def case_complete_table():
    _table([
        ("95/100: 5 % short is not complete (B1)", (95, 100, K), ("incomplete", 0.95)),
        ("just under OF's count", (999, 1000, K), ("incomplete", 0.999)),
        ("complete by OF's count", (1000, 1000, K), ("recorded", 1.0)),
        ("above (OF counts un-DMable members too)", (1074, 1000, K), ("recorded", 1.074)),
        ("at the upper guard", (1150, 1000, K), ("recorded", 1.15)),
        ("over it: OF's count is no measure (N1)", (1151, 1000, K), ("no_count", 1.151)),
        ("far below (a partial roster)", (4000, 40000, K), ("incomplete", 0.1)),
        ("empty set vs a count", (0, 10, K), ("incomplete", 0.0)),
        ("no count: never recorded", (5, None, K), ("no_count", None)),
        ("OF's 0 (in flight or failed): no count", (5, 0, K), ("no_count", None)),
        ("other knobs", (94, 100, acd.Knobs(complete_min=0.9)), ("recorded", 0.94)),
        ("other knobs, upper", (13, 10, acd.Knobs(complete_max=1.2)), ("no_count", 1.3)),
    ], acd.complete)


def case_skips_table():
    day = 86400.0
    _table([
        ("after incomplete, inside", ("incomplete", 3600.0, K), True),
        ("after deadline, inside", ("deadline", 0.0, K), True),
        ("at the re-probe age: crawl", ("incomplete", day, K), False),
        ("past it: crawl", ("deadline", day + 1, K), False),
        ("after recorded", ("recorded", 1.0, K), False),
        ("after truncated (a list, MAX_PAGES)", ("truncated", 1.0, K), False),
        ("after error / dead_session", ("error", 1.0, K), False),
        ("after no_count (no verdict)", ("no_count", 1.0, K), False),
        ("no verdict", (None, None, K), False),
        ("no age", ("incomplete", None, K), False),
        ("other knob", ("incomplete", 700.0, acd.Knobs(reprobe_s=600.0)), False),
    ], acd.skips)


_harness.run()
