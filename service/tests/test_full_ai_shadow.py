#!/usr/bin/env python3
"""test_full_ai_shadow — Full AI Chat in Shadow mode, through the inbound path.

`webhook_dispatch.on_inbound_message(account, fan, message_id)` then
`automation_executor.run_once(account, "full_ai_chat")` on the _harness temp
DB, Jev faked at `_router_jev._client` (`FakeJev`), `TYPESAFE_API_KEY` a fake
value (shared fixtures: `_full_ai_fixtures`). Assertions are on DB rows, run
summaries, the Jev request and log lines. The Route table on this path is
test_full_ai_routes.py.

  case_rule_off_no_job                    rule off: no `full_ai_chat` job
  case_rule_on_gate_off_one_job           one job {only_fan_ids, anchor, _rule_id}
  case_rule_on_gate_on_w7_unchanged       W7's own job as with the rule off, plus ours
  case_kill_switch_no_job                 W7_WEBHOOK_DISPATCH_DISABLED: no job
  case_hook_failure_keeps_w7              `full_ai_hook_failed`, W7's job still queued
  case_dispatch_failure_still_runs_hook   W7's dispatch raises: `w7_dispatch_failed`,
                                          the hook still runs once and queues its job
  case_dispatch_then_hook_in_order        dispatch, hook, then the deferred backfill
  case_pending_job_wake_only              a pending job names the Fan: wake only
  case_late_older_dm_own_job              a DM older than the pending job's anchor,
                                          her outbound between: its own job, two rows
  case_unanchored_pending_job_no_fold     a pending job with no anchor: the DM still
                                          gets its own job
  case_one_run_one_row                    one run_once: one Decision row, its stats,
                                          its log line and the one Jev request
  case_lane_reply_between_two_turns       A, another Lane's outbound, B: one job, two
                                          rows, each reading only up to its Anchor
  case_burst_one_row                      three DMs, one run: one row at the third
  case_dm_after_decision_new_turn         a later DM: a second row, the first untouched
  case_lane_reply_after_anchor_unread     an outbound after the Anchor is not read
  case_rerun_decided_anchor_duplicate_turn  no row, no Jev call, `duplicate_turn`
  case_race_lost_counts_duplicate         a Turn a racing job wrote: a duplicate
  case_crash_retry_redoes_only_undecided  the write crashes on Turn 2 of 3: error run,
                                          one row; the retry asks Jev twice, the first
                                          row kept
  case_anchor_missing                     no row, the summary says `anchor_missing`
  case_rule_off_drops_queued_job          rule Off with a job queued: dropped at claim
  case_same_fan_two_creators              one row per Creator, each its own chat
  case_unanchored_is_a_noop               empty payload, interval job: ok, `unanchored`
  case_photo_dm_reads_media_only          `on_inbound_image` photo DM: one row, his Turn
                                          `[sent a photo or video]`
  case_giphy_dm_reads_gif_only            `on_inbound_image` Giphy DM: one row, `[sent a GIF]`
  case_state_shape                        exactly the probe's state: 12 lines with `when`
                                          and `ppv`, her last line, last purchase and
                                          Pending offer, read at or before the Anchor
  case_cut_runs                           the Turn cut over plain rows: no outbound,
                                          a split, a trailing outbound, a starting cut
  case_build_state_plain_rows_match_db    `build_state` on SimpleNamespace rows equals
                                          the DB path's state for the same thread
  case_pending_offer                      a funnel's, a human's and an old priced unbought
                                          outbound read as the Pending offer
  case_pending_offer_none                 bought, purchased or unsent: "none"
  case_last_purchase                      the probe's wording within 7 days; past them,
                                          after the Anchor or none: "none in the last 7 days"
  case_no_send_a_import_scan              the shadow modules name no send path
  case_no_send_b_raising_patches          OF client, wire call, lease, cooldown raise:
                                          still two rows (hook wake-only path and a
                                          two-Turn catch-up) and an ok run, no hit,
                                          no other table moves
  case_no_send_c_mutant_is_caught         a runner calling `_make_client` fails (a) and (b)
  case_no_send_c_swallowed_call_is_caught a `_make_client` call inside `_router_jev.ask`'s
                                          try (its error swallowed) is still a hit,
                                          one per Turn

Run: ./venv/bin/python service/tests/test_full_ai_shadow.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import ast  # noqa: E402
import contextlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select, text  # noqa: E402

import automation_executor as ax  # noqa: E402
import automation_registry  # noqa: E402
import fan_lease  # noqa: E402
import of_client  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from _full_ai_fixtures import (  # noqa: E402
    KIND, NOULS, QUIET, T0, FakeJev, _dm, _fake_jev, _msg, _rows, _run, _run_row, _seed,
)
from automation_executor import run_once  # noqa: E402
from automations import _jev  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_chat as runner  # noqa: E402
from automations import full_ai_decide  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, AutomationRule, Message, ScheduledJob, Transaction  # noqa: E402


@contextlib.contextmanager
def _logs(name: str):
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
    h, lg = H(), logging.getLogger(name)
    old = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


async def _jobs(aid: str, kind: str | None = None) -> list[ScheduledJob]:
    async with get_session() as s:
        q = select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.status == "pending")
        if kind is not None:
            q = q.where(ScheduledJob.kind == kind)
        return list((await s.execute(q.order_by(ScheduledJob.id))).scalars().all())


def _w7(jobs: list[ScheduledJob]) -> list[tuple[str, dict]]:
    """W7's own jobs, minus the per-account rule id they carry."""
    out = []
    for j in jobs:
        if j.kind == KIND:
            continue
        p = json.loads(j.payload_json)
        p.pop("_rule_id", None)
        out.append((j.kind, p))
    return out


# ── The hook ──────────────────────────────────────────────────────────

async def case_rule_off_no_job():
    for aid, gate in (("fa_off_g0", False), ("fa_off_g1", True)):
        await _seed(aid, rule=False, gate=gate)
        await _msg(aid, 11, 1, "in", "hey", T0)
        await wd.on_inbound_message(aid, 11, 1)
        assert await _jobs(aid, KIND) == [], aid


async def case_rule_on_gate_off_one_job():
    aid, fan = "fa_on_g0", 12
    rid = await _seed(aid, rule=True, gate=False)
    await _msg(aid, fan, 501, "in", "hey you", T0)
    await wd.on_inbound_message(aid, fan, 501)
    jobs = await _jobs(aid)
    assert [j.kind for j in jobs] == [KIND], [(j.kind, j.payload_json) for j in jobs]
    assert json.loads(jobs[0].payload_json) == {"only_fan_ids": [fan], "anchor": 501, "_rule_id": rid}


