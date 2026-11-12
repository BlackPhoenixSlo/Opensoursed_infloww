"""OnlyFans synchronous transport with leased native handles.

Pinned private curl_cffi integration: review the stream option adapter on upgrade.
Buffered requests keep upstream setup; the outer lease also covers setup failures.
No global lock is held across perform. Eviction is NOT terminal close.
"""

import contextlib
import inspect
import threading
import time
import weakref
from urllib.parse import urljoin
from curl_cffi.requests import Headers
from of_cookie_events import response_cookie_events, cookie_from_row
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import Curl, CurlMime
from curl_cffi.const import CurlInfo, CurlOpt
from curl_cffi.requests import Session
from curl_cffi.requests.models import Response

from of_session_registry import Registry, Slot, Life

_SIGNATURE = inspect.signature(Session._request_once)

# The copied request option setup must be reviewed on any upstream drift.
import curl_cffi
import hashlib

if (
    curl_cffi.__version__ != "0.15.0"
    or hashlib.sha256(inspect.getsource(Session._request_once).encode()).hexdigest()
    != "4537bdd81bf31e7305a6f83f3361996e652e7eddb58a877219a783c68b256281"
):
    raise RuntimeError("unreviewed curl_cffi request implementation")


class Unsupported(RuntimeError):
    pass


class ReleasedCurl:
    def __getattr__(self, name):
        raise Unsupported("Response.curl is invalid outside managed ownership")

    def __bool__(self):
        return True


class ManagedResponse(Response):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.curl = ReleasedCurl()
        self._managed_stream = None
        self.metadata_pending = False

    def _finalize_stream(self):
        if self._managed_stream is not None:
            self._managed_stream.finish()
            self._stream_closed = True
        else:
            super()._finalize_stream()


class HeaderView:
    """Header-only supported fields; unavailable native fields marked None by caller."""

    get_reason_phrase = staticmethod(Curl.get_reason_phrase)
    pending = (
        "primary_ip",
        "primary_port",
        "local_ip",
        "local_port",
        "elapsed",
        "download_size",
        "upload_size",
        "header_size",
        "request_size",
        "response_size",
    )

    def __init__(self, url, headers, follow):
        from urllib.parse import urljoin

        blocks = []
        for line in headers.getvalue().splitlines():
            if line.startswith(b"HTTP/"):
                blocks.append([line, []])
            elif blocks:
                blocks[-1][1].append(line)
        self.redirects = 0
        self.redirect_url = b""
        for status, lines in blocks[:-1]:
            code = int(status.split()[1])
            location = next(
                (
                    l.split(b":", 1)[1].strip().decode("latin1")
                    for l in lines
                    if l.lower().startswith(b"location:")
                ),
                None,
            )
            if follow and 300 <= code < 400 and location:
                url = urljoin(url, location)
                self.redirects += 1
        fields = blocks[-1][0].split(None, 2)
        self.url = url.encode()
        self.status = int(fields[1])
        self.version = {b"HTTP/1.0": 1, b"HTTP/1.1": 2, b"HTTP/2": 3, b"HTTP/3": 30}[
            fields[0]
        ]
        if 300 <= self.status < 400:
            location = next(
                (
                    l.split(b":", 1)[1].strip().decode("latin1")
                    for l in blocks[-1][1]
                    if l.lower().startswith(b"location:")
                ),
                None,
            )
            if location:
                self.redirect_url = urljoin(url, location).encode()

    def getinfo(self, key):
        supported = {
            CurlInfo.EFFECTIVE_URL: self.url,
            CurlInfo.RESPONSE_CODE: self.status,
            CurlInfo.HTTP_VERSION: self.version,
            CurlInfo.COOKIELIST: [],
            CurlInfo.PRIMARY_IP: b"",
            CurlInfo.LOCAL_IP: b"",
            CurlInfo.REDIRECT_URL: self.redirect_url,
            CurlInfo.REDIRECT_COUNT: self.redirects,
        }
        # Only internal parser placeholders; public pending values are replaced with None.
        for k in (
            CurlInfo.PRIMARY_PORT,
            CurlInfo.LOCAL_PORT,
            CurlInfo.TOTAL_TIME,
            CurlInfo.SIZE_DOWNLOAD_T,
            CurlInfo.SIZE_UPLOAD_T,
            CurlInfo.HEADER_SIZE,
            CurlInfo.REQUEST_SIZE,
        ):
            supported[k] = 0
        if key not in supported:
            raise Unsupported("unsupported early metadata")
        return supported[key]


