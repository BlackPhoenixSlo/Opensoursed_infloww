#!/usr/bin/env python3
"""Bio custom domains → one Traefik file-provider route file (deploy/bio/README.md "Custom domains").

Run by bio-custom-domains.timer every minute on the box. Reads `bio_custom_domains` read-only (sqlite file URI,
mode=ro) and writes `--out` with one TLS router per domain whose status is `pending_cert` or `live` (DNS already
proved by the editor's check, bio_pages/domains.py), all to the bio service `--upstream`. Each domain is
re-validated against the bio app's hostname rule. At most `--max-new` domains not yet in the file join per run (each
one makes Traefik ask Let's Encrypt for a certificate). The file is written to a dot-tmp name Traefik ignores, parsed
back, then renamed over the old one; nothing is written when it would not change, and a DB or parse failure leaves
the old file as it is (exit 1).

A routed domain's A record is re-resolved at most once per `--recheck-s` (at most `--resolve-per-run` per run, the
oldest first). One that has not named BIO_SERVER_IP (from `--env-file`) for `--drop-after-s` is dropped from the
file and logged; it comes back when it resolves here again. The DB row is left alone (this script never writes the
DB): the owner sees it in the editor and checks or removes it there. Without BIO_SERVER_IP nothing is dropped.

Stdlib only (PyYAML is used for the parse-back check when installed); the file is JSON, which is YAML.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
import sys
import time
from pathlib import Path

# bio_pages/decide.py HOSTNAME (the bio app serves nothing else)
HOSTNAME = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]")
SERVICE = "bio-custom-domains"
_RULE = re.compile(r"Host\(`([^`]+)`\)")


def log(msg: str) -> None:
    print(f"bio-custom-domains: {msg}", flush=True)


def valid(domain: str) -> bool:
    return len(domain) <= 253 and bool(HOSTNAME.fullmatch(domain))


def read_domains(db: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        rows = con.execute("SELECT DISTINCT domain FROM bio_custom_domains "
                           "WHERE status IN ('pending_cert', 'live')").fetchall()
    finally:
        con.close()
    return sorted({str(r[0]) for r in rows})


def router_name(domain: str) -> str:
    return f"bio-cd-{domain.replace('.', '-')[:40]}-{hashlib.sha1(domain.encode()).hexdigest()[:8]}"


def build(domains: list[str], upstream: str, entrypoint: str, resolver: str) -> str:
    if not domains:
        return "{}\n"
    routers = {router_name(d): {"rule": f"Host(`{d}`)", "entryPoints": [entrypoint], "service": SERVICE,
                                "tls": {"certResolver": resolver}} for d in domains}
    cfg = {"http": {"routers": routers, "services": {SERVICE: {"loadBalancer": {"servers": [{"url": upstream}]}}}}}
    return json.dumps(cfg, indent=2, sort_keys=True) + "\n"


def routed(text: str) -> set[str]:
    """The domains a route file of ours names."""
    try:
        routers = (json.loads(text) or {}).get("http", {}).get("routers", {})
    except (ValueError, AttributeError):
        return set()
    return {m.group(1) for r in routers.values() if isinstance(r, dict)
            for m in [_RULE.fullmatch(str(r.get("rule", "")))] if m}


def parses(text: str) -> bool:
    try:
        data = json.loads(text)
    except ValueError:
        return False
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return isinstance(data, dict)
    try:
        return yaml.safe_load(text) == data
    except yaml.YAMLError:
        return False


def server_ip(env_file: Path | None) -> str | None:
    raw = os.environ.get("BIO_SERVER_IP", "")
    if not raw and env_file and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BIO_SERVER_IP="):
                raw = line.split("=", 1)[1].strip().strip("'\"")
    try:
        return str(ipaddress.IPv4Address(raw.strip())) if raw.strip() else None
    except ValueError:
        log("BIO_SERVER_IP is not an IPv4 address: no DNS drop check")
        return None


def resolve_a(domain: str) -> set[str] | None:
    """The domain's IPv4 addresses; an empty set when it has none, None when the resolver can't say now."""
    try:
        infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as e:
        return set() if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)) else None
    return {i[4][0] for i in infos}


def dropped(domains: list[str], state: dict, ip: str | None, now: float, args, resolve=resolve_a) -> set[str]:
    """Update `state` ({domain: {"checked", "miss_since"}}) with this run's re-resolves; the domains to leave out."""
    for d in list(state):
        if d not in domains:
            del state[d]
    if ip is None:
        return set()
    last = {d: state.get(d, {}).get("checked", float("-inf")) for d in domains}
    due = sorted((d for d in domains if now - last[d] >= args.recheck_s), key=last.__getitem__)[:args.resolve_per_run]
    for d in due:
        got = resolve(d)
        if got is None:
            continue
        st = state.setdefault(d, {})
        st["checked"] = now
        if ip in got:
            st.pop("miss_since", None)
        else:
            st.setdefault("miss_since", now)
    return {d for d in domains if now - state.get(d, {}).get("miss_since", now) >= args.drop_after_s}


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def run(args, now: float | None = None, resolve=resolve_a) -> int:
    now = time.time() if now is None else now
    try:
        rows = read_domains(args.db)
    except sqlite3.Error as e:
        log(f"DB unreadable ({type(e).__name__}): route file left as it is")
        return 1
    bad = [d for d in rows if not valid(d)]
    if bad:
        log(f"skipped {len(bad)} invalid domain(s)")
    wanted = [d for d in rows if valid(d)]
    state_path = args.state
    try:
        state = json.loads(state_path.read_text()) if state_path and state_path.is_file() else {}
    except ValueError:
        state = {}
    gone = dropped(wanted, state, server_ip(args.env_file), now, args, resolve)
    old_text = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
    have = routed(old_text)
    keep = [d for d in wanted if d not in gone and d in have]
    new = [d for d in wanted if d not in gone and d not in have]
    final = sorted(keep + new[:args.max_new])
    text = build(final, args.upstream, args.entrypoint, args.resolver)
    if not parses(text):
        log("built a file that does not parse back: route file left as it is")
        return 1
    if text != old_text:
        write_atomic(args.out, text)
        log(f"routers={len(final)} added={sorted(set(final) - have)} removed={sorted(have - set(final))} "
            f"deferred={max(0, len(new) - args.max_new)} dropped_dns={sorted(gone)}")
    if state_path:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(state_path, json.dumps(state, sort_keys=True))
    return 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", type=Path, default=Path("/root/opensoursed_infloww/service/data/chatterly.db"))
    p.add_argument("--out", type=Path, default=Path("/root/traefik-dynamic/bio-custom-domains.yml"))
    p.add_argument("--upstream", default="http://127.0.0.1:8791")
    p.add_argument("--entrypoint", default="websecure")
    p.add_argument("--resolver", default="letsencrypt")
    p.add_argument("--state", type=Path, default=Path("/var/lib/bio-custom-domains/state.json"))
    p.add_argument("--env-file", type=Path, default=Path("/root/opensoursed_infloww/.env"))
    p.add_argument("--max-new", type=int, default=5)
    p.add_argument("--recheck-s", type=int, default=3600)
    p.add_argument("--resolve-per-run", type=int, default=20)
    p.add_argument("--drop-after-s", type=int, default=24 * 3600)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args()))
