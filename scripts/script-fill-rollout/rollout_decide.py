from __future__ import annotations

import hashlib
import random
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

DESCRIBE_TARGET = 1000
STEP = 250
ITEM_MC = 20
CEILING_CENTS_PER_CREATOR = 200
MC_PER_CENT = 100
LIVEZ_SLOW_S = 2.0
ERRORS_IN_A_ROW = 3
RETRY_BUDGET = 3
COLLECT_PAUSE_BUDGET = 20
COLLECT_WAIT_S = 4 * 3600
DESCRIBE_WAIT_S = 2 * 3600
ZERO_SWEEPS_OPEN = 2
DAY_S = 86400
DESCRIBE_PURPOSES = frozenset({"describe_media", "describe_flags", "vault_jev_flags"})
STICKY_OPEN = frozenset({"no_progress"})
ROSTER_REASONS = ("watcher", "not_onlyfans", "no_session", "dead_session", "deactivated")
SIX_DIGITS = re.compile(r"\d{6,}")



def eligible(account: Mapping[str, Any]) -> tuple[bool, str | None]:
    if account.get("role") == "watcher" or account.get("watcher"):
        return False, "watcher"
    if account.get("platform") != "onlyfans":
        return False, "not_onlyfans"
    if not account.get("has_session"):
        return False, "no_session"
    if account.get("session_dead_at"):
        return False, "dead_session"
    if not account.get("is_active"):
        return False, "deactivated"
    return True, None


def roster(payload: Mapping[str, Any]) -> tuple[list[dict], list[tuple[dict, str]]]:
    ok: list[dict] = []
    skipped: list[tuple[dict, str]] = []
    for a in payload.get("accounts") or []:
        good, why = eligible(a)
        if good:
            ok.append(dict(a))
        else:
            skipped.append((dict(a), str(why)))
    for w in payload.get("watchers") or []:
        skipped.append((dict(w), "watcher"))
    return ok, skipped



def retry_class(status: int) -> str:
    return "retry" if status == 0 or status >= 500 else "open"


def before_of(summary: Mapping[str, Any], plan: Mapping[str, Any], zero_sweeps: int = 0) -> dict[str, Any]:
    cov = plan.get("coverage") or {}
    return {"described": int(cov.get("described") or 0), "goal": int(cov.get("goal") or 0),
            "complete": bool(summary.get("complete")), "jev": dict(plan.get("jev") or {}),
            "zero_sweeps": int(zero_sweeps)}