class StreamState:
    def __init__(self, session, slot, curl):
        self.session = session
        self.slot = slot
        self.curl = curl
        self.lock = threading.Lock()
        self.meta_lock = threading.Lock()
        self.done = threading.Event()
        self.closed = False
        self.future = None
        self.quit = None
        self.q = None
        self.response = None
        self.final = None
        session.registry.track_stream(self)

    def publish(self, response):
        with self.meta_lock:
            self.final = {
                k: v for k, v in response.__dict__.items() if k not in self.excluded
            }
            target = self.response() if self.response is not None else None
            if target is not None:
                self.update(target, self.final)

    excluded = (
        "curl",
        "queue",
        "stream_task",
        "quit_now",
        "_stream_closed",
        "_managed_stream",
        "_abandon_finalizer",
    )

    @staticmethod
    def update(target, source):
        for key, value in source.items():
            setattr(target, key, value)
        target.metadata_pending = False

    def abandon(self):
        # Weak response finalizer owns state, never response. Do not wait in GC callback.
        if self.quit:
            self.quit.set()
        if self.future:
            self.future.add_done_callback(lambda _: self.finish())
        else:
            self.finish()

    def finish(self):
        with self.lock:
            if self.closed:
                return
            if self.quit:
                self.quit.set()
            try:
                if self.future:
                    self.future.result()
            finally:
                assert self.future is None or self.done.is_set(), (
                    "stream worker still owns duplicate"
                )
                self.curl.close()
                self.closed = True
                with self.slot.lock:
                    self.slot.pins -= 1
                    assert self.slot.pins >= 0
                    self.session.registry.event("unpin", self.slot)
                session = self.session
                session.registry.forget_stream(self)
                self.session = None
                if session._life.closed:
                    session.registry.retire(self.slot, terminal=True)
                session._maybe_shutdown_executor()


