from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import CancelledError as _FuturesCancelled
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple

import atomic_json
import gdrive
import media_prep
import of_client
import of_paging
import vault_carrier
from vault_upload_plan import (  # noqa: F401 — re-exports
    MAX_BYTES, MAX_FILES, MAX_MB, Limits, _apply_caps, _item, cap_for,
    drive_meta, fan_handle, parse_meta, parse_metas, resolve_budget)

log = logging.getLogger("of-relay.vault_upload")

# NOT a socket timeout: curl_cffi raises its own Timeout (an OSError, not the builtin TimeoutError), so a slow create is never mistaken for "may have sent".
_MAYBE_WRITTEN = (FuturesTimeout, _FuturesCancelled, asyncio.CancelledError)

HERE = Path(__file__).resolve().parent
SPOOL_ROOT = Path(os.environ.get("VAULT_SPOOL_DIR") or (HERE / "vault_spool"))
LOCK_DIR = SPOOL_ROOT / "locks"
# Spool, not TMPDIR: a SIGKILL between staging and the run leaves bytes where sweep() finds them; a container never cleans /tmp.
STAGE_ROOT = SPOOL_ROOT / "incoming"

ITEM_STATUSES = ("pending", "uploading", "done", "failed", "skipped")
RUN_PHASES = ("collecting", "uploading", "mirroring", "finished")

_RUN_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}-\d{8}T\d{6}-[0-9a-f]{6}")


# Deliberately NOT read from run.json: a stale "running" file from a killed process must never lock the feature out forever.
_live: dict[str, str] = {}
_lock = threading.Lock()

@dataclass
class _Inbox:
    q: "queue.Queue" = field(default_factory=queue.Queue)
    stage_dir: str | None = None
    busy: int = 0


_inbox: dict[str, _Inbox] = {}
NOT_TAKING = "that import is no longer taking files — start a new one"


class NotTaking(RuntimeError):
    pass
OPEN_IDLE_S = float(os.environ.get("VAULT_OPEN_IDLE_S") or 10 * 60)


# Memo of Drive files already uploaded: re-downloading a whole folder to find nothing to do got this key Google's throttle page.
_MEMO_PATH = SPOOL_ROOT / "drive_memo.json"
# Guards memo writes: two imports at once would drop each other's entries; across processes only different accounts race, and a lost entry costs one re-download.
_memo_lock = threading.Lock()


def _memo_load() -> dict:
    try:
        return json.loads(_MEMO_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _memo_remember(account_id: str, drive_md5: str, vault_id) -> None:
    if not drive_md5 or not vault_id:
        return
    with _memo_lock:
        memo = _memo_load()
        memo.setdefault(str(account_id), {})[drive_md5] = vault_id
        SPOOL_ROOT.mkdir(parents=True, exist_ok=True)
        atomic_json.write_atomic(_MEMO_PATH, memo)


def _memo_lookup(account_id: str, drive_md5: str, client) -> int | None:
    if not drive_md5:
        return None
    with _memo_lock:
        vid = _memo_load().get(str(account_id), {}).get(drive_md5)
    if not vid:
        return None
    try:
        media = client.vault_media_by_id(int(vid)) or {}
    except Exception:  # noqa: BLE001 — a stale memo entry is not an error
        log.info("vault memo: %s no longer resolves, will re-upload", vid)
        return None
    if media.get("hidden") or media.get("isHidden"):
        log.info("vault memo: %s is hidden in the vault, treating as absent", vid)
        return None
    return int(vid)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(run_id: str) -> Path:
    if not _RUN_ID_RE.fullmatch(run_id or ""):
        raise ValueError(f"not a run id: {run_id!r}")
    return SPOOL_ROOT / run_id


def _state_path(run_id: str) -> Path:
    return _run_dir(run_id) / "run.json"


def read_state(run_id: str, cache: dict | None = None) -> dict | None:
    try:
        state = json.loads(_state_path(run_id).read_text())
    except (OSError, ValueError):
        return None
    return _reconcile(state, cache)


def _save(state: dict) -> None:
    atomic_json.write_atomic(_state_path(state["run_id"]), state)


def _intent_unresolved(item: dict) -> bool:
    if item.get("carrier_write_pending"):
        return True
    return bool(item.get("carrier_intent")
                and not item.get("carrier_post_id")
                and not item.get("carrier_scan_clear"))


def account_runs(account_id: str) -> list[dict]:
    cache: dict[str, bool] = {}
    return [st for d in _dirs()
            if (st := read_state(d.name, cache))
            and str(st.get("account_id")) == str(account_id)]


def latest_of(runs: list[dict]) -> dict | None:
    return max(runs, key=lambda s: s.get("created_at") or "") if runs else None


def latest_run(account_id: str) -> dict | None:
    return latest_of(account_runs(account_id))


def carriers_outstanding(account_id: str, runs: list[dict]) -> tuple[int, int]:
    undeletable = unrecorded = 0
    cache: dict[str, bool] = {}
    for st in runs:
        if _run_is_live(st, cache):
            continue
        for riders in _carriers(st.get("items") or []).values():
            if _live_post(riders):
                undeletable += 1
            elif any(_intent_unresolved(i) for i in riders):
                unrecorded += 1
    return undeletable, unrecorded


def _dirs() -> list[Path]:
    if not SPOOL_ROOT.is_dir():
        return []
    return [d for d in SPOOL_ROOT.iterdir()
            if d.is_dir() and _RUN_ID_RE.fullmatch(d.name)]


def _reconcile(state: dict, cache: dict | None = None) -> dict:
    if state.get("status") != "running" or _run_is_live(state, cache):
        return state
    decided = state.get("terminal_status")
    if state.get("phase") == "mirroring" and decided in ("done", "failed"):
        return {**state, "status": decided, "terminal_status": None}
    return {**state, "status": "interrupted",
            "error": state.get("error") or "relay restarted mid-run"}



# A lock nobody can be holding: imports last hours, so older than this is a crash whose pid was recycled (else permanent lockout).
_LOCK_MAX_AGE_S = 24 * 3600
# Same ceiling for the in-process registry: an unbounded _live entry would defer the carrier sweep for the relay's whole life (weeks).
_LIVE_MAX_STALL_S = 6 * 3600
_PID_START_TTL_S = 30.0
_pid_start_memo: dict[int, tuple[float, str | None]] = {}

# An instance id means "not written by anyone I can see": UNKNOWN, not dead, since a pid only means something inside one pid namespace.
_INSTANCE_ID = uuid.uuid4().hex


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _pid_start(pid: int) -> str | None:
    now = time.time()
    hit = _pid_start_memo.get(pid)
    if hit and now - hit[0] < _PID_START_TTL_S:
        return hit[1]
    stamp = None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        stamp = raw.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError, ValueError):
        try:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                                 capture_output=True, text=True, timeout=5)
            stamp = out.stdout.strip() or None
        except Exception:  # noqa: BLE001 — an unknown start time is not an error
            stamp = None
    _pid_start_memo[pid] = (now, stamp)
    return stamp