def next_target(described: int, goal: int) -> int:
    if goal <= 0:
        return 0
    return min((max(described, 0) // STEP + 1) * STEP, goal)


def _done(before: Mapping[str, Any], goal: int) -> str:
    if before.get("complete", True) or goal >= DESCRIBE_TARGET:
        return "done"
    return "open:mirror_incomplete"


def sweep_made_progress(remaining_before: int | None, remaining_after: int | None,
                        described_before: int, described_after: int) -> bool:
    if remaining_before is None or remaining_after is None:
        return described_after > described_before
    return remaining_after < remaining_before


def sweep_outcome(before: Mapping[str, Any], after: Mapping[str, Any] | None,
                  progress: Mapping[str, Any] | None, cap: Mapping[str, Any] | None) -> str:
    progress = progress or {}
    cap = cap or {}
    http = progress.get("http")
    if http == 424:
        return "open:key"
    if http == 429:
        return "defer"
    goal = int(before.get("goal") or 0)
    if after is None:
        if int(before.get("described") or 0) >= goal:
            return _done(before, goal)
        if cap.get("key_missing"):
            return "open:key"
        if (before.get("jev") or {}).get("ready") is False:
            return "open:jev_not_ready"
        if cap.get("capped"):
            return "defer"
        return "continue"
    if progress.get("key_error"):
        return "open:key"
    goal = int(after.get("goal", goal) or 0)
    got = int(after.get("described") or 0)
    if got >= goal:
        return _done(before, goal)
    jev_capped = progress.get("jev_capped") or "jev_capped" in str(progress.get("error") or "")
    if progress.get("capped") or (jev_capped and got < int(before.get("target") or 0)):
        return "defer"
    made_progress = sweep_made_progress(before.get("remaining"), after.get("remaining"),
                                        int(before.get("described") or 0), got)
    if not made_progress and int(before.get("zero_sweeps") or 0) + 1 >= ZERO_SWEEPS_OPEN:
        return "open:no_progress"
    return "continue"


def next_utc_midnight(now: float) -> float:
    return (int(now) // DAY_S + 1) * DAY_S



def sweep_spend(cap_before: Mapping[str, Any], cap_after: Mapping[str, Any]) -> int:
    b = int(cap_before.get("spent_millicents") or 0)
    a = int(cap_after.get("spent_millicents") or 0)
    if cap_before.get("day") == cap_after.get("day"):
        return max(0, a - b)
    return a + max(0, int(cap_before.get("cap_millicents") or 0) - b)


def run_spend(sweep_lines: Iterable[Mapping[str, Any]]) -> int:
    return sum(sweep_spend(ln.get("cap_before") or {}, ln.get("cap_after") or {})
               for ln in sweep_lines if ln.get("kind", "sweep") == "sweep")


def may_sweep(spent: int, running: int, ceiling: int, step: int = STEP, item_mc: int = ITEM_MC) -> bool:
    return spent + (running + 1) * step * item_mc <= ceiling



def error_class(progress: Mapping[str, Any] | None) -> str | None:
    p = progress or {}
    if not (p.get("stop") or p.get("aborted")):
        return None
    stop = p.get("stop") if isinstance(p.get("stop"), Mapping) else {}
    text = str(p.get("error") or stop.get("message") or "stopped")
    return re.sub(r"\d+", "#", text.split(":")[0] if p.get("aborted") else text)[:80]


UNSETTLED = ("recount_unreadable", "describe_still_running", "start_unanswered")


def unsettled_pause(codes: Iterable[str]) -> str:
    have = set(codes)
    return next(c for c in UNSETTLED if c in have)


def pause_reason(window: Mapping[str, Any]) -> str | None:
    lz = window.get("livez")
    if lz is not None:
        if lz.get("status") != 200:
            return "livez_down"
        if float(lz.get("seconds") or 0) > LIVEZ_SLOW_S:
            return "livez_slow"
    if int(window.get("errors_in_a_row") or 0) >= ERRORS_IN_A_ROW:
        return "errors"
    stops = list(window.get("stops") or [])
    if len(stops) >= 2:
        (c1, k1), (c2, k2) = stops[-2], stops[-1]
        if k1 and k1 == k2 and c1 != c2:
            return "same_error"
    jev = list(window.get("jev") or [])
    if len(jev) >= 2:
        (c1, r1), (c2, r2) = jev[-2], jev[-1]
        if r1 is False and r2 is False and c1 != c2:
            return "jev"
    return None



def _ipm(added: int, seconds: float) -> float:
    return round(added / (seconds / 60.0), 2) if seconds > 0 else 0.0


def throughput(sweep_lines: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    per: dict[str, list[float]] = {}
    spans: list[tuple[float, float]] = []
    total = 0
    for ln in sweep_lines:
        if ln.get("kind", "sweep") != "sweep":
            continue
        s, e = float(ln.get("started") or 0), float(ln.get("ended") or 0)
        added = max(0, int(ln.get("after") or 0) - int(ln.get("before") or 0))
        acc = per.setdefault(str(ln.get("creator")), [0, 0.0])
        acc[0] += added
        acc[1] += max(0.0, e - s)
        total += added
        if e > s:
            spans.append((s, e))
    union = 0.0
    cur_s = cur_e = None
    for s, e in sorted(spans):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                union += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        union += cur_e - cur_s
    return {"creators": {c: _ipm(int(a), sec) for c, (a, sec) in per.items()},
            "run": _ipm(total, union), "minutes": round(union / 60.0, 2), "added": total}



def resume(journal_lines: Iterable[Mapping[str, Any]], now: float | None = None) -> dict[str, Any]:
    journal_lines = list(journal_lines)
    creators: dict[str, dict[str, Any]] = {}
    sweeps: list[Mapping[str, Any]] = []
    ceiling = eligible_n = None

    def cr(c: Any) -> dict[str, Any]:
        return creators.setdefault(str(c), {"state": "pending", "zero_sweeps": 0})

    for ln in journal_lines:
        kind = ln.get("kind")
        if kind == "run_start":
            ceiling, eligible_n = ln.get("ceiling_mc"), ln.get("eligible")
        elif kind == "sweep_start":
            c = cr(ln.get("creator"))
            c.update(state="running", sweep={**ln, "lost_start": 0})
        elif kind in ("lost_start", "start_answer") and "sweep" in cr(ln.get("creator")):
            sw = cr(ln.get("creator"))["sweep"]
            if kind == "lost_start":
                sw["lost_start"] = ln.get("http")
            else:
                sw.pop("lost_start", None)
        elif kind == "sweep":
            c = cr(ln.get("creator"))
            c.pop("sweep", None)
            outcome = str(ln.get("outcome") or "continue")
            if outcome == "not_started":
                c["state"] = "pending"
                continue
            sweeps.append(ln)
            if outcome != "defer":
                made_progress = sweep_made_progress(ln.get("remaining_before"), ln.get("remaining_after"),
                                                    int(ln.get("before") or 0), int(ln.get("after") or 0))
                c["zero_sweeps"] = 0 if made_progress else c["zero_sweeps"] + 1
            c["state"] = "done" if outcome == "done" else "pending"
        elif kind in ("defer", "open") and "sweep" in cr(ln.get("creator")):
            continue
        elif kind == "defer":
            c = cr(ln.get("creator"))
            c.update(state="deferred", until=float(ln.get("until") or 0))
        elif kind == "open":
            c = cr(ln.get("creator"))
            reason = str(ln.get("reason") or "")
            c.update(state="open", reason=reason, sticky=reason in STICKY_OPEN)
    if now is not None:
        for c in creators.values():
            if c["state"] == "deferred" and c.get("until", 0) <= now:
                c["state"] = "pending"
    return {"creators": creators, "ceiling_mc": ceiling, "eligible": eligible_n,
            "spent_mc": run_spend(sweeps), "sweeps": sweeps, **fill_state(journal_lines)}


CHAT, FREE, PAID = "chat", "free_media", "paid_media"
MIN_PRICE_CENTS, MAX_PRICE_CENTS = 300, 20000
NON_BLOCKING = ("gap", "kept_existing", "kept_unpriced", "removed_media", "free_unfilled", "no_video", "ask_unmet")
BACKUP_MAX_AGE_S = 6 * 3600
BACKUP_TABLES = ("saved_replies", "vault_items")
FILL_KINDS = frozenset({"plan", "stale", "apply_intent", "apply", "readback", "undo"})
NOT_ELIGIBLE = frozenset({"status:reserved", "status:no_paid_steps", "status:already_filled", "already_filled"})


def is_reserved(name: Any) -> bool:
    s = str(name or "")
    digits = s[2:]
    return s.startswith("FM") and digits.isascii() and digits.isdigit()


def ids(raw: Any) -> list[int]:
    out = []
    for m in raw if isinstance(raw, list) else []:
        mid = m.get("id") if isinstance(m, Mapping) else m
        try:
            out.append(int(mid))
        except (TypeError, ValueError):
            continue
    return out


def fill_fields(r: Mapping[str, Any]) -> tuple[list[int], list[int], int]:
    return ids(r.get("media")), ids(r.get("previews")), int(r.get("price_cents") or 0)


def row_of(r: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        rid = int(r.get("id"))
    except (TypeError, ValueError):
        return None
    return {"id": rid, "script_id": r.get("script_id"), "step": r.get("script_step"),
            "media": ids(r.get("media")), "previews": ids(r.get("previews")),
            "price_cents": int(round(float(r.get("price") or 0) * 100)),
            "removed_media_ids": ids(r.get("removed_media_ids"))}


def _by_id(rows: Any) -> dict[int, Mapping[str, Any]]:
    if isinstance(rows, Mapping):
        return {int(k): v for k, v in rows.items()}
    return {int(r["id"]): r for r in rows or [] if r is not None}


def write_set(plan: Mapping[str, Any], before_rows: Any) -> list[dict[str, Any]]:
    before = _by_id(before_rows)
    return [dict(o) for o in plan.get("options") or []
            if o.get("media") and not (before.get(int(o["id"])) or {}).get("media")]


def plan_flags(plan: Mapping[str, Any]) -> list[str]:
    got = set(plan.get("flags") or [])
    for o in plan.get("options") or []:
        got.update(o.get("flags") or [])
    return [f for f in NON_BLOCKING if f in got]


def apply_gate(plan: Mapping[str, Any], live_ids: Iterable[int]) -> list[str]:
    out: list[str] = []
    status = plan.get("status")
    if status != "ok":
        return [f"status:{status}"]
    if not plan.get("fingerprint"):
        out.append("no_fingerprint")
    live = {int(m) for m in live_ids}
    opts = list(plan.get("options") or [])
    written = [o for o in opts if not o.get("keep") and o.get("media")]
    if any(m not in live for o in written for m in (*ids(o.get("media")), *ids(o.get("previews")))):
        out.append("media_not_live")
    steps = [int(o.get("step") or 0) for o in opts]
    if any(b < a for a, b in zip(steps, steps[1:])):
        out.append("step_order")
    for o in written:
        pv = ids(o.get("previews"))
        if pv and (o.get("role") != PAID or any(p not in ids(o.get("media")) for p in pv)):
            out.append("preview_not_media")
            break
    paid = [o for o in opts if o.get("role") == PAID]
    priced = [o for o in paid if not (o.get("keep") and int(o.get("price_cents") or 0) == 0)]
    if any(not MIN_PRICE_CENTS <= int(o.get("price_cents") or 0) <= MAX_PRICE_CENTS for o in priced):
        out.append("price_unsendable")
    by_step: dict[int, list[int]] = {}
    for o in paid:
        if int(o.get("price_cents") or 0) > 0:
            by_step.setdefault(int(o.get("step") or 0), []).append(int(o["price_cents"]))
    order = sorted(by_step)
    if any(max(by_step[a]) > min(by_step[b]) for a, b in zip(order, order[1:])):
        out.append("escalation")
    return out


def _paid_unpriced(o: Mapping[str, Any], before: Mapping[str, Any] | None) -> bool:
    return o.get("role") == PAID and int((before or {}).get("price_cents") or 0) == 0


def readback(plan: Mapping[str, Any], before_rows: Any, undo: Iterable[Mapping[str, Any]],
             rows_now: Any) -> list[str]:
    before, now = _by_id(before_rows), _by_id(rows_now)
    ws = write_set(plan, before)
    entries = {int(e["id"]): e for e in undo or []}
    opts = {int(o["id"]): o for o in plan.get("options") or []}
    out: list[str] = []
    if any(int(o["id"]) not in entries for o in ws):
        out.append("undo_short")
    bad = False
    for o in ws:
        r = now.get(int(o["id"]))
        if r is None or fill_fields(r) != fill_fields(o):
            bad = True
    for rid, e in entries.items():
        r = now.get(rid)
        if r is None or int(e.get("price_cents") or 0) != int(r.get("price_cents") or 0) \
                or bool(e.get("price_set")) != _paid_unpriced(opts.get(rid) or {}, before.get(rid)):
            bad = True
    if bad:
        out.append("values")
    if any((now.get(int(o["id"])) or {}).get("removed_media_ids") for o in ws):
        out.append("removed_media")
    return out


def reconstruct_undo(plan: Mapping[str, Any], before_rows: Any,
                     rows_now: Any) -> tuple[list[dict[str, Any]] | None, bool]:
    before, now = _by_id(before_rows), _by_id(rows_now)
    ws = write_set(plan, before)
    rows = [now.get(int(o["id"])) for o in ws]
    if all(r is not None and not r.get("media") for r in rows):
        return None, False
    if any(r is None or fill_fields(r) != fill_fields(o) for o, r in zip(ws, rows)):
        return None, True
    return [{"id": int(o["id"]), "media_ids": list(r["media"]), "previews": list(r.get("previews") or []),
             "price_cents": int(r.get("price_cents") or 0),
             "price_set": _paid_unpriced(o, before.get(int(o["id"])))} for o, r in zip(ws, rows)], False


def backup_mismatch(expected: Iterable[Mapping[str, Any]], got: Mapping[int, Mapping[str, Any]]) -> str | None:
    for x in expected:
        row = x["row"]
        rid = int(row["id"])
        g = got.get(rid)
        if g is None:
            return f"row_missing:{rid}"
        if str(g.get("account_id")) != str(x["creator"]):
            return f"row_account:{rid}"
        if fill_fields(g) != fill_fields(row):
            return f"row_values:{rid}"
    return None


def fill_state(journal_lines: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    fills: dict[tuple[str, str], dict[str, Any]] = {}
    ops: dict[str, dict[str, Any]] = {}
    applies: list[dict[str, Any]] = []
    for i, ln in enumerate(journal_lines):
        kind = ln.get("kind")
        if kind not in FILL_KINDS or ln.get("sequence") is None:
            continue
        c, s = str(ln.get("creator")), str(ln.get("sequence"))
        e = fills.setdefault((c, s), {"creator": c, "sequence": s, "plan": None, "plan_i": -1, "ops": []})
        if kind == "plan":
            e["plan"], e["plan_i"] = dict(ln), i
        elif kind == "apply_intent":
            op = {"op": str(ln.get("op")), "creator": c, "sequence": s, "i": i, "intent": dict(ln), "apply": None,
                  "apply_i": None, "readback": None, "undo": None, "stale": None}
            ops[op["op"]] = op
            e["ops"].append(op)
        else:
            op = ops.get(str(ln.get("op")))
            if op is None or op[kind] is not None:
                continue
            op[kind] = dict(ln)
            if kind == "apply":
                op["apply_i"] = i
                applies.append(op)
    return {"fills": fills, "applies": applies}


def filled(op: Mapping[str, Any]) -> bool:
    ap = op.get("apply") or {}
    return ap.get("status") == "ok" and bool(ap.get("undo"))


def claimed(op: Mapping[str, Any]) -> bool:
    return (op.get("apply") or {}).get("status") == "ok"


def orphan(op: Mapping[str, Any]) -> bool:
    return op["apply"] is None and op["stale"] is None


def unread(op: Mapping[str, Any]) -> bool:
    return claimed(op) and op["undo"] is None and op["readback"] is None


def mismatched(op: Mapping[str, Any]) -> bool:
    return op["readback"] is not None and not op["readback"].get("ok")


def uncertain(op: Mapping[str, Any]) -> bool:
    return (op.get("apply") or {}).get("status") == "uncertain"


def next_action(entry: Mapping[str, Any]) -> str:
    ops = list(entry.get("ops") or [])
    if any(orphan(op) for op in ops):
        return "reconcile"
    if any(unread(op) for op in ops):
        return "read_back"
    if is_reserved(entry.get("sequence")) or any((claimed(op) and op["undo"] is None) or uncertain(op)
                                                 or mismatched(op) for op in ops):
        return "none"
    p = entry.get("plan") or {}
    plan_i = int(entry.get("plan_i", -1))
    if p.get("status") == "ok" and p.get("gate") == [] and all(op["i"] < plan_i for op in ops):
        return "apply"
    return "none"


def fill_outcome(entry: Mapping[str, Any]) -> str:
    ops = list(entry.get("ops") or [])
    if any(mismatched(op) and op["undo"] is None for op in ops):
        return "readback_mismatch"
    wrote = [op for op in ops if filled(op) and op["undo"] is None]
    if any(op["readback"] is not None for op in wrote):
        return "filled"
    if wrote:
        return "unverified"
    if any(uncertain(op) for op in ops):
        return "uncertain"
    acted = [op for op in ops if op["i"] > int(entry.get("plan_i", -1))]
    if acted:
        op = acted[-1]
        if op["undo"] is not None:
            return "undone"
        if op["apply"] is None:
            return "stale" if op["stale"] else "in_flight"
        return str(op["apply"].get("status") or "unknown")
    p = entry.get("plan")
    if p is None:
        return "unplanned"
    gate = list(p.get("gate") or [])
    return gate[0] if gate else "not_applied"


def fill_counts(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"sequences": 0, "eligible": 0, "filled": 0, "skipped": Counter(), "flags": Counter(),
                           "mismatch": 0}
    for e in entries:
        out["sequences"] += 1
        oc = fill_outcome(e)
        if oc not in NOT_ELIGIBLE:
            out["eligible"] += 1
        if oc == "filled":
            out["filled"] += 1
        else:
            out["skipped"][oc] += 1
        out["flags"].update(((e.get("plan") or {}).get("flags")) or [])
        out["mismatch"] += sum(1 for op in e.get("ops") or [] if mismatched(op) and op["undo"] is None)
    out["skipped"], out["flags"] = dict(out["skipped"]), dict(out["flags"])
    return out


def fill_report(rows: Iterable[Mapping[str, Any]], entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    entries = list(entries)
    out_rows, at_goal, total = [], [0, 0], [0, 0, 0]
    for r in rows:
        r = dict(r)
        mine = [e for e in entries if e["creator"] == r["id"]]
        if mine:
            fc = r["fill"] = fill_counts(mine)
            total = [total[0] + fc["filled"], total[1] + fc["eligible"], total[2] + fc["mismatch"]]
            if r.get("state") == "done":
                at_goal = [at_goal[0] + fc["filled"], at_goal[1] + fc["eligible"]]
        out_rows.append(r)
    in_report = {str(r["id"]) for r in out_rows}
    seqs = [{"creator": e["creator"], "sequence": e["sequence"], "outcome": fill_outcome(e),
             "gate": list((e.get("plan") or {}).get("gate") or []),
             "flags": list((e.get("plan") or {}).get("flags") or [])}
            for e in entries if e["creator"] in in_report]
    return {"rows": out_rows, "sequences": seqs,
            "fill": {"rate_at_goal": fill_rate(*at_goal), "rate_all": fill_rate(total[0], total[1]),
                     "mismatch": total[2]}}


def fill_rate(filled_n: int, eligible_n: int) -> str:
    return f"{filled_n}/{eligible_n} ({round(100 * filled_n / eligible_n)} %)" if eligible_n else "n/a"


def sample(keys: Iterable[Any], n: int, seed: int) -> list[Any]:
    pool = sorted(keys)
    return random.Random(seed).sample(pool, min(max(0, n), len(pool)))



def report_state(journal_state: Mapping[str, Any], before: Mapping[str, Any] | None) -> str:
    state = journal_state.get("state")
    if state == "open":
        return f"open: {journal_state.get('reason')}"
    if state == "deferred":
        until = datetime.fromtimestamp(float(journal_state.get("until") or 0), timezone.utc)
        return f"open: deferred until {until.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    if state == "running":
        return "running"
    if before is None:
        return "unreadable"
    goal = int(before.get("goal") or 0)
    if int(before.get("described") or 0) >= goal:
        return _done(before, goal).replace(":", ": ")
    return "pending"


def dollars(mc: int | float | None) -> str:
    return f"${(mc or 0) / 10000:.2f}"


def labels(ids: Iterable[str]) -> dict[str, str]:
    order = sorted({str(i) for i in ids}, key=lambda i: hashlib.sha256(i.encode()).hexdigest())
    return {cid: f"C{n:02d}" for n, cid in enumerate(order, 1)}


def render(report: Mapping[str, Any], names: Mapping[str, str] | None = None) -> str:
    run = report.get("run") or {}
    fill = report.get("fill") or {}
    out = [f"# Script fill rollout report{' (sanitised)' if names is not None else ''}", "",
           f"Generated {report.get('generated', '')}.", "",
           f"Fill rate (Creators at their goal): {fill.get('rate_at_goal', 'n/a')}; all Creators: "
           f"{fill.get('rate_all', 'n/a')}; read-back mismatches {fill.get('mismatch', 0)}.", "",
           f"Run: described added {run.get('added', 0)}, sweep minutes {run.get('minutes', 0)}, "
           f"items/minute {run.get('items_per_min', 0)}, spend {dollars(run.get('spent_mc'))} of ceiling "
           f"{dollars(run.get('ceiling_mc'))}, Eligible Creators {run.get('eligible', 0)}.", "",
           "| Creator | State | Mirror complete | Describable | Described before | Described after | "
           "Terminal failures | Spend by provider | Sweep minutes | Items/minute | Sequences eligible | Filled | "
           "Skipped by reason | Flags | Read-back mismatches |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = list(report.get("creators") or [])
    if names is not None:
        rows.sort(key=lambda r: names.get(str(r.get("id")), "~"))
    for r in rows:
        cid = str(r.get("id"))
        who = names.get(cid, "C??") if names is not None else f"{cid} {r.get('username') or ''}".strip()
        spend = ", ".join(f"{p} {dollars(v)}" for p, v in sorted((r.get("spend") or {}).items())) or "-"
        comp = r.get("complete")
        fc = r.get("fill") or {}
        out.append(f"| {who} | {r.get('state', '')} | {'-' if comp is None else ('yes' if comp else 'no')} | "
                   f"{_n(r.get('describable'))} | {_n(r.get('described_before'))} | {_n(r.get('described_after'))} | "
                   f"{_n(r.get('terminal'))} | {spend} | {_n(r.get('sweep_minutes'))} | "
                   f"{_n(r.get('items_per_min'))} | {_n(fc.get('eligible'))} | {_n(fc.get('filled'))} | "
                   f"{_tally(fc.get('skipped'))} | {_tally(fc.get('flags'))} | {_n(fc.get('mismatch'))} |")
    out.append("")
    seqs = list(report.get("sequences") or [])
    if names is None and seqs:
        out += ["## Sequences", "", "| Creator | Sequence | Outcome | Gate | Flags |", "|---|---|---|---|---|"]
        for s in seqs:
            out.append(f"| {s.get('creator')} | {s.get('sequence')} | {s.get('outcome')} | "
                       f"{', '.join(s.get('gate') or []) or '-'} | {', '.join(s.get('flags') or []) or '-'} |")
        out.append("")
    return "\n".join(out)


def _tally(d: Mapping[str, int] | None) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted((d or {}).items())) or "-"


def _n(v: Any) -> str:
    return "-" if v is None else str(v)


def sanitise(report: Mapping[str, Any]) -> str:
    rows = list(report.get("creators") or [])
    names = labels(str(r.get("id")) for r in rows)
    text = render(report, names)
    secrets = set()
    for r in rows:
        for k in ("id", "username", "nickname", "name"):
            if r.get(k):
                secrets.add(str(r[k]))
        for s in r.get("sequences") or []:
            secrets.add(str(s))
    for s in report.get("sequences") or []:
        secrets.add(str(s.get("sequence")))
    for s in sorted(secrets, key=len, reverse=True):
        if len(s) >= 2:
            text = re.sub(rf"(?<!\w){re.escape(s)}(?!\w)", names.get(s, "[redacted]"), text)
    return SIX_DIGITS.sub("#", text)
