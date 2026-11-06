"""The slop fakes' HTTP server: stdlib `ThreadingHTTPServer` semantics (requests served
concurrently, each on a worker thread, in arrival order) with the thread count bounded.

Why: `ThreadingHTTPServer` spends a thread per CONNECTION, not per request, and an
HTTP/1.1 handler's thread then sits in `readline()` on the idle keep-alive socket until the
client closes it. The relay's `OFClient` keeps one curl handle per (account, worker thread)
(service/client_pool.py), each with its own keep-alive connection, so the fake OF ended up
with a thread per (account x relay worker): 2,722 threads for 50 accounts at --scale=small
(relay-admission, 2026-11-05, evidence ~/.slop/evidence/thread-rc-20261105T223546Z), and
the 5-7k-thread harnesses that kernel-panicked this Mac (`Spinlock timeout`) at 200 users.

Here a request runs on a pooled worker (at most `workers`, env SLOP_SERVER_WORKERS, default
512; started lazily, daemon threads, never more than the peak of requests IN FLIGHT); between
requests a keep-alive connection is parked in one selector thread and costs a file
descriptor, not a thread. When a request arrives on it, it goes back to the pool. Past
`workers` requests in flight, later ones queue (never refused) and `saturated` counts them;
the first one is logged, so a scenario that needs more concurrency says so (raise the env).

Drop-in: `ThreadingHTTPServer(addr, Handler)` -> `BoundedHTTPServer(addr, Handler)`;
`serve_forever` / `shutdown` / `server_close` / `daemon_threads` unchanged.
"""
from __future__ import annotations

import os
import queue
import selectors
import socket
import ssl
import sys
import threading
from collections import deque
from http.server import HTTPServer

WORKERS = int(os.environ.get("SLOP_SERVER_WORKERS", "512"))


class _Pool:
    """A fixed-ceiling pool of daemon threads, started on demand (as ThreadPoolExecutor, but
    daemon: a handler stuck on a slow client never blocks the harness's exit)."""

    def __init__(self, workers: int, name: str):
        self.workers, self.name = workers, name
        self.q: queue.SimpleQueue = queue.SimpleQueue()
        self.idle = threading.Semaphore(0)
        self.lock = threading.Lock()
        self.started = 0
        self.saturated = 0  # submits that found every worker busy at the ceiling: they queued

    def submit(self, fn, *args) -> None:
        self.q.put((fn, args))
        if self.idle.acquire(blocking=False):
            return
        with self.lock:
            if self.started < self.workers:
                self.started += 1
                threading.Thread(target=self._run, name=f"{self.name}-{self.started}", daemon=True).start()
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


class BoundedHTTPServer(HTTPServer):
    daemon_threads = True  # kept for callers that set it: every thread here is a daemon
    request_queue_size = 512  # listen() backlog (socketserver: 5)
    workers = WORKERS

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
        threading.Thread(target=self._park_loop, name=f"{name}-park", daemon=True).start()

    @property
    def saturated(self) -> int:
        return self.pool.saturated

    # socketserver calls this on serve_forever's thread for each accepted connection
    def process_request(self, request, client_address) -> None:
        self.pool.submit(self._open, request, client_address)

    def _open(self, request, client_address) -> None:
        cls = self.RequestHandlerClass
        h = cls.__new__(cls)  # BaseRequestHandler.__init__ runs the whole connection; split it
        h.request, h.client_address, h.server = request, client_address, self
        try:
            h.setup()
        except Exception:  # noqa: BLE001
            self.handle_error(request, client_address)
            self.shutdown_request(request)
            return
        self._next(h)  # parked until its first request arrives: a silent client pins no worker

    def _serve(self, h) -> None:
        """One request on `h`'s connection (BaseHTTPRequestHandler.handle's loop body), then
        park the connection or close it."""
        try:
            h.close_connection = True
            h.handle_one_request()
            if not h.close_connection and not self._closed:
                return self._next(h)
        except Exception:  # noqa: BLE001
            self.handle_error(h.request, h.client_address)
        self._close(h)

    def _next(self, h) -> None:
        """Serve `h`'s next request now if it is already buffered, else park the connection."""
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
        """Bytes of a next request already in rfile's buffer (curl does not pipeline, but a
        buffered byte would never wake the selector). Peeks without blocking."""
        sock = h.connection
        if isinstance(sock, ssl.SSLSocket) and sock.pending():  # decrypted, unseen by the selector
            return True
        try:
            sock.setblocking(False)
            return bool(h.rfile.peek(1))
        except (BlockingIOError, ssl.SSLWantReadError):
            return False
        except OSError:
            return True  # let the worker meet the error and close
        finally:
            try:
                sock.settimeout(h.timeout)
            except OSError:
                pass

    def _park_loop(self) -> None:
        while True:
            for key, _ev in self._sel.select():
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
                        except (ValueError, OSError):
                            self._close(h)
                    continue
                self._sel.unregister(key.fileobj)
                self.pool.submit(self._serve, key.data)

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
