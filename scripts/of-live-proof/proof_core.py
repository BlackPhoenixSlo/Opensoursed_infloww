from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, NamedTuple
from urllib.parse import unquote_plus, urlsplit, urlunsplit

KINDS = frozenset({"live", "mocked", "oauth"})
NEVER_TITLED = "never-titled"
NEVER_TITLED_SEP = "; "
OFM_NEW_WRITES = "ofm_new_writes"
TAGS = frozenset({"message", "post", "delete_at_once", "stream_start", "lockout", "irreversible", "fan_visible",
                  NEVER_TITLED, OFM_NEW_WRITES})
READS = frozenset({"GET", "HEAD", "OPTIONS"})
BACKSTOP = "backstop"
NOT_REVERSIBLE = "not reversible, owner go"
NOT_REVERSIBLE_REFUSED = "not reversible"
POST_LEAD = timedelta(minutes=30)
QUIET_HOUR = timedelta(hours=1)
FAN_VISIBLE_CAP = 2
LIVE_FAN_VISIBLE_MAX = 1

_TOPICS = [re.compile(p) for p in (
    r"(^|/)bank[a-z-]*(/|$)",
    r"(^|/)(payment-)?cards?(/|$)",
    r"(^|/)payment-?methods?(/|$)",
    r"(^|/)wallets?(/|$)",
    r"(^|/)add-funds?(/|$)",
    r"^/payouts/(methods?|types?|systems?|accounts?|legal|settings?)(/|$)",
    r"(^|/)payout-?(methods?|types?|systems?)(/|$)",
    r"(^|[/_-])dac7([/_-]|$)",
    r"(^|/)(support|tickets?)(/|$)",
    r"password",
    r"(^|/)(change-)?emails?(/|$)",
    r"(^|/)(change-)?phones?(-numbers?)?(/|$)",
    r"username",
    r"(^|/|-)(2fa|two-?factor|otp|totp|authenticator)(/|-|$)",
)]
# Writes only: GET /payouts/requests is the Statements payout history read.
_CRITICAL_WRITES = ("/payouts/requests",)
_SIGN_IN_KEYS = frozenset({"username", "email", "phone", "password"})
_DENIED_PATHS = ("/users/logout", "/users/delete/request", "/log")
# Non-GET /sessions is refused outright, not as lockout: Close all sessions gets a Mocked proof only.
_SESSIONS = "/sessions"
_STREAM_START = (("POST", "/streams"),)
_LOCKOUT = re.compile(r"block[a-z_-]*?(ips?|countr(y|ies))$|^(ips?|countr(y|ies))[-_]?block")

_CHAT_SEND = re.compile(r"^/chats/([^/]+)/messages$")
_QUEUE = re.compile(r"^/messages/queue(?:/([^/]+))?$")
_PUBLISH = re.compile(r"^/schedules/([^/]+)/publish$")
_STREAM_BLOCK = re.compile(r"^/streams/users/([^/]+)/block$")
_POST = re.compile(r"^/posts(?:/([^/]+))?$")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")


class RelayUpload(NamedTuple):
    route: str
    fields: dict
    picture: Callable


@dataclass(frozen=True)
class Write:
    method: str
    path: str
    max: int = 1
    body_must: Mapping | None = None
    relay: str | None = None
    relay_method: str | None = None
    relay_body: Mapping | Callable | None = None
    reverses: tuple | None = None
    host: str | None = None
    relay_upload: RelayUpload | None = None
    payload: Callable | None = None

    def __post_init__(self):
        if self.host is not None and not _HOSTNAME.fullmatch(self.host):
            raise ValueError(f"{self.method} {self.path}: host {self.host!r} must be an exact lowercase host name "
                             "(no wildcard, port, user, path or trailing dot)")


BROWSER_STEPS = ("fetch", "hand-off")


def step_family(step) -> str:
    return "relay" if step[0] == "relay" else "browser" if step[0] in BROWSER_STEPS else "ui"


@dataclass(frozen=True)
class Proof:
    id: str
    phase: int
    page: str
    control: str
    kind: str
    tags: frozenset = frozenset()
    reads: tuple = ()
    branches: tuple = ()
    arm: tuple = ()
    narrowing: Any = None
    trigger: Any = ()
    settled: Any = None
    of_read: Any = None
    effect: Callable | None = None
    undo: tuple = ()
    capture_steps: tuple = ()
    find: Callable | None = None
    undo_keys: Callable | None = None
    fake_only: bool = False
    refused_as: str | None = None
    refused_body: Callable | None = None
    check: Callable | None = None
    precheck: Callable | None = None
    undo_ids: Callable | None = None
    undo_steps: Callable | None = None
    binds: frozenset = frozenset()
    fan_visible_max: int = 1
    same: Callable | None = None
    ready: Callable | None = None
    may_tag: bool = False

    @property
    def hosts(self) -> tuple:
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
    method: str
    host: str
    path: str
    body: Any = None
    at: datetime | None = None


