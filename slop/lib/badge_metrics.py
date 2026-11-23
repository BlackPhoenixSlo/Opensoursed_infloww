from __future__ import annotations

import bisect
import math
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

UNREAD_ROUTE = "GET /api2/v2/chats"
_QUEUE_READ = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3}) .*?\bbadge_read account=(\S+) kind=queue\b", re.M)


@dataclass(frozen=True)
class Read:
    account: str
    start: float
    end: float
    pages: int


def lag(truth: list[tuple[float, object]], observed: list[tuple[float, object]], end: float) -> list[float]:
    """Per truth change: first time >= its t at which the tab shows that value or a later truth value
    (a later value counts only once it is truth), else `end - t`."""
    truth, observed = sorted(truth, key=lambda x: x[0]), sorted(observed, key=lambda x: x[0])
    okeys = [o[0] for o in observed]
    out = []
    for i, (t, _) in enumerate(truth):
        seen, j, k, tau, hit = set(), i, 0, t, None
        while True:
            while j < len(truth) and truth[j][0] <= tau:
                seen.add(truth[j][1])
                j += 1
            k = bisect.bisect_right(okeys, tau, lo=k)
            if k and observed[k - 1][1] in seen:
                hit = tau
                break
            tau = min(truth[j][0] if j < len(truth) else math.inf, okeys[k] if k < len(okeys) else math.inf)
            if tau == math.inf:
                break
        out.append((hit if hit is not None else end) - t)
    return out


def p95(xs: list[float]) -> float | None:
    """Nearest-rank 95th percentile, unrounded; None when empty."""
    if not xs:
        return None
    return sorted(xs)[math.ceil(0.95 * len(xs)) - 1]


def _unread_calls(calls: list[dict]) -> list[tuple[float, float, str, int]]:
    out = []
    for c in calls:
        q = parse_qs(c.get("query") or "")
        if c.get("route") == UNREAD_ROUTE and (q.get("filter") or [""])[0] == "unread":
            t0 = c["t0"] if c.get("t0") is not None else c["t"]
            out.append((t0, c["t"], str(c["account"]), int((q.get("offset") or ["0"])[0])))
    return out


def raw_attempts(calls: list[dict]) -> int:
    return len(_unread_calls(calls))


def group_reads(calls: list[dict]) -> list[Read]:
    reads: list[Read] = []
    open_: dict[str, int] = {}
    for t0, t, aid, offset in sorted(_unread_calls(calls), key=lambda c: c[0]):
        if offset > 0 and aid in open_:
            r = reads[open_[aid]]
            reads[open_[aid]] = Read(aid, r.start, max(r.end, t), r.pages + 1)
        else:
            open_[aid] = len(reads)
            reads.append(Read(aid, t0, t, 1))
    return reads


def window_reads(calls: list[dict]) -> list[tuple[float, float, str]]:
    """(start, end, Creator) of each page-0 chats window call (no `filter`, offset 0): one per window read."""
    out = []
    for c in calls:
        q = parse_qs(c.get("query") or "")
        if c.get("route") == UNREAD_ROUTE and "filter" not in q and (q.get("offset") or ["0"])[0] == "0":
            out.append((c["t0"] if c.get("t0") is not None else c["t"], c["t"], str(c["account"])))
    return sorted(out)


def stale_answers(answers: list[tuple[float, float, str, float]],
                  reads: list[tuple[float, float, str]]) -> tuple[int, list[tuple[float, float, str, float]]]:
    """`answers` (sent, answered, Creator, its fold's `as_of` in s): each judged against the newest window read of
    its Creator that started at or before it was sent; stale when its fold predates that read. -> (judged, stale)."""
    starts: dict[str, list[float]] = {}
    for t0, _t, aid in sorted(reads):
        starts.setdefault(aid, []).append(t0)
    judged, stale = 0, []
    for a in answers:
        xs = starts.get(a[2], [])
        i = bisect.bisect_right(xs, a[0])
        if not i:
            continue
        judged += 1
        if a[3] < xs[i - 1]:
            stale.append(a)
    return judged, stale


def dots(rows: dict[int, tuple[bool, bool]], events: list[tuple[float, int | None, bool]]) -> dict[int, bool]:
    """Per-fan unread dot over `rows` {fan: (unread, muted)} after `events` (t, fan or None for every fan, unread)
    in time order: unread and not Muted (FanRow's EdgeMarker)."""
    state = {f: u for f, (u, _m) in rows.items()}
    for _t, fan, u in sorted(events, key=lambda e: e[0]):
        for f in (list(state) if fan is None else [fan]):
            state[f] = u
    return {f: u and not rows.get(f, (False, False))[1] for f, u in state.items()}


