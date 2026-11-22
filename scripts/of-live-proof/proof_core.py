"""proof_core: the Live guard's pure policy, the Proof definition shape and proof ordering.

`decide(request, run)` is the one policy both enforcement points call (the live Relay's egress wrap and the capture
browser's route). It answers read, allow, reversal or refused, with a class and a reason, deciding the nine classes
of docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md in order, first match wins; under `capture --abort` a
write past class 3 is refused `capture_abort`. Nothing here does I/O; the Undo log, its file helpers and its checks
are undo_log.py's.

Arming is the primary safety. The Critical, Critical GET, stream and lockout lists below are backstops no arming
lifts; each starts small and grows from Request captures.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, NamedTuple
from urllib.parse import unquote_plus, urlsplit, urlunsplit

KINDS = frozenset({"live", "mocked", "oauth"})
NEVER_TITLED = "never-titled"   # proof_list check_sweep: a control Wired before ofm-not-yet, never Not-yet titled (D1)
NEVER_TITLED_SEP = "; "   # a never-titled proof's `control`: its real sweep labels joined (one proof, several controls)
# A control behind OFM_NEW_WRITES_ENABLED (service/runtime_switches.py): phase_check also checks it Not yet with the switch off.
OFM_NEW_WRITES = "ofm_new_writes"
TAGS = frozenset({"message", "post", "delete_at_once", "stream_start", "lockout", "irreversible", "fan_visible",
                  NEVER_TITLED, OFM_NEW_WRITES})
READS = frozenset({"GET", "HEAD", "OPTIONS"})
BACKSTOP = "backstop"   # a drill's `refused_as` when the Relay's own `_denied` refuses it (no wire line)
NOT_REVERSIBLE = "not reversible, owner go"
# Ticket 100: an undo chain refused to its end (a sent message no unsend took back); check_undo_log fails the run on it.
NOT_REVERSIBLE_REFUSED = "not reversible"
POST_LEAD = timedelta(minutes=30)
QUIET_HOUR = timedelta(hours=1)
FAN_VISIBLE_CAP = 2  # whole effort, owner-proxy Q15 (ticket 104)
# Ticket 99: live, a proof gets one fan-visible attempt whatever its fan_visible_max (Publish now runs live with cap 1,
# neutral text, no media: its hidden-refusal re-run never leaves). Fake mode keeps fan_visible_max.
LIVE_FAN_VISIBLE_MAX = 1

# Critical topics, matched on the path below /api2/v2, lowercased. They refuse every write (class 3) and every read
# a proof does not name (class 2, story 57).
# ASSUMPTION: OnlyFans's real Bank / payout-method / DAC7 / support / sign-in paths are not yet captured, so these
# are path-segment keyword patterns, broad by design (rung 4); overturned by a capture showing a pattern refusing a
# non-Critical control, which then narrows that pattern.
_TOPICS = [re.compile(p) for p in (
    r"(^|/)bank[a-z-]*(/|$)",
    r"(^|/)(payment-)?cards?(/|$)",
    r"(^|/)payment-?methods?(/|$)",
    r"(^|/)wallets?(/|$)",
    r"(^|/)add-funds?(/|$)",
    r"^/payouts/(methods?|types?|systems?|accounts?|legal|settings?)(/|$)",
    r"(^|/)payout-?(methods?|types?|systems?)(/|$)",
    r"(^|[/_-])dac7([/_-]|$)",  # a segment, never a hex hash (live 2026-11-21: a cdn2 /files/ hash held "dac7")
    r"(^|/)(support|tickets?)(/|$)",
    r"password",
    r"(^|/)(change-)?emails?(/|$)",
    r"(^|/)(change-)?phones?(-numbers?)?(/|$)",
    r"username",
    r"(^|/|-)(2fa|two-?factor|otp|totp|authenticator)(/|-|$)",
)]
# Writes only: GET /payouts/requests is Statements' payout history read (service/of_reads.py:169).
_CRITICAL_WRITES = ("/payouts/requests",)
_SIGN_IN_KEYS = frozenset({"username", "email", "phone", "password"})
# The Relay's own backstop, service/of_client.py:343-360 `_denied`, mirrored (not imported: of_client imports
# curl_cffi and the accounts/proxies/proxy_health registries at module load). Every method on these paths, every
# request to a bug*.onlyfans.com host, and every non-GET under /sessions is refused in class 3 (reads in class 2);
# no flag, arming or owner go lifts it, so the capture browser, which has no Relay behind it, is held to it too.
# ASSUMPTION: spec class 5 seeds the lockout list with non-GET /sessions; that path is refused outright instead,
# since D3 gives Close all sessions a Mocked proof only and ticket 121 leaves the /sessions deny untouched (rung 4,
# spec deviation); overturned by the parked owner-go ticket that lifts the /sessions backstop.
_DENIED_PATHS = ("/users/logout", "/users/delete/request", "/log")
_SESSIONS = "/sessions"
# Class 5 lists: a forgotten tag does not help.
_STREAM_START = (("POST", "/streams"),)
# ASSUMPTION: block by country / block by IP (Phase 3's Lockout controls) are not captured yet; a non-GET whose path
# segment or top-level body key names an IP or country block is treated as lockout (rung 4); overturned by their
# Request captures, which replace these patterns with the measured path.
_LOCKOUT = re.compile(r"block[a-z_-]*?(ips?|countr(y|ies))$|^(ips?|countr(y|ies))[-_]?block")

_CHAT_SEND = re.compile(r"^/chats/([^/]+)/messages$")
_QUEUE = re.compile(r"^/messages/queue(?:/([^/]+))?$")
_PUBLISH = re.compile(r"^/schedules/([^/]+)/publish$")
# ticket 73: Block a username on Streaming takes the username in the path; the trigger types `u{fan}`.
_STREAM_BLOCK = re.compile(r"^/streams/users/([^/]+)/block$")
_POST = re.compile(r"^/posts(?:/([^/]+))?$")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")   # a Write's `host`: equals h.lower().rstrip("."), no * : / @


class RelayUpload(NamedTuple):
    """Ticket 67: how an undo uploads a picture again (`Write.relay_upload`)."""
    route: str          # the Relay's upload route (multipart `file` + `fields`)
    fields: dict        # its other form fields
    picture: Callable   # a read (before, after-write, after-undo) -> the picture's CDN URL, or None


@dataclass(frozen=True)
class Write:
    """One armed OnlyFans write (or declared undo): method, OF path template (`{name}` = one segment)."""
    method: str
    path: str
    max: int = 1
    body_must: Mapping | None = None  # exact body; required for lockout and stream_start
    # An undo's Relay route (story 31), `{name}` filled from the Undo log row (`{id}` = the created OnlyFans id).
    # ASSUMPTION: the route an undo goes through is named on its Write, not in a separate Proof field (rung 5: the
    # spec's Proof shape stays as is); overturned when a Phase needs a UI undo in the capture browser (ticket 07).
    relay: str | None = None
    # ticket 30: an undo whose Relay route differs from its OnlyFans write in method or needs a JSON body (`{name}`
    # filled as in `relay`, `{account}` = the run's Creator): e.g. OF's PUT /vault/media/hidden behind the Relay's
    # POST /admin/vault-ai/items/{media}/hide {account_id}. None: the Relay call uses `method` and sends no body.
    relay_method: str | None = None
    relay_body: Mapping | Callable | None = None
    # ticket 60: or a function (before read) -> the Relay body, for a switch or setting put back by the same write with
    # the before value; FakeOF tells its undo hit from the write's by time (undo_driver.row_problem).
    # ASSUMPTION: a setting's undo is the same PATCH with the before value, so the body tells it from the write (rung 5);
    # overturned by a setting whose undo needs its own route.
    # ticket 30: an undo's arm indexes, the Undo log rows it reverses (each row is stamped with its arm index when the
    # Relay opens it); None = every row. An undo request one row already sent is not sent again for the next row.
    reverses: tuple | None = None
    # ticket 53: the one host beyond onlyfans.com this Write goes to (the Record proofs' storage PUT), exact; None =
    # onlyfans.com or a subdomain. The Live guard takes a request on a named host only as the Write that names it,
    # and this Write only on that host (fake mode: also on FakeOF's origin, logged as onlyfans.com).
    host: str | None = None
    # ticket 67: an undo that puts a picture back by uploading it again (OF's profile write takes only a new upload
    # item or "", no old one: 60518.js `Ye`). The driver downloads `picture(before)` through the Relay's /img right
    # after the before read and keeps it in the evidence folder (none, or one the route would refuse: the proof stops
    # before its trigger, undo_driver.keep). The undo is always sent (one after-write read cannot prove the write
    # never lands); it posts the kept bytes to `route` (multipart `file` + `fields`), then sends `relay_body` with
    # `{upload}` filled by the route's reply (OF's upload item, a non-empty processId, else no PATCH). It holds only
    # when the picture read back after the undo is the kept one by `undo_driver.picture_match` (undo_driver.undo).
    relay_upload: RelayUpload | None = None
    # ofm-not-yet follow-up #5: an arm's declared payload, (body, run, at) -> why this request's body is outside it,
    # or None (`at`: Request.at, when it is sent; W30 W1: a scheduled post's date is bound to it). The Live guard refuses such a write `unarmed` before it leaves (decide, class 4), whatever the proof's own
    # steps sent; an arm with none takes any body its other rules pass.
    payload: Callable | None = None

    def __post_init__(self):
        if self.host is not None and not _HOSTNAME.fullmatch(self.host):
            raise ValueError(f"{self.method} {self.path}: host {self.host!r} must be an exact lowercase host name "
                             "(no wildcard, port, user, path or trailing dot)")


# Trigger step families (proofs/phase0.py): ("relay", ...) calls a Relay route, ("fetch", ...) and ("hand-off", ...)
# run in the capture browser (of_browser.py), every other step in the control's Mirror frame. One family per trigger.
BROWSER_STEPS = ("fetch", "hand-off")


def step_family(step) -> str:
    return "relay" if step[0] == "relay" else "browser" if step[0] in BROWSER_STEPS else "ui"


@dataclass(frozen=True)
class Proof:
    """One control's proof definition; every later Phase writes these as data (spec Contracts)."""
    id: str
    phase: int
    page: str
    control: str
    kind: str                                   # live | mocked | oauth
    tags: frozenset = frozenset()               # subset of TAGS
    reads: tuple = ()                           # Critical GET paths (templates) this proof may read
    branches: tuple = ()                        # named verdicts; empty = one verdict
    arm: tuple = ()                             # Write, ...; empty = a read proof
    narrowing: Any = None
    trigger: Any = ()
    settled: Any = None
    of_read: Any = None                         # (get) or (get, Proof fan) -> comparable value; None reads nothing
    effect: Callable | None = None              # (before, after-write) -> bool; required when arm is non-empty
    undo: tuple = ()                            # Write, ...; empty = refused live unless irreversible + owner go
    capture_steps: tuple = ()
    # A write whose reply was lost (story 53) is found, never retried: (before, after-write read, run marker) ->
    # OnlyFans id of the thing it made, or None (the row then closes FAILED). None here: such a write stays FAILED.
    # ASSUMPTION: the finder is a Proof field beside of_read, not driver code (rung 5: later proofs stay data);
    # overturned if a Phase's finder needs a read of its own, which then joins of_read.
    find: Callable | None = None
    # ticket 30: (before, after-write read) -> {source id: {name: value}}, the placeholders beyond `{id}` the undo
    # Writes fill (the vault media id each new post carries), by the OnlyFans id of the item they were read off; the
    # row whose id is the source takes its own (`read_keys_for`, ticket 131). Each value is registered with the Relay
    # as kind `name`, so a `{name}` in an undo's pinned body binds, in the Live guard, to it alone (`_match`).
    undo_keys: Callable | None = None
    # A drill (story 39): armed on purpose, it passes only when the Live guard refuses its armed write with class
    # `refused_as` and, where given, `refused_body(logged outbound body)` holds; FakeOF must never see it. A drill
    # declares no effect (it may have none) and must be `fake_only`: the driver never starts a fake-only proof
    # under --of live. A `mocked` drill need not be: under --of live it is recorded `mocked: not run live` instead.
    # `refused_as="backstop"` (BACKSTOP): the Relay's own `_denied` refuses it before the Live guard, so it passes on
    # the app's 403 with no wire line (Phase 3 ticket 63: Close all sessions until ticket 81 lifts the backstop).
    fake_only: bool = False
    refused_as: str | None = None
    refused_body: Callable | None = None
    # A proof's own judgement of what the app browser saw (Phase 6 tickets 94, 95): (seen) -> {problems, parked,
    # record}, `seen` holding the trigger's `images` and `dom` snapshots, the app browser's `responses`, this proof's
    # `offhost` requests, its `wire` lines and the `of_read` before (prove.py `run_proof`); `parked` a reason when
    # the Proof Creator lacks the thing to compare, `record` what the capture record carries. None: the wire and
    # settled checks alone decide.
    check: Callable | None = None
    # Phase 6 ticket 96: (before read) -> why this proof must not write, or None. Judged on the before read, ahead of
    # any page or write; a reason parks the proof (nothing is triggered) with that reason.
    precheck: Callable | None = None
    # Ticket 100: a proof with this makes its undo Writes a fallback chain: the driver tries them in order and stops
    # at the first answered 2xx; before a later one it calls `undo_ids(after-write read, OnlyFans id, Proof fan)` ->
    # {name: id} for that Write's other placeholders, each registered with the Relay as kind `name` read off the
    # created id (`/__proof/read-id`). A chain refused to its end closes the row `NOT_REVERSIBLE_REFUSED` with the
    # reason. None: every undo Write runs (undo_driver).
    undo_ids: Callable | None = None
    # Ticket 96: a setting restored by a confirmed sequence, run once for all of the proof's rows: `undo_steps(before)`
    # -> [(undo Write index, Relay body (`{account}` filled), confirm(fresh read) -> bool), ...]. Each step's Relay call
    # is followed by a fresh read it must confirm before the next is sent (undo_driver).
    undo_steps: Callable | None = None
    # Ticket 131 port (tickets 100, 97): kinds `/__proof/read-id` may register beyond the undos' pinned-body
    # placeholders: "schedule" (the schedule item a publish names, beside its queued message) and "message" (the chat
    # message a queued item became, the fallback unsend's path `{message}`). The Relay verifies each with its own read.
    binds: frozenset = frozenset()
    # Ticket 99: the fan-visible attempts this proof may make (Publish now re-proven once on a fresh upload after
    # OnlyFans refuses its hidden medium), each still counted against FAN_VISIBLE_CAP.
    fan_visible_max: int = 1
    # ticket 67: (before, after-undo read) -> whether the undo put it back, for a read the undo cannot return to the
    # letter (a picture uploaded again gets a new URL); None: the two reads are equal (`undo_log.reads_equal`).
    same: Callable | None = None
    # ticket 60: (before read) -> a park reason when OnlyFans's side is not set for the trigger (a switch the control
    # needs is off and no captured body can turn it on), else None; checked before the page opens, so nothing is sent.
    ready: Callable | None = None
    # ticket 98: only a Co-tag proof's POST /posts may carry a tag (a tag notification cannot be undone), and then only
    # the run's named partner (`cotag_problems`); any other proof's tagged post is refused, partner or not.
    may_tag: bool = False

    @property
    def hosts(self) -> tuple:
        """ticket 53: the hosts beyond onlyfans.com this proof's arms name (`Write.host`), in arm order, each a
        `facts.<name>_host` of its capture record (proof_list --check-records). The Relay's arm copies them into
        Run.hosts, so `decide` passes them only while this proof is armed."""
        return tuple(dict.fromkeys(w.host for w in self.arm if w.host))

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"{self.id}: kind {self.kind!r} not in {sorted(KINDS)}")
        if not set(self.tags) <= TAGS:
            raise ValueError(f"{self.id}: unknown tags {sorted(set(self.tags) - TAGS)}")
        if self.refused_as is not None and not (self.fake_only or self.kind == "mocked"):
            raise ValueError(f"{self.id}: a drill (refused_as) must be fake_only (or mocked: never started live)")
        for steps in (self.trigger, self.capture_steps):
            if len({step_family(step) for step in steps}) > 1:
                raise ValueError(f"{self.id}: a trigger's steps are one family (relay, capture browser or UI), "
                                 "never a mix")
        if self.arm and self.effect is None and self.refused_as is None:
            raise ValueError(f"{self.id}: an armed proof must declare its effect")
        if self.undo_steps is not None and self.undo_ids is not None:
            raise ValueError(f"{self.id}: an undo sequence (undo_steps) and a fallback chain (undo_ids) are exclusive")