def _lock_path(account_id: str) -> Path:
    return LOCK_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', str(account_id))}.lock"


def _read_lock(path: Path) -> dict:
    try:
        rec = json.loads(path.read_text())
        return rec if isinstance(rec, dict) else {}
    except (OSError, ValueError):
        return {}


def _lock_holder(account_id: str) -> dict | None:
    p = _lock_path(account_id)
    rec = _read_lock(p)
    pid = rec.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    if not _pid_alive(pid):
        return None
    started, instance = rec.get("started"), rec.get("instance")
    now_started = _pid_start(pid)
    if (started and now_started and started != now_started
            and instance in (None, _INSTANCE_ID)):
        return None
    try:
        if time.time() - p.stat().st_mtime > _LOCK_MAX_AGE_S:
            return None
    except OSError:
        return None
    return rec


def _stalled(run_id: str | None) -> bool:
    try:
        return time.time() - _state_path(run_id).stat().st_mtime > _LIVE_MAX_STALL_S
    except (OSError, ValueError, TypeError):
        return False


def _account_is_live(account_id: str, cache: dict | None = None) -> bool:
    aid = str(account_id)
    if cache is not None and aid in cache:
        return cache[aid]
    mine = _live.get(aid)
    answer = (mine is not None and not _stalled(mine)) or _lock_holder(aid) is not None
    if cache is not None:
        cache[aid] = answer
    return answer


def _run_is_live(state: dict, cache: dict | None = None) -> bool:
    if state.get("finished_at") or state.get("status") != "running":
        return False
    aid, run_id = str(state.get("account_id")), state.get("run_id")
    mine = _live.get(aid)
    if mine is not None:
        return mine == run_id and not _stalled(run_id)
    holder = _lock_holder(aid) if _account_is_live(aid, cache) else None
    # A lock written before run ids were recorded cannot name its run: treat it as possibly this one rather than delete somebody's live carrier.
    return bool(holder) and holder.get("run_id") in (None, run_id)


def _acquire_lock(account_id: str, run_id: str | None = None) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    p = _lock_path(account_id)
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, json.dumps({
                    "pid": os.getpid(), "started": _pid_start(os.getpid()),
                    "instance": _INSTANCE_ID, "run_id": run_id,
                    "created_at": _now()}).encode())
            finally:
                os.close(fd)
            return p
        except FileExistsError:
            holder = _lock_holder(account_id)
            if holder and (holder.get("pid") != os.getpid()
                           or holder.get("instance") not in (None, _INSTANCE_ID)):
                raise RuntimeError(
                    f"another process (pid {holder.get('pid')}) is already "
                    f"importing to this account's vault — if that is wrong, "
                    f"delete {p}") from None
            log.warning("vault: clearing a stale import lock at %s (%s)",
                        p, _read_lock(p) or "unreadable")
            p.unlink(missing_ok=True)
    raise RuntimeError(
        f"could not take the vault import lock for this account ({p})")


def _release_lock(path: Path | None, run_id: str | None = None) -> None:
    # Release only while the lock still names OUR run: a second begin() between start()'s two statements would otherwise have its new lock deleted.
    if path is None:
        return
    try:
        if run_id is not None:
            held = _read_lock(path).get("run_id")
            if held is not None and held != run_id:
                log.info("vault: leaving the import lock %s alone — it names "
                         "run %s now, not %s", path, held, run_id)
                return
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("vault: could not release the import lock %s — %s", path, e)



