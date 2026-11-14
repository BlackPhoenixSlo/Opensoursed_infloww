"""automations/full_ai_scene.py — Full AI Chat's saved sext scene, pure (test Mode).

The owner-ordered save state ("some save states for few messages", 2026-11-14): each test
row's `reply_json["scene"]` is `{"n", "stage", "heat"}` or None; `full_ai_test.fetch` folds
the newest into `TurnFacts.scene`. It feeds Jev's `scene` state (`scene_words`) and the
Writer's stage/heat floor only: a named ADR-0032 exception, never a Route input
(`full_ai_decide`). Config `sext_scene` gates every caller.

  - `scene_next(prev, on, stage, heat)`: the next saved state (rules on the function).
  - `scene_words(scene)`: the state as Jev reads it.
"""
from __future__ import annotations

from typing import Any

STAGES = ("opening", "building", "peak", "after")


def scene_next(prev: dict[str, Any] | None, on: bool, stage: str | None,
               heat: int) -> dict[str, Any] | None:
    """The scene after this Turn. `on`: the Turn ran the scene (Route sext, or sell_now while
    hot); not on -> None (scene over). `stage`: Jev's `scene_stage`, None on its default or
    tie (`choice_or_none`). n counts her scene messages; heat never drops below the scene's.
    Jev none/default keeps prev's stage (else opening); otherwise the later of prev's and
    Jev's, except prev `after` and Jev not `after`: a new scene (n 1, Jev's stage, this
    Turn's heat)."""
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
    """Jev's `scene` state: "none" or how long and how far it has gone."""
    if not scene:
        return "none"
    return f"sexting for {scene['n']} of her messages so far, stage: {scene['stage']}"