@dataclass(frozen=True)
class Request:
    """One outbound request as either enforcement point sees it."""
    method: str
    host: str
    path: str                                   # URL path; a query string is ignored
    body: Any = None                            # parsed JSON body, or None
    at: datetime | None = None                  # when it is sent (aware)


@dataclass(frozen=True)
class Run:
    """The run's state at the moment of one decision; the caller updates it after each allowed write."""
    proof: Proof | None = None                  # the armed proof, None between proofs
    of: str = "live"                            # live | fake
    capture_abort: bool = False                 # `capture --abort`
    proof_fan: str | None = None                # --proof-fan
    owner_go: frozenset = frozenset()           # --owner-go values: "stream" and proof ids
    lockout: bool = False                       # --lockout
    spent: Mapping = field(default_factory=dict)  # Verdict.key -> allowed count, this proof
    created: frozenset = frozenset()            # OnlyFans ids created by allowed writes in this proof (every arm)
    # ticket 131: arm index -> frozenset, the ids each arm's replies created; an undo's `{id}` binds only to the ids
    # of the arms its `reverses` names (`created` itself stays the union publish and queue narrowing read).
    created_by: Mapping = field(default_factory=dict)
    # ticket 131: {name: frozenset} the ids of each other kind an undo's pinned body names (`{media}`), registered by
    # `/__proof/read-id` (`add_read_id`); a placeholder binds only to ids of its own kind.
    keys: Mapping = field(default_factory=dict)
    # proof ids that spent a fan-visible publish, whole effort, one entry per attempt (ticket 99:
    # Proof.fan_visible_max), so a proof id may repeat
    fan_visible_done: tuple = ()
    quiet_hour: datetime | None = None          # start of the run's declared quiet hour (aware)
    hosts: tuple = ()                           # the armed proof's Proof.hosts, set only by relay_live's arm; () between proofs
    cotag_partner: str | None = None            # --cotag-partner (ofm-not-yet ticket 98): a post's only Co-tag
    marker: str | None = None                   # the run's marker (`oi-proof-<run id>`), set by relay_live's arm


