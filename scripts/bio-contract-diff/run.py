#!/usr/bin/env python3
"""Contract diff: ofl.ink v2 (node app + PocketBase) vs the standalone bio app, both seeded from fixture.json.

Delete this tool after the PR3 rollback window.

Not CI: needs node, ~/oflinkv2 (its app/node_modules) and the PocketBase binary. Everything runs on loopback, on temp
dirs, at nice 10, and is stopped at exit. Never a live host.

  ./venv/bin/python scripts/bio-contract-diff/run.py --pb PATH [--out DIR]
      [--v2 ~/oflinkv2]

Compares status, Content-Type, Cache-Control, presence of Location / Access-Control-*, body bytes (ignores date,
server, connection, keep-alive, content-length, transfer-encoding, vary), then PocketBase's dailyStats against
bio_daily. Writes <out>/report.txt and <out>/cases.jsonl. Exit 0 iff every diff is a case marked legit (PR1 spec §5)
and the counts agree. The reviewed escape-card asset bytes map to v2 for comparison; any drift fails.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "service"))
import corpus  # noqa: E402
from bio_pages import decide  # noqa: E402
from slop.lib.stack import Stack  # noqa: E402
from slop.lib import gate  # noqa: E402

EMAIL, PASSWORD = "diff@contract.test", "contract-diff-not-prod-1"
LIMIT = 5
IGNORED = {"date", "server", "connection", "keep-alive", "content-length", "transfer-encoding", "vary"}
AVATAR_SRC = ROOT / "service/bio_pages/public/images/igicon.webp"
PUBLIC = ROOT / "service/bio_pages/public"


def _ports(n: int) -> list[int]:
    ss = [socket.socket() for _ in range(n)]
    for s in ss:
        s.bind(("127.0.0.1", 0))
    out = [s.getsockname()[1] for s in ss]
    for s in ss:
        s.close()
    return out


def _wait(url: str, what: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=2, headers={"X-Forwarded-For": "10.9.255.254"}).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit(f"contract-diff: {what} did not come up at {url}")


def v2_view(v2: Path):
    """Map only pinned PR-E assets and pages built from the pinned index to v2 bytes."""
    ours = {n: (PUBLIC / n).read_bytes() for n in ("index.html", "script.js", "style.css")}
    theirs = {n: (v2 / "app/public" / n).read_bytes() for n in ours}
    pinned = {n: (hashlib.sha256(ours[n]).hexdigest(), hashlib.sha256(theirs[n]).hexdigest())
              == corpus.ASSET_SHA256[n] for n in ours}
    drift = [f"{n} DRIFT" for n in ours if not pinned[n]]
    swap = {ours[n]: theirs[n] for n in ("script.js", "style.css") if pinned[n]}
    our_index = decide.render_index(ours["index.html"].decode("utf-8"), True) if pinned["index.html"] else None
    v2_index = theirs["index.html"].decode("utf-8")

    def view(body: bytes) -> bytes | None:
        if body in swap:
            return swap[body]
        if our_index is None:
            return None
        try:
            boot = decide.parse_bootstrap(body)
        except ValueError:
            return None
        if boot is decide.NO_BOOTSTRAP or decide.bootstrap_page(our_index, boot).encode("utf-8") != body:
            return None
        return decide.bootstrap_page(v2_index, boot).encode("utf-8")
    return view, drift


def send(port: int, case: dict, ip: str | None, avatar: str, view=None) -> dict:
    """One raw HTTP/1.1 request; normalize only pinned reviewed asset bodies."""
    target = case["target"].replace(b"{avatar}", avatar.encode())
    lines = [case["method"].encode() + b" " + target + b" HTTP/1.1"]
    if case["host"] is not None:
        lines.append(b"Host: " + case["host"].encode())
    hdrs = dict(case["headers"])
    if ip and case.get("xff", True):
        hdrs.setdefault("X-Forwarded-For", ip)
    if case["method"] in ("POST", "PUT", "PATCH"):
        hdrs["Content-Length"] = "0"
    hdrs["Connection"] = "close"
    lines += [f"{k}: {v}".encode() for k, v in hdrs.items()]
    raw = b"\r\n".join(lines) + b"\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=15) as s:
        s.sendall(raw)
        resp = http.client.HTTPResponse(s, method=case["method"])
        try:
            resp.begin()
            body = resp.read()
        except (http.client.HTTPException, OSError) as e:
            return {"status": None, "error": type(e).__name__}
        h = {k.lower(): v for k, v in resp.getheaders()}
    got = {"status": resp.status, "content-type": h.get("content-type"), "cache-control": h.get("cache-control"),
           "location": "location" in h, "cors": sorted(k for k in h if k.startswith("access-control-")),
           "body_sha": hashlib.sha1(body).hexdigest(), "body_len": len(body),
           "body_head": body[:160].decode("utf-8", "replace"),
           "extra_headers": sorted(k for k in h if k not in IGNORED | {"content-type", "cache-control"})}
    if view is not None:
        seen = view(body)
        if seen is not None and seen != body:
            got["body_sha"] = hashlib.sha1(seen).hexdigest()
            got["mapped"] = True
    return got


def _same(a: dict, b: dict) -> list[str]:
    keys = ("status", "content-type", "cache-control", "location", "cors", "body_sha", "error")
    return [k for k in keys if a.get(k) != b.get(k)]


def seed_pb(pb: str, fx: dict) -> str:
    """Fixture into PocketBase over its REST API as the superuser; returns the avatar's stored file name."""
    tok = httpx.post(f"{pb}/api/collections/_superusers/auth-with-password",
                     json={"identity": EMAIL, "password": PASSWORD}).raise_for_status().json()["token"]
    h = {"Authorization": tok}
    avatar = ""
    for p in fx["profiles"]:
        body = {k: p[k] for k in ("id", "username", "displayName", "bio", "verified", "mode")}
        httpx.post(f"{pb}/api/collections/profiles/records", json=body, headers=h).raise_for_status()
        if p.get("avatar"):
            r = httpx.patch(f"{pb}/api/collections/profiles/records/{p['id']}", headers=h,
                            files={"avatar": ("avatar.webp", AVATAR_SRC.read_bytes(), "image/webp")})
            avatar = r.raise_for_status().json()["avatar"]
    for lk in fx["links"]:
        httpx.post(f"{pb}/api/collections/links/records", json=lk, headers=h).raise_for_status()
    for d in fx["spareDomains"]:
        httpx.post(f"{pb}/api/collections/spareDomains/records", json=d, headers=h).raise_for_status()
    for d in fx["customDomains"]:
        httpx.post(f"{pb}/api/collections/customDomains/records", json=d, headers=h).raise_for_status()
    return avatar


