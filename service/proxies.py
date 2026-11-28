from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from brand import BRAND_NAME

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE / "proxies.json"

_lock = threading.Lock()
log = logging.getLogger(__name__)


def _empty() -> dict[str, Any]:
    return {"proxies": []}


# Last good proxies.json text: a torn read (another process mid-write) falls back on it; `_gen` stops an older read overtaking a save.
_last_good_text: str | None = None
_gen = 0
_good_lock = threading.Lock()
_torn_logged = False


@dataclass(frozen=True)
class Ok:
    data: dict[str, Any]


@dataclass(frozen=True)
class Torn:
    last_good: dict[str, Any] | None


Registry = Ok | Torn


def registry() -> Registry:
    global _last_good_text, _torn_logged
    if not REGISTRY_PATH.exists():
        return Ok(_empty())
    gen = _gen
    try:
        text = REGISTRY_PATH.read_text()
        data = json.loads(text)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        if not _torn_logged:
            _torn_logged = True
            log.warning("proxies_registry_torn fallback=%s", "last_good" if _last_good_text else "none")
        return Torn(json.loads(_last_good_text) if _last_good_text else None)
    if _torn_logged:
        _torn_logged = False
        log.info("proxies_registry_recovered")
    with _good_lock:
        if _gen == gen:
            _last_good_text = text
    return Ok(data)


def load() -> dict[str, Any]:
    data = _known(registry())
    return data if data is not None else _empty()


def _known(reg: Registry) -> dict[str, Any] | None:
    return reg.data if isinstance(reg, Ok) else reg.last_good


class RegistryUnreadable(RuntimeError):
    pass


def _load_for_write() -> dict[str, Any]:
    # Writers read whole or not at all: saving the last good copy plus our edit would drop another process's mid-write.
    r = registry()
    if isinstance(r, Ok):
        return r.data
    raise RegistryUnreadable(f"{REGISTRY_PATH.name} does not parse; not written")


@dataclass(frozen=True)
class Proxy:
    entry: dict[str, Any]


@dataclass(frozen=True)
class Direct:
    pass


@dataclass(frozen=True)
class Refuse:
    reason: str


class EgressRefused(RegistryUnreadable):
    pass


def egress(reg: Registry, account_id: str, session_filename: str | None = None) -> Proxy | Direct | Refuse:
    # No good read and no way to tell if the account is proxied: Refuse, since going direct would show OF the host IP for a proxied Creator.
    data = _known(reg)
    if data is None:
        return Refuse("proxies.json is unreadable and was never read whole: egress unknown")
    p = _account_entry(data, account_id) or _session_entry(data, session_filename)
    if p is not None:
        return Proxy(p)
    return Direct()


CELLS = bool(os.environ.get("OI_CELL_MAP"))


class NoProxyRefused(Exception):
    def __init__(self, account_id: str, where: str):
        super().__init__(f"Creator {account_id} has no proxy: a Cell never reaches the platform direct ({where})")
        self.account_id = str(account_id)
        self.where = where


def no_proxy(account_id: str, where: str) -> NoProxyRefused:
    log.warning("no_proxy_refused account=%s at=%s", account_id, where)
    return NoProxyRefused(account_id, where)


def require_proxy(account_id: str, where: str, session_filename: str | None = None) -> None:
    if not isinstance(egress(registry(), str(account_id), session_filename), Proxy):
        raise no_proxy(account_id, where)


def save(data: dict[str, Any]) -> None:
    # Write in place (same inode): proxies.json is bind-mounted as a single file, where a temp-file rename fails (EXDEV/EBUSY).
    global _last_good_text, _gen
    try:
        before = _egress_by_account(load())
    except Exception:
        before = None
    text = json.dumps(data, indent=2, sort_keys=False)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    with _good_lock:
        _last_good_text = text
        _gen += 1
    _pool_tokens_cache.clear()
    if before is None:
        return
    try:
        after = _egress_by_account(data)
        switched = sorted(a for a in before.keys() | after.keys() if before.get(a) != after.get(a))
        if switched:
            import events
            for aid in switched:
                events.publish_state("proxy_switched", account_id=aid, proxied=aid in after)
            for fn in _switch_listeners:
                fn(switched)
    except Exception:
        log.warning("proxy_switched_announce_failed", exc_info=True)


# Runs under `_lock`: a listener must not call back into this module's writers.
_switch_listeners: list[Callable[[list[str]], None]] = []


def on_switch(fn: Callable[[list[str]], None]) -> None:
    _switch_listeners.append(fn)


