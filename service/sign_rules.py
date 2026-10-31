"""
Central sign-rule refresh (roadmap 2.17).

OF's request-signing rules (static_param, start, end, checksum_indexes,
checksum_constant) belong to an OF build (`x-of-rev`), not to a user: every
account at one build signs with the same five values. session_bootstrap's
`_lookup_static_param_for_rev` already leans on that. So when OF ships a new
build, ONE capture at that build, of any account, carries what every other
account needs; nobody has to re-capture the rest one by one.

`refresh()` picks the donor: the freshest session at the live build (as
live_rev last saw OF answer) whose rules reproduce its own captured samples
(checksum_indexes, checksum_constant) AND that OF has answered a signed call
with a 2xx since the capture (`signing.signed_ok_at`, stamped by OFClient),
which is the only proof of static_param, start and end. A static_param typed
into the paste-curl override box never donates.
It writes the donor's build and rules into every other OnlyFans account's
latest session that sits at a different build with older rules, and evicts
those accounts' pooled clients so their next call signs with the new rules.
Cookies, x-bc and the user agent are the account's own and stay untouched.

Older never overwrites newer: OF's build ids start with their build time
(`202610091632-c45cc0ac3f`), and a donor only replaces a session on an older
build. So a build flip-flopping during an OF rollout cannot walk accounts
back, while a capture from a long-open tab (fresh cookies, stale build) still
takes the new rules. A build id without that prefix falls back to when the
rules were captured (`signing.rules_captured_at`, else the file's
`captured_at`).

Triggers (`request_refresh`): live_rev seeing OF answer with a new build,
and a session's first 2xx (a new capture becoming a possible donor). They
only start a run once server startup has called `enable_background()`.
Single-flight: one refresh runs at a time, on its own thread, and a trigger
that lands during a run queues exactly one more run, not one per account.
"""

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
# Off until server startup turns it on (`enable_background`), so a script or
# a test that makes a client note a new build never starts a thread that
# rewrites session files; tests call refresh().
_auto = False


def enable_background() -> None:
    global _auto
    _auto = True


def _complete(rules: Any) -> bool:
    return isinstance(rules, dict) and all(rules.get(k) not in (None, "") for k in RULE_KEYS)


def _rules_time(session: dict) -> str:
    """When the session's current rules were captured (ISO-ish, sorts as text)."""
    signing = session.get("signing") or {}
    return str(signing.get("rules_captured_at") or session.get("captured_at") or "")


def _build_time(rev: Any) -> str | None:
    """`202610091632` of `202610091632-c45cc0ac3f`; None for any other shape."""
    m = re.match(r"(\d{12})-", str(rev or ""))
    return m.group(1) if m else None


def _as_new(session: dict, rev: str, donor_ts: str) -> bool:
    """Are the session's rules at least as new as the donor's (build `rev`,
    rules captured at `donor_ts`)? By build time when both ids carry one."""
    mine, theirs = _build_time((session.get("headers") or {}).get("x_of_rev")), _build_time(rev)
    if mine and theirs:
        return mine >= theirs
    return _rules_time(session) >= donor_ts


def _sessions() -> list[tuple[str, Any, dict]]:
    """(account id, latest session path, parsed session) for every OnlyFans
    account with a readable session."""
    out = []
    # Watchers too: a watcher signs its reads with the same rules.
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
    """The freshest session at `rev` whose own rules reproduce its own samples.
    A session whose rules were copied in here has samples from its old build,
    fails the check, and so is never a donor."""
    best: tuple[str, str, dict] | None = None
    for aid, _sp, s in sessions:
        if (s.get("headers") or {}).get("x_of_rev") != rev:
            continue
        signing = s.get("signing") or {}
        rules, samples = signing.get("rules"), signing.get("samples") or []
        if not _complete(rules) or not samples:
            continue
        if not signing.get("signed_ok_at") or signing.get("static_param_source") == "override":
            continue  # static_param, start and end unproven by OF
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
    """Spread the live build's rules to every account on an older build.
    Returns (and keeps, for `last()`) what it did."""
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
        # Normal right after OF ships: nobody has captured at the new build yet.
        # The next capture at it (any account) triggers the spread.
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
        signing.pop("signed_ok_at", None)  # its own proof was for the old rules

    for aid, sp, s in sessions:
        if aid == donor_aid or (s.get("headers") or {}).get("x_of_rev") == rev:
            continue
        if _as_new(s, rev, donor_ts):
            continue  # its rules are as new as the donor's: never walk back
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
    """The last refresh's result ({} before the first)."""
    return dict(_last)


def request_refresh(reason: str) -> bool:
    """Run `refresh` on a background thread, single-flight. Safe from any
    thread and cheap to call often. True when this call started a run."""
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
