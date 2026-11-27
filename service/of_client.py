from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from contextvars import ContextVar
from typing import Any, Callable, Literal, NamedTuple
from urllib.parse import urlsplit

from curl_cffi import requests
from curl_cffi.const import CurlECode

import accounts as account_registry
import live_rev
import of_call_counter
import of_pacing
import proxy_health
import account_health
import proxies as proxy_registry
import send_tripwire
from of_managed_session import ManagedSession
from of_cookie_events import apply_cookie_events, cookie_from_row, response_cookie_events
from of_origin import IMPERSONATE, OF_API_ORIGIN, OF_WEB_ORIGIN
from of_rich_text import escape_as_of_html, has_html, is_of_html, of_plain, sanitize_of_html
from of_signer import sign

log_of = logging.getLogger("of-client")

# Automation lane only (set per run_once, copied into to_thread); human sends never set it, the 1:1 composer only warns.
OUTBOUND_TEXT_GUARD: ContextVar[Callable[[str], str] | None] = ContextVar(
    "of_outbound_text_guard", default=None)

# A person is waiting on this call: server._proxy sets it for an /api/of/* request
# that is not `X-Priority: background`. Its GETs (and their x-hash warmup) then get
# INTERACTIVE_RETRY instead of _proxy_retry's ~6 s, so a dead proxy answers the
# Fan List / bell / thread in about a second (prod 2026-10-28: 5/5 attempts on
# chats and notifications reads). Writes keep the full policy whoever asks, and
# so does everything with no request (ingest scans, automations).
INTERACTIVE_READ: ContextVar[bool] = ContextVar("of_interactive_read", default=False)

# One timed relay read's counters (server._of_read_timing sets the dict; its log line
# reads it). `_signed_slot` adds its wait and a call count; server._proxy the lane
# wait and the call's time. None: not timed. asyncio.to_thread copies the context,
# so the worker thread fills the route's own dict. Logging only, never raises.
READ_TIMING: ContextVar[dict | None] = ContextVar("of_read_timing", default=None)


def timing_add(key: str, seconds: float) -> None:
    try:
        t = READ_TIMING.get()
        if t is not None:
            t[key] = t.get(key, 0.0) + seconds
    except Exception:  # noqa: BLE001 — a timing line must never fail a read
        pass


class RetryPolicy(NamedTuple):
    tries: int
    pause_s: float
    counts: bool


FULL_RETRY = RetryPolicy(5, 0.4, True)
# Gives up in ~1 s and does not count toward proxy DOWN: three land inside prod's 0-32 s CONNECT-403 blips.
INTERACTIVE_RETRY = RetryPolicy(2, 0.2, False)


class Retry(NamedTuple):
    pause: float


class Raise(NamedTuple):
    count_health: bool


# Reads exc and raise-from causes only, never __context__: an error raised while handling a refusal may have reached OF (send once).
def proxy_refused(exc: BaseException) -> bool:
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, requests.exceptions.ProxyError):
            return not os.environ.get("OI_CELL_MAP") or before_tunnel(e)
        e = e.__cause__
    return False


_TUNNEL_REFUSED = re.compile(r"CONNECT tunnel failed, response \d{3}")


