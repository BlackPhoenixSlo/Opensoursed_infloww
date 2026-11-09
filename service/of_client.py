"""
OnlyFans HTTP client.

Loads a captured session (from POST /admin/session/bootstrap) and
wraps `requests.Session` with the headers OF expects on every signed call:
  Sign, Time   — generated per request via of_signer.sign()
  User-ID, X-BC, X-OF-Rev, User-Agent  — pinned from the captured session
  X-Hash       — fetched once from cdn2.onlyfans.com/hash/?u={user_id}
  App-Token    — hardcoded (OF web client constant)

  client = OFClient.from_latest_session()
  client.me()
  client.list_chats(limit=10)
  client.get_messages(chat_id="...")
"""
from __future__ import annotations

import json
import logging
import os
from collections import deque
import random
import tempfile
import threading
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from contextvars import ContextVar
from typing import Any, Callable, Literal, NamedTuple
from urllib.parse import urlsplit

from curl_cffi import requests  # Chrome TLS fingerprint via libcurl-impersonate
from curl_cffi.const import CurlECode

import accounts as account_registry
import live_rev
import of_call_counter
import of_pacing
import proxy_health
import proxies as proxy_registry
from of_origin import IMPERSONATE, OF_API_ORIGIN, OF_WEB_ORIGIN
from of_rich_text import escape_as_of_html, has_html, is_of_html, of_plain, sanitize_of_html
from of_signer import sign

# Dedicated logger so proxy/upstream errors are filterable from the rest
# of the relay log noise: `grep "of-client" /tmp/of-relay.log`.
log_of = logging.getLogger("of-client")

# The automation lane's outbound word guard (Growth > Sensitive words merged with
# the account's banned words). automation_executor.run_once sets it for the length
# of one run; asyncio.to_thread copies the context, so every send/post an
# automation makes passes through it whichever helper it went through. Human
# sends never set it: the 1:1 composer only warns, as Infloww's does.
OUTBOUND_TEXT_GUARD: ContextVar[Callable[[str], str] | None] = ContextVar(
    "of_outbound_text_guard", default=None)

# A person is waiting on this call: server._proxy sets it for an /api/of/* request
# that is not `X-Priority: background`. Its GETs (and their x-hash warmup) then get
# INTERACTIVE_RETRY instead of _proxy_retry's ~6 s, so a dead proxy answers the
# Fan List / bell / thread in about a second (prod 2026-10-28: 5/5 attempts on
# chats and notifications reads). Writes keep the full policy whoever asks, and
# so does everything with no request (ingest scans, automations).
INTERACTIVE_READ: ContextVar[bool] = ContextVar("of_interactive_read", default=False)


class RetryPolicy(NamedTuple):
    """How `_proxy_retry` treats a refused proxy: `tries` attempts with pauses
    equal-jittered (half to all of `pause_s` doubling), and whether its final failure `counts` toward
    proxy_health's DOWN_AFTER."""
    tries: int
    pause_s: float
    counts: bool


# Everything by default: 5 tries, pauses jittered in [b/2, b) for b = 0.4-3.2 s (3-6 s). Its final failure counts.
FULL_RETRY = RetryPolicy(5, 0.4, True)
# A read someone waits on: 2 tries, one 0.1-0.2 s pause. Its failure does NOT count
# toward marking the proxy bad: it gives up inside ~1 s, so three of them land
# within any of prod's 0-32 s CONNECT-403 blips (docs/adr/0030).
INTERACTIVE_RETRY = RetryPolicy(2, 0.2, False)


class Retry(NamedTuple):
    """retry_step: sleep `pause` seconds, then try again."""
    pause: float


class Raise(NamedTuple):
    """retry_step: re-raise; first record a proxy_health failure if `count_health`."""
    count_health: bool


