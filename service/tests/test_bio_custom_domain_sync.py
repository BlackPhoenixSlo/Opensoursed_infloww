#!/usr/bin/env python3
"""deploy/bio/sync-custom-domains.py over a fixture SQLite DB: only pending_cert/live + valid hostnames get a router,
at most --max-new new ones per run, no write when unchanged, the old file kept on a DB failure, the DB opened
read-only, and a domain whose A record misses BIO_SERVER_IP for --drop-after-s dropped (and back once it resolves).

Run: ./venv/bin/python service/tests/test_bio_custom_domain_sync.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

import importlib.util  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

from bio_pages import decide  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/bio/sync-custom-domains.py"
_spec = importlib.util.spec_from_file_location("sync_custom_domains", SCRIPT)
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)
IP = "203.0.113.7"


def _fixture(rows):
    d = Path(tempfile.mkdtemp(prefix="bio_cd_sync_"))
    db = d / "chatterly.db"
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE bio_custom_domains (id TEXT PRIMARY KEY, profile_id TEXT, domain TEXT, status TEXT, "
              "token TEXT, checked TEXT)")
    c.executemany("INSERT INTO bio_custom_domains(id, profile_id, domain, status) VALUES (?, ?, ?, ?)",
                  [(f"r{i}", f"p{i}", dom, st) for i, (dom, st) in enumerate(rows)])
    c.commit()
    c.close()
    env = d / ".env"
    env.write_text(f"OTHER=1\nBIO_SERVER_IP={IP}\n")
    return d, sync.parse_args(["--db", str(db), "--out", str(d / "dyn" / "bio-custom-domains.yml"),
                               "--state", str(d / "state" / "state.json"), "--env-file", str(env),
                               "--upstream", "http://127.0.0.1:8791"])


def _routers(args):
    return yaml.safe_load(args.out.read_text())["http"]["routers"]


def _mkout(args):
    args.out.parent.mkdir(parents=True, exist_ok=True)


def case_hostname_rule_matches_the_bio_app():
    assert sync.HOSTNAME.pattern == decide.HOSTNAME.pattern


def case_routes_only_verified_valid_domains():
    d, args = _fixture([("a.example", "live"), ("b.example", "pending_cert"), ("c.example", "pending"),
                        ("Bad Domain", "live"), ("x.example`) || Host(`evil.test", "live"), ("a.example", "live")])
    _mkout(args)
    assert sync.run(args, now=1000, resolve=lambda _d: {IP}) == 0
    r = _routers(args)
    assert sorted(v["rule"] for v in r.values()) == ["Host(`a.example`)", "Host(`b.example`)"], r
    for v in r.values():
        assert v["entryPoints"] == ["websecure"] and v["tls"] == {"certResolver": "letsencrypt"}
        assert v["service"] == "bio-custom-domains"
    cfg = yaml.safe_load(args.out.read_text())
    assert cfg["http"]["services"]["bio-custom-domains"]["loadBalancer"]["servers"] == [
        {"url": "http://127.0.0.1:8791"}]
    assert not list(args.out.parent.glob(".*.tmp")), "no tmp file left behind"
    assert oct(args.out.stat().st_mode)[-3:] == "644"


def case_at_most_five_new_per_run_and_no_rewrite_when_unchanged():
    d, args = _fixture([(f"d{i}.example", "live") for i in range(8)])
    _mkout(args)
    sync.run(args, now=1000, resolve=lambda _d: {IP})
    assert len(_routers(args)) == 5
    sync.run(args, now=1060, resolve=lambda _d: {IP})
    assert len(_routers(args)) == 8
    mtime = args.out.stat().st_mtime_ns
    args.out.touch()
    before = args.out.stat().st_mtime_ns
    assert sync.run(args, now=1120, resolve=lambda _d: {IP}) == 0
    assert args.out.stat().st_mtime_ns == before, "unchanged: not rewritten"
    assert mtime


def case_empty_writes_an_empty_valid_file():
    d, args = _fixture([("p.example", "pending")])
    _mkout(args)
    assert sync.run(args, now=1000) == 0
    assert args.out.read_text() == "{}\n" and yaml.safe_load(args.out.read_text()) == {}


def case_removed_row_drops_its_router():
    d, args = _fixture([("a.example", "live"), ("b.example", "live")])
    _mkout(args)
    sync.run(args, now=1000, resolve=lambda _d: {IP})
    c = sqlite3.connect(args.db)
    c.execute("UPDATE bio_custom_domains SET status = 'pending' WHERE domain = 'b.example'")
    c.commit()
    c.close()
    sync.run(args, now=1060, resolve=lambda _d: {IP})
    assert [v["rule"] for v in _routers(args).values()] == ["Host(`a.example`)"]


def case_db_failure_keeps_the_old_file():
    d, args = _fixture([("a.example", "live")])
    _mkout(args)
    sync.run(args, now=1000, resolve=lambda _d: {IP})
    old = args.out.read_text()
    args.db = d / "missing.db"
    assert sync.run(args, now=1060) == 1
    assert args.out.read_text() == old
    assert not args.db.exists(), "mode=ro never creates the DB"


def case_db_is_opened_read_only():
    d, args = _fixture([("a.example", "live")])
    real = sqlite3.connect
    seen = []

    def spy(target, *a, **kw):
        seen.append((target, kw.get("uri")))
        return real(target, *a, **kw)
    sync.sqlite3.connect = spy
    try:
        _mkout(args)
        sync.run(args, now=1000, resolve=lambda _d: {IP})
    finally:
        sync.sqlite3.connect = real
    assert seen and all(t.endswith("?mode=ro") and uri for t, uri in seen), seen


def case_dns_miss_for_a_day_drops_then_returns():
    d, args = _fixture([("a.example", "live"), ("b.example", "live")])
    _mkout(args)
    answers = {"a.example": {IP}, "b.example": {IP}}
    res = lambda dom: answers[dom]  # noqa: E731
    t = 1000.0
    sync.run(args, now=t, resolve=res)
    answers["b.example"] = {"198.51.100.1"}
    for step in range(1, 26):  # hourly re-resolves; the first miss at step 1, under 24 h of misses it stays
        t += 3600
        sync.run(args, now=t, resolve=res)
        if step < 25:
            assert len(_routers(args)) == 2, step
    assert [v["rule"] for v in _routers(args).values()] == ["Host(`a.example`)"], "a day of misses: dropped"
    answers["b.example"] = None  # resolver can't say: no change
    t += 3600
    sync.run(args, now=t, resolve=res)
    assert len(_routers(args)) == 1
    answers["b.example"] = {IP}
    t += 3600
    sync.run(args, now=t, resolve=res)
    assert len(_routers(args)) == 2, "resolves here again: back"
    state = json.loads(args.state.read_text())
    assert "miss_since" not in state["b.example"], state


def case_recheck_is_bounded():
    d, args = _fixture([(f"d{i}.example", "live") for i in range(30)])
    _mkout(args)
    calls = []
    res = lambda dom: calls.append(dom) or {IP}  # noqa: E731
    sync.run(args, now=1000, resolve=res)
    assert len(calls) == 20, "at most --resolve-per-run"
    calls.clear()
    sync.run(args, now=1060, resolve=res)
    assert len(calls) == 10, "the rest; the checked ones wait --recheck-s"
    calls.clear()
    sync.run(args, now=1120, resolve=res)
    assert calls == []


def case_no_server_ip_no_drop():
    d, args = _fixture([("a.example", "live")])
    (d / ".env").write_text("BIO_SERVER_IP=\n")
    _mkout(args)
    for t in range(0, 3 * 24 * 3600, 3600):
        sync.run(args, now=1000 + t, resolve=lambda _d: set())
    assert len(_routers(args)) == 1


_harness.run()