# A Send claim's second attempt: only a proxy that answered CONNECT with a refusal, an unresolvable proxy or a refused TCP connect proves nothing reached OF.
def before_tunnel(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(exc, requests.exceptions.ProxyError):
        return code == CurlECode.COULDNT_RESOLVE_PROXY or bool(_TUNNEL_REFUSED.search(str(exc)))
    return isinstance(exc, requests.exceptions.ConnectionError) and code == CurlECode.COULDNT_CONNECT


ExcKind = Literal["proxy", "couldnt_connect", "connection"]


def retry_step(policy: RetryPolicy, attempt: int, exc_kind: ExcKind, proxied: bool,
               rng: Callable[[], float] | None = None) -> Retry | Raise:
    if exc_kind == "proxy":
        if attempt < policy.tries - 1:
            b = policy.pause_s * 2 ** attempt
            return Retry(b / 2 + (rng or random.random)() * b / 2)
        return Raise(policy.counts)
    if exc_kind == "couldnt_connect":
        return Raise(bool(policy.counts and proxied))
    return Raise(False)


CF_COOKIES = frozenset({"__cf_bm", "_cfuvid", "cf_clearance"})
# Held by every in-place session_*.json rewrite; a capture writes a NEW file.
_SESSION_WRITE_LOCK = threading.Lock()


# Re-read at write time under the lock; mkstemp 0600 + os.replace (session holds auth cookies, never write through an existing file).
def update_session_file(path: Path, mutate: Callable[[dict], bool | None]) -> None:
    with _SESSION_WRITE_LOCK:
        data = json.loads(path.read_text())
        if mutate(data) is False:
            return
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# Guard reads markup bodies as their plain text so a banned word can neither hide behind tags nor trip on a class name.
def _guard_outbound(text, *, chat=False):
    guard = OUTBOUND_TEXT_GUARD.get()
    if guard is None:
        return text
    if not (is_of_html(text) if chat else has_html(text)):
        return guard(text)
    guard(of_plain(text))
    return text


def _short_path(url: str) -> str:
    try:
        s = urlsplit(url)
        return s.path or url
    except Exception:
        return url[:120]


# In-process only: a write made in a runner subprocess waits out the cache TTL.
_WRITE_INVALIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/api2/v2/users/me", ("users_me",)),
    ("/api2/v2/subscriptions/bundles", ("users_me",)),
    ("/api2/v2/promotions", ("users_me",)),
    ("/api2/v2/payouts/requests", ("payouts", "users_me")),
)


# Never raises: OF already accepted the write; a cache bust must not turn that into an error.
def _invalidate_after_write(account_id: str, url: str) -> None:
    try:
        path = _short_path(url)
        hit = {ns for prefix, names in _WRITE_INVALIDATES
               if path == prefix or path.startswith(prefix + "/") for ns in names}
        if hit:
            import relay_cache
            for ns in hit:
                relay_cache.invalidate(ns, str(account_id))
    except Exception:  # noqa: BLE001
        log_of.warning("cache_invalidate_after_write_failed account=%s url=%s",
                       account_id, _short_path(url), exc_info=True)


def _observe_consent(account_id: str, method: str, url: str, json_body: dict | None, r) -> None:
    try:
        import consent_notices
        consent_notices.observe(account_id, method, url, json_body, r)
    except Exception:  # noqa: BLE001
        log_of.warning("consent_observe_failed account=%s", account_id, exc_info=True)


def _observe_unread_total(account_id: str, method: str, url: str, r, asked_at: int) -> None:
    unread_total = sys.modules.get("unread_total")
    if unread_total is None or not unread_total.ENABLED:
        return
    try:
        unread_total.observe_response(account_id, method, url, r, asked_at)
    except Exception:  # noqa: BLE001
        log_of.warning("unread_total_observe_failed account=%s", account_id, exc_info=True)


def _err_kind(e: BaseException) -> str:
    code = getattr(e, "code", None)
    try:
        code = int(code) if code is not None else "-"
    except (TypeError, ValueError):
        code = "-"
    return f"type={type(e).__name__} curl={code}"


APP_TOKEN = "33d57ade8c02dbc5a333db99ff9ae26a"
API_BASE = f"{OF_WEB_ORIGIN}/api2/v2"
CHAT_MEDIA_KINDS = ("photos", "videos", "audios")
HASH_BASE = f"{OF_API_ORIGIN}/hash" if OF_API_ORIGIN else "https://cdn2.onlyfans.com/hash"
DEFAULT_TIMEOUT_S = 30


OF_CDN_SUFFIXES = (
    ".onlyfans.com",
    ".ofcdn.com",
    ".mycdn.dev",
)


HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE / "sessions"


