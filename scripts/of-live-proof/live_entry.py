"""live_entry: the live entry, the preflight and `serve`'s wait (ticket 09; prove.py calls it).

Live entry (stories 2, 43): `--of live` needs an explicit `--session-dir`; no default session is ever read, and the
refusal (`--session-dir is required`) comes before anything starts. The dir is copied into the run's temp dir as the
Proof Creator's account dir (relay_guarded.py's redirected `sessions/accounts/80000112`), before the Relay starts; its
path and contents are never printed, and the copy goes with the temp dir at teardown: prove.py `_prove`'s teardown
ignores SIGINT and SIGTERM and `Stack.close` deletes the temp dir in a `finally`, so only SIGKILL (or the
interpreter dying) leaves it. The Creator's `accounts` row and owner link are made the way
scripts/demo-shots/seed.py makes them, for a throwaway owner registered through the API.

Preflight (driver step 1, story 1), before any proof, both modes; fake mode expects FakeOF's Creator:
  - the stack is on loopback, the Relay holds exactly one Creator and it is the expected one, the Relay's uncached
    identity read (`/__proof/session`, the undecorated /users/me) names it and answers alive, and the run lock is held
    by this run: `preflight` here;
  - no earlier run's Undo log has a `pending` row: prove.py `earlier_pending`, under the lock before the stack starts;
  - the capture browser's own identity read names it: capture.py `start` (of_browser `identity_problem`), whenever
    it opens (on demand only, for `capture` or a proof with capture-browser steps; D27), before any step.
`--fault wrong-creator` (fake only) makes the run expect a Creator other than the one FakeOF serves, so the
wrong-Creator refusal is proven without a live stack; `main` resolves it once into the expected Creator, and FakeOF
never sees it as a fault.

Live proofs fail closed (`live_refusal`): besides proof_core's `not_started` (mocked, stream start, irreversible,
Proof fan unset, mocked with no trigger), a non-Mocked proof with no trigger is refused (the run fails: a forgotten
trigger never passes as parked). Ticket 11 built the live OnlyFans-side reader (prove.py `Stack.of_get`, a signed GET
through the run's Relay), so a proof that writes or reads OnlyFans starts live, unless its steps are capture-browser
steps (`capture`, or a `fetch` / `hand-off` trigger step): those run only on the fake-mode drill page, and live
capture steps (clicks on onlyfans.com) are not written, so it is refused before the capture browser opens.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from of_browser import probe_verdict
from proof_core import not_started, step_family

PROOF_CREATOR = "80000112"   # the owner's sandbox Creator (D25), the only one a live run touches
WRONG_CREATOR = "wrong-creator"
OWNER = "ofmproof"


def session_dir_refusal(of: str, session_dir) -> str | None:
    """The CLI's check before anything starts. Only the dir's listing is looked at, never a file's contents."""
    if of != "live":
        return "--session-dir is live mode only (fake mode bootstraps from FakeOF)" if session_dir else None
    if not session_dir:
        return "--of live: --session-dir is required (no default session is ever read)"
    d = Path(session_dir)
    if not d.is_dir() or not (d / "latest.json").is_file():
        return "--session-dir is not an account session dir (no latest.json in it)"
    return None


def expected_creator(of: str, fault: str | None) -> str:
    """The Creator the run must find: 80000112 live; FakeOF's in fake mode, or under `--fault wrong-creator` the id one
    past it (every FakeOF seed serves the same Creator), which the stack then does not hold."""
    if of == "live":
        return PROOF_CREATOR
    from fake_layer import creator_id
    return str(int(creator_id(1)) + 1) if fault == WRONG_CREATOR else creator_id(1)


LIVE_BROWSER_STEPS = ("refused: capture-browser steps run only on the fake-mode drill page; live capture steps "
                      "(clicks on onlyfans.com) are not written yet")
NO_TRIGGER = "refused: no trigger (only a Mocked proof may have none)"


def live_refusal(proof, of: str, proof_fan, capture=None) -> tuple[str, str] | None:
    """Why this run never starts `proof`: ("parked", reason) from `not_started` (stories 9, 13, 28, 56, every mode),
    ("refused", NO_TRIGGER) for a non-Mocked proof with no trigger (every mode), or ("refused", LIVE_BROWSER_STEPS)
    under --of live for a proof that writes or reads OnlyFans and would play capture-browser steps (`capture`, or a
    browser trigger step), so the capture browser never signs in for a step that cannot run. None: it starts."""
    why = not_started(proof, of, proof_fan)
    if why:
        return "parked", why
    if not proof.trigger:
        return "refused", NO_TRIGGER
    if of == "live" and (proof.arm or proof.of_read is not None) \
            and (capture or any(step_family(s) == "browser" for s in proof.trigger)):
        return "refused", LIVE_BROWSER_STEPS
    return None