@dataclass(frozen=True)
class Run:
    proof: Proof | None = None
    of: str = "live"
    capture_abort: bool = False
    proof_fan: str | None = None
    owner_go: frozenset = frozenset()
    lockout: bool = False
    spent: Mapping = field(default_factory=dict)
    created: frozenset = frozenset()
    created_by: Mapping = field(default_factory=dict)
    keys: Mapping = field(default_factory=dict)
    fan_visible_done: tuple = ()
    quiet_hour: datetime | None = None
    hosts: tuple = ()
    cotag_partner: str | None = None
    marker: str | None = None


def marker_problem(text: Any, run: Run) -> str | None:
    if not run.marker:
        return "no run marker armed"
    if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(run.marker)}(?![A-Za-z0-9_-])", str(text or "")):
        return None
    return f"the text lacks this run's marker {run.marker}"


@dataclass(frozen=True)
class Verdict:
    kind: str
    cls: str
    reason: str
    key: tuple | None = None
    fan_visible: bool = False
    capture: str = ""


def _refused(cls, reason, **kw):
    return Verdict("refused", cls, reason, **kw)


def _api(path: str) -> str:
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


# Mirrors service/of_client.py `_denied`, not imported: of_client pulls curl_cffi and the account/proxy registries at load.
def _denied(method: str, host: str, api: str) -> str | None:
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
    return "lockout" in proof.tags or any(_lockout_path(w.method.upper(), _api(w.path), w.body_must)
                                          for w in proof.arm)


_WHOLE = re.compile(r"^\{([^/{}]+)\}$")


def _bind(tpl: Any, v: Any, templates: bool):
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
    of = _of_host(host, ())
    return of if w.host is None else host == w.host or (run.of == "fake" and of)


def _match(proof: Proof, method: str, path: str, body: Any, run: Run, host: str = "onlyfans.com"):
    spent = run.spent
    path = path.split("?", 1)[0].rstrip("/")

    def fits(w, templates=False):
        m = _template(w.path).match(path) if w.method.upper() == method and _host_fits(w, host, run) else None
        if m is None:
            return None
        if "created" in m.groupdict() and m["created"] not in _undo_ids(w, run):
            return None
        got = {} if w.body_must is None else _bind(dict(w.body_must), body, templates)
        return None if got is None else (m.groupdict(), got)

    arms = [(("arm", i), w) for i, w in enumerate(proof.arm) if fits(w)]
    for key, w in arms:
        if spent.get(key, 0) < w.max:
            return key, w
    # An undo's {id} binds only to ids an allowed write created, so an undo cannot delete a real post or list.
    for i, w in enumerate(proof.undo):
        m = fits(w, templates=True)
        kinds = {**run.keys, "id": _undo_ids(w, run)}
        named = {"id"} | declared_kinds(proof)
        if m and all(v in kinds.get(k, ()) for k, v in [*((k, v) for k, v in m[0].items() if k in named),
                                                        *m[1].items()]):
            return ("undo", i), w
    return arms[0] if arms else (None, None)


def _names(v) -> set:
    if isinstance(v, str):
        return {m[1]} if (m := _WHOLE.match(v)) else set()
    if isinstance(v, Mapping):
        return set().union(*map(_names, v.values()))
    if isinstance(v, (list, tuple)):
        return set().union(*map(_names, v))
    return set()


def _arms(proof: Proof, w: Write) -> set:
    return set(range(len(proof.arm))) if w.reverses is None else set(w.reverses)


def _undo_ids(w: Write, run: Run) -> frozenset:
    if w.reverses is None:
        return run.created
    return frozenset().union(*(run.created_by.get(a, frozenset()) for a in w.reverses))


def undo_key_names(proof: Proof) -> frozenset:
    return frozenset(set().union(*(_names(dict(w.body_must)) for w in proof.undo if w.body_must is not None)) - {"id"})


def declared_kinds(proof: Proof) -> frozenset:
    return (undo_key_names(proof) | frozenset(proof.binds)) - {"id"}


def _names_key(w: Write, key: str) -> bool:
    return key in _template(w.path).groupindex or (w.body_must is not None and key in _names(dict(w.body_must)))