_SIGNED_RETIRED = "signed session retired; retry with current account session"


class OFAPIError(Exception):
    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response
        self.of_client = None


# Every later file would be refused the same way (creator and fan account not subscribed), so a vault import stops on the first.
class FanSendRefused(Exception):
    pass


class OFDeniedError(OFAPIError):
    pass


class OFDeactivatedError(OFDeniedError):
    pass


class OFDispatchRefused(OFDeniedError):
    def __init__(self, reason: str):
        super().__init__(f"refused before dispatch: {reason}")
        self.reason = reason


# Not the account's fault (no pause, no session_dead); a multi-request write may have landed its earlier requests.
class OFSessionRetired(OFDeniedError):
    def __init__(self, msg: str = _SIGNED_RETIRED):
        super().__init__(msg)


class OFSignedPoolBusy(OFSessionRetired):
    def __init__(self):
        super().__init__("signed session pool busy")


# Calls that end or report on the Creator's own OF account; no route makes one today, this keeps a future route from it.
_DENIED_API_PATHS = ("/api2/v2/users/logout", "/api2/v2/users/delete/request", "/api2/v2/log")
_SESSIONS_PATH = "/api2/v2/sessions"


def _denied(method: str, url: str) -> str | None:
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path.rstrip("/")
    if host.startswith("bug") and host.endswith(".onlyfans.com"):
        return "OF bug reporter"
    under = lambda p: path == p or path.startswith(p + "/")  # noqa: E731
    for p in _DENIED_API_PATHS:
        if under(p):
            return p
    if method != "GET" and under(_SESSIONS_PATH):
        return f"{method} {_SESSIONS_PATH}"
    return None


# The one write a deactivated Creator still gets: removing a carrier takes something OFF its OnlyFans.
_CARRIER_REMOVAL: ContextVar[bool] = ContextVar("of_carrier_removal", default=False)

PRE_DISPATCH: ContextVar[Callable[[], str | None] | None] = ContextVar("of_pre_dispatch", default=None)


# OF web chat always emits a <p> wrapper; creator-to-creator sends 400 unless wrapped.
def _wrap_text_as_p(text: str) -> str:
    if not text:
        return text
    if is_of_html(text):
        return sanitize_of_html(text)
    return escape_as_of_html(text, br="<br />")


# OF's composer always emits the rf* arrays together: a send body declares all three or none.
_RF_KEYS = ("rfTag", "rfGuest", "rfPartner")


# None = we added nothing of our own, do not retry; keep=[] = retry keeping nobody.
class _CoTagRetry(NamedTuple):
    keep: list[int]
    native_rf: bool


# Native rf* arrays stay through an empty write (omitting them 400s creator-to-creator sends); ones we introduced come back out.
def _write_tag_block(body: dict, ids: list[int], *, native_rf: bool) -> None:
    if ids:
        body["userTags"] = list(ids)
    else:
        body.pop("userTags", None)
    if ids or native_rf:
        body["rfTag"] = list(ids)
        body.setdefault("rfGuest", [])
        body.setdefault("rfPartner", [])
    else:
        for key in _RF_KEYS:
            body.pop(key, None)


from of_upload import (  # noqa: E402
    UploadMixin, CARRIER_DAYS, UploadClaim, VAULT_MARKER, _CARRIER_MIN_GAP_S,
    _CARRIER_MISSING_GRACE_S, _CONVERT_TIMEOUT_S, _HASH_CHUNK,
    _PART_CONCURRENCY, _PART_SIZE, _S3_BASE, convert_rejected, post_is_gone,
    remove_carrier, s3_etag_and_md5,
)
from of_reads import ReadsMixin  # noqa: E402
from of_sends import SendsMixin  # noqa: E402


