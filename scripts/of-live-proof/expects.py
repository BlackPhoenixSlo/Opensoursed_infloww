from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import parse_qs

from proof_core import READS, Proof, _api


class Park(Exception):
    pass


@dataclass(frozen=True)
class Expect:
    path: str
    query: Mapping
    rows: Callable


ORDER_PARK = "parked — needs ≥2 rows whose order the sort changes"


def expect_waits(proof: Proof) -> list:
    out = [(i, s[1], s[2]) for i, s in enumerate(proof.trigger or ()) if s[0] == "text" and isinstance(s[2], Expect)]
    st = proof.settled
    if st and st[0] == "text" and isinstance(st[2], Expect):
        out.append(("settled", st[1], st[2]))
    return out


SORT_KEYS = ("field", "sort")


def _expect_rows(exp: Expect, reply) -> list:
    return [str(r if r is not None else "").strip() for r in exp.rows(reply) or []]


def resolve_expects(waits, get) -> dict:
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
    out = []
    for e in window:
        if e.get("origin") != "driver" and e["method"] == "GET" and _api(e["path"]) == _api(exp.path):
            got = parse_qs(e.get("query") or "")
            out.append({k: got[k][-1] for k in SORT_KEYS if k in got})
    return out


def expect_problems(proof: Proof, window) -> list:
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
    sent = [e for e in window if not (e.get("origin") == "driver" and e["method"] in READS)]
    out = [f"parked ({reason}) after {len(sent)} request(s) beyond the driver's reads: "
           + ", ".join(f"{e['method']} {e['path']}" for e in sent[:5])] if sent else []
    if list(undo) != ["none"]:
        out.append(f"parked ({reason}) with closed undo rows: {list(undo)}")
    return out
