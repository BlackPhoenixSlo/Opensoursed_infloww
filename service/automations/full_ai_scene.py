from __future__ import annotations

import json
from datetime import datetime
from typing import Any

STAGES = ("opening", "building", "peak", "after")


def scene_next(prev: dict[str, Any] | None, on: bool, stage: str | None,
               heat: int) -> dict[str, Any] | None:
    if not on:
        return None
    jev = stage if stage in STAGES else None
    if not prev:
        return {"n": 1, "stage": jev or "opening", "heat": int(heat)}
    old = prev.get("stage") if prev.get("stage") in STAGES else "opening"
    if old == "after" and jev and jev != "after":
        return {"n": 1, "stage": jev, "heat": int(heat)}
    new = old if jev is None else max(old, jev, key=STAGES.index)
    return {"n": int(prev.get("n") or 0) + 1, "stage": new,
            "heat": max(int(prev.get("heat") or 0), int(heat))}


def scene_words(scene: dict[str, Any] | None) -> str:
    if not scene:
        return "none"
    return f"sexting for {scene['n']} of her messages so far, stage: {scene['stage']}"


def saved_scene(rows, now: datetime, gap_s: int) -> dict[str, Any] | None:
    if not rows or (now - rows[-1].created_at).total_seconds() > gap_s:
        return None
    try:
        reply = json.loads(rows[-1].reply_json or "{}")
    except (TypeError, ValueError):
        return None
    return (reply.get("scene") or None) if isinstance(reply, dict) else None