def marker_problem(text: Any, run: Run) -> str | None:
    """Round 2 #22: why `text` does not carry this run's exact marker (a whole token, so another run's
    `oi-proof-<id>` or a longer one never passes), or None. No marker armed: refused."""
    if not run.marker:
        return "no run marker armed"
    if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(run.marker)}(?![A-Za-z0-9_-])", str(text or "")):
        return None
    return f"the text lacks this run's marker {run.marker}"


@dataclass(frozen=True)
class Verdict:
    kind: str                                   # read | allow | reversal | refused
    cls: str
    reason: str
    key: tuple | None = None                    # ("arm"|"undo", index) the caller adds to Run.spent when passed
    fan_visible: bool = False                   # caller adds the proof id to Run.fan_visible_done when passed
    capture: str = ""                           # "aborted": capture-abort mode answers every write this way


def _refused(cls, reason, **kw):
    return Verdict("refused", cls, reason, **kw)


def _api(path: str) -> str:
    """The path below /api2/v2, without query or trailing slash."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    if path == "/api2/v2" or path.startswith("/api2/v2/"):
        return path[len("/api2/v2"):] or "/"
    return path


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _template(tpl: str) -> re.Pattern:
    parts = re.split(r"(\{[^/{}]+\})", tpl.rstrip("/"))
    rx = "".join(f"(?P<{p[1:-1]}>[^/]+)" if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(f"^{rx}$")


def _of_host(host: str, named: tuple) -> bool:
    host = host.lower().rstrip(".")
    if host == "onlyfans.com" or host.endswith(".onlyfans.com"):
        return True
    return any(h == host and "*" not in h for h in named)


def _topic(api: str) -> bool:
    low = api.lower()
    return any(t.search(low) for t in _TOPICS)


def _denied(method: str, host: str, api: str) -> str | None:
    """Mirror of service/of_client.py `_denied`: why OnlyFans must never see this, or None."""
    if host.startswith("bug") and host.endswith(".onlyfans.com"):
        return "OF bug reporter"
    for p in _DENIED_PATHS:
        if _under(api, p):
            return p
    if method != "GET" and _under(api, _SESSIONS):
        return f"{method} {_SESSIONS}"
    return None


def _critical(method: str, api: str, body: Any) -> str | None:
    low = api.lower()
    for p in _CRITICAL_WRITES:
        if _under(low, p):
            return f"{method} {p}"
    if _topic(api):
        return f"Critical path {api}"
    if low == "/users/me" and isinstance(body, dict) and _SIGN_IN_KEYS & set(body):
        return f"profile update carries {sorted(_SIGN_IN_KEYS & set(body))}"
    return None


def _stream_path(method: str, api: str) -> bool:
    return (method, api) in _STREAM_START


def _lockout_path(method: str, api: str, body: Any = None) -> bool:
    if method in READS:
        return False
    keys = list(body) if isinstance(body, dict) else []
    return any(_LOCKOUT.search(k.lower()) for k in api.split("/") + [str(k) for k in keys] if k)


def is_lockout(proof: Proof) -> bool:
    """A Lockout control proof, by tag or by an armed write on the guard's lockout path list."""
    return "lockout" in proof.tags or any(_lockout_path(w.method.upper(), _api(w.path), w.body_must)
                                          for w in proof.arm)


_WHOLE = re.compile(r"^\{([^/{}]+)\}$")


def _bind(tpl: Any, v: Any, templates: bool):
    """`v` (a request body) against a pinned body: the `{name}` values it binds ({} when equal, every value a string),
    or None when it differs. Only an undo's pinned body is a template (`templates`); an arm's is compared exactly."""
    if templates and isinstance(tpl, str) and (m := _WHOLE.match(tpl)):
        return {m[1]: str(v)} if isinstance(v, (str, int)) and not isinstance(v, bool) else None
    if isinstance(tpl, Mapping) and isinstance(v, Mapping) and set(tpl) == set(v):
        pairs = [(tpl[k], v[k]) for k in tpl]
    elif isinstance(tpl, (list, tuple)) and isinstance(v, (list, tuple)) and len(tpl) == len(v):
        pairs = list(zip(tpl, v))
    else:
        return {} if not isinstance(tpl, (Mapping, list, tuple)) and tpl == v else None
    out = {}
    for t, x in pairs:
        got = _bind(t, x, templates)
        if got is None or any(out.get(k, val) != val for k, val in got.items()):
            return None
        out.update(got)
    return out


def _host_fits(w: Write, host: str, run: Run) -> bool:
    """ticket 53: a Write naming a host takes a request on that host alone (fake mode: also FakeOF's origin, which the
    Relay logs as onlyfans.com); any other Write takes onlyfans.com or a subdomain alone."""
    of = _of_host(host, ())
    return of if w.host is None else host == w.host or (run.of == "fake" and of)