async def case_rule_on_gate_on_w7_unchanged():
    fan = 13
    off, on = "fa_w7_ruleoff", "fa_w7_ruleon"
    await _seed(off, rule=False, gate=True)
    rid = await _seed(on, rule=True, gate=True)
    for aid in (off, on):
        await _msg(aid, fan, 601, "in", "hii", T0)
        await wd.on_inbound_message(aid, fan, 601)
    j_off, j_on = await _jobs(off), await _jobs(on)
    assert _w7(j_off) and _w7(j_on) == _w7(j_off), (_w7(j_off), _w7(j_on))
    ours = [j for j in j_on if j.kind == KIND]
    assert len(ours) == 1, [j.payload_json for j in ours]
    assert json.loads(ours[0].payload_json) == {"only_fan_ids": [fan], "anchor": 601, "_rule_id": rid}


async def case_kill_switch_no_job():
    aid, fan = "fa_kill", 14
    await _seed(aid, rule=True, gate=False)
    await _msg(aid, fan, 701, "in", "yo", T0)
    os.environ["W7_WEBHOOK_DISPATCH_DISABLED"] = "1"
    try:
        await wd.on_inbound_message(aid, fan, 701)
    finally:
        os.environ.pop("W7_WEBHOOK_DISPATCH_DISABLED", None)
    assert await _jobs(aid) == []


async def case_hook_failure_keeps_w7():
    aid, fan = "fa_hookfail", 15
    await _seed(aid, rule=True, gate=True)
    await _msg(aid, fan, 801, "in", "hello", T0)
    real = ax.enqueue_job

    async def _enqueue(account_id, kind, **kw):
        if kind == KIND:
            raise RuntimeError("queue down")
        return await real(account_id, kind, **kw)
    ax.enqueue_job = _enqueue  # type: ignore[assignment]
    try:
        with _logs("of-relay.webhook_dispatch") as lines:
            await wd.on_inbound_message(aid, fan, 801)
    finally:
        ax.enqueue_job = real  # type: ignore[assignment]
    jobs = await _jobs(aid)
    assert [j.kind for j in jobs] == ["welcome_chatter_for_info"], [j.kind for j in jobs]
    assert any(l.startswith(f"full_ai_hook_failed account={aid} fan={fan}") for l in lines), lines


@contextlib.contextmanager
def _patched(**names):
    """Module attributes of webhook_dispatch swapped for the block."""
    saved = {n: getattr(wd, n) for n in names}
    for n, v in names.items():
        setattr(wd, n, v)
    try:
        yield
    finally:
        for n, v in saved.items():
            setattr(wd, n, v)


async def case_dispatch_failure_still_runs_hook():
    """W7's dispatch raising does not mute Full AI: `w7_dispatch_failed`, the
    real hook still awaited once and its job queued, no history backfill (not
    deferred), and nothing escapes."""
    aid, fan = "fa_dispfail", 19
    await _seed(aid, rule=True, gate=True)
    await _msg(aid, fan, 851, "in", "hello", T0)
    real_hook, hooked, scraped = wd._full_ai_hook, [], []

    async def _boom(*_a):
        raise RuntimeError("w7 down")

    async def _hook(*a):
        hooked.append(a)
        await real_hook(*a)

    async def _scrape(*a):
        scraped.append(a)
    with _patched(_dispatch_inbound=_boom, _full_ai_hook=_hook, enqueue_fan_scrape=_scrape), \
            _logs("of-relay.webhook_dispatch") as lines:
        await wd.on_inbound_message(aid, fan, 851)     # raises nothing
    assert hooked == [(aid, fan, 851)], hooked
    assert scraped == [], scraped
    assert [j.kind for j in await _jobs(aid)] == [KIND], [j.kind for j in await _jobs(aid)]
    assert lines.count(f"w7_dispatch_failed account={aid} fan={fan}") == 1, lines


async def case_dispatch_then_hook_in_order():
    """The happy path: W7's dispatch, then the hook, then the deferred backfill."""
    calls: list[str] = []

    async def _dispatch(*_a):
        calls.append("dispatch")
        return True

    async def _hook(*_a):
        calls.append("hook")

    async def _scrape(*_a):
        calls.append("scrape")
    with _patched(_dispatch_inbound=_dispatch, _full_ai_hook=_hook, enqueue_fan_scrape=_scrape):
        await wd.on_inbound_message("fa_disporder", 20, 861)
    assert calls == ["dispatch", "hook", "scrape"], calls


async def case_pending_job_wake_only():
    """A pending job naming the Fan: a second DM enqueues nothing, only wakes."""
    aid, fan = "fa_dedup", 16
    rid = await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2001, "hey", T0)
    woke = {"n": 0}
    orig = ax.wake_supervisor
    ax.wake_supervisor = lambda: woke.__setitem__("n", woke["n"] + 1)  # type: ignore[assignment]
    try:
        await _dm(aid, fan, 2002, "you there?", T0 + timedelta(minutes=1))
    finally:
        ax.wake_supervisor = orig  # type: ignore[assignment]
    jobs = await _jobs(aid)
    assert [json.loads(j.payload_json) for j in jobs] == [
        {"only_fan_ids": [fan], "anchor": 2001, "_rule_id": rid}], [j.payload_json for j in jobs]
    assert woke["n"] == 1, woke


async def case_late_older_dm_own_job():
    """B lands late (WS replay) and older, behind a pending job anchored at A
    with her outbound between them: the job's walk starts after that outbound,
    so B gets its own job, and both Turns get a row."""
    aid, fan = "fa_late", 17
    await _seed(aid, rule=True, gate=False)
    await _msg(aid, fan, 2051, "out", "hey you", T0 + timedelta(minutes=5),
               automation_kind="reply_mass_funnel")
    await _dm(aid, fan, 2052, "hi", T0 + timedelta(minutes=10))
    await _dm(aid, fan, 2050, "you up?", T0 + timedelta(minutes=3))
    assert sorted(json.loads(j.payload_json)["anchor"] for j in await _jobs(aid, KIND)) == [2050, 2052]
    fake = FakeJev((QUIET, 1.0), (QUIET, 1.0))
    for _ in range(2):
        res, _stats = await _run(aid, fake)
        assert res["status"] == "ok", res
    assert len(fake.calls) == 2, fake.calls
    assert sorted(r.trigger_key for r in await _rows(aid)) == ["2050", "2052"]


