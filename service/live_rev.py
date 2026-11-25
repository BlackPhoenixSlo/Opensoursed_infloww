from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

log = logging.getLogger("of-relay.live-rev")

_lock = threading.Lock()
# OF's x-of-rev appears only in SPA request/response headers (never homepage HTML); an older-build session keeps working, so it is no freshness signal.
_cache: dict[str, Any] = {
    "rev": None,
    "fetched_at": 0.0,
    "source": None,
    "error": None,
}


def note(rev: str | None, source: str = "unknown") -> None:
    if not rev:
        return
    rev = str(rev).strip()
    if not rev:
        return
    with _lock:
        if _cache["rev"] == rev:
            _cache["fetched_at"] = time.time()
            return
        prev = _cache["rev"]
        _cache.update(rev=rev, source=source, fetched_at=time.time(), error=None)
    if prev != rev:
        log.info("live x-of-rev updated %r → %r (source=%s)", prev, rev, source)
        try:
            # Lazy: sign_rules imports this module.
            import sign_rules
            sign_rules.request_refresh(f"build {rev}")
        except Exception:
            log.warning("sign rules refresh trigger failed", exc_info=True)


def _seed_from_sessions() -> None:
    try:
        import accounts as account_registry
    except Exception:
        log.warning("live_rev session seed: cannot import accounts module", exc_info=True)
        return
    candidates: list[tuple[str, str, str]] = []
    try:
        for meta in account_registry.list_accounts():
            aid = meta.get("id")
            if not aid:
                continue
            sp = account_registry.latest_session_path(aid)
            if not sp:
                continue
            try:
                s = json.loads(sp.read_text())
            except Exception:
                log.warning("live_rev session seed: cannot read session for %s", aid, exc_info=True)
                continue
            rev = (s.get("headers") or {}).get("x_of_rev")
            ts = s.get("captured_at")
            if rev and ts:
                candidates.append((str(ts), str(rev), str(aid)))
    except Exception:
        log.warning("live_rev session seed walk failed", exc_info=True)
        return
    if not candidates:
        log.info("live_rev session seed: no captured x_of_rev in any account session")
        return
    candidates.sort(reverse=True)
    _, rev, aid = candidates[0]
    note(rev, source=f"session_seed:{aid}")


def refresh(force: bool = False) -> dict[str, Any]:
    with _lock:
        have_rev = _cache["rev"]
    if not have_rev or force:
        _seed_from_sessions()
    return dict(_cache)


def get(stale_ok: bool = True) -> dict[str, Any]:
    del stale_ok
    if _cache["rev"] is None:
        return refresh()
    return dict(_cache)