def source_arms(proof: Proof, key: str) -> set:
    by_id = [_arms(proof, w) for w in proof.undo if "id" in _template(w.path).groupindex]
    by_key = [_arms(proof, w) for w in proof.undo if _names_key(w, key)] or [set(range(len(proof.arm)))]
    return set().union(*by_id) & set().union(*by_key)


def add_read_id(run: Run, key: str, of_id: str, source: str) -> Run:
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
    got = (read or {}).get(str(source)) or {}
    return {str(k): str(v) for k, v in got.items() if v is not None}


READ_ID_KINDS = ("media", "schedule", "message")


def read_id_query(kind: str, source, fan, now: datetime | None = None) -> tuple[str, dict]:
    if kind == "media":
        return f"/api2/v2/posts/{source}", {}
    if kind == "schedule":
        if now is None:
            raise ValueError("read_id_query: the schedule read needs `now` (its days are today and tomorrow, UTC)")
        return "/api2/v2/schedules", {"limit": 50, "filter[publishDate]": now.strftime("%Y-%m-%d"),
                                      "filter[publishDateEnd]": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                                      "filter[timeZone]": "UTC"}
    return f"/api2/v2/chats/{fan}/messages", {"limit": 10, "order": "desc"}


# isScheduled is not trusted alone: a date under POST_LEAD ahead, past or unreadable publishes now.
def _scheduled_ahead(body: Any, at: datetime | None) -> bool:
    if not isinstance(body, dict) or not body.get("isScheduled") or at is None:
        return False
    try:
        when = datetime.fromisoformat(str(body.get("scheduledDate", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return when.tzinfo is not None and when - at >= POST_LEAD


def _fan_visible(method: str, api: str, body: Any, proof: Proof, key: tuple, at: datetime | None) -> bool:
    if method == "PUT" and _PUBLISH.match(api):
        return True
    if method in ("POST", "PUT", "PATCH") and _POST.match(api):
        return not _scheduled_ahead(body, at)
    if method in ("POST", "PUT") and _QUEUE.match(api):
        return not (isinstance(body, dict) and _scheduled_ahead({**body, "isScheduled": 1}, at))
    return key[0] == "arm" and "fan_visible" in proof.tags


def fan_visible_refusal(done, proof: Proof, of: str) -> str | None:
    done = list(done)
    most = proof.fan_visible_max if of == "fake" else LIVE_FAN_VISIBLE_MAX
    if done.count(proof.id) >= most:
        return f"{proof.id} already made " + ("its one fan-visible attempt" if most == 1
                                              else f"its {most} fan-visible attempts")
    if len(done) >= FAN_VISIBLE_CAP:
        return f"fan-visible cap of {FAN_VISIBLE_CAP} for the effort is spent"
    return None


def _fan_visible_proof(proof: Proof) -> bool:
    return "fan_visible" in proof.tags or any(
        w.method.upper() == "PUT" and _PUBLISH.match(_api(w.path)) for w in proof.arm)


_COTAG_KEYS = ("rfTag", "userTags", "rfGuest", "rfPartner")


def cotag_tagged(body: Any) -> bool:
    return isinstance(body, dict) and any(body.get(k) for k in _COTAG_KEYS)


def cotag_problems(body: Any, partner: str | None) -> list:
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
    return next(iter(cotag_problems(body, partner)), None)


def _unreadable_post(body: Any) -> str | None:
    return None if isinstance(body, dict) else f"the post body is not a JSON object: {str(body)[:80]}"


def _post_tag_refusal(body: Any, proof: Proof, partner: str | None) -> str | None:
    if proof.may_tag:
        return cotag_refusal(body, partner)
    if cotag_tagged(body):
        return f"{proof.id} may not tag (only a Co-tag proof's post carries a tag; a tag notification cannot be undone)"
    return _unreadable_post(body)


def decide(request: Request, run: Run) -> Verdict:
    method, host = request.method.upper(), request.host.lower()
    api, body, proof = _api(request.path), request.body, run.proof

    if not _of_host(host, run.hosts):
        return _refused("host", f"{host} is not onlyfans.com and not named from a capture")
    if method in READS and not _of_host(host, ()):
        return _refused("host", f"{method} on {host}: a named host takes only the armed Write that names it")

    if method in READS:
        if why := _denied(method, host, api):
            return _refused("critical_read", f"Relay backstop (_denied): {method} {why}; no proof's reads lift it")
        if _topic(api) and not (proof and any(_template(_api(r)).match(api) for r in proof.reads)):
            return _refused("critical_read", f"{method} {api} is on the Critical GET list and not in the proof's reads")
        return Verdict("read", "read", f"{method} {api}")

    abort = "aborted" if run.capture_abort else ""
    if why := critical_write(method, request.path, body, host):
        return _refused("critical", why, capture=abort)
    if run.capture_abort:
        return _refused("capture_abort", f"capture --abort: {method} {api} recorded, never sent", capture=abort)

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
            owner_go = True
        else:
            return _refused("no_undo", f"{proof.id} declares no undo", key=key)

    if proof.kind == "oauth":
        return _refused("oauth", f"{proof.id} is an OAuth hand-off: no live write", key=key)
    if proof.kind == "mocked" and run.of == "live":
        return _refused("mocked", "mocked: not run live", key=key)
    if stream and not ("stream" in run.owner_go and w.body_must is not None):
        return _refused("stream", "stream start needs --owner-go stream and a pinned body it matches", key=key)
    if lockout and not (run.lockout and w.body_must is not None):
        return _refused("lockout", "lockout write needs --lockout and a pinned body it matches", key=key)

    publish = _PUBLISH.match(api) if method == "PUT" else None
    chat = _CHAT_SEND.match(api) if method == "POST" else None
    q = _QUEUE.match(api) if method in ("POST", "PUT") else None
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
                return _refused("mass_message", f"queue edit of {q[1]}, not created in {proof.id}", key=key)
            if isinstance(body, dict) and body.get("scheduledDate") and not _scheduled_ahead(
                    {**body, "isScheduled": 1}, request.at):
                return _refused("mass_message", f"queue scheduledDate {body['scheduledDate']!r} is under "
                                f"{int(POST_LEAD.total_seconds() // 60)} minutes ahead", key=key)
            ids = body.get("userIds") if isinstance(body, dict) else None
            if [str(u) for u in ids or []] != [str(run.proof_fan)] or body.get("userLists"):
                return _refused("mass_message", "mass message: queue recipients are not exactly the Proof fan "
                                f"(userIds={ids}, userLists={body.get('userLists') if isinstance(body, dict) else None})",
                                key=key)

    if method in ("POST", "PUT", "PATCH") and _POST.match(api):
        if not ("delete_at_once" in proof.tags or _scheduled_ahead(body, request.at)):
            return _refused("post", "post needs a schedule at least 30 minutes ahead or delete_at_once", key=key)
        media = body.get("mediaFiles") if isinstance(body, dict) else None
        if (run.of != "fake" and method == "POST" and api == "/posts" and media not in (None, [])
                and (_fan_visible_proof(proof) or _fan_visible(method, api, body, proof, key, request.at))):
            return _refused("fan_visible", "outside fake mode a fan-visible proof's POST /posts carries an empty "
                            f"mediaFiles, not {str(media)[:80]}", key=key)
        if method == "POST" and api == "/posts" and (why := _post_tag_refusal(body, proof, run.cotag_partner)):
            return _refused("post", why, key=key)

    fan_visible = _fan_visible(method, api, body, proof, key, request.at)
    if fan_visible:
        if why := fan_visible_refusal(run.fan_visible_done, proof, run.of):
            return _refused("fan_visible", why, key=key)
        qh, at = run.quiet_hour, request.at
        if qh is None or at is None or not qh <= at < qh + QUIET_HOUR:
            return _refused("fan_visible", "fan-visible publish only inside the run's declared quiet hour", key=key)
        if "delete_at_once" not in proof.tags or not proof.undo:
            return _refused("fan_visible", "fan-visible publish needs a declared immediate delete or unsend", key=key)

    if reversal:
        return Verdict("reversal", "reversal", f"{method} {api} reverses an allowed write of {proof.id}", key=key)
    return Verdict("allow", "allow", NOT_REVERSIBLE if owner_go else f"{method} {api} armed for {proof.id}",
                   key=key, fan_visible=fan_visible)


_FAN_REACHING = frozenset({"fan_visible", "delete_at_once", "message"})


def order_group(proof: Proof) -> int:
    if is_lockout(proof):
        return 3
    if not proof.arm:
        return 0
    return 2 if _FAN_REACHING & proof.tags or _fan_visible_proof(proof) else 1


def order(proofs, ran=(), canon=()):
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
    return [f"{p.id} is fake-only: --of live never starts it" for p in proofs if of == "live" and p.fake_only]


def critical_write(method: str, path: str, body: Any = None, host: str = "onlyfans.com") -> str | None:
    m, api = method.upper(), _api(path)
    if m in READS:
        return None
    if why := _denied(m, host.lower(), api):
        return f"Relay backstop (_denied): {why}; no flag lifts it"
    if why := _critical(m, api, body):
        return f"Critical control: {why}"
    return None


def critical_capture_refused(proof: Proof, abort: bool) -> str | None:
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



def _req(e) -> str:
    return f"{e['method']} {e['path']}"


def wire_problems(proof: Proof, entries, relay_errors=()) -> list:
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
    hit = {m.upper() for m, _, status in relay_errors if status == 403} - {e["method"] for e in entries}
    out = [f"{proof.id}: {w.method.upper()} {w.path} was not refused by the Relay's own backstop (403, no wire line)"
           for w in proof.arm if w.method.upper() not in hit]
    return out + [f"{proof.id}: {_req(e)} reached the Live guard ({e.get('verdict')})"
                  for e in entries if e["method"] not in READS]


def _drill_problems(proof: Proof, entries) -> list:
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
    if held is None:
        return "take", ""
    pid = held.get("pid") if isinstance(held, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return "refuse", "lock unreadable (no pid): remove it by hand once no run is going"
    who = f"pid {pid} ({held.get('evidence', '?')})"
    if alive:
        return "refuse", f"lock held by {who}: one run at a time"
    return "take", f"stale lock of {who} taken over"



PACE = timedelta(seconds=5)
DELETE_AT_ONCE = timedelta(seconds=60)
SCHEDULED_UNDO_LEAD = timedelta(minutes=10)
FORCE_HEADROOM = PACE + timedelta(seconds=5)


def _message_proof(proof: Proof) -> bool:
    return "message" in proof.tags or any(
        (w.method.upper() == "POST" and _CHAT_SEND.match(_api(w.path)))
        or (w.method.upper() in ("POST", "PUT") and _QUEUE.match(_api(w.path))) for w in proof.arm)


def not_started(proof: Proof, of: str, proof_fan=None) -> str | None:
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
    if last_write is None:
        return 0.0
    return max(0.0, (last_write + PACE - now).total_seconds())


def pace_problems(wire) -> list:
    writes = sorted((e for e in wire if e.get("verdict") in ("allow", "reversal") and e.get("method") not in READS),
                    key=lambda e: e["seq"])
    out = []
    for a, b in zip(writes, writes[1:]):
        gap = (datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])).total_seconds()
        if gap < PACE.total_seconds():
            out.append(f"wire lines {a['seq']} and {b['seq']}: forwarded writes {gap:.1f} s apart, under the "
                       f"{PACE.total_seconds():.0f} s pace")
    return out


_SECRET_PARAM = re.compile(r"(?i)^x-(?:amz|goog)-|signature|policy|key-pair-id|token|credential|secret|^sig$")
REDACTED = "REDACTED"
_BINARY = re.compile(r"[\x00-\x08\x0e-\x1f]")


def redact_query(query: str) -> str:
    if not query:
        return query or ""
    out = []
    for part in str(query).split("&"):
        name, eq, _ = part.partition("=")
        out.append(f"{name}={REDACTED}" if eq and _SECRET_PARAM.search(unquote_plus(name)) else part)
    return "&".join(out)


def redact_url(url: str) -> str:
    u = urlsplit(str(url))
    return urlunsplit(u._replace(query=redact_query(u.query))) if u.query else str(url)


_QUERY_PAIR = re.compile(r"([?&])([^=&\s\"'<>]+)=([^&\s\"'<>]*)")
_S3_ERROR_TAGS = re.compile(r"<(AWSAccessKeyId|StringToSign|StringToSignBytes|SignatureProvided|CanonicalRequest)>.*?</\1>",
                            re.S)


def redact_text(text: str) -> str:
    text = _QUERY_PAIR.sub(lambda m: f"{m[1]}{m[2]}={REDACTED}" if _SECRET_PARAM.search(unquote_plus(m[2])) else m[0],
                           str(text))
    return _S3_ERROR_TAGS.sub(lambda m: f"<{m[1]}>{REDACTED}</{m[1]}>", text)


def log_body(data):
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray, memoryview)):
        raw = bytes(data)
        try:
            data = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(raw)} bytes>"
        if _BINARY.search(data):
            return f"<{len(raw)} bytes>"
    if not isinstance(data, str):
        return f"<{type(data).__name__} body>"
    try:
        return json.loads(data)
    except ValueError:
        return data[:2000]


def fill(v, values: dict):
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


def fan_trigger(proof: Proof) -> bool:
    return any(step[0] == "fill" and len(step) > 2 and "{fan}" in str(step[2]) for step in proof.trigger or ())


def fill_text(text: str, marker: str, proof_fan) -> str:
    handle = marker.replace("-", "_").lower()
    return text.replace("{marker}", marker).replace("{handle}", handle).replace("{fan}", str(proof_fan or ""))