def _match(proof: Proof, method: str, path: str, body: Any, run: Run, host: str = "onlyfans.com"):
    """The armed write or declared undo this request is: method, path template and, where pinned, the body (exact for
    an arm; an undo's may hold `{name}` placeholders). An arm with count left wins; then an undo (its path `{id}` must
    be an id the arms it `reverses` created, `_undo_ids`, and each `{name}` of its pinned body, or of its path when
    `name` is a kind the proof declares, in `run.keys[name]`, ids of that kind registered for it: ticket 131); then a
    spent arm, so the caller refuses it over count. (None, None): nothing matched."""
    spent = run.spent
    path = path.split("?", 1)[0].rstrip("/")

    def fits(w, templates=False):
        """(path placeholders, pinned-body placeholders) when this request is `w`, else None."""
        m = _template(w.path).match(path) if w.method.upper() == method and _host_fits(w, host, run) else None
        if m is None:
            return None
        # ticket 34: `{created}` (an arm's or an undo's) binds to an id the creating arms made (`_undo_ids`: those its
        # `reverses` names, else every arm's): a rename of the folder the proof made, never a real one. `{id}` in an
        # arm still matches any segment (publish, queue: class 6)
        if "created" in m.groupdict() and m["created"] not in _undo_ids(w, run):
            return None
        got = {} if w.body_must is None else _bind(dict(w.body_must), body, templates)
        return None if got is None else (m.groupdict(), got)

    arms = [(("arm", i), w) for i, w in enumerate(proof.arm) if fits(w)]
    for key, w in arms:
        if spent.get(key, 0) < w.max:
            return key, w
    for i, w in enumerate(proof.undo):
        m = fits(w, templates=True)
        # ASSUMPTION: an undo's `{id}` binds to an id an allowed write created, so an undo cannot delete a real
        # post or list (rung 4); other path placeholder names (a Fan, a list) match any segment. Overturned by an undo
        # that must reverse a write whose id comes from elsewhere, which then names its placeholder otherwise.
        # Ticket 30: a placeholder in an undo's pinned body (the vault media id OF's hide takes in `mediaIds`) binds
        # the same way, to an id the driver registered from its after-write read (`/__proof/read-id`); so does a path
        # placeholder named as a declared kind (ticket 100: the fallback unsend's `{message}`).
        kinds = {**run.keys, "id": _undo_ids(w, run)}
        named = {"id"} | declared_kinds(proof)
        if m and all(v in kinds.get(k, ()) for k, v in [*((k, v) for k, v in m[0].items() if k in named),
                                                        *m[1].items()]):
            return ("undo", i), w
    return arms[0] if arms else (None, None)


def _names(v) -> set:
    """The whole-string `{name}` placeholders in a pinned body (nested)."""
    if isinstance(v, str):
        return {m[1]} if (m := _WHOLE.match(v)) else set()
    if isinstance(v, Mapping):
        return set().union(*map(_names, v.values()))
    if isinstance(v, (list, tuple)):
        return set().union(*map(_names, v))
    return set()


def _arms(proof: Proof, w: Write) -> set:
    """The arm indexes an undo Write reverses (`reverses` None: every arm)."""
    return set(range(len(proof.arm))) if w.reverses is None else set(w.reverses)


def _undo_ids(w: Write, run: Run) -> frozenset:
    """The ids an undo's `{id}` (any Write's `{created}`, ticket 34) may bind to: those the arms it reverses created
    (`reverses` None: every created id)."""
    if w.reverses is None:
        return run.created
    return frozenset().union(*(run.created_by.get(a, frozenset()) for a in w.reverses))


def undo_key_names(proof: Proof) -> frozenset:
    """The placeholder names in the pinned bodies of a proof's undo Writes, but `id` (the created kind): the kinds
    `/__proof/read-id` may register for it (ticket 131)."""
    return frozenset(set().union(*(_names(dict(w.body_must)) for w in proof.undo if w.body_must is not None)) - {"id"})


def declared_kinds(proof: Proof) -> frozenset:
    """Every kind `/__proof/read-id` may register for a proof: its undos' body placeholders and its `binds`, never
    `id` (the created kind)."""
    return (undo_key_names(proof) | frozenset(proof.binds)) - {"id"}


def _names_key(w: Write, key: str) -> bool:
    return key in _template(w.path).groupindex or (w.body_must is not None and key in _names(dict(w.body_must)))


def source_arms(proof: Proof, key: str) -> set:
    """The arms whose created item a `{key}` id may be read off (ticket 131): reversed both by an undo whose path takes
    `{id}` (the item is deleted by its own id) and by an undo naming `{key}` in its pinned body or path (the Record
    proof: the post arm, never an upload arm); a kind no undo names (ticket 100's "schedule", for the publish) by any
    arm."""
    by_id = [_arms(proof, w) for w in proof.undo if "id" in _template(w.path).groupindex]
    by_key = [_arms(proof, w) for w in proof.undo if _names_key(w, key)] or [set(range(len(proof.arm)))]
    return set().union(*by_id) & set().union(*by_key)


def add_read_id(run: Run, key: str, of_id: str, source: str) -> Run:
    """`/__proof/read-id`'s decision (ticket 131): `run` with `of_id` registered as kind `key`, read off the item whose
    OnlyFans id is `source`. ValueError (refused) unless a proof is armed, `key` is a kind it declares
    (`declared_kinds`, never `id`), and `source` was created by one of its `source_arms`."""
    if run.proof is None:
        raise ValueError("no proof armed")
    if not of_id:
        raise ValueError("no id to register")
    if key not in declared_kinds(run.proof):
        raise ValueError(f"{key!r} is not a kind {run.proof.id} declares (an undo body placeholder or a bind)")
    if not any(source in run.created_by.get(a, ()) for a in source_arms(run.proof, key)):
        raise ValueError(f"source {source!r} was not created in {run.proof.id} by an arm {{{key}}} is read off")
    return replace(run, keys={**run.keys, key: frozenset(run.keys.get(key, ())) | {of_id}})


def read_keys_for(read, source) -> dict:
    """The undo keys of the item whose OnlyFans id is `source`, out of a `Proof.undo_keys` read ({source: {name: id}}),
    as strings; none when the read does not name it (ticket 131)."""
    got = (read or {}).get(str(source)) or {}
    return {str(k): str(v) for k, v in got.items() if v is not None}


READ_ID_KINDS = ("media", "schedule", "message")   # the kinds `/__proof/read-id` can verify (`read_id_query`)


def read_id_query(kind: str, source, fan, now: datetime | None = None) -> tuple[str, dict]:
    """The OnlyFans read (path, query) that shows a `kind` id (ticket 100): the post `source` with its media, the
    schedule items of today and tomorrow (UTC, `now` needed), or the Proof fan's latest chat messages. One shape for
    the Relay's `/__proof/read-id` check and the driver's own reads (phase6_writes), so they cannot drift."""
    if kind == "media":
        return f"/api2/v2/posts/{source}", {}
    if kind == "schedule":
        if now is None:
            raise ValueError("read_id_query: the schedule read needs `now` (its days are today and tomorrow, UTC)")
        return "/api2/v2/schedules", {"limit": 50, "filter[publishDate]": now.strftime("%Y-%m-%d"),
                                      "filter[publishDateEnd]": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                                      "filter[timeZone]": "UTC"}
    return f"/api2/v2/chats/{fan}/messages", {"limit": 10, "order": "desc"}


