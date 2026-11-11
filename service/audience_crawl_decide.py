"""service/audience_crawl_decide.py — the pure rules of the Audience crawl
(docs/spec/phase-02-audience-crawl.md): its Knobs, the Backoff ladder, the resume
offset, the refusals, the outcome names, the coalescing rule of a round and (P2b) the
read order, the roster end, what makes two sends comparable, the completeness gate and
the skip after a failed verdict.
Stdlib only, no I/O; audience_crawl.py runs them.

A source is `"fans"`, `"following"` or `("list", <OF list id>)`. A round serves every
request queued before it started (the crawler takes its whole queue at once, so each
read begins after each served send's POST): `needs` says what one request reads,
`needers` the round's sources (each read once) with the requests needing each,
`coalesced` how many other requests of the round share a read with one.

Knobs (read only by `knobs()`, from env at call time; a malformed or non-positive
value warns and falls back to the default):

  AUDIENCE_CRAWL_MODE         paced   `paced` (audience_crawl) | `legacy` (today's inline,
                                      unpaced `audiences.resolve_recipients_blocking`)
  AUDIENCE_CRAWL_DEADLINE_S   900     from the send; a request past it is NULL, `deadline`
  AUDIENCE_CRAWL_429_FIRST_S  30      first wait of the 429 ladder
  AUDIENCE_CRAWL_429_MAX_S    300     its cap (OF's own ask is never capped)
  AUDIENCE_CRAWL_PAGE_TRIES   3       tries per page on a non-429, non-auth error
  AUDIENCE_CRAWL_MAX_PAGES    1000    this crawl's backstop (of_paging.MAX_PAGES unchanged)
  AUDIENCE_CRAWL_ROSTER_PAGE  50      fans / following page size (of_paging.ROSTER_PAGE)
  AUDIENCE_CRAWL_COMPLETE_MIN 1.0     the completeness gate: a crawled set under this share of OF's own count
                                      of the send (`complete`) is NULL, `incomplete`
  AUDIENCE_CRAWL_COMPLETE_MAX 1.15    over this share it is NULL, `no_count` (OF's count is no measure of it)
  AUDIENCE_CRAWL_REPROBE_S    86400   after an `incomplete` / `deadline` verdict, sends are `skipped_incomplete`
                                      (no read) until the verdict is this old; then one real crawl (`skips`)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

log = logging.getLogger("of-relay.audience_crawl_decide")

MODES = ("paced", "legacy")
# Request outcomes (the `audience_crawl_end` line's `outcome=`, also mass_runs.crawl_outcome). Only `recorded`
# stamps. `incomplete`: read to its end, but under COMPLETE_MIN of OF's count. `no_count`: read to its end, but
# OF's feed gave no count of the send to judge it (none, 0, the read failed, or over COMPLETE_MAX of it).
# `skipped_incomplete`: no read.
OUTCOMES = ("recorded", "online", "unknown_list", "truncated", "deadline", "dead_session", "error",
            "incomplete", "no_count", "skipped_incomplete")
# A crawl's verdict on whether the roster reads complete in time (what `skips` reads). A `truncated` / `error`
# / `dead_session` / `no_count` crawl says nothing about that (a broken exclude list reads no roster page), so it never
# masks an earlier `incomplete`.
VERDICTS = ("recorded", "incomplete", "deadline")
# A verdict that the roster cannot be read complete in time: the next sends skip the crawl until a re-probe.
SKIP_AFTER = ("incomplete", "deadline")
ROSTERS = ("fans", "following")


@dataclass(frozen=True)
class Knobs:
    mode: str = "paced"
    deadline_s: float = 900.0
    first_s: float = 30.0
    max_s: float = 300.0
    page_tries: int = 3
    max_pages: int = 1000
    roster_page: int = 50
    # 1.0: complete by OF's count. AE 11-11: recorded sets ran 1.00-1.074 of the send's finish total (n=196, none
    # in [0.95, 1.0)), partial ones <= 0.88; 0.95 would record a set 5 % short.
    complete_min: float = 1.0
    # 1.15: over it OF's count is no measure of the set (a gross undercount, e.g. not yet settled): no verdict.
    # Above the measured 1.074 max with room.
    complete_max: float = 1.15
    # 24 h: a partial Creator's ratio moved <= 0.01 across days (a roster-endpoint ceiling, not luck), so a
    # daily real crawl (~1 of ~24 sends) is enough to see it change.
    reprobe_s: float = 86400.0


_DEFAULT = Knobs()


def _num(env: Mapping[str, str], name: str, default, cast):
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        v = cast(str(raw).strip())
    except ValueError:
        v = None
    if v is None or v <= 0:
        log.warning("audience_crawl_bad_env name=%s value=%r — using default %s", name, raw, default)
        return default
    return v


def knobs(env: Mapping[str, str] | None = None) -> Knobs:
    """Every Audience crawl Knob, read now (`env`: os.environ by default)."""
    env = os.environ if env is None else env
    mode = str(env.get("AUDIENCE_CRAWL_MODE") or _DEFAULT.mode).strip().lower()
    if mode not in MODES:
        log.warning("audience_crawl_bad_env name=AUDIENCE_CRAWL_MODE value=%r — using default %s",
                    env.get("AUDIENCE_CRAWL_MODE"), _DEFAULT.mode)
        mode = _DEFAULT.mode
    return Knobs(
        mode=mode,
        deadline_s=_num(env, "AUDIENCE_CRAWL_DEADLINE_S", _DEFAULT.deadline_s, float),
        first_s=_num(env, "AUDIENCE_CRAWL_429_FIRST_S", _DEFAULT.first_s, float),
        max_s=_num(env, "AUDIENCE_CRAWL_429_MAX_S", _DEFAULT.max_s, float),
        page_tries=_num(env, "AUDIENCE_CRAWL_PAGE_TRIES", _DEFAULT.page_tries, int),
        max_pages=_num(env, "AUDIENCE_CRAWL_MAX_PAGES", _DEFAULT.max_pages, int),
        roster_page=_num(env, "AUDIENCE_CRAWL_ROSTER_PAGE", _DEFAULT.roster_page, int),
        complete_min=_num(env, "AUDIENCE_CRAWL_COMPLETE_MIN", _DEFAULT.complete_min, float),
        complete_max=_num(env, "AUDIENCE_CRAWL_COMPLETE_MAX", _DEFAULT.complete_max, float),
        reprobe_s=_num(env, "AUDIENCE_CRAWL_REPROBE_S", _DEFAULT.reprobe_s, float),
    )


def next_wait(attempt: int, asked: float | None, k: Knobs) -> float:
    """The wait after a 429 on ladder rung `attempt` (0-based): OF's ask when it is
    longer (uncapped), else first x 2^attempt capped at max."""
    rung = min(k.first_s * (2 ** max(0, attempt)), k.max_s)
    return max(float(asked), rung) if asked is not None else rung


def asked_wait(header: str | None, allow: float | None) -> float | None:
    """OF's asked wait, uncapped: its `Retry-After` header in seconds first, else
    `allow` (the body's "Please allow N seconds", of_pacing.allow_s), else None."""
    if header is not None:
        try:
            v = float(str(header).strip())
            if v >= 0:
                return v
        except ValueError:
            pass
    return allow


def resume_offset(offset: int, page: int) -> int:
    """Where a crawl resumes after a 429 at `offset`: one page back, never below 0."""
    return max(0, int(offset) - int(page))


def refusal(user_lists: Iterable | None, filters: dict | None, online_only: bool,
            excluded_user_lists: Iterable | None = ()) -> str | None:
    """A request answered with no read: `online` (an online or filtered audience is a
    moment, not a roster), `unknown_list` (a list name OF resolved to we cannot
    know: an include other than fans / following / a numeric id, or an exclude list
    that is not a numeric id), else None (crawl it)."""
    # Rung 1: the Composer passes exclude list names through unresolved
    # (mass_queue_api.py:303), and legacy resolve_recipients_blocking crawls them as
    # /lists/<name>/users, which fails its whole request: no name is resolved either way.
    if filters or online_only:
        return "online"
    for raw in user_lists or ():
        name = str(raw).strip().lower()
        if name not in ROSTERS and not name.isdigit():
            return "unknown_list"
    for raw in excluded_user_lists or ():
        if not str(raw).strip().isdigit():
            return "unknown_list"
    return None


def source(raw) -> Any:
    """A user_lists name as a source: `fans` / `following`, else `("list", id)`
    (`refusal` has already turned away any other name)."""
    name = str(raw).strip().lower()
    return name if name in ROSTERS else ("list", int(name))


def needs(user_lists: Iterable, excluded_user_lists: Iterable,
          verified: Mapping[int, Any]) -> tuple[tuple, tuple, tuple]:
    """One request's (include sources, exclude sources to read, reused list ids), each
    deduped in order. An exclude list in `verified` (the membership its send verified
    under `broadcast_lock`) is reused, never read; a verified id the send does not
    exclude is ignored."""
    inc = tuple(dict.fromkeys(source(x) for x in user_lists or ()))
    ex = [int(x) for x in excluded_user_lists or ()]
    reused = tuple(dict.fromkeys(x for x in ex if x in verified))
    exc = tuple(dict.fromkeys(("list", x) for x in ex if x not in verified))
    return inc, exc, reused


def audience_key(user_lists: Iterable | None, excluded_user_lists: Iterable | None = (),
                 included_users: Iterable | None = ()) -> tuple | None:
    """What makes two sends of one automation_kind comparable (a verdict `skips` reads): their include lists
    and their exclude lists, each normalized, deduped and sorted. None, comparable to nothing (never
    skipped): an audience with no roster (fans / following), or with explicit ids
    (`included_users`). Excluded ids are not part of it: each send resets its Auto_Exclude to its own guard."""
    def norm(xs):
        return tuple(sorted({str(x).strip().lower() for x in xs or ()}))
    inc = norm(user_lists)
    if any(u is not None for u in included_users or ()) or not set(inc) & set(ROSTERS):
        return None
    return inc, norm(excluded_user_lists)


def lists_first(by_src: Mapping[Any, list]) -> dict:
    """`needers`' map, every list (include or exclude) before the rosters, each kind in first-seen order: a
    broken exclude list (a page or two) fails its needers before any roster page (hundreds)."""
    return dict(sorted(by_src.items(), key=lambda kv: kv[0] in ROSTERS))


def complete(n: int, sent: int | None, k: Knobs) -> tuple[str, float | None]:
    """The completeness gate on a crawled set of `n` ids: (`recorded` | `incomplete` | `no_count`, ratio).
    `sent`: OF's own count of this send (the mass feed's sentCount, read once the roster reads ended); ratio =
    n / sent: under COMPLETE_MIN `incomplete`, over COMPLETE_MAX `no_count` (no measure), else `recorded`
    (complete by OF's count). No count (not in the feed, or 0): `no_count`, ratio None."""
    if not sent or sent <= 0:
        return "no_count", None
    ratio = n / sent
    if ratio > k.complete_max:
        return "no_count", ratio
    return ("recorded" if ratio >= k.complete_min else "incomplete"), ratio


def skips(last: str | None, age_s: float | None, k: Knobs) -> bool:
    """Skip this crawl? `last`: the newest comparable earlier send's verdict (VERDICTS), `age_s` how long ago
    that send started. Yes after `incomplete` / `deadline` younger than REPROBE_S."""
    return last in SKIP_AFTER and age_s is not None and age_s < k.reprobe_s


def needers(need: Mapping[Any, Iterable]) -> dict:
    """{source: [request, ...]} over a round's `need` {request: sources}: every source once
    (the union read once), first seen, with the requests needing it in round order."""
    out: dict = {}
    for r, srcs in need.items():
        for s in srcs:
            rs = out.setdefault(s, [])
            if r not in rs:
                rs.append(r)
    return out


def coalesced(r, by_src: Mapping[Any, Iterable]) -> int:
    """How many other requests of the round share at least one read with `r` (`by_src`:
    `needers`)."""
    # ASSUMPTION: `coalesced` = other requests sharing >= 1 source (spec gives the field, not its unit).
    return len({o for rs in by_src.values() if r in rs for o in rs} - {r})
