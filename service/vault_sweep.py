from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import Any, NamedTuple

import vault_jev_rules
from llm_client import LLMKeyError, key_error_payload

log = logging.getLogger("of-relay.vault_sweep")

CHUNK = 50
# Consecutive failures that stop a sweep: every item is failing the same way (a wrong key once failed 5336/5336 silently).
BREAK_AFTER = 25
# Item-intrinsic statuses neither count toward the breaker nor reset it; a vault can open with 25 DRM clips.
NEUTRAL = frozenset({"blocked_drm", "gone", "not_in_mirror", "not_flaggable", vault_jev_rules.GAVE_UP,
                     vault_jev_rules.REJECTED,
                     vault_jev_rules.RETRY_WAIT, vault_jev_rules.JEV_CAPPED})


class SweepStop(Exception):

    def __init__(self, message: str, fix: str, *, jev_cost_millicents: int = 0) -> None:
        super().__init__(message)
        self.message, self.fix = message, fix
        self.jev_cost_millicents = jev_cost_millicents

    def payload(self) -> dict[str, str]:
        return {"message": self.message, "fix": self.fix}


class SweepResult(NamedTuple):

    total: int
    done: int
    failed: int
    capped: bool
    cost_millicents: int
    error: str
    key_error: dict | None = None
    stop: dict | None = None


async def run(
    ids: list[int],
    visit: Callable[[int], Awaitable[dict[str, Any]]],
    *,
    concurrency: int,
    gate: Callable[[], asyncio.Semaphore],
    into: dict[str, dict[str, Any]],
    key: str,
    label: str,
    extra_total: int = 0,
    settled: Sequence[dict[str, Any]] = (),
    hold: Callable[[int], AbstractAsyncContextManager[Any]] | None = None,
) -> SweepResult:
    """Visit every id, `concurrency` at a time, publishing progress as it goes.

    `gate` is called (not passed) so a process-wide semaphore can bind lazily to
    the running loop. `into[key]` is rewritten after every item — that dict is
    what the status endpoint serves, and it deliberately outlives the sweep so a
    UI arriving late still learns how the last pass ended.

    `hold(id)`, when given, is entered BEFORE both slots and held through the
    visit: a resource the item needs (a clip's `admission.JEV_VIDEO` slot) is
    waited for while holding nothing, so the wait idles no vision slot.
    """
    total = len(ids) + extra_total + len(settled)
    done = failed = cost = jev_cost = 0
    capped = False
    jev_capped = False
    first_error = ""
    key_error: dict | None = None
    stop: dict | None = None
    notice = ""
    streak = 0
    streak_error = ""

    def _count(r: dict[str, Any]) -> None:
        nonlocal done, failed, cost, jev_cost, first_error, jev_capped
        if not r.get("ok"):
            failed += 1
            jev_capped = jev_capped or r.get("status") == "jev_capped"
            if not first_error and r.get("detail"):
                first_error = str(r["detail"])[:200]
        cost += int(r.get("cost_millicents") or 0)
        jev_cost += int(r.get("jev_cost_millicents") or 0)
        done += 1

    for r in settled:
        _count(r)

    def _publish() -> None:
        into[key] = {"total": total, "done": done, "failed": failed,
                     "capped": capped, "jev_capped": jev_capped, "cost_millicents": cost,
                     "error": first_error, "key_error": key_error, "stop": stop}
        if jev_cost:
            into[key]["jev_cost_millicents"] = jev_cost
        if notice:
            into[key]["notice"] = notice

    _publish()
    sem = asyncio.Semaphore(concurrency)

    async def _one(mid: int) -> None:
        nonlocal done, failed, cost, capped, first_error, key_error, stop, streak, streak_error, notice
        async with (hold(mid) if hold else nullcontext()), sem, gate():
            if capped or key_error or stop:
                return
            try:
                res = await visit(mid)
            except LLMKeyError as e:
                key_error = key_error_payload(e)
                first_error = first_error or key_error["message"]
                log.warning("%s: stopped on a key error kind=%s provider=%s",
                            label, e.kind, e.provider)
                failed += 1
                done += 1
                _publish()
                return
            except SweepStop as e:
                stop = e.payload()
                log.warning("%s: stopped: %s", label, e.message)
                _count({"ok": False, "detail": e.message, "cost_millicents": e.jev_cost_millicents,
                        "jev_cost_millicents": e.jev_cost_millicents})
                _publish()
                return
            except Exception as e:  # noqa: BLE001 — one bad item costs ONE item
                log.exception("%s: item raised media=%s", label, mid)
                res = {"ok": False, "status": "error",
                       "detail": f"{type(e).__name__}: {e}"[:200]}
            if res.get("status") == "capped":
                capped = True
            if res.get("notice") and not notice:
                notice = str(res["notice"])[:200]
            if res.get("ok"):
                streak, streak_error = 0, ""
            elif res.get("status") not in NEUTRAL:
                streak += 1
                streak_error = streak_error or str(res.get("detail") or res.get("status") or "")[:200]
                if streak >= BREAK_AFTER and not stop:
                    stop = {"message": f"Stopped: {streak} items in a row failed.",
                            "fix": f"First error: {streak_error or 'unknown'}. Fix it, then press again."}
                    log.warning("%s: stopped by the breaker after %s failures: %s", label, streak, streak_error)
            for r in (res, *(res.get("extra") or ())):
                _count(r)
            _publish()

    for i in range(0, len(ids), CHUNK):
        if capped or key_error or stop:
            break
        await asyncio.gather(*(_one(m) for m in ids[i:i + CHUNK]),
                             return_exceptions=True)
    _publish()
    into[key]["finished_at"] = datetime.now(timezone.utc).isoformat()
    return SweepResult(total, done, failed, capped, cost, first_error, key_error, stop)