def _scheduled_ahead(body: Any, at: datetime | None) -> bool:
    if not isinstance(body, dict) or not body.get("isScheduled") or at is None:
        return False
    try:
        when = datetime.fromisoformat(str(body.get("scheduledDate", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return when.tzinfo is not None and when - at >= POST_LEAD


def _fan_visible(method: str, api: str, body: Any, proof: Proof, key: tuple, at: datetime | None) -> bool:
    # ASSUMPTION: a fan-visible publish is the schedule publish (post Publish now, queue Send now), a post or queue
    # write not scheduled at least POST_LEAD ahead (immediate, incl. a Co-tag post; a queue body with no scheduledDate
    # is the Relay's send-now path, service/mass_queue_api.py:232), or any armed write of a proof tagged fan_visible;
    # a chat send to the Proof fan is not counted (rung 2: ticket 01's list). Overturned if the owner counts Proof-fan
    # chat sends too.
    if method == "PUT" and _PUBLISH.match(api):
        return True
    # The body's isScheduled is not trusted alone: a date under POST_LEAD ahead, past or unreadable publishes now.
    if method in ("POST", "PUT", "PATCH") and _POST.match(api):
        return not _scheduled_ahead(body, at)
    if method in ("POST", "PUT") and _QUEUE.match(api):
        return not (isinstance(body, dict) and _scheduled_ahead({**body, "isScheduled": 1}, at))
    return key[0] == "arm" and "fan_visible" in proof.tags


def fan_visible_refusal(done, proof: Proof, of: str) -> str | None:
    """Why one more fan-visible attempt of `proof` is refused, or None (ticket 99): `done` holds one proof id per
    attempt already made in the effort. A proof gets Proof.fan_visible_max attempts in fake mode, LIVE_FAN_VISIBLE_MAX
    elsewhere; the effort gets FAN_VISIBLE_CAP. The one rule `decide` and a proof's own re-run (phase6 `pn_publish`)
    both apply."""
    done = list(done)
    most = proof.fan_visible_max if of == "fake" else LIVE_FAN_VISIBLE_MAX
    if done.count(proof.id) >= most:
        return f"{proof.id} already made " + ("its one fan-visible attempt" if most == 1
                                              else f"its {most} fan-visible attempts")
    if len(done) >= FAN_VISIBLE_CAP:
        return f"fan-visible cap of {FAN_VISIBLE_CAP} for the effort is spent"
    return None


def _fan_visible_proof(proof: Proof) -> bool:
    """Whether a proof makes a fan-visible write by design: tagged fan_visible, or arming a schedule publish."""
    return "fan_visible" in proof.tags or any(
        w.method.upper() == "PUT" and _PUBLISH.match(_api(w.path)) for w in proof.arm)


_COTAG_KEYS = ("rfTag", "userTags", "rfGuest", "rfPartner")


def cotag_tagged(body: Any) -> bool:
    """Whether a post body carries any Co-tag (a non-empty tag array, or anything truthy where one goes)."""
    return isinstance(body, dict) and any(body.get(k) for k in _COTAG_KEYS)


def cotag_problems(body: Any, partner: str | None) -> list:
    """Ticket 98's one Co-tag rule (the guard's backstop and the proof's wire check): why a post body's Co-tags are
    not exactly the run's named partner. An untagged post (every tag array absent or empty) has none; a tagged one
    needs a partner, `rfTag` and `userTags` each exactly [partner], `rfGuest` and `rfPartner` empty. Ids: digits only
    (an int or a string of digits), then compared as strings, so "02001" is not 2001."""
    if why := _unreadable_post(body):
        return [why]
    if not cotag_tagged(body):
        return []
    if not partner:
        return ["a Co-tagged post with no Co-tag partner named (--cotag-partner)"]
    out = []
    for k in ("rfTag", "userTags"):
        got = body.get(k)
        ids = [str(x) for x in got if isinstance(x, (int, str)) and not isinstance(x, bool) and str(x).isdigit()] \
            if isinstance(got, list) else None
        if ids is None or len(ids) != len(got) or ids != [str(partner)]:
            out.append(f"Co-tag {k} is {str(got)[:80]}, not exactly the named partner [{partner}]")
    out += [f"Co-tag {k} is {str(body[k])[:80]}, not empty" for k in ("rfGuest", "rfPartner") if body.get(k)]
    return out


def cotag_refusal(body: Any, partner: str | None) -> str | None:
    """The guard's backstop (decide, class 7): `cotag_problems`' first, or None."""
    return next(iter(cotag_problems(body, partner)), None)


def _unreadable_post(body: Any) -> str | None:
    """Why the backstop cannot read a post body (form-encoded, raw text), or None."""
    return None if isinstance(body, dict) else f"the post body is not a JSON object: {str(body)[:80]}"


def _post_tag_refusal(body: Any, proof: Proof, partner: str | None) -> str | None:
    """decide's class 7 Co-tag backstop for a POST /posts (ticket 98): a Co-tag proof's (Proof.may_tag) tags exactly
    the named partner; any other proof's post carries no tag, and an unreadable body is refused, not passed unread."""
    if proof.may_tag:
        return cotag_refusal(body, partner)
    if cotag_tagged(body):
        return f"{proof.id} may not tag (only a Co-tag proof's post carries a tag; a tag notification cannot be undone)"
    return _unreadable_post(body)


def decide(request: Request, run: Run) -> Verdict:
    method, host = request.method.upper(), request.host.lower()
    api, body, proof = _api(request.path), request.body, run.proof

    # 1. host
    if not _of_host(host, run.hosts):
        return _refused("host", f"{host} is not onlyfans.com and not named from a capture")
    if method in READS and not _of_host(host, ()):
        return _refused("host", f"{method} on {host}: a named host takes only the armed Write that names it")

    # 2. reads
    if method in READS:
        if why := _denied(method, host, api):
            return _refused("critical_read", f"Relay backstop (_denied): {method} {why}; no proof's reads lift it")
        if _topic(api) and not (proof and any(_template(_api(r)).match(api) for r in proof.reads)):
            return _refused("critical_read", f"{method} {api} is on the Critical GET list and not in the proof's reads")
        return Verdict("read", "read", f"{method} {api}")

    # 3. Critical: armed or not, no flag lifts it
    abort = "aborted" if run.capture_abort else ""
    if why := critical_write(method, request.path, body, host):
        return _refused("critical", why, capture=abort)
    # `capture --abort`: every other write, from the capture browser or the Relay, is recorded and never sent
    if run.capture_abort:
        return _refused("capture_abort", f"capture --abort: {method} {api} recorded, never sent", capture=abort)

    # 4. arming, count, undo
    if proof is None:
        return _refused("unarmed", f"{method} {api}: no proof armed")
    key, w = _match(proof, method, request.path, body, run, host)
    if w is None:
        return _refused("unarmed", f"{method} {api} (body included) is not armed for {proof.id}")
    if w.payload is not None and (why := w.payload(body, run, request.at)):
        return _refused("unarmed", f"{method} {api}: {why}, outside {proof.id}'s declared payload", key=key)
    if run.spent.get(key, 0) >= w.max:
        return _refused("over_count", f"{method} {api}: armed {w.max}, already spent", key=key)
    stream = "stream_start" in proof.tags or _stream_path(method, api)
    lockout = "lockout" in proof.tags or _lockout_path(method, api, body)
    reversal = key[0] == "undo"
    if reversal and not any(run.spent.get(("arm", i), 0) for i in range(len(proof.arm))):
        return _refused("unarmed", f"{method} {api}: undo before any write of {proof.id} was allowed", key=key)
    owner_go = False
    if not reversal and not proof.undo:
        if "irreversible" in proof.tags and proof.id in run.owner_go:
            owner_go = True  # Critical and the Relay backstop were already refused in class 3
        else:
            return _refused("no_undo", f"{proof.id} declares no undo", key=key)

    # 5. kind, stream, lockout
    if proof.kind == "oauth":
        return _refused("oauth", f"{proof.id} is an OAuth hand-off: no live write", key=key)
    if proof.kind == "mocked" and run.of == "live":
        return _refused("mocked", "mocked: not run live", key=key)
    if stream and not ("stream" in run.owner_go and w.body_must is not None):
        return _refused("stream", "stream start needs --owner-go stream and a pinned body it matches", key=key)
    if lockout and not (run.lockout and w.body_must is not None):
        return _refused("lockout", "lockout write needs --lockout and a pinned body it matches", key=key)

    # 6. messages: the Proof fan alone; a publish only for an id this proof created, or a schedule item registered
    # beside one (ticket 100: `/__proof/read-id` kind "schedule", verified by the Relay's own read)
    publish = _PUBLISH.match(api) if method == "PUT" else None
    chat = _CHAT_SEND.match(api) if method == "POST" else None
    q = _QUEUE.match(api) if method in ("POST", "PUT") else None
    # ticket 73: the block (POST) names the Proof fan by handle, u{Proof fan}; the unblock (DELETE, the undo, also bound
    # to created ids in `_match`) by its row id, which is the user id: exactly the Proof fan's id
    block = _STREAM_BLOCK.match(api) if method in ("POST", "DELETE") else None
    if publish:
        if publish[1] not in run.created | run.keys.get("schedule", frozenset()):
            return _refused("mass_message", f"publish of {publish[1]}, not created in {proof.id}", key=key)
    elif chat or q or block:
        if run.proof_fan is None:
            return _refused("mass_message", "Proof fan unset", key=key)
        if block:
            if block[1] != (f"u{run.proof_fan}" if method == "POST" else str(run.proof_fan)):
                return _refused("mass_message", f"stream block of {block[1]}, not the Proof fan", key=key)
        elif chat:
            if chat[1] != str(run.proof_fan):
                return _refused("mass_message", f"chat send to {chat[1]}, not the Proof fan", key=key)
        else:
            if q[1] is not None and q[1] not in run.created:
                # ASSUMPTION: a queue edit is narrowed only on an item this proof created (rung 4, D13 self-contained
                # proofs); overturned if a Phase must edit a queued item it did not create, which then parks.
                return _refused("mass_message", f"queue edit of {q[1]}, not created in {proof.id}", key=key)
            # a scheduled queue write lands POST_LEAD ahead at least (no scheduledDate: the fan-visible path, below)
            if isinstance(body, dict) and body.get("scheduledDate") and not _scheduled_ahead(
                    {**body, "isScheduled": 1}, request.at):
                return _refused("mass_message", f"queue scheduledDate {body['scheduledDate']!r} is under "
                                f"{int(POST_LEAD.total_seconds() // 60)} minutes ahead", key=key)
            ids = body.get("userIds") if isinstance(body, dict) else None
            if [str(u) for u in ids or []] != [str(run.proof_fan)] or body.get("userLists"):
                return _refused("mass_message", "mass message: queue recipients are not exactly the Proof fan "
                                f"(userIds={ids}, userLists={body.get('userLists') if isinstance(body, dict) else None})",
                                key=key)

    # 7. posts
    if method in ("POST", "PUT", "PATCH") and _POST.match(api):
        if not ("delete_at_once" in proof.tags or _scheduled_ahead(body, request.at)):
            return _refused("post", "post needs a schedule at least 30 minutes ahead or delete_at_once", key=key)
        # ticket 99: outside fake mode a fan-visible proof's post carries no media (Publish now runs live with neutral
        # text, no media), whatever the proof's own steps send; a post that is itself fan-visible too
        media = body.get("mediaFiles") if isinstance(body, dict) else None
        if (run.of != "fake" and method == "POST" and api == "/posts" and media not in (None, [])
                and (_fan_visible_proof(proof) or _fan_visible(method, api, body, proof, key, request.at))):
            return _refused("fan_visible", "outside fake mode a fan-visible proof's POST /posts carries an empty "
                            f"mediaFiles, not {str(media)[:80]}", key=key)
        if method == "POST" and api == "/posts" and (why := _post_tag_refusal(body, proof, run.cotag_partner)):
            return _refused("post", why, key=key)

    # Fan-visible publishes: capped for the whole effort (owner-proxy Q15), decided before reversal and allow.
    fan_visible = _fan_visible(method, api, body, proof, key, request.at)
    if fan_visible:
        if why := fan_visible_refusal(run.fan_visible_done, proof, run.of):
            return _refused("fan_visible", why, key=key)
        qh, at = run.quiet_hour, request.at
        if qh is None or at is None or not qh <= at < qh + QUIET_HOUR:
            return _refused("fan_visible", "fan-visible publish only inside the run's declared quiet hour", key=key)
        # ASSUMPTION: the delete_at_once tag is the proof's declared immediate delete or unsend with the 60-second
        # outer failure threshold (the driver's timer, ticket 08); overturned if a proof needs a separate field.
        if "delete_at_once" not in proof.tags or not proof.undo:
            return _refused("fan_visible", "fan-visible publish needs a declared immediate delete or unsend", key=key)

    # 8. reversal, 9. allow
    if reversal:
        return Verdict("reversal", "reversal", f"{method} {api} reverses an allowed write of {proof.id}", key=key)
    return Verdict("allow", "allow", NOT_REVERSIBLE if owner_go else f"{method} {api} armed for {proof.id}",
                   key=key, fan_visible=fan_visible)


_FAN_REACHING = frozenset({"fan_visible", "delete_at_once", "message"})


def order_group(proof: Proof) -> int:
    """ADR-0042's run order (ofm-not-yet ticket 101): 0 a read (no armed write), 1 a write no Fan can see, 2 a
    Fan-reaching write (tagged fan_visible, delete_at_once or message, or arming a schedule publish), 3 a Lockout
    proof."""
    if is_lockout(proof):
        return 3
    if not proof.arm:
        return 0
    return 2 if _FAN_REACHING & proof.tags or _fan_visible_proof(proof) else 1


def order(proofs, ran=(), canon=()):
    """The run order, whatever order the proofs were given in: by `order_group` (reads, Fan-invisible writes,
    Fan-reaching writes, Lockout last), inside a group by `canon` (the proof list's id order, `proofs.ORDER`), then
    as given. Refuses a non-lockout proof once a lockout proof has run."""
    proofs = list(proofs)
    done = next((p for p in ran if is_lockout(p)), None)
    if done is not None:
        late = [p.id for p in proofs if not is_lockout(p)]
        if late:
            raise ValueError(f"{late[0]!r} after lockout proof {done.id!r}: lockout proofs run last")
    rank = {pid: n for n, pid in enumerate(canon)}
    return [p for _, p in sorted(enumerate(proofs), key=lambda ip: (order_group(ip[1]), rank.get(ip[1].id, len(rank)),
                                                                   ip[0]))]


def fake_only_refused(proofs, of: str) -> list:
    """The driver's refusal before anything starts: every fake-only proof (the drills) selected under --of live."""
    return [f"{p.id} is fake-only: --of live never starts it" for p in proofs if of == "live" and p.fake_only]


def critical_write(method: str, path: str, body: Any = None, host: str = "onlyfans.com") -> str | None:
    """Why this write is refused in decide's class 3 (a Critical control or the Relay backstop), or None."""
    m, api = method.upper(), _api(path)
    if m in READS:
        return None
    if why := _denied(m, host.lower(), api):
        return f"Relay backstop (_denied): {why}; no flag lifts it"
    if why := _critical(m, api, body):
        return f"Critical control: {why}"
    return None


def critical_capture_refused(proof: Proof, abort: bool) -> str | None:
    """Story 26: a Critical control's capture runs only in abort mode. Checked on the proof's armed writes and its
    capture steps' fixed writes, before anything starts."""
    if abort:
        return None
    writes = [(w.method, w.path, dict(w.body_must) if w.body_must else None) for w in proof.arm]
    writes += [(s[1], s[2], s[3]) for s in proof.capture_steps
               if s and s[0] == "fetch" and isinstance(s[2], str) and not callable(s[3])]
    for method, path, body in writes:
        if why := critical_write(method, path, body):
            return f"{proof.id}: {method.upper()} {path} is refused in class 3 ({why}): its capture runs only " \
                   f"with --abort"
    return None


# ── The driver's wire check (step 9); the Undo log is undo_log.py's ──

def _req(e) -> str:
    return f"{e['method']} {e['path']}"


def wire_problems(proof: Proof, entries, relay_errors=()) -> list:
    """Step 9: the wire log lines of one proof's trigger window, against what it armed.

    A write proof must send its armed write (each at least once) and get no refusal; a read proof sends no write.
    `relay_errors`: (method, Relay route, status) the app saw answered >= 400 in the same window. One with no wire line
    of its method is the Relay's own backstop (service/of_client.py `_denied`): nothing reached the Live guard.
    ASSUMPTION: an error matches a wire line by method within the window (rung 5: the app-side route and the OnlyFans
    path differ, and the window holds one proof's clicks); overturned by a proof whose window mixes routes of one
    method, which then needs a per-request correlation id.
    """
    out = []
    if proof.refused_as == BACKSTOP:
        return _backstop_drill(proof, entries, relay_errors)
    if proof.refused_as is not None:
        return _drill_problems(proof, entries) + _backstop(entries, relay_errors)
    allowed = [e for e in entries if e.get("verdict") == "allow"]
    if proof.arm:
        missing = [w for i, w in enumerate(proof.arm)
                   if not any(e["method"] == w.method.upper() and _template(_api(w.path)).match(_api(e["path"]))
                              for e in allowed)]
        if missing:
            out.append("no write sent; armed: " + ", ".join(f"{w.method.upper()} {w.path}" for w in missing))
    for e in entries:
        if e.get("verdict") == "refused":
            out.append(f"refused by the Live guard: {_req(e)} ({e.get('class')}: {e.get('reason', '')})")
    if not proof.arm:
        out += [f"read proof sent a write: {_req(e)}" for e in entries if e["method"] not in READS]
    return out + _backstop(entries, relay_errors)


def _backstop(entries, relay_errors) -> list:
    return [f"Relay's own backstop refused {method.upper()} {route} ({status}): no wire line, nothing reached OnlyFans"
            for method, route, status in relay_errors if not any(e["method"] == method.upper() for e in entries)]


def _line_of(writes, e) -> bool:
    return any(e["method"] == w.method.upper() and _template(_api(w.path)).match(_api(e["path"])) for w in writes)


def _backstop_drill(proof: Proof, entries, relay_errors) -> list:
    """A backstop drill's window: each armed write answered 403 by the Relay's own backstop (by method, with no wire
    line, as `_backstop` tells it), and nothing but reads reached the Live guard."""
    hit = {m.upper() for m, _, status in relay_errors if status == 403} - {e["method"] for e in entries}
    out = [f"{proof.id}: {w.method.upper()} {w.path} was not refused by the Relay's own backstop (403, no wire line)"
           for w in proof.arm if w.method.upper() not in hit]
    return out + [f"{proof.id}: {_req(e)} reached the Live guard ({e.get('verdict')})"
                  for e in entries if e["method"] not in READS]


def _drill_problems(proof: Proof, entries) -> list:
    """A drill's window: its armed write refused with `refused_as` (body checked where declared), no other refusal,
    and nothing but reads forwarded."""
    def expected(e):
        return (e.get("verdict") == "refused" and e.get("class") == proof.refused_as and _line_of(proof.arm, e)
                and (proof.refused_body is None or bool(proof.refused_body(e.get("body")))))

    out = [f"{proof.id}: {w.method.upper()} {w.path} was not refused as {proof.refused_as} with its outbound body "
           "logged" for w in proof.arm
           if not any(expected(e) and _line_of((w,), e) for e in entries)]
    for e in entries:
        if e.get("verdict") == "refused" and not expected(e):
            out.append(f"refused by the Live guard: {_req(e)} ({e.get('class')}: {e.get('reason', '')})")
        elif e.get("verdict") != "refused" and e["method"] not in READS:
            out.append(f"{proof.id}: {_req(e)} was forwarded to OnlyFans")
    return out


def census(wire, hits) -> list:
    """Fake mode's guard census (story 38), over the whole run: every FakeOF hit that is not the harness's own tagged
    read must be a forwarded wire log entry (read, allow or reversal; one hit per entry, matched on method and path),
    and no refused entry may be among the hits. Any other hit took a Relay call path that skips the guard. A tagged
    hit (the driver's read, ticket 11) must match a forwarded wire entry of origin `driver`, which only tagged hits
    use: a driver read that skipped the Relay is named.
    ASSUMPTION: method and path identify a hit (rung 5: the wrap sees the URL without curl_cffi's `params`, so the
    query cannot be compared); overturned by a run where a bypass hides behind a forwarded twin, which then needs a
    per-request id from the wrap to FakeOF."""
    out = []
    pool = [(e["method"], e["path"]) for e in wire if e.get("verdict") != "refused" and e.get("origin") != "driver"]
    driver = [(e["method"], e["path"]) for e in wire if e.get("verdict") != "refused" and e.get("origin") == "driver"]
    refused = {(e["method"], e["path"]) for e in wire if e.get("verdict") == "refused"}
    for h in hits:
        key = (h["method"], h["path"])
        if h.get("tagged"):
            if key in driver:
                driver.remove(key)
            else:
                out.append(f"tagged FakeOF hit with no driver wire line (a driver read that skipped the Relay): "
                           f"{key[0]} {key[1]}")
            continue
        if key in pool:
            pool.remove(key)
        elif key in refused:
            out.append(f"refused request reached FakeOF: {key[0]} {key[1]}")
        else:
            out.append(f"FakeOF hit with no forwarded wire line (bypassed the guard): {key[0]} {key[1]}")
    return out


def lock_decision(held, alive: bool) -> tuple:
    """The Creator's run lock (story 21): ("take", report) or ("refuse", reason).

    `held`: the lock file's JSON ({pid, evidence}), None when there is none; `alive`: whether its pid runs. A stale
    lock (dead pid) is taken over and reported; its run's `pending` rows are then refused by the earlier-runs check
    (story 52), like any earlier run's. ASSUMPTION: a reused pid reads as alive and refuses (rung 4: refuse when unsure);
    overturned by a run refused on a pid that is not a harness run, which the owner then removes by hand."""
    if held is None:
        return "take", ""
    pid = held.get("pid") if isinstance(held, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return "refuse", "lock unreadable (no pid): remove it by hand once no run is going"
    who = f"pid {pid} ({held.get('evidence', '?')})"
    if alive:
        return "refuse", f"lock held by {who}: one run at a time"
    return "take", f"stale lock of {who} taken over"


# ── The driver's rules for proof kinds, tags and run flags (ticket 08, trimmed by D27) ──

PACE = timedelta(seconds=5)                    # story 22: live writes at least 5 s apart
DELETE_AT_ONCE = timedelta(seconds=60)         # story 10: deleted within 60 s of the allowed write
SCHEDULED_UNDO_LEAD = timedelta(minutes=10)    # story 10: a Scheduled post's undo forced 10 min before its time
# ASSUMPTION: a delete-at-once undo is forced 10 s before its 60 s bound (one pacing gap of 5 s plus 5 s for the
# request) so the delete lands within 60 s as story 10 says, where the ticket says "60 seconds after the write"
# (rung 4: the earlier deadline is the safer one); overturned if the owner reads 60 s as the moment to start it.
FORCE_HEADROOM = PACE + timedelta(seconds=5)


def _message_proof(proof: Proof) -> bool:
    """A message or PPV proof, by tag or by an armed chat send / queue write (a forgotten tag does not help)."""
    return "message" in proof.tags or any(
        (w.method.upper() == "POST" and _CHAT_SEND.match(_api(w.path)))
        or (w.method.upper() in ("POST", "PUT") and _QUEUE.match(_api(w.path))) for w in proof.arm)


def not_started(proof: Proof, of: str, proof_fan=None) -> str | None:
    """Why the driver never starts this proof in this run, or None (stories 9, 13, 24, 28, 56).

    Under --of live: a Mocked proof (`mocked: not run live`), a stream-start proof (by tag or the guard's stream
    path list) and an irreversible proof never start. D27 parks the owner-go run path in ticket 126, so these are
    refusals only: no flag starts them here. In every mode a message or PPV proof parks until the run names the Proof
    fan; the run never picks a Fan itself.
    ASSUMPTION: parking on the Proof fan applies under --of fake too (story 24: no run picks a Fan, and the Live guard
    refuses a message write with no Proof fan in both modes; rung 4); overturned when fake mode gets a synthetic
    Proof fan of its own.
    A Mocked proof with no trigger never starts either (ticket 134): its Mirror check covers it, and run_proof reads
    trigger[0]. Checked last, so the reasons above still win; any other trigger-less proof is refused (live_entry).
    """
    if of == "live":
        if proof.kind == "mocked":
            return "mocked: not run live"
        if "stream_start" in proof.tags or any(_stream_path(w.method.upper(), _api(w.path)) for w in proof.arm):
            return "stream start: needs the owner's stream go; no owner-go run path yet (ticket 126)"
        if "irreversible" in proof.tags:
            return "irreversible: needs the owner's go naming this proof; no owner-go run path yet (ticket 126)"
    if (_message_proof(proof) or fan_trigger(proof)) and not proof_fan:
        return "parked: Proof fan unset; the run never picks a Fan (--proof-fan names it)"
    if not proof.trigger and proof.kind == "mocked":
        return "mocked: no trigger; covered by the Mirror check"
    return None


def undo_deadline(proof: Proof, method: str, path: str, body: Any, written_at: datetime) -> datetime | None:
    """When the driver forces this allowed write's undo, whatever step the proof is on (story 10), or None.

    A delete-at-once write: 60 s after it, less FORCE_HEADROOM. A Scheduled post (`isScheduled` with a parseable
    aware `scheduledDate`): 10 minutes before its time. Both: the earlier."""
    out = []
    if "delete_at_once" in proof.tags:
        out.append(written_at + DELETE_AT_ONCE - FORCE_HEADROOM)
    if method.upper() in ("POST", "PUT", "PATCH") and _POST.match(_api(path)) and isinstance(body, dict) \
            and body.get("isScheduled"):
        try:
            when = datetime.fromisoformat(str(body.get("scheduledDate", "")).replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when is not None and when.tzinfo is not None:
            out.append(when - SCHEDULED_UNDO_LEAD)
    return min(out) if out else None


def pace_wait(last_write: datetime | None, now: datetime) -> float:
    """Seconds a forwarded write must wait so it goes at least PACE after the previous one (story 22)."""
    if last_write is None:
        return 0.0
    return max(0.0, (last_write + PACE - now).total_seconds())


def pace_problems(wire) -> list:
    """Every pair of consecutive forwarded writes (allow or reversal, not a read) logged under PACE apart (story 22).
    `wire`: folded wire lines with their ISO `time` (the intent, logged after the pacing wait)."""
    writes = sorted((e for e in wire if e.get("verdict") in ("allow", "reversal") and e.get("method") not in READS),
                    key=lambda e: e["seq"])
    out = []
    for a, b in zip(writes, writes[1:]):
        gap = (datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])).total_seconds()
        if gap < PACE.total_seconds():
            out.append(f"wire lines {a['seq']} and {b['seq']}: forwarded writes {gap:.1f} s apart, under the "
                       f"{PACE.total_seconds():.0f} s pace")
    return out


# ticket 53: what an evidence log may hold of a URL and a body. A presigned storage URL (the Record proofs' PUT) carries
# a working upload credential in its query (X-Amz-Credential, -Security-Token, -Signature, valid X-Amz-Expires
# seconds); every evidence writer (wire.jsonl, capture-browser.jsonl, fake-hits.jsonl, app-offhost.jsonl) keeps the
# param names and drops the values. A binary upload's body is logged by its length only.
# ASSUMPTION: a query param is secret when its name starts with X-Amz- / X-Goog- or holds signature, policy,
# key-pair-id, token, credential or secret, or is `sig` (rung 4: S3, CloudFront, GCS presigning); overturned by a
# presigned URL whose credential travels under another name, which then joins the pattern.
_SECRET_PARAM = re.compile(r"(?i)^x-(?:amz|goog)-|signature|policy|key-pair-id|token|credential|secret|^sig$")
REDACTED = "REDACTED"
_BINARY = re.compile(r"[\x00-\x08\x0e-\x1f]")


def redact_query(query: str) -> str:
    """`query` with every secret param's value replaced by REDACTED, names and order kept."""
    if not query:
        return query or ""
    out = []
    for part in str(query).split("&"):
        name, eq, _ = part.partition("=")
        out.append(f"{name}={REDACTED}" if eq and _SECRET_PARAM.search(unquote_plus(name)) else part)
    return "&".join(out)


def redact_url(url: str) -> str:
    """`url` with its query redacted (`redact_query`)."""
    u = urlsplit(str(url))
    return urlunsplit(u._replace(query=redact_query(u.query))) if u.query else str(url)


_QUERY_PAIR = re.compile(r"([?&])([^=&\s\"'<>]+)=([^&\s\"'<>]*)")
_S3_ERROR_TAGS = re.compile(r"<(AWSAccessKeyId|StringToSign|StringToSignBytes|SignatureProvided|CanonicalRequest)>.*?</\1>",
                            re.S)


def redact_text(text: str) -> str:
    """Free text (a copied relay/next log) with every secret query value in any URL it holds replaced by REDACTED, and
    the credential-bearing tags of an S3 error body (`SignatureDoesNotMatch`) emptied."""
    text = _QUERY_PAIR.sub(lambda m: f"{m[1]}{m[2]}={REDACTED}" if _SECRET_PARAM.search(unquote_plus(m[2])) else m[0],
                           str(text))
    return _S3_ERROR_TAGS.sub(lambda m: f"<{m[1]}>{REDACTED}</{m[1]}>", text)


def log_body(data):
    """A request body as an evidence log keeps it: JSON parsed, text as text (at most 2000 characters), bytes that are
    not UTF-8 JSON or text (a binary upload) as `<N bytes>` only."""
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray, memoryview)):
        raw = bytes(data)
        try:
            data = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(raw)} bytes>"
        if _BINARY.search(data):   # valid UTF-8 by chance (a media header), still binary
            return f"<{len(raw)} bytes>"
    if not isinstance(data, str):
        return f"<{type(data).__name__} body>"
    try:
        return json.loads(data)
    except ValueError:
        return data[:2000]


