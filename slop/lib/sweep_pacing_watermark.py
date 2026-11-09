"""The ledger full walk's persisted watermark (transaction_scan_history.last_full_at), the last two
stages of scenarios/2026-11-05-sweep-pacing.py, after its own checks (their logs are taken).

restart (tx_restart_keeps_full_schedule): every backfilled, unpaused Creator gets a watermark by
SQL, from the product's crc32 phases (`PHASE_PIN: false`, so the stage runs on the real ones):
alternately in its previous period (due) or at the start of its current one (not due); a Creator
within MARGIN_S of its next boundary is always due, so no clock tick flips a verdict mid-stage.
CROWD (one shared OF bucket: 8 full walks at once would 429 each other) is stamped not due and
left out of the verdict.
The relay is SIGKILLed (`crash_relay`) and started on the same DB, then two supervisor passes run.
Pass A: exactly the due Creators walk full (their ingest_tx_scan_start mode and their unfiltered
ledger GETs at OF), the rest recent, their watermark untouched; the due ones' stamped >= the restart.
Pass B: nobody walks full (a Creator whose period boundary falls between pass A and pass B is not asserted there).

failed (tx_failed_full_consumes_period): one of those Creators F (not CROWD's shared bucket, the
most time to its boundary), made due by SQL, its full walk's first page answered 429 twice (the
send and of_pacing's one retry: the terminal second 429). Pass 1: F walks full and fails (exactly
two 429s, no other unfiltered GET), error kept (status error, streak + 1, the 429 in last_error),
rows held unchanged, watermark stamped in this period. Pass 2 (same period): F walks recent, no
unfiltered GET. Its watermark moved back one period by SQL (the boundary crossed: time compression,
declared); pass 3: F walks full again, completes, streak 0.

Bypasses (declared): the watermarks are seeded by SQL (rows the product writes: a full walk's
window end); the boundary crossing is the watermark moved back one period, not the clock; the
supervisor's 900 s sleep is `/__slop/sweep-pacing/run` as in the rest of the scenario.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from slop.lib.sweep_pacing_evidence import TX_START as _TX_START, held_count, scan_many
from slop.lib.sweep_pacing_faults import TX_FAILED_FULL, TX_RESTART
from slop.lib.sweep_pacing_wire import TOO_MANY
from slop.seed import ts

MARGIN_S = 300.0          # a Creator this close to its next boundary is seeded due
PASS_TIMEOUT_S = 300


def _utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def _dt(v) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _bucket_start(epoch: float, phase: float, every: float) -> float:
    """Epoch of the start of the period `epoch` falls in (transaction_ingest_decide.full_bucket)."""
    return ((epoch + phase) // every) * every - phase


async def _runs(http, ids=()) -> dict:
    r = await http.get("/__slop/sweep-pacing/runs", params={"phase_ids": ",".join(ids)} if ids else None)
    r.raise_for_status()
    return r.json()


async def tx_pass(http, sw, timeout_s: float = PASS_TIMEOUT_S) -> dict:
    """One supervisor pass, returned once it ended; per Creator its walk modes and its unfiltered
    ledger GETs at OF."""
    n0 = len((await _runs(http))["runs"])
    t0 = time.time()
    (await http.post("/__slop/sweep-pacing/run", json={"job": "tx_cycles", "cycles": 1})).raise_for_status()
    until = time.monotonic() + timeout_s
    while True:
        got = await _runs(http)
        mine = got["runs"][n0:]
        if (mine and all(x["t1"] for x in mine)) or time.monotonic() > until:
            break
        await asyncio.sleep(0.5)
    t1 = time.time()
    modes: dict[str, list[str]] = defaultdict(list)
    for y in got["log"]:
        if t0 <= y["t"] <= t1 and (m := _TX_START.search(y["msg"])):
            modes[m.group(1)].append(m.group(2))
    full: dict[str, list[int]] = defaultdict(list)
    for e in sw.snapshot():
        if t0 <= e["t"] <= t1 and e["route"] == "transactions" and "startDate" not in e["query"]:
            full[e["account"]].append(e["status"])
    return {"t0": t0, "t1": t1, "modes": dict(modes), "full": dict(full),
            "ended": bool(mine) and all(x["t1"] for x in mine), "errors": [x["error"] for x in mine if x["error"]]}


def _stamp(w, at: dict[str, datetime]) -> None:
    con = w.sql()
    with con:
        con.executemany("UPDATE transaction_scan_history SET last_full_at = ? WHERE account_id = ?",
                        [(ts(v), a) for a, v in at.items()])
    con.close()


async def run(ctx, w, sw, *, shared: set[str]) -> None:
    http = ctx.owner.share()
    con = w.sql()
    done = sorted(r[0] for r in con.execute(
        "SELECT account_id FROM transaction_scan_history WHERE fully_backfilled = 1 "
        "AND (paused_until IS NULL OR paused_until < ?)", (ts(_utc(time.time())),)))
    con.close()
    (await http.post("/__slop/sweep-pacing/knobs", json={"PHASE_PIN": False})).raise_for_status()
    got = await _runs(http, done)
    every, phases = float(got["full_every_s"]), {a: float(p) for a, p in got["phases"].items()}

    # ── restart: mixed persisted phases, SIGKILL, the same DB ───────────────
    now = time.time()
    left = {a: _bucket_start(now, phases[a], every) + every - now for a in done}
    asserted = [a for a in done if a not in shared]   # CROWD's shared bucket: stamped not due, not asserted
    due = {a for k, a in enumerate(asserted) if k % 2 == 0} | {a for a in done if left[a] < MARGIN_S}
    seed = {a: _utc(_bucket_start(now, phases[a], every) + (-1 if a in due else 1)) for a in done}
    _stamp(w, seed)
    await http.aclose()
    killed = ctx.stack.crash_relay()
    await asyncio.to_thread(ctx.stack.start_relay)
    http = ctx.owner.share()
    (await http.post("/__slop/sweep-pacing/knobs", json={"PHASE_PIN": False})).raise_for_status()
    after = await _runs(http, done)
    a_pass = await tx_pass(http, sw)
    scan_a = scan_many(w, done)
    b_pass = await tx_pass(http, sw)
    restart_at = _utc(killed)
    wrong = {}
    for a in asserted:
        want = ["refresh"] if a in due else ["recent"]
        stamped = _dt(scan_a.get(a, {}).get("last_full_at"))
        ok_stamp = (stamped is not None and stamped >= restart_at - timedelta(seconds=1)) if a in due \
            else stamped == seed[a]
        # A due Creator (left < MARGIN_S) whose boundary falls between pass A and pass B's end is due again
        # in pass B: its full walk there is correct, so pass B only asserts the ones still in A's period.
        crossed = _bucket_start(a_pass["t0"], phases[a], every) != _bucket_start(b_pass["t1"], phases[a], every)
        ok_b = crossed or (b_pass["modes"].get(a) == ["recent"] and not b_pass["full"].get(a))
        ok = (a_pass["modes"].get(a) == want and bool(a_pass["full"].get(a)) == (a in due) and ok_stamp and ok_b)
        if not ok:
            wrong[a] = {"due": a in due, "pass_a": a_pass["modes"].get(a), "pass_a_full_gets": a_pass["full"].get(a),
                        "pass_b": b_pass["modes"].get(a), "pass_b_full_gets": b_pass["full"].get(a),
                        "seeded": ts(seed[a]), "after_a": scan_a.get(a, {}).get("last_full_at")}
    phases_kept = after["phases"] == got["phases"]
    ctx.check(TX_RESTART, len(due & set(asserted)) >= 1 and len(set(asserted) - due) >= 1 and not wrong and phases_kept
              and a_pass["ended"] and b_pass["ended"] and time.time() - now < MARGIN_S,
              creators=len(asserted), due=sorted(due & set(asserted)), not_due=sorted(set(asserted) - due),
              shared_not_asserted=sorted(shared & set(done)), wrong=wrong,
              phases_kept=phases_kept, stage_s=round(time.time() - now, 1),
              pass_a_s=round(a_pass["t1"] - a_pass["t0"], 1), pass_b_s=round(b_pass["t1"] - b_pass["t0"], 1),
              errors=a_pass["errors"] + b_pass["errors"])

    # ── failed: a terminal second 429 on the full walk spends the period ────
    now = time.time()
    left = {a: _bucket_start(now, phases[a], every) + every - now for a in done if a not in shared}
    f = max(left, key=left.get) if left else None
    if f is None or left[f] < MARGIN_S:
        ctx.check(TX_FAILED_FULL, False, why="no backfilled Creator with time to its boundary", left=left)
        await http.aclose()
        return
    start = _bucket_start(now, phases[f], every)
    _stamp(w, {f: _utc(start - 1)})
    before, held0 = scan_many(w, [f])[f], held_count(w, f)
    sw.inject[(f, "transactions")] = {"offset": 0, "full": True, "text": TOO_MANY, "times": 2}
    p1 = await tx_pass(http, sw)
    s1, held1 = scan_many(w, [f])[f], held_count(w, f)
    p2 = await tx_pass(http, sw)
    s2 = scan_many(w, [f])[f]
    stamped = _dt(s1["last_full_at"])
    if stamped is not None:
        _stamp(w, {f: stamped - timedelta(seconds=every)})   # the boundary crossed (declared)
    p3 = await tx_pass(http, sw)
    s3, held3 = scan_many(w, [f])[f], held_count(w, f)
    steps = {
        "fail_pass_walks_full": p1["modes"].get(f) == ["refresh"],
        "exactly_two_429s": p1["full"].get(f) == [429, 429],
        "error_kept": s1["status"] == "error" and s1["failures"] == (before["failures"] or 0) + 1
        and "429" in (s1["last_error"] or ""),
        "rows_kept": held1 == held0,
        "stamped_this_period": stamped is not None and stamped >= _utc(start),
        "same_period_recent": p2["modes"].get(f) == ["recent"] and not p2["full"].get(f)
        and s2["last_full_at"] == s1["last_full_at"],
        "next_period_full": p3["modes"].get(f) == ["refresh"] and bool(p3["full"].get(f))
        and all(st == 200 for st in p3["full"].get(f, [])),
        "retry_completes": s3["failures"] == 0 and s3["status"] == "ok" and held3 >= held1,
        "injected_fired": bool(sw.inject[(f, "transactions")].get("done")),
    }
    ctx.check(TX_FAILED_FULL, all(steps.values()) and time.time() - now < left[f], creator=f, **steps,
              modes=[p.get("modes", {}).get(f) for p in (p1, p2, p3)],
              full_gets=[p.get("full", {}).get(f) for p in (p1, p2, p3)],
              scan_before=before, scan_fail=s1, scan_same=s2, scan_next=s3, held=(held0, held1, held3),
              seconds_to_boundary=round(left[f]), stage_s=round(time.time() - now, 1))
    ctx.metric("tx_watermark", {"every_s": every, "due": sorted(due), "creators": done, "failed_creator": f,
                                "restart_pass_s": [round(p["t1"] - p["t0"], 1) for p in (a_pass, b_pass)],
                                "fail_pass_s": [round(p["t1"] - p["t0"], 1) for p in (p1, p2, p3)]})
    await http.aclose()
