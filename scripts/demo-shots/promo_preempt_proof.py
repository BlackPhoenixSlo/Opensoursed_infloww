#!/usr/bin/env python3
"""Keep running proof (tickets 16 + 26): each scenario boots promo_proof_relay.py (running
supervisor, temp DB, loopback only) against promo_fake_of.py and drives the product through
its own routes (PATCH/POST /admin/promotions) and OF toast frames. Expectations (EXPECT) are
written before any run; a disagreement is a FINDING, never an edited expectation.

"seeded" = time travel: every timestamp of the Creator (DB rows + the fake's promos) moves
back by N seconds (`shift`), standing in for N seconds passing. The toast gate's in-memory
monotonic read time cannot move: scenarios that need it wait in real time.

  promo_preempt_proof.py --slice A|B [--only NAME[,NAME]] [--relay-root DIR] --out DIR
writes DIR/counts.json (one entry per scenario) and DIR/<scenario>/{dump.json,relay*.log}.
  promo_preempt_proof.py --serve [--port 8797]   seeded Kept campaign for screenshots
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PY = ROOT / "venv" / "bin" / "python"
sys.path.insert(0, str(HERE))
from promo_fake_of import FMT, FakeOF, utcnow  # noqa: E402

P, ME = "/api2/v2/promotions", "/api2/v2/users/me"
DBFMT = "%Y-%m-%d %H:%M:%S.%f"
HOST = "proof-a"
AID = "1000001"
MSG = "Keep running proof"
PASSWORD = "proof-throwaway-pass-2026"


def E(slice_, posts, reason, **want):
    return {"slice": slice_, "posts": posts, "reason": reason, "want": want}


# ── Expectations: written before running; never edited to make a run pass ───────────
EXPECT = {
    # Slice A
    "after-end": E("A", 1, "P0 ends: one After-end re-create; the next backstop finds P1 live",
                   keep_running=True, sources=["auto_ended"]),
    "mn02-unparsed": E("A", 1, "200 with a non-JSON body = unknown; never listed, so 900 s on it is lost: "
                       "Keep running off create_unknown", keep_running=False, keep_warning="create_unknown",
                       states=["lost"]),
    "mn02-never-live": E("A", 3, "each create answers an id OF never lists: the Zero-claim breaker trips "
                         "after 3", keep_running=False, keep_warning="breaker"),
    "mn03-429": E("A", 2, "a 429 backs off; the second in a row turns Keep running off",
                  keep_running=False, keep_warning="rate_limited"),
    "mn03-403-once": E("A", 2, "one 403 backs off only; the next create lands", keep_running=True),
    "mn05": E("A", 1, "200 without an id = unknown; the next read adopts the listed promo",
              keep_running=True, states=["created"]),
    "mn06-crash": E("A", 1, "relay SIGKILLed mid-POST: the restarted relay never re-sends, a read adopts it",
                    keep_running=True, states=["created"]),
    "mn06-slow": E("A", 1, "answer after the 30 s client timeout = unknown; a read adopts it",
                   keep_running=True, states=["created"]),
    "mn07-two-relays": E("A", 1, "two relays on one DB woken together: one create (open-row index)",
                         keep_running=True),
    "mn07-copy-unset": E("A", 0, "ticked where PROMO_CREATE_HOST_ID is unset: stamped '', fenced before "
                         "any OF read", get_promotions=0),
    "mn09-trial": E("A", 3, "Free trial, Re-create limit 3: three re-creates, then off limit_reached",
                    keep_running=False, keep_warning="limit_reached"),
    "mn10-untick": E("A", 0, "untick between the run's read and its POST: reserve refuses",
                     keep_running=False, refused="campaign_changed"),
    "mn10-manual-after-read": E("A", 1, "manual create after the run's read: the run refuses newer_create; "
                                "the one POST is the manual one", refused="newer_create", sources=["manual"]),
    "mn12-takeover": E("A", 1, "create with Keep running + expect_taken_from=C1 moves the tick (notice); a "
                       "stale expectation 409s before any POST", second_status=409, taken_notice=True),
    "mn13": E("A", 1, "preempt off, claims 99: one near_cap re-check (one slot), it re-creates past the cap",
              recheck_jobs=2, keep_running=True),      # near_cap, then the new promo's first read
    "mn14": E("A", 1, "OF flips finished on the last claim; its toast lands under the poke floor: deferred, "
              "fires after the floor (real time)", keep_running=True),
    "fence-unset": E("A", 0, "relay rebooted with PROMO_CREATE_HOST_ID unset: boot notice; run fenced "
                     "before any read", notices_fence_min=1, get_after_unset=0),
    "toast-100": E("A", 1, "100 toasts 1.5 s apart: the gate pokes near the trigger; one re-create"),
    # Slice B
    "fill-90": E("B", 1, "cap 100, Trusted count 90: one Fill while old claims < cap; OF ends the old at "
                 "the create", sources=["auto_fill"], claims_lt_cap=True, gap_s=0),
    "fill-twice": E("B", 2, "the promo Keep running made itself: its first read (~10 s after the create) "
                    "sees 0 claims, so 90 more claims Fill it again", sources=["auto_fill", "auto_fill"],
                    gap_s=0),
    "timed": E("B", 1, "finishedAt 200 s out, skew 0 (seeded): the Timed re-check ~115 s before the end "
               "creates once", sources=["auto_timed"]),
    "burst-past-cap": E("B", 1, "100 claims inside the poke floor: Fill window passed; After-end on the "
                        "Trusted inferred cap, once", sources=["auto_ended"], claims_ge_cap=True),
    "mn01-lag": E("B", 0, "a lower count untrusts for good: 92 claims make no Fill",
                  wait_reason="count_untrusted"),
    "mn01-nonzero-start": E("B", 1, "P1 starts at 2 claims: untrusted, no second Fill",
                            wait_reason="count_untrusted"),
    "mn04-failed-preempt": E("B", 2, "Fill answered 429 while OF ends the old: recovery re-check, After-end",
                             keep_running=True, preempt=True, sources=["auto_fill", "auto_ended"]),
    "mn04-no-slot": E("B", 1, "2 automatic creates this hour (seeded): no recovery slot, no Fill at 90; "
                      "After-end at the cap", wait_mid="no_recovery_slot", last_source="auto_ended"),
    "mn08-guessed-end": E("B", 1, "only our expires_at guess: expiry re-checks, never Timed; After-end once "
                          "OF ends it", sources=["auto_ended"]),
    "mn08-skew": E("B", 1, "skew 45 s (seeded) > 30: waiting line 'clock', no Timed; After-end after the end",
                   wait_mid="clock", sources=["auto_ended"]),
    "switch-off": E("B", 1, "PROMO_PREEMPT_ENABLED=0: no Fill at 90; After-end at the cap",
                    posts_mid=0, claims_ge_cap=True, sources=["auto_ended"]),
    "toast-far": E("B", 0, "30 toasts far from the trigger: no poke after the tick's read, no create"),
    "second-live": E("B", 1, "OF keeps the old promo live after the Fill: next run logs promo_keep_second_live, "
                     "no POST", sources=["auto_fill"], log="promo_keep_second_live", gap_s=0),
    "preempt-400": E("B", 2, "Fill answered 400: preempt unticked, Keep running on; After-end after the end",
                     keep_running=True, preempt=False, sources=["auto_fill", "auto_ended"]),
}

_LIVE: list = []    # every relay started, for cleanup


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _now() -> datetime:
    """Naive UTC, as the DB stores it."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ts(dt: datetime) -> str:
    return dt.strftime(DBFMT)


