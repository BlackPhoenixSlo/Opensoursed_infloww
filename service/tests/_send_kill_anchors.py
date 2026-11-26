from __future__ import annotations

import contextlib
import json
import sqlite3
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import _harness
import _send_kill as sk
import _send_kill_cell as cell
import _send_kill_chat
import _send_kill_http
import _send_kill_jobs
import _send_kill_markers

ANCHORED = ("mass_premade", "mass_job", "scheduled_send", "priority_mass", "lifecycle_initial", "lifecycle",
            "funnel", "full_ai_live", "full_ai_ppv", "send_welcome")
ONE_SHOT = ("scheduled_send", "mass_job", "mass_premade")
GAPS = ("autoreply", "welcome_chatter", "followup", "nudge", "purchase_followup")
_ALL = {d.kind: d for d in (*_send_kill_http.DRIVERS, *_send_kill_jobs.DRIVERS, *_send_kill_markers.DRIVERS,
                            *_send_kill_chat.DRIVERS)}
Check = cell.Check


class _WireHttp:

    def __init__(self, wire: sk.Wire):
        self.wire = wire
        self.sends: list[str | None] = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        import send_tripwire
        if not sk._is_send(method, url):
            return cell.Resp(200, {}, url)
        budget = send_tripwire.budget()
        self.sends.append(budget.op_id if budget else None)
        return cell.Resp(200, self.wire.hit(f"{method} {url.split('/api2/v2')[-1]}", json), url)

    def get(self, url, headers=None, timeout=None):
        return cell.Resp(200, {}, url)


def _real(of: sk.WireOF, http: _WireHttp):
    c = cell.client(http)
    c.account_id = of.account_id
    return c


@contextlib.contextmanager
def _real_sends(http: _WireHttp):
    def via(name):
        def send(self, *a, **kw):
            res = getattr(_real(self, http), name)(*a, **kw)
            if name == "send_message":
                self.sent.append({"fan_id": int(a[0]), "text": a[1] if len(a) > 1 else kw.get("text"), **kw})
            return res
        return send
    with contextlib.ExitStack() as stack:
        for name in ("send_message", "schedule_message", "schedule_mass_message", "send_mass_message",
                     "publish_schedule"):
            stack.enter_context(patch.object(sk.WireOF, name, via(name)))
        yield


def _repend(job: int) -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        c.execute("UPDATE scheduled_jobs SET status='pending', run_at=datetime('now','-1 minute') WHERE id=?", (job,))
        c.commit()


def ops(aid: str) -> list[tuple[str, str, str, int]]:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        try:
            return [tuple(r) for r in c.execute(
                "SELECT op_id, kind, state, attempts FROM send_ops WHERE account=? ORDER BY created_at, op_id",
                (aid,))]
        except sqlite3.OperationalError:
            return []


def _spy_outcomes(seen: list):
    import automation_executor as ax
    from automations import welcome_chatter_for_info as wcfi
    real_run, real_fold = ax.run_once, wcfi._fold

    async def run_once(*a, **kw):
        out = await real_run(*a, **kw)
        seen.append(out.get("reason") if isinstance(out, dict) else None)
        return out

    def fold(tally, skips, out):
        seen.append(out.kind)
        return real_fold(tally, skips, out)
    return patch.object(ax, "run_once", run_once), patch.object(wcfi, "_fold", fold)


async def run(kind: str, cut: str) -> dict:
    d = _ALL[kind]
    aid = f"sa_{kind}_{cut}"
    at_kill: dict = {}
    wire = sk.Wire(cut, lambda: at_kill.setdefault("ops", ops(aid)) is not None)
    http = _WireHttp(wire)
    seen: list = []
    refusals: list = []

    async def step(fn, probe_update: bool = False):
        spies = _spy_outcomes(seen)
        with contextlib.ExitStack() as stack:
            for s in (sk._install(ctx), _real_sends(http), *spies):
                stack.enter_context(s)
            if probe_update:
                stack.enter_context(sk._cut_after_update(wire, lambda: d.post_update(ctx)))
            try:
                return await sk._maybe(fn, ctx)
            except HTTPException as e:
                refusals.append(e.detail.get("error") if isinstance(e.detail, dict) else e.detail)
                return False

    with cell.cells(accounts=f"onlyfans:{aid}"):
        cell.restart()
        ctx = await d.setup(aid, wire)
        await step(d.first, probe_update=cut == "after_update" and callable(d.post_update))
        first = {"ops": ops(aid), "killed_at": wire.killed_at, "accepts": len(wire.accepts)}
        if cut == "accepted" and wire.killed_at == "accepted":
            at_kill["ops"] = first["ops"]
        cell.restart()
        await sk.restart(aid)
        restarted = ops(aid)
        sk.let_time_pass(aid)
        if cut == "rerun":
            _repend(ctx["job"])
            await step(d.first)
        else:
            await step(d.tick)
            if d.resend is not None:
                await step(d.resend)
    by_op = Counter(http.sends)
    return {"first": first, "at_kill": at_kill.get("ops"), "restarted": restarted, "final": ops(aid),
            "accepts": len(wire.accepts), "wire_sends": len(http.sends), "by_op": dict(by_op),
            "outcomes": seen, "refusals": refusals}


def _states(rows) -> list[str]:
    return [r[2] for r in rows or []]


def _ids(rows) -> set[str]:
    return {r[0] for r in rows or []}


