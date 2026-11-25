#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from vault_collect_plan import CollectPlan, Step  # noqa: E402


def drive(plan: CollectPlan, n: int, folders: dict[int, list[int]] | None = None,
          sticky: bool = False, limit: int = 10_000) -> list[Step]:
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


S = 99


def offs(a: int, b: int) -> list[int]:
    return [i * S for i in range(a, b)]


def case_round_interleave():
    fids = list(range(101, 113))
    plan = CollectPlan(fids, max_pages=200)
    got = short(drive(plan, 2000, {f: [1] for f in fids}))
    want = ([("f", f) for f in fids[:10]] + [("d", o) for o in offs(0, 5)] + [("a", 0)]
            + [("f", f) for f in fids[10:]] + [("d", o) for o in offs(5, 10)] + [("a", S)]
            + [("d", o) for o in offs(10, 15)] + [("a", 2 * S)]
            + [("d", o) for o in offs(15, 18)])
    assert got == want, got
    assert plan.walked and not plan.capped, (plan.walked, plan.capped)


def case_folder_paged_whole():
    plan = CollectPlan([7], max_pages=200)
    steps = drive(plan, 50, {7: list(range(1, 251))})
    assert [s.offset for s in steps if s.kind == "folder"] == [0, 100, 200], steps
    plan = CollectPlan([7], max_pages=200)
    steps = drive(plan, 50, {7: list(range(1, 201))})
    assert [s.offset for s in steps if s.kind == "folder"] == [0, 100], steps


def case_crossing_ends_the_walk():
    plan = CollectPlan([], max_pages=200)
    steps = drive(plan, 650)
    assert short(steps) == [("d", o) for o in offs(0, 5)] + [("a", 0), ("d", 5 * S)], short(steps)
    assert plan.walked and plan.all_pages == 7
    plan = CollectPlan([], max_pages=200, top=1, bottom=1)
    steps = drive(plan, 560, sticky=True)
    assert short(steps) == [("d", 0), ("a", 0), ("d", S), ("a", S), ("d", 2 * S), ("a", 2 * S)], short(steps)
    assert plan.walked


def case_shift_is_a_gap():
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
    assert short(drive(plan, 250)) == [("d", o) for o in offs(0, 3)]
    plan = CollectPlan([], max_pages=200)
    assert short(drive(plan, 0)) == [("d", 0)]
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
    drive(plan, 298)
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
    assert short(steps) == [("d", o) for o in offs(0, 5)] + [("a", 0)] + [
        ("d", o) for o in offs(5, 10)] and plan.walked, short(steps)
    try:
        CollectPlan([], max_pages=1, top=0, bottom=0)
    except ValueError:
        pass
    else:
        raise AssertionError("top=bottom=0 accepted")


_harness.run()