def _parse_db(v: str) -> datetime:
    return datetime.fromisoformat(v)


class Relay:
    def __init__(self, s: "Scenario", env: dict, tag: str):
        self.s, self.env, self.tag = s, env, tag
        self.log = s.dir / f"{tag}.log"
        self.p = None

    def start(self) -> "Relay":
        self.port = self.s.port or _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TMPDIR") if k in os.environ}
        env.update({
            "DATABASE_URL": f"sqlite+aiosqlite:///{self.s.tmp}/relay.db",
            "CHATTERLY_DB_URL": f"sqlite:///{self.s.tmp}/relay.db",
            "CHATTERLY_TEST_MODE": "1", "SHARE_TOKEN": "",
            "SESSION_SECRET": "proof-session-secret-0123456789abcdef",
            "CHATTER_SESSION_SECRET": "proof-chatter-secret-0123456789abcdef",
            "ADMIN_PASSWORD": "proof-admin-throwaway",
            "DEEPSEEK_API_KEY": "fake", "DEEPINFRA_API_KEY": "fake", "GOOGLE_DRIVE_API_KEY": "fake",
            "DEMO_SHOTS_ROOT": str(self.s.root), "DEMO_SHOTS_TMP": str(self.s.tmp),
            "DEMO_SHOTS_RELAY_PORT": str(self.port), "OF_API_ORIGIN": self.s.fake.origin,
            "PROMO_CREATE_HOST_ID": HOST, "UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN": "5",
        })
        for k, v in self.env.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        out = open(self.log, "a")
        self.p = subprocess.Popen(["nice", "-n", "10", str(PY), str(HERE / "promo_proof_relay.py")],
                                  cwd=str(self.s.root), env=env, stdout=out, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        _LIVE.append(self)
        end = time.time() + 120
        while time.time() < end:
            if self.p.poll() is not None:
                raise RuntimeError(f"relay {self.tag} exited {self.p.returncode}; see {self.log}")
            try:
                urllib.request.urlopen(self.base + "/livez", timeout=2).read()
                return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError(f"relay {self.tag} not ready; see {self.log}")

    def alive(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def kill(self, sig=signal.SIGTERM, wait=15.0) -> None:
        if not self.alive():
            return
        try:
            os.killpg(self.p.pid, sig)
            self.p.wait(wait)
        except subprocess.TimeoutExpired:
            os.killpg(self.p.pid, signal.SIGKILL)
            self.p.wait(10)
        except ProcessLookupError:
            pass

    def hook(self, method: str, path: str, body=None) -> dict:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"{}")


class Scenario:
    def __init__(self, name: str, out: Path, root: Path):
        self.name, self.root = name, root
        self.dir = out / name
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.tmp = Path(tempfile.mkdtemp(prefix=f"promo-proof-{name}-", dir="/tmp"))
        self.fake = FakeOF()
        self.relays: list[Relay] = []
        self.jar = http.cookiejar.CookieJar()
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.extra: dict = {}
        self.notes: list[str] = []
        self.cid: int | None = None
        self.port = 0

    # ── plumbing ──────────────────────────────────────────────
    def relay(self, env: dict | None = None, tag: str = "relay") -> Relay:
        r = Relay(self, env or {}, tag).start()
        self.relays.append(r)
        return r

    @property
    def main(self) -> Relay:
        return next(r for r in reversed(self.relays) if r.alive())

    def api(self, method: str, path: str, body=None, relay: Relay | None = None) -> tuple[int, object]:
        r = relay or self.main
        req = urllib.request.Request(r.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            resp = self.http.open(req, timeout=120)
            st, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            st, raw = e.code, e.read()
        try:
            return st, json.loads(raw or b"null")
        except ValueError:
            return st, raw.decode(errors="replace")

    def db(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.tmp / "relay.db", timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def cols(self, con, table: str) -> dict:
        return {r["name"]: r for r in con.execute(f"PRAGMA table_info({table})")}

    def insert(self, table: str, row: dict) -> int:
        """Insert the columns this schema has; NOT NULL ones left out get a neutral value."""
        con = self.db()
        with con:
            cols = self.cols(con, table)
            vals = {k: v for k, v in row.items() if k in cols}
            for k, c in cols.items():
                if k not in vals and c["notnull"] and not c["pk"] and c["dflt_value"] is None:
                    t = (c["type"] or "").upper()
                    vals[k] = _ts(_now()) if "DATE" in t else (
                        0 if any(x in t for x in ("INT", "BOOL", "NUM")) else "")
            cur = con.execute(f"INSERT INTO {table}({','.join(vals)}) VALUES ({','.join('?' * len(vals))})",
                              list(vals.values()))
            rid = cur.lastrowid
        con.close()
        return rid

    # ── world ─────────────────────────────────────────────────
    def start(self, env: dict | None = None) -> None:
        self.relay(env)
        st, d = self.api("POST", "/auth/register", {"username": "proof-owner", "password": PASSWORD})
        if st != 200:
            raise RuntimeError(f"register: {st} {d}")
        self.user_id = d["user_id"]
        now = _now()
        a = self.tmp / "sessions" / "accounts" / AID
        a.mkdir(parents=True, exist_ok=True)
        (a / "meta.json").write_text(json.dumps({
            "id": AID, "nickname": "Proof", "color": "#7c3aed", "incogniton_profile_id": None,
            "platform": "onlyfans", "name": "Proof Creator", "created_at": now.isoformat() + "Z",
            "last_used_at": now.isoformat() + "Z"}))
        bases = [10007 + 131 * k for k in range(32)]
        rules = {"static_param": "slopStaticParam2026", "start": "41999", "end": "6a1b2c3d",
                 "checksum_indexes": [n % 40 for n in bases], "checksum_constant": 2026}
        (a / "session_wire.json").write_text(json.dumps({
            "headers": {"user_id": AID, "x_bc": "%040x" % 0xC0FFEE, "x_of_rev": "proof-of-rev-202611190000",
                        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"},
            "signing": {"rules": rules, "signed_ok_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "cookies": [{"name": "auth_id", "value": AID, "domain": ".onlyfans.com", "path": "/"},
                        {"name": "sess", "value": "%032x" % 0xBADC0DE, "domain": ".onlyfans.com", "path": "/"}]}))
        (a / "latest.json").write_text(json.dumps({"session": "session_wire.json", "ts": now.isoformat() + "Z"}))
        (self.tmp / "sessions" / "active.json").write_text(json.dumps({"active_account_id": AID}))
        self.insert("accounts", {"id": AID, "nickname": "Proof", "color": "#7c3aed", "is_active_default": 1,
                                 "created_at": _ts(now - timedelta(days=90)), "last_used_at": _ts(now)})
        self.insert("user_accounts", {"user_id": self.user_id, "account_id": AID,
                                      "created_at": _ts(now - timedelta(days=90))})

    def campaign(self, of_id: int, *, discount=50, cap=100, days=30, name="Kept promo", **kw) -> int:
        row = {"account_id": AID, "of_promo_id": of_id, "name": name, "discount_percent": discount,
               "price_cents": 0, "subscribe_counts": cap, "subscribe_days": days, "message": MSG,
               "promo_type": "all", "status": "active", "subscriber_count": 0, "auto_reactivate": 0,
               "reactivate_count": 0, "created_at": _ts(_now() - timedelta(hours=1)), **kw}
        self.cid = self.insert("promo_campaigns", row)
        return self.cid

    def tick(self, cid: int, settle=True, **body) -> dict:
        st, d = self.api("PATCH", f"/admin/promotions/{cid}", {"auto_reactivate": True, **body})
        if st != 200:
            raise RuntimeError(f"tick: {st} {d}")
        if settle:
            self.settle()
        return d

    def wake(self) -> None:
        for r in self.relays:
            if r.alive():
                r.hook("POST", "/__proof/wake")

    def busy(self) -> bool:
        for r in self.relays:
            if r.alive():
                i = r.hook("GET", "/__proof/idle")
                if i["inflight"] or i["received"] != i["processed"]:
                    return True
        now = _now()
        con = self.db()
        rows = con.execute("SELECT status, run_at FROM scheduled_jobs WHERE status IN ('pending','running') "
                           "AND kind='promo_reactivate'").fetchall()
        con.close()
        return any(r["status"] == "running" or _parse_db(r["run_at"]) <= now for r in rows)

    def settle(self, timeout=120.0) -> None:
        self.wake()
        time.sleep(0.4)
        calm, end, n = 0, time.time() + timeout, 0
        while time.time() < end:
            calm = 0 if self.busy() else calm + 1
            if calm >= 4:
                return
            n += 1
            if n % 10 == 0:
                self.wake()
            time.sleep(0.4)
        self.notes.append(f"settle timeout {timeout}s")

    def wait_for(self, cond, timeout: float) -> float | None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if cond():
                return round(time.time() - t0, 1)
            time.sleep(0.5)
        return None

    SHIFT = {"scheduled_jobs": ("created_at", "run_at"),
             "automation_runs": ("started_at", "completed_at"),
             "promo_create_reservations": ("created_at", "sent_at", "settled_at", "not_before", "listed_at"),
             "promo_campaigns": ("created_at", "last_reactivated_at", "keep_ticked_at", "expires_at",
                                 "keep_warning_at"),
             "promo_keep_state": ("read_at", "recheck_at")}

    def shift(self, secs: float) -> None:
        """Seeded time travel: the Creator's DB timestamps and the fake's promos move `secs` back."""
        self.settle()
        d = timedelta(seconds=secs)
        con = self.db()
        with con:
            for table, want in self.SHIFT.items():
                cols = self.cols(con, table)
                if not cols:
                    continue
                key = "account_id" if "account_id" in cols else None
                pk = "rowid" if table == "promo_keep_state" else "id"
                for c in (c for c in want if c in cols):
                    rows = con.execute(f"SELECT {pk} AS k, {c} AS v FROM {table} WHERE {c} IS NOT NULL"
                                       + (" AND account_id=?" if key else ""), (AID,) if key else ()).fetchall()
                    for r in rows:
                        con.execute(f"UPDATE {table} SET {c}=? WHERE {pk}=?", (_ts(_parse_db(r["v"]) - d), r["k"]))
            if "finished_at" in self.cols(con, "promo_keep_state"):
                for r in con.execute("SELECT rowid AS k, finished_at AS v FROM promo_keep_state "
                                     "WHERE finished_at IS NOT NULL").fetchall():
                    try:
                        v = (datetime.strptime(r["v"], FMT) - d).strftime(FMT)
                    except ValueError:
                        self.notes.append(f"keep_state finished_at not shifted: {r['v']}")
                        continue
                    con.execute("UPDATE promo_keep_state SET finished_at=? WHERE rowid=?", (v, r["k"]))
        con.close()
        self.fake.shift(AID, secs)
        self.settle()

    def backstop(self) -> None:
        """Seeded: an hour passes, so the hourly backstop run is due."""
        self.shift(3600)

    def toasts(self, n: int, gap: float, claim: bool = True) -> None:
        for i in range(n):
            if claim:
                self.fake.claim(AID)
            self.main.hook("POST", "/__proof/of-ws-frame",
                           {"account_id": AID, "frame": {"toasts": [{"type": "subscribed", "id": 900000 + i}]}})
            if gap:
                time.sleep(gap)
        self.wait_for(lambda: not any(
            (lambda i: i["received"] != i["processed"])(r.hook("GET", "/__proof/idle"))
            for r in self.relays if r.alive()), 60)

    def posts(self) -> int:
        return self.fake.count(AID, "POST", P)

    def gets(self) -> int:
        return self.fake.count(AID, "GET", P)

    def keep_state(self) -> dict:
        con = self.db()
        try:
            r = con.execute("SELECT * FROM promo_keep_state WHERE account_id=?", (AID,)).fetchone()
        except sqlite3.OperationalError:
            r = None
        con.close()
        return dict(r) if r else {}

    def env(self, set_=None, unset=()) -> None:
        for r in self.relays:
            if r.alive():
                r.hook("POST", "/__proof/env", {"set": set_ or {}, "unset": list(unset)})

    # ── results ───────────────────────────────────────────────
    def dump(self) -> dict:
        con = self.db()

        def q(sql, args=()):
            try:
                return [dict(r) for r in con.execute(sql, args)]
            except sqlite3.OperationalError as e:
                return [{"_error": str(e)}]

        camps = q("SELECT * FROM promo_campaigns WHERE account_id=?", (AID,))
        keys = ("id", "name", "of_promo_id", "auto_reactivate", "preempt", "keep_warning", "keep_host_id",
                "recreates_left", "reactivate_count", "expires_at")
        out = {
            "reservations": q("SELECT id, campaign_id, source, state, error_class, of_promo_id, "
                              "replaced_of_promo_id, claims_seen, first_claims, host_id, created_at, sent_at, "
                              "settled_at, not_before, listed_at FROM promo_create_reservations "
                              "WHERE account_id=? ORDER BY id", (AID,)),
            "keep_state": q("SELECT * FROM promo_keep_state WHERE account_id=?", (AID,)),
            "campaigns": [{k: c.get(k) for k in keys if k in c} for c in camps],
            "notices": q("SELECT kind, text, data_json, dedupe_key, created_at FROM agency_notifications "
                         "WHERE kind='promo_keep_running' ORDER BY id"),
            "runs": q("SELECT id, status, started_at, stats_json FROM automation_runs "
                      "WHERE kind='promo_reactivate' ORDER BY id"),
            "jobs": q("SELECT id, status, run_at, created_at, payload_json FROM scheduled_jobs "
                      "WHERE kind='promo_reactivate' ORDER BY id"),
        }
        con.close()
        out["fake_posts"] = self.fake.acct(AID).posts
        out["fake_events"] = self.fake.acct(AID).events
        out["fake_log"] = [{**r, "t": round(r["t"], 3)} for r in self.fake.log]
        return out

    def log_text(self) -> str:
        return "\n".join(r.log.read_text(errors="replace") for r in self.relays if r.log.exists())

    def finish(self) -> dict:
        for r in self.relays:
            r.kill()
        d = self.dump()
        lines = [ln for ln in self.log_text().splitlines()
                 if "promo_" in ln or "Traceback" in ln or " ERROR " in ln]
        d["log"] = lines
        (self.dir / "dump.json").write_text(json.dumps(d, indent=1, default=str))
        camps = [c for c in d["campaigns"] if "_error" not in c]
        main = next((c for c in camps if c["id"] == self.extra.get("kept_id", self.cid)), camps[0] if camps else {})
        res = [r for r in d["reservations"] if "_error" not in r]
        post0 = next(iter(d["fake_posts"]), {})
        ks = (d["keep_state"] or [{}])[0]
        c = {
            "POST /promotions": self.posts(), "GET /promotions": self.gets(),
            "GET /users/me": sum(1 for r in self.fake.log if r["method"] == "GET" and r["path"] == ME),
            "keep_running": bool(main.get("auto_reactivate")),
            "preempt": None if "preempt" not in main else bool(main.get("preempt")),
            "keep_warning": main.get("keep_warning"),
            "wait_reason": ks.get("wait_reason"),
            "recheck_jobs": sum(1 for j in d["jobs"] if '"_recheck"' in (j.get("payload_json") or "")),
            "notices_fence": sum(1 for n in d["notices"] if '"reason": "fence"' in (n.get("data_json") or "")),
            "jobs_run": sum(1 for r in d["runs"] if r.get("status") not in (None, "running")),
            "claims_at_post": post0.get("claims_old"), "cap": post0.get("cap_old"),
            "gap_s": self.fake.gap_s(AID),
            "sources": [r["source"] for r in res], "states": [r["state"] for r in res],
            **self.extra,
        }
        c["fails"] = judge(self.name, c, "\n".join(lines))
        c["pass"] = not c["fails"]
        c["expected_posts"] = EXPECT[self.name]["posts"]
        c["reason"] = EXPECT[self.name]["reason"]
        c["notes"] = self.notes
        c["code_root"] = self.root.name
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return c


def judge(name: str, c: dict, log: str) -> list[str]:
    e, f = EXPECT[name], []
    if c["POST /promotions"] != e["posts"]:
        f.append(f"POST /promotions expected {e['posts']} observed {c['POST /promotions']}")
    if c["GET /users/me"] != 0:
        f.append(f"GET /users/me expected 0 observed {c['GET /users/me']}")
    for k, v in e["want"].items():
        if k == "refused":
            ok = f"reason={v}" in log
        elif k == "log":
            ok = v in log
        elif k == "claims_lt_cap":
            ok = c["claims_at_post"] is not None and c["claims_at_post"] < c["cap"]
        elif k == "claims_ge_cap":
            ok = c["claims_at_post"] is not None and c["claims_at_post"] >= c["cap"]
        elif k == "notices_fence_min":
            ok = c["notices_fence"] >= v
        elif k == "get_promotions":
            ok = c["GET /promotions"] == v
        elif k == "last_source":
            ok = bool(c["sources"]) and c["sources"][-1] == v
        else:
            ok = c.get(k) == v
        if not ok:
            f.append(f"{k} expected {v!r} observed {c.get(k)!r}")
    return f


# ── scenarios ────────────────────────────────────────────────────────────────────────
def sc_after_end(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0))
    s.fake.finish(AID, p0)
    s.backstop()
    s.backstop()


def _ended_then(s, answers, cycles):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.fake.finish(AID, p0)
    s.fake.acct(AID).next = list(answers)
    s.tick(s.campaign(p0), settle=False)
    s.settle(timeout=150)
    for _ in range(cycles):
        s.backstop()


def sc_mn02_unparsed(s):
    _ended_then(s, [{"body": "not json", "never_listed": True}], 2)


def sc_mn02_never_live(s):
    _ended_then(s, [{"never_listed": True}] * 3, 4)


def sc_mn03_429(s):
    _ended_then(s, [{"status": 429, "retry_after": 30}] * 2, 2)


def sc_mn03_403_once(s):
    _ended_then(s, [{"status": 403}], 2)


def sc_mn05(s):
    _ended_then(s, [{"no_id": True}], 2)


def sc_mn06_slow(s):
    _ended_then(s, [{"sleep": 35}], 2)


def sc_mn06_crash(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.fake.finish(AID, p0)
    hold = threading.Event()
    s.fake.acct(AID).next = [{"hold": hold}]
    s.tick(s.campaign(p0), settle=False)
    s.wake()
    s.extra["post_seen_s"] = s.wait_for(lambda: s.posts() == 1, 60)
    time.sleep(1)
    s.main.kill(signal.SIGKILL)
    hold.set()
    s.relay(tag="relay-restart")
    s.settle()
    s.extra["posts_after_restart"] = s.posts()
    s.backstop()
    s.backstop()


def sc_mn07_two_relays(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0))
    s.relay(tag="relay-2")
    s.fake.finish(AID, p0)
    con = s.db()
    job = dict(con.execute("SELECT * FROM scheduled_jobs WHERE kind='promo_reactivate' ORDER BY id").fetchone())
    con.close()
    for _ in range(2):  # seeded: one due job per relay (run locks are per process), so both run at once
        s.insert("scheduled_jobs", {**{k: v for k, v in job.items() if k != "id"}, "status": "pending",
                                    "attempts": 0, "last_error": None, "run_at": _ts(_now()),
                                    "created_at": _ts(_now())})
    s.settle()          # wakes both relays together
    s.extra["runs_per_relay"] = {r.tag: r.log.read_text().count("kind=promo_reactivate run_id=")
                                 for r in s.relays}
    s.backstop()


def sc_mn07_copy_unset(s):
    s.start(env={"PROMO_CREATE_HOST_ID": None})
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.fake.finish(AID, p0)
    s.tick(s.campaign(p0))
    s.backstop()


def sc_fence_unset(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0))
    s.main.kill()
    g0 = s.gets()
    s.relay(env={"PROMO_CREATE_HOST_ID": None}, tag="relay-unset")
    s.fake.finish(AID, p0)
    s.backstop()
    s.backstop()
    s.extra["get_after_unset"] = s.gets() - g0


def sc_mn09_trial(s):
    s.start()
    p0 = s.fake.add(AID, cap=10, days=3, message=MSG)
    s.tick(s.campaign(p0, discount=100, cap=10, days=3), recreate_limit=3)
    for k in range(3):
        p = s.fake.newest(AID)
        s.fake.set_claims(AID, p.id, 10)
        s.fake.finish(AID, p.id)
        s.backstop()            # After-end
        if k < 2:
            s.backstop()        # the new promo read live before it fills
    s.backstop()


def sc_mn10_untick(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    cid = s.campaign(p0)
    s.tick(cid)
    s.fake.finish(AID, p0)
    s.fake.acct(AID).on_read = lambda: s.extra.__setitem__(
        "untick_status", s.api("PATCH", f"/admin/promotions/{cid}", {"auto_reactivate": False})[0])
    s.backstop()


def sc_mn10_manual_after_read(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0))
    s.fake.finish(AID, p0)
    body = {"account_id": AID, "name": "Manual", "discount": 50, "subscribe_counts": 100,
            "subscribe_days": 30, "message": "Manual proof"}
    s.fake.acct(AID).on_read = lambda: s.extra.__setitem__(
        "manual_status", s.api("POST", "/admin/promotions", body)[0])
    s.backstop()
    s.backstop()


def sc_mn12_takeover(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    c1 = s.campaign(p0)
    s.tick(c1)
    body = {"account_id": AID, "name": "Takeover", "discount": 40, "subscribe_counts": 100,
            "subscribe_days": 30, "message": "Takeover proof", "auto_reactivate": True,
            "expect_taken_from": c1}
    st, d = s.api("POST", "/admin/promotions", body)
    s.extra["first_status"] = st
    s.extra["kept_id"] = d.get("id") if isinstance(d, dict) else None
    st2, d2 = s.api("POST", "/admin/promotions", {**body, "name": "Takeover stale"})
    s.extra["second_status"] = st2
    s.extra["second_detail"] = d2
    s.settle()
    con = s.db()
    s.extra["taken_notice"] = bool(con.execute(
        "SELECT 1 FROM agency_notifications WHERE dedupe_key LIKE 'promo_keep_taken:%'").fetchone())
    s.extra["c1_keep"] = bool(con.execute("SELECT auto_reactivate FROM promo_campaigns WHERE id=?",
                                          (c1,)).fetchone()[0])
    con.close()


def sc_mn13(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=False)
    s.fake.set_claims(AID, p0, 99)
    s.backstop()                        # reads 99: near_cap re-check queued (+90 s)
    s.toasts(1, 0, claim=False)         # a toast OF has not counted yet: poke, under the floor
    s.shift(61)                         # seeded: floor passes; a second run, slot taken
    s.extra["runs_before_cap"] = len([r for r in s.dump()["runs"]])
    s.fake.set_claims(AID, p0, 100)     # full; OF still lists it live
    s.shift(91)                         # seeded: the near_cap re-check is due


def sc_mn14(s):
    s.start()
    s.fake.acct(AID).finish_on_cap = True
    p0 = s.fake.add(AID, cap=100, claims=98, message=MSG)
    s.tick(s.campaign(p0), preempt=False)
    t0 = time.time()
    s.toasts(2, 0.2)                    # 99, 100: OF flips finished on the last
    s.extra["toast_after_tick_s"] = round(time.time() - t0, 1)
    s.extra["poke_fired_after_s"] = s.wait_for(lambda: s.posts() == 1, 150)
    s.settle()


def _toast_run(s, n, gap, drain):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.toasts(n, gap)
    time.sleep(drain)
    s.settle()


def sc_toast_100(s):
    _toast_run(s, 100, 1.5, 70)


def sc_toast_far(s):
    _toast_run(s, 30, 4.0, 30)


def sc_fill_90(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.toasts(90, 0.05)                  # the gate pokes at 89; under the floor: deferred
    s.shift(61)                         # seeded: the floor passes


def sc_fill_twice(s):
    sc_fill_90(s)
    first = s.keep_state().get("kept_of_promo_id")
    # real time: the first read is due ~10 s after the create and folds the new promo in at 0
    s.extra["first_read_after_s"] = s.wait_for(
        lambda: (s.wake() or True) and (k := s.keep_state()).get("kept_of_promo_id") not in (None, first)
        and k.get("first_claims") == 0, 60)
    s.toasts(90, 0.05)                  # claims on the new promo; the gate pokes at 89
    s.shift(125)                        # seeded: the poke floor and the 2 min Cooldown pass


def _seed_skew(s, skew):
    s.insert("promo_keep_state", {"account_id": AID, "skew_s": skew, "seen_below": 0})


def sc_timed(s):
    s.start()
    _seed_skew(s, 0)
    p0 = s.fake.add(AID, cap=100, message=MSG, finished_at=_utc_aware() + timedelta(seconds=200))
    s.tick(s.campaign(p0), preempt=True)
    s.extra["timed_fired_after_s"] = s.wait_for(lambda: s.posts() == 1, 150)
    s.settle()


def _utc_aware():
    return utcnow()


def sc_burst_past_cap(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.toasts(100, 0.02)
    s.shift(61)


def sc_mn01_lag(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.fake.set_claims(AID, p0, 40)
    s.backstop()
    s.fake.acct(AID).stale[p0] = [30]
    s.backstop()
    s.fake.set_claims(AID, p0, 92)
    s.backstop()


def sc_mn01_nonzero_start(s):
    s.start()
    s.fake.acct(AID).new_starts_at = 2
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.fake.set_claims(AID, p0, 90)
    s.backstop()                        # Fill → P1 at 2 claims
    s.backstop()
    s.fake.set_claims(AID, s.fake.newest(AID).id, 92)
    s.backstop()


def sc_mn04_failed_preempt(s):
    s.start()
    a = s.fake.acct(AID)
    a.end_old_on_fail = True
    a.next = [{"status": 429, "retry_after": 30}]
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.fake.set_claims(AID, p0, 90)
    s.backstop()                        # Fill → 429; OF ended P0 anyway; recovery re-check
    s.shift(126)                        # seeded: back-off over, the re-check runs
    s.backstop()


def sc_mn04_no_slot(s):
    s.start()
    p0 = s.fake.add(AID, cap=100, message=MSG)
    cid = s.campaign(p0)
    s.tick(cid, preempt=True)
    now = _now()
    for m in (20, 10):                  # seeded: two automatic creates this hour (never sent)
        s.insert("promo_create_reservations", {
            "account_id": AID, "campaign_id": cid, "source": "auto_ended", "state": "failed",
            "terms_json": "{}", "error_class": "not_sent", "host_id": HOST, "reconcile_reads": 0,
            "created_at": _ts(now - timedelta(minutes=m)), "settled_at": _ts(now - timedelta(minutes=m))})
    s.toasts(90, 0.05)
    s.shift(61)
    s.extra["wait_mid"] = s.keep_state().get("wait_reason")
    s.extra["posts_mid"] = s.posts()
    s.toasts(10, 0.05)
    s.shift(61)


def sc_mn08_guessed_end(s):
    s.start()
    _seed_skew(s, 0)
    p0 = s.fake.add(AID, cap=100, message=MSG)
    cid = s.campaign(p0, finish_days=1, expires_at=_ts(_now() + timedelta(seconds=200)))
    s.tick(cid, preempt=True)
    s.shift(231)                        # seeded: the expiry re-check; OF still lists it live
    s.extra["posts_mid"] = s.posts()
    s.fake.finish(AID, p0)
    s.shift(61)                         # seeded: the expiry retry
    s.backstop()


def sc_mn08_skew(s):
    s.start()
    _seed_skew(s, 45)
    p0 = s.fake.add(AID, cap=100, message=MSG, finished_at=_utc_aware() + timedelta(seconds=100))
    s.tick(s.campaign(p0), preempt=True)
    s.extra["wait_mid"] = s.keep_state().get("wait_reason")
    s.backstop()


def sc_switch_off(s):
    s.start()
    s.env({"PROMO_PREEMPT_ENABLED": "0"})
    try:
        p0 = s.fake.add(AID, cap=100, message=MSG)
        s.tick(s.campaign(p0), preempt=True)
        s.toasts(90, 0.05)
        s.backstop()                    # reads 90, switch off: no Fill
        s.extra["posts_mid"] = s.posts()
        s.extra["wait_mid"] = s.keep_state().get("wait_reason")
        s.toasts(10, 0.05)              # the gate (trigger = cap) pokes at 99; deferred
        s.shift(61)
    finally:
        s.env(unset=["PROMO_PREEMPT_ENABLED"])


def sc_second_live(s):
    s.start()
    s.fake.acct(AID).end_old = False
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.fake.set_claims(AID, p0, 90)
    s.backstop()                        # Fill → P1; P0 stays live
    s.backstop()
    s.backstop()


def sc_preempt_400(s):
    s.start()
    s.fake.acct(AID).next = [{"status": 400, "message": "Bad request"}]
    p0 = s.fake.add(AID, cap=100, message=MSG)
    s.tick(s.campaign(p0), preempt=True)
    s.fake.set_claims(AID, p0, 90)
    s.backstop()                        # Fill → 400
    s.shift(126)                        # seeded: the recovery re-check; P0 still live
    s.extra["posts_mid"] = s.posts()
    s.fake.set_claims(AID, p0, 100)
    s.fake.finish(AID, p0)
    s.backstop()


SCENARIOS = {n: globals()["sc_" + n.replace("-", "_")] for n in EXPECT}


def serve(port: int, root: Path) -> int:
    """Screenshot stack: fake OF + proof relay, Creator 1000001 with a Kept campaign; Ctrl-C stops."""
    out = Path(tempfile.mkdtemp(prefix="promo-serve-out-", dir="/tmp"))
    s = Scenario("serve", out, root)
    s.port = port
    try:
        s.start()
        p0 = s.fake.add(AID, cap=100, claims=37, message=MSG)
        s.tick(s.campaign(p0, name="Spring promo"), preempt=True)
        print(f"relay {s.main.base}  fake OF {s.fake.origin}  temp {s.tmp}\n"
              f"login proof-owner / {PASSWORD}  campaign {s.cid} (Kept, Fill on)\n"
              f"web: cd {root}/app && RELAY_URL={s.main.base} DEMO_SHOTS_TMP={s.tmp} NEXT_TELEMETRY_DISABLED=1 "
              f"NODE_OPTIONS='--require {HERE}/fetch-guard.cjs' nice -n 10 node node_modules/next/dist/bin/next "
              f"dev --webpack -H 127.0.0.1 -p 3047\n"
              "Ctrl-C stops", flush=True)
        while s.main.alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for r in s.relays:
            r.kill()
        s.fake.close()
        shutil.rmtree(s.tmp, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", choices=["A", "B"])
    ap.add_argument("--only", default="")
    ap.add_argument("--relay-root", default=str(ROOT))
    ap.add_argument("--out")
    ap.add_argument("--serve", action="store_true", help="seeded screenshot stack instead of scenarios")
    ap.add_argument("--port", type=int, default=8797, help="--serve relay port")
    a = ap.parse_args()
    if a.serve:
        return serve(a.port, Path(a.relay_root).resolve())
    if not (a.slice and a.out):
        ap.error("--slice and --out are required (or --serve)")
    names = [n for n in EXPECT if EXPECT[n]["slice"] == a.slice]
    if a.only:
        pick = [x.strip() for x in a.only.split(",") if x.strip()]
        bad = [x for x in pick if x not in EXPECT]
        if bad:
            ap.error(f"unknown scenario(s): {bad}")
        names = pick
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "counts.json"
    counts = json.loads(path.read_text()) if path.exists() else {}
    root = Path(a.relay_root).resolve()
    for n in names:
        print(f"── {n}: expect {EXPECT[n]['posts']} POST — {EXPECT[n]['reason']}", flush=True)
        s = Scenario(n, out, root)
        t0 = time.time()
        try:
            SCENARIOS[n](s)
        except Exception as e:  # noqa: BLE001 — a harness error is recorded, the slice goes on
            s.notes.append(f"harness error: {e!r}")
        try:
            c = s.finish()
        except Exception as e:  # noqa: BLE001
            c = {"pass": False, "fails": [f"finish error: {e!r}"], "notes": s.notes}
        c["wall_s"] = round(time.time() - t0, 1)
        counts[n] = c
        path.write_text(json.dumps(counts, indent=1, default=str))
        print(f"   {'PASS' if c['pass'] else 'FAIL'} POST={c.get('POST /promotions')} "
              f"GET={c.get('GET /promotions')} me={c.get('GET /users/me')} {c.get('fails')} {c.get('notes')}",
              flush=True)
    return 0


if __name__ == "__main__":
    def _cleanup(*_):
        for r in _LIVE:
            r.kill(signal.SIGKILL, 5)
        sys.exit(1)
    signal.signal(signal.SIGTERM, _cleanup)
    try:
        sys.exit(main())
    finally:
        for r in _LIVE:
            r.kill(signal.SIGKILL, 5)
