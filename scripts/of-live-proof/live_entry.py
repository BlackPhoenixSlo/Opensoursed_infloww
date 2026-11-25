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

PROOF_CREATOR = "80000112"
WRONG_CREATOR = "wrong-creator"
OWNER = "ofmproof"


def session_dir_refusal(of: str, session_dir) -> str | None:
    if of != "live":
        return "--session-dir is live mode only (fake mode bootstraps from FakeOF)" if session_dir else None
    if not session_dir:
        return "--of live: --session-dir is required (no default session is ever read)"
    d = Path(session_dir)
    if not d.is_dir() or not (d / "latest.json").is_file():
        return "--session-dir is not an account session dir (no latest.json in it)"
    return None


def expected_creator(of: str, fault: str | None) -> str:
    if of == "live":
        return PROOF_CREATOR
    from fake_layer import creator_id
    return str(int(creator_id(1)) + 1) if fault == WRONG_CREATOR else creator_id(1)


LIVE_BROWSER_STEPS = ("refused: capture-browser steps run only on the fake-mode drill page; live capture steps "
                      "(clicks on onlyfans.com) are not written yet")
NO_TRIGGER = "refused: no trigger (only a Mocked proof may have none)"


def live_refusal(proof, of: str, proof_fan, capture=None) -> tuple[str, str] | None:
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
    password = "ofm-proof-" + os.urandom(6).hex()
    r = request.post(f"{relay}/auth/register", data={"username": OWNER, "password": password})
    if not r.ok:
        raise RuntimeError(f"register failed: {r.status} {r.text()[:300]}")
    return str(r.json().get("user_id") or ""), password


def link_account(db: Path, user_id: str, creator: str = PROOF_CREATOR) -> None:
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
    r = request.get(f"{relay}/admin/accounts")
    ids = [str(a.get("id")) for a in (r.json().get("accounts") or [])] if r.ok else [f"<accounts read {r.status}>"]
    r = request.get(f"{relay}/__proof/session", headers={"X-Account-Id": ids[0] if len(ids) == 1 else expected})
    try:
        body = r.json()
    except Exception:  # noqa: BLE001  (not JSON: named by its text)
        body = r.text()[:200]
    return preflight_problems(urls, ids, expected, (r.status, body), lock_held)


def serve_wait(app: str, relay: str, login: tuple, sleep=time.sleep) -> None:
    print(f"ofm-live-proof: serve: app {app}", flush=True)
    print(f"ofm-live-proof: serve: relay {relay}", flush=True)
    print(f"ofm-live-proof: serve: sign in as {login[0]} / {login[1]} (this stack's throwaway owner)", flush=True)
    print("ofm-live-proof: serve: up; Ctrl-C (SIGINT) or SIGTERM tears it down", flush=True)
    try:
        while True:
            sleep(3600)
    except KeyboardInterrupt:
        print("ofm-live-proof: serve: interrupted; tearing down", flush=True)
