from __future__ import annotations

import os
import queue
import selectors
import socket
import ssl
import sys
import threading
import time
from collections import deque
from http.server import HTTPServer

WORKERS = int(os.environ.get("SLOP_SERVER_WORKERS", "512"))


class _Pool:

    def __init__(self, workers: int, name: str):
        self.workers, self.name = workers, name
        self.q: queue.SimpleQueue = queue.SimpleQueue()
        self.idle = threading.Semaphore(0)
        self.lock = threading.Lock()
        self.started = 0
        self.threads: list[threading.Thread] = []
        self.saturated = 0

    def submit(self, fn, *args) -> None:
        self.q.put((fn, args))
        if self.idle.acquire(blocking=False):
            return
        with self.lock:
            if self.started < self.workers:
                self.started += 1
                worker = threading.Thread(target=self._run, name=f"{self.name}-{self.started}", daemon=True)
                self.threads.append(worker)
                worker.start()
                return
            self.saturated += 1
            first = self.saturated == 1
        if first:
            print(f"slop: {self.name}: all {self.workers} workers busy, requests queue "
                  f"(SLOP_SERVER_WORKERS raises it)", file=sys.stderr, flush=True)

    def _run(self) -> None:
        while True:
            fn, args = self.q.get()
            if fn is None:
                return
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 — the server's handle_error already ran
                pass
            self.idle.release()

    def close(self) -> None:
        for _ in self.threads:
            self.q.put((None, ()))
        deadline = time.monotonic() + 1
        for worker in self.threads:
            worker.join(timeout=max(0, deadline - time.monotonic()))


# Thread per connection hit 2,722 threads at 50 accounts and 5-7k kernel-panicked the Mac; bound workers, park idle keep-alives.
class BoundedHTTPServer(HTTPServer):
    daemon_threads = True
    request_queue_size = 512
    workers = WORKERS
    idle_close_s: float | None = None
    idle_closed = 0

    def server_activate(self) -> None:
        super().server_activate()
        name = f"slop-http-{self.server_address[1]}"
        self.pool = _Pool(self.workers, name)
        self._sel = selectors.DefaultSelector()
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._sel.register(self._wake_r, selectors.EVENT_READ)
        self._to_park: deque = deque()
        self._closed = False
        self._park_thread = threading.Thread(target=self._park_loop, name=f"{name}-park", daemon=True)
        self._park_thread.start()

    @property
    def saturated(self) -> int:
        return self.pool.saturated

    def process_request(self, request, client_address) -> None:
        self.pool.submit(self._open, request, client_address)

    def _open(self, request, client_address) -> None:
        cls = self.RequestHandlerClass
        h = cls.__new__(cls)
        h.request, h.client_address, h.server = request, client_address, self
        try:
            h.setup()
        except Exception:  # noqa: BLE001
            self.handle_error(request, client_address)
            self.shutdown_request(request)
            return
        self._next(h)

    def _serve(self, h) -> None:
        try:
            h.close_connection = True
            h.handle_one_request()
            if not h.close_connection and not self._closed:
                return self._next(h)
        except Exception:  # noqa: BLE001
            self.handle_error(h.request, h.client_address)
        self._close(h)

    def _next(self, h) -> None:
        if self._buffered(h):
            self.pool.submit(self._serve, h)
        else:
            self._to_park.append(h)
            self._wake_w.send(b"\0")

    def _close(self, h) -> None:
        try:
            h.finish()
        except Exception:  # noqa: BLE001
            pass
        self.shutdown_request(h.request)

    @staticmethod
    def _buffered(h) -> bool:
        sock = h.connection
        if isinstance(sock, ssl.SSLSocket) and sock.pending():
            return True
        try:
            sock.setblocking(False)
            return bool(h.rfile.peek(1))
        except (BlockingIOError, ssl.SSLWantReadError):
            return False
        except OSError:
            return True
        finally:
            try:
                sock.settimeout(h.timeout)
            except OSError:
                pass

    def _park_loop(self) -> None:
        parked_at: dict = {}
        while True:
            idle = self.idle_close_s
            for key, _ev in self._sel.select(None if idle is None else min(1.0, idle)):
                if key.fileobj is self._wake_r:
                    try:
                        while self._wake_r.recv(4096):
                            pass
                    except (BlockingIOError, OSError):
                        pass
                    if self._closed:
                        return self._close_parked()
                    while self._to_park:
                        h = self._to_park.popleft()
                        try:
                            self._sel.register(h.connection, selectors.EVENT_READ, h)
                            parked_at[h] = time.monotonic()
                        except (ValueError, OSError):
                            self._close(h)
                    continue
                self._sel.unregister(key.fileobj)
                parked_at.pop(key.data, None)
                self.pool.submit(self._serve, key.data)
            if idle is not None:
                cut = time.monotonic() - idle
                for h in [h for h, t in parked_at.items() if t < cut]:
                    del parked_at[h]
                    try:
                        self._sel.unregister(h.connection)
                    except (KeyError, ValueError, OSError):
                        pass
                    self._close(h)
                    self.idle_closed += 1

    def _close_parked(self) -> None:
        for key in list(self._sel.get_map().values()):
            if key.data is not None:
                self._close(key.data)
        self._sel.close()

    def server_close(self) -> None:
        super().server_close()
        if not getattr(self, "_closed", True):
            self._closed = True
            try:
                self._wake_w.send(b"\0")
            except OSError:
                pass
            self._park_thread.join(timeout=1)
            self.pool.close()
            self._wake_r.close()
            self._wake_w.close()