def _egress_by_account(data: dict[str, Any]) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    for p in data.get("proxies", []):
        endpoint = tuple(p.get(k) for k in ("label", "scheme", "host", "port", "username", "password"))
        for aid in _ids_on(p):
            out[aid] = endpoint
    return out


def list_proxies() -> list[dict[str, Any]]:
    return load().get("proxies", [])


def _by_label(data: dict[str, Any], label: str) -> dict[str, Any] | None:
    return next((p for p in data["proxies"] if p.get("label") == label), None)


def get_by_label(label: str) -> dict[str, Any] | None:
    return _by_label(load(), label)


def _session_entry(data: dict[str, Any], session_filename: str | None) -> dict[str, Any] | None:
    if not session_filename:
        return None
    return next((p for p in data.get("proxies", []) if p.get("assigned_session") == session_filename), None)


def _ids_on(p: dict[str, Any]) -> list[str]:
    ids = p.get("assigned_account_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    legacy = p.get("assigned_account_id")
    return [str(legacy)] if legacy else []


def get_for_account(account_id: str) -> dict[str, Any] | None:
    return _account_entry(load(), account_id)


def _account_entry(data: dict[str, Any], account_id: str | None) -> dict[str, Any] | None:
    if not account_id:
        return None
    aid = str(account_id)
    return next((p for p in data.get("proxies", []) if aid in _ids_on(p)), None)


def proxy_url(p: dict[str, Any]) -> str:
    scheme = p.get("scheme", "http")
    host, port = p["host"], p["port"]
    user, pw = p.get("username"), p.get("password")
    if user and pw:
        return f"{scheme}://{user}:{pw}@{host}:{port}"
    return f"{scheme}://{host}:{port}"


def proxies_dict_for_requests(p: dict[str, Any]) -> dict[str, str]:
    u = proxy_url(p)
    return {"http": u, "https": u}


def upsert(entry: dict[str, Any]) -> dict[str, Any]:
    label = entry.get("label")
    if not label:
        raise ValueError("proxy entry needs a 'label'")
    for required in ("host", "port"):
        if not entry.get(required):
            raise ValueError(f"proxy entry missing '{required}'")
    entry.setdefault("scheme", "http")
    entry.setdefault("notes", "")
    entry.setdefault("assigned_session", None)
    entry.setdefault("assigned_account_id", None)
    entry.setdefault("assigned_account_ids", [])
    entry.setdefault("user_id", None)
    entry.setdefault("verified_ip", None)
    entry.setdefault("verified_at", None)
    entry.setdefault("verified_geo", None)

    with _lock:
        data = _load_for_write()
        for i, p in enumerate(data["proxies"]):
            if p.get("label") == label:
                merged = {**p, **{k: v for k, v in entry.items() if v is not None or k == "assigned_session"}}
                data["proxies"][i] = merged
                save(data)
                return merged
        if is_reserved_label(label):
            raise ValueError(f"label {label!r} is reserved for the {BRAND_NAME} proxy pool")
        data["proxies"].append(entry)
        save(data)
        return entry


SCHEMES = ("http", "https", "socks5")


def parse_proxy_line(line: str, default_scheme: str = "http") -> dict[str, Any]:
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
        lh, _, lp = left.rpartition(":")
        rh, _, rp = right.rpartition(":")
        if rp.isdigit() and not (lp.isdigit() and "." in lh and "." not in rh):
            auth, hostport = left, right
        else:
            hostport, auth = spec.split("@", 1)
        host, _, port_s = hostport.rpartition(":")
    else:
        bits = spec.split(":")
        if len(bits) == 2:
            host, port_s = bits
        elif len(bits) >= 4:
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
    entry = parse_proxy_line(line, default_scheme)
    existing = get_by_label(entry["label"])
    if existing is not None and is_pool(existing):
        raise PermissionError(f"{BRAND_NAME} proxy is read-only")
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
        data = _load_for_write()
        before = len(data["proxies"])
        data["proxies"] = [p for p in data["proxies"] if p.get("label") != label]
        if len(data["proxies"]) == before:
            return False
        save(data)
        return True


def assign(label: str, session_filename: str | None) -> dict[str, Any]:
    with _lock:
        data = _load_for_write()
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
    ids = p.get("assigned_account_ids") or []
    p["assigned_account_id"] = str(ids[0]) if ids else None


def assign_account(label: str, account_id: str | None) -> dict[str, Any]:
    # Each account belongs to at most one proxy (OF can correlate same-IP accounts); binding moves it.
    if account_id is None:
        p = get_by_label(label)
        if p is not None:
            return p
        raise KeyError(f"no proxy with label {label!r}")

    with _lock:
        data = _load_for_write()
        target = _bind(data, label, str(account_id))
        save(data)
        return target


def _bind(data: dict[str, Any], label: str, aid: str) -> dict[str, Any]:
    target = None
    for p in data["proxies"]:
        # Lift the legacy singular binding into the list first so a second account does not drop it.
        ids = _ids_on(p)
        if p.get("label") == label:
            target = p
            if aid not in ids:
                ids.append(aid)
        else:
            # Account moves: drop it from every other proxy (one proxy per account).
            ids = [x for x in ids if x != aid]
        p["assigned_account_ids"] = ids
        _sync_legacy_singular(p)
    if target is None:
        raise KeyError(f"no proxy with label {label!r}")
    target["assigned_session"] = None
    return target


def unbind_account(label: str, account_id: str) -> dict[str, Any]:
    aid = str(account_id)
    with _lock:
        data = _load_for_write()
        target = _by_label(data, label)
        if target is None:
            raise KeyError(f"no proxy with label {label!r}")
        ids = _ids_on(target)
        target["assigned_account_ids"] = [x for x in ids if x != aid]
        _sync_legacy_singular(target)
        save(data)
        return target


def migrate_legacy_assignments(filename_to_account: dict[str, str]) -> int:
    rebound = 0
    with _lock:
        data = _load_for_write()
        for p in data["proxies"]:
            ids = list(p.get("assigned_account_ids") or [])
            legacy = p.get("assigned_account_id")
            if legacy and str(legacy) not in [str(x) for x in ids]:
                ids.append(str(legacy))
                p["assigned_account_ids"] = ids
            if ids:
                _sync_legacy_singular(p)
                continue
            sf = p.get("assigned_session")
            if sf and sf in filename_to_account:
                aid = str(filename_to_account[sf])
                p["assigned_account_ids"] = [aid]
                _sync_legacy_singular(p)
                rebound += 1
        if rebound:
            save(data)
    return rebound


def record_verification(label: str, *, ip: str | None, geo: str | None,
                        ok: bool) -> None:
    with _lock:
        data = _load_for_write()
        p = _by_label(data, label)
        if p is None:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if ok and ip:
            p.update(verified_ip=ip, verified_geo=geo, verified_at=stamp)
        elif ok:
            p.update(verified_at=stamp)
        else:
            p.update(verified_at=stamp, verified_ip=None)
        save(data)



POOL_ENV = "INFLOWW_PROXIES"
POOL_CLEAR = "none"
POOL_LABEL_PREFIX = "infloww-"
POOL_TIER_BREAK = "|"


def is_pool(p: dict[str, Any] | None) -> bool:
    return bool(p and p.get("pool"))


_POOL_LABEL_RE = re.compile(r"^infloww-[0-9a-f]{8}$")


def is_reserved_label(label: str) -> bool:
    return bool(_POOL_LABEL_RE.match(label or ""))


def pool_entries(reg: Registry | None = None) -> list[dict[str, Any]]:
    data = load() if reg is None else _known(reg)
    return [p for p in (data or {}).get("proxies", []) if is_pool(p)]


def parse_pool(text: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    tier = 0
    for raw in re.split(r"[\n,]", text or ""):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == POOL_TIER_BREAK:
            tier += 1
            continue
        if POOL_TIER_BREAK in line:
            errors.append(f"{redact_line(line)}: a tier break `{POOL_TIER_BREAK}` must be an item of its own")
            continue
        try:
            e = parse_proxy_line(line)
        except ValueError as exc:
            errors.append(f"{redact_line(line)}: {exc}")
            continue
        key = f"{e['scheme']}://{e.get('username') or ''}@{e['host']}:{e['port']}"
        e["label"] = POOL_LABEL_PREFIX + hashlib.sha256(key.encode()).hexdigest()[:8]
        e["tier"] = tier
        if any(x["label"] == e["label"] for x in entries):
            continue
        entries.append(e)
    return entries, errors


def sync_pool(text: str | None, rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random
    clear = (text or "").strip().lower() == POOL_CLEAR
    wanted, errors = ([], []) if clear else parse_pool(text)
    result: dict[str, Any] = {"size": 0, "errors": errors, "rebound": 0,
                              "dropped": 0, "changed": False, "skipped": None}
    with _lock:
        try:
            data = _load_for_write()
        except RegistryUnreadable:
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
                if label in want:
                    log.warning("%s: label %s is held by a custom proxy; that pool proxy is skipped",
                                POOL_ENV, label)
                    seen.add(label)
                kept.append(p)
            elif label in want and label not in seen:
                e = want[label]
                p.update({k: e.get(k) for k in ("host", "port", "scheme", "username", "password", "tier")})
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


def _endpoint(p: dict[str, Any]) -> str:
    return f"{p.get('host') or ''}:{p.get('port') or ''}"


def _egress_key(entries: list[dict[str, Any]]) -> Callable[[dict[str, Any]], str]:
    ip_of: dict[str, str] = {}
    for p in entries:
        if p.get("verified_ip"):
            ip_of.setdefault(_endpoint(p), str(p["verified_ip"]))
    return lambda p: str(p.get("verified_ip") or ip_of.get(_endpoint(p)) or _endpoint(p))


def egress_identity(proxy_url: str | None, reg: Registry) -> str:
    if not proxy_url:
        return "direct"
    host, _, port = proxy_url.rsplit("@", 1)[-1].split("://", 1)[-1].rpartition(":")
    return _egress_key((_known(reg) or {}).get("proxies") or [])({"host": host, "port": port})


Geo = Callable[[dict[str, Any]], str | None]
Verify = Callable[[dict[str, Any]], bool]


def _country(p: dict[str, Any] | None, geo: Geo) -> str | None:
    return (geo(p) or p.get("verified_geo") or None) if p else None


def _loads(data: dict[str, Any], deactivated: frozenset[str],
           skip: str | None = None) -> tuple[Callable[[dict[str, Any]], str], dict[str, int]]:
    entries = data.get("proxies", [])
    key = _egress_key(entries)
    used: dict[str, int] = {}
    for p in entries:
        used[key(p)] = used.get(key(p), 0) + sum(1 for x in _ids_on(p) if x != skip and x not in deactivated)
    return key, used


def _pick_pool(candidates: list[dict[str, Any]], data: dict[str, Any], aid: str,
               rng: random.Random, *, like: dict[str, Any] | None, geo: Geo,
               deactivated: frozenset[str]) -> dict[str, Any]:
    key, used = _loads(data, deactivated, skip=aid)
    want_geo = _country(like, geo)
    same = [p for p in candidates if want_geo and _country(p, geo) in (want_geo, None)]
    candidates = same or candidates
    least = min(used.get(key(p), 0) for p in candidates)
    return rng.choice([p for p in candidates if used.get(key(p), 0) == least])


def _pick_answering(candidates: list[dict[str, Any]], data: dict[str, Any], aid: str,
                    rng: random.Random, *, like: dict[str, Any] | None, geo: Geo,
                    verify: Verify, checked: dict[str, bool], deactivated: frozenset[str],
                    probes: int | None = None, first_tier: int | None = None) -> dict[str, Any] | None:
    want_geo = _country(like, geo)

    def near(p: dict[str, Any]) -> bool:
        return not want_geo or _country(p, geo) in (want_geo, None)

    for tier in _tiers(candidates, first_tier):
        left = list(tier)
        spare = None
        while left:
            if spare and not any(near(p) for p in left):
                return spare
            pick = _pick_pool(left, data, aid, rng, like=like, geo=geo, deactivated=deactivated)
            label = pick.get("label") or ""
            if label not in checked:
                if probes is not None and probes <= 0:
                    return None
                checked[label] = bool(verify(pick))
                probes = None if probes is None else probes - 1
            if checked[label]:
                if near(pick):
                    return pick
                spare = spare or pick
            left = [p for p in left if p.get("label") != label]
        if spare:
            return spare
    return None


ATTACH_PROBES = 2


def _tier(p: dict[str, Any]) -> int:
    return int(p.get("tier") or 0)


def _tiers(entries: list[dict[str, Any]], first: int | None = None) -> list[list[dict[str, Any]]]:
    return [[p for p in entries if _tier(p) == t]
            for t in sorted({_tier(p) for p in entries}, key=lambda t: (t != first, t))]


def _pool_entry_of(data: dict[str, Any], aid: str) -> dict[str, Any] | None:
    return next((p for p in data["proxies"] if is_pool(p) and aid in _ids_on(p)), None)


def assign_pool(account_id: str, *, bad: set[str], dead: set[str], due: set[str], geo: Geo, verify: Verify,
                deactivated: frozenset[str],
                rng: random.Random | None = None) -> tuple[dict[str, Any], bool]:
    aid = str(account_id)
    rng = rng or random
    data = load()
    current = _pool_entry_of(data, aid)
    cur = current.get("label") if current else None
    if current and cur not in due:
        return current, True
    pool = [p for p in data["proxies"] if is_pool(p)]
    if not pool:
        raise LookupError(f"no {BRAND_NAME} proxies are set up on this relay")
    candidates = [p for p in pool if p.get("label") not in bad and p.get("label") != cur]
    checked: dict[str, bool] = {}
    pick = _pick_answering(candidates, data, aid, rng, like=current, geo=geo, verify=verify, checked=checked,
                           deactivated=deactivated,
                           probes=ATTACH_PROBES, first_tier=_tier(current) if current else None)
    if pick is None:
        if current:
            return current, True
        untried = [p for p in candidates if (p.get("label") or "") not in checked]
        alive = [p for p in pool if p.get("label") not in dead]
        pick = _pick_pool(_tiers(untried or candidates or alive or pool)[0], data, aid, rng,
                          like=None, geo=geo, deactivated=deactivated)
    with _lock:
        data = _load_for_write()
        now = _pool_entry_of(data, aid)
        if now is not None and now.get("label") != cur:
            return now, True
        target = _bind(data, pick["label"], aid)
        save(data)
    return target, False


def failover_pool(label: str, *, bad: set[str], geo: Geo, verify: Verify,
                  deactivated: frozenset[str],
                  rng: random.Random | None = None) -> list[str] | None:
    rng = rng or random
    data = load()
    source = _by_label(data, label)
    if not is_pool(source) or not _ids_on(source):
        return None
    skip = set(bad) | {label}
    healthy = [p for p in data["proxies"] if is_pool(p) and p.get("label") not in skip]
    checked: dict[str, bool] = {}
    plan: dict[str, str] = {}
    for aid in _ids_on(source):
        target = _pick_answering(healthy, data, aid, rng, like=source, geo=geo, verify=verify, checked=checked,
                                 deactivated=deactivated, first_tier=_tier(source))
        if target is None:
            break
        plan[aid] = target["label"]
        target["assigned_account_ids"] = _ids_on(target) + [aid]
    if not plan:
        return []
    with _lock:
        data = _load_for_write()
        by_label = {p.get("label"): p for p in data["proxies"]}
        source = by_label.get(label)
        if not is_pool(source):
            return None
        moved = [aid for aid in _ids_on(source)
                 if aid in plan and is_pool(by_label.get(plan[aid]))]
        if not moved:
            return []
        for aid in moved:
            _bind(data, plan[aid], aid)
        save(data)
    return moved


REBALANCE_PROBES = 2


def rebalance_step(*, bad: set[str], due: set[str], geo: Geo, verify: Verify, deactivated: frozenset[str],
                   tiers: tuple[int, ...] = (0,),
                   rng: random.Random | None = None) -> tuple[str, str, str] | None:
    rng = rng or random
    data = load()
    pool = [p for p in data["proxies"] if is_pool(p)]
    key, used = _loads(data, deactivated)
    for t in tiers:
        tier = [p for p in pool if _tier(p) == t]
        if not tier or any(p.get("label") in bad or p.get("label") in due for p in tier):
            continue
        source = max(tier, key=lambda p: used.get(key(p), 0))
        want_geo = _country(source, geo)
        idle = [p for p in tier if not used.get(key(p), 0)
                and (not want_geo or _country(p, geo) in (want_geo, None))]
        mover = next((a for a in reversed(_ids_on(source)) if a not in deactivated), None)
        if used.get(key(source), 0) < 2 or not idle or mover is None:
            continue
        target = _pick_answering(idle, data, mover, rng, like=source, geo=geo, verify=verify, checked={},
                                 deactivated=deactivated, probes=REBALANCE_PROBES)
        if target is None or (want_geo and _country(target, geo) not in (want_geo, None)):
            continue
        src, dst = source["label"], target["label"]
        with _lock:
            data = _load_for_write()
            key, used = _loads(data, deactivated)
            now_src, now_dst = _by_label(data, src), _by_label(data, dst)
            if not (is_pool(now_src) and mover in _ids_on(now_src) and is_pool(now_dst)
                    and not used.get(key(now_dst), 0)):
                return None
            _bind(data, dst, mover)
            save(data)
        return mover, src, dst
    return None



POOL_PLACEHOLDER = "[inflowwww-proxy]"
_SCRUB_MIN_LEN = 4
_pool_tokens_cache: dict[tuple, tuple[str, ...]] = {}


def _pool_tokens() -> tuple[str, ...]:
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
    if not text:
        return text
    toks = _pool_tokens()
    for t in toks:
        if t in text:
            text = text.replace(t, POOL_PLACEHOLDER)
    return text


def unbind_pool(account_id: str) -> bool:
    current = get_for_account(account_id)
    if not is_pool(current):
        return False
    unbind_account(current["label"], account_id)
    return True
