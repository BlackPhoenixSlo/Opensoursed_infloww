#!/usr/bin/env python3
"""Rollout driver (Phase 3): bring every Eligible Creator on a relay to its Describe target and Fill every
eligible Sequence, unattended and resumably, through the product routes over loopback.

    nice -n 10 python3 -I scripts/script-fill-rollout/rollout.py <mode> --relay http://127.0.0.1:<port> [...]

Modes: measure | collect | describe | report (3a) and plan | apply | undo (3b). Every mode is a dry run (no
product-state write: vault, Collect runs, Scripts rows, spend ledger) unless --live. Sign-in: SFR_SESSION holds a
`chatterly_session` cookie value; absent and on a TTY, a hidden prompt signs in (POST /auth/login, then
/auth/2fa/login on a challenge). The session lives in memory only: never in a file, the journal or argv. The
session must be a Master (`is_admin`).

Fill side (3b). `plan` POSTs `fill/plan` (a POST that writes nothing server-side) for every Sequence of every
Eligible Creator, runs the Apply gate and journals status, gate, flags, the plan and the rows' current values;
it is read-only, so it runs the same with or without --live. `apply` sends only journaled plans that passed the
gate (run `plan` first); a filled (not undone) or `uncertain` Sequence is never applied again, whatever is
planned after it. Live, it first refuses (exit 2) without a fresh, integrity-checked --backup file, and skips a
Sequence whose rows about to be written the backup does not hold; per plan (one without a fingerprint is never
sent) it journals `apply_intent`, POSTs `fill/apply` with the reviewed fingerprint (re-plan and re-gate once on
409 stale, skip as `stale` after a second), journals the Undo list before anything else, then reads the Scripts
list back; any read-back mismatch pauses the run (exit 3). A re-run reconciles an intent whose response was lost
by read-back (never landed -> re-plan; landed -> rebuilt Undo list; differs -> `uncertain`, never undone).
`undo` replays journaled Undo lists through `fill/undo`, newest first, and lists rows left because someone
edited them. Without --live, apply and undo POST nothing: they list what they would do. Reserved sequences
(`FM` + digits) are never sent to apply. `report --sample N --seed N` writes a host-only contact sheet.

Exit codes: 0 done, 2 refused (usage, non-loopback relay, not Master, relay without Phase 1a, backup missing or
bad), 3 paused (re-run when the relay is well / the ceiling is restated), 4 deferred work remains (re-run after
00:00 UTC). Open Creators (key, Jev not ready, no progress, mirror incomplete) and skipped Sequences are listed
and do not change the exit code.

Journal: JSON Lines, append-only, mode 0600, default ~/script-fill-rollout/journal.jsonl. It holds ids; never
copy it into the repo. No lock: one operator runs one driver.

Standard library only (the box host has no venv); no `service/` import. One process, one thread: parallel sweeps
run on the server, the driver polls them. The relay client, journal and run context live in rollout_core.py; the fill
side in rollout_fill.py; decisions in rollout_decide.py (pure). Spec:
docs/spec/phase-03-rollout-to-every-creator.md.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parent))   # `-I` drops the script's dir; stdlib stays first
import rollout_core as core  # noqa: E402
import rollout_decide as rd  # noqa: E402
import rollout_fill  # noqa: E402
from rollout_core import (EXIT_DEFERRED, EXIT_DONE, EXIT_PAUSED, EXIT_REFUSED, VAULT, Ctx, Journal,  # noqa: E402
                          Refused, Relay, check_relay, iso, now, say, sign_in, utc_day)

MODES = ("measure", "collect", "describe", "report", "plan", "apply", "undo")
REPO = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL = Path.home() / "script-fill-rollout" / "journal.jsonl"
DEFAULT_OUT = REPO / ".scratch" / "script-fill-content" / "rollout-report.md"
RELAY_SICK = frozenset({"livez_down", "errors"})


class Paused(Exception):
    """Exit 3 with a pause reason (before any sweep ran)."""


def cap_of(plan: dict) -> dict:
    cap = dict(plan.get("cap") or {})
    keep = {k: cap.get(k) for k in ("spent_millicents", "cap_millicents", "capped", "key_missing")}
    keep["day"] = cap.get("day") or utc_day()   # the ledger's UTC day (llm_client.cap_state), else ours
    return keep


def read_roster(ctx: Ctx) -> int:
    """Read the roster once, list skips once, journal it. Returns the unfiltered Eligible count."""
    r = ctx.relay.call("GET", "/admin/accounts")
    if not r.ok:
        raise Paused(f"roster_unreadable_{r.status}")
    ok, skipped = rd.roster(r.json)
    ctx.all_ok = ok
    want = set(ctx.args.creator or [])
    ctx.scoped = [a for a in ok if not want or str(a.get("id")) in want]
    ctx.skipped = [(a, why) for a, why in skipped if not want or str(a.get("id")) in want]
    known = {str(a.get("id")) for a in ok} | {str(a.get("id")) for a, _ in skipped}
    for cid in sorted(want - known):
        say(f"warn: --creator {cid} is not on the roster")
    for a, why in ctx.skipped:
        say(f"skip {a.get('id')} ({a.get('username') or ''}): {why}")
        ctx.journal.write("skip", str(a.get("id")), reason=why)
    ctx.journal.write("roster", None, eligible=[str(a.get("id")) for a in ctx.scoped], eligible_n=len(ok),
                      skipped=len(ctx.skipped))
    say(f"roster: {len(ok)} eligible, {len(skipped)} skipped; {len(ctx.scoped)} in scope")
    return len(ok)


# ── measure ─────────────────────────────────────────────────────────────────

def mode_measure(ctx: Ctx) -> int:
    """Read-only, per Creator: vault size, mirror complete, described, target remaining, cap state, Sequences."""
    for a in ctx.scoped:
        cid = str(a.get("id"))
        s = ctx.summary(cid) or {}
        p = ctx.plan(cid, rd.DESCRIBE_TARGET)
        if p is None:
            say(f"measure {cid}: plan unreadable")
            continue
        cov = p["coverage"]
        sr = ctx.relay.call("GET", "/admin/saved-replies", {"account_id": cid})
        seqs = len({r.get("script_id") for r in (sr.json or {}).get("list", []) if r.get("script_id")}) \
            if sr.ok else None
        cap = cap_of(p)
        ctx.journal.write("measure", cid, count=s.get("count"), complete=s.get("complete"),
                          described=cov.get("described"), describable=cov.get("describable"),
                          terminal=cov.get("terminal"), goal=cov.get("goal"),
                          target_remaining=p.get("target_remaining"), cap=cap,
                          jev_ready=(p.get("jev") or {}).get("ready"), sequences=seqs)
        say(f"measure {cid}: vault {s.get('count')} complete {s.get('complete')} described {cov.get('described')}"
            f"/{cov.get('goal')} remaining {p.get('target_remaining')} capped {cap.get('capped')} "
            f"spent {rd.dollars(cap.get('spent_millicents'))} sequences {seqs}")
    return EXIT_DONE


# ── collect ─────────────────────────────────────────────────────────────────

def mode_collect(ctx: Ctx) -> int:
    """One Collect per run for each Creator whose mirror is not complete: answer its pauses, wait, re-read
    `complete`. Still incomplete (a page-capped walk) -> open mirror_incomplete unless it holds 1,000 described."""
    for a in ctx.scoped:
        cid = str(a.get("id"))
        s = ctx.summary(cid)
        if s is None:
            say(f"collect {cid}: summary unreadable")
            continue
        if s.get("complete"):
            say(f"collect {cid}: mirror complete ({s.get('count')} items)")
            continue
        if not ctx.live:
            say(f"collect {cid}: would collect (mirror {s.get('count')} items, not complete) [dry run]")
            continue
        r = ctx.relay.call("POST", f"{VAULT}/collect", {"account_id": cid})
        if not r.ok and not (r.status == 409 and r.error() == "collect_already_running"):
            say(f"collect {cid}: start refused HTTP {r.status} {r.error()}")
            continue
        end, run, pauses = _await_collect(ctx, cid)
        if end in RELAY_SICK:
            ctx.journal.write("pause", cid, reason=end)
            say(f"paused: {end} (the Collect runs on; the next run awaits it)")
            return EXIT_PAUSED
        if end != "done":
            ctx.settle_open(cid, end.split(":", 1)[1])
            continue
        ctx._summary.pop(cid, None)
        s2 = ctx.summary(cid) or {}
        ctx.journal.write("collect", cid, run_id=run.get("id"), status=run.get("status"), pauses=pauses,
                          complete=s2.get("complete"), count=s2.get("count"), total_seen=run.get("total_seen"))
        say(f"collect {cid}: {run.get('status')} after {pauses} pause(s), complete {s2.get('complete')}, "
            f"{s2.get('count')} items")
        if not s2.get("complete"):
            p = ctx.plan(cid, rd.DESCRIBE_TARGET)
            if p is None or int(p["coverage"].get("described") or 0) < rd.DESCRIBE_TARGET:
                ctx.settle_open(cid, "mirror_incomplete")
    return EXIT_DONE


def _await_collect(ctx: Ctx, cid: str) -> tuple[str, dict, int]:
    """Poll a started Collect every POLL_S, answering each pause with continue, until it ends.
    Returns (end, run, pauses): end `done`, `livez_down`, `errors` (RETRY_BUDGET retryable failures in a row),
    `open:collect_unreadable_<status>` (RETRY_BUDGET failures in a row, the last one not retryable),
    `open:collect_paused` (still paused after COLLECT_PAUSE_BUDGET continues) or `open:collect_still_running`
    (still running after COLLECT_WAIT_S: the run goes on, the next run awaits it)."""
    pauses, run, fails = 0, {}, 0
    deadline = time.monotonic() + rd.COLLECT_WAIT_S
    while True:
        time.sleep(core.POLL_S)
        if time.monotonic() >= deadline:
            return "open:collect_still_running", run, pauses
        if ctx.relay.livez()["status"] != 200:
            return "livez_down", run, pauses
        bad = ctx.relay.call("GET", f"{VAULT}/collect/status", {"account_id": cid})
        if bad.ok:
            run = bad.json.get("run") or {}
            if run.get("status") != "paused":
                if not run.get("running"):
                    return "done", run, pauses
                fails = 0
                continue
            if pauses >= rd.COLLECT_PAUSE_BUDGET:   # a Collect that never stops pausing ends this run's wait
                return "open:collect_paused", run, pauses
            bad = ctx.relay.call("POST", f"{VAULT}/collect/continue", {"account_id": cid})
            if bad.ok:
                pauses, fails = pauses + 1, 0
                say(f"collect {cid}: pause {pauses} answered (continue)")
                continue
        fails += 1
        if fails >= rd.RETRY_BUDGET:
            if rd.retry_class(bad.status) == "retry":
                return "errors", run, pauses
            return f"open:collect_unreadable_{bad.status}", run, pauses


# ── describe ────────────────────────────────────────────────────────────────

def _ceiling(ctx: Ctx, st: dict, eligible_n: int) -> int:
    if ctx.args.ceiling_cents is not None:
        return int(ctx.args.ceiling_cents) * rd.MC_PER_CENT
    if st.get("ceiling_mc") is not None:
        return int(st["ceiling_mc"])
    return rd.CEILING_CENTS_PER_CREATOR * rd.MC_PER_CENT * eligible_n


def _trim(progress: dict | None) -> dict:
    p = progress or {}
    return {k: p.get(k) for k in ("total", "done", "failed", "capped", "cost_millicents", "error", "key_error",
                                   "stop", "aborted") if p.get(k) not in (None, "", False)}


def probe_target(ctx: Ctx, cid: str, p: dict, before: dict, cap: dict) -> tuple[str, Any, int]:
    """Probe staged requests using filled slots (described plus terminal), and settle against the full plan."""
    goal = before["goal"]
    full_remaining = int(p.get("target_remaining") or 0)
    if full_remaining == 0:
        return "settle", rd.sweep_outcome({**before, "described": goal}, None, None, cap), 0

    cov = p.get("coverage") or {}
    requested = min(rd.DESCRIBE_TARGET, int(cov.get("describable") or rd.DESCRIBE_TARGET))
    filled = before["described"] + int(cov.get("terminal") or 0)
    t = rd.next_target(filled, requested)
    while t < requested:
        pt = ctx.plan(cid, t)
        if pt is None:
            return "unreadable", None, 0
        rem = int(pt.get("target_remaining") or 0)
        if rem > 0:
            return "sweep", t, rem
        t = rd.next_target(t, requested)
    return "sweep", requested, full_remaining


def in_flight(st: dict, ctx: Ctx) -> list[str]:
    """Creators whose journaled sweep_start has no sweep line yet (still on the roster): awaited, reserved."""
    all_ids = {str(a.get("id")) for a in ctx.all_ok}
    return [cid for cid, c in st["creators"].items() if c["state"] == "running" and cid in all_ids]


class Wave:
    """One describe run: up to --slots sweeps at once, each Creator stepped 250 at a time to its goal."""

    def __init__(self, ctx: Ctx, eligible_n: int) -> None:
        self.ctx, self.relay, self.j = ctx, ctx.relay, ctx.journal
        self.st = rd.resume(self.j.read(), now=now())
        self.ceiling = _ceiling(ctx, self.st, eligible_n)
        self.eligible_n = eligible_n
        self.spent = int(self.st["spent_mc"])
        self.item_mc = int(ctx.args.item_mc)
        self.slots = int(ctx.args.slots)
        self.window: dict[str, Any] = {"livez": None, "stops": [], "jev": [], "errors_in_a_row": 0}
        self.running: dict[str, dict] = {}
        self.pending: list[str] = []
        self.retry: list[str] = []            # failed reads / starts: back in `pending` only after a POLL_S sleep
        self.fails: dict[str, int] = {}       # a Creator's failed calls in a row (rd.RETRY_BUDGET)
        self.unsettled: dict[str, str] = {}   # sweeps left in flight in the journal -> an rd.UNSETTLED code
        self.deferred: set[str] = set()
        self.zero: dict[str, int] = {}
        self.pausing: str | None = None
        crs = self.st["creators"]
        self.scope = {str(a.get("id")) for a in ctx.scoped}
        for cid, c in crs.items():
            self.zero[cid] = int(c.get("zero_sweeps") or 0)
        for cid in in_flight(self.st, ctx):   # a sweep still running on the server: await it
            sw = dict(crs[cid]["sweep"])
            sw["zero_sweeps"] = self.zero[cid]
            self.running[cid] = sw
        for a in ctx.scoped:
            cid = str(a.get("id"))
            c = crs.get(cid) or {"state": "pending"}
            if c["state"] == "done":
                say(f"done {cid} (journal)")
            elif c["state"] == "deferred":
                self.deferred.add(cid)
                say(f"deferred {cid} until {iso(c['until'])} (journal)")
            elif c["state"] == "open" and c.get("sticky"):
                say(f"open {cid}: {c.get('reason')} (journal)")
            elif cid not in self.running:
                self.pending.append(cid)

    def failed(self, cid: str, status: int | None = None) -> bool:
        """Count a failed call for `cid` (`status`: the relay's last unless given); True while it may be retried
        (retryable status, budget left)."""
        n = self.fails[cid] = self.fails.get(cid, 0) + 1
        st = self.relay.last_status if status is None else status
        return rd.retry_class(st) == "retry" and n < rd.RETRY_BUDGET

    def retry_or_open(self, cid: str, status: int | None = None) -> None:
        """A failed read or start: 5xx / transport is retried after the next poll sleep, up to RETRY_BUDGET in a
        row, then opened `relay_errors`; any other status will not heal, so it is opened now. The next run
        re-checks both (not sticky). `status`: the failed call's, when other calls ran since."""
        st = self.relay.last_status if status is None else status
        if self.failed(cid, st):
            self.retry.append(cid)
        elif rd.retry_class(st) == "retry":
            self.settle(cid, "open:relay_errors", f"HTTP {st}, {self.fails[cid]} in a row")
        else:
            self.settle(cid, f"open:unreadable_{st}")

    def keep_or_unsettle(self, cid: str, sw: dict, what: str, any_status: bool = False) -> None:
        """A running sweep whose status or recount failed: polled again next round while retryable (any status
        with `any_status`: a status 4xx mid-sweep is no end, and recounting it would split the sweep's spend
        across lines) within the budget; else unsettled — no journal line, so its sweep_start stays in flight and
        the next run awaits and recounts it (its spend is journaled then, never lost); this run ends paused."""
        st = self.relay.last_status
        if self.failed(cid) or (any_status and self.fails[cid] < rd.RETRY_BUDGET):
            self.running[cid] = sw
            return
        self.unsettled[cid] = "recount_unreadable"
        say(f"{what} {cid}: unreadable (HTTP {st}); its sweep stays in flight in the journal for the next run")

    # settle a Creator's next state
    def settle(self, cid: str, outcome: str, detail: str | None = None) -> None:
        if outcome == "continue":
            if cid in self.scope:   # an awaited out-of-scope sweep is not stepped on
                self.pending.insert(0, cid)   # its next step takes the freed slot first
        elif outcome == "done":
            say(f"done {cid}")
        elif outcome == "defer":
            until = rd.next_utc_midnight(now())
            self.j.write("defer", cid, until=until)
            self.deferred.add(cid)
            say(f"defer {cid} until {iso(until)} (Describe cap)")
        elif outcome.startswith("open:"):
            self.ctx.settle_open(cid, outcome.split(":", 1)[1], detail)

    def start(self, cid: str) -> None:
        """Pre-check one Creator and start its next sweep, or settle it."""
        ctx = self.ctx
        s = ctx.summary(cid)
        if s is None:   # classified on the summary's own status: no plan read may overwrite `last_status`
            return self.retry_or_open(cid)
        p = ctx.plan(cid, rd.DESCRIBE_TARGET)
        if p is None:
            return self.retry_or_open(cid)
        cap = cap_of(p)
        before = rd.before_of(s, p, self.zero.get(cid, 0))
        jev = before["jev"]
        self.window["jev"].append([cid, jev.get("ready") is not False])
        out = rd.sweep_outcome(before, None, None, cap)
        if out != "continue":
            return self.settle(cid, out, jev.get("reason") if out == "open:jev_not_ready" else None)
        kind, t, rem = probe_target(ctx, cid, p, before, cap)
        if kind == "unreadable":
            return self.retry_or_open(cid)
        if kind == "settle":
            return self.settle(cid, t)
        goal = before["goal"]
        before["target"] = t
        reserved = len(self.running) + len(self.unsettled)   # an unsettled sweep's spend is not journaled yet
        if not rd.may_sweep(self.spent, reserved, self.ceiling, rd.STEP, self.item_mc):
            self.pending.insert(0, cid)
            self.pausing = "ceiling"
            say(f"ceiling: spent {rd.dollars(self.spent)} + {reserved + 1} sweep(s) x "
                f"{rd.dollars(rd.STEP * self.item_mc)} > {rd.dollars(self.ceiling)}; no new sweep")
            return
        started = now()
        sw = {"target": t, "before": before["described"], "cap_before": cap, "started": started,
              "goal": goal, "complete": before["complete"], "zero_sweeps": before["zero_sweeps"],
              "remaining_before": p.get("target_remaining")}
        # The reservation is journaled BEFORE the paid POST: a kill after the relay accepted it leaves this
        # sweep_start in flight, so the next run awaits it and recounts its spend from `cap_before` (W30 F5).
        self.j.write("sweep_start", cid, target=t, before=sw["before"], cap_before=cap, started=started,
                     goal=goal, complete=sw["complete"], remaining_before=sw["remaining_before"])
        say(f"sweep {cid}: target {t} (described {before['described']}, goal {goal}, {rem} to describe)")
        self.post(cid, sw, cap)

    def post(self, cid: str, sw: dict, cap: dict) -> None:
        """POST the start of the reservation `sw` (journaled) and act on the answer; `cap`: the Creator's cap as
        last read (a refusal closes the reservation there)."""
        r = self.relay.call("POST", f"{VAULT}/describe-all", body={"account_id": cid, "target": sw["target"]})
        sw = {k: v for k, v in sw.items() if k not in ("lost_start", "repost", "cap_seen")}
        if rd.retry_class(r.status) == "retry":
            # Unknown answer (transport error, 5xx): the relay may have accepted the start, and may claim and
            # bill it only later (its POST reads coverage before the claim, while status still says idle). The
            # reservation stays in flight, journaled as lost so a re-run knows it too (W30 F37), and is only ever
            # settled against ITS `cap_before` (W30 F34/F40).
            say(f"sweep {cid}: start answer lost (HTTP {r.status}); polling it as running")
            self.j.write("lost_start", cid, http=r.status, cap_before=sw.get("cap_before") or {})
            self.running[cid] = {**sw, "lost_start": r.status}
            return
        if r.status not in (200, 409):
            # A clear refusal: close the reservation (`not_started`: no sweep, no zero-progress count).
            self.j.write("sweep", cid, target=sw["target"], before=sw["before"], after=sw["before"], progress={},
                         cap_before=sw.get("cap_before") or {}, cap_after=cap, started=sw.get("started"),
                         ended=now(), outcome="not_started", http=r.status)
        if r.status in (429, 424):
            before = {"described": int(sw.get("before") or 0), "target": int(sw["target"]),
                      "goal": int(sw.get("goal") or 0), "complete": sw.get("complete", True),
                      "zero_sweeps": int(sw.get("zero_sweeps") or 0)}
            return self.settle(cid, rd.sweep_outcome(before, None, {"http": r.status}, cap))
        if r.status not in (200, 409):
            return self.settle(cid, f"open:start_{r.status}", r.error() or None)
        self.fails.pop(cid, None)
        self.j.write("start_answer", cid, http=r.status)
        if r.status == 409:
            say(f"sweep {cid}: one already runs, awaiting it")
        if r.status == 200 and (r.json or {}).get("status") == "done":   # met on the server: zero work
            sw["done_now"] = True
        self.running[cid] = sw

    def finish(self, cid: str, progress: dict | None) -> None:
        sw = self.running.pop(cid)
        p = self.ctx.plan(cid, rd.DESCRIBE_TARGET)
        if p is None:
            return self.keep_or_unsettle(cid, sw, "recount")
        cov = p["coverage"]
        after = {"described": int(cov.get("described") or 0), "goal": int(cov.get("goal") or 0),
                 "remaining": p.get("target_remaining")}
        cap_after = cap_of(p)
        lost = sw.get("lost_start")
        if (lost is not None and after["described"] <= int(sw.get("before") or 0)
                and rd.sweep_spend(sw.get("cap_before") or {}, cap_after) == 0):
            # A lost start answer, recounted: nothing described, nothing spent YET — the relay may still claim
            # it. Never closed here and never re-baselined: the same reservation's start is POSTed again after a
            # poll sleep (409 = the lost one claimed; 200 = this one did; the relay runs one sweep per Creator),
            # so whatever runs is recounted from the original `cap_before` (W30 F40). Out of retries: left in
            # flight in the journal (lost), the run pauses.
            if self.failed(cid, lost):
                self.running[cid] = {**sw, "repost": True, "cap_seen": cap_after}
            else:
                self.unsettled[cid] = "start_unanswered"
                say(f"sweep {cid}: start still unanswered after {self.fails[cid]} tries; left in flight")
            return
        self.fails.pop(cid, None)
        before = {"described": int(sw.get("before") or 0), "target": int(sw.get("target") or 0),
                  "goal": int(sw.get("goal") or 0), "complete": sw.get("complete", True),
                  "zero_sweeps": int(sw.get("zero_sweeps") or 0), "remaining": sw.get("remaining_before")}
        out = rd.sweep_outcome(before, after, progress, cap_after)
        ended = now()
        line = {"target": before["target"], "before": before["described"], "after": after["described"],
                "remaining_before": before["remaining"], "remaining_after": after["remaining"],
                "progress": _trim(progress), "cap_before": sw.get("cap_before") or {}, "cap_after": cap_after,
                "started": sw.get("started"), "ended": ended, "outcome": out}
        self.j.write("sweep", cid, **line)
        self.spent += rd.sweep_spend(line["cap_before"], cap_after)
        self.window["stops"].append([cid, rd.error_class(progress)])
        if out != "defer":
            made_progress = rd.sweep_made_progress(before["remaining"], after["remaining"],
                                                  before["described"], after["described"])
            self.zero[cid] = 0 if made_progress else self.zero.get(cid, 0) + 1
        say(f"swept {cid}: {before['described']} -> {after['described']} of {after['goal']} "
            f"in {round((ended - float(sw.get('started') or ended)) / 60, 1)} min, "
            f"spend {rd.dollars(rd.sweep_spend(line['cap_before'], cap_after))}: {out}")
        detail = None
        if out == "open:no_progress":
            pr = progress or {}
            stop = pr.get("stop") if isinstance(pr.get("stop"), dict) else {}
            detail = str(pr.get("error") or stop.get("message") or "") or None
        self.settle(cid, out, detail)

    def poll(self) -> bool:
        """Poll every running sweep once; True when at least one poll answered."""
        answered = False
        for cid in list(self.running):
            sw = self.running[cid]
            if sw.get("done_now"):
                answered = True
                self.finish(cid, {})
                continue
            if sw.get("repost"):   # a lost start that recounted at zero: its start again, same reservation
                answered = True
                self.post(cid, self.running.pop(cid), sw.get("cap_seen") or {})
                continue
            r = self.relay.call("GET", f"{VAULT}/describe-all/status", {"account_id": cid})
            if r.ok:
                answered = True
                if r.json.get("running"):
                    self.fails.pop(cid, None)
                    # per start: each sweep's `sw` is a new dict, so a Creator's next step starts its own clock
                    if time.monotonic() - sw.setdefault("seen_running", time.monotonic()) >= rd.DESCRIBE_WAIT_S:
                        # W30 F44: a stranded flag answers running forever; no sweep line, so the reservation stays
                        self.unsettled[cid] = "describe_still_running"
                        self.running.pop(cid)
                        say(f"sweep {cid}: still running after {rd.DESCRIBE_WAIT_S // 3600} h; left in flight")
                else:
                    self.finish(cid, r.json.get("progress") or {})
            else:
                answered = answered or rd.retry_class(r.status) == "open"   # a 4xx is the relay answering
                self.keep_or_unsettle(cid, self.running.pop(cid), "status", any_status=True)
        return answered

    def run(self) -> int:
        if self.st.get("ceiling_mc") != self.ceiling or self.st.get("eligible") is None:
            self.j.write("run_start", None, ceiling_mc=self.ceiling, eligible=self.eligible_n)
        say(f"describe: ceiling {rd.dollars(self.ceiling)}, spent {rd.dollars(self.spent)}, slots {self.slots}, "
            f"{len(self.pending)} to work, {len(self.running)} sweep(s) in flight")
        answered = True
        while True:
            if self.pausing is None:
                self.window["livez"] = self.relay.livez()
                self.window["errors_in_a_row"] = self.relay.errors_in_a_row
                self.pausing = rd.pause_reason(self.window)
            while self.pausing is None and self.pending and len(self.running) < self.slots:
                self.start(self.pending.pop(0))
                self.window["errors_in_a_row"] = self.relay.errors_in_a_row
                self.window["livez"] = None
                self.pausing = self.pausing or rd.pause_reason(self.window)
            if not self.running and (not self.retry or self.pausing):
                break
            if self.pausing in RELAY_SICK and not answered:
                break   # the running sweeps stay journaled in flight; the next run awaits them
            time.sleep(core.POLL_S)
            self.pending.extend(self.retry)   # a failed start comes back only after a poll interval
            self.retry.clear()
            answered = self.poll() if self.running else True
            self.window["errors_in_a_row"] = self.relay.errors_in_a_row
            if self.pausing is None and self.relay.errors_in_a_row >= rd.ERRORS_IN_A_ROW:
                self.pausing = "errors"
        if self.pausing or self.unsettled:
            # ASSUMPTION (rung 4): an unreadable sweep end pauses the run (exit 3, `recount_unreadable`): its spend
            # is unmeasured, so neither done nor the Fleet ceiling can be trusted until a re-run recounts it.
            reason = self.pausing or rd.unsettled_pause(self.unsettled.values())
            left = sorted(self.running) + sorted(self.unsettled)
            self.j.write("pause", None, reason=reason, running=left)
            say(f"paused: {reason}" + (f" ({len(left)} sweep(s) left in flight)" if left else ""))
            return EXIT_PAUSED
        left = sorted(self.deferred)
        if left:
            say(f"deferred until after 00:00 UTC: {len(left)} Creator(s)")
            return EXIT_DEFERRED
        say("describe: done")
        return EXIT_DONE


def describe_dry(ctx: Ctx, eligible_n: int) -> int:
    """What a live describe would do next per Creator, with the live run's target probe and reservations;
    starts nothing."""
    st = rd.resume(ctx.journal.read(), now=now())
    ceiling, spent = _ceiling(ctx, st, eligible_n), int(st["spent_mc"])
    flying, would = len(in_flight(st, ctx)), 0
    code = EXIT_DONE
    for a in ctx.scoped:
        cid = str(a.get("id"))
        c = st["creators"].get(cid) or {"state": "pending"}
        if c["state"] in ("done", "running") or (c["state"] == "open" and c.get("sticky")):
            say(f"describe {cid}: {c['state']} (journal)")
            continue
        if c["state"] == "deferred":
            say(f"describe {cid}: deferred until {iso(c['until'])} (journal)")
            code = code if code == EXIT_PAUSED else EXIT_DEFERRED
            continue
        s, p = ctx.summary(cid), ctx.plan(cid, rd.DESCRIBE_TARGET)
        if s is None or p is None:
            say(f"describe {cid}: unreadable")
            continue
        cap = cap_of(p)
        before = rd.before_of(s, p, int(c.get("zero_sweeps") or 0))
        out = rd.sweep_outcome(before, None, None, cap)
        if out == "continue":
            kind, t, rem = probe_target(ctx, cid, p, before, cap)
            if kind == "unreadable":
                say(f"describe {cid}: unreadable")
                continue
            if kind == "settle":
                out = t
        if out == "continue":
            running = min(flying + would, int(ctx.args.slots) - 1)   # the live run reserves its running sweeps
            if not rd.may_sweep(spent, running, ceiling, rd.STEP, ctx.args.item_mc):
                say(f"describe {cid}: would pause (ceiling {rd.dollars(ceiling)}, spent {rd.dollars(spent)}, "
                    f"{running} running sweep(s) reserved)")
                code = EXIT_PAUSED
                continue
            # No free slot: the live run starts it only after a sweep ahead ends, and only if that sweep's real
            # spend still leaves the ceiling room (W30 F13), so the line says it is conditional.
            queued = flying + would >= int(ctx.args.slots)
            would += 1
            say(f"describe {cid}: would "
                + ("queue for a slot, then sweep (if the sweeps ahead leave ceiling room) " if queued else "sweep ")
                + f"to target {t} (described {before['described']}, goal "
                f"{before['goal']}, estimate {rd.dollars(min(rd.STEP, rem) * ctx.args.item_mc)}) [dry run]")
        else:
            say(f"describe {cid}: would {out} [dry run]")
            if out == "defer" and code != EXIT_PAUSED:
                code = EXIT_DEFERRED
    return code


def mode_describe(ctx: Ctx, eligible_n: int) -> int:
    if not ctx.live:
        return describe_dry(ctx, eligible_n)
    return Wave(ctx, eligible_n).run()


# ── report ──────────────────────────────────────────────────────────────────

def _spend(ctx: Ctx, cid: str, since: str) -> dict:
    r = ctx.relay.call("GET", "/admin/stats/grok-calls",
                       {"account_id": cid, "by": "purpose_model", "status": "all", "from": since})
    out: dict[str, int] = {}
    for row in (r.json or {}).get("rows", []) if r.ok else []:
        if row.get("purpose") in rd.DESCRIBE_PURPOSES:
            prov = str(row.get("provider") or "unknown")
            out[prov] = out.get(prov, 0) + int(row.get("cost_millicents") or 0)
    return out


def mode_report(ctx: Ctx, eligible_n: int) -> int:
    lines = ctx.journal.read()
    st = rd.resume(lines, now=now())
    tp = rd.throughput(st["sweeps"])
    first_before: dict[str, int] = {}
    for ln in lines:
        c = str(ln.get("creator"))
        if ln.get("kind") in ("sweep_start", "measure") and c not in first_before:
            v = ln.get("before") if ln.get("kind") == "sweep_start" else ln.get("described")
            if v is not None:
                first_before[c] = int(v)
    rows = []
    for a in ctx.scoped:
        cid = str(a.get("id"))
        s, p = ctx.summary(cid), ctx.plan(cid, rd.DESCRIBE_TARGET)
        cov = (p or {}).get("coverage") or {}
        mine = [sw for sw in st["sweeps"] if str(sw.get("creator")) == cid]
        state = rd.report_state(st["creators"].get(cid) or {"state": "pending"},
                                rd.before_of(s, p) if s is not None and p is not None else None)
        s = s or {}
        secs = sum(max(0.0, float(sw.get("ended") or 0) - float(sw.get("started") or 0)) for sw in mine)
        since = min((utc_day(float(sw.get("started") or 0)) for sw in mine), default=None)
        rows.append({"id": cid, "username": a.get("username"), "nickname": a.get("nickname") or a.get("name"),
                     "state": state, "complete": s.get("complete"), "describable": cov.get("describable"),
                     "described_before": first_before.get(cid, cov.get("described")),
                     "described_after": cov.get("described"), "terminal": cov.get("terminal"),
                     "spend": _spend(ctx, cid, since) if since else {},
                     "sweep_minutes": round(secs / 60, 1) if mine else None,
                     "items_per_min": tp["creators"].get(cid) if mine else None})
    for a, why in ctx.skipped:
        rows.append({"id": str(a.get("id")), "username": a.get("username"),
                     "nickname": a.get("nickname") or a.get("name"), "state": f"skip: {why}"})
    want_seq = set(ctx.args.sequence or [])
    entries = [e for (c, s), e in sorted(st["fills"].items()) if not want_seq or s in want_seq]
    fr = rd.fill_report(rows, entries)
    report = {"generated": iso(), "creators": fr["rows"], "sequences": fr["sequences"], "fill": fr["fill"],
              "run": {"added": tp["added"], "minutes": tp["minutes"], "items_per_min": tp["run"],
                      "spent_mc": st["spent_mc"], "ceiling_mc": st.get("ceiling_mc"), "eligible": eligible_n}}
    full = ctx.journal.path.parent / "rollout-report-full.md"
    full.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(rd.render(report))
    out = Path(ctx.args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rd.sanitise(report))
    ctx.journal.write("report", None, full=str(full), out=str(out))
    say(f"report: full {full} (host only), sanitised {out}")
    if ctx.args.sample:
        in_report = {str(r["id"]) for r in rows}
        sheet = rollout_fill.write_sample(ctx, [e for e in entries if e["creator"] in in_report],
                                          int(ctx.args.sample), int(ctx.args.seed))
        say(f"contact sheet: {sheet} (host only)")
    return EXIT_DONE


# ── CLI ─────────────────────────────────────────────────────────────────────

def _slots(v: str) -> int:
    n = int(v)
    if not 1 <= n <= 3:
        raise argparse.ArgumentTypeError("--slots is 1-3")
    return n


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="rollout.py", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Dry run (no --live): no product-state write. `plan` calls the read-only fill/plan route (a POST that "
               "writes nothing server-side) in every run; `apply` and `undo` POST fill/apply and fill/undo only "
               "with --live.\nExit: 0 done, 2 refused, 3 paused, 4 deferred (re-run after 00:00 UTC).")
    ap.add_argument("mode", choices=MODES)
    ap.add_argument("--relay", required=True, help="loopback relay URL, e.g. http://127.0.0.1:8000")
    ap.add_argument("--live", action="store_true", help="write product state (default: dry run)")
    ap.add_argument("--owner-session", action="store_true",
                    help="accept a non-Master session: you checked this login owns every Creator")
    ap.add_argument("--journal", default=str(DEFAULT_JOURNAL), help=f"default {DEFAULT_JOURNAL}")
    ap.add_argument("--creator", action="append", help="Creator id (repeatable)")
    ap.add_argument("--sequence", action="append",
                    help="Sequence name (repeatable; plan / apply / undo / report; describe-side modes ignore it)")
    ap.add_argument("--backup", default=None,
                    help="DB backup a live apply verifies first (under 6 h old, integrity ok); a Sequence whose rows "
                         "it does not hold is skipped")
    ap.add_argument("--sample", type=int, default=0, help="report: contact sheet of N seeded filled Sequences")
    ap.add_argument("--seed", type=int, default=0, help="report: seed for --sample (default 0)")
    ap.add_argument("--ceiling-cents", type=int, default=None,
                    help=f"Fleet ceiling (default {rd.CEILING_CENTS_PER_CREATOR} x Eligible Creators)")
    ap.add_argument("--item-mc", type=int, default=rd.ITEM_MC, help=f"per-item estimate (default {rd.ITEM_MC})")
    ap.add_argument("--slots", type=_slots, default=3, help="parallel sweeps, 1-3 (default 3)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="sanitised report path")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        relay = Relay(check_relay(args.relay))
        if args.sequence and args.mode in ("measure", "collect", "describe"):
            say("note: --sequence applies to plan / apply / undo / report; ignored here")
        sign_in(relay, owner_ok=args.owner_session)
        ctx = Ctx(args, relay, Journal(Path(args.journal).expanduser(), args.mode))
        eligible_n = read_roster(ctx)
        if args.mode == "measure":
            return mode_measure(ctx)
        if args.mode == "collect":
            return mode_collect(ctx)
        if args.mode == "describe":
            return mode_describe(ctx, eligible_n)
        if args.mode in ("plan", "apply", "undo"):
            return {"plan": rollout_fill.mode_plan, "apply": rollout_fill.mode_apply,
                    "undo": rollout_fill.mode_undo}[args.mode](ctx)
        return mode_report(ctx, eligible_n)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr, flush=True)
        return EXIT_REFUSED
    except Paused as e:
        print(f"paused: {e}", file=sys.stderr, flush=True)
        return EXIT_PAUSED


if __name__ == "__main__":
    sys.exit(main())
