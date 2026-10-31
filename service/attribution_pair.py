"""Pure half of `attribution.py`: no DB, no I/O, importable anywhere.

  pair_placeholders(phs, reals, max_s)   which mass placeholder folds into which
                                         real OF row (adopt_thread_placeholders)
  adopt_windows(stamps, span)            the merged per-stub time ranges its read
                                         of candidate real rows covers
  hard_yield(mass_run_id, sent_by, automation_id)
                                         W7 manual stand-down for one outbound
                                         row? (write_outbound_attribution)
  manual_yield_s(cfg_json)               the per-account manual stand-down
                                         (_manual_yield_seconds)

`attribution.py` re-exports `_norm_body` / `_seconds_apart` (other modules import
them from there); their home is here so the pairing can be tested without a DB.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from html import unescape
from typing import Protocol, TypeVar

# Pairing key for placeholder ↔ real-row matching. NOT cosmetic and NOT the same
# question `_preview_text` answers: we store a caption with plain `\n`, OF echoes
# the SAME caption back with `<br />` around it, so a byte-equality key never
# matched a multi-line body and `adopt_thread_placeholders` returned 0 for every
# one of them (161k live stubs, 4,113 of them pairable once normalized).
#
# Tags collapse to a SPACE, not to "": OF sometimes swaps the newline for `<br/>`
# rather than wrapping it, and stripping to "" would glue `foo<br/>bar` into
# `foobar` while our own copy normalizes to `foo bar`. A space is right for both
# shapes because the whitespace collapse below folds the duplicate away.
#
# Deliberately LOCAL rather than imported from `automations/`:
# `welcome_chatter_for_info` already imports attribution, so reaching the other
# way closes an import cycle. `reply_mass_funnel._norm_body` is the same shape for
# the same reason but is NOT the same function — it casefolds and does not unescape
# or NFC-normalize. Do not consolidate them without measuring: casefolding here
# would let two sends differing only in case pair and delete one, and dropping the
# unescape there would change opener matching. Same idea, different contracts.
# `</?[A-Za-z]…>` and not `<[^>]+>`: a tag NAME starts with a letter, and the
# loose form ate real prose — "i want u < 3 tonight > ok" collapsed to "i want
# u ok". Worse, it did so ASYMMETRICALLY: our stored copy holds the raw `<`,
# OF echoes it escaped as `&lt;`, so the two sides of the SAME send normalized
# to different keys and the pair was missed.
_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_WS_RE = re.compile(r"\s+")


def _norm_body(body: str | None) -> str:
    """Body → pairing key, or "" for a body that must never pair.

    "" is a REFUSAL, not a key: `<photo>` / `<video>` (and any media-only send)
    strip to nothing, and folding all of them into one bucket would let an
    unrelated stub adopt an unrelated row. Every caller must skip an empty key.

    Tags are stripped BEFORE entities are unescaped, and that order is deliberate
    even though it is not the convergent one. A caption of ours holding a literal
    `i <3 u > all` loses that span while OF's escaped echo keeps it, so the pair is
    MISSED — today's duplicate survives, which is the status quo. Unescaping first
    would converge those two, but it also turns any escaped angle bracket in a
    fan-visible caption into a strippable tag, and this order is the one measured
    against all 4,113 pairable prod rows (0 ambiguous). A missed pair costs a
    duplicate; a wrong pair stamps the wrong run on a real send and deletes the
    evidence.
    """
    if not body:
        return ""
    txt = unescape(_TAG_RE.sub(" ", body))
    txt = unicodedata.normalize("NFC", txt)
    return _WS_RE.sub(" ", txt).strip()


def _seconds_apart(a: datetime | None, b: datetime | None) -> float:
    """|a - b| in seconds; `inf` when either side is missing, so a row with an
    unusable timestamp LOSES the nearest-match instead of winning it. (created_at
    is NOT NULL, but a row once reached prod holding '' — see db/models.py — and
    a corrupt cell must not silently become the best candidate.)"""
    if a is None or b is None:
        return float("inf")
    return abs((a - b).total_seconds())


class PairRow(Protocol):
    """What `pair_placeholders` reads off a row (a `db.models.Message` in prod)."""
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


def pair_placeholders(phs: list[P], reals: list[R], max_s: float) -> list[tuple[P, R]]:
    """Placeholders × real outbound rows of ONE thread → `[(ph, real), …]` to adopt,
    in the order the caller must apply them.

    Key: `_norm_body` (OF's `<br />` echo == our `\\n`); an empty key never pairs.
    GLOBALLY nearest-first, not placeholder-by-placeholder: one caption can go to
    the same fan twice (two runs, weeks apart) and there are usually more stubs
    than ingested rows, so letting each stub grab its own nearest lets an OLD stub
    claim a row that belongs to a recent one purely by iteration order. Every
    candidate pair is sorted by distance (stable: ties keep row order) and claimed
    greedily, so the result does not depend on row order.

    `max_s` is the bound: sorted nearest-first, so the first pair past it ends the
    walk (`inf`, an unusable timestamp on either side, is past it too). Without it
    a stub whose own real row never ingested claims the same caption sent a month
    later, stamps it with a month-old run and is deleted — unrecoverable.

    A real row absorbs at most one placeholder and a placeholder folds into at most
    one row. A real row already stamped by a DIFFERENT run was adopted on an earlier
    pass (adoption runs on every ingest of the thread); pairing it again would
    delete the second stub for nothing, so that pair is skipped WITHOUT claiming
    either side.

    Every returned pair has claimed both sides already. The caller may still refuse
    one (`attribution._repoint_transaction`'s ledger collision); the claim stands,
    and that is deliberate: everything either row still has coming is FARTHER
    away, so letting the contested row or the refused stub fall through to its
    next-nearest would fold it into the wrong send.
    """
    ph_by_key: dict[str, list[P]] = {}
    for p in phs:
        key = _norm_body(p.body)
        if key:                      # "" is a refusal — see _norm_body
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
    claimed: set[int] = set()   # real rows already given a placeholder
    used: set[int] = set()      # placeholders already given a real row
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
    """Placeholder send stamps → the `[t - span, t + span]` ranges around them,
    sorted and with overlapping (or touching) ranges merged, so a burst of stubs
    seconds apart is one read clause, not fifty, while a July stub and a September
    one stay two. Order of `stamps` does not matter; [] → []."""
    ranges: list[list[datetime]] = []
    for t in sorted(stamps):
        lo, hi = t - span, t + span
        if ranges and lo <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])
    return [(lo, hi) for lo, hi in ranges]


def hard_yield(*, mass_run_id: int | None, sent_by: int | None,
               automation_id: int | None) -> bool:
    """W7 HARD YIELD for one outbound row — manual chatter always wins: only a
    genuine 1:1 send by a human rests the fan. `sent_by` is AFTER the Automation
    fallback; `automation_id` is the sentinel's id, or None when its lookup failed.

    A manual BROADCAST (mass_run_id set) must not cool down the whole audience
    (they should reply); automation sends set their own cooldown post-send; an
    unknown sender (None) is excluded; a failed sentinel lookup skips the yield.
    `automation_kind` is deliberately not an input: the yield keys on WHO sent (a
    human id), never on which automation label the row carries. The mass sender
    tag is NOT decided here: `attribution._mass_sender_tag` owns that rule."""
    return (mass_run_id is None and sent_by is not None
            and automation_id is not None and sent_by != automation_id)


# Default stand-down after a human takes over a chat (the W7 hard-yield). 1 min;
# per-account override via account_ai_config.webhook_config_json.manual_yield_minutes.
_DEFAULT_MANUAL_YIELD_S = 60


def manual_yield_s(cfg_json) -> int:
    """`webhook_config_json` → manual-chatter stand-down in seconds.
    Absent / unreadable / no `manual_yield_minutes` / non-numeric → 60. 0 disables.
    `max(0, …)`: a NEGATIVE value clamps to 0, i.e. it also disables (it is not
    "bad → default"). Truncated to whole seconds, so under 1/60 min disables too."""
    if not cfg_json:
        return _DEFAULT_MANUAL_YIELD_S
    try:
        mins = (json.loads(cfg_json) or {}).get("manual_yield_minutes")
        if mins is not None:
            return max(0, int(float(mins) * 60))
    except Exception:
        pass
    return _DEFAULT_MANUAL_YIELD_S