def over_pages(reads: list[Read], max_pages: int = 2) -> list[Read]:
    return [r for r in reads if r.pages > max_pages]


def gap_ok(starts: list[float], min_gap: float) -> tuple[bool, float | None]:
    s = sorted(starts)
    worst = min((b - a for a, b in zip(s, s[1:])), default=None)
    return (worst is None or worst >= min_gap), worst


def single_flight_ok(spans: list[tuple[float, float]]) -> tuple[bool, list[tuple[tuple, tuple]]]:
    overlaps, holder = [], None
    for span in sorted(spans):
        if holder is not None and span[0] < holder[1]:
            overlaps.append((holder, span))
        if holder is None or span[1] > holder[1]:
            holder = span
    return not overlaps, overlaps


def per_hour(starts: list[float], cap: int) -> tuple[bool, int]:
    """Most starts in any half-open 3600 s window."""
    s = sorted(starts)
    rate = max((bisect.bisect_left(s, a + 3600) - i for i, a in enumerate(s)), default=0)
    return rate <= cap, rate


def cap_rates(reads: list[Read], queue: list[tuple[float, str]], cap: int) -> dict[str, tuple[bool, int]]:
    """Per Creator, `per_hour` over its Attribution read starts plus its `kind=queue` re-reads `(t, Creator)`."""
    starts: dict[str, list[float]] = {}
    for r in reads:
        starts.setdefault(r.account, []).append(r.start)
    for t, aid in queue:
        starts.setdefault(str(aid), []).append(t)
    return {aid: per_hour(xs, cap) for aid, xs in starts.items()}


def held_at(series: list[tuple[float, object]], t: float, default=None):
    """The value a time-sorted `(t, value)` series holds at `t` (its last at or before), else `default`."""
    i = bisect.bisect_right(series, t, key=lambda x: x[0])
    return series[i - 1][1] if i else default


def both_circles(red_fans, amber_fans) -> set:
    return set(red_fans) & set(amber_fans)


def raw_leak(served: list[tuple[float, str, int]], raw: list[tuple[float, str, int]],
             red: list[tuple[float, str, int]]) -> list[tuple[float, str, int]]:
    """Served numbers equal to OF's raw counter at an instant where raw != Red truth; unjudged where either is
    still unknown."""
    def by_aid(rows):
        out: dict[str, tuple[list, list]] = {}
        for t, aid, v in sorted(rows, key=lambda r: r[0]):
            keys, vals = out.setdefault(aid, ([], []))
            keys.append(t)
            vals.append(v)
        return out

    def at(series, t):
        i = bisect.bisect_right(series[0], t) if series else 0
        return series[1][i - 1] if i else None
    raws, reds = by_aid(raw), by_aid(red)
    leaks = []
    for t, aid, n in served:
        r, truth = at(raws.get(aid), t), at(reds.get(aid), t)
        if r is not None and truth is not None and r != truth and n == r:
            leaks.append((t, aid, n))
    return leaks


def relay_marks(reads: list[dict]) -> list[dict]:
    """Read-log entries a relay thread GET caused (badge_wire `via="relay_get"`: a first page without the Peek
    cursor, or `order=asc&offset=0`)."""
    return [r for r in reads if r.get("via") == "relay_get"]


def counter_moves(frames: list[dict], before: dict[str, int]) -> list[dict]:
    """Counter frames whose value differs from the Creator's raw counter before the window."""
    return [f for f in frames if f.get("kind") == "counter" and f.get("value") != before.get(f.get("account"))]


def queue_reads(text: str) -> list[tuple[float, str]]:
    """(epoch s, Creator) of every mass re-read relay.log logged (`badge_read ... kind=queue`, Phase F's window
    re-read after a finished mass; logged when it lands)."""
    return [(time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) + int(m.group(2)) / 1000, m.group(3))
            for m in _QUEUE_READ.finditer(text)]


def amber_gate(present: bool, require: bool, ok: bool | None = None) -> tuple[bool | None, str | None]:
    """A Phase F check's verdict (None = SKIP): F's amber field absent from the accounts answer -> SKIP, FAIL under
    `require_amber=1`; present -> `ok`, where an unjudged check FAILs under `require_amber=1` too (the runner counts
    SKIP as no failure, so a green F run must not hide one)."""
    if not present:
        why = "Phase F's amber field is absent from the accounts answer"
        return (False, why + " but require_amber=1") if require else (None, why)
    if ok is None and require:
        return False, "unjudged under require_amber=1"
    return ok, None