def proxy_refused(exc: BaseException) -> bool:
    """The proxy refused before the tunnel opened (curl_cffi raises ProxyError
    only then: curl 5 resolve-proxy, 97 proxy/SOCKS handshake, 56 on CONNECT,
    e.g. IPRoyal's 403 once `_proxy_retry` gave up), so the call never got to OF.
    Read off `exc` and its `raise ... from` causes only, never `__context__`:
    an error merely raised while handling a refusal is about its own call,
    which may have reached OF (send once)."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, requests.exceptions.ProxyError):
            return True
        e = e.__cause__
    return False


# The three failures `_proxy_retry` tells apart (see retry_step).
ExcKind = Literal["proxy", "couldnt_connect", "connection"]


def retry_step(policy: RetryPolicy, attempt: int, exc_kind: ExcKind, proxied: bool,
               rng: Callable[[], float] | None = None) -> Retry | Raise:
    """`_proxy_retry`'s decision after 0-based `attempt` failed. `exc_kind`:
    "proxy" (ProxyError: retried until the last try, whose failure counts under
    a `counts` policy; the pause is equal jitter: half the doubling ceiling
    `b = pause_s * 2**attempt` plus `rng()` (default `random.random`, [0, 1))
    times the other half, so accounts behind one refusing proxy do not retry in
    lockstep, yet a burst cannot burn all tries at once), "couldnt_connect" (curl 7: never
    retried; counts only on a proxied client under a `counts` policy) or
    "connection" (any other ConnectionError: raised, never counted)."""
    if exc_kind == "proxy":
        if attempt < policy.tries - 1:
            b = policy.pause_s * 2 ** attempt
            return Retry(b / 2 + (rng or random.random)() * b / 2)
        return Raise(policy.counts)
    if exc_kind == "couldnt_connect":
        return Raise(bool(policy.counts and proxied))
    return Raise(False)


# Cloudflare's cookies, which OF's responses refresh (see OFClient._persist_cf_cookies).
CF_COOKIES = frozenset({"__cf_bm", "_cfuvid", "cf_clearance"})
# Held by every in-process rewrite of an existing session_*.json — see
# update_session_file. (A capture writes a NEW timestamped file; nothing else
# rewrites one in place.)
_SESSION_WRITE_LOCK = threading.Lock()


def update_session_file(path: Path, mutate: Callable[[dict], None]) -> None:
    """Read-modify-write one session file in place. Under _SESSION_WRITE_LOCK,
    re-read at write time (so a concurrent writer's change is kept, not
    overwritten with a stale copy), written to a fresh mkstemp file (0600,
    O_EXCL, random name: never through a pre-existing file or link; the session
    holds the account's auth cookies), fsync'd, and os.replace'd, so a reader
    never sees half a file and a crash never leaves an empty one. Raises on
    failure; the old file is then untouched and the temp file removed."""
    with _SESSION_WRITE_LOCK:
        data = json.loads(path.read_text())
        mutate(data)
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


def _cookie_domain(domain: str | None) -> str:
    """Cookie domain for matching: `.onlyfans.com` and a host-only
    `onlyfans.com` name the same cookie slot in a session file."""
    return (domain or ".onlyfans.com").lstrip(".").lower()


def _guard_outbound(text, *, chat=False):
    """`text` as the guard leaves it, or the guard's exception (blocked).

    The guard reads what the fan will: a text the send's boundary reads as
    markup is read as its plain text (`of_plain`), once, so a banned word can
    neither hide behind tags nor trip on a class name; it goes on unchanged and
    the send's own boundary rewrites it. Which texts that is follows the path:
    `of_text` (the mass, queue and post bodies, the Fansly shim's plain text)
    rewrites every `has_html` text; the chat send (`chat=True`,
    `_wrap_text_as_p`) only OF markup, and escapes anything else whole, so the
    fan reads bare tags (`<a href=word>x</a>`) as written and the guard reads
    them so too.
    Block mode only: `load_banned_words` pins it, so a markup body is never
    masked."""
    guard = OUTBOUND_TEXT_GUARD.get()
    if guard is None:
        return text
    if not (is_of_html(text) if chat else has_html(text)):
        return guard(text)
    guard(of_plain(text))
    return text


def _short_path(url: str) -> str:
    """Strip scheme/host/query so log lines stay terse: /api2/v2/chats."""
    try:
        s = urlsplit(url)
        return s.path or url
    except Exception:
        return url[:120]


# OF path an accepted write went to -> the relay's cached reads (relay_cache
# namespaces, server._account_ttl) it changes. Done here because every caller's
# write funnels through `request_json`: the routes, promotions_api, the promo
# re-arm automation. `/users/me` carries the profile, the reply-on-subscribe
# switch, `promotions` and `subscriptionBundles`, so all of those clear it.
# In-process only: a write made in a runner subprocess waits out the TTL.
_WRITE_INVALIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("/api2/v2/users/me", ("users_me",)),
    ("/api2/v2/subscriptions/bundles", ("users_me",)),
    ("/api2/v2/promotions", ("users_me",)),
    ("/api2/v2/payouts/requests", ("payouts", "users_me")),
)


def _invalidate_after_write(account_id: str, url: str) -> None:
    """Never raises: OF already accepted the write, and a cache bust must not
    turn that into an error (the entry then just waits out its TTL)."""
    try:
        path = _short_path(url)
        hit = {ns for prefix, names in _WRITE_INVALIDATES
               if path == prefix or path.startswith(prefix + "/") for ns in names}
        if hit:
            import relay_cache  # lazy: keeps the client importable on its own
            for ns in hit:
                relay_cache.invalidate(ns, str(account_id))
    except Exception:  # noqa: BLE001
        log_of.warning("cache_invalidate_after_write_failed account=%s url=%s",
                       account_id, _short_path(url), exc_info=True)


def _observe_consent(account_id: str, method: str, url: str, json_body: dict | None, r) -> None:
    """consent_notices.observe; never raises (lazy: db-backed, keeps the client importable on its own)."""
    try:
        import consent_notices
        consent_notices.observe(account_id, method, url, json_body, r)
    except Exception:  # noqa: BLE001
        log_of.warning("consent_observe_failed account=%s", account_id, exc_info=True)


def _err_kind(e: BaseException) -> str:
    """`type=<class> curl=<code>` for a failed call's log line. curl_cffi's
    errors carry libcurl's code (`curl=56` CONNECT refused, `28` timeout, `7`
    connect failed); anything else logs `curl=-`."""
    code = getattr(e, "code", None)
    try:
        code = int(code) if code is not None else "-"
    except (TypeError, ValueError):
        code = "-"
    return f"type={type(e).__name__} curl={code}"


APP_TOKEN = "33d57ade8c02dbc5a333db99ff9ae26a"   # OF web app constant
# OF_WEB_ORIGIN / OF_API_ORIGIN: of_origin.py (the ADR 0024 test seam; "" = OnlyFans).
API_BASE = f"{OF_WEB_ORIGIN}/api2/v2"
# OF web's chat gallery type tabs: the last segment of /chats/{chat_id}/media/<kind>.
CHAT_MEDIA_KINDS = ("photos", "videos", "audios")
HASH_BASE = f"{OF_API_ORIGIN}/hash" if OF_API_ORIGIN else "https://cdn2.onlyfans.com/hash"
DEFAULT_TIMEOUT_S = 30


# OnlyFans' media hosts: the only hosts the Relay fetches media bytes from
# (server's /img proxy, S4S media copies).
OF_CDN_SUFFIXES = (
    ".onlyfans.com",
    ".ofcdn.com",
    ".mycdn.dev",  # OF's media subdomains
)


HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE / "sessions"


class OFAPIError(Exception):
    """Non-2xx from OF (or upstream Cloudflare). Carries the raw response."""
    def __init__(self, message: str, response=None):
        super().__init__(message)
        self.response = response


class FanSendRefused(Exception):
    """OnlyFans refused a vault import's send to its linked fan account —
    usually "Cannot send message to this user": the creator and that account
    are not subscribed to each other. Every later file would be refused the
    same way, so the import stops on it instead of trying each one."""


class OFDeniedError(OFAPIError):
    """A call `_denied` refuses before it leaves the box (no response)."""


class OFDeactivatedError(OFDeniedError):
    """A write for a deactivated Creator, refused before it leaves the box.
    Transient for every caller: the Creator may be activated again."""


# Calls that end or report on the Creator's own OF account: logout, account
# deletion, ending login sessions, OF's client telemetry and its bug reporter.
# No relay route makes one today; this backstop keeps a future route from it.
_DENIED_API_PATHS = ("/api2/v2/users/logout", "/api2/v2/users/delete/request", "/api2/v2/log")
_SESSIONS_PATH = "/api2/v2/sessions"
_LEDGER_PATH = "/payouts/transactions"   # its background pages: paced per bound proxy too (of_pacing)


def _denied(method: str, url: str) -> str | None:
    """Why `method url` must never be sent to OF, or None to send it."""
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


# Set by remove_carrier for its one DELETE: the only write a deactivated
# Creator still gets, because it takes something OFF its OnlyFans.
_CARRIER_REMOVAL: ContextVar[bool] = ContextVar("of_carrier_removal", default=False)


def _wrap_text_as_p(text: str) -> str:
    """OF web's chat textarea is a rich-text editor that always emits a
    `<p>…</p>` wrapper. Plain-text sends to fans work without wrapping,
    but creator-to-creator sends 400 unless wrapped — match OF web's
    body exactly here. Multi-paragraph text becomes one `<p>` with
    `<br />` separators, mirroring what the OF editor produces."""
    if not text:
        return text
    # Already HTML (OF's rich text: a picked formatted script)? Don't
    # double-wrap; keep only OF's own tags and classes (of_rich_text).
    if is_of_html(text):
        return sanitize_of_html(text)
    # Internal newlines → <br />, then wrap the whole thing (of_text's fail-closed escape is the same wrap).
    return escape_as_of_html(text, br="<br />")


# The release-form arrays, which OF's composer always emits together. A send
# body either declares all three itself (the 1:1 chat send) or none of them.
_RF_KEYS = ("rfTag", "rfGuest", "rfPartner")


class _CoTagRetry(NamedTuple):
    """What a 4xx retry needs to rebuild a send body's tag block.

    One value rather than two loose ones, because the two are only meaningful
    together: `None` is "we added nothing of our own, so do not retry", and
    that state cannot be confused with "retry, keeping nobody" (`keep=[]`).
    """
    keep: list[int]     # the OPERATOR's own picks, the only ids that survive
    native_rf: bool     # did the body declare the rf* arrays itself?


def _write_tag_block(body: dict, ids: list[int], *, native_rf: bool) -> None:
    """Put `ids` — and only `ids` — into every field a tag rides in.

    The ONE definition of the tag block's shape, called both when a send is
    built and when the 4xx retry rebuilds it from the operator's picks alone.
    Two functions writing the same fields in opposite directions is how the last
    silent drop shipped: the retry blanked what it had never set.

    `native_rf` is whether the body declared the rf* arrays itself. Those stay
    through an empty write — empty is their resting shape, and omitting them is
    what used to 400 creator-to-creator sends. The ones we INTRODUCED come back
    out instead, so a queue or wall body falls back to byte-for-byte what it
    was: if OF ever objects to the field itself on an endpoint, the cost is an
    untagged send, never a dead sender.
    """
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


# The client's parts. Imported here, after every name they take from this module
# is defined; the upload names are re-exported so `of_client.X` keeps working.
from of_upload import (  # noqa: E402
    UploadMixin, CARRIER_DAYS, UploadClaim, VAULT_MARKER, _CARRIER_MIN_GAP_S,
    _CARRIER_MISSING_GRACE_S, _CONVERT_TIMEOUT_S, _HASH_CHUNK,
    _PART_CONCURRENCY, _PART_SIZE, _S3_BASE, convert_rejected, post_is_gone,
    remove_carrier, s3_etag_and_md5,
)
from of_reads import ReadsMixin  # noqa: E402
from of_sends import SendsMixin  # noqa: E402


class _SignedSessionPool:
    """Reuse a bounded set of curl handles across executor threads for one account.

    curl_cffi's default Session keeps one handle per thread. A shared Session
    with one handle is unsafe concurrently, so each lease owns one Session
    until the whole signed call (including proxy retries) has finished.
    """

    SIZE = 8  # 5 account-lane calls, with room for direct job/automation calls
    WAIT_S = DEFAULT_TIMEOUT_S * FULL_RETRY.tries

    def __init__(self, source: requests.Session):
        self._ready = threading.Condition()
        self._available: deque[requests.Session] = deque()
        self._waiters: deque[object] = deque()
        self._closed = False
        for _ in range(self.SIZE):
            session = requests.Session(impersonate=IMPERSONATE, use_thread_local_curl=False)
            session.proxies.update(source.proxies)
            # Passing Cookies copies it in curl_cffi; passing its CookieJar
            # shares the live, internally locked jar across this account's leases.
            session.cookies = source.cookies.jar
            self._available.append(session)

    @contextmanager
    def lease(self):
        ticket = object()
        deadline = time.monotonic() + self.WAIT_S
        with self._ready:
            self._waiters.append(ticket)
            try:
                while True:
                    if self._closed:
                        raise OFAPIError("signed session retired; retry with current account session")
                    if self._waiters[0] is ticket and self._available:
                        session = self._available.popleft()
                        self._waiters.popleft()
                        self._ready.notify_all()
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise OFAPIError("signed session pool busy")
                    self._ready.wait(remaining)
            finally:
                if ticket in self._waiters:
                    self._waiters.remove(ticket)
                    self._ready.notify_all()
        try:
            yield session
        finally:
            with self._ready:
                retire = self._closed
                if not retire:
                    self._available.append(session)
                    self._ready.notify_all()
            if retire:
                session.close()

    def close(self) -> None:
        """Retire idle handles now, and each borrowed handle on its return."""
        with self._ready:
            if self._closed:
                return
            self._closed = True
            idle = list(self._available)
            self._available.clear()
            self._ready.notify_all()
        for session in idle:
            session.close()


class _Transport:
    # Class-level default: a client never built from a file (or a bare
    # __new__ one in tests) has nowhere to persist Cloudflare cookies.
    session_path: Path | None = None
    # Has a signed call with this session's rules had a 2xx from OF
    # (`signing.signed_ok_at`, see _note_signed_ok)? True on a bare client: it never stamps.
    _signed_ok: bool = True
    # A bare client's account and transport: none (of_pacing keys a walk's page on the account).
    account_id: str | None = None
    proxy_url: str | None = None
    proxy_label: str | None = None

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
        # The account this client belongs to. For single-account callers this
        # is identical to user_id; for multi-account, this is the account_id
        # (which we currently key by user_id, but they are semantically
        # distinct so the server can rename / re-key without touching OFClient).
        self.account_id = str(h["user_id"])

        # curl_cffi.requests.Session takes impersonate at construction; every
        # subsequent .get()/.post() uses that TLS profile + matching default headers.
        self.http = requests.Session(impersonate=IMPERSONATE)
        self._signed_pool_lock = threading.Lock()
        self._signed_pool: _SignedSessionPool | None = None
        self._signed_retired = False
        if proxies:
            self.http.proxies.update(proxies)

        # Replay every cookie Playwright captured (auth_id, sess, fp, etc.)
        for c in session_dict.get("cookies", []):
            self.http.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )
        # Set by from_session_file: where _persist_cf_cookies writes Cloudflare's
        # refreshed cookies back, so the next client built from disk starts warm.
        self.session_path: Path | None = None
        self._cf_seen = {(c["name"], _cookie_domain(c.get("domain"))): c["value"]
                         for c in session_dict.get("cookies", [])
                         if c.get("name") in CF_COOKIES}
        self._signed_ok = bool(session_dict["signing"].get("signed_ok_at"))

        # Fetched lazily on first signed call (it's a single GET to the CDN).
        self._x_hash: str | None = None

    def _signed_session(self):
        # Tests may inject a fake HTTP object on a bare OFClient. Production
        # sessions share the captured cookie jar and proxy configuration.
        if not isinstance(self.http, requests.Session):
            return nullcontext(self.http)
        with self._signed_pool_lock:
            if self._signed_retired:
                raise OFAPIError("signed session retired; retry with current account session")
            if self._signed_pool is None:
                self._signed_pool = _SignedSessionPool(self.http)
            pool = self._signed_pool
        return pool.lease()

    def close_signed_sessions(self) -> None:
        with self._signed_pool_lock:
            self._signed_retired = True
            pool = self._signed_pool
        if pool is not None:
            pool.close()

    # ── Constructors ────────────────────────────────────────────

    @classmethod
    def from_session_file(cls, path: str | Path, **kw) -> "OFClient":
        """Loads a session file. Auto-attaches its assigned proxy from the
        registry unless caller passes an explicit `proxies=` (escape hatch).

        Proxy lookup order:
          1. Per-account binding (assigned_account_id == path.parent.name)
             — new scheme; survives re-captures.
          2. Per-session-file binding (assigned_session == path.name)
             — legacy; remains supported for back-compat.
        A proxies.json read mid-write answers from the last good read; with
        none, proxies.EgressRefused (never direct: proxies.egress).
        """
        path = Path(path)
        data = json.loads(path.read_text())
        if "proxies" not in kw and "proxy_label" not in kw:
            # Per-account dirs live at sessions/accounts/<id>/session_*.json
            # so the immediate parent dir name is the account_id.
            account_id = path.parent.name
            reg = proxy_registry.registry()
            eg = proxy_registry.egress(reg, account_id, path.name)
            if isinstance(eg, proxy_registry.Refuse):
                log_of.warning("client_egress_refused account=%s reason=%s", account_id, eg.reason)
                raise proxy_registry.EgressRefused(eg.reason)
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
        """Load the OFClient that serves a specific account. The session lives
        at sessions/accounts/<account_id>/latest.json."""
        path = account_registry.latest_session_path(account_id)
        if path is None:
            raise FileNotFoundError(
                f"Account {account_id!r} has no captured session. "
                f"Run the bootstrap (paste-curl) for this account first."
            )
        return cls.from_session_file(path, **kw)

    @classmethod
    def from_latest_session(cls, **kw) -> "OFClient":
        """Legacy entry point: resolves the *currently-active* account and
        loads its session. Kept so single-account callers keep working."""
        aid = account_registry.get_active_account_id()
        if not aid:
            raise FileNotFoundError(
                "No account has a captured session yet. "
                "POST /admin/session/bootstrap first."
            )
        return cls.from_account(aid, **kw)

    # ── Egress probe ────────────────────────────────────────────

    def egress_ip(self, timeout_s: int = 10) -> str | None:
        """Returns the IP that OF would see for this client (proxy egress or
        direct WAN). Goes through the same curl_cffi session so we measure
        what real OF calls measure, not Python's default route."""
        try:
            r = self._proxy_retry(
                lambda: self.http.get("https://api.ipify.org", timeout=timeout_s),
                what="egress-ip")
            if r.ok:
                return r.text.strip()
        except Exception:
            pass
        return None

    # ── Internal: x-hash ────────────────────────────────────────

    def _ensure_x_hash(self, policy: RetryPolicy = FULL_RETRY) -> str:
        if self._x_hash:
            return self._x_hash
        # This warmup fires on the FIRST signed request of every fresh client
        # — once per pooled client now (see service/client_pool.py), so an
        # eviction is what re-runs it. It must get the same CONNECT-403 retry
        # as real OF calls, otherwise a single datacenter proxy blip fails the
        # whole tick/job before _http_call's _proxy_retry is ever reached (it
        # runs inside _signed_headers, ahead of the wrapped request).
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

    # ── Core signed HTTP ────────────────────────────────────────

    def _build_url(self, path_or_url: str, params: dict | None) -> str:
        url = path_or_url if path_or_url.startswith("http") else f"{OF_WEB_ORIGIN}{path_or_url}"
        if params:
            # Bake params into the URL so the signed path matches what's sent.
            from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
            p = urlparse(url)
            q = parse_qsl(p.query, keep_blank_values=True)
            q.extend(params.items())
            url = urlunparse(p._replace(query=urlencode(q, doseq=True)))
        return url

    def _signed_headers(self, url: str) -> dict:
        """Build the full header set for a signed request. Sign is fresh per call."""
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
        """Signed GET. `path_or_url` may be a full URL or an /api2/v2/... path."""
        url = self._build_url(path_or_url, params)
        return self._http_call("GET", url)

    def _note_signed_ok(self, url: str, r) -> None:
        """Stamp `signing.signed_ok_at` into the session file at the first 2xx
        a signed /api2/ call gets: proof the capture's static_param, start and
        end are right, which its samples (checksum only) can't give. Only a
        stamped session lends its rules to other accounts (sign_rules, 2.17),
        so the stamp asks for that refresh. Once per capture; never raises."""
        if (self._signed_ok or self.session_path is None or "/api2/" not in url
                or not 200 <= getattr(r, "status_code", 0) < 300):
            return
        self._signed_ok = True
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        def _stamp(data: dict) -> None:
            signing = data.setdefault("signing", {})
            if signing.get("rules") == self.rules:  # not if a refresh swapped them meanwhile
                signing["signed_ok_at"] = at
        try:
            update_session_file(self.session_path, _stamp)
            import sign_rules  # lazy: sign_rules imports this module
            sign_rules.request_refresh(f"verified {self.account_id}")
        except Exception:
            log_of.warning("signed_ok_stamp_failed account=%s", self.account_id, exc_info=True)

    def _persist_cf_cookies(self, r) -> None:
        """Write Cloudflare's cookies from this response's Set-Cookie back into
        the session file. The live curl session already keeps them; the file
        did not, so every client rebuilt from disk (eviction, proxy edit,
        restart) replayed the capture-time `__cf_bm` (30-minute TTL) and
        `cf_clearance` — a silent 403 source after idle. Writes only on a
        changed value; a cookie is matched on name AND domain, so a CF cookie
        another host set never overwrites the main one. Never raises (a failed
        write leaves the old file)."""
        if self.session_path is None:
            return
        try:
            fresh = {(c.name, _cookie_domain(c.domain)): c for c in r.cookies.jar
                     if c.name in CF_COOKIES
                     and self._cf_seen.get((c.name, _cookie_domain(c.domain))) != c.value}
            if not fresh:
                return

            def _apply(data: dict) -> None:
                cookies = data.setdefault("cookies", [])
                for (name, domain), c in fresh.items():
                    row = next((x for x in cookies if x.get("name") == name
                                and _cookie_domain(x.get("domain")) == domain), None)
                    if row is None:
                        row = {"name": name, "domain": c.domain or ".onlyfans.com",
                               "path": c.path or "/"}
                        cookies.append(row)
                    row["value"] = c.value
                    if c.expires:
                        row["expires"] = c.expires
            update_session_file(self.session_path, _apply)
            self._cf_seen.update({key: c.value for key, c in fresh.items()})
            log_of.info("cf_cookies_persisted account=%s cookies=%s",
                        self.account_id, sorted(f"{n}@{d}" for n, d in fresh))
        except Exception:
            log_of.warning("cf_cookies_persist_failed account=%s", self.account_id,
                           exc_info=True)

    def _http_call(self, method: str, url: str, *,
                   json_body: dict | None = None) -> requests.Response:
        """All outbound OF calls funnel here so failures (proxy 403, TLS, DNS,
        timeout) get a single structured log line with the context we need to
        debug: which account, which proxy, which OF endpoint.

        Also the single place we passively observe OF's current build hash:
        every response carries `x-of-rev` in the headers, which feeds the
        global live-rev cache that picks the sign rules (see live_rev.py, sign_rules.py).

        A call `_denied` names (logout, account deletion, ending sessions,
        telemetry), or any write for a deactivated Creator, is refused and
        logged here, before anything is sent."""
        if (reason := _denied(method, url)) is not None:
            log_of.error("denied account=%s method=%s url=%s (%s)",
                         self.account_id, method, _short_path(url), reason)
            raise OFDeniedError(f"refused: {method} {_short_path(url)} ({reason})")
        # A deactivated Creator gets no OF write, whichever route or job asks
        # (account_health "Deactivation"). Reads stay open for the owner's
        # history; the roster loops skip it on their own. The one write let
        # through is a carrier post's removal (remove_carrier).
        if method != "GET" and not (method == "DELETE" and _CARRIER_REMOVAL.get()):
            import account_health  # lazy: db-backed, and only a write needs it
            if account_health.refuses_writes(self.account_id):
                log_of.warning("deactivated account=%s method=%s url=%s refused",
                               self.account_id, method, _short_path(url))
                raise OFDeactivatedError(f"refused: {method} {_short_path(url)} (Creator deactivated)")
        # A read someone waits on fails fast (INTERACTIVE_READ); a write never does.
        policy = INTERACTIVE_RETRY if method == "GET" and INTERACTIVE_READ.get() else FULL_RETRY
        # The x-hash warmup runs its own _proxy_retry here, never nested in the one below.
        self._ensure_x_hash(policy=policy)
        try:
            # Datacenter providers (e.g. IPRoyal DC) sporadically 403 on CONNECT
            # under load; the same IP works again moments later. _proxy_retry()
            # Hold one curl handle across retries (sticky proxy connection/IP),
            # then return it for reuse by another worker thread.
            with self._signed_session() as signed_http:
                def _do() -> requests.Response:
                    # Signed per attempt: a retry can come seconds later, and Sign/Time must be fresh.
                    headers = self._signed_headers(url)
                    if json_body is not None:
                        headers["Content-Type"] = "application/json"
                    if method == "GET":
                        return signed_http.get(url, headers=headers, timeout=self.timeout_s)
                    return signed_http.request(method, url, json=json_body,
                                               headers=headers, timeout=self.timeout_s)
                # The OF call counter: one count per request sent, its answer's status or `error`
                # when none came back (CONNECT retries inside _proxy_retry are one request).
                try:
                    r = self._proxy_retry(_do, what=f"{method} {_short_path(url)}", policy=policy)
                except Exception:
                    of_call_counter.record(self.account_id, method, url, None)
                    raise
            of_call_counter.record(self.account_id, method, url, r.status_code)
            # Opportunistic rev capture. OF echoes their current build in
            # `x-of-rev` on most /api2/v2/* responses; note() is a no-op
            # if the header's missing or unchanged so this is cheap on
            # every call. If this ever raises we want to know — it's the
            # only way the global live-rev cache (sign rules) gets fresh data.
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
            # OF's consent-form demand (NC/AL law): a pinned agency notification while it lasts.
            _observe_consent(self.account_id, method, url, json_body, r)
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
        """Extract host:port from the proxy URL for logging without leaking creds."""
        if not self.proxy_url:
            return "direct"
        try:
            # http://user:pass@host:port → host:port (last "@": a password may hold one)
            after_at = self.proxy_url.rsplit("@", 1)[-1]
            return after_at
        except Exception:
            return "?"

    def _attempt(self, fn):
        """One try of `fn`, counted in proxy_health's per-label telemetry: in flight
        while it runs (a streaming get only until its headers arrive), then refused
        (ProxyError), ok (an answer) or left out (any other failure)."""
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

    def _proxy_retry(self, fn, *, what: str = "", policy: RetryPolicy = FULL_RETRY):
        """Run a raw curl_cffi call `fn`, retrying the transient datacenter
        CONNECT 403 (IPRoyal DC) as `policy` says: its tries, and an equal-jittered
        pause whose ceiling doubles between attempts. FULL_RETRY (the default)
        pauses half to all of 0.4, 0.8, 1.6, 3.2 s (3-6 s over 5 tries), as these outages can outlast a few
        hundred ms; INTERACTIVE_RETRY gives up after 2 tries (~1 s) for a
        read someone waits on. Retries run against the SAME self.http
        session — no proxy lookup, no rebuild, no rotation — so OF still sees
        one sticky IP. Both _http_call AND the handful of raw
        self.http.get/post/put calls (CDN media download, convert upload)
        funnel through it, so a proxy blip no longer hard-fails a request.

        It is also where a proxy failure is counted toward proxy_health's
        DOWN_AFTER (every raw call and _http_call funnel through here, the
        x-hash warm-up included): the final ProxyError, and curl's "couldn't
        connect" (7) on a proxied client (curl_cffi raises it as
        ConnectionError, not ProxyError; with a proxy set the only host curl
        connects to is the proxy, so it refused or is gone; not retried: a
        refused port answers at once). Only under a policy that `counts`.
        Every attempt (`_attempt`) also feeds proxy_health's refusal window and
        inflight counters, whatever the policy."""
        tries = policy.tries
        for attempt in range(tries):
            try:
                return self._attempt(fn)
            # One clause for both: ProxyError is not a ConnectionError in
            # curl_cffi (siblings under RequestException), so the isinstance
            # below dispatches exactly as two ordered except clauses would.
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

    def get_json(self, path_or_url: str, **kw) -> Any:
        # Inside a background walk: the Creator's pacer and OF's 429 retried once (of_pacing);
        # a ledger page also takes its bound proxy endpoint's slot (this client's transport).
        eg = None
        if urlsplit(path_or_url).path.rstrip("/").endswith(_LEDGER_PATH):
            eg = of_pacing.egress(self.proxy_url, self.proxy_label)
        return of_pacing.paced(self.account_id, lambda: self._get_json(path_or_url, **kw), eg)

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
        """Generic signed request. `method` in {GET, POST, PUT, PATCH, DELETE}.
        OF's sign algorithm is body-independent, so the same headers work for all methods."""
        url = self._build_url(path_or_url, params)
        return self._http_call(method.upper(), url, json_body=json_body)

    def request_json(self, method: str, path_or_url: str, **kw) -> Any:
        """request() + raise OFAPIError on non-2xx + .json() the success body.
        Treats 204 No Content as None (some OF writes return empty bodies)."""
        r = self.request(method, path_or_url, **kw)
        if not r.ok:
            raise OFAPIError(f"{r.status_code} for {r.url}\n{r.text[:500]}", response=r)
        if method.upper() != "GET":
            _invalidate_after_write(self.account_id, path_or_url)
        if r.status_code == 204 or not r.text:
            return None
        return r.json()

    # Convenience: same surface as before so existing callers don't break.
    def post(self, path_or_url: str, **kw) -> requests.Response:
        return self.request("POST", path_or_url, **kw)

    def post_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("POST", path_or_url, **kw)

    def put_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("PUT", path_or_url, **kw)

    def delete_json(self, path_or_url: str, **kw) -> Any:
        return self.request_json("DELETE", path_or_url, **kw)



class OFClient(_Transport, ReadsMixin, SendsMixin, UploadMixin):
    """One OF account's signed client: `_Transport` (session, signing, retry,
    the deny/deactivated gate) plus its endpoint parts in of_reads, of_sends
    and of_upload."""
