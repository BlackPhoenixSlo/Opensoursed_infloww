from __future__ import annotations

import asyncio
import json
import random
import re
import socket
import threading
import time
from typing import Callable


# measured: gap between prod proxy_error_retry lines minus the pause between them
REFUSE_S = 0.33
_LOOPBACK = ("127.0.0.1", "::1")
_EGRESS: dict[int, int] = {}


def egress_of(peer_port: int) -> str:
    p = _EGRESS.get(int(peer_port))
    return "direct" if p is None else f"127.0.0.1:{p}"


def registry_bindings(path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {aid: p["label"] for p in data.get("proxies", []) for aid in (p.get("assigned_account_ids") or [])}


def registry_pool(path) -> dict[str, int]:
    data = json.loads(path.read_text())
    return {p["label"]: p["port"] for p in data["proxies"] if p.get("pool")}


_INTERIM = re.compile(rb"HTTP/1\.[01] 1(?!01)\d\d ")
_INTERIM_PART = re.compile(rb"H(?:T(?:T(?:P(?:/(?:1(?:\.(?:[01](?: (?:1(?:\d\d?)?)?)?)?)?)?)?)?)?)?\Z")


def _answered(head: bytes) -> tuple[bool, bytes]:
    while _INTERIM.match(head) and (end := head.find(b"\r\n\r\n")) >= 0:
        head = head[end + 4:]
    if not head or _INTERIM.match(head) or _INTERIM_PART.match(head):
        return False, head
    return True, b""


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter, socks: tuple,
                mark: asyncio.Event | None = None, once: asyncio.Event | None = None,
                refusing: Callable[[], bool] | None = None) -> None:
    head = b""
    try:
        while chunk := await src.read(65536):
            if once is not None and b"upgrade: websocket" in chunk.lower():
                once = None
            if once is not None and once.is_set() and (refusing is None or refusing()):
                break
            dst.write(chunk)
            await dst.drain()
            if mark is not None and not mark.is_set():
                began, head = _answered(head + chunk)
                if began:
                    mark.set()
        # drain() stops at the high-water mark and the shutdown below dropped the rest (a slow reader lost its last <= 64 KiB, measured)
        dst.transport.set_write_buffer_limits(0)
        await dst.drain()
    except OSError:
        pass
    finally:
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ProxyWire:
    def __init__(self, refuse_s: float = REFUSE_S, refuse_share: float = 0.0, seed: int = 0):
        self.refuse_s = refuse_s
        self.refuse_share = refuse_share
        self._rng = random.Random(seed)
        self.alive = True
        self.lock = threading.Lock()
        self.connects: list[dict] = []
        self._open: set = set()
        self._srv: socket.socket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def port(self) -> int:
        return self._srv.getsockname()[1]

    def __enter__(self) -> "ProxyWire":
        self._srv = socket.create_server(("127.0.0.1", 0), backlog=512)
        self._loop = asyncio.new_event_loop()
        up = threading.Event()

        def main() -> None:
            asyncio.set_event_loop(self._loop)
            self._server = self._loop.run_until_complete(
                asyncio.start_server(self._serve, sock=self._srv, backlog=512))
            up.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=main, name=f"slop-proxy-wire-{self.port}", daemon=True)
        self._thread.start()
        if not up.wait(10):
            raise SystemExit("slop: the fake proxy did not start")
        return self

    def __exit__(self, *_a) -> None:
        self.kill()
        async def shutdown() -> None:
            self._server.close()
            for task in tuple(self._tasks):
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            await self._server.wait_closed()
        asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("slop fake proxy thread did not stop")
        self._loop.close()

    def kill(self) -> float:
        with self.lock:
            self.alive = False
            socks, self._open = list(self._open), set()
        for s in socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return time.time()

    def revive(self) -> None:
        with self.lock:
            self.alive = True

    def set_refuse_share(self, share: float) -> None:
        with self.lock:
            self.refuse_share = share

    async def _serve(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        uw = None
        c = cw.get_extra_info("socket")
        u = None
        up = None
        try:
            _ver, n = await cr.readexactly(2)
            await cr.readexactly(n)
            cw.write(b"\x05\x00")
            await cw.drain()
            _ver, cmd, _rsv, atyp = await cr.readexactly(4)
            if atyp == 1:
                host = socket.inet_ntoa(await cr.readexactly(4))
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, await cr.readexactly(16))
            else:
                host = (await cr.readexactly((await cr.readexactly(1))[0])).decode()
            port = int.from_bytes(await cr.readexactly(2), "big")
            with self.lock:
                ok = self.alive and cmd == 1 and host in _LOOPBACK
                if ok and self.refuse_share:
                    ok = self._rng.random() >= self.refuse_share
                self.connects.append({"t": time.time(), "alive": ok, "dest": f"{host}:{port}"})
            if not ok:
                await asyncio.sleep(self.refuse_s)
                cw.write(b"\x05\x02\x00\x01" + b"\0" * 6)
                await cw.drain()
                return
            ur, uw = await asyncio.open_connection(host, port)
            u = uw.get_extra_info("socket")
            up = u.getsockname()[1]
            _EGRESS[up] = self.port
            with self.lock:
                if not self.alive:
                    return
                self._open.update((c, u))
            cw.write(b"\x05\x00\x00\x01" + b"\0" * 6)
            await cw.drain()
            answered = asyncio.Event()
            await asyncio.gather(_pipe(ur, cw, (u, c), answered),
                                 _pipe(cr, uw, (c, u), None, answered, lambda: bool(self.refuse_share)))
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            with self.lock:
                self._open.discard(c)
                if u is not None:
                    self._open.discard(u)
                    if up is not None:
                        _EGRESS.pop(up, None)
            for w in (cw, uw):
                if w is not None:
                    w.close()
            self._tasks.discard(task)
