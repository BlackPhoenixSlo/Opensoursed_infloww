#!/usr/bin/env python3
"""
vault_collect_plan.CollectPlan — the manual Collect's page order, pure.

  case_round_interleave           folders 1-10 whole → 5 desc → 1 asc → folders 11-20 → …
  case_folder_paged_whole         a folder's pages run offset 0,100,… until !hasMore / empty
  case_crossing_ends_the_walk     desc meets asc (either way round) → walked, no more All pages
  case_shift_is_a_gap             an item removed before a cursor (the overlap id lost) → ended, not walked (F3)
  case_end_of_all_ends_the_walk   a cursor's empty page or hasMore false → walked
  case_folders_after_all_walked   All walked early: the remaining folders still page
  case_backstop_caps              desc+asc stop at max_pages; unwalked → capped; folders still page;
                                  a folder stops at max_pages too
  case_skip_folder                a failed folder is dropped, the walk goes on
  case_next_is_idempotent         asking twice names the same page
  case_no_folders                 no folders: All alone, terminates

Run: ./venv/bin/python service/tests/test_vault_collect_plan.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from vault_collect_plan import CollectPlan, Step  # noqa: E402


def drive(plan: CollectPlan, n: int, folders: dict[int, list[int]] | None = None,
          sticky: bool = False, limit: int = 10_000) -> list[Step]:
    """Run `plan` against a vault of ids 1..n (newer = higher) with `folders`
    {id: members}; `sticky` = OF always says hasMore (a stuck cursor)."""
    folders = folders or {}
    steps: list[Step] = []
    while (st := plan.next()) is not None:
        steps.append(st)
        assert len(steps) < limit, "plan never ended"
        if st.kind == "folder":
            ids = sorted(folders.get(st.list_id, []), reverse=True)
        else:
            ids = list(range(n, 0, -1)) if st.kind == "desc" else list(range(1, n + 1))
        page = ids[st.offset:st.offset + plan.page]
        plan.feed(st, page, sticky or st.offset + plan.page < len(ids))
    return steps


def short(steps: list[Step]) -> list[tuple]:
    return [(s.kind[0], s.list_id if s.kind == "folder" else s.offset) for s in steps]


S = 99   # an All cursor's step: page - 1, consecutive pages share one id (the continuity check)


def offs(a: int, b: int) -> list[int]:
    """All-cursor offsets of pages a..b-1."""
    return [i * S for i in range(a, b)]


def case_round_interleave():
    fids = list(range(101, 113))                      # 12 one-page folders
    plan = CollectPlan(fids, max_pages=200)
    got = short(drive(plan, 2000, {f: [1] for f in fids}))
    want = ([("f", f) for f in fids[:10]] + [("d", o) for o in offs(0, 5)] + [("a", 0)]
            + [("f", f) for f in fids[10:]] + [("d", o) for o in offs(5, 10)] + [("a", S)]
            + [("d", o) for o in offs(10, 15)] + [("a", 2 * S)]
            # round 4: desc page 18 holds what asc page 2 took → met, walk ends
            + [("d", o) for o in offs(15, 18)])
    assert got == want, got
    assert plan.walked and not plan.capped, (plan.walked, plan.capped)


def case_folder_paged_whole():
    plan = CollectPlan([7], max_pages=200)
    steps = drive(plan, 50, {7: list(range(1, 251))})
    assert [s.offset for s in steps if s.kind == "folder"] == [0, 100, 200], steps
    plan = CollectPlan([7], max_pages=200)            # an exact multiple ends on the empty page
    steps = drive(plan, 50, {7: list(range(1, 201))})
    assert [s.offset for s in steps if s.kind == "folder"] == [0, 100], steps


def case_crossing_ends_the_walk():
    # 650 items: desc pages 0-4 = ids 650..155, asc 0 = 1..100; desc page 5 = 155..56 holds asc's → met.
    plan = CollectPlan([], max_pages=200)
    steps = drive(plan, 650)
    assert short(steps) == [("d", o) for o in offs(0, 5)] + [("a", 0), ("d", 5 * S)], short(steps)
    assert plan.walked and plan.all_pages == 7
    # asc meets desc: 560 items, sticky hasMore so only crossing can end it.
    plan = CollectPlan([], max_pages=200, top=1, bottom=1)
    steps = drive(plan, 560, sticky=True)
    # d0 560..461, a0 1..100, d99 461..362, a99 100..199, d198 362..263,
    # a198 199..298 holds desc's 263..298 → met.
    assert short(steps) == [("d", 0), ("a", 0), ("d", S), ("a", S), ("d", 2 * S), ("a", 2 * S)], short(steps)
    assert plan.walked


def case_shift_is_a_gap():
    """Two items removed before the desc cursor after its first page: the next page (offset 99) starts at 1099,
    no longer holding id 1101 (the overlap), and 1100 is unseen — the walk ends (cursors meet) but is not walked.
    (One removal is still covered by the overlap, but reads as a gap too: conservative.)"""
    plan = CollectPlan([], max_pages=200)
    live, seen = list(range(1, 1201)), set()
    while (st := plan.next()) is not None:
        ordered = live[::-1] if st.kind == "desc" else live
        page = ordered[st.offset:st.offset + plan.page]
        seen |= set(page)
        plan.feed(st, page, st.offset + plan.page < len(live))
        if plan.all_pages == 1:
            live.remove(1200)
            live.remove(1199)
    assert plan.ended and plan.gap and not plan.walked and not plan.capped, (plan.ended, plan.gap)
    assert 1100 not in seen
    # an upload at the head only repeats ids (desc shifts right): still walked
    plan = CollectPlan([], max_pages=200)
    live = list(range(1, 1201))
    while (st := plan.next()) is not None:
        ordered = live[::-1] if st.kind == "desc" else live
        page = ordered[st.offset:st.offset + plan.page]
        plan.feed(st, page, st.offset + plan.page < len(live))
        if plan.all_pages == 1:
            live.append(5000)
    assert plan.walked and not plan.gap


def case_end_of_all_ends_the_walk():
    plan = CollectPlan([], max_pages=200)
    assert short(drive(plan, 250)) == [("d", o) for o in offs(0, 3)]       # hasMore false
    plan = CollectPlan([], max_pages=200)
    assert short(drive(plan, 0)) == [("d", 0)]                             # empty
    assert plan.walked and not plan.capped


def case_folders_after_all_walked():
    fids = list(range(1, 26))
    plan = CollectPlan(fids, max_pages=200)
    steps = short(drive(plan, 120, {f: [f] for f in fids}))
    assert steps == ([("f", f) for f in fids[:10]] + [("d", 0), ("d", S)]
                     + [("f", f) for f in fids[10:20]] + [("f", f) for f in fids[20:]]), steps


def case_backstop_caps():
    plan = CollectPlan([1, 2], max_pages=3)
    steps = drive(plan, 10_000, {1: [1], 2: list(range(1, 1001))}, sticky=True)
    assert [s for s in short(steps) if s[0] != "f"] == [("d", o) for o in offs(0, 3)], steps
    assert plan.capped and not plan.walked
    assert [s.offset for s in steps if s.list_id == 2] == [0, 100, 200], "folder not capped"
    plan = CollectPlan([], max_pages=3)
    drive(plan, 298)                                   # walked on exactly the last page: not capped
    assert plan.walked and not plan.capped


def case_skip_folder():
    plan = CollectPlan([1, 2], max_pages=200)
    st = plan.next()
    assert st == Step("folder", 0, 1)
    plan.skip_folder()
    assert plan.next() == Step("folder", 0, 2)


def case_next_is_idempotent():
    plan = CollectPlan([5], max_pages=200)
    assert plan.next() == plan.next() == Step("folder", 0, 5)
    plan.feed(Step("folder", 0, 5), [1], False)
    assert plan.next() == plan.next() == Step("desc", 0)


def case_no_folders():
    plan = CollectPlan([], max_pages=200)
    steps = drive(plan, 1000)
    # desc pages 0-4 (1000..505), a0 (1..100), desc pages 5-9: page 9 (110..11) meets asc → 11 pages.
    assert short(steps) == [("d", o) for o in offs(0, 5)] + [("a", 0)] + [
        ("d", o) for o in offs(5, 10)] and plan.walked, short(steps)
    try:
        CollectPlan([], max_pages=1, top=0, bottom=0)
    except ValueError:
        pass
    else:
        raise AssertionError("top=bottom=0 accepted")


_harness.run()
