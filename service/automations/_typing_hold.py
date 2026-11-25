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


_DEFAULT_TYPING_WPM = 38.0
_MAX_TYPING_DELAY_S = 60.0


def typing_delay_seconds(text: str, wpm: float) -> float:
    if not wpm or wpm <= 0:
        return 0.0
    words = len((text or "").split())
    return min(words / float(wpm) * 60.0, _MAX_TYPING_DELAY_S)


async def load_typing_wpm(account_id: str) -> float:
    if test_mode():
        return 0.0
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


_TYPING_REEMIT_S = 2.5
_DEFAULT_TYPING_INDICATOR = True


async def load_typing_indicator(account_id: str) -> bool:
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
    if seconds <= 0:
        return
    from of_ws import emit_typing
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
                           think_for_s: float = 0.0,
                           cut=None) -> None:
    total = float(seconds or 0.0)
    async with run_slot.released(total, budget_s=INLINE_MAX_S):
        if total <= 0:
            return
        phases = _hold_phases(account_id, fan_id, total, typing_indicator=typing_indicator,
                              quiet_s=quiet_s, think_at_s=think_at_s, think_for_s=think_for_s)
        if cut is None:
            await phases
        else:
            await _until(phases, cut)


_CUT_POLL_S = 0.5


async def _until(phases, cut) -> None:
    task = asyncio.ensure_future(phases)
    try:
        while not task.done() and not cut():
            await asyncio.wait({task}, timeout=_CUT_POLL_S)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if not task.cancelled():
        task.result()


async def _hold_phases(account_id: str, fan_id: int, total: float, *, typing_indicator: bool,
                       quiet_s: float, think_at_s: float, think_for_s: float) -> None:
    quiet = min(max(0.0, float(quiet_s or 0.0)), total)
    typing = total - quiet
    if not typing_indicator:
        await asyncio.sleep(total)
        return
    if quiet > 0:
        await asyncio.sleep(quiet)
    gap_at = max(0.0, float(think_at_s or 0.0))
    gap_for = max(0.0, float(think_for_s or 0.0))
    if gap_for <= 0 or gap_at >= typing:
        await _emit_typing_for(account_id, fan_id, typing)
        return
    gap_for = min(gap_for, typing - gap_at)
    await _emit_typing_for(account_id, fan_id, gap_at)
    await asyncio.sleep(gap_for)
    await _emit_typing_for(account_id, fan_id, typing - gap_at - gap_for)
