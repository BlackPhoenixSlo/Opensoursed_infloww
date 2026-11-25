from __future__ import annotations

from typing import NamedTuple

from .fan_state import fan_state, set_fan_state

STATE_KEY = "_openers"

CLASSES = ("q", "tease")
SLOTS = {"q": ("q1", "q2", "q3"), "tease": ("tease1", "tease2", "tease3")}
ALL_SLOTS = tuple(s for cls in CLASSES for s in SLOTS[cls])
_SLOT_CLASS = {s: cls for cls in CLASSES for s in SLOTS[cls]}


class Opener(NamedTuple):
    cls: str
    slot: str
    text: str
    instruction: str


_Q_INSTRUCTION = (
    "- Ask him this, in your own words — keep the specific thing it refers to: {line}")
_T_INSTRUCTION = (
    "- Work this line in as a grounded flirty riff, reworded in your own voice — he "
    "just messaged you, so it is a reply, NOT an opener: {line}")


def _generation(profile) -> str:
    at = getattr(profile, "last_generated_at", None)
    return at.isoformat() if at is not None else ""


def _used(state, profile) -> set[str]:
    if not isinstance(state, dict) or state.get("gen") != _generation(profile):
        return set()
    used = state.get("used")
    return {u for u in used if u in ALL_SLOTS} if isinstance(used, list) else set()


def stocked(profile, cls: str) -> list[tuple[str, str]]:
    if profile is None:
        return []
    out: list[tuple[str, str]] = []
    for slot in SLOTS[cls]:
        value = getattr(profile, slot, None)
        if isinstance(value, str) and value.strip():
            out.append((slot, value.strip()))
    return out


def _next_opener(profile, state) -> Opener | None:
    used = _used(state, profile)
    for cls in CLASSES:
        for slot, text in stocked(profile, cls):
            if slot in used:
                continue
            tmpl = _Q_INSTRUCTION if cls == "q" else _T_INSTRUCTION
            return Opener(cls, slot, text, tmpl.format(line=text))
    return None


def mark_used(state, profile, slot: str) -> dict:
    if slot not in ALL_SLOTS:
        raise ValueError(f"unknown opener slot {slot!r}")
    out = dict(state) if isinstance(state, dict) else {}
    out["gen"] = _generation(profile)
    out["used"] = sorted(_used(state, profile) | {slot})
    done = out.get("classes_done")
    done = set(done) if isinstance(done, list) else set()
    out["classes_done"] = sorted(done | {_SLOT_CLASS[slot]})
    return out


def _pass_complete(state) -> bool:
    done = state.get("classes_done") if isinstance(state, dict) else None
    return set(done or ()) >= set(CLASSES)


def next_for(fan, profile) -> Opener | None:
    state = fan_state(fan, STATE_KEY)
    if _pass_complete(state):
        return None
    return _next_opener(profile, state)


def need_block(opener: Opener) -> str:
    return "YOUR GOAL THIS MESSAGE:\n" + opener.instruction


async def record_used(account_id: str, fan_id: int, fan, profile,
                      slot: str) -> None:
    await set_fan_state(account_id, fan_id, STATE_KEY,
                        mark_used(fan_state(fan, STATE_KEY), profile, slot))