def fill(v, values: dict):
    """A record value with every `{name}` placeholder replaced from `values` (a whole-string placeholder keeps the
    value's type, so `"{id}"` can become 123). The one filler of the Phase checks that replay a record's request:
    scripts/of-mirror-check/phase_check.py and service/tests/test_of_mirror_content_writes.py."""
    if isinstance(v, dict):
        return {fill(k, values): fill(x, values) for k, x in v.items()}
    if isinstance(v, list):
        return [fill(x, values) for x in v]
    if isinstance(v, str):
        for name, val in values.items():
            if v == "{" + name + "}":
                return val
            v = v.replace("{" + name + "}", str(val))
    return v


# ticket 73: a trigger that types the Proof fan (Streaming's Block a username fills `u{fan}`). `{fan}` in a fill step's
# text becomes the run's Proof fan, as `{marker}` the run's marker; such a proof parks like a message proof while the
# Proof fan is unset (`not_started`), so no run types a Fan it picked itself.
def fan_trigger(proof: Proof) -> bool:
    """Whether a fill step of `proof`'s trigger types the Proof fan (`{fan}`)."""
    return any(step[0] == "fill" and len(step) > 2 and "{fan}" in str(step[2]) for step in proof.trigger or ())


def fill_text(text: str, marker: str, proof_fan) -> str:
    """A fill step's text with the run's marker and Proof fan put in (`{marker}`, `{fan}`), and `{handle}`: the marker as
    a social username (ticket 69: dashes as underscores, lower case, `oi_proof_<run>`; letters, digits and `_` only, as
    every network's handle rule takes)."""
    handle = marker.replace("-", "_").lower()
    return text.replace("{marker}", marker).replace("{handle}", handle).replace("{fan}", str(proof_fan or ""))