def _new_state(run_id: str, aid: str, list_id: int | None,
               fan_id: int | None = None) -> dict:
    return {
        "run_id": run_id, "account_id": aid, "status": "running",
        "phase": "collecting", "created_at": _now(), "finished_at": None,
        "list_id": list_id, "error": None, "filing_error": None,
        "fan_id": fan_id,
        "filed_into_list": None, "spool_cleared_bytes": None,
        "terminal_status": None,
        "admitted": 0,
        "details_saved": None,
        "items": [],
    }


def landed_ids(state: dict) -> list[int]:
    return [int(it["vault_id"]) for it in (state or {}).get("items") or []
            if _landed(it)]


def _landed(it: Any) -> bool:
    return isinstance(it, dict) and it.get("status") == "done" and bool(it.get("vault_id"))


def begin(account_id: str, *, list_id: int | None = None,
          fan_id: int | None = None, keep_open: bool = False,
          stage_dir: str | None = None) -> str:
    aid = str(account_id)
    run_id = f"{aid}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    # In-process claim FIRST: taking the file lock first made a same-process second run see its own pid as stale, clear it, then release the lock the first run held.
    with _lock:
        if aid in _live:
            raise RuntimeError("a vault upload is already running for this account")
        _live[aid] = run_id
    lock_path = None
    try:
        lock_path = _acquire_lock(aid, run_id)
        # Inside the claim, so a read-only or full spool volume releases it instead of locking the account out until restart.
        _run_dir(run_id).mkdir(parents=True, exist_ok=True)
        _save(_new_state(run_id, aid, list_id, fan_id))
        if keep_open:
            with _lock:
                _inbox[run_id] = _Inbox(stage_dir=stage_dir)
    except Exception:
        with _lock:
            if _live.get(aid) == run_id:
                _live.pop(aid, None)
        _release_lock(lock_path, run_id)
        raise
    return run_id


def abandon(run_id: str, error: str) -> None:
    left = _stop_taking(run_id)
    state = read_state(run_id)
    aid = str((state or {}).get("account_id") or "")
    if state is not None:
        _record_unsent(state, left)
        state.update(status="failed", phase="finished",
                     error=error, finished_at=_now())
        _save(state)
    with _lock:
        if aid and _live.get(aid) == run_id:
            _live.pop(aid, None)
    _release_lock(_lock_path(aid) if aid else None, run_id)


@contextmanager
def receiving(run_id: str):
    with _lock:
        box = _inbox.get(run_id)
        if box is None:
            raise NotTaking(NOT_TAKING)
        box.busy += 1
    try:
        yield box.stage_dir
    except FileNotFoundError as e:
        with _lock:
            gone = _inbox.get(run_id) is not box
        if gone:
            raise NotTaking(NOT_TAKING) from e
        raise
    finally:
        with _lock:
            box.busy -= 1


def append(run_id: str, path: str, meta: dict | None = None) -> None:
    with _lock:
        box = _inbox.get(run_id)
        if box is None:
            raise NotTaking(NOT_TAKING)
        box.q.put((str(path), meta))


def close(run_id: str) -> bool:
    with _lock:
        box = _inbox.get(run_id)
        if box is None:
            return False
        box.q.put(None)
        return True


def _stop_taking(run_id: str) -> list[tuple]:
    with _lock:
        box = _inbox.pop(run_id, None)
    left: list[tuple] = []
    while box is not None:
        try:
            got = box.q.get_nowait()
        except queue.Empty:
            break
        if got is not None:
            left.append(got)
    return left


def _record_unsent(state: dict, left: list[tuple]) -> None:
    for path, meta in left:
        it = _item(Path(path).name, None, "local", None, status="failed",
                   error="the import ended before this file was uploaded — "
                         "add it again")
        it["meta"] = meta or None
        state.setdefault("items", []).append(it)