def seed_ours(db: Path, files: Path, fx: dict, avatar: str) -> None:
    con = sqlite3.connect(db, timeout=30)
    try:
        with con:
            con.execute("INSERT INTO users(id, username, password) VALUES ('diff-owner', 'diff-owner', 'x')")
            for p in fx["profiles"]:
                con.execute("INSERT INTO bio_profiles(id, owner_user_id, username, display_name, bio, avatar, mode,"
                            " verified) VALUES (?, 'diff-owner', ?, ?, ?, ?, ?, ?)",
                            (p["id"], p["username"], p["displayName"], p["bio"], avatar if p.get("avatar") else "",
                             p["mode"], int(p["verified"])))
            for lk in fx["links"]:
                con.execute("INSERT INTO bio_links(id, profile_id, link_id, title, destination, default_tracking_code,"
                            " mode, geo, is_adult, tracking, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (lk["id"], lk["profile"], lk["linkId"], lk["title"], lk["destination"],
                             lk["defaultTrackingCode"], lk["mode"],
                             json.dumps(lk["geo"]) if lk["geo"] is not None else None, int(lk["isAdult"]),
                             int(lk["tracking"]), float(lk["order"])))
            for d in fx["spareDomains"]:
                con.execute("INSERT INTO bio_spare_domains(id, domain) VALUES (?, ?)", (d["id"], d["domain"]))
            for d in fx["customDomains"]:
                con.execute("INSERT INTO bio_custom_domains(id, profile_id, domain, status) VALUES (?,?,?,?)",
                            (d["id"], d["profile"], d["domain"], d["status"]))
    finally:
        con.close()
    pid = next(p["id"] for p in fx["profiles"] if p.get("avatar"))
    (files / "profiles" / pid).mkdir(parents=True, exist_ok=True)
    (files / "profiles" / pid / avatar).write_bytes(AVATAR_SRC.read_bytes())
    (files / "profiles" / pid / ".hidden").write_bytes(b"x")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / ".scratch/bio-contract-diff"
                    / datetime.now().strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--pb", default=os.environ.get("POCKETBASE_BIN"), required=not os.environ.get("POCKETBASE_BIN"))
    ap.add_argument("--v2", type=Path, default=Path(os.environ["OFLINK_V2_DIR"]) if os.environ.get("OFLINK_V2_DIR")
                    else None, required=not os.environ.get("OFLINK_V2_DIR"))
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    with gate.machine_gate(wait=True, evidence=out):
        tmp = Path(tempfile.mkdtemp(prefix="bio-contract-diff-"))
        p_pb, p_v2 = _ports(2)
        fx = json.loads((HERE / "fixture.json").read_text())
        procs: list[subprocess.Popen] = []
        stack = None
        nice = ["nice", "-n", "10"]

        def spawn(cmd, log, **kw):
            procs.append(subprocess.Popen(nice + cmd, stdout=open(tmp / log, "wb"), stderr=subprocess.STDOUT,
                                          start_new_session=True, **kw))

        try:
            pbdir = ["--dir", str(tmp / "pb_data"), "--migrationsDir", str(args.v2 / "pocketbase/pb_migrations"),
                     "--hooksDir", str(args.v2 / "pocketbase/pb_hooks")]
            subprocess.run(nice + [args.pb, "migrate", "up", *pbdir], check=True, capture_output=True)
            subprocess.run(nice + [args.pb, "superuser", "upsert", EMAIL, PASSWORD, *pbdir], check=True,
                           capture_output=True)
            spawn([args.pb, "serve", "--http", f"127.0.0.1:{p_pb}", *pbdir], "pb.log")
            _wait(f"http://127.0.0.1:{p_pb}/api/health", "PocketBase")

            stack = Stack(ui=False, fault=None, logdir=out, sidecars={"bio": ("slop/lib/bio.py", "BIO_PORT", "/internal/healthz")})
            stack.relay_env[0].update(BIO_PRIMARY_HOSTS="localhost,ofl.test", BIO_REVEAL_LIMIT_PER_MINUTE=str(LIMIT),
                                      BIO_ESCAPE_TAP="1")
            stack.__enter__()
            db = stack.db
            p_bio = stack.extra_ports["BIO_PORT"]

            avatar = seed_pb(f"http://127.0.0.1:{p_pb}", fx)
            seed_ours(db, stack.shard_svc[0] / "bio_files", fx, avatar)

            v2env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "PORT": str(p_v2),
                     "PB_URL": f"http://127.0.0.1:{p_pb}", "PB_SUPERUSER_EMAIL": EMAIL, "PB_SUPERUSER_PASSWORD": PASSWORD,
                     "PRIMARY_HOSTS": "localhost,ofl.test", "REVEAL_LIMIT_PER_MINUTE": str(LIMIT)}
            spawn(["node", "-r", str(HERE / "listen-shim.cjs"), "server.js"], "v2.log", env=v2env, cwd=args.v2 / "app")
            _wait(f"http://127.0.0.1:{p_v2}/internal/healthz", "ofl.ink v2")

            view, drift = v2_view(args.v2)
            cases = corpus.build()
            rows, ip_of = [], {}
            plain = [c for c in cases if not c.get("burst")]
            bursts = [c for c in cases if c.get("burst")]
            for i, c in enumerate(plain):
                ip = f"10.9.{i // 250}.{i % 250 + 1}"
                a, b = send(p_v2, c, ip, avatar), send(p_bio, c, ip, avatar, view)
                rows.append({"case": c["name"], "legit": c["legit"], "extra_count": c.get("extra_count"),
                             "diff": _same(a, b), "v2": a, "ours": b})
            if datetime.now().second >= 50:   # every burst inside one guard minute
                time.sleep(61 - datetime.now().second)
            for j, c in enumerate(bursts):
                ip = ip_of.get(c.get("same_ip_as")) or f"10.9.250.{j + 1}"
                ip_of[c["name"]] = ip
                theirs = [send(p_v2, c, ip, avatar) for _ in range(c["burst"])]
                ours = [send(p_bio, c, ip, avatar, view) for _ in range(c["burst"])]
                for k, (a, b) in enumerate(zip(theirs, ours)):
                    rows.append({"case": f"{c['name']} #{k + 1}", "legit": c["legit"], "diff": _same(a, b),
                                 "v2": a, "ours": b})

            # SIGTERM exercises the bio lifespan flush before count reconciliation.
            bio_proc = stack.sidecar_procs["bio"]
            os.killpg(bio_proc.pid, signal.SIGTERM)
            bio_proc.wait(timeout=45)
            # counts: v2's events (dailyStats) vs bio_daily, minus legit no-XFF events
            pb = f"http://127.0.0.1:{p_pb}"
            tok = httpx.post(f"{pb}/api/collections/_superusers/auth-with-password",
                             json={"identity": EMAIL, "password": PASSWORD}).json()["token"]
            items = httpx.get(f"{pb}/api/collections/dailyStats/records?perPage=500",
                              headers={"Authorization": tok}).json()["items"]
            theirs_n = Counter()
            for it in items:
                theirs_n[(it["day"], it["profile"], it["link"], it["country"], "v")] += it["views"]
                theirs_n[(it["day"], it["profile"], it["link"], it["country"], "c")] += it["clicks"]
            con = sqlite3.connect(db)
            ours_n = Counter()
            for day, pid, lid, country, v, k in con.execute(
                    "SELECT day, profile_id, link_id, country, SUM(views), SUM(clicks) FROM bio_daily GROUP BY 1,2,3,4"):
                ours_n[(day, pid, lid, country, "v")] += v
                ours_n[(day, pid, lid, country, "c")] += k
            con.close()
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            explained = Counter()
            for r in rows:
                if r.get("extra_count") and r["ours"].get("status") in (200, 204) \
                        and r["v2"].get("status") not in (200, 204):
                    explained[(day, *r["extra_count"])] += 1
            theirs_n, ours_n = +theirs_n, +(ours_n - explained)
            counts_ok = theirs_n == ours_n
            counts_diff = {"|".join(k): (theirs_n.get(k, 0), ours_n.get(k, 0))
                           for k in set(theirs_n) | set(ours_n) if theirs_n.get(k, 0) != ours_n.get(k, 0)}

            bad = [r for r in rows if (set(r["diff"]) - corpus.LEGIT.get(r["legit"], frozenset())) or
                   (r["legit"] and not r["diff"])]
            legit_hit = Counter(r["legit"] for r in rows if r["diff"] and r["legit"])
            legit_same = [r["case"] for r in rows if r["legit"] and not r["diff"]]
            with open(out / "cases.jsonl", "w") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            lines = [f"contract diff {datetime.now().isoformat(timespec='seconds')}",
                     f"v2: {args.v2} (node {subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()},"
                     f" PocketBase {subprocess.run([args.pb, '--version'], capture_output=True, text=True).stdout.strip()})",
                     f"ours: {ROOT} bio_pages on BIO_PORT {p_bio} (Stack, separate bio process, temp DB)",
                     f"cases: {len(rows)} answers compared ({len(plain)} cases + {sum(c['burst'] for c in bursts)} burst answers)",
                     f"same: {sum(not r['diff'] for r in rows)}",
                     f"reviewed asset rows mapped: {sum(bool(r['ours'].get('mapped')) for r in rows)}",
                     f"reviewed asset pins: {', '.join(drift) if drift else 'all pinned'}",
                     f"legit diffs: {sum(legit_hit.values())}"] + [f"  {n:4d}  {why}" for why, n in legit_hit.most_common()] + [
                     f"legit-marked but equal: {len(legit_same)} {legit_same[:8]}",
                     f"UNEXPECTED diffs: {len(bad)}"]
            for r in bad[:60]:
                lines.append(f"  {r['case']!r}: {r['diff']} v2={ {k: r['v2'].get(k) for k in r['diff']} } "
                             f"ours={ {k: r['ours'].get(k) for k in r['diff']} }")
            lines.append(f"counts (dailyStats vs bio_daily, {sum(explained.values())} legit no-XFF events excluded): "
                         f"{'equal' if counts_ok else 'DIFFER'} ({sum(theirs_n.values())} events) {counts_diff}")
            verdict = "PASS" if not bad and counts_ok else "FAIL"
            lines.append(f"verdict: {verdict}")
            (out / "report.txt").write_text("\n".join(lines) + "\n")
            print("\n".join(lines))
            print(f"contract-diff: {out}")
            return 0 if verdict == "PASS" else 1
        finally:
            if stack is not None:
                stack.__exit__(None, None, None)
            for p in procs:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for p in procs:
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
            for log in ("pb.log", "v2.log"):
                if (tmp / log).exists():
                    (out / log).write_bytes((tmp / log).read_bytes())


if __name__ == "__main__":
    sys.exit(main())
