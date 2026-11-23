"""Fixtures hold no restricted registry, so `excluded_from_badges` decides on the row alone; no Unread set is held, so
`owe_reply` is the Relay's `amber_count` with that guard passing."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SERVICE = str(Path(__file__).resolve().parents[2] / "service")
if _SERVICE not in sys.path:
    sys.path.append(_SERVICE)

import unread_total_decide as decide  # noqa: E402


def roster_count(rows: list[dict[str, Any]], me: str) -> dict[str, int]:
    unread = 0
    for r in rows:
        fan = (r.get("withUser") or {}).get("id")
        if not decide.excluded_from_badges(fan, r, frozenset()) and decide.of_counts(r):
            unread += 1
    return {"unread": unread, "owe_reply": decide.amber_count(rows, me, frozenset(), None)}
