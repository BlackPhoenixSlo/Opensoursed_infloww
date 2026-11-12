"""Process-wide idle-handle registry. Locks never span network I/O.

Slots survive handle replacement; immutable IDs and generations reject stale
retirement. The registry owns slots, not clients; finalizers mark orphan slots.
"""

import itertools
import threading
import time
import weakref

_IDS = itertools.count(1)


class Life:
    def __init__(self):
        self.id = next(_IDS)
        self.lock = threading.RLock()
        self.closed = False


class Slot:
    def __init__(self, life):
        self.id = next(_IDS)
        self.session_id = life.id
        self.life = life
        self.lock = threading.RLock()
        self.generation = 0
        self.curl = None
        self.state = "EMPTY"
        self.active = 0
        self.pins = 0
        self.last = None
        self.clean = True
        self.owner = None
        self.orphan = False
        self.retiring = 0


class BoundedEvents(list):
    def __init__(self, limit=4096):
        super().__init__()
        self.limit = limit
        self.dropped = 0
        self.append_lock = threading.Lock()

    def append(self, value):
        with self.append_lock:
            if len(self) == self.limit:
                del self[0]
                self.dropped += 1
            super().append(value)


class Registry:
    """One registry/sweeper per process. Strong slots, no strong Session/OFClient refs."""

    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, age=30, interval=0.2):
        self.age = age
        self.interval = interval
        self.lock = threading.Lock()
        self.slots = {}
        self.events = BoundedEvents()
        self.errors = BoundedEvents(16)
        self.sessions = weakref.WeakSet()
        self.streams = weakref.WeakSet()
        self.admission_lock = threading.RLock()
        self.accepting = True
        self.stop_event = threading.Event()
        self.hooks = {}
        self.thread = threading.Thread(
            target=self.run, name="managed-idle-sweeper", daemon=True
        )
        self.thread.start()

    def event(self, kind, s, **kw):
        self.events.append(
            dict(
                t=time.time(),
                mono=time.monotonic(),
                kind=kind,
                session=s.session_id,
                slot=s.id,
                generation=s.generation,
                state=s.state,
                active=s.active,
                pins=s.pins,
                thread=threading.get_ident(),
                native=threading.get_native_id(),
                **kw,
            )
        )

    def add(self, s):
        with self.lock:
            self.slots[s.id] = s
        self.event("register", s)

    def snapshot(self):
        with self.lock:
            return list(self.slots.values())

    def deregister(self, s):
        # Caller holds slot lock. No registry-to-slot lock nesting elsewhere.
        if (s.life.closed or s.orphan) and not (
            s.curl or s.active or s.pins or s.retiring
        ):
            with self.lock:
                if self.slots.pop(s.id, None) is not None:
                    self.event("deregister", s)

    def retire(self, s, expected=None, terminal=False):
        with s.lock:
            if expected is not None and expected != (s.session_id, s.id, s.generation):
                self.event("stale_rejected", s, expected=expected)
                return False
            self.deregister(s)
            if not s.curl or s.active or s.pins or not s.clean:
                return False
            if not terminal and (
                s.last is None or time.monotonic() - s.last < self.age
            ):
                return False
            old = s.curl
            generation = s.generation
            last = s.last
            s.retiring += 1
            s.curl = None
            s.state = "RETIRING"
            self.event(
                "detach",
                s,
                handle=getattr(old, "_trace_id", None),
                idle_s=None if last is None else time.monotonic() - last,
            )
        hook = self.hooks.get("detached")
        if hook:
            hook(s, generation)
        try:
            old.close()
        except BaseException as e:
            self.errors.append(repr(e))
            self.event("cleanup_failed", s, error=repr(e))
            raise
        finally:
            with s.lock:
                if s.generation == generation and s.state == "RETIRING":
                    s.state = "EMPTY"
                s.retiring -= 1
                self.event(
                    "cleanup_ack",
                    s,
                    retired_generation=generation,
                    handle=getattr(old, "_trace_id", None),
                    last_release=last,
                )
                self.deregister(s)
        return True

    def run(self):
        while not self.stop_event.wait(self.interval):
            for s in self.snapshot():
                try:
                    self.retire(s, terminal=s.life.closed or s.orphan)
                except BaseException:
                    self.stop_event.set()
                    break

    def orphan(self, slots):
        for s in slots:
            with s.lock:
                s.orphan = True

    def track_stream(self, stream):
        with self.lock:
            self.streams.add(stream)

    def forget_stream(self, stream):
        with self.lock:
            self.streams.discard(stream)

    def finish_completed_streams(self, session=None):
        # Never hold global/slot locks while a finalizer takes its state lock.
        # future.done() means the native worker has returned, not merely that
        # headers arrived or an async caller was cancelled.
        with self.lock:
            streams = list(self.streams)
        for stream in streams:
            if session is None or stream.session is session:
                future = stream.future
                if future is not None and future.done():
                    stream.finish()

    def stop_admission(self):
        with self.admission_lock:
            self.accepting = False

    def drain(self):
        """Terminal only: wait for native owners, never force-close active handles."""
        self.stop_admission()
        with self.admission_lock:
            sessions = list(self.sessions)
        for session in sessions:
            session.close()
        while True:
            self.finish_completed_streams()
            if not any(
                slot.active or slot.pins or slot.retiring for slot in self.snapshot()
            ):
                break
            time.sleep(0.01)
        for session in sessions:
            session.drain(timeout=None)
        self.shutdown()

    def shutdown(self):
        # Never force close an active worker; caller must drain first.
        assert all(not s.active and not s.pins for s in self.snapshot()), (
            "shutdown requires drained leases/pins"
        )
        for session in list(self.sessions):
            session.drain()
        self.stop_event.set()
        self.thread.join(5)
        for s in self.snapshot():
            self.retire(s, terminal=True)
        assert not self.thread.is_alive() and not self.errors, self.errors
