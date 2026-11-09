"""A phone's way to the app: a TLS + HTTP/2 edge in front of the stack's app, behind a
WAN with a round-trip time, all on loopback.

    Chromium --(RTT)--> DelayProxy --> nghttpx (TLS, h2, as Traefik) --> app (`next start`)

`WanEdge(stack, rtt_ms=190)` starts both and answers `url` (https://localhost:<port>). The
certificate is self-signed, made per run in the stack's tmp; launch Chromium with
`edge.chrome_args` (its SPKI pinned as trusted), NOT `ignore_https_errors`: Chromium keeps
no HTTP cache for a response with a certificate error, so a return visit would refetch
every immutable chunk.

DelayProxy holds every byte for half the RTT each way, in order, and holds a new
connection one RTT before its first byte (the TCP handshake), so a fresh connection pays
connect + TLS 1.3 + request = 3 RTTs before its first response byte, as a live deployment
measured from the laptop (connect 185 ms, TLS +200 ms, TTFB +195 ms at ~187 ms RTT).
Bandwidth is not limited here (Chromium's own throttling does it), though the 16-slot
queue caps each direction at ~1 MiB per one-way delay (~10 MiB/s at 190 ms RTT), far
above the phone profiles' bandwidth.
TCP slow start is not modelled (loopback windows), so a large download on a fresh
connection is a little faster than on a real link. nghttpx's access log
(`edge-access.log`) keeps each request's time.
Loopback only: both listen on 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

NGHTTPX = shutil.which("nghttpx")   # None: WanEdge stops the run (INFRA), naming it


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DelayProxy:
    """TCP on 127.0.0.1:`port` to `upstream`, each direction `one_way_s` late, order kept. Every
    connection runs on one asyncio loop thread."""

    def __init__(self, upstream: tuple[str, int], one_way_s: float):
        self.upstream, self.d = upstream, one_way_s
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self._loop = asyncio.new_event_loop()
        self._tasks: set[asyncio.Task] = set()
        up = threading.Event()

        def main() -> None:
            asyncio.set_event_loop(self._loop)
            self._server = self._loop.run_until_complete(asyncio.start_server(self._conn, sock=self.sock, backlog=64))
            up.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=main, name="wan-loop", daemon=True)
        self._thread.start()
        if not up.wait(10):
            raise SystemExit("slop: the WAN delay proxy did not start")

    async def _conn(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        # Owns closing both sides: a pipe ends its direction with EOF (half-close), never closes.
        task = asyncio.current_task()
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self.connections += 1
        writers, pipes = [cw], []
        try:
            await asyncio.sleep(2 * self.d)  # SYN out, SYN-ACK back: the client's first byte leaves one RTT later
            ur, uw = await asyncio.open_connection(*self.upstream)
            writers.append(uw)
            for w in writers:
                w.get_extra_info("socket").setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            pipes = [asyncio.create_task(self._pipe(cr, uw)), asyncio.create_task(self._pipe(ur, cw))]
            await asyncio.gather(*pipes)
        except OSError:
            pass  # upstream refused or a side reset: close both below
        finally:
            for t in pipes:
                t.cancel()
            for w in writers:
                w.close()
            close_waiters = [asyncio.create_task(w.wait_closed()) for w in writers]
            try:
                await asyncio.gather(*pipes, return_exceptions=True)
                await asyncio.wait(close_waiters, timeout=1)
            finally:
                for w in writers:
                    if w.transport.get_write_buffer_size():  # 0: flushed or lost, connection_lost ran or is due
                        w.transport.abort()
                await asyncio.gather(*close_waiters, return_exceptions=True)

    async def _pipe(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        """src to dst, `d` late; ends with dst's EOF. A failed write (OSError) cancels the reader and raises."""
        q: asyncio.Queue = asyncio.Queue(maxsize=16)
        loop = asyncio.get_running_loop()

        async def read() -> None:
            while True:
                try:
                    data = await src.read(65536)
                except OSError:
                    data = b""
                await q.put((loop.time() + self.d, data))
                if not data:
                    return

        reader = asyncio.create_task(read())
        try:
            while True:
                due, data = await q.get()
                wait = due - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                if not data:
                    if dst.can_write_eof():
                        dst.write_eof()
                    return
                dst.write(data)
                await dst.drain()
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)

    def close(self) -> None:
        async def stop() -> None:
            self._server.close()
            while self._tasks:  # a connection accepted during the gather starts its task late
                tasks = tuple(self._tasks)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            await self._server.wait_closed()

        future = asyncio.run_coroutine_threadsafe(stop(), self._loop)
        try:
            future.result(timeout=10)
        finally:
            future.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise TimeoutError("WAN delay proxy loop did not stop")
            self._loop.close()


class WanEdge:
    """nghttpx (TLS, HTTP/2 to the browser, HTTP/1.1 to the app) behind a DelayProxy."""

    def __init__(self, stack, rtt_ms: float):
        if not NGHTTPX:
            raise SystemExit("slop: nghttpx not on PATH (the TLS + HTTP/2 edge lib/wan.py puts in front of the app; "
                             "brew install nghttp2)")
        app = urlsplit(stack.app)
        tmp, log = Path(stack.tmp), Path(stack.logdir)
        key, cert = tmp / "edge-key.pem", tmp / "edge-cert.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(cert), "-days", "2", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
        pub = subprocess.run(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"], check=True,
                             capture_output=True).stdout
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "der"], input=pub, check=True,
                             capture_output=True).stdout
        self.spki = base64.b64encode(hashlib.sha256(der).digest()).decode()
        self.chrome_args = [f"--ignore-certificate-errors-spki-list={self.spki}"]
        self.tls_port = _free_port()
        self.proc = stack.spawn([NGHTTPX, f"--frontend=127.0.0.1,{self.tls_port}",
                                 f"--backend=127.0.0.1,{app.port}", "--workers=1", "--no-ocsp", "--no-via",
                                 "--backend-read-timeout=600s", "--frontend-read-timeout=600s",
                                 "--backend-keep-alive-timeout=60s",
                                 # Traefik's default (entryPoints http2.maxConcurrentStreams; deploy/ sets none), not
                                 # nghttpx's 100: hung background reads past the cap stall every request after them
                                 "--frontend-http2-max-concurrent-streams=250",
                                 f"--accesslog-file={log / 'edge-access.log'}",
                                 "--accesslog-format=$time_iso8601 $status $request_time $method $path $alpn",
                                 f"--errorlog-file={log / 'edge-error.log'}", str(key), str(cert)],
                                {"PATH": "/usr/bin:/bin"}, "edge.log")
        t0 = time.time()
        while True:
            try:
                if httpx.get(f"https://127.0.0.1:{self.tls_port}/login", verify=False, timeout=30).status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            if self.proc.poll() is not None or time.time() - t0 > 60:
                raise SystemExit(f"slop: nghttpx edge not ready on {self.tls_port}; see {log}/edge.log")
            time.sleep(0.5)
        self.rtt_ms = rtt_ms
        self.wan = DelayProxy(("127.0.0.1", self.tls_port), rtt_ms / 2000)
        self.url = f"https://localhost:{self.wan.port}"

    def close(self) -> None:
        self.wan.close()
