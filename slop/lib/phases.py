"""Run phases (CONTEXT.md): where a run's `seconds` went — startup, seeding, execution, teardown — on the monotonic
clock, from the post-gate start. Stdlib only. One phase is open at a time; switching charges the elapsed time to the
open one, so the four always add up to `elapsed()`. Seeding nests inside execution (overlapping seeds count once)."""
from __future__ import annotations

import contextlib
import time

now = time.monotonic  # tests swap in a controlled clock
KEYS = ("startup_s", "seeding_s", "execution_s", "teardown_s")


class RunPhases:
    def __init__(self) -> None:
        self.restart()

    def restart(self) -> None:
        """The run's start: after the gate (its wait is params.lock_wait_s, not a phase)."""
        self.t0 = self._since = now()
        self.secs = {"startup": 0.0, "seeding": 0.0, "execution": 0.0, "teardown": 0.0}
        self.cur: str | None = None  # None: no stack attempted (load error, gate refusal): every phase null
        self.reached: set[str] = set()
        self.seed_calls = self.seed_failed = self._seeding = 0
        self._resume: str | None = None  # the phase the outermost open seed interrupted
        self.stack = None  # its `teardown_s` (a failed start's own cleanup) and `waits`

    def elapsed(self) -> float:
        return now() - self.t0

    def enter(self, phase: str) -> None:
        t = now()
        if self.cur is not None:
            self.secs[self.cur] += t - self._since
        self.cur, self._since = phase, t
        self.reached.add(phase)

    @contextlib.contextmanager
    def seed(self):
        """One Ctx.build: its seconds go to seeding even when it raises (then counted in seed_failed)."""
        self.seed_calls += 1
        self._seeding += 1
        if self._seeding == 1:
            self._resume = self.cur
            self.enter("seeding")
        try:
            yield
        except BaseException:
            self.seed_failed += 1
            raise
        finally:
            self._seeding -= 1
            if self._seeding == 0 and self.cur == "seeding":  # a seed ending after teardown began leaves teardown
                self.enter(self._resume)

    def as_dict(self) -> dict:
        """metrics.json `run_phases`. A start that failed (still in startup) charges the stack's own partial-start
        cleanup (`Stack.teardown_s`) to teardown; phases never reached are null."""
        if self.cur is not None:
            self.enter(self.cur)  # charge the open phase up to now
        secs = dict(self.secs)
        if self.cur == "startup" and self.stack is not None and self.stack.teardown_s is not None:
            # the start failed or was cut short: no teardown was timed by the clock, the stack timed its own cleanup
            moved = min(secs["startup"], self.stack.teardown_s)
            secs["startup"] -= moved
            secs["teardown"] += moved
            self.reached.add("teardown")
        out = {f"{k}_s": (round(v, 3) if k in self.reached else None) for k, v in secs.items()}
        if "execution" in self.reached:
            out["seeding_s"] = round(secs["seeding"], 3)
        return {**out, "seed_calls": self.seed_calls, "seed_failed": self.seed_failed,
                "waits": [] if self.stack is None else list(self.stack.waits)}


def line(ph: dict, gate_wait_s=None) -> str:
    """summary.txt's one `run phases:` line."""
    def f(v):
        return "-" if v is None else f"{v:.1f}s"
    waits = ", ".join(f"{w['name']} {w['seconds']:.1f}s/{w['polls']}" for w in ph.get("waits") or [])
    return (f"run phases: startup {f(ph['startup_s'])} · seeding {f(ph['seeding_s'])} · execution "
            f"{f(ph['execution_s'])} · teardown {f(ph['teardown_s'])}; seeds {ph['seed_calls']} "
            f"({ph['seed_failed']} failed); waits (s/polls): {waits or '-'}; gate wait {f(gate_wait_s)}")


def timed(ph: dict | None) -> bool:
    """An attempt whose run_phases account for its run seconds (a run that never reached a stack has all four null)."""
    return ph is not None and any(ph.get(k) is not None for k in KEYS)


def add(a, b):
    """Two optional second counts: None only when both are."""
    return b if a is None else a if b is None else round(a + b, 3)


def merge(a: dict | None, b: dict | None) -> dict | None:
    """Two attempts' run_phases (nightly's FAIL and its re-run): seconds and counts summed, waits concatenated."""
    if a is None or b is None:
        return a or b
    return {**{k: add(a.get(k), b.get(k)) for k in KEYS},
            "seed_calls": a.get("seed_calls", 0) + b.get("seed_calls", 0),
            "seed_failed": a.get("seed_failed", 0) + b.get("seed_failed", 0),
            "waits": [*(a.get("waits") or []), *(b.get("waits") or [])]}

