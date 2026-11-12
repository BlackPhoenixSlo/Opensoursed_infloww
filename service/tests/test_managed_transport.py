"""Local real transport/caller regressions; no production endpoints or database."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for key in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(key, None)
os.environ["CHATTERLY_TEST_MODE"] = "1"
os.environ["OF_CALL_STATS_PATH"] = ""

from curl_cffi.requests.exceptions import SessionClosed
from of_managed_session import ManagedSession, Unsupported
from of_session_registry import Registry

started = threading.Event()
release = threading.Event()
wire = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        wire.append((self.path, self.headers.get("Cookie", "")))
        if self.path.endswith("/domain-set"):
            self.send_response(200)
            self.send_header("Set-Cookie", "bad=parent; Domain=co.uk; Path=/")
            self.send_header("Set-Cookie", "good=host; Domain=a.co.uk; Path=/")
        else:
            self.send_response(503 if self.path == "/non200" else 200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"a")
        self.wfile.flush()
        if self.path == "/wait":
            started.set()
            release.wait(5)
        try:
            self.wfile.write(b"b")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def client():
    from of_client import OFClient

    return OFClient(
        dict(
            headers=dict(
                user_id="101", x_bc="local", x_of_rev="local", user_agent="local"
            ),
            signing=dict(
                signed_ok_at=1,
                rules=dict(
                    static_param="local",
                    start="a",
                    end="b",
                    checksum_indexes=[0],
                    checksum_constant=1,
                ),
            ),
            cookies=[],
        )
    )


def domain(url):
    registry = Registry()
    session = ManagedSession(registry=registry, proxies={"http": url})
    try:
        session.get("http://a.co.uk/domain-set")
        assert not any(c.domain.lstrip(".") == "co.uk" for c in session.cookies.jar), (
            "public suffix published"
        )
        session.get("http://a.co.uk/domain-replay")
        assert wire[-1][1] == "good=host", wire[-1]
        session.get("http://b.co.uk/domain-replay")
        assert not wire[-1][1], wire[-1]
    finally:
        session.drain()
        registry.shutdown()


def vault(url):
    import vault_frames
    import storyboard
    from of_managed_session import ManagedResponse

    outcomes = {}
    with tempfile.TemporaryDirectory() as directory:
        c = client()
        responses = []
        original_get = c.http.get

        def get(*args, **kw):
            response = original_get(*args, **kw)
            responses.append(response)
            return response

        c.http.get = get
        original_open = Path.open
        original_iter = ManagedResponse.iter_content

        def fail_open(path, *a, **kw):
            if path.name == "source.tmp":
                raise OSError("fixture-open")
            return original_open(path, *a, **kw)

        class BrokenWriter:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, chunk):
                raise OSError("fixture-write")

        def fail_write(path, *a, **kw):
            return (
                BrokenWriter()
                if path.name == "source.tmp"
                else original_open(path, *a, **kw)
            )

        def fail_iteration(response, *args, **kw):
            yield next(original_iter(response, *args, **kw))
            raise ValueError("fixture-iteration")

        try:
            with (
                patch.object(storyboard, "_STORYBOARD_DIR", Path(directory)),
                patch.object(
                    storyboard, "_storyboard_all_frames_present", return_value=False
                ),
            ):
                for case in ("non200", "open", "write", "iteration"):
                    target = url + ("/non200" if case == "non200" else "/ok")
                    context = (
                        patch.object(
                            Path, "open", fail_open if case == "open" else fail_write
                        )
                        if case in ("open", "write")
                        else patch.object(
                            ManagedResponse,
                            "iter_content",
                            fail_iteration if case == "iteration" else original_iter,
                        )
                    )
                    with context:
                        result = vault_frames.warm_one_sync(c, target, 1)
                    assert result == ("dl_fail" if case == "non200" else "error"), (
                        case,
                        result,
                    )
                    assert responses[-1]._managed_stream.closed, (
                        case,
                        "duplicate not closed",
                    )
                    assert not any(slot.pins for slot in c.http.registry.snapshot()), (
                        case,
                        "pinned",
                    )
                    outcomes[case] = result
        finally:
            for response in responses:
                response.close()
            c.http.drain()
    return outcomes


def drain(url):
    import anyio

    registry = Registry()
    session = ManagedSession(registry=registry)
    errors = []

    def worker():
        response = session.get(url + "/wait", stream=True)
        try:
            return b"".join(response.iter_content())
        finally:
            response.close()

    async def cancelled_waiter():
        task = asyncio.create_task(
            anyio.to_thread.run_sync(worker, abandon_on_cancel=True)
        )
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert any(slot.pins for slot in registry.snapshot())

        def stop():
            try:
                registry.drain()
            except BaseException as exc:
                errors.append(repr(exc))

        stopper = threading.Thread(target=stop)
        stopper.start()
        await asyncio.sleep(0.1)
        assert stopper.is_alive(), (
            "drain mistook cancelled waiter for completed native worker"
        )
        try:
            session.get(url + "/denied")
        except (Unsupported, SessionClosed):
            pass
        else:
            raise AssertionError("new lease admitted during terminal drain")
        release.set()
        await asyncio.to_thread(stopper.join, 5)
        assert not stopper.is_alive() and not errors, errors
        assert not registry.snapshot() and not registry.thread.is_alive()
        assert all(not thread.is_alive() for thread in session.executor._threads)

    try:
        asyncio.run(cancelled_waiter())
    finally:
        release.set()
        session.drain()
        registry.shutdown()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    os.environ["OF_API_ORIGIN"] = url
    selected = sys.argv[1:] or ["domain", "vault", "drain"]
    results = {}
    try:
        for case in selected:
            results[case] = globals()[case](url) or "passed"
        print(json.dumps(results))
    finally:
        release.set()
        if Registry._instance is not None:
            Registry._instance.drain()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
