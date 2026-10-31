"""customs_decide.py — the customs queue's PURE order-anchor logic.

No DB, no llm_client, no service imports: `customs_api` reads the rows (and
strips their HTML) and calls these. Stdlib only, importable without side effects.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Iterable, NamedTuple


class _Msg(NamedTuple):
    """ONE stripped thread row, as the order scan reads it.

    A bare 5-tuple with the same fields was indexed positionally in six places
    (`m[4]` for is_tip, `m[2]` for the text, `m[1]` for the direction), which is
    unreadable at the call site and silently wrong if the SELECT's column order
    ever moves. The names cost one class and make both impossible."""
    message_id: int
    direction: str          # "in" = the fan, "out" = us
    text: str               # already `_strip_html`-ed and stripped
    at: datetime | None
    is_tip: bool


# ── THE ORDER LINES ──────────────────────────────────────────────────────────
#
# THE ANCHOR WORDS open an order. Deliberately the narrowest possible set — a
# word that only appears when somebody is talking about commissioned work. This
# is what decides WHERE the order starts, so a loose word here (`video`, say,
# which appears in every PPV caption we have ever sent) drags the span back
# across unrelated history.
_ORDER_ANCHOR_WORDS = ("custom", "voice note", "voicenote", "commission")

# THE SPEC WORDS keep a line when the span is too long to print whole. Wider
# than the anchors, because by this point the span is already bounded and the
# job is recall: these are the words a spec is written in — the length, the
# wardrobe, the thing to say.
_ORDER_SPEC_WORDS = (
    "custom", "video", "vid", "clip", "record", "film", "commission",
    "minute", "minutes", "min", "mins", "long", "length",
    "wear", "wearing", "hat", "shirt", "shirtless", "naked", "outfit",
    "say", "name", "talk", "content", "details", "describe", "described",
)

# A GAP THIS LONG ENDS AN ORDER. One live fan has a COMPLETED 2024 custom and a
# live 2026 one in the same thread; without this the span opens in November
# 2024 and the operator reads two years of two different jobs. 45 days is longer
# than the quiet stretches inside one live order (one ran 6 days, another had a
# 24-day silence mid-layaway) and far shorter than the 16 months between his
# two orders.
_ORDER_GAP_DAYS = 45

# Above this many lines the span is FILTERED to spec-bearing lines instead of
# printed whole. Tuned against both live rows: a fast order (6 days) prints
# whole at 32 lines, and a layaway (60 days of daily chat) is 238 lines whole
# and 33 filtered. Both land readable.
_ORDER_MAX_FULL = 40

# Prefix length `_is_blast` compares on; `blast_counts` keys on the same.
_BLAST_KEY_LEN = 120


def _norm(s: str) -> str:
    """Whitespace/quote-insensitive key for matching a quote to its message."""
    return " ".join(s.replace("’", "'").replace("‘", "'").replace("“", '"')
                    .replace("”", '"').lower().split())


def _whole_messages(quotes: list[str], fan_msgs: list[dict]) -> list[str]:
    """Swap each model quote for the FULL stored message it came from.

    The operator's rule is "whole message if it's that important", and a model
    told never to shorten still does. So the prompt is not the enforcement;
    this is. A quote that is not a substring of anything he sent is dropped —
    a line shown as "his words" must be his."""
    out: list[str] = []
    for q in quotes:
        nq = _norm(q).strip('."\' …')
        if not nq:
            continue
        hit = next((m["text"] for m in fan_msgs if nq in _norm(m["text"])), None)
        if hit and hit.strip() not in out:
            out.append(hit.strip())
    return out


def _is_blast(text: str, blast: dict[str, int]) -> bool:
    """Did we send this exact text to more than one fan?

    OUR MARKETING IS THE LOUDEST THING IN THE THREAD and it is full of the words
    an order is written in — "unlock it and you get everything, every set, every
    clip", sent to the whole roster. On the live rows this was most of what a
    keyword scan returned, which is precisely the "not clear enough" the operator
    named. A line that went to N fans is not this fan's order, whatever it says.

    Compared on a prefix because the same blast arrives with and without its
    `<br/>` variants, which strip to texts differing only in whitespace."""
    return blast.get(text[:_BLAST_KEY_LEN], 0) > 1


def blast_counts(rows: Iterable[tuple[str | None, int]],
                 strip: Callable[[str], str]) -> dict[str, int]:
    """`(raw body, distinct fans)` rows → distinct-fan count per `strip`-ed
    `[:_BLAST_KEY_LEN]` key, the table `_is_blast` reads.

    ⚠️ SUMMED ONTO THE NORMALISED KEY, NEVER ASSIGNED. `GROUP BY
    Message.body` groups on the RAW body, so one blast stored with and
    without its `<br/>`/`<p>` wrapper comes back as SEVERAL rows that strip
    to the same text. A dict comprehension collapses them by OVERWRITING —
    last row wins — so three variants each sent to one fan scored 1 apiece
    and `_is_blast`'s `> 1` let our own PPV copy through as the fan's own
    words. The prefix key unified them; the counting undid it.

    Summing distinct-fan counts across variants slightly over-counts a fan
    who received two of them. That is the SAFE direction here: this filter
    only ever REMOVES lines from the order span, so over-counting drops one
    more line of our marketing, while under-counting puts marketing in the
    work order the operator films from."""
    blast: dict[str, int] = {}
    for b, n in rows:
        key = strip(b or "").strip()[:_BLAST_KEY_LEN]
        blast[key] = blast.get(key, 0) + int(n)
    return blast


def order_span(msgs: list[_Msg], blast: dict[str, int]) -> dict[str, Any]:
    """`customs_order`'s answer from the stripped thread (`msgs`, oldest-first)
    and the `blast_counts` table: where the current order opens, its span, and
    the spec filter when it is too long to print whole."""

    def _own_words(text: str, direction: str) -> bool:
        """A line that is this fan's conversation, not our mass marketing."""
        return not (direction == "out" and _is_blast(text, blast))

    # ── 1. WHERE DOES THE CURRENT ORDER OPEN?
    # The earliest anchor line reachable from the newest one without crossing a
    # `_ORDER_GAP_DAYS` silence. Walking back from the NEWEST is what keeps a
    # finished older order out of a live one's span.
    # INBOUND ONLY. Our per-fan AI nudges ("<name>, still thinking about that
    # custom idea you pitched") are unique per recipient, so the blast filter
    # cannot catch them, and one of them opened a live span on a sentence the
    # fan never said. Only the fan can open an order.
    anchors = [i for i, m in enumerate(msgs)
               if not m.is_tip and m.direction == "in" and m.text
               and any(w in m.text.lower() for w in _ORDER_ANCHOR_WORDS)]
    if not anchors:
        return {"lines": [], "count": 0, "opened_at": None,
                "truncated": False, "reason": "no order talk found in this thread"}
    start = anchors[-1]
    for j in range(len(anchors) - 1, 0, -1):
        prev_at, cur_at = msgs[anchors[j - 1]].at, msgs[anchors[j]].at
        if prev_at and cur_at and (cur_at - prev_at).days > _ORDER_GAP_DAYS:
            break
        start = anchors[j - 1]

    # ── 2. THE SPAN, in order. Tips stay in: they are how the operator sees a
    # LAYAWAY — a live fan paid $100 at a time against a $700 custom, and a span
    # showing only words reads as though the job is fully paid.
    span = [m for m in msgs[start:]
            if m.is_tip or (len(m.text) >= 12 and _own_words(m.text, m.direction))]

    # ── 3. Print it whole when it is short enough to read; otherwise keep the
    # spec-bearing lines. WORD-BOUNDARY matching here, unlike the anchor scan:
    # the spec words are short ("min", "say", "hat") and a substring test makes
    # "min" match "reminded" and "say" match "says". The anchors are long enough
    # not to need it.
    truncated = False
    if len(span) > _ORDER_MAX_FULL:
        truncated = True
        pat = re.compile(r"\b(" + "|".join(_ORDER_SPEC_WORDS) + r")\b")
        span = [m for m in span if m.is_tip or pat.search(m.text.lower())]

    return {
        "opened_at": msgs[start].at.isoformat() if msgs[start].at else None,
        # true = the span was too long to print whole and only spec-bearing
        # lines survived, so the operator knows there is thread he is not seeing.
        "truncated": truncated,
        "count": len(span),
        "lines": [{"message_id": m.message_id, "from_fan": m.direction == "in",
                   "is_tip": m.is_tip, "text": m.text,
                   "at": m.at.isoformat() if m.at else None}
                  for m in span],
    }


def is_his_line(m: dict) -> bool:
    """A transcript row that is a line HE wrote (a tip is not a line)."""
    return bool(m.get("from_fan") and not m.get("is_tip"))


def brief_msgs(span: list[dict], window: list[dict]) -> list[dict]:
    """The brief's transcript rows: the whole-thread order `span` merged with
    the context `window` by message_id (the span's row wins), oldest-first by
    `at`."""
    by_id = {int(m["message_id"]): m for m in span}
    for m in window:
        by_id.setdefault(int(m["message_id"]), m)
    return sorted(by_id.values(), key=lambda m: m.get("at") or "")


def brief_skip_reason(msgs: list[dict]) -> str | None:
    """The brief's `ok: false` reason for `brief_msgs`' rows, or None to go on:
    nothing stored, or no line of his — the model would only guess the order."""
    if not msgs:
        return "no stored messages around this tip"
    if not any(is_his_line(m) for m in msgs):
        return "he never said what he wanted in this window"
    return None