class _Transport:
    session_path: Path | None = None
    _signed_ok: bool = True
    account_id: str | None = None
    proxy_url: str | None = None
    proxy_label: str | None = None
    SIGNED_SLOTS = 8
    SIGNED_WAIT_S = DEFAULT_TIMEOUT_S * FULL_RETRY.tries
    _signed_slots: threading.BoundedSemaphore | None = None
    _signed_retired: bool = False

    def __init__(self, session_dict: dict, *, proxies: dict | None = None,
                 proxy_label: str | None = None,
                 timeout_s: int = DEFAULT_TIMEOUT_S):
        h = session_dict["headers"]
        rules = session_dict["signing"]["rules"]
        for k in ("static_param", "start", "end", "checksum_indexes", "checksum_constant"):
            if rules.get(k) in (None, ""):
                raise ValueError(
                    f"Session signing.rules missing/empty: {k}. "
                    f"Re-link the account (POST /admin/session/bootstrap)."
                )

        self.user_id = str(h["user_id"])
        self.x_bc = h["x_bc"]
        self.x_of_rev = h["x_of_rev"]
        self.user_agent = h["user_agent"]
        self.rules = rules
        self.timeout_s = timeout_s
        self.proxy_label = proxy_label
        self.proxy_url: str | None = (proxies or {}).get("https") or (proxies or {}).get("http")
        self.account_id = str(h["user_id"])

        self.http = ManagedSession(impersonate=IMPERSONATE)
        self._signed_slots = threading.BoundedSemaphore(self.SIGNED_SLOTS)
        if proxies:
            self.http.proxies.update(proxies)

        for row in session_dict.get("cookies", []):
            cookie = cookie_from_row(row)
            if cookie is not None:
                self.http.cookies.jar.set_cookie(cookie)
        self.session_path: Path | None = None
        self._signed_ok = bool(session_dict["signing"].get("signed_ok_at"))

        self._x_hash: str | None = None

    @contextmanager
    def _signed_slot(self):
        slots = self._signed_slots
        t0 = time.monotonic()
        deadline = t0 + self.SIGNED_WAIT_S
        while True:
            if self._signed_retired:
                raise OFSessionRetired()
            left = deadline - time.monotonic()
            if slots is None or slots.acquire(timeout=max(0.0, min(left, 0.25))):
                break
            if left <= 0.25:
                timing_add("signed_wait_s", time.monotonic() - t0)
                raise OFSignedPoolBusy()
        timing_add("signed_wait_s", time.monotonic() - t0)
        timing_add("of_calls", 1)
        try:
            if self._signed_retired:
                raise OFSessionRetired()
            yield
        finally:
            if slots is not None:
                slots.release()

    def close_signed_sessions(self) -> None:
        self._signed_retired = True


    @classmethod
    def from_session_file(cls, path: str | Path, **kw) -> "OFClient":
        path = Path(path)
        data = json.loads(path.read_text())
        if "proxies" not in kw and "proxy_label" not in kw:
            account_id = path.parent.name
            reg = proxy_registry.registry()
            eg = proxy_registry.egress(reg, account_id, path.name)
            if (isinstance(eg, proxy_registry.Direct)
                    and account_id in account_health.write_gate_snapshot()
                    and proxy_registry.pool_entries(reg)):
                eg = proxy_registry.Refuse("deactivated Creator is missing a proxy binding")
            if isinstance(eg, proxy_registry.Refuse):
                log_of.warning("client_egress_refused account=%s reason=%s", account_id, eg.reason)
                raise proxy_registry.EgressRefused(eg.reason)
            if proxy_registry.CELLS and isinstance(eg, proxy_registry.Direct):
                raise proxy_registry.no_proxy(account_id, "client")
            p = eg.entry if isinstance(eg, proxy_registry.Proxy) else None
            if p is not None:
                kw["proxies"] = proxy_registry.proxies_dict_for_requests(p)
                kw["proxy_label"] = p["label"]
            log_of.info("client_egress account=%s proxy=%s(%s)%s", account_id,
                        p["label"] if p else "—", f"{p['host']}:{p['port']}" if p else "direct",
                        " registry=torn" if isinstance(reg, proxy_registry.Torn) else "")
        client = cls(data, **kw)
        client.session_path = path
        return client

    @classmethod
    def from_account(cls, account_id: str, **kw) -> "OFClient":
        path = account_registry.latest_session_path(account_id)
        if path is None:
            raise FileNotFoundError(
                f"Account {account_id!r} has no captured session. "
                f"Run the bootstrap (paste-curl) for this account first."
            )
        return cls.from_session_file(path, **kw)

    @classmethod
    def from_latest_session(cls, **kw) -> "OFClient":
        aid = account_registry.get_active_account_id()
        if not aid:
            raise FileNotFoundError(
                "No account has a captured session yet. "
                "POST /admin/session/bootstrap first."
            )
        return cls.from_account(aid, **kw)


    def egress_ip(self, timeout_s: int = 10) -> str | None:
        try:
            r = self._proxy_retry(
                lambda: self.http.get("https://api.ipify.org", timeout=timeout_s),
                what="egress-ip")
            if r.ok:
                return r.text.strip()
        except Exception:
            pass
        return None


    # Runs inside _signed_headers ahead of _http_call's retry, so it needs its own CONNECT-403 retry or one proxy blip fails the whole tick.
    def _ensure_x_hash(self, policy: RetryPolicy = FULL_RETRY) -> str:
        if self._x_hash:
            return self._x_hash
        r = self._proxy_retry(lambda: self.http.get(
            f"{HASH_BASE}/?u={self.user_id}",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://onlyfans.com/",
                "User-Agent": self.user_agent,
            },
            timeout=self.timeout_s,
        ), what="x-hash", policy=policy)
        r.raise_for_status()
        self._x_hash = r.text.strip()
        return self._x_hash


    def _build_url(self, path_or_url: str, params: dict | None) -> str:
        url = path_or_url if path_or_url.startswith("http") else f"{OF_WEB_ORIGIN}{path_or_url}"
        if params:
            from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
            p = urlparse(url)
            q = parse_qsl(p.query, keep_blank_values=True)
            q.extend(params.items())
            url = urlunparse(p._replace(query=urlencode(q, doseq=True)))
        return url

    def _signed_headers(self, url: str) -> dict:
        sig = sign(url, self.user_id, self.rules)
        return {
            "Accept": "application/json, text/plain, */*",
            "App-Token": APP_TOKEN,
            "Sign": sig["sign"],
            "Time": sig["time"],
            "User-ID": self.user_id,
            "X-BC": self.x_bc,
            "X-Hash": self._ensure_x_hash(),
            "X-OF-Rev": self.x_of_rev,
            "User-Agent": self.user_agent,
            "Referer": "https://onlyfans.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    def get(self, path_or_url: str, *, params: dict | None = None) -> requests.Response:
        url = self._build_url(path_or_url, params)
        return self._http_call("GET", url)

    def _note_signed_ok(self, url: str, r) -> None:
        if (self._signed_ok or self.session_path is None or "/api2/" not in url
                or not 200 <= getattr(r, "status_code", 0) < 300):
            return
        self._signed_ok = True
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        def _stamp(data: dict) -> None:
            signing = data.setdefault("signing", {})
            if signing.get("rules") == self.rules:
                signing["signed_ok_at"] = at
        try:
            update_session_file(self.session_path, _stamp)
            import sign_rules
            sign_rules.request_refresh(f"verified {self.account_id}")
        except Exception:
            log_of.warning("signed_ok_stamp_failed account=%s", self.account_id, exc_info=True)

    def _persist_cf_cookies(self, r) -> None:
        if self.session_path is None:
            return
        try:
            events = tuple(event for event in response_cookie_events(r.url, r.headers)
                           if event.name in CF_COOKIES)
            if not events:
                return
            update_session_file(self.session_path,
                                lambda data: apply_cookie_events(data.setdefault("cookies", []), events))
        except Exception:
            log_of.warning("cf_cookies_persist_failed account=%s", self.account_id,
                           exc_info=True)

    def _http_call(self, method: str, url: str, *,
                   json_body: dict | None = None) -> requests.Response:
        if (reason := _denied(method, url)) is not None:
            log_of.error("denied account=%s method=%s url=%s (%s)",
                         self.account_id, method, _short_path(url), reason)
            raise OFDeniedError(f"refused: {method} {_short_path(url)} ({reason})")
        # A deactivated Creator gets no OF write from any route or job; reads stay open for the owner's history.
        if method != "GET" and not (method == "DELETE" and _CARRIER_REMOVAL.get()):
            import account_health
            if account_health.refuses_writes(self.account_id):
                log_of.warning("deactivated account=%s method=%s url=%s refused",
                               self.account_id, method, _short_path(url))
                raise OFDeactivatedError(f"refused: {method} {_short_path(url)} (Creator deactivated)")
        # DC proxies sporadically 403 on CONNECT then work again; retries reuse the SAME self.http session (sticky IP, no rotation).
        policy = INTERACTIVE_RETRY if method == "GET" and INTERACTIVE_READ.get() else FULL_RETRY
        try:
            check = PRE_DISPATCH.get() if method != "GET" else None

            def _do() -> requests.Response:
                # Signed per attempt: a retry can come seconds later, and Sign/Time must be fresh.
                headers = self._signed_headers(url)
                if json_body is not None:
                    headers["Content-Type"] = "application/json"
                if method == "GET":
                    return self.http.get(url, headers=headers, timeout=self.timeout_s)
                # A guarded write's last check, on every attempt, after every wait (slot, warm-up,
                # back-off pause, telemetry, signing): a refusal sends nothing.
                if check is not None and (why := check()):
                    raise OFDispatchRefused(why)
                return send_tripwire.leave(
                    lambda: self.http.request(method, url, json=json_body, headers=headers, timeout=self.timeout_s),
                    delivery=True, before_tunnel=before_tunnel,
                )
            with self._signed_slot():
                # The x-hash warmup runs its own _proxy_retry here, never nested in the one below.
                self._ensure_x_hash(policy=policy)
                asked_at = int(time.time() * 1000)
                try:
                    r = self._proxy_retry(_do, what=f"{method} {_short_path(url)}", policy=policy)
                # Refused right before an attempt: never sent.
                except OFDispatchRefused:
                    raise
                except Exception:
                    of_call_counter.record(self.account_id, method, url, None)
                    raise
            of_call_counter.record(self.account_id, method, url, r.status_code)
            try:
                rev_hdr = r.headers.get("x-of-rev") or r.headers.get("X-OF-Rev")
                if rev_hdr:
                    live_rev.note(rev_hdr, source=f"response:{self.account_id}")
            except Exception:
                log_of.warning(
                    "live_rev.note failed account=%s url=%s",
                    self.account_id, _short_path(url), exc_info=True,
                )
            self._persist_cf_cookies(r)
            self._note_signed_ok(url, r)
            proxy_health.record(self.proxy_label, True)
            _observe_consent(self.account_id, method, url, json_body, r)
            _observe_unread_total(self.account_id, method, url, r, asked_at)
            return r
        except requests.exceptions.ProxyError as e:
            log_of.warning(
                "proxy_error account=%s proxy=%s(%s) method=%s url=%s %s err=%s",
                self.account_id, self.proxy_label or "—",
                self._proxy_ip(), method, _short_path(url), _err_kind(e), str(e)[:200],
            )
            raise
        except requests.exceptions.Timeout as e:
            log_of.warning(
                "timeout account=%s proxy=%s(%s) method=%s url=%s %s err=%s",
                self.account_id, self.proxy_label or "—", self._proxy_ip(), method,
                _short_path(url), _err_kind(e), str(e)[:200],
            )
            raise
        except Exception as e:
            log_of.warning(
                "http_error account=%s proxy=%s(%s) method=%s url=%s %s err=%s",
                self.account_id, self.proxy_label or "—", self._proxy_ip(), method,
                _short_path(url), _err_kind(e), str(e)[:200],
            )
            raise

    def _proxy_ip(self) -> str:
        if not self.proxy_url:
            return "direct"
        try:
            # Last "@": a password may hold one.
            after_at = self.proxy_url.rsplit("@", 1)[-1]
            return after_at
        except Exception:
            return "?"

    def _attempt(self, fn):
        label = self.proxy_label
        proxy_health.attempt_start(label)
        refused = None
        try:
            r = fn()
            refused = False
            return r
        except requests.exceptions.ProxyError:
            refused = True
            raise
        finally:
            proxy_health.attempt_end(label, refused)

    def require_proxy(self, where: str) -> None:
        if not self.proxy_url:
            raise proxy_registry.no_proxy(self.account_id, where)
        proxy_registry.require_proxy(self.account_id, where, self.session_path.name if self.session_path else None)

    def _proxy_retry(self, fn, *, what: str = "", policy: RetryPolicy = FULL_RETRY):
        tries = policy.tries
        for attempt in range(tries):
            if proxy_registry.CELLS:
                self.require_proxy("call")
            try:
                return self._attempt(fn)
            # ProxyError is not a ConnectionError in curl_cffi (siblings), so this one clause dispatches like two ordered ones.
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
                kind: ExcKind
                if isinstance(e, requests.exceptions.ProxyError):
                    kind = "proxy"
                elif getattr(e, "code", None) == CurlECode.COULDNT_CONNECT:
                    kind = "couldnt_connect"
                else:
                    kind = "connection"
                step = retry_step(policy, attempt, kind, bool(self.proxy_url))
                if isinstance(step, Retry):
                    log_of.info(
                        "proxy_error_retry account=%s proxy=%s(%s) attempt=%d/%d %s %s err=%s",
                        self.account_id, self.proxy_label or "—", self._proxy_ip(),
                        attempt + 1, tries, what, _err_kind(e), str(e)[:200],
                    )
                    time.sleep(step.pause)
                    continue
                if step.count_health:
                    proxy_health.record(self.proxy_label, False, str(e))
                raise

    def pace_key(self) -> str:
        # Own proxy_url, never a fresh account->proxy lookup: after a proxy move an outstanding client keeps its old exit's slot.
        return proxy_registry.egress_identity(self.proxy_url, proxy_registry.registry())

    def get_json(self, path_or_url: str, **kw) -> Any:
        return of_pacing.paced(self.account_id, lambda: self._get_json(path_or_url, **kw), self.pace_key)

    def _get_json(self, path_or_url: str, **kw) -> Any:
        r = self.get(path_or_url, **kw)
        if not r.ok:
            raise OFAPIError(
                f"{r.status_code} for {r.url}\n{r.text[:500]}",
                response=r,
            )
        return r.json()

    def request(self, method: str, path_or_url: str, *,
                json_body: dict | None = None,
                params: dict | None = None) -> requests.Response:
        url = self._build_url(path_or_url, params)
        return self._http_call(method.upper(), url, json_body=json_body)

    def request_json(self, method: str, path_or_url: str, **kw) -> Any:
        r = self.request(method, path_or_url, **kw)
        if not r.ok:
            raise OFAPIError(f"{r.status_code} for {r.url}\n{r.text[:500]}", response=r)
        if method.upper() != "GET":
            _invalidate_after_write(self.account_id, path_or_url)
        if r.status_code == 204 or not r.text:
            return None
        return r.json()

    def post(self, path_or_url: str, **kw) -> requests.Response:
        return self.request("POST", path_or_url, **kw)

    def post_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("POST", path_or_url, **kw)

    def put_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("PUT", path_or_url, **kw)

    def delete_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("DELETE", path_or_url, **kw)



class OFClient(_Transport, ReadsMixin, SendsMixin, UploadMixin):
    pass
