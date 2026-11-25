from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

import accounts as account_registry
import live_rev
from of_signer import verify_rules

log = logging.getLogger("of-relay.sign-rules")

RULE_KEYS = ("static_param", "start", "end", "checksum_indexes", "checksum_constant")

_lock = threading.Lock()
_running = False
_again = False
_last: dict[str, Any] = {}
# Off until server startup enables it, so scripts and tests never start a thread that rewrites session files.
_auto = False


def enable_background() -> None:
    global _auto
    _auto = True


def _complete(rules: Any) -> bool:
    return isinstance(rules, dict) and all(rules.get(k) not in (None, "") for k in RULE_KEYS)


def _rules_time(session: dict) -> str:
    signing = session.get("signing") or {}
    return str(signing.get("rules_captured_at") or session.get("captured_at") or "")


def _build_time(rev: Any) -> str | None:
    m = re.match(r"(\d{12})-", str(rev or ""))
    return m.group(1) if m else None


def _as_new(session: dict, rev: str, donor_ts: str) -> bool:
    mine, theirs = _build_time((session.get("headers") or {}).get("x_of_rev")), _build_time(rev)
    if mine and theirs:
        return mine >= theirs
    return _rules_time(session) >= donor_ts


def _sessions() -> list[tuple[str, Any, dict]]:
    out = []
    for meta in account_registry.list_accounts(include_watchers=True):
        aid = meta.get("id")
        if not aid or not meta.get("has_session") or meta.get("platform", "onlyfans") != "onlyfans":
            continue
        sp = account_registry.latest_session_path(aid)
        if sp is None:
            continue
        try:
            out.append((aid, sp, json.loads(sp.read_text())))
        except Exception:
            log.warning("sign_rules: cannot read session for %s", aid, exc_info=True)
    return out


def _donor(sessions: list[tuple[str, Any, dict]], rev: str) -> tuple[str, dict] | None:
    best: tuple[str, str, dict] | None = None
    for aid, _sp, s in sessions:
        # Signing rules are tied to the OF build (x-of-rev).
        if (s.get("headers") or {}).get("x_of_rev") != rev:
            continue
        signing = s.get("signing") or {}
        rules, samples = signing.get("rules"), signing.get("samples") or []
        if not _complete(rules) or not samples:
            continue
        # Samples verify checksum indexes and constant. A signed 2xx validates static_param/start/end.
        if not signing.get("signed_ok_at") or signing.get("static_param_source") == "override":
            continue
        try:
            ok, _ = verify_rules(rules, samples)
        except Exception:
            ok = False
        if not ok:
            continue
        ts = str(s.get("captured_at") or "")
        if best is None or ts > best[1]:
            best = (aid, ts, s)
    return None if best is None else (best[0], best[2])


def refresh(reason: str = "manual") -> dict[str, Any]:
    from of_client import update_session_file
    import client_pool

    rev = live_rev.get().get("rev")
    result: dict[str, Any] = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason, "rev": rev, "donor": None, "updated": [], "failed": [],
    }
    if not rev:
        result["skipped"] = "live build unknown"
        return _remember(result)
    sessions = _sessions()
    found = _donor(sessions, rev)
    if found is None:
        result["skipped"] = "no verified session at the live build"
        return _remember(result)
    donor_aid, donor = found
    rules = {k: donor["signing"]["rules"][k] for k in RULE_KEYS}
    donor_ts = str(donor.get("captured_at") or "")
    result["donor"] = donor_aid

    def _apply(data: dict) -> None:
        data.setdefault("headers", {})["x_of_rev"] = rev
        signing = data.setdefault("signing", {})
        signing["rules"] = dict(rules)
        signing["rules_captured_at"] = donor_ts
        signing["rules_from"] = {"account_id": donor_aid, "x_of_rev": rev}
        signing.pop("signed_ok_at", None)

    for aid, sp, s in sessions:
        if aid == donor_aid or (s.get("headers") or {}).get("x_of_rev") == rev:
            continue
        if _as_new(s, rev, donor_ts):
            continue
        try:
            update_session_file(sp, _apply)
        except Exception:
            log.warning("sign_rules: cannot update session for %s", aid, exc_info=True)
            result["failed"].append(aid)
            continue
        client_pool.evict(aid)
        result["updated"].append(aid)
    if result["updated"]:
        log.info("sign rules for build %s copied from %s to %d account(s): %s",
                 rev, donor_aid, len(result["updated"]), ",".join(result["updated"]))
    return _remember(result)


def _remember(result: dict[str, Any]) -> dict[str, Any]:
    global _last
    _last = result
    return result


def last() -> dict[str, Any]:
    return dict(_last)


def request_refresh(reason: str) -> bool:
    global _running, _again
    if not _auto:
        return False
    with _lock:
        if _running:
            _again = True
            return False
        _running = True
    threading.Thread(target=_run, args=(reason,), name="sign-rules-refresh", daemon=True).start()
    return True


def _run(reason: str) -> None:
    global _running, _again
    while True:
        try:
            refresh(reason)
        except Exception:
            log.exception("sign rules refresh failed (reason=%s)", reason)
        with _lock:
            if not _again:
                _running = False
                return
            _again = False
            reason = "queued"
