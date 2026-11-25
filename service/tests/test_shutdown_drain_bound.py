import _harness  # noqa: F401  (first: temp DB + sys.path)

import asyncio
import threading
import time

import of_session_registry
import server


class _StuckRegistry:

    def __init__(self):
        self.stop_event = threading.Event()
        self.release = threading.Event()

    def stop_admission(self):
        pass

    def snapshot(self):
        return []

    def drain(self, timeout=None):
        self.release.wait(4)
        return True


def case_blocked_drain_does_not_hold_the_persist_flush():
    reg = _StuckRegistry()
    flushed = []

    async def persist():
        flushed.append(time.monotonic())

    orig = (of_session_registry.Registry.instance, server._REGISTRY_DRAIN_S, server._stop_persist_worker)
    of_session_registry.Registry.instance = classmethod(lambda cls: reg)
    server._REGISTRY_DRAIN_S = 0.2
    server._stop_persist_worker = persist
    try:
        t0 = time.monotonic()
        asyncio.run(asyncio.wait_for(server._stop_event_pumps(), 8))
    finally:
        reg.release.set()
        (of_session_registry.Registry.instance, server._REGISTRY_DRAIN_S, server._stop_persist_worker) = orig
    assert flushed, "persist flush never ran"
    assert flushed[0] - t0 < 3.0, f"persist flush waited {flushed[0] - t0:.1f}s on a blocked drain"
    assert reg.stop_event.is_set(), "idle sweeper left running after the bounded wait gave up"


_harness.run()