async def case_unanchored_pending_job_no_fold():
    """A pending job naming the Fan with no anchor (keyed `only_fan_ids`,
    `fan_id` or `test_fan`) decides nothing, so a DM still gets its own job."""
    for i, key in enumerate(("only_fan_ids", "fan_id", "test_fan")):
        aid, fan = f"fa_unfold_{i}", 18
        rid = await _seed(aid, rule=True, gate=False)
        await ax.enqueue_job(aid, KIND, payload={key: [fan] if key == "only_fan_ids" else fan,
                                                 "_rule_id": rid})
        await _dm(aid, fan, 2061, "hey", T0)
        assert [json.loads(j.payload_json).get("anchor") for j in await _jobs(aid, KIND)] == [None, 2061], key


# ── One run, one row ──────────────────────────────────────────────────

LONG = "so i was thinking about what you said earlier " * 20       # > 600 chars: untruncated


async def _chat(aid: str, fan: int) -> tuple[list[dict], int, datetime]:
    """14 lines before his Turn (her last), then his Turn of two DMs.
    Returns the 12 thread lines Jev must read, the Anchor id and time."""
    lines = []
    for i in range(14):
        d = "out" if i % 2 else "in"
        body = f"<p>line {i} &amp; more</p>"
        await _msg(aid, fan, 1000 + i, d, body, T0 + timedelta(minutes=i))
        # Line i is 20 - i minutes before his Turn: under 10 reads "minutes before".
        lines.append({"from": "her" if d == "out" else "fan", "text": f"line {i} & more",
                      "when": "minutes before" if i >= 11 else "within the last two hours"})
    await _msg(aid, fan, 1100, "in", "hey are you there", T0 + timedelta(minutes=20))
    anchor_at = T0 + timedelta(minutes=21)
    await _msg(aid, fan, 1101, "in", LONG, anchor_at)
    return lines[-12:], 1101, anchor_at


async def case_one_run_one_row():
    aid, fan = "fa_tracer", 21
    await _seed(aid, rule=True, gate=False)
    thread, anchor, anchor_at = await _chat(aid, fan)
    await wd.on_inbound_message(aid, fan, anchor)
    fake = FakeJev(({**QUIET, "gif_fits": .9}, 2.7))
    with _fake_jev(fake), _logs("of-relay.automation.full_ai_chat") as lines:
        res = await run_once(aid, KIND)
    assert res["status"] == "ok", res

    # The one Jev request: every Router question and the Score, on the pin.
    assert len(fake.calls) == 1, fake.calls
    call = fake.calls[0]
    assert call["model"] == "jev-1.14.0", call["model"]
    assert set(call["questions"]) == NOULS | {"intensity"}, sorted(call["questions"])
    assert type(call["questions"]["intensity"]).__name__ == "Score"
    assert all(type(call["questions"][q]).__name__ == "Noul" for q in NOULS)
    st = call["state"]
    assert st["fan_new_messages"] == ["hey are you there", LONG.strip()], st["fan_new_messages"]
    assert st["thread"] == thread, st["thread"]

    rows = await _rows(aid)
    assert len(rows) == 1, rows
    r = rows[0]
    got = {k: getattr(r, k) for k in (
        "fan_id", "mode", "trigger_kind", "trigger_key", "anchor_message_id", "anchor_created_at",
        "route", "route_row", "heat", "status", "question_version", "router_model",
        "writer_model", "jev_error", "arm", "salt_ver")}
    assert got == {
        "fan_id": fan, "mode": "shadow", "trigger_kind": "inbound", "trigger_key": str(anchor),
        "anchor_message_id": anchor, "anchor_created_at": anchor_at, "route": "chat",
        "route_row": "otherwise", "heat": 4, "status": "planned",      # 2.7 -> level 3, + 1
        "question_version": rj.QUESTION_VERSION, "router_model": "jev-1.14.0",
        "writer_model": None, "jev_error": None,
        "arm": full_ai_decide.arm_of(aid, fan), "salt_ver": 1}, got
    assert isinstance(r.jev_ms, int) and r.jev_ms >= 20, r.jev_ms
    jj = json.loads(r.jev_json)
    assert jj["answers"] == {**QUIET, "gif_fits": .9}, jj["answers"]
    assert jj["intensity"] == {"score": 2.7, "p": {"0": .05, "1": .1, "2": .2, "3": .6, "4": .05}}, jj
    assert jj["fired"] == ["gif_fits"], jj["fired"]
    assert jj["state"] == st, (jj["state"], st)

    stats = json.loads((await _run_row(res["run_id"])).stats_json)
    assert {k: stats[k] for k in ("recorded", "duplicate", "rows")} == {
        "recorded": 1, "duplicate": 0,
        "rows": [{"row_id": r.id, "route": "chat", "jev_ms": r.jev_ms}]}, stats
    assert lines.count(f"full_ai_turn account={aid} fan={fan} route=chat row=otherwise "
                       f"jev_ms={r.jev_ms}") == 1, lines
    assert await _jobs(aid, KIND) == []


# ── Turn catch-up ─────────────────────────────────────────────────────

def _lines(st: dict) -> list[tuple[str, str]]:
    """The thread as (from, text): what each line says and who said it."""
    return [(l["from"], l["text"]) for l in st["thread"]]


