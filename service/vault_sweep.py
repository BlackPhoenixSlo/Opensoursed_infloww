"""
vault_sweep.py — the one way a vault sweep walks a list of media ids.

`vault_ai_api` grew four of these: a `_X_running: set[str]`, a `_X_progress:
dict[str, dict]`, a 409 on double-start, and `GET /admin/vault-ai/<kind>/status`
returning `{running, progress}`. The CLIENT noticed first and collapsed its half
into one hook — `app/hooks/useVaultSweep.ts` opens by saying "The server runs
several of these and three are literally the same object". The server never
followed, so `_run_describe_all` and `_run_flags_all` carried the same
semaphore → per-item → chunk → gather skeleton twice.

That cost real money on 2026-08-11: the per-item call was unguarded in BOTH, and
one item that RAISED (rather than returning a status) propagated out of the
gather and ended the whole pass — an operator re-pressing "Describe all" every
few minutes for an hour, ~47% of it stopped. Fixing it in two places would have
left the next fault class to be fixed in one and not the other, which is how the
two drifted in the first place (they disagreed about what `done` counts).

WHAT A `visit` MUST RETURN. A dict — the shape `_describe_one` / `_jev_and_flag`
return, plus the optional `extra` a visit that settles riders adds:

    ok               truthy ⇒ the item was processed. Anything else is a failure.
    status           "capped" ⇒ the day's budget is gone; the sweep STOPS. Every
                     other value is informational.
    detail           why it failed, for the operator. The FIRST one is kept.
    cost_millicents  optional; summed across the run.
    jev_cost_millicents  optional; the Jev pass's part of `cost_millicents`,
                     summed and published apart (only when non-zero).
    extra            optional list of results for OTHER items this visit also
                     settled (a duplicate copied from the item just described).
                     Each counts as one visited item; `extra_total` (a `run`
                     kwarg) is how many such riders `total` includes up front.

`settled` (a `run` kwarg) is results of items finished BEFORE the walk (free
copies made up front): counted into `total` and `done` from the first publish,
so a status poll reads one pass however its items were settled.

A `visit` that raises is a failure like any other — it does not end the sweep.
The ONE exception is `llm_client.LLMKeyError`: the key is missing or the
provider rejected it, so every remaining item would fail the same way and cost
a call to learn it. That stops the sweep like `capped`, and the payload the
owner is shown rides in the snapshot as `key_error`. Its sibling is `SweepStop`
(a server-side cause no retry fixes: NudeNet missing, Jev down), published as
`stop: {message, fix}`. And a BREAKER: `BREAK_AFTER` failures in a row with no
success between (item-intrinsic statuses, `NEUTRAL`, neither count nor reset)
stop the sweep with the streak's first error — the next every-item-fails cause
nobody typed yet (11-14: a wrong TypeSafe key failed 5336/5336 in silence).
The drawer prints both; `finished_at` dates the last pass so it can say when.
The reason it is counted rather than propagated is that the alternative was
measured and it was terrible: the item that raises writes no row, so it reads as
never-attempted forever, and the 49 other items in its chunk are abandoned
mid-flight. Pinned by `test_vault_ai_describe.case_one_exploding_item_does_not_
end_the_sweep`.

`done` COUNTS ITEMS VISITED, NOT ITEMS THAT SUCCEEDED. The two sweeps used to
disagree about this — describe counted visits, flags counted successes — while
the shared frontend rendered both as "done/total", so a flags pass that finished
with 13 failures parked at 487/500 forever. Visits is the answer that makes
"done == total" mean "this pass is over", which is the only question the counter
is ever asked. `failed` carries the rest.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from typing import Any, NamedTuple

from llm_client import LLMKeyError, key_error_payload

log = logging.getLogger("of-relay.vault_sweep")

# Items dispatched per `gather`. Bounded so a 2,000-item vault doesn't spawn
# 2,000 tasks at once; the semaphore bounds how many actually RUN.
CHUNK = 50
# Failures in a row (no success between) that stop a sweep: every item is failing the same way.
BREAK_AFTER = 25
# Statuses about the ITEM itself (a DRM clip, a deleted file, a kind the pass skips): neither a failure that
# counts toward the breaker nor a success that resets it — a vault can open with 25 DRM clips.
NEUTRAL = frozenset({"blocked_drm", "gone", "not_in_mirror", "not_flaggable"})


class SweepStop(Exception):
    """A cause no retry fixes and that is not an API key (NudeNet missing, Jev down): the sweep stops and
    publishes `stop` = `payload()`. `message` says what is wrong, `fix` what to do; no ids, no keys."""

    def __init__(self, message: str, fix: str) -> None:
        super().__init__(message)
        self.message, self.fix = message, fix

    def payload(self) -> dict[str, str]:
        return {"message": self.message, "fix": self.fix}


class SweepResult(NamedTuple):
    """What a finished sweep amounts to. The same fields the progress dict
    publishes, so a caller logging the outcome and a UI polling mid-run are
    reading one set of definitions."""

    total: int
    done: int          # VISITED — see the module docstring
    failed: int
    capped: bool
    cost_millicents: int
    error: str         # the first `detail` a failure carried
    key_error: dict | None = None  # key_error_payload of the key error that stopped it
    stop: dict | None = None       # SweepStop.payload() / the breaker's, when that stopped it


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
    first_error = ""
    key_error: dict | None = None
    stop: dict | None = None
    streak = 0            # failures in a row (the breaker)
    streak_error = ""     # the streak's first detail

    def _count(r: dict[str, Any]) -> None:
        nonlocal done, failed, cost, jev_cost, first_error
        if not r.get("ok"):
            failed += 1
            if not first_error and r.get("detail"):
                first_error = str(r["detail"])[:200]
        cost += int(r.get("cost_millicents") or 0)
        jev_cost += int(r.get("jev_cost_millicents") or 0)  # already inside `cost`
        done += 1

    for r in settled:
        _count(r)

    def _publish() -> None:
        into[key] = {"total": total, "done": done, "failed": failed,
                     "capped": capped, "cost_millicents": cost,
                     "error": first_error, "key_error": key_error, "stop": stop}
        if jev_cost:  # the Jev v8 pass's share (vault_jev), on its own cap row
            into[key]["jev_cost_millicents"] = jev_cost

    _publish()
    sem = asyncio.Semaphore(concurrency)

    async def _one(mid: int) -> None:
        nonlocal done, failed, cost, capped, first_error, key_error, stop, streak, streak_error
        async with (hold(mid) if hold else nullcontext()), sem, gate():  # hold first, then per-sweep + global
            if capped or key_error or stop:
                return
            try:
                res = await visit(mid)
            except LLMKeyError as e:  # the key, not the item — stop (see docstring)
                key_error = key_error_payload(e)
                first_error = first_error or key_error["message"]
                log.warning("%s: stopped on a key error kind=%s provider=%s",
                            label, e.kind, e.provider)
                failed += 1
                done += 1
                _publish()
                return
            except SweepStop as e:  # the server, not the item — stop
                stop = e.payload()
                first_error = first_error or e.message
                log.warning("%s: stopped: %s", label, e.message)
                failed += 1
                done += 1
                _publish()
                return
            except Exception as e:  # noqa: BLE001 — one bad item costs ONE item
                log.exception("%s: item raised media=%s", label, mid)
                res = {"ok": False, "status": "error",
                       "detail": f"{type(e).__name__}: {e}"[:200]}
            if res.get("status") == "capped":
                capped = True
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
        # `return_exceptions` is the backstop behind `_one`'s own guard: a bare
        # gather re-raises the first failure the instant it happens and abandons
        # the rest of the chunk as orphans. Nothing about one item should be able
        # to reach the caller.
        await asyncio.gather(*(_one(m) for m in ids[i:i + CHUNK]),
                             return_exceptions=True)
    _publish()
    into[key]["finished_at"] = datetime.now(timezone.utc).isoformat()
    return SweepResult(total, done, failed, capped, cost, first_error, key_error, stop)
