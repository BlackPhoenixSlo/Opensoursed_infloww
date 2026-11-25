import _harness  # noqa: F401  (first: temp DB + sys.path)

import time

from of_session_registry import Life, Registry, Slot


class _Curl:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False

    def close(self):
        self.closed = True
        if self.fail:
            raise RuntimeError("close boom")


def _idle_slot(reg, curl):
    s = Slot(Life())
    s.curl = curl
    s.state = "IDLE"
    s.last = time.monotonic() - 10
    reg.add(s)
    return s


def _wait(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def case_sweeper_survives_close_failure():
    reg = Registry(age=0, interval=0.01)
    try:
        bad = _idle_slot(reg, _Curl(fail=True))
        assert _wait(lambda: bad.curl is None)
        assert reg.errors, "close failure recorded"
        good_curl = _Curl()
        _idle_slot(reg, good_curl)
        assert _wait(lambda: good_curl.closed), "sweeper stopped after one failure"
        assert reg.thread.is_alive()
    finally:
        reg.stop_event.set()
        reg.thread.join(2)



def case_drain_gives_up_at_its_deadline():
    reg = Registry(age=0, interval=0.01)
    try:
        stuck = Slot(Life())
        stuck.active = 1
        reg.add(stuck)
        t0 = time.monotonic()
        assert reg.drain(timeout=0.2) is False
        assert time.monotonic() - t0 < 2.0
        assert stuck.active == 1, "active owner left alone"
    finally:
        reg.stop_event.set()
        reg.thread.join(2)
    quiet = Registry(age=0, interval=0.01)
    try:
        quiet.add(Slot(Life()))
        assert quiet.drain(timeout=2.0) is True
    finally:
        quiet.stop_event.set()
        quiet.thread.join(2)


def case_drain_timeout_stops_the_sweeper():
    reg = Registry(age=0, interval=0.01)
    try:
        stuck = Slot(Life())
        stuck.active = 1
        reg.add(stuck)
        assert reg.drain(timeout=0.1) is False
        assert reg.stop_event.is_set(), "sweeper still running after a drain timeout"
        reg.thread.join(2)
        assert not reg.thread.is_alive()
    finally:
        reg.stop_event.set()
        reg.thread.join(2)


def case_sweeper_checks_stop_before_each_retirement():
    reg = Registry(age=0, interval=0.3)
    try:
        class _StopsSweeper(_Curl):
            def close(self):
                super().close()
                reg.stop_event.set()

        first, second = _StopsSweeper(), _Curl()
        _idle_slot(reg, first)
        _idle_slot(reg, second)
        assert _wait(lambda: first.closed)
        reg.thread.join(2)
        assert not second.closed, "sweeper retired a handle after the stop flag was set"
    finally:
        reg.stop_event.set()
        reg.thread.join(2)


def case_abandoned_drain_never_shuts_down():
    import threading
    reg = Registry(age=0, interval=60)
    gate = threading.Event()

    class _Session:
        drained = False

        def close(self):
            gate.wait(2)

        def drain(self, timeout=None):
            self.drained = True
    sess = _Session()
    reg.sessions.add(sess)
    idle = _Curl()
    _idle_slot(reg, idle)
    out = []
    t = threading.Thread(target=lambda: out.append(reg.drain(timeout=5)))
    try:
        t.start()
        time.sleep(0.05)
        reg.stop_event.set()
        gate.set()
        t.join(3)
        assert out == [False], out
        assert not sess.drained and not idle.closed, "abandoned drain ran shutdown() after the caller gave up"
    finally:
        gate.set()
        reg.stop_event.set()
        reg.thread.join(2)


_harness.run()
