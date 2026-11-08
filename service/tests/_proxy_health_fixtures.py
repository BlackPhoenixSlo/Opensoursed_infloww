"""service/tests/_proxy_health_fixtures.py — the proxy-health bench shared by test_proxy_health.py,
test_proxy_failover.py and test_proxy_probe.py: a temp registry (`_registry`: hu-1 + spare; `_pool`: three
Inflowwww pool proxies, Creators 1..6), the watcher inline on a fake clock with a scripted probe (`_Watch`),
the event recorder (`_Events`), and the state helpers (`_fail`, `_bad`, `_spread_refusals`).

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap `_harness` FIRST, then import this.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import events
import proxies
import proxy_health
import proxy_health_decide
import proxy_probe


def _registry() -> None:
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxyhealth_")) / "proxies.json"
    proxies.upsert({"label": "hu-1", "scheme": "http", "host": "198.51.100.1", "port": 8080,
                    "username": "u", "password": "p"})
    proxies.upsert({"label": "spare", "scheme": "http", "host": "198.51.100.2", "port": 8080})
    proxies.assign_account("hu-1", "101")
    proxies.assign_account("hu-1", "102")
    proxy_health._state.clear()
    proxy_health._watchers.clear()
    proxy_health._tele.clear()
    proxy_health.verify_pick = lambda p, **_: True   # a new binding's probe: answers unless a case scripts it


# The watcher's clock inside `_Watch`: a fake `_sleep` advances it, so the
# confirm's deadline loop sees its wait pass.
_CLOCK = [0.0]


def _advance(s: float) -> None:
    _CLOCK[0] += max(s, 0)


def _then(*steps):
    """A `_sleep` that runs steps[i] at its i-th wait (None: just returns).
    Wait 0 is the confirm's (CONFIRM_GAP_S after the first error), then the rechecks'."""
    it = iter(steps)

    def sleep(_s):
        _advance(_s)
        step = next(it, None)
        if step:
            step()
    return sleep


_REAL_VERIFY = proxy_health.verify_pick


# The watcher inline and without waits; the probe answers from a script
# (True = answers; True once it runs out) and is logged per label; a label in
# `dead` never answers and takes nothing from the script. `_Watch(False, False, True)`.
class _Watch:
    def __init__(self, *answers: bool, geo: dict[str, str] | None = None, dead: set[str] = frozenset()):
        self.answers, self.probed, self.slept, self.geo = list(answers), [], [], geo or {}
        self.dead = set(dead)

    def __enter__(self):
        self._real = (proxy_health._spawn, proxy_health._sleep, proxy_probe.probe, proxy_health._now,
                      proxy_probe.probe_of)
        proxy_health._spawn = lambda fn, name: fn()
        _CLOCK[0] = time.time()
        proxy_health._now = lambda: _CLOCK[0]

        def _sleep(s):
            self.slept.append(s)
            _advance(s)
        proxy_health._sleep = _sleep

        # The health probe (probe_of: no ip/geo, its real shape) answers from the script; the trace
        # (`note_trace`'s region, uncounted) always answers with `geo` and is logged apart.
        def _probe(p, timeout_s=15):
            self.probed.append(p["label"])
            ok = False if p["label"] in self.dead else (self.answers.pop(0) if self.answers else True)
            return ({"ok": True, "ttfb_ms": 80, "error": None}
                    if ok else {"ok": False, "ttfb_ms": None,
                                "error": "proxy_probe_failed: CONNECT tunnel failed, response 403", "refused": True})

        def _trace(p, timeout_s=15):
            self.traced.append(p["label"])
            return {"ok": True, "ip": "203.0.113.7", "geo": self.geo.get(p["label"], "HU"), "colo": "BUD",
                    "ttfb_ms": 80, "error": None}
        self.traced = []
        proxy_probe.probe_of, proxy_probe.probe = _probe, _trace
        return self

    def __exit__(self, *_):
        (proxy_health._spawn, proxy_health._sleep, proxy_probe.probe, proxy_health._now,
         proxy_probe.probe_of) = self._real


def _fail(label: str, n: int = proxy_health_decide.DOWN_AFTER) -> None:
    for _ in range(n):
        proxy_health.record(label, False, "CONNECT tunnel failed, response 403")


class _Events:
    def __enter__(self):
        self.seen, self._real = [], events.publish_state
        events.publish_state = lambda t, **kw: self.seen.append((t, kw))
        return self

    def __exit__(self, *_):
        events.publish_state = self._real


def _pool(n: int = 3, tier_break: int | None = None) -> list[str]:
    """Three Inflowwww pool proxies; Creators 1..6 spread two per proxy. `tier_break`: the env's
    POOL_TIER_BREAK before that proxy (the ones from it on are the failover's next tier)."""
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxyfail_")) / "proxies.json"
    items = [f"socks5://pool-{i}.invalid:{9000 + i}" for i in range(n)]
    if tier_break is not None:
        items.insert(tier_break, proxies.POOL_TIER_BREAK)
    proxies.sync_pool(",".join(items))
    labels = [p["label"] for p in proxies.pool_entries()]
    for i, aid in enumerate(("1", "2", "3", "4", "5", "6")):
        proxies.assign_account(labels[i % n], aid)
    proxy_health._state.clear()
    proxy_health._watchers.clear()
    proxy_health._tele.clear()
    proxy_health.verify_pick = _REAL_VERIFY   # probes go through _Watch's scripted proxy_probe.probe_of
    return labels


def _on(label: str) -> list[str]:
    return sorted(proxies._ids_on(proxies.get_by_label(label)))


def _bad(label: str, due: bool = False) -> None:
    proxy_health._state[label] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down",
                                  "rechecks_failed": proxy_health_decide.FAILOVER_AFTER_RECHECKS if due else 0}


def _spread_refusals(label: str, ok: int, refused: int, buckets: int = 3) -> None:
    """`ok` answers, then `refused` refusals spread over `buckets` tenths of the window (the clock moves)."""
    for _ in range(ok):
        proxy_health._sample(label, False)
    for i in range(refused):
        if i and i % max(refused // buckets, 1) == 0:
            _advance(proxy_health.window_s() / 10)
        proxy_health._sample(label, True)