def startable(proofs, pending_ids, of: str, proof_fan, rep: dict, capture=None) -> list:
    """The proofs this run may start, before anything opens (the capture browser included): a PENDING id parks (a Phase
    lists it, its ticket adds it) and each `live_refusal` lands in rep's `parked` or `refused` with its reason.
    `capture`: prove.py's (None, "send", "abort")."""
    for i in pending_ids:
        rep["parked"].append({"proof": i, "reason": "no proof definition yet: Live proof pending"})
        print(f"ofm-live-proof: {i}: parked (no proof definition yet: Live proof pending)", flush=True)
    out = []
    for p in proofs:
        why = live_refusal(p, of, proof_fan, capture)
        if why:
            rep[why[0]].append({"proof": p.id, "reason": why[1]})
            print(f"ofm-live-proof: {p.id}: {why[1]}", flush=True)
        else:
            out.append(p)
    return out


def copy_session(src, tmp: Path, creator: str = PROOF_CREATOR) -> Path:
    """The session dir copied into the run's temp dir as `sessions/accounts/<creator>` (symlinks copied as files).
    A `meta.json` is written only when the copy has none (seed.py's fields)."""
    dst = tmp / "sessions" / "accounts" / creator
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=False)
    if not (dst / "meta.json").exists():
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        (dst / "meta.json").write_text(json.dumps({
            "id": creator, "nickname": "ofm-proof", "color": None, "incogniton_profile_id": None,
            "platform": "onlyfans", "name": "ofm-proof", "created_at": now, "last_used_at": now}))
    (tmp / "sessions" / "active.json").write_text(json.dumps({"active_account_id": creator}))
    return dst


def register_owner(request, relay: str) -> tuple[str, str]:
    """The throwaway owner, through the Relay's API: (user_id, password). The password is the loopback stack's own,
    gone with the temp DB."""
    password = "ofm-proof-" + os.urandom(6).hex()
    r = request.post(f"{relay}/auth/register", data={"username": OWNER, "password": password})
    if not r.ok:
        raise RuntimeError(f"register failed: {r.status} {r.text()[:300]}")
    return str(r.json().get("user_id") or ""), password


def link_account(db: Path, user_id: str, creator: str = PROOF_CREATOR) -> None:
    """The Creator's `accounts` row and owner link, as scripts/demo-shots/seed.py `_accounts` writes them (the Relay
    may already have mirrored the copied dir into `accounts`: kept as it is)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    con = sqlite3.connect(db, timeout=30)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        with con:
            con.execute("INSERT OR IGNORE INTO accounts(id, nickname, color, is_active_default, created_at, "
                        "last_used_at) VALUES (?,?,?,?,?,?)", (creator, "ofm-proof", None, 1, now, now))
            con.execute("INSERT OR IGNORE INTO user_accounts(user_id, account_id, created_at) VALUES (?,?,?)",
                        (user_id, creator, now))
    finally:
        con.close()


def preflight_problems(urls, account_ids, expected: str, identity: tuple, lock_held: bool) -> list:
    """Each reason the run is refused before any proof ([] = go). `identity`: (status, body) of the Relay's uncached
    /users/me; a dead session (OnlyFans's "Wrong user") is named as such."""
    out = [f"not loopback: {u}" for u in urls if urlsplit(u).hostname != "127.0.0.1"]
    if list(account_ids) != [expected]:
        out.append(f"expected one Creator {expected}, the Relay has {list(account_ids)}")
    verdict, why = probe_verdict(*identity, expected)
    if verdict == "dead":
        out.append(f"session dead: {why}")
    elif verdict != "ok":
        out.append(f"Relay identity read (/__proof/session): {why}")
    if not lock_held:
        out.append(f"the run lock for Creator {expected} is not held by this run")
    return out


def preflight(request, relay: str, urls, expected: str, lock_held: bool) -> list:
    """`preflight_problems` over the running stack (`request`: the owner's Playwright request context). The identity
    read is for the stack's single Creator, so a stack holding another one is named by OnlyFans's own answer."""
    r = request.get(f"{relay}/admin/accounts")
    ids = [str(a.get("id")) for a in (r.json().get("accounts") or [])] if r.ok else [f"<accounts read {r.status}>"]
    r = request.get(f"{relay}/__proof/session", headers={"X-Account-Id": ids[0] if len(ids) == 1 else expected})
    try:
        body = r.json()
    except Exception:  # noqa: BLE001  (not JSON: named by its text)
        body = r.text()[:200]
    return preflight_problems(urls, ids, expected, (r.status, body), lock_held)


def serve_wait(app: str, relay: str, login: tuple, sleep=time.sleep) -> None:
    """`serve` (story 37): print the loopback URLs and the throwaway owner's login, then wait until SIGINT or SIGTERM
    (prove.py `main` turns SIGTERM into KeyboardInterrupt); the teardown after it ignores both."""
    print(f"ofm-live-proof: serve: app {app}", flush=True)
    print(f"ofm-live-proof: serve: relay {relay}", flush=True)
    print(f"ofm-live-proof: serve: sign in as {login[0]} / {login[1]} (this stack's throwaway owner)", flush=True)
    print("ofm-live-proof: serve: up; Ctrl-C (SIGINT) or SIGTERM tears it down", flush=True)
    try:
        while True:
            sleep(3600)
    except KeyboardInterrupt:
        print("ofm-live-proof: serve: interrupted; tearing down", flush=True)
