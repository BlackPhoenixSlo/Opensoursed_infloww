"""A Creator's proxy at its wire, on loopback: the SOCKS5 endpoint the relay's REAL
`OFClient` (curl_cffi) dials once the Creator is bound to it through the product's
own `POST /admin/proxies` + `POST /admin/proxies/assign`. Alive, it tunnels each
CONNECT to its target (loopback only: lib/of_wire.py), as a residential proxy does.
`kill()` closes every open tunnel and makes each later CONNECT wait `refuse_s`, then
answer SOCKS5 reply 0x02 (not allowed): curl reports CURLE_PROXY (97), which
curl_cffi raises as `ProxyError`, the class prod's provider-side CONNECT 403 (curl 56)
raises, so the product's own retry, proxy_health and 502 run unchanged.

Every tunnel runs on the wire's one asyncio loop thread (it was 2 threads per tunnel, and the
relay keeps a tunnel per (account x worker thread) open: thousands; see lib/bounded_server.py).

`refuse_share` (0..1, `set_refuse_share`): a flapping proxy, alive but refusing that share
of CONNECTs, drawn at random from `seed` in arrival order (deterministic per --seed), each
refusal after `refuse_s` with the same 0x02, as prod's provider-side bursts
(slop/evidence/20261105T150727Z-ae-proxy-refusals-296e9299c). While it refuses, a tunnel
carries one HTTP exchange: a request on a reused tunnel closes it (curl re-dials on a
fresh CONNECT), so the share of CONNECTs is the share of attempts (with keep-alive, 30 %
of CONNECTs was 7.7 % of attempts); a WebSocket upgrade keeps its tunnel.

`connects` records every CONNECT in arrival order: {t, alive, dest} (alive False = refused).

`egress_of(peer_port)`: the egress a loopback fake in this process (lib/of_wire.py) saw a request arrive from:
"127.0.0.1:<proxy port>" when that peer port is an open tunnel's upstream socket, else "direct" (the address an
OF signature's `AWS:SourceIp` names; lib/img_relay.py names the CDN side's egress the same way).

Bypass, declared: SOCKS5, not HTTP CONNECT. lib/of_wire.py is plain http and curl
tunnels only an https target through an HTTP proxy, so an HTTP proxy would never be
asked a CONNECT to refuse. `refuse_s` (0.33 s) is measured: the gap between prod's
`proxy_error_retry` lines minus the pause between them (slop/evidence/
20261028T111800Z-scale-vs-load-7cc9bbd67/prod/relay_ingest_retry.log).
"""
from __future__ import annotations

import asyncio
import random
import socket
import threading
import time

REFUSE_S = 0.33
_LOOPBACK = ("127.0.0.1", "::1")
_EGRESS: dict[int, int] = {}  # an open tunnel's upstream local port -> its proxy's port (every wire in the process)


def egress_of(peer_port: int) -> str:
    p = _EGRESS.get(int(peer_port))
    return "direct" if p is None else f"127.0.0.1:{p}"


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter, socks: tuple,
                mark: asyncio.Event | None = None, once: asyncio.Event | None = None) -> None:
    """Copy src to dst; `mark` is set once a chunk went through; with `once` (the answer's mark),
    a chunk after the answer began (the next request on this tunnel) closes it instead. Either
    direction ending shuts both sockets, which ends the other."""
    try:
        while chunk := await src.read(65536):
            if once is not None and once.is_set():
                if b"upgrade: websocket" in chunk.lower():
                    once = None
                else:
                    break
            dst.write(chunk)
            await dst.drain()
            if mark is not None:
                mark.set()
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
        self._open: set = set()  # the open tunnels' sockets (both ends), shut by kill()
        self._srv: socket.socket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

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

        threading.Thread(target=main, name=f"slop-proxy-wire-{self.port}", daemon=True).start()
        if not up.wait(10):
            raise SystemExit("slop: the fake proxy did not start")
        return self

    def __exit__(self, *_a) -> None:
        self._loop.call_soon_threadsafe(self._server.close)
        self.kill()
        self._loop.call_soon_threadsafe(self._loop.stop)

    def kill(self) -> float:
        """The proxy dies: open tunnels end, every later CONNECT is refused. Returns the time."""
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
        """The proxy answers again: later CONNECTs tunnel."""
        with self.lock:
            self.alive = True

    def set_refuse_share(self, share: float) -> None:
        """Refuse this share of later CONNECTs (0 = none), the proxy otherwise alive."""
        with self.lock:
            self.refuse_share = share

    async def _serve(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        uw = None
        c = cw.get_extra_info("socket")
        u = None
        try:
            _ver, n = await cr.readexactly(2)
            await cr.readexactly(n)
            cw.write(b"\x05\x00")  # no auth
            await cw.drain()
            _ver, cmd, _rsv, atyp = await cr.readexactly(4)
            if atyp == 1:
                host = socket.inet_ntoa(await cr.readexactly(4))
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, await cr.readexactly(16))
            else:  # a name: never resolved here
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
                if not self.alive:  # killed meanwhile
                    return
                self._open.update((c, u))
            cw.write(b"\x05\x00\x00\x01" + b"\0" * 6)
            await cw.drain()
            answered = asyncio.Event() if self.refuse_share else None   # one exchange per tunnel
            await asyncio.gather(_pipe(ur, cw, (u, c), answered), _pipe(cr, uw, (c, u), None, answered))
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            with self.lock:
                self._open.discard(c)
                if u is not None:
                    self._open.discard(u)
                    _EGRESS.pop(up, None)
            for w in (cw, uw):
                if w is not None:
                    w.close()
