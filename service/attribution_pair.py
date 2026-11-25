from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from html import unescape
from typing import Protocol, TypeVar

_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_WS_RE = re.compile(r"\s+")


# Pairing key: we store `\n`, OF echoes the same caption with <br /> around it, so byte equality never matched.
# Tags collapse to a space, not "": `foo<br/>bar` must not glue to `foobar`. Tag names start with a letter, else `u < 3 > ok` loses prose.
# Local, not shared with reply_mass_funnel._norm_body (it casefolds; import cycle): do not consolidate.
def _norm_body(body: str | None) -> str:
    if not body:
        return ""
    txt = unescape(_TAG_RE.sub(" ", body))
    txt = unicodedata.normalize("NFC", txt)
    return _WS_RE.sub(" ", txt).strip()


# inf when a side is missing: an unusable timestamp must lose the nearest match, not win it.
def _seconds_apart(a: datetime | None, b: datetime | None) -> float:
    if a is None or b is None:
        return float("inf")
    return abs((a - b).total_seconds())


class PairRow(Protocol):
    @property
    def body(self) -> str | None: ...
    @property
    def created_at(self) -> datetime | None: ...
    @property
    def message_id(self) -> int: ...
    @property
    def mass_run_id(self) -> int | None: ...


P = TypeVar("P", bound=PairRow)
R = TypeVar("R", bound=PairRow)


# Globally nearest-first: per-stub greedy lets an OLD stub claim a row belonging to a recent send.
# Past max_s the walk ends: else a stub whose real row never ingested adopts the same caption sent a month later and is deleted.
# A claim stands even if the caller refuses the pair: the next-nearest would fold into the wrong send.
def pair_placeholders(phs: list[P], reals: list[R], max_s: float) -> list[tuple[P, R]]:
    ph_by_key: dict[str, list[P]] = {}
    for p in phs:
        key = _norm_body(p.body)
        if key:
            ph_by_key.setdefault(key, []).append(p)
    if not ph_by_key:
        return []
    real_by_key: dict[str, list[R]] = {}
    for r in reals:
        key = _norm_body(r.body)
        if key in ph_by_key:
            real_by_key.setdefault(key, []).append(r)
    if not real_by_key:
        return []

    cands = sorted(
        ((_seconds_apart(r.created_at, ph.created_at), ph, r)
         for key, rs in real_by_key.items()
         for ph in ph_by_key[key]
         for r in rs),
        key=lambda t: t[0],
    )
    out: list[tuple[P, R]] = []
    claimed: set[int] = set()
    used: set[int] = set()
    for dist, ph, real in cands:
        if dist > max_s:
            break
        if real.message_id in claimed or ph.message_id in used:
            continue
        if real.mass_run_id is not None and (
                ph.mass_run_id is None or int(real.mass_run_id) != int(ph.mass_run_id)):
            continue
        claimed.add(real.message_id)
        used.add(ph.message_id)
        out.append((ph, real))
    return out


def adopt_windows(stamps: list[datetime], span: timedelta) -> list[tuple[datetime, datetime]]:
    ranges: list[list[datetime]] = []
    for t in sorted(stamps):
        lo, hi = t - span, t + span
        if ranges and lo <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    return [(lo, hi) for lo, hi in ranges]


# A manual BROADCAST (mass_run_id set) must not cool down its whole audience; keyed on who sent, never on the label.
def hard_yield(*, mass_run_id: int | None, sent_by: int | None,
               automation_id: int | None) -> bool:
    return (mass_run_id is None and sent_by is not None
            and automation_id is not None and sent_by != automation_id)


_DEFAULT_MANUAL_YIELD_S = 60


def manual_yield_s(cfg_json) -> int:
    if not cfg_json:
        return _DEFAULT_MANUAL_YIELD_S
    try:
        mins = (json.loads(cfg_json) or {}).get("manual_yield_minutes")
        if mins is not None:
            return max(0, int(float(mins) * 60))
    except Exception:
        pass
    return _DEFAULT_MANUAL_YIELD_S