async def case_lane_reply_between_two_turns():
    """Inbound A, another Lane's outbound, inbound B before the claim: one job,
    then one run writing two rows, A's then B's."""
    aid, fan = "fa_ab", 51
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2101, "are you real", T0)
    await _msg(aid, fan, 2102, "out", "hey babe, missed you", T0 + timedelta(minutes=1),
               automation_kind="reply_mass_funnel")
    await _dm(aid, fan, 2103, "show me more", T0 + timedelta(minutes=2))
    assert len(await _jobs(aid, KIND)) == 1, [j.payload_json for j in await _jobs(aid, KIND)]
    fake = FakeJev((QUIET, 1.0), (QUIET, 2.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert len(fake.calls) == 2, fake.calls
    a, b = (c["state"] for c in fake.calls)
    assert a["fan_new_messages"] == ["are you real"] and _lines(a) == [], a
    assert b["fan_new_messages"] == ["show me more"], b
    assert _lines(b) == [("fan", "are you real"), ("her", "hey babe, missed you")], b
    rows = await _rows(aid)
    assert [r.trigger_key for r in rows] == ["2101", "2103"], [r.trigger_key for r in rows]
    assert [json.loads(r.jev_json)["state"] for r in rows] == [a, b]
    assert {k: stats[k] for k in ("recorded", "duplicate")} == {"recorded": 2, "duplicate": 0}, stats
    assert [x["row_id"] for x in stats["rows"]] == [r.id for r in rows], stats


async def case_burst_one_row():
    """A burst of three DMs, then one run: one row anchored at the third."""
    aid, fan = "fa_burst", 52
    await _seed(aid, rule=True, gate=False)
    for i, body in enumerate(("hey", "u up?", "miss u")):
        await _dm(aid, fan, 2201 + i, body, T0 + timedelta(seconds=10 * i))
    fake = FakeJev((QUIET, 1.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert len(fake.calls) == 1, fake.calls
    assert fake.calls[0]["state"]["fan_new_messages"] == ["hey", "u up?", "miss u"], fake.calls
    rows = await _rows(aid)
    assert [(r.trigger_key, r.anchor_message_id) for r in rows] == [("2203", 2203)], rows
    assert stats["recorded"] == 1, stats


def _cols(r: AiDecision) -> dict:
    return {c.name: getattr(r, c.key) for c in AiDecision.__table__.columns}


async def case_dm_after_decision_new_turn():
    """A DM after the decision, no outbound between: a second row anchored at it
    whose Turn holds the earlier DM too; the first row is never touched."""
    aid, fan = "fa_after", 53
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2301, "hi there", T0)
    await _run(aid, FakeJev((QUIET, 1.0)))
    (first,) = await _rows(aid)
    before = _cols(first)
    await _dm(aid, fan, 2302, "hello??", T0 + timedelta(minutes=5))
    assert [json.loads(j.payload_json)["anchor"] for j in await _jobs(aid, KIND)] == [2302]
    fake = FakeJev((QUIET, 2.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok" and stats["recorded"] == 1, (res, stats)
    assert fake.calls[0]["state"]["fan_new_messages"] == ["hi there", "hello??"], fake.calls
    rows = await _rows(aid)
    assert [r.trigger_key for r in rows] == ["2301", "2302"], rows
    assert _cols(rows[0]) == before, (_cols(rows[0]), before)


async def case_lane_reply_after_anchor_unread():
    """Another Lane's outbound after the Anchor, before the run: the row reads
    only up to its Anchor."""
    aid, fan = "fa_lateout", 54
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2401, "what are you doing", T0)
    await _msg(aid, fan, 2402, "out", "just got out of the shower", T0 + timedelta(minutes=1),
               automation_kind="welcome_chatter_for_info")
    fake = FakeJev((QUIET, 1.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok" and stats["recorded"] == 1, (res, stats)
    st = fake.calls[0]["state"]
    assert st["fan_new_messages"] == ["what are you doing"] and _lines(st) == [], st
    assert "shower" not in json.dumps(st), st
    assert [r.trigger_key for r in await _rows(aid)] == ["2401"]


async def case_rerun_decided_anchor_duplicate_turn():
    """A re-run on a decided Anchor (the DM re-delivered): no row, no Jev call."""
    aid, fan = "fa_rerun", 55
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2501, "hey", T0)
    await _run(aid, FakeJev((QUIET, 1.0)))
    await wd.on_inbound_message(aid, fan, 2501)
    assert len(await _jobs(aid, KIND)) == 1
    fake = FakeJev()
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert fake.calls == [], fake.calls
    assert stats.get("skipped") == "duplicate_turn", stats
    assert len(await _rows(aid)) == 1


async def case_race_lost_counts_duplicate():
    """A row lost to a racing job (it wrote the Turn while Jev was asked): no
    second row, counted as a duplicate."""
    aid, fan = "fa_race", 56
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2601, "hey", T0)

    class Racer(FakeJev):
        async def system_one(self, state, questions, model=None):
            async with get_session() as s:
                s.add(AiDecision(account_id=aid, fan_id=fan, mode="shadow", trigger_kind="inbound",
                                 trigger_key="2601", route="chat", heat=1, route_row="otherwise",
                                 question_version=rj.QUESTION_VERSION, status="planned"))
            return await super().system_one(state, questions, model)
    res, stats = await _run(aid, Racer((QUIET, 1.0)))
    assert res["status"] == "ok", res
    assert {k: stats[k] for k in ("recorded", "duplicate", "rows")} == {
        "recorded": 0, "duplicate": 1, "rows": []}, stats
    assert len(await _rows(aid)) == 1


async def case_crash_retry_redoes_only_undecided():
    """Three Turns in one job, the write step crashing on the second: an error
    run with one row; the retry asks Jev only for the two Turns still without a row."""
    aid, fan = "fa_retry", 60
    await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 3001, "one", T0)
    await _msg(aid, fan, 3002, "out", "hi", T0 + timedelta(minutes=1), automation_kind="reply_mass_funnel")
    await _dm(aid, fan, 3003, "two", T0 + timedelta(minutes=2))
    await _msg(aid, fan, 3004, "out", "yes?", T0 + timedelta(minutes=3), automation_kind="reply_mass_funnel")
    await _dm(aid, fan, 3005, "three", T0 + timedelta(minutes=4))
    (job,) = await _jobs(aid, KIND)
    real, writes = runner._record, {"n": 0}

    async def _crashing(*a, **k):
        writes["n"] += 1
        if writes["n"] == 2:
            raise RuntimeError("db down")
        return await real(*a, **k)
    runner._record = _crashing  # type: ignore[assignment]
    try:
        fake = FakeJev((QUIET, 1.0), (QUIET, 1.0), (QUIET, 1.0))
        res, _ = await _run(aid, fake)
    finally:
        runner._record = real  # type: ignore[assignment]
    assert res["status"] == "error", res
    assert len(fake.calls) == 2, fake.calls
    (first,) = await _rows(aid)
    before = _cols(first)
    async with get_session() as s:                      # the retry's backoff, elapsed
        j = await s.get(ScheduledJob, job.id)
        assert j.status == "pending", j.status
        j.run_at = datetime.utcnow() - timedelta(seconds=1)
    fake = FakeJev((QUIET, 2.0), (QUIET, 2.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok" and stats["recorded"] == 2, (res, stats)
    assert [c["state"]["fan_new_messages"] for c in fake.calls] == [["two"], ["three"]], fake.calls
    rows = await _rows(aid)
    assert [r.trigger_key for r in rows] == ["3001", "3003", "3005"], rows
    assert _cols(rows[0]) == before, (_cols(rows[0]), before)


async def case_anchor_missing():
    """An anchor not in `messages`: no row, no Jev call, the summary says why."""
    aid, fan = "fa_missing", 57
    rid = await _seed(aid, rule=True, gate=False)
    await ax.enqueue_job(aid, KIND, payload={"only_fan_ids": [fan], "anchor": 999999, "_rule_id": rid})
    fake = FakeJev()
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert (await _run_row(res["run_id"])).status == "ok"
    assert stats.get("skipped") == "anchor_missing", stats
    assert fake.calls == [] and await _rows(aid) == []


async def case_rule_off_drops_queued_job():
    """Rule switched Off with a job queued: the job is dropped at claim, no row."""
    aid, fan = "fa_dropoff", 58
    rid = await _seed(aid, rule=True, gate=False)
    await _dm(aid, fan, 2801, "hey", T0)
    (job,) = await _jobs(aid, KIND)
    async with get_session() as s:
        (await s.get(AutomationRule, rid)).is_enabled = False
    fake = FakeJev()
    with _fake_jev(fake):
        res = await run_once(aid, KIND)
    assert res["status"] == "skipped" and res["reason"] == "rule_disabled", res
    assert fake.calls == [] and await _rows(aid) == []
    async with get_session() as s:
        assert (await s.get(ScheduledJob, job.id)).status == "cancelled"


async def case_same_fan_two_creators():
    """The same Fan id on two enabled Creators: one row per Creator, each
    reading its own chat."""
    fan = 59
    for aid, body in (("fa_two_a", "hi from a"), ("fa_two_b", "hi from b")):
        await _seed(aid, rule=True, gate=False)
        await _dm(aid, fan, 2901, body, T0)
    for aid, body in (("fa_two_a", "hi from a"), ("fa_two_b", "hi from b")):
        assert len(await _jobs(aid, KIND)) == 1, aid
        fake = FakeJev((QUIET, 1.0))
        res, _ = await _run(aid, fake)
        assert res["status"] == "ok", res
        assert fake.calls[0]["state"]["fan_new_messages"] == [body], (aid, fake.calls)
        rows = await _rows(aid)
        assert [(r.fan_id, r.trigger_key) for r in rows] == [(fan, "2901")], (aid, rows)


async def case_unanchored_is_a_noop():
    """No anchor (an empty payload, and the rule's materialized interval job):
    no Jev call, no row, an ok run whose summary says `unanchored`."""
    aid = "fa_unanch"
    rid = await _seed(aid, rule=True, gate=False)
    fake = FakeJev()
    with _fake_jev(fake):
        empty = await run_once(aid, KIND, payload={})
        assert await ax._materialize_due_rules() >= 1
        (job,) = await _jobs(aid, KIND)
        assert (job.rule_id, json.loads(job.payload_json)) == (rid, {}), job.payload_json
        tick = await run_once(aid, KIND)
    for res in (empty, tick):
        run = await _run_row(res["run_id"])
        assert (res["status"], run.status) == ("ok", "ok"), (res, run.status)
        assert json.loads(run.stats_json).get("skipped") == "unanchored", run.stats_json
    assert tick["job_id"] == job.id, tick
    assert fake.calls == [] and await _rows(aid) == []


# ── What the Router reads ─────────────────────────────────────────────

async def _media_dm(aid: str, fan: int, mid: int, at: datetime, *, gif: bool) -> None:
    """His media DM lands with no body and reaches the hook through
    `on_inbound_image`'s hand-off: a photo (media, media count 1), or a Giphy
    DM (OF sends it with `media: []`, `mediaCount: 0` and a `giphyId`)."""
    frame = ({"id": mid, "text": "", "giphyId": "xT9IgG50Fb7Mi0prBC", "media": [], "mediaCount": 0}
             if gif else
             {"id": mid, "text": "", "media": [{"id": 77, "type": "photo"}], "mediaCount": 1})
    await _msg(aid, fan, mid, "in", "", at, media_count=0 if gif else 1, raw_json=json.dumps(frame))
    await wd.on_inbound_image(aid, fan, mid, has_media=not gif)


async def case_photo_dm_reads_media_only():
    aid, fan = "fa_photo", 61
    await _seed(aid, rule=True, gate=False)
    await _media_dm(aid, fan, 3101, T0, gif=False)
    fake = FakeJev((QUIET, 1.0))
    res, _ = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert fake.calls[0]["state"]["fan_new_messages"] == ["[sent a photo or video]"], fake.calls[0]["state"]
    (r,) = await _rows(aid)
    assert r.trigger_key == "3101" and json.loads(r.jev_json)["state"] == fake.calls[0]["state"], r


async def case_giphy_dm_reads_gif_only():
    aid, fan = "fa_gif", 62
    await _seed(aid, rule=True, gate=False)
    await _media_dm(aid, fan, 3201, T0, gif=True)
    fake = FakeJev((QUIET, 1.0))
    res, _ = await _run(aid, fake)
    assert res["status"] == "ok", res
    assert fake.calls[0]["state"]["fan_new_messages"] == ["[sent a GIF]"], fake.calls[0]["state"]
    (r,) = await _rows(aid)
    assert r.trigger_key == "3201" and json.loads(r.jev_json)["state"] == fake.calls[0]["state"], r


async def case_state_shape():
    """The Jev state is the probe's request shape: exactly his Turn, the 12
    lines before it (`from`, `text`, `when`, an optional `ppv`), her last line,
    his last purchase and the Pending offer, all read at or before the Anchor."""
    aid, fan = "fa_shape", 63
    await _seed(aid, rule=True, gate=False)
    t = T0                                      # his Turn starts here
    gif = json.dumps({"giphyId": "xT9IgG50Fb7Mi0prBC", "media": [], "mediaCount": 0})
    for mid, d, body, at, kw in (
            (4000, "in", "too old to read", t - timedelta(days=4), {}),
            (4001, "out", "good morning babe", t - timedelta(days=3), {}),
            (4002, "in", "morning", t - timedelta(days=3) + timedelta(minutes=5), {}),
            (4003, "out", "", t - timedelta(days=2), dict(price_cents=1500, is_paid=True, media_count=2)),
            (4004, "in", "wow", t - timedelta(days=2) + timedelta(minutes=1), {}),
            (4005, "in", "", t - timedelta(hours=20), dict(media_count=1)),
            (4006, "in", "", t - timedelta(hours=5), dict(raw_json=gif)),
            (4007, "out", "", t - timedelta(hours=4), {}),       # nothing to read: dropped
            (4008, "out", "you there?", t - timedelta(minutes=90),
             dict(automation_kind="welcome_chatter_for_info")),
            (4009, "in", "yes", t - timedelta(minutes=60), {}),
            (4010, "out", "", t - timedelta(minutes=30), dict(price_cents=2500, is_paid=False)),
            (4011, "out", "", t - timedelta(minutes=8), dict(media_count=1, automation_kind="image_reply")),
            (4012, "out", "<p>what do you think &amp; want?</p>", t - timedelta(minutes=2), {}),
            (4013, "in", "hmm", t, {}),
            (4014, "in", "", t + timedelta(minutes=1), dict(media_count=1)),          # the Anchor
            (4015, "out", "later, from another Lane", t + timedelta(minutes=2),
             dict(price_cents=900, is_paid=False, automation_kind="reply_mass_funnel"))):
        await _msg(aid, fan, mid, d, body, at, **kw)
    await wd.on_inbound_message(aid, fan, 4013)
    await wd.on_inbound_image(aid, fan, 4014)
    fake = FakeJev((QUIET, 1.0))
    res, stats = await _run(aid, fake)
    assert res["status"] == "ok" and stats["recorded"] == 1, (res, stats)
    st = fake.calls[0]["state"]
    assert set(st) == {"fan_new_messages", "thread", "her_last_line", "last_purchase",
                       "pending_offer"}, sorted(st)
    assert st["fan_new_messages"] == ["hmm", "[sent a photo or video]"], st["fan_new_messages"]
    assert st["thread"] == [
        {"from": "her", "text": "good morning babe", "when": "days before"},
        {"from": "fan", "text": "morning", "when": "days before"},
        {"from": "her", "text": "[photo or video]", "when": "days before",
         "ppv": "locked $15 message, he bought it"},
        {"from": "fan", "text": "wow", "when": "days before"},
        {"from": "fan", "text": "[sent a photo or video]", "when": "earlier the same day"},
        {"from": "fan", "text": "[sent a GIF]", "when": "earlier the same day"},
        {"from": "her", "text": "you there?", "when": "within the last two hours"},
        {"from": "fan", "text": "yes", "when": "within the last two hours"},
        {"from": "her", "text": "[locked message]", "when": "within the last two hours",
         "ppv": "locked $25 message, he has not bought it"},
        {"from": "her", "text": "[she sent him a pic back]", "when": "minutes before"},
        {"from": "her", "text": "what do you think & want?", "when": "minutes before"},
    ], st["thread"]
    assert st["her_last_line"] == "what do you think & want?", st["her_last_line"]
    assert st["pending_offer"] == "locked $25 message", st["pending_offer"]
    assert st["last_purchase"] == "none in the last 7 days", st["last_purchase"]
    assert "another Lane" not in json.dumps(st), st
    (r,) = await _rows(aid)
    assert r.trigger_key == "4014" and json.loads(r.jev_json)["state"] == st, r


def _ns(mid: int, direction: str, at: datetime, body: str = "", **kw) -> types.SimpleNamespace:
    """A plain chat row with `Message`'s fields and defaults: no DB."""
    return types.SimpleNamespace(**{
        "message_id": mid, "direction": direction, "created_at": at, "body": body,
        "media_count": 0, "price_cents": 0, "is_paid": None, "purchased_at": None,
        "is_unsent": False, "raw_json": None, "automation_kind": None, **kw})


def case_cut_runs():
    """The one Turn definition over plain rows: runs cut at each outbound, each
    with the outbound before it (the starting cut for the first)."""
    t = [T0 + timedelta(minutes=i) for i in range(5)]
    start = (T0 - timedelta(hours=1), 1)
    for label, rows, cut, want in (
            ("no outbound", [_ns(1, "in", t[0]), _ns(2, "in", t[1])], None, [(None, [1, 2])]),
            ("outbound splits two runs", [_ns(1, "in", t[0]), _ns(2, "out", t[1]), _ns(3, "in", t[2]),
                                          _ns(4, "in", t[3])], None, [(None, [1]), ((t[1], 2), [3, 4])]),
            ("trailing outbound", [_ns(1, "in", t[0]), _ns(2, "out", t[1]), _ns(3, "out", t[2])], None,
             [(None, [1])]),
            ("starting cut carried", [_ns(5, "in", t[0]), _ns(6, "out", t[1]), _ns(7, "in", t[2])], start,
             [(start, [5]), ((t[1], 6), [7])]),
            ("leading outbound replaces it", [_ns(8, "out", t[0]), _ns(9, "in", t[1])], start,
             [((t[0], 8), [9])]),
            ("empty", [], start, [])):
        got = [(c, [m.message_id for m in turn]) for c, turn in runner.cut_runs(rows, cut)]
        assert got == want, (label, got, want)


async def case_build_state_plain_rows_match_db():
    """`build_state` over plain rows (no DB) gives the state and offer flag the
    DB path (`_read`) gives for the same thread."""
    aid, fan = "fa_pure_state", 70
    await _seed(aid, rule=True, gate=False)
    rows = [
        _ns(8001, "out", T0 - timedelta(hours=3), "<p>hey babe &amp; hi</p>"),
        _ns(8002, "in", T0 - timedelta(hours=2), "hi"),
        _ns(8003, "out", T0 - timedelta(minutes=30), "", price_cents=1500, is_paid=False, media_count=2,
            automation_kind="reply_mass_funnel"),
        _ns(8004, "in", T0, "what is it"),
        _ns(8005, "in", T0 + timedelta(minutes=1), "", media_count=1)]
    tx = types.SimpleNamespace(kind="tip", amount_cents=500, occurred_at=T0 - timedelta(hours=1))
    async with get_session() as s:
        for m in rows:
            s.add(Message(account_id=aid, fan_id=fan, **vars(m)))
        s.add(Transaction(account_id=aid, fan_id=fan, **vars(tx)))
    ((anchor, db_st, db_offer),) = await runner._read(aid, fan, 8005)
    assert anchor.message_id == 8005, anchor
    st, has_offer = runner.build_state(rows[3:], rows[:3], tx, rows[2])
    assert (st, has_offer) == (db_st, db_offer), (st, has_offer, db_st, db_offer)
    assert has_offer and len(st["thread"]) == 3 and st["last_purchase"] != "none in the last 7 days", st
    assert st["pending_offer"] == "locked $15 message: [photo or video]", st


async def _offer_turn(aid: str, fan: int, offers: list[dict], ago: timedelta = timedelta(hours=1)) -> dict:
    """Her priced messages `offers` (oldest first, `ago` apart), then his DM:
    the state Jev read."""
    await _seed(aid, rule=True, gate=False)
    for i, kw in enumerate(offers):
        await _msg(aid, fan, 5001 + i, "out", kw.pop("body"), T0 - ago * (len(offers) - i), **kw)
    await _dm(aid, fan, 5100, "what is it", T0)
    fake = FakeJev((QUIET, 1.0))
    res, _ = await _run(aid, fake)
    assert res["status"] == "ok", res
    return fake.calls[0]["state"]


async def case_pending_offer():
    """Her newest priced, unbought, not-unsent outbound before his Turn, from
    any Lane or a human and of any age: `pending_offer` carries it."""
    st = await _offer_turn("fa_offer_funnel", 64, [
        dict(body="<p>just for you 😈</p>", price_cents=1500, is_paid=False,
             automation_kind="reply_mass_funnel")])
    assert st["pending_offer"] == "locked $15 message: just for you 😈", st
    assert st["her_last_line"] == "just for you 😈 (locked $15 message, he has not bought it)", st
    st = await _offer_turn("fa_offer_human", 65, [
        dict(body="", price_cents=2000, media_count=3)])          # a human send: no Lane kind
    assert st["pending_offer"] == "locked $20 message: [photo or video]", st
    st = await _offer_turn("fa_offer_old", 66, [                 # no age limit
        dict(body="still waiting for you", price_cents=3000, is_paid=False,
             automation_kind="reply_mass_funnel")], ago=timedelta(days=3))
    assert st["pending_offer"] == "locked $30 message: still waiting for you", st
    st = await _offer_turn("fa_offer_behind", 68, [              # newest unbought, not newest priced
        dict(body="first one", price_cents=1000, is_paid=False),
        dict(body="second one", price_cents=1500, is_paid=True)])
    assert st["pending_offer"] == "locked $10 message: first one", st


async def case_pending_offer_none():
    """A bought, a purchased or an unsent priced message is no Pending offer."""
    for aid, kw in (("fa_offer_bought", dict(is_paid=True)),
                    ("fa_offer_purchased", dict(is_paid=None, purchased_at=T0 - timedelta(minutes=30))),
                    ("fa_offer_unsent", dict(is_paid=False, is_unsent=True))):
        st = await _offer_turn(aid, 67, [dict(body="for you", price_cents=1500, **kw)])
        assert st["pending_offer"] == "none", (aid, st)


async def _purchase_turn(aid: str, fan: int, txs: list[tuple[str, int, timedelta]]) -> str:
    """His purchases `txs` (kind, cents, how long before his Turn; negative =
    after its start), then a Turn of two DMs ten minutes apart: the
    `last_purchase` Jev read."""
    await _seed(aid, rule=True, gate=False)
    async with get_session() as s:
        for kind, cents, before in txs:
            s.add(Transaction(account_id=aid, fan_id=fan, kind=kind, amount_cents=cents,
                              occurred_at=T0 - before))
        s.add(Transaction(account_id=aid, fan_id=fan + 1000, kind="tip", amount_cents=7700,
                          occurred_at=T0 - timedelta(minutes=1)))      # another Fan's
    await _msg(aid, fan, 6001, "in", "hey", T0)
    await _dm(aid, fan, 6002, "you there", T0 + timedelta(minutes=10))
    fake = FakeJev((QUIET, 1.0))
    res, _ = await _run(aid, fake)
    assert res["status"] == "ok", res
    return fake.calls[0]["state"]["last_purchase"]


async def case_last_purchase():
    """His newest tip or PPV buy at or before the Anchor, in the probe's words;
    past 7 days, "none in the last 7 days"."""
    for i, (txs, want) in enumerate((
            ([("tip", 2500, timedelta(hours=3))], "he tipped her $25, about 3 hours ago"),
            ([("ppv_message", 1200, timedelta(minutes=30))],
             "he bought a locked message for $12, 30 minutes ago"),
            ([("ppv_post", 900, timedelta(days=3))], "he bought a locked message for $9, about 3 days ago"),
            ([("ppv_message", 1200, timedelta(days=2)), ("tip", 500, timedelta(minutes=50)),
              ("subscription", 1000, timedelta(minutes=5))], "he tipped her $5, 50 minutes ago"),
            ([("tip", 500, -timedelta(minutes=5))], "he tipped her $5, 0 minutes ago"),   # inside his Turn
            ([("tip", 500, -timedelta(minutes=11))], "none in the last 7 days"),          # after the Anchor
            ([("tip", 2500, timedelta(days=8))], "none in the last 7 days"),
            ([], "none in the last 7 days"))):
        got = await _purchase_turn(f"fa_buy_{i}", 69, txs)
        assert got == want, (i, got, want)


# ── No-send ───────────────────────────────────────────────────────────

_SHADOW = (runner, rj, full_ai_decide, _jev)
_BANNED_MODULES = {"of_client", "automations._outbound", "automation_executor", "fan_lease"}
_BANNED_NAMES = {"_make_client", "send_message", "acquire_fan_lease", "start_fan_cooldown"}


def _send_paths(source: str) -> list[str]:
    """No-send (a): every import of a send module and every send name in `source`."""
    found = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            found += [a.name for a in n.names if a.name in _BANNED_MODULES]
        elif isinstance(n, ast.ImportFrom):
            # A relative import in automations/ resolves under `automations`.
            mod = ".".join(p for p in ("automations" if n.level else "", n.module or "") if p)
            names = {f"{mod}.{a.name}" if mod else a.name for a in n.names}
            found += [m for m in {mod} | names if m in _BANNED_MODULES]
            found += [a.name for a in n.names if a.name in _BANNED_NAMES]
        elif isinstance(n, ast.Name) and n.id in _BANNED_NAMES:
            found.append(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _BANNED_NAMES:
            found.append(n.attr)
    return found


def case_no_send_a_import_scan():
    for mod in _SHADOW:
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert _send_paths(src) == [], (mod.__name__, _send_paths(src))
    # The scan itself sees what it must.
    assert _send_paths("import automation_executor as ax\nax._make_client('a')\n") == [
        "automation_executor", "_make_client"]
    assert _send_paths("from . import _outbound\n") == ["automations._outbound"]
    assert _send_paths("from fan_lease import acquire_fan_lease\n") == ["fan_lease", "acquire_fan_lease"]


# Every send path, at each binding a sender looks it up by: the client factory,
# OFClient's `request` (the spec's), its wire call (`get` skips `request`) and
# the proxy-retry funnel the raw CDN calls share (of_client.py:842-847), and the
# lease and cooldown both on fan_lease and on ax's re-export
# (automation_executor.py:87-98).
_SEND_PATHS = ((ax, "_make_client"), (of_client.OFClient, "request"),
               (of_client.OFClient, "_http_call"), (of_client.OFClient, "_proxy_retry"),
               (fan_lease, "acquire_fan_lease"), (fan_lease, "start_fan_cooldown"),
               (ax, "acquire_fan_lease"), (ax, "start_fan_cooldown"))


class SendReached(Exception):
    """A shadow run reached a send path."""


@contextlib.contextmanager
def _raising():
    """Each send path records its hit, then raises. The hit list, not the raise,
    is the proof: an `except Exception` on the way cannot swallow a hit."""
    hits: list[str] = []
    saved = [(o, n, getattr(o, n)) for o, n in _SEND_PATHS]
    for o, n, real in saved:
        name = f"{o.__name__}.{n}"

        def hit(*_a, _name=name, **_k):
            hits.append(_name)
            raise SendReached(_name)

        async def ahit(*a, _hit=hit, **k):
            _hit(*a, **k)
        setattr(o, n, ahit if inspect.iscoroutinefunction(real) else hit)
    try:
        yield hits
    finally:
        for o, n, real in saved:
            setattr(o, n, real)


async def _snapshot() -> dict[str, list]:
    out = {}
    async with get_session() as s:
        for t in ("messages", "fans", "fan_lease", "skip_list"):
            out[t] = [tuple(r) for r in (await s.execute(text(f"SELECT * FROM {t} ORDER BY 1, 2"))).all()]
    return out


async def _inbound_run(aid: str, fan: int, mid: int) -> tuple[dict, dict, dict, list[str]]:
    """Every new path: his DM `mid` (the hook enqueues), another Lane's reply,
    his DM `mid + 2` (the hook only wakes: the job is pending), then one
    catch-up run deciding both Turns."""
    await _seed(aid, rule=True, gate=False)
    await _msg(aid, fan, mid, "in", "hey gorgeous", T0)
    await _msg(aid, fan, mid + 1, "out", "hi handsome", T0 + timedelta(minutes=1),
               automation_kind="reply_mass_funnel")
    await _msg(aid, fan, mid + 2, "in", "what you up to", T0 + timedelta(minutes=2))
    before = await _snapshot()
    with _raising() as hits, _fake_jev(FakeJev((QUIET, 1.0), (QUIET, 1.0))):
        await wd.on_inbound_message(aid, fan, mid)
        await wd.on_inbound_message(aid, fan, mid + 2)
        res = await run_once(aid, KIND)
    return res, before, await _snapshot(), hits


async def case_no_send_b_raising_patches():
    aid = "fa_nosend_b"
    res, before, after, hits = await _inbound_run(aid, 31, 901)
    assert hits == [], hits
    assert res["status"] == "ok", res
    assert [r.trigger_key for r in await _rows(aid)] == ["901", "903"]
    assert await _jobs(aid, KIND) == []
    for t in before:
        assert after[t] == before[t], (t, before[t], after[t])


async def case_no_send_c_mutant_is_caught():
    src = Path(runner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run")
    fn.body[:0] = ast.parse("import automation_executor as ax\nax._make_client(account_id)\n").body
    mutant_src = ast.unparse(ast.fix_missing_locations(tree))
    assert set(_send_paths(mutant_src)) == {"automation_executor", "_make_client"}

    real = automation_registry.get_automation(KIND)
    mutant = types.ModuleType("automations._full_ai_chat_mutant")
    mutant.__file__ = runner.__file__
    try:
        exec(compile(mutant_src, "<full_ai_chat mutant>", "exec"), mutant.__dict__)  # re-registers KIND
        assert automation_registry.get_automation(KIND) is mutant.run
        aid = "fa_nosend_c"
        res, before, after, hits = await _inbound_run(aid, 32, 902)
        assert hits == ["automation_executor._make_client"], hits
        assert res["status"] == "error", res
        assert await _rows(aid) == []
        assert (await _run_row(res["run_id"])).status == "error"
        for t in before:
            assert after[t] == before[t], t
    finally:
        automation_registry.register(KIND)(real)
    assert automation_registry.get_automation(KIND) is runner.run


async def case_no_send_c_swallowed_call_is_caught():
    """`ask` turns every Exception into a GateError, so a send reached there
    could end as an ok run; the hit is recorded before anything can swallow it."""
    tree = ast.parse(Path(rj.__file__).read_text(encoding="utf-8"))
    ask = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "ask")
    guarded = next(n for n in ask.body if isinstance(n, ast.Try))
    guarded.body[:0] = ast.parse("import automation_executor as ax\nax._make_client(account_id)\n").body
    mutant_src = ast.unparse(ast.fix_missing_locations(tree))
    assert set(_send_paths(mutant_src)) == {"automation_executor", "_make_client"}

    mutant = types.ModuleType("automations._router_jev_mutant")
    exec(compile(mutant_src, "<_router_jev mutant>", "exec"), mutant.__dict__)
    mutant.GateError = rj.GateError     # the one class the runner catches, as in the real module
    real = rj.ask
    rj.ask = mutant.ask  # type: ignore[assignment]     # the runner reads `router.ask`
    try:
        _res, before, after, hits = await _inbound_run("fa_nosend_c2", 33, 903)
    finally:
        rj.ask = real  # type: ignore[assignment]
    # A Jev failure writes its `jev_failed` row and the catch-up goes on, so the
    # run ends ok and the swallowed call is caught once per Turn (two Turns).
    assert hits == ["automation_executor._make_client"] * 2, hits
    assert _res["status"] == "ok", _res
    assert [r.route_row for r in await _rows("fa_nosend_c2")] == ["jev_failed"] * 2
    for t in before:
        assert after[t] == before[t], t


_harness.run()
