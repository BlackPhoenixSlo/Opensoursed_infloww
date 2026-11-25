from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Iterable, NamedTuple


class _Msg(NamedTuple):
    message_id: int
    direction: str
    text: str
    at: datetime | None
    is_tip: bool


# Anchor words stay the narrowest set: a loose one (`video` is in every PPV caption) drags the span across unrelated history.
_ORDER_ANCHOR_WORDS = ("custom", "voice note", "voicenote", "commission")

_ORDER_SPEC_WORDS = (
    "custom", "video", "vid", "clip", "record", "film", "commission",
    "minute", "minutes", "min", "mins", "long", "length",
    "wear", "wearing", "hat", "shirt", "shirtless", "naked", "outfit",
    "say", "name", "talk", "content", "details", "describe", "described",
)

# 45 days: longer than quiet stretches inside one live order (a 24-day silence mid-layaway), far shorter than 16 months between two orders.
_ORDER_GAP_DAYS = 45

# Tuned on live rows: a 6-day order is 32 lines whole; a 60-day layaway is 238 whole, 33 filtered.
_ORDER_MAX_FULL = 40

_BLAST_KEY_LEN = 120


def _norm(s: str) -> str:
    return " ".join(s.replace("’", "'").replace("‘", "'").replace("“", '"')
                    .replace("”", '"').lower().split())


def _whole_messages(quotes: list[str], fan_msgs: list[dict]) -> list[str]:
    # A quote not found in anything he sent is dropped: a line shown as "his words" must be his.
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
    # Our mass marketing is full of order words; a line sent to N fans is not this fan's order.
    return blast.get(text[:_BLAST_KEY_LEN], 0) > 1


def blast_counts(rows: Iterable[tuple[str | None, int]],
                 strip: Callable[[str], str]) -> dict[str, int]:
    # Summed onto the normalised key, never assigned: GROUP BY raw body yields several rows per stripped text; over-counting is the safe direction (only removes marketing lines).
    blast: dict[str, int] = {}
    for b, n in rows:
        key = strip(b or "").strip()[:_BLAST_KEY_LEN]
        blast[key] = blast.get(key, 0) + int(n)
    return blast


def order_span(msgs: list[_Msg], blast: dict[str, int]) -> dict[str, Any]:

    def _own_words(text: str, direction: str) -> bool:
        return not (direction == "out" and _is_blast(text, blast))

    # Inbound only: our per-fan AI nudges are unique per recipient, escape the blast filter, and once opened a span on words the fan never said.
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

    # Tips stay in: they show a LAYAWAY ($100 at a time against a $700 custom); words alone read as fully paid.
    span = [m for m in msgs[start:]
            if m.is_tip or (len(m.text) >= 12 and _own_words(m.text, m.direction))]

    # Word-boundary matching: spec words are short ("min", "say") and a substring test hits "reminded"/"says".
    truncated = False
    if len(span) > _ORDER_MAX_FULL:
        truncated = True
        pat = re.compile(r"\b(" + "|".join(_ORDER_SPEC_WORDS) + r")\b")
        span = [m for m in span if m.is_tip or pat.search(m.text.lower())]

    return {
        "opened_at": msgs[start].at.isoformat() if msgs[start].at else None,
        "truncated": truncated,
        "count": len(span),
        "lines": [{"message_id": m.message_id, "from_fan": m.direction == "in",
                   "is_tip": m.is_tip, "text": m.text,
                   "at": m.at.isoformat() if m.at else None}
                  for m in span],
    }


def is_his_line(m: dict) -> bool:
    return bool(m.get("from_fan") and not m.get("is_tip"))


def brief_msgs(span: list[dict], window: list[dict]) -> list[dict]:
    by_id = {int(m["message_id"]): m for m in span}
    for m in window:
        by_id.setdefault(int(m["message_id"]), m)
    return sorted(by_id.values(), key=lambda m: m.get("at") or "")


def brief_skip_reason(msgs: list[dict]) -> str | None:
    if not msgs:
        return "no stored messages around this tip"
    if not any(is_his_line(m) for m in msgs):
        return "he never said what he wanted in this window"
    return None
