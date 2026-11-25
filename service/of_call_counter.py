from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import math
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import stats_file

log = logging.getLogger("of-relay.of_call_counter")

SCHEMA = 1
# Copied from db/write_telemetry._ID_SEG so this module stays a stdlib leaf (importing db/ pulls in the engine).
_ID_SEG = re.compile(r"/(?:\d+|[0-9a-fA-F-]{16,})(?=/|$)")
_USERS_SEG = re.compile(r"(/users/)(?!(?:me|list|notifications|performers|settings)(?:/|$))[^/]+")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        v = float(raw or default)
    except ValueError:
        v = math.nan
    if math.isfinite(v) and v > 0:
        return v
    log.warning("of_call_stats_bad_knob %s=%r; default %g", name, raw[:40], default)
    return default


FLUSH_S = _env_float("OF_CALL_STATS_FLUSH_S", 30.0)
MAX_ROWS = int(_env_float("OF_CALL_STATS_MAX_ROWS", 20000))


def stats_path() -> Path | None:
    return stats_file.beside_db("OF_CALL_STATS_PATH", "of_call_stats.json")


_lock = threading.Lock()
_write_lock = threading.Lock()
_counts: dict[tuple[str, str, str, str], int] = {}
_folded = 0
_started_at = time.time()
_boots = 1
_flushed_at: float | None = None
_write_error: str | None = None
_path: Path | None = None
_unobserved_s = 0.0
_unobserved_since = _started_at


def status_class(status) -> str:
    if not isinstance(status, int):
        return "error"
    if status in (401, 403, 429):
        return str(status)
    if 200 <= status < 600:
        return f"{status // 100}xx"
    return "error"


def path_key(method, url) -> str:
    p = urlsplit(str(url or "")).path or "/"
    p = _USERS_SEG.sub(r"\1{}", _ID_SEG.sub("/{}", p))
    return f"{str(method or '?').upper()} {p}"


# ContextVar so a label follows tasks and to_thread work started inside; a bare threading.Thread starts empty.
_caller: contextvars.ContextVar[str | None] = contextvars.ContextVar("of_call_counter_caller", default=None)
_DASH_ID = re.compile(r"-(?:\d+|[0-9a-fA-F]{8,})(?=-|$)")


def fold_caller(name) -> str:
    return _DASH_ID.sub("-{}", _ID_SEG.sub("/{}", str(name)))


@contextlib.contextmanager
def caller(name: str):
    token = _caller.set(fold_caller(name))
    try:
        yield
    finally:
        _caller.reset(token)


async def label_request_calls(request, call_next):
    with caller("route:" + path_key(request.method, request.url.path)):
        return await call_next(request)


def caller_kind() -> str:
    label = _caller.get()
    if label is not None:
        return label
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return "task:" + fold_caller(task.get_name()) if task is not None else "unlabelled"


def record(account_id, method, url, status) -> None:
    global _folded
    try:
        key = (caller_kind(), path_key(method, url), str(account_id) if account_id else "-",
               status_class(status))
        with _lock:
            if key not in _counts and len(_counts) >= MAX_ROWS:
                key = ("other", "other", key[2], key[3])
                _folded += 1
            _counts[key] = _counts.get(key, 0) + 1
    except Exception:  # noqa: BLE001 — counting must never break an OF call
        pass


def snapshot() -> dict:
    with _lock:
        counts = dict(_counts)
        folded = _folded
    return {"v": SCHEMA, "started_at": _started_at, "flushed_at": _flushed_at, "boots": _boots,
            "rows": [[*k, n] for k, n in sorted(counts.items())], "folded": folded,
            "write_error": _write_error, "unobserved_s": _unobserved_s, "unobserved_since": _unobserved_since}


def flush() -> None:
    global _flushed_at, _write_error
    p = _path
    if p is None:
        return
    with _write_lock:
        try:
            at = time.time()
            snap = snapshot()
            snap["flushed_at"] = at
            stats_file.write(p, snap, separators=(",", ":"))
            _flushed_at, _write_error = at, None
        except Exception as exc:  # noqa: BLE001
            _write_error = f"{type(exc).__name__}: {exc}"[:200]


def _count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2 ** 63


def _time(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def _load(p: Path) -> None:
    global _started_at, _boots, _folded, _unobserved_s, _unobserved_since
    try:
        raw = stats_file.read(p)
        if not isinstance(raw, dict) or raw.get("v") != SCHEMA:
            log.warning("of_call_stats_schema_mismatch path=%s; fresh window", p)
            return
        rows, started = raw.get("rows"), raw.get("started_at")
        bad = next((why for why, ok in (
            ("rows", isinstance(rows, list) and all(
                isinstance(r, list) and len(r) == 5 and all(isinstance(x, str) for x in r[:4]) and _count(r[4]) and r[4] > 0
                for r in rows)),
            ("started_at", _time(started) and started > 0),
            ("boots", _count(raw.get("boots"))), ("folded", _count(raw.get("folded")))) if not ok), None)
        if bad:
            log.warning("of_call_stats_bad_field path=%s field=%s; fresh window", p, bad)
            return
        now, fl = time.time(), raw.get("flushed_at")
        us, since = raw.get("unobserved_s"), raw.get("unobserved_since")
        gap = now - fl if _time(fl) else None
        tally = (us + gap, float(since)) if (_time(us) and us >= 0 and _time(since) and gap is not None
                                             and math.isfinite(gap) and gap >= 0) else None
        started = float(started)
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001 — a bad file never fails the boot
        log.warning("of_call_stats_unreadable path=%s %s: %s; fresh window", p, type(exc).__name__, str(exc)[:120])
        return
    if tally is None:
        log.warning("of_call_stats_unobserved_unknown path=%s; downtime tally restarts at this boot", p)
        tally = (0.0, now)
    with _lock:
        for r in rows:
            k = tuple(r[:4])
            _counts[k] = _counts.get(k, 0) + r[4]
        _folded += raw["folded"]
    _started_at, _boots = started, raw["boots"] + 1
    _unobserved_s, _unobserved_since = tally


def _flusher() -> None:
    while True:
        time.sleep(FLUSH_S)
        flush()


def start(path: Path | str | None) -> None:
    global _path
    if path is None or _path is not None:
        return
    _path = Path(path)
    _load(_path)
    flush()
    threading.Thread(target=_flusher, name="of-call-stats-flush", daemon=True).start()