class ManagedSession(Session):
    _mime_guard = threading.Lock()
    _mime_in_use = weakref.WeakSet()

    @contextlib.contextmanager
    def _multipart_owner(self, form):
        if form is None:
            yield
            return
        with self._mime_guard:
            if form in self._mime_in_use:
                raise Unsupported("concurrent reuse of CurlMime")
            if not form._form:
                raise Unsupported("closed CurlMime")
            self._mime_in_use.add(form)
        try:
            # Strong reference spans setup, perform, parsing and reset. Caller owns
            # free/reuse after return (including of_upload's proxy retry).
            yield
        finally:
            with self._mime_guard:
                self._mime_in_use.discard(form)

    def __init__(self, *a, registry=None, **kw):
        if (
            a
            or kw.get("curl")
            or kw.get("debug")
            or kw.get("thread")
            or kw.get("use_thread_local_curl") is False
        ):
            raise Unsupported("custom Curl/debug/thread mode unsupported")
        self.registry = registry or Registry.instance()
        self._life = Life()
        self._managed_local = threading.local()
        self._slots = []
        self._metadata_lock = threading.RLock()
        self._executor_lock = threading.Lock()
        with self.registry.admission_lock:
            if not self.registry.accepting:
                raise Unsupported("transport is draining")
            super().__init__(**kw)
            self.response_class = ManagedResponse
            self.registry.sessions.add(self)
            # Stock eager Curl is registered, not orphaned or recreated by close().
            eager = self._local.curl
            self._local.curl = None
            s = Slot(self._life)
            s.curl = eager
            s.generation = 1
            s.state = "IDLE"
            s.last = time.monotonic()
            self._slots.append(s)
            self.registry.add(s)
            self._finalizer = weakref.finalize(self, self.registry.orphan, self._slots)

    @property
    def executor(self):
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(thread_name_prefix="managed-stream")
            return self._executor

    @property
    def curl(self):
        lease = getattr(self._managed_local, "lease", None)
        if lease is None:
            raise Unsupported("raw Session.curl requires managed request lease")
        return lease

    @contextlib.contextmanager
    def _lease(self):
        with self.registry.admission_lock, self._life.lock:
            if not self.registry.accepting:
                raise Unsupported("transport is draining")
            if self._life.closed:
                raise Unsupported("managed Session closed")
            if getattr(self._managed_local, "lease", None) is not None:
                raise Unsupported("reentrant request")
            # Reservation is Session-local, never worker-local. Mark active while
            # holding the slot lock so the sweeper cannot detach a chosen handle.
            s = None
            empty = None
            for candidate in self._slots:
                with candidate.lock:
                    assert candidate.session_id == self._life.id
                    if candidate.active or candidate.pins or candidate.retiring:
                        continue
                    if candidate.state == "IDLE" and candidate.curl and candidate.clean:
                        candidate.active = 1
                        s = candidate
                        break
                    if candidate.state == "EMPTY" and candidate.curl is None:
                        empty = candidate
            if s is None:
                # Recycle an empty record after cleanup acknowledgement. A fresh
                # Curl is still created immediately; no capacity wait or cap.
                s = empty
                if s is None:
                    s = Slot(self._life)
                    self._slots.append(s)
                    self.registry.add(s)
                with s.lock:
                    assert not (s.active or s.pins or s.retiring or s.curl)
                    s.active = 1
            with s.lock:
                assert s.session_id == self._life.id and s.active == 1
                s.active = 1
                s.state = "LEASED"
                s.owner = threading.get_ident()
                if s.curl is None:
                    s.generation += 1
                generation = s.generation
                c = s.curl
                self.registry.event("reserve", s)
        try:
            hook = self.registry.hooks.get("reserved")
            if hook:
                hook(s, generation)
            if c is None:
                c = Curl(debug=False)
                with s.lock:
                    assert s.generation == generation and s.active == 1
                    s.curl = c
            self._managed_local.lease = c
            self._managed_local.lease_slot = s
            # Mandatory for native multi-threaded use; explicit same option in baseline fixture.
            c.setopt(CurlOpt.NOSIGNAL, 1)
            s.clean = False
            yield s, c
        finally:
            if c is not None:
                reset_error = None
                try:
                    # Covers setup exceptions before stock request's finally. Reset failure never IDLE.
                    c.reset()
                    clean = True
                except BaseException as exc:
                    clean = False
                    reset_error = exc
                    with s.lock:
                        s.curl = None
                    c.close()
                finally:
                    with s.lock:
                        s.clean = clean
                        s.active = 0
                        s.last = time.monotonic()
                        s.state = "IDLE" if s.curl else "EMPTY"
                        self.registry.event("release", s, clean=clean)
            else:
                with s.lock:
                    s.active = 0
                    s.state = "EMPTY"
                    self.registry.event("create_failed", s)
            self._managed_local.lease = None
            self._managed_local.lease_slot = None
            if self._life.closed:
                self.registry.retire(s, terminal=True)
                self._maybe_shutdown_executor()
            if c is not None and reset_error is not None:
                raise reset_error

    def _validate(self, kw):
        if kw.get("stream") and self.curl_infos:
            raise Unsupported("stream curl_infos require native metadata; unsupported")
        if kw.get("content_callback"):
            raise Unsupported("custom callbacks unreviewed")
        if kw.get("multipart") is not None and (
            kw.get("stream") or not isinstance(kw["multipart"], CurlMime)
        ):
            raise Unsupported("only buffered CurlMime supported")
        allowed = {CurlOpt.NOSIGNAL, CurlOpt.TCP_KEEPALIVE, CurlOpt.CONNECTTIMEOUT_MS}
        if set(self.curl_options) - allowed:
            raise Unsupported("unreviewed curl_options")
        if self.curl_options.get(CurlOpt.NOSIGNAL, 1) != 1:
            raise Unsupported("NOSIGNAL must be1")

    def _request_once(self, *a, **kw):
        bound = _SIGNATURE.bind(self, *a, **kw)
        bound.apply_defaults()
        values = dict(bound.arguments)
        values.pop("self")
        self._validate(values)
        with self._multipart_owner(values.get("multipart")), self._lease() as (s, c):
            self._managed_local.request_url = urljoin(
                self.base_url or "", values["url"]
            )
            if values.get("stream"):
                from of_session_stream import stream_once

                return stream_once(self, **values)
            return super()._request_once(**values)

    def _parse_response(
        self,
        c,
        buffer,
        header_buffer,
        default_encoding,
        discard_cookies,
        *,
        request_url=None,
    ):
        with self._metadata_lock:
            response = super()._parse_response(
                c, buffer, header_buffer, default_encoding, True
            )
            if isinstance(c, Curl) and not (discard_cookies or self.discard_cookies):
                # Preserve each redirect response's scope and duplicate header order.
                url = request_url or self._managed_local.request_url
                blocks = []
                for line in header_buffer.getvalue().splitlines():
                    if line.startswith(b"HTTP/"):
                        blocks.append([line, []])
                    elif line and blocks:
                        blocks[-1][1].append(line)
                for status, lines in blocks:
                    code = int(status.split()[1])
                    if code < 200:
                        continue
                    headers = Headers(lines)
                    for event in response_cookie_events(url, headers):
                        if not _supported_cookie_scope(url, event.domain):
                            continue
                        for cookie in list(self._cookies.jar):
                            if (
                                cookie.name,
                                cookie.domain.lstrip(".").lower(),
                                cookie.path,
                            ) == event.key:
                                self._cookies.jar.clear(
                                    cookie.domain, cookie.path, cookie.name
                                )
                        if not event.delete:
                            cookie = cookie_from_row(event.row())
                            if cookie is not None:
                                self._cookies.jar.set_cookie(cookie)
                    if 300 <= code < 400 and headers.get("location"):
                        url = urljoin(url, headers["location"])
            return response

    def upkeep(self):
        with self._lease() as (_, c):
            return c.upkeep()

    def ws_connect(self, *a, **kw):
        raise Unsupported("WebSocket lifecycle not covered")

    def close(self):
        with self._life.lock:
            self._life.closed = True
            self._closed = True
        for s in list(self._slots):
            self.registry.retire(s, terminal=True)
        self._maybe_shutdown_executor()

    def drain(self, timeout=5):
        self.close()
        until = None if timeout is None else time.monotonic() + timeout
        while any(s.active or s.pins or s.retiring for s in self._slots):
            self.registry.finish_completed_streams(self)
            if until is not None and time.monotonic() >= until:
                raise TimeoutError("managed drain still has owners")
            time.sleep(0.01)
        executor = self._executor
        if executor is not None:
            if threading.current_thread() in executor._threads:
                raise Unsupported("executor must be joined by shutdown owner")
            executor.shutdown(wait=True)

    def _maybe_shutdown_executor(self):
        if self._life.closed and all(not s.active and not s.pins for s in self._slots):
            with self._executor_lock:
                if self._executor is not None:
                    self._executor.shutdown(wait=False)


def _supported_cookie_scope(url, domain):
    """OnlyFans permits its parent domain; other origins get exact-host cookies.

    This adapter is not a general browser/PSL implementation. In particular,
    a.co.uk cannot publish a co.uk cookie for another account's origin.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    domain = domain.lstrip(".").lower()
    return domain == host or (
        (host == "onlyfans.com" or host.endswith(".onlyfans.com"))
        and (domain == "onlyfans.com" or domain.endswith(".onlyfans.com"))
    )
