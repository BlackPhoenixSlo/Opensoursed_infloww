"""
Proxy registry — persistent store of per-account proxies.

Each session JSON in service/sessions/ can be paired with a proxy in this
registry by label. OFClient consults `get_proxy_for_session(filename)` on
load and routes all curl_cffi traffic through it.

Single source of truth lives in service/proxies.json. Schema:

  {
    "proxies": [
      {
        "label":              "proxy-1",
        "scheme":             "http",      // http | https | socks5
        "host":               "203.0.113.10",
        "port":               12323,
        "username":           "...",       // optional
        "password":           "...",       // optional — plain text, see notes
        "notes":              "Example City, XX AS64500",
        "assigned_session":   "session_20260101T000000Z.json",  // or null
        "verified_ip":        "203.0.113.10",
        "verified_at":        "2026-05-17T22:14:03Z",
        "verified_geo":       "Example City, XX"
      }
    ]
  }

Phase-1 (testing) stores credentials in plain text. Phase-2 should move
secrets into the OS keychain — see TODO section O.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "proxies.json"

_lock = threading.Lock()
log = logging.getLogger(__name__)


def _empty() -> dict[str, Any]:
    return {"proxies": []}


def load() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return _empty()
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(data, dict) or "proxies" not in data:
        return _empty()
    return data


def save(data: dict[str, Any]) -> None:
    """Write in place (same inode): proxies.json is bind-mounted into the relay
    container as a single file, where a temp-file rename fails (EXDEV/EBUSY).
    Truncate, write, flush and fsync; a torn write reads as unparseable, which
    `sync_pool` refuses to overwrite (`_load_for_sync`). Mode "w" truncates
    the existing file; it never makes a new one.

    Every write goes through here, so this is where an account's egress
    changes: each account whose proxy (or that proxy's endpoint) differs
    from before gets a `proxy_switched` SSE event."""
    try:
        before = _egress_by_account(load())
    except Exception:   # a malformed old entry must not block the write
        before = None
    text = json.dumps(data, indent=2, sort_keys=False)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    _pool_tokens_cache.clear()
    if before is None:
        return
    try:
        after = _egress_by_account(data)
        switched = sorted(a for a in before.keys() | after.keys() if before.get(a) != after.get(a))
        if switched:
            import events  # lazy: scripts import this module without the relay
            for aid in switched:
                events.publish_state("proxy_switched", account_id=aid, proxied=aid in after)
            for fn in _switch_listeners:
                fn(switched)
    except Exception:   # best-effort: the write above is what matters
        log.warning("proxy_switched_announce_failed", exc_info=True)


# Called by `save` with the account ids whose egress changed (server.py drops
# their pooled client and reconnects their chat socket, so REST and the WS move
# to the new route together). Runs under `_lock`: a listener must not call back
# into this module's writers.
_switch_listeners: list[Callable[[list[str]], None]] = []


def on_switch(fn: Callable[[list[str]], None]) -> None:
    _switch_listeners.append(fn)


def _egress_by_account(data: dict[str, Any]) -> dict[str, tuple]:
    """account id → the endpoint its traffic leaves through (label, scheme,
    host, port, credentials); an account on no proxy is absent. Raises on a
    malformed entry; `save` treats that as "unknown"."""
    out: dict[str, tuple] = {}
    for p in data.get("proxies", []):
        endpoint = tuple(p.get(k) for k in ("label", "scheme", "host", "port", "username", "password"))
        for aid in _ids_on(p):
            out[aid] = endpoint
    return out


def list_proxies() -> list[dict[str, Any]]:
    return load().get("proxies", [])


def get_by_label(label: str) -> dict[str, Any] | None:
    for p in list_proxies():
        if p.get("label") == label:
            return p
    return None


def get_for_session(session_filename: str) -> dict[str, Any] | None:
    """Return the proxy currently assigned to `session_filename`, or None.
    Legacy: pre-multi-account installs bound proxies to a specific session
    file. New installs bind to account_id (see `get_for_account`)."""
    for p in list_proxies():
        if p.get("assigned_session") == session_filename:
            return p
    return None


def _ids_on(p: dict[str, Any]) -> list[str]:
    """Return the list of account ids bound to this proxy.

    Reads the canonical `assigned_account_ids` list and, for legacy entries
    written before multi-binding was supported, falls back to the singular
    `assigned_account_id`. Callers should treat the result as a set."""
    ids = p.get("assigned_account_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    legacy = p.get("assigned_account_id")
    return [str(legacy)] if legacy else []


def get_for_account(account_id: str) -> dict[str, Any] | None:
    """Return the proxy assigned to this OF account (preferred — survives
    re-captures because each new session is bucketed under the same id).

    Each account belongs to at most ONE proxy (enforced in `assign_account`);
    a proxy may serve many accounts (and the picker flags >1 with a shared-
    egress warning, because OF can correlate same-IP accounts)."""
    if not account_id:
        return None
    aid = str(account_id)
    for p in list_proxies():
        if aid in _ids_on(p):
            return p
    return None


def proxy_url(p: dict[str, Any]) -> str:
    """Render a proxy entry to the URL form curl_cffi/requests expects."""
    scheme = p.get("scheme", "http")
    host, port = p["host"], p["port"]
    user, pw = p.get("username"), p.get("password")
    if user and pw:
        return f"{scheme}://{user}:{pw}@{host}:{port}"
    return f"{scheme}://{host}:{port}"


def proxies_dict_for_requests(p: dict[str, Any]) -> dict[str, str]:
    """Shape curl_cffi.requests.Session.proxies wants."""
    u = proxy_url(p)
    return {"http": u, "https": u}


def upsert(entry: dict[str, Any]) -> dict[str, Any]:
    """Add or replace by label. Returns the stored entry."""
    label = entry.get("label")
    if not label:
        raise ValueError("proxy entry needs a 'label'")
    for required in ("host", "port"):
        if not entry.get(required):
            raise ValueError(f"proxy entry missing '{required}'")
    entry.setdefault("scheme", "http")
    entry.setdefault("notes", "")
    entry.setdefault("assigned_session", None)     # legacy per-file binding
    entry.setdefault("assigned_account_id", None)  # legacy singular — mirrored from list[0]
    entry.setdefault("assigned_account_ids", [])   # canonical: many-accounts-per-proxy
    entry.setdefault("user_id", None)              # owner; null = shared default pool
    entry.setdefault("verified_ip", None)
    entry.setdefault("verified_at", None)
    entry.setdefault("verified_geo", None)

    with _lock:
        data = load()
        for i, p in enumerate(data["proxies"]):
            if p.get("label") == label:
                # Preserve any fields the caller didn't supply.
                merged = {**p, **{k: v for k, v in entry.items() if v is not None or k == "assigned_session"}}
                data["proxies"][i] = merged
                save(data)
                return merged
        if is_reserved_label(label):     # a NEW label only; existing ones are edited above
            raise ValueError(f"label {label!r} is reserved for the Inflowwww proxy pool")
        data["proxies"].append(entry)
        save(data)
        return entry


SCHEMES = ("http", "https", "socks5")


def parse_proxy_line(line: str, default_scheme: str = "http") -> dict[str, Any]:
    """Parse one pasted proxy line (formats: docs/proxies.md). Returns {label, host, port, scheme, username?,
    password?}; raises ValueError with a short reason. An optional label may
    follow the proxy after whitespace; it defaults to `host:port`."""
    parts = (line or "").strip().split(None, 1)
    if not parts:
        raise ValueError("empty line")
    spec = parts[0]
    label = parts[1].strip() if len(parts) > 1 else ""
    scheme = default_scheme
    if "://" in spec:
        scheme, spec = spec.split("://", 1)
    scheme = scheme.lower()
    if scheme not in SCHEMES:
        raise ValueError(f"unsupported scheme {scheme!r} (use http, https or socks5)")
    auth = None
    if "@" in spec:
        left, right = spec.rsplit("@", 1)
        # user:pass@host:port unless the right side cannot be host:port, or
        # both could (numeric password) and only the left host looks like one.
        lh, _, lp = left.rpartition(":")
        rh, _, rp = right.rpartition(":")
        if rp.isdigit() and not (lp.isdigit() and "." in lh and "." not in rh):
            auth, hostport = left, right
        else:                                     # host:port@user:pass
            hostport, auth = spec.split("@", 1)
        host, _, port_s = hostport.rpartition(":")
    else:
        bits = spec.split(":")
        if len(bits) == 2:                        # host:port
            host, port_s = bits
        elif len(bits) >= 4:                      # host:port:user:pass
            host, port_s = bits[0], bits[1]
            auth = ":".join(bits[2:])
        else:
            raise ValueError("unrecognised format (expected host:port, host:port:user:pass, user:pass@host:port or host:port@user:pass)")
    if not host:
        raise ValueError("no host")
    if not port_s.isdigit():
        raise ValueError("port must be a number")
    port = int(port_s)
    if not 1 <= port <= 65535:
        raise ValueError("port out of range (1-65535)")
    out: dict[str, Any] = {"label": label or f"{host}:{port}", "host": host,
                           "port": port, "scheme": scheme}
    if auth is not None:
        user, _, pw = auth.partition(":")
        if not user or not pw:
            raise ValueError("auth must be user:pass")
        out["username"], out["password"] = user, pw
    return out


def redact_line(line: str) -> str:
    """Mask anything that could be a password in a pasted line that failed to
    parse (so the position of host vs auth is unknown): every `:value` on a
    line with `@`, and everything from the 3rd colon segment otherwise."""
    parts = (line or "").strip().split(None, 1)
    if not parts:
        return ""
    spec = parts[0]
    prefix = ""
    if "://" in spec:
        scheme, spec = spec.split("://", 1)
        prefix = scheme + "://"
    if "@" in spec:
        spec = re.sub(r":[^@:]+", ":***", spec)
    else:
        bits = spec.split(":")
        if len(bits) >= 3:
            keep = 3 if len(bits) >= 4 else 2
            spec = ":".join(bits[:keep] + ["***"])
    return prefix + spec + (" " + parts[1].strip() if len(parts) > 1 else "")


def upsert_from_line(line: str, default_scheme: str = "http",
                     owner: str | None = None) -> dict[str, Any]:
    """parse_proxy_line + upsert. Re-pasting an existing label refreshes its
    host/port/credentials but keeps its account bindings and notes.

    `owner` mirrors POST /admin/proxies: when set (a signed-in user), a new
    entry is tagged with it, and an existing label must already belong to
    it (PermissionError otherwise; shared defaults are read-only)."""
    entry = parse_proxy_line(line, default_scheme)
    existing = get_by_label(entry["label"])
    if existing is not None and is_pool(existing):
        raise PermissionError("Inflowwww proxy is read-only")
    if owner is not None:
        if existing is not None and existing.get("user_id") is None:
            raise PermissionError("shared default proxy is read-only")
        if existing is not None and existing.get("user_id") != owner:
            raise PermissionError("not your proxy")
        entry["user_id"] = owner
    if existing is not None:
        for k in ("notes", "assigned_session"):
            entry[k] = existing.get(k)
        entry["assigned_account_ids"] = _ids_on(existing)
    return upsert(entry)


def remove(label: str) -> bool:
    with _lock:
        data = load()
        before = len(data["proxies"])
        data["proxies"] = [p for p in data["proxies"] if p.get("label") != label]
        if len(data["proxies"]) == before:
            return False
        save(data)
        return True


def assign(label: str, session_filename: str | None) -> dict[str, Any]:
    """Bind a proxy to a session file (LEGACY). Prefer `assign_account`.
    Enforces 1:1 — if another proxy already owns that session, it is unassigned."""
    with _lock:
        data = load()
        target = None
        for p in data["proxies"]:
            if p.get("label") == label:
                target = p
            elif session_filename and p.get("assigned_session") == session_filename:
                p["assigned_session"] = None
        if target is None:
            raise KeyError(f"no proxy with label {label!r}")
        target["assigned_session"] = session_filename
        save(data)
        return target


def _sync_legacy_singular(p: dict[str, Any]) -> None:
    """Mirror `assigned_account_ids[0]` into the legacy `assigned_account_id`
    so older readers (db/import_legacy.py, any out-of-band tooling) still see
    SOMETHING when a proxy is bound. None when the list is empty."""
    ids = p.get("assigned_account_ids") or []
    p["assigned_account_id"] = str(ids[0]) if ids else None


def assign_account(label: str, account_id: str | None) -> dict[str, Any]:
    """Bind an OF account to a proxy. Each account belongs to AT MOST one
    proxy — if the account is currently bound to a different proxy, it is
    moved here. Many accounts may share the same proxy (the UI surfaces a
    warning when >1 share egress because OF can correlate same-IP behaviour).

    `account_id=None` is preserved as a no-op (the old "unbind the single
    binding" gesture moved to `unbind_account`); silently ignoring keeps
    legacy callers safe."""
    if account_id is None:
        # Existing callers (and the older UI) sometimes hit this with null
        # to express "unbind". With multi-binding, that gesture is ambiguous
        # (unbind WHICH account?) so the explicit `unbind_account` path
        # owns it. Look up the target so callers still get the proxy back.
        for p in list_proxies():
            if p.get("label") == label:
                return p
        raise KeyError(f"no proxy with label {label!r}")

    aid = str(account_id)
    with _lock:
        data = load()
        target = None
        for p in data["proxies"]:
            # Lift legacy singular into the list before mutating, so a
            # pre-multi-binding entry doesn't silently lose its original
            # binding when a second account is added.
            ids = _ids_on(p)
            if p.get("label") == label:
                target = p
                if aid not in ids:
                    ids.append(aid)
            else:
                # Account moves: drop it from every OTHER proxy. Same
                # invariant the old single-binding code enforced, just
                # expressed against a list.
                ids = [x for x in ids if x != aid]
            p["assigned_account_ids"] = ids
            _sync_legacy_singular(p)
        if target is None:
            raise KeyError(f"no proxy with label {label!r}")
        # Clear the legacy filename binding so the two don't fight each other.
        target["assigned_session"] = None
        save(data)
        return target


def unbind_account(label: str, account_id: str) -> dict[str, Any]:
    """Remove a single account from a proxy's binding list. Account is left
    without a proxy (falls back to direct egress until reassigned)."""
    aid = str(account_id)
    with _lock:
        data = load()
        target = None
        for p in data["proxies"]:
            if p.get("label") == label:
                target = p
                # Lift legacy singular into the list first so a pre-multi
                # entry can be unbound just like any other.
                ids = _ids_on(p)
                p["assigned_account_ids"] = [x for x in ids if x != aid]
                _sync_legacy_singular(p)
                break
        if target is None:
            raise KeyError(f"no proxy with label {label!r}")
        save(data)
        return target


def migrate_legacy_assignments(filename_to_account: dict[str, str]) -> int:
    """Promote `assigned_session` (filename) bindings into the per-account
    list using a {session_filename: account_id} map (built from the account
    dirs). Idempotent. Returns how many proxies were rebound.

    Also lifts any pre-multi-binding `assigned_account_id` value into the
    `assigned_account_ids` list so reads through the canonical accessor
    pick it up. The list is the source of truth; the singular stays
    mirrored for legacy readers."""
    rebound = 0
    with _lock:
        data = load()
        for p in data["proxies"]:
            # Lift legacy singular into the list if not yet migrated.
            ids = list(p.get("assigned_account_ids") or [])
            legacy = p.get("assigned_account_id")
            if legacy and str(legacy) not in [str(x) for x in ids]:
                ids.append(str(legacy))
                p["assigned_account_ids"] = ids
            if ids:
                _sync_legacy_singular(p)
                continue  # already on the new scheme
            sf = p.get("assigned_session")
            if sf and sf in filename_to_account:
                aid = str(filename_to_account[sf])
                p["assigned_account_ids"] = [aid]
                _sync_legacy_singular(p)
                # Don't clear assigned_session immediately — keep it as an audit
                # crumb so an admin can still see which capture originally
                # introduced this binding.
                rebound += 1
        if rebound:
            save(data)
    return rebound


def record_verification(label: str, *, ip: str | None, geo: str | None,
                        ok: bool) -> None:
    """Persist the last egress-IP probe result for a proxy."""
    with _lock:
        data = load()
        for p in data["proxies"]:
            if p.get("label") == label:
                if ok:
                    p["verified_ip"] = ip
                    p["verified_geo"] = geo
                    p["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    p["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    p["verified_ip"] = None
                save(data)
                return


TRACE_URL = "https://1.1.1.1/cdn-cgi/trace"


def parse_trace(text: str) -> dict[str, str]:
    """Cloudflare's trace body: `key=value` lines (ip, loc, colo, ...)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def probe(p: dict[str, Any], timeout_s: int = 15) -> dict[str, Any]:
    """One GET of Cloudflare's trace endpoint through the proxy: the egress
    ip, its country (`loc`, kept as `geo`), the Cloudflare `colo` and the
    time to first byte. No OnlyFans call and no third-party key (it used to
    be ipify plus ipinfo.io). Returns {ok, ip, geo, colo, ttfb_ms, error?}.
    Blocking; safe from a request handler."""
    from curl_cffi import CurlInfo, requests as curl_requests

    url = proxy_url(p)
    out: dict[str, Any] = {"ok": False, "ip": None, "geo": None, "colo": None,
                           "ttfb_ms": None, "error": None}
    try:
        with curl_requests.Session(curl_infos=[CurlInfo.STARTTRANSFER_TIME]) as s:
            r = s.get(TRACE_URL, proxies={"http": url, "https": url}, timeout=timeout_s)
        if r.status_code != 200:
            out["error"] = f"proxy_probe_failed: HTTP {r.status_code}"
            return out
        trace = parse_trace(r.text)
        ttfb = r.infos.get(CurlInfo.STARTTRANSFER_TIME)
        out.update(ip=trace.get("ip") or None, geo=trace.get("loc") or None,
                   colo=trace.get("colo") or None,
                   ttfb_ms=round(ttfb * 1000) if isinstance(ttfb, (int, float)) else None)
        out["ok"] = out["ip"] is not None
        if not out["ok"]:
            out["error"] = "proxy_probe_failed: no ip in the trace"
    except Exception as e:  # curl errors: refused CONNECT, timeout, TLS, DNS
        out["error"] = f"proxy_probe_failed: {e}"
    return out


# ── Inflowwww proxy pool ───────────────────────────────────────────────────
# The proxies in the relay env (POOL_ENV), seeded into this
# registry as system entries (`pool: true`, no owner) so OFClient's ordinary
# per-account routing does the egress and the stored binding is what keeps an
# account on its pick. Pool entries are never listed, edited, tested or bound
# through the generic /admin/proxies routes; their host and credentials stay
# on the relay. Contract: docs/proxies.md, "Inflowwww proxy pool".

POOL_ENV = "INFLOWW_PROXIES"
POOL_CLEAR = "none"        # the only env value that empties an existing pool
POOL_LABEL_PREFIX = "infloww-"


def is_pool(p: dict[str, Any] | None) -> bool:
    return bool(p and p.get("pool"))


_POOL_LABEL_RE = re.compile(r"^infloww-[0-9a-f]{8}$")


def is_reserved_label(label: str) -> bool:
    """A label a NEW user proxy may not take: exactly the generated pool form
    `infloww-<8 hex>`. Existing entries keep whatever label they have."""
    return bool(_POOL_LABEL_RE.match(label or ""))


def pool_entries() -> list[dict[str, Any]]:
    return [p for p in list_proxies() if is_pool(p)]


def parse_pool(text: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse POOL_ENV: proxy lines in any `parse_proxy_line` format, separated
    by newlines or commas; blank and `#` lines skipped; every good line is
    kept (no cap). Returns (entries, errors): `errors` are lines that don't
    parse, with the redacted line, never a password. Each entry's label is `infloww-<hash>` of
    scheme/user/host/port (stable across password rotations, changes when the
    proxy itself is swapped), so a removed proxy is told apart from a kept one."""
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in re.split(r"[\n,]", text or ""):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            e = parse_proxy_line(line)
        except ValueError as exc:
            errors.append(f"{redact_line(line)}: {exc}")
            continue
        key = f"{e['scheme']}://{e.get('username') or ''}@{e['host']}:{e['port']}"
        e["label"] = POOL_LABEL_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:8]
        if any(x["label"] == e["label"] for x in entries):
            continue
        entries.append(e)
    return entries, errors


def _load_for_sync() -> dict[str, Any] | None:
    """`load`, except a proxies.json that exists but cannot be read as a
    registry gives None instead of an empty one (so sync never overwrites it)."""
    if not REGISTRY_PATH.exists():
        return _empty()
    try:
        data = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return None
    return data


def sync_pool(text: str | None, rng: random.Random | None = None) -> dict[str, Any]:
    """Make the registry's pool entries match POOL_ENV (called at startup).
    New proxies are added, kept ones refreshed with their bindings intact, and
    removed ones dropped; an account that was on a removed proxy is re-bound to
    a random remaining one (or left with no proxy when the pool is empty).

    Fails closed: while pool entries exist, an unset/empty env or any line that
    doesn't parse leaves the pool and its bindings untouched (WARNING logged),
    so a missing env never silently moves accounts to the server IP. Only
    `none` clears it. A proxies.json that exists but does not parse is never written."""
    rng = rng or random
    clear = (text or "").strip().lower() == POOL_CLEAR
    wanted, errors = ([], []) if clear else parse_pool(text)
    result: dict[str, Any] = {"size": 0, "errors": errors, "rebound": 0,
                              "dropped": 0, "changed": False, "skipped": None}
    with _lock:
        data = _load_for_sync()
        if data is None:
            log.error("%s: %s exists but does not parse; pool sync skipped", POOL_ENV, REGISTRY_PATH)
            result["skipped"] = "registry unreadable"
            return result
        current = [p for p in data["proxies"] if is_pool(p)]
        if current and not clear and (errors or not wanted):
            why = "has a bad line" if errors else "is unset or empty"
            log.warning("%s %s; keeping the %d existing Inflowwww proxies and their bindings "
                        "(set it to 'none' to clear the pool)", POOL_ENV, why, len(current))
            result.update(size=len(current), skipped=why)
            return result
        want = {e["label"]: e for e in wanted}
        before = json.dumps(data, sort_keys=True)
        orphans: list[str] = []
        kept: list[dict[str, Any]] = []
        seen: set[str] = set()
        for p in data["proxies"]:
            label = p.get("label")
            if not is_pool(p):
                if label in want:   # a custom proxy holds the name: never adopted
                    log.warning("%s: label %s is held by a custom proxy; that pool proxy is skipped",
                                POOL_ENV, label)
                    seen.add(label)
                kept.append(p)
            elif label in want and label not in seen:
                e = want[label]
                p.update({k: e.get(k) for k in ("host", "port", "scheme", "username", "password")})
                p.update({"pool": True, "user_id": None})
                seen.add(label)
                kept.append(p)
            else:
                orphans.extend(_ids_on(p))
        for label, e in want.items():
            if label not in seen:
                kept.append({**e, "pool": True, "user_id": None, "notes": "", "assigned_session": None,
                             "assigned_account_id": None, "assigned_account_ids": [],
                             "verified_ip": None, "verified_at": None, "verified_geo": None})
        pool = [p for p in kept if is_pool(p)]
        rebound = 0
        if pool:
            for aid in orphans:
                if any(aid in _ids_on(p) for p in kept):
                    continue
                target = rng.choice(pool)
                target["assigned_account_ids"] = _ids_on(target) + [aid]
                _sync_legacy_singular(target)
                rebound += 1
        data["proxies"] = kept
        changed = json.dumps(data, sort_keys=True) != before
        if changed:
            save(data)
    result.update(size=len(pool), rebound=rebound, dropped=len(orphans) - rebound, changed=changed)
    return result


def _egress_ip(p: dict[str, Any]) -> str:
    return str(p.get("verified_ip") or p.get("host") or "")


def assign_pool(account_id: str, rng: random.Random | None = None) -> tuple[dict[str, Any], bool]:
    """Bind `account_id` to an Inflowwww proxy. Sticky: an account already on a
    pool proxy keeps it. Otherwise the least-used one: fewest other accounts
    already leaving from its IP (bindings on any proxy count), ties broken at
    random, so a new account gets an IP of its own while one is free. Several
    accounts share one once the pool is full. Returns (entry, kept).
    LookupError when empty."""
    current = get_for_account(account_id)
    if is_pool(current):
        return current, True
    pool = pool_entries()
    if not pool:
        raise LookupError("no Inflowwww proxies are set up on this relay")
    aid = str(account_id)
    used: dict[str, int] = {}
    for p in list_proxies():
        ip = _egress_ip(p)
        used[ip] = used.get(ip, 0) + sum(1 for x in _ids_on(p) if x != aid)
    least = min(used[_egress_ip(p)] for p in pool)
    pick = (rng or random).choice([p for p in pool if used[_egress_ip(p)] == least])
    return assign_account(pick["label"], account_id), False


# ── Scrubbing pool secrets out of free text ────────────────────────────────
# Exception text (curl's "Failed to connect to <host> port N", a proxy URL in a
# repr) can name a pool proxy. Anything persisted or served from such text
# goes through `scrub_pool_secrets` first.

POOL_PLACEHOLDER = "[inflowwww-proxy]"
_SCRUB_MIN_LEN = 4      # shorter tokens would mangle ordinary words
_pool_tokens_cache: dict[tuple, tuple[str, ...]] = {}


def _pool_tokens() -> tuple[str, ...]:
    """Each pool entry's host:port, host, username and password, longest first.
    Cached on the registry file's (mtime, size) so a call costs one stat."""
    try:
        st = REGISTRY_PATH.stat()
    except OSError:
        return ()
    key = (str(REGISTRY_PATH), st.st_mtime_ns, st.st_size)
    hit = _pool_tokens_cache.get(key)
    if hit is not None:
        return hit
    toks: set[str] = set()
    for p in pool_entries():
        host = str(p.get("host") or "")
        for t in (f"{host}:{p.get('port')}", host, p.get("username"), p.get("password")):
            if t and len(str(t)) >= _SCRUB_MIN_LEN:
                toks.add(str(t))
    out = tuple(sorted(toks, key=len, reverse=True))
    _pool_tokens_cache.clear()
    _pool_tokens_cache[key] = out
    return out


def scrub_pool_secrets(text: str | None) -> str | None:
    """Replace every pool proxy's host, host:port, username and password in
    `text` with a placeholder. Unchanged (and cheap) when the pool is empty."""
    if not text:
        return text
    toks = _pool_tokens()
    for t in toks:
        if t in text:
            text = text.replace(t, POOL_PLACEHOLDER)
    return text


def unbind_pool(account_id: str) -> bool:
    """Drop the account's pool binding, if it has one. Returns whether it did."""
    current = get_for_account(account_id)
    if not is_pool(current):
        return False
    unbind_account(current["label"], account_id)
    return True
