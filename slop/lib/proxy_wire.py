"""A Creator's proxy at its wire, on loopback: the SOCKS5 endpoint the relay's REAL
`OFClient` (curl_cffi) dials once the Creator is bound to it through the product's
own `POST /admin/proxies` + `POST /admin/proxies/assign`. Alive, it tunnels each
CONNECT to its target (loopback only: lib/of_wire.py), as a residential proxy does.
`kill()` closes every open tunnel and makes each later CONNECT wait `refuse_s`, then
answer SOCKS5 reply 0x02 (not allowed): curl reports CURLE_PROXY (97), which
curl_cffi raises as `ProxyError`, the class prod's provider-side CONNECT 403 (curl 56)
raises, so the product's own retry, proxy_health and 502 run unchanged.

`connects` records every CONNECT in arrival order: {t, alive, dest}.

Bypass, declared: SOCKS5, not HTTP CONNECT. lib/of_wire.py is plain http and curl
tunnels only an https target through an HTTP proxy, so an HTTP proxy would never be
asked a CONNECT to refuse. `refuse_s` (0.33 s) is measured: the gap between prod's
`proxy_error_retry` lines minus the pause between them (slop/evidence/
20261028T111800Z-scale-vs-load-7cc9bbd67/prod/relay_ingest_retry.log).
"""
from __future__ import annotations

import socket
import threading
import time

REFUSE_S = 0.33
_LOOPBACK = ("127.0.0.1", "::1")


def _recv(c: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = c.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


def _pipe(src: socket.socket, dst: socket.socket) -> None:
    try:
        while chunk := src.recv(65536):
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ProxyWire:
    def __init__(self, refuse_s: float = REFUSE_S):
        self.refuse_s = refuse_s
        self.alive = True
        self.lock = threading.Lock()
        self.connects: list[dict] = []
        self._open: set[socket.socket] = set()
        self._srv: socket.socket | None = None

    @property
    def port(self) -> int:
        return self._srv.getsockname()[1]

    def __enter__(self) -> "ProxyWire":
        self._srv = socket.create_server(("127.0.0.1", 0), backlog=512)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def __exit__(self, *_a) -> None:
        self._srv.close()
        self.kill()

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

    def _accept(self) -> None:
        while True:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c: socket.socket) -> None:
        up = None
        try:
            _ver, n = _recv(c, 2)
            _recv(c, n)
            c.sendall(b"\x05\x00")  # no auth
            _ver, cmd, _rsv, atyp = _recv(c, 4)
            if atyp == 1:
                host = socket.inet_ntoa(_recv(c, 4))
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, _recv(c, 16))
            else:  # a name: never resolved here
                host = _recv(c, _recv(c, 1)[0]).decode()
            port = int.from_bytes(_recv(c, 2), "big")
            with self.lock:
                ok = self.alive and cmd == 1 and host in _LOOPBACK
                self.connects.append({"t": time.time(), "alive": ok, "dest": f"{host}:{port}"})
            if not ok:
                time.sleep(self.refuse_s)
                c.sendall(b"\x05\x02\x00\x01" + b"\0" * 6)
                return
            up = socket.create_connection((host, port))
            with self.lock:
                if not self.alive:  # killed meanwhile
                    return
                self._open.update((c, up))
            c.sendall(b"\x05\x00\x00\x01" + b"\0" * 6)
            back = threading.Thread(target=_pipe, args=(up, c), daemon=True)
            back.start()
            _pipe(c, up)
            back.join()
        except OSError:
            pass
        finally:
            with self.lock:
                self._open.discard(c)
                if up is not None:
                    self._open.discard(up)
            for s in (c, up):
                if s is not None:
                    s.close()