def landed_meta(state: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for it in (state or {}).get("items") or []:
        if _landed(it) and it.get("meta"):
            out[int(it["vault_id"])] = it["meta"]
    return out


def _mirror_landed(state: dict,
                   on_landed: Callable[[list[int], dict[int, dict]], Any] | None
                   ) -> None:
    if on_landed is None:
        return
    ids = landed_ids(state)
    if not ids:
        return
    # Failure is set but not published until the save after this call: publishing early lets a poll read a terminal state before the mirror lands.
    terminal = state["status"]
    state["status"] = "running"
    state["phase"] = "mirroring"
    state["terminal_status"] = terminal
    _save(state)
    try:
        got = on_landed(ids, landed_meta(state))
        if isinstance(got, dict):
            state["details_saved"] = got
    # The mirror hook waits on another thread; loop shutdown can interrupt the readback.
    except BaseException as e:  # noqa: BLE001 — see the docstring: nothing this
        # Deliberately NOT re-raised: re-raising skipped _cleanup_carriers and left the account claimed in _live.
        log.warning("vault run %s: mirror hook failed: %s: %s",
                    state.get("run_id"), type(e).__name__, e)
    finally:
        state["status"] = terminal
        state["terminal_status"] = None


def start(account_id: str, *, client, gate=None,
          local_paths: list[str] | None = None,
          drive_links: list[str] | None = None,
          list_id: int | None = None,
          run_id: str | None = None,
          on_landed: Callable[[list[int], dict[int, dict]], Any] | None = None,
          limits: Limits | None = None,
          metas: list[dict | None] | None = None,
          fan_id: int | None = None,
          send_gate=None) -> dict:
    aid = str(account_id)
    limits = (limits or Limits()).checked()
    adopted = run_id is not None
    if not adopted:
        run_id = begin(aid, list_id=list_id, fan_id=fan_id)
    state = read_state(run_id)
    if state is None or str(state.get("account_id")) != aid:
        raise RuntimeError(f"vault run {run_id} is not a live run for this account")
    state["status"] = "running"
    up = _Uploader(state, client, gate, send_gate, limits)

    try:
        items = _collect(state, local_paths or [], drive_links or [],
                         client=client, limits=limits, metas=metas)
        state["items"] = items
        state["phase"] = "uploading"
        _save(state)

        with up.running():
            for item in [i for i in items if i["status"] == "pending"]:
                up.add(item)
            _drain_inbox(up)
        _file_into_folder(state, client, gate)
        state["status"] = "done"
    except Exception as e:
        log.exception("vault batch %s failed", run_id)
        state["status"] = "failed"
        # Redacted: this slot is stored on disk and shown on the dashboard.
        state["error"] = gdrive.redact(f"{type(e).__name__}: {e}")
        for it in state.get("items") or []:
            if it.get("status") == "pending":
                it.update(status="failed",
                          error="not uploaded — the import stopped first")
    finally:
        _record_unsent(state, _stop_taking(run_id))
        _mirror_landed(state, on_landed)
        state["phase"] = "finished"
        state["finished_at"] = _now()
        _save(state)
        _cleanup_carriers(state, client, gate)
        _clear_spool(state)
        _save(state)
        with _lock:
            if _live.get(aid) == run_id:
                _live.pop(aid, None)
        _release_lock(_lock_path(aid), run_id)
    return state


class _Staged(NamedTuple):
    item: dict
    claim: of_client.UploadClaim
    renamed: str | None


class _Uploader:

    def __init__(self, state: dict, client, gate, send_gate, limits: Limits):
        self.state, self.client, self.limits = state, client, limits
        self.gate, self.send_gate = gate, send_gate
        if state.get("fan_id"):
            self.batch, self._deliver = 1, self._send
        else:
            self.batch, self._deliver = limits.carrier_batch, self._carry
        self.staged: list[_Staged] = []
        self._carried_at: float | None = None

    def add(self, item: dict) -> None:
        staged = _upload_one(self.state, item, self.client, self.limits)
        _save(self.state)
        if staged is not None:
            self.staged.append(staged)
            if len(self.staged) >= self.batch:
                self.flush()

    def flush(self) -> None:
        batch, self.staged = self.staged, []
        if not batch:
            return
        try:
            self._deliver(batch)
        except BaseException:
            try:
                _save(self.state)
            except Exception:  # noqa: BLE001 — never mask what is propagating
                log.exception("vault batch %s: could not save after a carrier "
                              "was interrupted", self.state["run_id"])
            raise
        _save(self.state)

    def _send(self, batch: list[_Staged]) -> None:
        (staged,) = batch
        gate, part = self.send_gate, next(i for i, it in enumerate(self.state["items"]) if it is staged.item)
        _send(self.state, staged, self.client, (lambda thunk: gate(thunk, part)) if gate else self.gate)

    def _carry(self, batch: list[_Staged]) -> None:
        if self.limits.pace_s and self._carried_at is not None:
            wait = self.limits.pace_s - (time.monotonic() - self._carried_at)
            if wait > 0:
                time.sleep(wait)
        if _carry(self.state, batch, self.client, self.gate):
            self._carried_at = time.monotonic()

    @contextmanager
    def running(self):
        try:
            yield self
        except Exception:
            try:
                self.flush()
            except Exception:  # noqa: BLE001 — the original error is the story
                log.exception("vault batch %s: carrying the staged claims on "
                              "the way out failed", self.state["run_id"])
            raise
        except BaseException:
            for s in self.staged:
                s.item.update(status="failed",
                              error="uploaded, but the import stopped before it "
                                    "reached the vault — add it again")
            self.staged = []
            raise
        self.flush()


def _drain_inbox(up: _Uploader) -> None:
    state = up.state
    run_id = state["run_id"]
    with _lock:
        box = _inbox.get(run_id)
    if box is None:
        return
    while True:
        if box.q.empty():
            up.flush()
        try:
            got = box.q.get(timeout=OPEN_IDLE_S)
        except queue.Empty:
            with _lock:
                if box.busy:
                    continue
            log.info("vault run %s: no file for %ss — no longer taking files",
                     run_id, OPEN_IDLE_S)
            break
        if got is None:
            break
        for item in _admit(state, [got], up.limits):
            up.add(item)
    for item in _admit(state, _stop_taking(run_id), up.limits):
        up.add(item)


def _admit(state: dict, group: list[tuple], limits: Limits) -> list[dict]:
    items = []
    for path, meta in group:
        p = Path(path)
        it = _item(p.name, str(p), "local", p.stat().st_size if p.exists() else None)
        it["meta"] = meta or None
        items.append(it)
    if not items:
        return []
    state["admitted"] = _apply_caps(items, limits, already=state.get("admitted") or 0)
    state["items"].extend(items)
    _save(state)
    return [it for it in items if it["status"] == "pending"]



def _collect(state: dict, local_paths: list[str], drive_links: list[str],
             *, client, limits: Limits,
             metas: list[dict | None] | None = None) -> list[dict]:
    def progress(items: list[dict]) -> None:
        state["items"] = items
        _save(state)

    items = _plan(state, local_paths, drive_links, client=client, limits=limits,
                  metas=metas)
    state["admitted"] = _apply_caps(items, limits)
    progress(items)
    _fetch_drive(items, _run_dir(state["run_id"]), limits, progress)
    return items


def _plan(state: dict, local_paths: list[str], drive_links: list[str],
          *, client, limits: Limits,
          metas: list[dict | None] | None = None) -> list[dict]:
    items: list[dict] = []

    for n, p in enumerate(local_paths):
        path = Path(p)
        size = path.stat().st_size if path.exists() else None
        it = _item(path.name, str(path), "local", size, spooled=False)
        it["meta"] = (metas[n] if metas and n < len(metas) else None) or None
        items.append(it)

    if not drive_links:
        return items

    files = gdrive.resolve(drive_links, max_files=resolve_budget(limits))
    for f in files:
        ok, why = gdrive.is_uploadable(f)
        if not ok:
            items.append(_item(f.name, None, "gdrive", f.size,
                               status="skipped", error=why))
            continue
        meta = drive_meta(f)
        if known := _memo_lookup(state["account_id"], f.md5, client):
            it = _item(f.name, None, "gdrive", f.size, status="done")
            it.update(vault_id=known, deduped=True, drive_md5=f.md5, meta=meta)
            items.append(it)
            continue
        it = _item(f.name, None, "gdrive", f.size)
        it["meta"] = meta
        it.update(drive_id=f.id, drive_md5=f.md5, mime_type=f.mime_type,
                  drive_resource_key=f.resource_key)
        items.append(it)
    return items


def _fetch_drive(items: list[dict], run_dir: Path, limits: Limits,
                 progress: Callable[[list[dict]], None]) -> None:
    for it in items:
        if it["status"] != "pending" or it["source"] != "gdrive" or it.get("path"):
            continue
        try:
            guard_space(it["size"] or 0, limits, path=run_dir)
            f = gdrive.DriveFile(id=it["drive_id"], name=it["name"],
                                 mime_type=it.get("mime_type") or "",
                                 size=it["size"],
                                 resource_key=it.get("drive_resource_key"),
                                 md5=it.get("drive_md5"))
            dest = gdrive.download(
                f, run_dir,
                max_bytes=cap_for(it["name"], it.get("mime_type"), limits),
                min_free_bytes=limits.min_free_bytes)
            it.update(path=str(dest), spooled=True)
        except Exception as e:  # noqa: BLE001 — one bad file must not end the run
            it.update(status="failed", error=gdrive.redact(f"{type(e).__name__}: {e}"))
        progress(items)


def guard_space(incoming: int, limits: Limits | None = None, *,
                path: Path | None = None) -> None:
    limits = limits or Limits()
    target = Path(path or SPOOL_ROOT)
    target.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(target).free
    if free - incoming < limits.min_free_bytes:
        raise RuntimeError(
            f"not enough disk: {free / 1e9:.1f} GB free, this needs "
            f"~{incoming / 1e9:.1f} GB and "
            f"{limits.min_free_bytes / 1e9:.1f} GB must stay free")



def _carrier_hooks(state: dict, items: list[dict]):
    key = uuid.uuid4().hex

    def note_carrier_intent(marker: str) -> None:
        # A timeout, proxy error or SIGKILL mid-create: OF may have created the post anyway and we never learn its id; this intent record is what the sweep scans.
        intent = {"at": _now(), "marker": marker}
        for it in items:
            it.update(carrier_intent=intent, carrier_key=key, carrier_deleted=False)
        _save(state)

    def remember_carrier(post_id) -> None:
        for it in items:
            it["carrier_post_id"] = post_id
            it["carrier_deleted"] = False
        _save(state)

    def carrier_gone(post_id) -> None:
        for it in items:
            it["carrier_post_id"] = post_id
            it["carrier_deleted"] = True
        _save(state)

    return note_carrier_intent, remember_carrier, carrier_gone


def _fail(item: dict, e: BaseException) -> None:
    item.update(status="failed", error=f"{type(e).__name__}: {e}")


def _upload_one(state: dict, item: dict, client, limits: Limits) -> _Staged | None:
    path = item.get("path")
    if not path or not Path(path).exists():
        item.update(status="failed",
                    error=("file missing from spool" if item.get("spooled")
                           else "file no longer exists on disk"))
        return None

    try:
        if media_prep.can_shrink(item["name"], item.get("mime_type")):
            guard_space(Path(path).stat().st_size, limits,
                        path=_run_dir(state["run_id"]))
    except Exception as e:  # noqa: BLE001 — one file, not the whole run
        _fail(item, e)
        return None
    try:
        upload_path, prepared = media_prep.prepare(
            path, _run_dir(state["run_id"]),
            over_mb=limits.compress_over_mb, target_mb=limits.target_mb,
            mime=item.get("mime_type"))
    except Exception as e:  # noqa: BLE001 — one file, not the whole run
        log.exception("vault: preparing %s failed", item["name"])
        _fail(item, e)
        return None
    renamed = (Path(upload_path).name
               if prepared and str(upload_path) != str(path) else None)
    if prepared:
        item["compressed_from"] = item["size"]
        item["size"] = Path(upload_path).stat().st_size
        _save(state)

    final_size = Path(upload_path).stat().st_size
    if final_size > limits.max_bytes:
        item.update(status="skipped",
                    error=(f"{final_size / 1e6:.0f} MB is over the "
                           f"{limits.max_bytes / 1e6:.0f} MB per-file limit"
                           + (" even after preparation" if prepared else "")
                           + " — raise VAULT_UPLOAD_MAX_MB if that is not what "
                             "you meant"))
        if renamed:
            Path(upload_path).unlink(missing_ok=True)
        return None

    item["status"] = "uploading"
    _save(state)
    try:
        claim = client.upload_claim(str(upload_path))
    except Exception as e:  # noqa: BLE001 — one file, not the whole run
        log.exception("vault upload failed for %s", item["name"])
        _fail(item, e)
        claim = None
    if renamed:
        Path(upload_path).unlink(missing_ok=True)
    if claim is None:
        return None
    item["claim_retries"] = claim.retries
    if claim.media:
        return _Staged(item, claim, renamed)
    _settle(item, claim.vault_id, note=claim.note, hidden=claim.hidden,
            deduped=claim.vault_id is not None, renamed=renamed)
    _land(state, item)
    return None


def _settle(item: dict, vault_id, *, note: str | None = None,
            still_transcoding: bool = False, hidden: bool = False,
            deduped: bool = False, renamed: str | None = None) -> None:
    item.update(vault_id=vault_id, deduped=deduped, hidden=hidden,
                still_transcoding=still_transcoding)
    if hidden:
        # The bytes ARE on OF under an id the creator hid; hiding is one-way, so re-uploading can never restore it: not "done".
        item.update(status="skipped",
                    error="already in the vault but HIDDEN (removed there) — "
                          "OnlyFans dedupes on the bytes, so re-uploading "
                          "cannot bring it back")
    elif vault_id:
        item["status"] = "done"
    else:
        note = note or "no vault id"
        if renamed:
            note = f"{note} (uploaded as {renamed}, normalised from {item['name']})"
        item.update(status="failed", error=note)


def _land(state: dict, item: dict) -> None:
    if item["status"] != "done":
        return
    try:
        if item.get("drive_md5") and item.get("vault_id"):
            _memo_remember(state["account_id"], item["drive_md5"], item["vault_id"])
        if item.get("spooled") and item.get("path"):
            Path(item["path"]).unlink(missing_ok=True)
            item["path"] = None
    except Exception:  # noqa: BLE001
        log.exception("vault: housekeeping after %s landed failed", item.get("name"))


def _send(state: dict, staged: _Staged, client, gate) -> None:
    item, claim = staged.item, staged.claim
    try:
        res = client.materialize_via_message(
            [claim.media], int(state["fan_id"]), dedupe_key=claim.dedupe_key,
            size=claim.size, gate=gate)
    except Exception as e:
        log.exception("vault send failed for %s", item["name"])
        _fail(item, e)
        if isinstance(e, of_client.FanSendRefused):
            item["error"] = str(e)
            raise
        if isinstance(e, _MAYBE_WRITTEN):
            # Same lost race as a carrier's, but the write was a chat message: nothing will publish to the feed, so no carrier alarm.
            item.update(message_write_pending=True,
                        error="timed out waiting to send — the message to the "
                              "fan may still go out; check the chat before "
                              "re-importing this file")
        return
    item["message_id"] = res.get("message_id")
    _settle(item, res.get("vault_id"), note=res.get("note"),
            still_transcoding=bool(res.get("still_transcoding")),
            renamed=staged.renamed)
    _land(state, item)


def _carry(state: dict, batch: list[_Staged], client, gate) -> bool:
    items = [s.item for s in batch]
    intent, remember, gone = _carrier_hooks(state, items)
    try:
        res = client.materialize_to_vault(
            [s.claim.media for s in batch], on_carrier=remember,
            on_carrier_intent=intent, on_carrier_deleted=gone, gate=gate)
        placed = vault_carrier.attribute(
            client, res["media"], [(s.claim.dedupe_key, s.claim.size) for s in batch])
    except BaseException as e:
        log.exception("vault carrier for %d files failed", len(items))
        for it in items:
            _fail(it, e)
            if isinstance(e, _MAYBE_WRITTEN):
                # A carrier that loses the race still creates the post, so this intent cannot be scanned for: a scan now would find nothing and wrongly conclude it never existed.
                it["carrier_write_pending"] = True
        if not isinstance(e, Exception):
            raise
        return any(it.get("carrier_intent") for it in items)
    pid = res["carrier_post_id"]
    for s, got in zip(batch, placed, strict=True):
        if len(batch) == 1:
            note = "carrier ready but no media id surfaced before timeout"
        else:
            note = (f"carrier {pid} took this file but its vault id could not "
                    f"be told apart from the other {len(batch) - 1} on it — it "
                    f"may still be in the vault; re-importing it is safe, "
                    f"OnlyFans will recognise the bytes")
        _settle(s.item, got.vault_id, note=note,
                still_transcoding=got.transcoding, renamed=s.renamed)
    for it in items:
        _land(state, it)
    return True


def _gate(gate):
    return gate or (lambda thunk: thunk())


def _file_into_folder(state: dict, client, gate=None) -> None:
    by_list: dict[int, list] = {}
    for i in state["items"]:
        if not (i.get("vault_id") and i["status"] == "done"):
            continue
        lid = (i.get("meta") or {}).get("list_id") or state.get("list_id")
        if lid:
            by_list.setdefault(int(lid), []).append(i["vault_id"])
    if not by_list:
        return
    run = _gate(gate)
    filed = 0
    errors: list[str] = []
    for lid, ids in by_list.items():
        try:
            run(lambda lid=lid, ids=ids: client.add_media_to_vault_list(lid, ids))
            filed += len(ids)
        except Exception as e:
            # Never fatal and never a reason to re-upload: the media is already in the vault, just not in the picked folder.
            log.warning("vault batch %s: foldering into %s failed — %s",
                        state["run_id"], lid, e)
            errors.append(f"{len(ids)} into folder {lid}: {e}")
    state["filed_into_list"] = filed
    if errors:
        state["filing_error"] = ("could not file " + "; ".join(errors))


def _carriers(items: list) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for n, it in enumerate(items):
        if (it.get("carrier_intent") or it.get("carrier_post_id")
                or it.get("carrier_write_pending")):
            out.setdefault(it.get("carrier_key") or f"item-{n}", []).append(it)
    return out


def _rides_live(i: dict) -> bool:
    return bool(i.get("carrier_post_id") and not i.get("carrier_deleted"))


def _live_post(riders: list[dict]):
    return next((i["carrier_post_id"] for i in riders if _rides_live(i)), None)


def _delete_live_carriers(items: list, remove: Callable[[Any], Any]
                          ) -> tuple[int, int, int]:
    # A post OF says does not exist cannot publish, so a 404 counts as deleted.
    deleted = gone = failed = 0
    for riders in _carriers(items).values():
        pid = _live_post(riders)
        if pid is None:
            continue
        names = ", ".join(str(it.get("name")) for it in riders)
        try:
            remove(pid)
            deleted += 1
            log.warning("vault: deleted carrier %s (%s), left live by its run",
                        pid, names)
        except Exception as e:  # noqa: BLE001
            if not of_client.post_is_gone(e):
                failed += 1
                log.error("VAULT CARRIER LEFT BEHIND: post %s (%s) — %s",
                          pid, names, e)
                continue
            gone += 1
            log.info("vault: carrier %s (%s) was already gone", pid, names)
        for it in riders:
            it["carrier_deleted"] = True
    return deleted, gone, failed


def _cleanup_carriers(state: dict, client, gate=None) -> None:
    run = _gate(gate)
    _delete_live_carriers(
        state["items"], lambda pid: run(lambda: of_client.remove_carrier(client, pid)))


def _clear_spool(state: dict) -> None:
    rd = _run_dir(state["run_id"])
    if not rd.is_dir():
        return
    freed = 0
    for f in rd.iterdir():
        if f.name == "run.json":
            continue
        try:
            freed += f.stat().st_size
            f.unlink()
        except OSError as e:
            log.warning("vault batch: could not clear %s — %s", f, e)
    for it in state["items"]:
        if it.get("spooled"):
            it["path"] = None
    state["spool_cleared_bytes"] = freed



def _marker_text(post: dict) -> str | None:
    raw = [v for v in (post.get("rawText"), post.get("text")) if isinstance(v, str)]
    if not raw:
        return None
    return html.unescape(re.sub(r"<[^>]+>", "", " ".join(raw)))


def _known_carriers(account_id: str) -> set[str]:
    aid, out = str(account_id), set()
    for d in _dirs():
        try:
            raw = json.loads((d / "run.json").read_text())
        except (OSError, ValueError):
            continue
        if str(raw.get("account_id")) != aid:
            continue
        for i in raw.get("items") or []:
            if i.get("carrier_post_id"):
                out.add(str(i["carrier_post_id"]))
    return out


def _sweep_scheduled(client, account_id: str,
                     recheck: Callable[[], set | None]) -> tuple[int, int, bool]:
    known = recheck()
    if known is None:
        log.info("vault sweep: account %s started importing — leaving its "
                 "scheduled posts alone", account_id)
        return 0, 0, False
    try:
        rows, why = of_paging.schedules_in_window(client, of_client.CARRIER_DAYS)
    except Exception as e:  # noqa: BLE001 — a listing failure is not a run failure
        log.error("vault sweep: could NOT list scheduled posts for account "
                  "%s — an unrecorded carrier may be live: %s", account_id, e)
        return 0, 1, False
    if why:
        log.error("vault sweep: scheduled-post listing for account %s is "
                  "INCOMPLETE (%s) — only the carriers it did list are retired, "
                  "no intent is cleared this run", account_id, why)

    deleted = failed = unevaluable = 0
    for row in rows:
        kind = row.get("type") if isinstance(row, dict) else None
        if kind == "chat":
            continue
        # A row we cannot evaluate (no entity / post id / unknown type) is never deleted, and the scan is not complete (it may be the carrier).
        post = row.get("entity") if isinstance(row, dict) else None
        if not isinstance(post, dict):
            unevaluable += 1
            log.warning("vault sweep: account %s scheduled row %s has no entity "
                        "— skipped, not deleted", account_id,
                        row.get("id") if isinstance(row, dict) else row)
            continue
        if kind != "post":
            unevaluable += 1
            log.warning("vault sweep: account %s scheduled row %s has type "
                        "%r — skipped, not deleted", account_id,
                        row.get("id"), kind)
            continue
        pid = post.get("id")
        if pid is None:
            unevaluable += 1
            log.warning("vault sweep: account %s scheduled row %s has no post id "
                        "— skipped, not deleted", account_id, row.get("id"))
            continue
        if str(pid) in known:
            continue
        text = _marker_text(post)
        if text is None:
            unevaluable += 1
            log.warning("vault sweep: account %s scheduled post %s has no text "
                        "— skipped, not deleted", account_id, pid)
            continue
        if of_client.VAULT_MARKER not in text:
            continue
        fresh = recheck()
        if fresh is None:
            log.info("vault sweep: account %s started importing mid-scan — "
                     "abandoning it, nothing retired", account_id)
            return deleted, failed, False
        known = fresh
        if str(pid) in known:
            continue
        try:
            of_client.remove_carrier(client, pid)
            deleted += 1
            log.warning("vault sweep: deleted an UNRECORDED carrier post %s — "
                        "its create response must have been lost", pid)
        except Exception as e:  # noqa: BLE001
            failed += 1
            log.error("vault sweep: unrecorded carrier %s STILL LIVE — %s", pid, e)
    if why:
        failed += 1
    return deleted, failed, failed == 0 and not unevaluable


def sweep(client_for: Callable[[str], Any], *, keep_hours: int = 48) -> dict:
    import cell_hold
    cell_hold.refuse_writes()
    fixed, failed, removed = 0, 0, 0
    cutoff = time.time() - keep_hours * 3600
    scan: set[str] = set()
    dead: list[tuple[Path, dict, bool]] = []
    live_cache: dict[str, bool] = {}

    for d in sorted(STAGE_ROOT.glob("vault-in-*")) if STAGE_ROOT.is_dir() else []:
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue

    for d in _dirs():
        try:
            raw = json.loads((d / "run.json").read_text())
        except (OSError, ValueError):
            try:
                stale = d.stat().st_mtime < cutoff
            except OSError:
                stale = False
            if stale:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
            continue
        state = _reconcile(raw, live_cache)
        aid = str(state.get("account_id"))
        items = state.get("items") or []
        if _account_is_live(aid, live_cache):
            continue
        dead.append((d, state, state.get("status") != raw.get("status")))
        if any(_intent_unresolved(i) for i in items):
            scan.add(aid)

    scanned: set[str] = set()
    for aid in sorted(scan):
        def _recheck(aid=aid) -> set | None:
            return None if _account_is_live(aid) else _known_carriers(aid)

        if _recheck() is None:
            continue
        try:
            client = client_for(aid)
        except Exception as e:  # noqa: BLE001
            log.error("vault sweep: no client for account %s — %s", aid, e)
            failed += 1
            continue
        got, lost, complete = _sweep_scheduled(client, aid, _recheck)
        fixed += got
        failed += lost
        if complete:
            scanned.add(aid)

    now_cache: dict[str, bool] = {}
    for d, state, changed in dead:
        aid = str(state.get("account_id"))
        if _account_is_live(aid, now_cache):
            continue
        items = state.get("items") or []
        live = sum(1 for riders in _carriers(items).values() if _live_post(riders))
        if live:
            try:
                client = client_for(aid)
            except Exception as e:  # noqa: BLE001
                failed += live
                log.error("vault sweep: no client for account %s — %s", aid, e)
            else:
                got, gone, lost = _delete_live_carriers(
                    items, lambda pid: of_client.remove_carrier(client, pid))
                fixed += got
                failed += lost
                changed = changed or bool(got or gone)
        # An intent is only retired by a scan that actually completed; a failed, unpaged or abandoned listing leaves it.
        if aid in scanned:
            for it in items:
                if _intent_unresolved(it):
                    it["carrier_scan_clear"] = True
                    changed = True
        if changed:
            _save(state)

        # Retention stats the STATE FILE, not the directory: a directory mtime is never older than the last write, so nothing was ever removed.
        unresolved = any(
            _rides_live(i) or _intent_unresolved(i)
            for i in items)
        try:
            stale = (d / "run.json").stat().st_mtime < cutoff
        except OSError:
            stale = False
        if state.get("finished_at") and stale and not unresolved:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1

    if fixed or failed or removed:
        log.info("vault sweep: %d carriers deleted, %d still live, %d dirs removed",
                 fixed, failed, removed)
    return {"carriers_deleted": fixed, "carriers_failed": failed,
            "dirs_removed": removed}