def _all_sent_once(r: dict) -> bool:
    rows = r["final"]
    return bool(rows) and _states(rows) == ["sent"] * len(rows) and r["accepts"] == len(rows) \
        and all(row[3] == 1 for row in rows)


def _ok_anchored(kind: str, got: dict[str, dict]) -> list[Check]:
    clean, pre, acc, upd = (got[c] for c in ("clean", "pre_write", "accepted", "after_update"))
    one_op_each = all(None not in r["by_op"] and max(r["by_op"].values(), default=0) <= 1 for r in got.values())
    return [
        (f"{kind}: clean run = 1 accept + 1 sent row per part", _all_sent_once(clean), clean),
        (f"{kind}: kill after claim finds the anchored claim saved; rerun maps to it, 0 accepts",
         pre["first"]["killed_at"] == "pre_write" and _states(pre["at_kill"])[-1:] == ["claimed"]
         and "uncertain" in _states(pre["final"]) and "claimed" not in _states(pre["final"])
         and _ids(pre["final"]) == _ids(pre["at_kill"])
         and pre["accepts"] == _states(pre["at_kill"]).count("sent"), pre),
        (f"{kind}: kill after accept → uncertain, rerun replays nothing, ≤1 accept per op",
         acc["first"]["killed_at"] == "accepted" and _states(acc["at_kill"])[-1:] == ["claimed"]
         and "uncertain" in _states(acc["final"]) and "claimed" not in _states(acc["final"])
         and _ids(acc["final"]) == _ids(acc["at_kill"])
         and acc["accepts"] == _states(acc["at_kill"]).count("sent") + 1, acc),
        (f"{kind}: kill after the durable update → sent, rerun sends 0 more", _all_sent_once(upd), upd),
        (f"{kind}: every wire send carried its op, each op ≤1 accept", one_op_each,
         {c: r["by_op"] for c, r in got.items()}),
    ]


def _ok_gap(kind: str, r: dict) -> list[Check]:
    return [(f"{kind}: no anchor → refused no_anchor, 0 transport sends, no claim",
             r["accepts"] == 0 and r["wire_sends"] == 0 and not r["final"]
             and "no_anchor" in r["outcomes"] + r["refusals"], r)]


def _table_matches() -> list[Check]:
    import sys
    from pathlib import Path
    import send_ops
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import cell_features
    table = json.loads(cell_features.FEATURES.read_text())
    off = {k for f in table["features"].values() if f["state"] == "off" for k in f["send_kinds"]}
    return [("gap kinds = send_ops.NO_ANCHOR ⊆ Feature table ANCHORLESS, each listed off",
             set(GAPS) == send_ops.NO_ANCHOR and set(GAPS) <= set(cell_features.ANCHORLESS) <= off,
             {"no_anchor": sorted(send_ops.NO_ANCHOR), "anchorless": sorted(cell_features.ANCHORLESS),
              "off": sorted(off)})]


async def run_all(kinds=ANCHORED, gaps=GAPS) -> list[Check]:
    checks: list[Check] = []
    for kind in kinds:
        got = {cut: await run(kind, cut) for cut in ("clean", "pre_write", "accepted", "after_update")}
        checks += _ok_anchored(kind, got)
        if kind in ONE_SHOT:
            again = await run(kind, "rerun")
            checks.append((f"{kind}: finished job run again replays its saved anchor, 0 more accepts",
                           _all_sent_once(again) and again["wire_sends"] == 1, again))
    for kind in gaps:
        checks += _ok_gap(kind, await run(kind, "clean"))
    return checks + _table_matches()


class _Every:
    def __contains__(self, kind) -> bool:
        return True


def _mutant(name: str):
    import uuid
    import automation_executor as ax
    import send_ops
    from automations import welcome_chatter_for_info as wcfi
    real_op = send_ops._automated_op

    def fresh(account, kind, target, anchor, part, body):
        return real_op(account, kind, target, uuid.uuid4().hex, part, body)
    if name == "anchor_per_run":
        return cell._patches((send_ops, "_automated_op", fresh), (send_ops, "MANUAL", _Every()))
    if name == "unfenced":
        return cell._patches((send_ops, "MANUAL", _Every()))
    return cell._patches((send_ops, "NO_ANCHOR", frozenset()), (ax, "_UNANCHORED_KINDS", frozenset()),
                         (wcfi, "send_ops", SimpleNamespace(cells=lambda: False)))


MUTANTS = {
    "anchor_per_run": ("scheduled_send: finished job run again replays its saved anchor, 0 more accepts",
                       "send_welcome: kill after accept → uncertain, rerun replays nothing, ≤1 accept per op"),
    "gap_sends": tuple(f"{k}: no anchor → refused no_anchor, 0 transport sends, no claim" for k in GAPS),
}


def run_mutant(name: str) -> int:
    import asyncio
    if name not in MUTANTS:
        return 2
    kinds = ANCHORED if name == "anchor_per_run" else ()
    gaps = () if name == "anchor_per_run" else GAPS

    async def go():
        with _mutant(name):
            return await run_all(kinds, gaps)
    failed = cell.report(asyncio.run(go()))
    green = [c for c in MUTANTS[name] if c not in failed]
    print(f"--break {name}: {len(MUTANTS[name]) - len(green)}/{len(MUTANTS[name])} own checks red"
          + (f"; still green: {green}" if green else ""))
    return 0 if not green else 1
