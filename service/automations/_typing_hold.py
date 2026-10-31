"""Typing-speed delay + typing-indicator hold."""
from __future__ import annotations

import asyncio
import json
import logging

import run_slot
from db.engine import get_session
from db.models import AccountAiConfig

from .rhythm import INLINE_MAX_S
from ._knobs import test_mode

log = logging.getLogger("of-relay.automation.common")


# ── Human "typing speed" delay ───────────────────────────────────────
# Each bubble is held back for the time a real person would take to TYPE it, so
# replies don't pop instantly (and a 2-bubble reply has a believable gap). Speed
# is words-per-minute, configured per-account in webhook_config_json.typing_wpm
# (the "⚡ Instant reply" tab); default 38 wpm. Clamped so a long line can't hang.
_DEFAULT_TYPING_WPM = 38.0
_MAX_TYPING_DELAY_S = 60.0  # a single bubble never waits more than 1 min to "type"


def typing_delay_seconds(text: str, wpm: float) -> float:
    """How long it'd take to type `text` at `wpm` words/min (0 wpm → no delay)."""
    if not wpm or wpm <= 0:
        return 0.0
    words = len((text or "").split())
    return min(words / float(wpm) * 60.0, _MAX_TYPING_DELAY_S)


async def load_typing_wpm(account_id: str) -> float:
    """Per-account typing speed from webhook_config_json.typing_wpm (default 38).
    Read regardless of whether webhook dispatch is enabled — it's a send-pacing
    knob, not a dispatch gate. 0 disables the typing delay."""
    if test_mode():
        return 0.0  # no real sleeps in the test harness
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    if cfg is not None and cfg.webhook_config_json:
        try:
            d = json.loads(cfg.webhook_config_json) or {}
            if "typing_wpm" in d and d["typing_wpm"] is not None:
                return max(0.0, float(d["typing_wpm"]))
        except Exception:
            log.warning("bad typing_wpm account=%s", account_id, exc_info=True)
    return _DEFAULT_TYPING_WPM


# ── "...is typing" indicator (ON by default, opt-out per account) ─────
# When enabled, the typing-delay hold before each bubble ALSO emits OF's live
# typing frame to the fan, so they actually see the "...is typing" bubble during
# the wait (instead of the message just arriving late). Default ON for every
# account; opt OUT per-account with webhook_config_json.typing_indicator=false.
# Re-emit cadence matches OF's own (~2.5s) since the indicator auto-clears after
# a few seconds. Always False under CHATTERLY_TEST_MODE (no real frames in tests).
_TYPING_REEMIT_S = 2.5
_DEFAULT_TYPING_INDICATOR = True


async def load_typing_indicator(account_id: str) -> bool:
    """Per-account toggle for the live typing indicator (webhook_config_json.
    typing_indicator). Default ON; only an explicit `false` disables it.
    Absent/NULL key → ON. Parse-error → default. Test-mode → False."""
    if test_mode():
        return False
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, str(account_id))
    if cfg is not None and cfg.webhook_config_json:
        try:
            d = json.loads(cfg.webhook_config_json) or {}
            if "typing_indicator" in d and d["typing_indicator"] is not None:
                return bool(d["typing_indicator"])
        except Exception:
            log.warning("bad typing_indicator account=%s", account_id, exc_info=True)
    return _DEFAULT_TYPING_INDICATOR


async def _emit_typing_for(account_id: str, fan_id: int, seconds: float) -> None:
    """Sleep `seconds` with the live "...is typing" frame re-emitted every ~2.5s.
    Always safe — a missing live socket degrades to a plain sleep."""
    if seconds <= 0:
        return
    from of_ws import emit_typing  # local import: avoid a server↔automation cycle
    remaining = float(seconds)
    while remaining > 0:
        try:
            await emit_typing(account_id, int(fan_id))
        except Exception:
            log.debug("emit_typing failed account=%s fan=%s", account_id, fan_id,
                      exc_info=True)
        step = min(_TYPING_REEMIT_S, remaining)
        await asyncio.sleep(step)
        remaining -= step


