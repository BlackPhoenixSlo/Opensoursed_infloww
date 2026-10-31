"""
A proxies.json read while `save` rewrites it in place (truncate, write, fsync: the
bind mount forbids a rename) must never send a proxied Creator's traffic direct.

  case_egress_table                      proxies.egress: Ok / Torn x last good yes / no x
                                         proxied / unproxied -> Proxy / Direct / Refuse
  case_registry_reads                    missing file: empty Ok; empty, half-written, not a
                                         registry: Torn with the last good read (or None);
                                         `save` itself is a good read; load() never empty
                                         once one was good; each caller its own copy
  case_read_overtaken_by_save            a read that a save lands in the middle of does not
                                         store its older text as the last good
  case_writers_on_torn                   every writer (and sync_pool) on any torn read, with
                                         or without a last good: RegistryUnreadable (sync:
                                         skipped), file untouched
  case_torn_logged_once_per_run          a run of torn reads logs one warning; the good read
                                         ending it one info
  case_from_session_file                 torn with a last good: the proxied client; torn
                                         with none: EgressRefused, no client; Ok unproxied:
                                         direct
  case_save_loop_vs_concurrent_load      `save` in a loop thread vs load() / egress() in
                                         another: never an empty registry, never Direct for
                                         the proxied account (N reads, torn ones counted)

Run: ./venv/bin/python service/tests/test_proxy_registry_read.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import logging  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import of_client  # noqa: E402
import proxies as proxy_registry  # noqa: E402
from proxies import Direct, Ok, Proxy, Refuse, Torn, egress  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="proxy_registry_read_"))
proxy_registry.REGISTRY_PATH = TMP / "proxies.json"
PROXIED, UNPROXIED = "111", "222"
ENTRY = {"label": "hu-1", "scheme": "http", "host": "h.invalid", "port": 8080,
         "assigned_account_ids": [PROXIED]}
GOOD = {"proxies": [ENTRY]}


def _fresh(text: str | None) -> None:
    """The file as `text` (None: no file) and no good read remembered."""
    proxy_registry._last_good_text = None
    proxy_registry._torn_logged = False
    if text is None:
        proxy_registry.REGISTRY_PATH.unlink(missing_ok=True)
    else:
        proxy_registry.REGISTRY_PATH.write_text(text)


def case_egress_table() -> None:
    # (registry, account) -> egress
    for reg, aid, want in [
        (Ok(GOOD), PROXIED, Proxy(ENTRY)),
        (Ok(GOOD), UNPROXIED, Direct()),
        (Ok({"proxies": []}), PROXIED, Direct()),
        (Torn(GOOD), PROXIED, Proxy(ENTRY)),      # torn, last good: answers from it
        (Torn(GOOD), UNPROXIED, Direct()),
        (Torn(None), PROXIED, Refuse),            # torn, none before: never direct
        (Torn(None), UNPROXIED, Refuse),          # nothing tells it apart (inferred: no marker exists)
    ]:
        got = egress(reg, aid)
        assert (isinstance(got, Refuse) if want is Refuse else got == want), (reg, aid, got)
    # The legacy per-session-file binding, through either registry.
    legacy = {"proxies": [{**ENTRY, "assigned_account_ids": [], "assigned_session": "s.json"}]}
    for reg in (Ok(legacy), Torn(legacy)):
        assert egress(reg, UNPROXIED, "s.json") == Proxy(legacy["proxies"][0])
        assert egress(reg, UNPROXIED, "other.json") == Direct()


def case_registry_reads() -> None:
    _fresh(None)
    assert proxy_registry.registry() == Ok({"proxies": []})
    for torn in ("", json.dumps(GOOD)[:17], "[]", '{"proxies": 3}', "{}"):
        _fresh(torn)
        assert proxy_registry.registry() == Torn(None), torn
        assert proxy_registry.load() == {"proxies": []}, torn    # nothing better ever read
        _fresh(json.dumps(GOOD))
        assert proxy_registry.registry() == Ok(GOOD)
        proxy_registry.REGISTRY_PATH.write_text(torn)
        assert proxy_registry.registry() == Torn(GOOD), torn
        assert proxy_registry.load() == GOOD, torn
    # save is a good read too (the process's own write); a later torn read answers from it.
    _fresh("")
    newer = {"proxies": [{**ENTRY, "port": 9090}]}
    proxy_registry.save(newer)
    proxy_registry.REGISTRY_PATH.write_text("")
    assert proxy_registry.load() == newer
    # Each caller its own copy: mutating one does not change the next.
    proxy_registry.load()["proxies"].clear()
    assert proxy_registry.load() == newer


def case_read_overtaken_by_save() -> None:
    real, newer = proxy_registry.REGISTRY_PATH, {"proxies": [{**ENTRY, "port": 9090}]}

    class SaveMidRead:              # read the old text, then a save lands before the read returns
        def exists(self):
            return real.exists()

        def read_text(self):
            text = real.read_text()
            proxy_registry.REGISTRY_PATH = real
            proxy_registry.save(newer)
            return text

    _fresh(json.dumps(GOOD))
    proxy_registry.REGISTRY_PATH = SaveMidRead()
    try:
        assert proxy_registry.registry() == Ok(GOOD)   # the read itself is what it read
    finally:
        proxy_registry.REGISTRY_PATH = real
    real.write_text("")
    assert proxy_registry.load() == newer, "an overtaken read stored its older text as the last good"


def case_writers_on_torn() -> None:
    other = {**ENTRY, "label": "de-1", "assigned_account_ids": ["333"]}
    two = {"proxies": [ENTRY, other]}
    new = {"label": "fr-1", "host": "f.invalid", "port": 1}
    writers = [
        ("upsert", lambda: proxy_registry.upsert(dict(new))),
        ("remove", lambda: proxy_registry.remove("hu-1")),
        ("assign", lambda: proxy_registry.assign("hu-1", "s.json")),
        ("assign_account", lambda: proxy_registry.assign_account("hu-1", "444")),
        ("unbind_account", lambda: proxy_registry.unbind_account("hu-1", PROXIED)),
        ("migrate_legacy_assignments", lambda: proxy_registry.migrate_legacy_assignments({})),
        ("record_verification", lambda: proxy_registry.record_verification("hu-1", ip="1.2.3.4", geo="HU", ok=True)),
    ]
    torn = json.dumps(two)[:40]
    # Torn with none before, or with a last good (another process mid-write: last good +
    # our edit would drop its write): refuse, file untouched.
    for last_good in (False, True):
        for name, w in writers:
            _fresh(json.dumps(two))
            if last_good:
                proxy_registry.registry()
            proxy_registry.REGISTRY_PATH.write_text(torn)
            try:
                w()
                raise AssertionError(f"{name} wrote on an unreadable registry (last_good={last_good})")
            except proxy_registry.RegistryUnreadable:
                pass
            assert proxy_registry.REGISTRY_PATH.read_text() == torn, (name, last_good)
        r = proxy_registry.sync_pool("none")
        assert r["skipped"] == "registry unreadable", (last_good, r)
        assert proxy_registry.REGISTRY_PATH.read_text() == torn, ("sync_pool", last_good)


def case_torn_logged_once_per_run() -> None:
    got: list[tuple[int, str]] = []

    class H(logging.Handler):
        def emit(self, r):
            got.append((r.levelno, r.getMessage()))

    h, level = H(), proxy_registry.log.level
    proxy_registry.log.addHandler(h)
    proxy_registry.log.setLevel(logging.INFO)
    try:
        _fresh(json.dumps(GOOD))
        for text in (json.dumps(GOOD), "", "", "{", json.dumps(GOOD), json.dumps(GOOD), "", ""):
            proxy_registry.REGISTRY_PATH.write_text(text)
            proxy_registry.registry()
    finally:
        proxy_registry.log.removeHandler(h)
        proxy_registry.log.setLevel(level)
    assert got == [(logging.WARNING, "proxies_registry_torn fallback=last_good"),
                   (logging.INFO, "proxies_registry_recovered"),
                   (logging.WARNING, "proxies_registry_torn fallback=last_good")], got


def _session(aid: str) -> Path:
    d = TMP / "sessions" / "accounts" / aid
    d.mkdir(parents=True, exist_ok=True)
    p = d / "session_1.json"
    p.write_text(json.dumps({"headers": {"user_id": aid, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                             "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                                   "checksum_indexes": [1], "checksum_constant": 1}},
                             "cookies": [{"name": "sess", "value": "abc", "domain": ".onlyfans.com", "path": "/"}]}))
    return p


def case_from_session_file() -> None:
    sp, su = _session(PROXIED), _session(UNPROXIED)
    _fresh(json.dumps(GOOD))
    proxy_registry.registry()                       # the relay read it whole once
    proxy_registry.REGISTRY_PATH.write_text('{"proxies": [{"lab')
    c = of_client.OFClient.from_session_file(sp)
    assert c.proxy_label == "hu-1" and c.proxy_url, (c.proxy_label, c.proxy_url)
    assert of_client.OFClient.from_session_file(su).proxy_url is None
    _fresh('{"proxies": [{"lab')                    # never read whole: refuse, never direct
    for p in (sp, su):
        try:
            of_client.OFClient.from_session_file(p)
            raise AssertionError("built a client on an unknown egress")
        except proxy_registry.EgressRefused:
            pass
    _fresh(json.dumps(GOOD))
    assert of_client.OFClient.from_session_file(su).proxy_url is None


def case_save_loop_vs_concurrent_load() -> None:
    _fresh(json.dumps(GOOD))
    proxy_registry.registry()
    stop = threading.Event()
    saves = [0]

    def writer() -> None:
        while not stop.is_set():
            proxy_registry.save(GOOD)
            saves[0] += 1

    t = threading.Thread(target=writer, daemon=True)
    torn = [0]
    real = proxy_registry.Torn

    class Counting(real):
        def __init__(self, *a, **k):
            torn[0] += 1
            super().__init__(*a, **k)

    proxy_registry.Torn = Counting
    t.start()
    n, empty, direct, t_end = 0, 0, 0, time.monotonic() + 3.0
    try:
        while time.monotonic() < t_end:
            if not proxy_registry.load().get("proxies"):
                empty += 1
            if not isinstance(egress(proxy_registry.registry(), PROXIED), Proxy):
                direct += 1
            n += 2
    finally:
        stop.set()
        t.join()
        proxy_registry.Torn = real
    print(f"  measured: {n} reads, {torn[0]} torn, {saves[0]} saves, {empty} empty, {direct} not proxied")
    assert n > 1000 and saves[0] > 100, (n, saves)
    assert empty == 0 and direct == 0, (empty, direct)
    assert torn[0] > 0, "no read hit a write: the case proves nothing (rerun)"


_harness.run()
