"""expects: run-time preconditions of a proof, read from OnlyFans before the page opens (tickets 60, 61). `Park` is
an unmet one; `Expect` a text wait's want read from OnlyFans's own sorted list, guarded by `resolve_expects`, and the
checks after the trigger (`expect_problems`, `park_problems`) on its wire window. Split out of proof_core.py, the Live
guard's pure policy, so that stays under 1000 lines; nothing here does I/O (`get` is the driver's Relay read).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import parse_qs

from proof_core import READS, Proof, _api


class Park(Exception):
    """tickets 60, 61: a precondition found unmet on OnlyFans's side before the trigger: the proof sent nothing and
    parks with this reason (report `parked`), neither passing nor failing."""


@dataclass(frozen=True)
class Expect:
    """ticket 61: a text wait's `want` read from OnlyFans at run time, in place of a fixed string: `rows(get(path,
    query))` lists a list's row texts in OnlyFans's order, and the wait is for the first. Resolved by
    `resolve_expects` through the same Relay `get` as `of_read`, in fake and live mode alike."""
    path: str
    query: Mapping
    rows: Callable   # (OnlyFans's JSON) -> [row text, ...] in OnlyFans's order


ORDER_PARK = "parked — needs ≥2 rows whose order the sort changes"


def expect_waits(proof: Proof) -> list:
    """(key, selector, Expect) for each text wait of `proof` whose want is an `Expect`, in run order: a trigger step
    keyed by its index, then `settled` keyed "settled"."""
    out = [(i, s[1], s[2]) for i, s in enumerate(proof.trigger or ()) if s[0] == "text" and isinstance(s[2], Expect)]
    st = proof.settled
    if st and st[0] == "text" and isinstance(st[2], Expect):
        out.append(("settled", st[1], st[2]))
    return out


SORT_KEYS = ("field", "sort")   # the query keys an Expect's read sorts by; its baseline read drops them


def _expect_rows(exp: Expect, reply) -> list:
    return [str(r if r is not None else "").strip() for r in exp.rows(reply) or []]


def resolve_expects(waits, get) -> dict:
    """{key: want} for `expect_waits`' waits, all read from OnlyFans before the page opens (a read proof changes nothing
    on OnlyFans's side, so the order cannot move before the wait). Guards a vacuous pass from OnlyFans's side alone,
    never from the app's page (a Mirror bug showing the target order already must not park green): each read needs two
    rows or more, the first wait's first row must differ from OnlyFans's unsorted first row (the same read without
    SORT_KEYS, what the page lists before any sort), and each later wait's from the previous wait's. Else
    `Park(ORDER_PARK...)`. `get(path, query)` is the driver's Relay read."""
    wants, prev = {}, None
    for n, (key, _sel, exp) in enumerate(waits):
        q = dict(exp.query)
        got = _expect_rows(exp, get(exp.path, q))
        if len(got) < 2:
            raise Park(f"{ORDER_PARK}: {exp.path} {q} read {len(got)} row(s)")
        if not got[0]:
            raise Park(f"{ORDER_PARK}: {exp.path} {q}'s first row has no text")
        if n == 0:
            base = _expect_rows(exp, get(exp.path, {k: v for k, v in q.items() if k not in SORT_KEYS}))
            prev = base[0] if base else None
            if got[0] == prev:
                raise Park(f"{ORDER_PARK}: {got[0]!r} is first in {exp.path} unsorted too")
        elif got[0] == prev:
            raise Park(f"{ORDER_PARK}: {got[0]!r} is first for the previous wait too ({exp.path} {q})")
        wants[key] = prev = got[0]
    return wants


def sent_queries(exp: Expect, window) -> list:
    """ticket 61: the SORT_KEYS of each app GET of `exp.path` in a wire window (the driver's own reads left out)."""
    out = []
    for e in window:
        if e.get("origin") != "driver" and e["method"] == "GET" and _api(e["path"]) == _api(exp.path):
            got = parse_qs(e.get("query") or "")
            out.append({k: got[k][-1] for k in SORT_KEYS if k in got})
    return out


def expect_problems(proof: Proof, window) -> list:
    """ticket 61: each Expect wait's sort reached OnlyFans: an app GET of its path in the window carried its SORT_KEYS
    (a Mirror that sorts one loaded page client-side shows the right first row, yet fails here); and the app's first
    GET of that path, at page load, carried none (the unsorted read `resolve_expects` guards against is what the page
    loads: a persisted or default sort, or a page already in the target order, fails here)."""
    out = []
    for _key, _sel, exp in expect_waits(proof):
        want = {k: str(exp.query[k]) for k in SORT_KEYS if k in exp.query}
        sent = sent_queries(exp, window)
        if want and want not in sent:
            out.append(f"the app sent no GET {exp.path} with {want}: the sort did not reach OnlyFans")
        if sent and sent[0]:
            out.append(f"the app's first GET {exp.path} carried {sent[0]} at page load: not the unsorted baseline")
    return list(dict.fromkeys(out))


def park_problems(reason: str, window, undo) -> list:
    """tickets 60, 61: a Park counts only when nothing beyond the driver's own reads left after the arm and no undo row
    closed; else it fails (a park must never hide a write or a closed row)."""
    sent = [e for e in window if not (e.get("origin") == "driver" and e["method"] in READS)]
    out = [f"parked ({reason}) after {len(sent)} request(s) beyond the driver's reads: "
           + ", ".join(f"{e['method']} {e['path']}" for e in sent[:5])] if sent else []
    if list(undo) != ["none"]:
        out.append(f"parked ({reason}) with closed undo rows: {list(undo)}")
    return out