async def hold_with_typing(account_id: str, fan_id: int, seconds: float,
                           *, typing_indicator: bool = False,
                           quiet_s: float = 0.0,
                           think_at_s: float = 0.0,
                           think_for_s: float = 0.0) -> None:
    """Wait `seconds` before sending a bubble, and decide what the fan sees while
    we do.

    ⚠️ INVARIANT: the time slept is ALWAYS `seconds`; the call can take longer
    by the wait to get the run's slot back after it (below). Those waits are
    bounded per RUN (all of them together within `rhythm.INLINE_MAX_S`), so a
    reply's holds plus its waits stay inside the 900 s fan lease. The three
    optional arguments only redistribute WHEN the typing frame is emitted inside
    the slept total — they never lengthen or shorten it. Every guard in the tree
    reads one number and must keep reading the same one: `rhythm.INLINE_MAX_S`,
    the 900s fan lease and the deferral boundary.

    Left at their defaults this function is byte-identical to what it always did —
    one sleep, or one continuously-emitting loop — so all 16 existing call sites
    are untouched.

    The phases, in order:
      `quiet_s`     leading slice with the indicator DARK. She has not started
                    typing: she is reading, thinking, or reaching for the emoji
                    tray. Today's code had no such phase, so the bar ran for the
                    entire latency including the part before she picked the phone
                    up — a perfectly reliable "the whole delay was typing" oracle.
      the typing phase (`seconds - quiet_s`), optionally broken ONCE by a silent
                    stall at `think_at_s` lasting `think_for_s`: she stopped
                    mid-sentence. Real people type, stop, and type again; a solid
                    unbroken bar on every bubble of every reply does not.

    See `automations/pacing.py` for who computes these numbers and why.

    The run's concurrency slot is handed back for a hold of 3 s or more
    (run_slot.released; the knob AUTOMATION_RELEASE_SLOT_MIN_HOLD_S is the floor
    and the kill switch): the hold is a pure wait, and the fan lease + the run's
    in-flight guard stay held, so only another (account, kind) can use the slot
    meanwhile. Taking it back comes before any fresh run; once the run's
    take-back waits would pass `rhythm.INLINE_MAX_S` in all, this raises
    `run_slot.SlotLost` AFTER the sleep and before anything is sent. The caller
    sends nothing more of the reply, records the bubbles that already landed
    (its "sent" path), then re-raises. Never call it under a lock another run
    may wait for (run_slot.py)."""
    total = float(seconds or 0.0)
    # Even a zero hold goes through released(): a run that lost its slot must
    # raise SlotLost here instead of sending its next bubble.
    async with run_slot.released(total, budget_s=INLINE_MAX_S):
        if total <= 0:
            return
        await _hold_phases(account_id, fan_id, total, typing_indicator=typing_indicator,
                           quiet_s=quiet_s, think_at_s=think_at_s, think_for_s=think_for_s)


async def _hold_phases(account_id: str, fan_id: int, total: float, *, typing_indicator: bool,
                       quiet_s: float, think_at_s: float, think_for_s: float) -> None:
    quiet = min(max(0.0, float(quiet_s or 0.0)), total)
    typing = total - quiet
    if not typing_indicator:
        # Nothing to show ⇒ nothing to phase. One sleep, exactly as before.
        await asyncio.sleep(total)
        return
    if quiet > 0:
        await asyncio.sleep(quiet)
    gap_at = max(0.0, float(think_at_s or 0.0))
    gap_for = max(0.0, float(think_for_s or 0.0))
    if gap_for <= 0 or gap_at >= typing:
        await _emit_typing_for(account_id, fan_id, typing)
        return
    # Clamp the stall to what is left, so the three slices below always sum to
    # `typing` exactly — the invariant above is arithmetic, not a comment.
    gap_for = min(gap_for, typing - gap_at)
    await _emit_typing_for(account_id, fan_id, gap_at)
    await asyncio.sleep(gap_for)                       # she stopped mid-sentence
    await _emit_typing_for(account_id, fan_id, typing - gap_at - gap_for)
