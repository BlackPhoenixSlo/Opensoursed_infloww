#!/usr/bin/env python3
"""Inflowwww proxy pool: every proxy in `INFLOWW_PROXIES`, seeded into the registry as hidden system
entries, one bound per account (least-used IP) and kept (docs/proxies.md, "Inflowwww proxy pool").

  case_parse_zero_to_three_lines:      empty/blank/None → none; newline or comma separated; labels infloww-<hash>.
  case_parse_bad_and_repeated_lines:   a bad line is an error (password redacted); a repeated proxy counts once.
  case_pool_has_no_cap:                five lines parse and sync as five pool entries, each with its own label.
  case_sync_seeds_and_keeps_custom:    pool entries are `pool: true`, no owner; a custom proxy is untouched;
                                       a password rotation keeps the label and its bindings.
  case_least_used_pick_then_sticky:    assign_pool picks the least-used IP (ties at random), so accounts get IPs
                                       of their own while one is free; two proxies on one verified IP count as
                                       one; a second call keeps the pick; it moves an account off a custom proxy.
  case_switch_reconnects_the_pump:     a write that changes an account's egress (pool assign, pool unbind)
                                       evicts its client and restarts its running WS pump; a kept pick, or an
                                       account with no pump, starts nothing.
  case_evict_waits_for_inflight_build: a client build that read the old route before a proxy write cannot land in
                                       the pool after that write's evict (it would pin the old route).
  case_log_lines_hide_proxy_credentials: _proxy_ip keeps a password holding "@" out of the host:port; the ws error
                                       line never quotes the proxy URL (websockets' InvalidProxy does).
  case_removed_proxy_is_repicked:      a proxy dropped from the env re-binds its accounts to a remaining one;
                                       `none` empties the pool and leaves them with no proxy; assign then raises.
  case_sync_fails_closed:              unset, empty, comment-only or a bad line, while pool entries exist, leaves
                                       the registry byte-identical (bindings kept); `none` is the only clear.
  case_sync_skips_unreadable_registry: a proxies.json that does not parse is never overwritten.
  case_reserved_labels:                a NEW user label of the form infloww-<8 hex> is refused (line paste, POST
                                       /admin/proxies); `pool`, other infloww-* labels, an infloww-* host and
                                       edits to an existing entry still work; sync never adopts a custom proxy.
  case_save_is_in_place:               save keeps the inode and never renames (proxies.json is a single-file
                                       bind mount in Docker, where os.replace fails with EXDEV).
  case_scrub_pool_secrets:             host, host:port, username and password are replaced; no pool → unchanged;
                                       /admin/errors (POST and the unhandled-error middleware) and the
                                       automation run/job records store no pool secret.
  case_pool_errors_are_scrubbed:       curl error text and the /health rows name no pool label or host.
  case_list_hides_pool:                GET /admin/proxies never lists a pool entry (no label, host, password in
                                       the body) and reports {size, account_ids} clamped to the viewer.
  case_generic_routes_refuse_pool:     assign/unbind/test/delete 404, upsert 403, a bulk line 403s per line.
  case_sql_mirror_skips_pool:          db/import_legacy copies custom proxies to SQL, never a pool entry, and
                                       drops a pool row mirrored earlier.
  case_pool_routes:                    POST /admin/proxy-pool/assign + /unbind for the owner; another Agency's
                                       owner and A's chatter are refused, the registry is unchanged; signed out → 401.

The registry is repointed at a temp file; every host and password is fake (`.invalid`).

Run: ./venv/bin/python service/tests/test_proxy_pool.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import proxy_health  # noqa: E402

proxy_registry.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxy_pool_")) / "proxies.json"

IDS = fx.seed_two_agencies()
CREATOR_A, CREATOR_B = IDS["creator_a"], IDS["creator_b"]
account_registry.upsert_account(CREATOR_A, nickname="Pool Creator Alpha")
account_registry.upsert_account(CREATOR_B, nickname="Pool Creator Beta")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")

import server  # noqa: E402

proxy_health.verify_pick = lambda p, **_: True   # a new binding's probe (test_proxy_health covers it): these hosts are fakes

server._invalidate_client = lambda aid=None: None
server._kick_db_sync = lambda reason: None

PW = "pool-secret-pw"
L1 = f"pool-1.invalid:8001:pooluser1:{PW}"
L2 = f"u2:{PW}@pool-2.invalid:8002"
L3 = "socks5://pool-3.invalid:8003"
CUSTOM = {"label": "mine", "host": "custom.invalid", "port": 9000, "user_id": IDS["agency_a_owner"]}


def _reset(text: str | None = None) -> None:
    proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))
    proxy_registry.upsert(dict(CUSTOM))
    if text is not None:
        proxy_registry.sync_pool(text)


def _labels(text: str) -> list[str]:
    return [e["label"] for e in proxy_registry.parse_pool(text)[0]]


def case_parse_zero_to_three_lines():
    for empty in (None, "", "  \n , \n# comment"):
        assert proxy_registry.parse_pool(empty) == ([], []), empty
    one = proxy_registry.parse_pool(L1)[0]
    assert len(one) == 1 and one[0]["host"] == "pool-1.invalid" and one[0]["password"] == PW
    three = _labels(f"{L1}\n{L2},{L3}")
    assert len(three) == 3 and len(set(three)) == 3, three
    assert all(lbl.startswith("infloww-") for lbl in three), three
    # Stable: the same proxy gets the same label, whatever its password or position.
    assert _labels(f"{L3},{L1}") == [three[2], three[0]]
    assert _labels(L1.replace(PW, "rotated")) == [three[0]]


def case_parse_bad_and_repeated_lines():
    entries, errors = proxy_registry.parse_pool(f"{L1},pool-x.invalid:notaport:u:{PW},{L2},{L1},{L3}")
    assert len(entries) == 3, entries   # the repeated L1 counts once
    assert len(errors) == 1 and "port must be a number" in errors[0], errors
    assert PW not in " ".join(errors), "a password leaked into a pool parse message"


def case_pool_has_no_cap():
    five = [f"pool-{i}.invalid:12323:sameuser:{PW}" for i in range(1, 6)]
    labels = _labels("\n".join(five))
    assert len(labels) == 5 and len(set(labels)) == 5, labels
    _reset()
    r = proxy_registry.sync_pool(",".join(five))
    assert r["skipped"] is None and r["size"] == 5 and r["errors"] == [], r
    assert sorted(p["host"] for p in proxy_registry.pool_entries()) == [f"pool-{i}.invalid" for i in range(1, 6)]


def case_sync_seeds_and_keeps_custom():
    _reset(f"{L1},{L2}")
    pool = proxy_registry.pool_entries()
    assert len(pool) == 2 and all(p["pool"] is True and p["user_id"] is None for p in pool), pool
    assert proxy_registry.get_by_label("mine")["host"] == "custom.invalid"
    label = pool[0]["label"]
    proxy_registry.assign_account(label, CREATOR_A)
    r = proxy_registry.sync_pool(f"{L1.replace(PW, 'rotated')},{L2}")
    assert (r["size"], r["errors"], r["rebound"], r["dropped"], r["skipped"]) == (2, [], 0, 0, None), r
    p = proxy_registry.get_by_label(label)
    assert p["password"] == "rotated" and p["assigned_account_ids"] == [CREATOR_A], p
    # Unchanged env: the registry file is not rewritten.
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    proxy_registry.sync_pool(f"{L1.replace(PW, 'rotated')},{L2}")
    assert proxy_registry.REGISTRY_PATH.read_bytes() == before


def case_least_used_pick_then_sticky():
    _reset(f"{L1},{L2},{L3}")
    labels = {p["label"] for p in proxy_registry.pool_entries()}
    # A free pool: ties at random, so 40 seeds reach every proxy.
    picks = set()
    for seed in range(40):
        proxy_registry.unbind_pool(CREATOR_A)
        p, kept = proxy_health.assign_pool(CREATOR_A, random.Random(seed))
        assert not kept and p["label"] in labels
        picks.add(p["label"])
    assert picks == labels, f"40 seeded picks never hit every pool proxy: {picks}"
    first = proxy_registry.get_for_account(CREATOR_A)["label"]
    for seed in range(10):
        p, kept = proxy_health.assign_pool(CREATOR_A, random.Random(seed))
        assert kept and p["label"] == first, "a held pool proxy must be kept"
    # Least-used: three accounts land on three different proxies, whatever the seed.
    for seed in range(10):
        for aid in ("acct-c", "acct-d"):
            proxy_registry.unbind_pool(aid)
        got = {first}
        for aid in ("acct-c", "acct-d"):
            got.add(proxy_health.assign_pool(aid, random.Random(seed))[0]["label"])
        assert got == labels, f"seed {seed}: a free proxy was skipped: {got}"
    # Full pool: the fourth account shares one; the next free slot is the least-used again.
    shared = proxy_health.assign_pool("acct-e")[0]["label"]
    assert shared in labels
    alone = next(a for a in ("acct-c", "acct-d") if proxy_registry.get_for_account(a)["label"] != shared)
    freed = proxy_registry.get_for_account(alone)["label"]
    proxy_registry.unbind_pool(alone)
    for seed in range(10):
        proxy_registry.unbind_pool(alone)
        assert proxy_health.assign_pool(alone, random.Random(seed))[0]["label"] == freed
    for aid in ("acct-c", "acct-d", "acct-e"):
        proxy_registry.unbind_pool(aid)
    # Two pool proxies verified on one IP count as one: the next pick takes the other IP.
    a, b, c = sorted(labels)
    for lbl in (a, b):
        proxy_registry.record_verification(lbl, ip="203.0.113.9", geo=None, ok=True)
    proxy_registry.unbind_pool(CREATOR_A)
    proxy_registry.assign_account(a, CREATOR_A)
    for seed in range(10):
        proxy_registry.unbind_pool("acct-c")
        assert proxy_health.assign_pool("acct-c", random.Random(seed))[0]["label"] == c
    proxy_registry.unbind_pool("acct-c")
    # From a custom proxy: moved onto the pool, off the custom one.
    proxy_registry.assign_account("mine", CREATOR_B)
    p, kept = proxy_health.assign_pool(CREATOR_B)
    assert not kept and proxy_registry.is_pool(proxy_registry.get_for_account(CREATOR_B))
    assert CREATOR_B not in proxy_registry.get_by_label("mine")["assigned_account_ids"]
    assert proxy_registry.unbind_pool(CREATOR_B) and proxy_registry.get_for_account(CREATOR_B) is None
    assert not proxy_registry.unbind_pool(CREATOR_B)


def case_switch_reconnects_the_pump():
    _reset(f"{L1},{L2}")
    evicted: list = []
    started: list[str] = []

    async def fake_pump(aid: str) -> None:
        started.append(aid)
        await asyncio.sleep(3600)

    async def run() -> None:
        old_task = asyncio.create_task(fake_pump(CREATOR_A))
        server._account_pumps[CREATOR_A] = old_task
        await asyncio.sleep(0.01)
        started.clear()

        proxy_health.assign_pool(CREATOR_A)            # direct → pool
        await asyncio.sleep(0.01)
        assert old_task.cancelled(), "the old socket must be torn down"
        assert started == [CREATOR_A], started
        assert evicted == [CREATOR_A], evicted

        started.clear()
        evicted.clear()
        _, kept = proxy_health.assign_pool(CREATOR_A)  # kept: nothing changes
        await asyncio.sleep(0.01)
        assert kept and started == [] and evicted == []

        assert proxy_registry.unbind_pool(CREATOR_A)     # pool → No proxy (server IP)
        await asyncio.sleep(0.01)
        assert started == [CREATOR_A] and evicted == [CREATOR_A], (started, evicted)

        started.clear()
        evicted.clear()
        proxy_health.assign_pool(CREATOR_B)            # no pump: evicted, none started
        await asyncio.sleep(0.01)
        assert started == [] and evicted == [CREATOR_B], (started, evicted)
        assert CREATOR_B not in server._account_pumps

    real_pump, real_evict = server._ws_pump_for_account, server._invalidate_client
    server._ws_pump_for_account = fake_pump
    server._invalidate_client = lambda aid=None: evicted.append(aid)
    try:
        asyncio.run(run())
    finally:
        server._ws_pump_for_account, server._invalidate_client = real_pump, real_evict
        server._account_pumps.clear()
        proxy_registry.unbind_pool(CREATOR_B)


def case_evict_waits_for_inflight_build():
    import threading
    import client_pool
    reading, release = threading.Event(), threading.Event()

    class _Slow:
        user_id = x_of_rev = None

        @classmethod
        def from_account(cls, aid):
            reading.set()          # has read proxies.json: the OLD route
            release.wait(5)
            return cls()

    real, client_pool.OFClient = client_pool.OFClient, _Slow  # type: ignore[assignment]
    try:
        client_pool.evict()
        builder = threading.Thread(target=client_pool.get, args=("acc_race",))
        builder.start()
        assert reading.wait(5)
        evictor = threading.Thread(target=client_pool.evict, args=("acc_race",))
        evictor.start()            # the proxy write's evict, mid-build
        evictor.join(0.05)
        release.set()
        builder.join(5)
        evictor.join(5)
        assert "acc_race" not in client_pool._POOL, "a client built on the old route outlived the evict"
    finally:
        release.set()
        client_pool.OFClient = real  # type: ignore[assignment]
        client_pool.evict()


def case_log_lines_hide_proxy_credentials():
    import logging
    from of_client import OFClient
    from of_ws import OFWebSocket
    secret = "p@ss/w#rd"
    c = OFClient.__new__(OFClient)
    c.account_id, c.proxy_label = "acc_log", "mine"
    c.proxy_url = f"http://user:{secret}@custom.invalid:9000"
    c.me = lambda: {"wsUrl": "wss://ws.invalid/ws3/1", "wsAuthToken": "t"}
    c.user_agent = "ua"
    assert c._proxy_ip() == "custom.invalid:9000", c._proxy_ip()

    ws = OFWebSocket(c)
    lines: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
            ws.stop()

    h = _H(level=logging.WARNING)
    logging.getLogger("of-ws").addHandler(h)

    async def go():
        async for _ in ws.events():
            pass
    try:
        asyncio.run(asyncio.wait_for(go(), 10))
    finally:
        logging.getLogger("of-ws").removeHandler(h)
    assert lines and "ws error account=acc_log" in lines[0], lines
    assert "mine(custom.invalid:9000)" in lines[0], lines
    for leak in (secret, "w#rd", "user:"):
        assert leak not in lines[0], lines[0]


def case_removed_proxy_is_repicked():
    _reset(f"{L1},{L2}")
    gone, stay = (e["label"] for e in proxy_registry.parse_pool(f"{L1},{L2}")[0])
    proxy_registry.assign_account(gone, CREATOR_A)
    r = proxy_registry.sync_pool(L2)
    assert r["rebound"] == 1 and r["dropped"] == 0, r
    assert proxy_registry.get_by_label(gone) is None
    assert proxy_registry.get_for_account(CREATOR_A)["label"] == stay
    r = proxy_registry.sync_pool("none")
    assert (r["size"], r["rebound"], r["dropped"], r["changed"]) == (0, 0, 1, True), r
    assert proxy_registry.get_for_account(CREATOR_A) is None
    assert proxy_registry.get_by_label("mine") is not None, "an empty pool must not touch custom proxies"
    try:
        proxy_health.assign_pool(CREATOR_A)
    except LookupError:
        pass
    else:
        raise AssertionError("an empty pool must raise")


def case_list_hides_pool():
    _reset(f"{L1},{L2},{L3}")
    proxy_health.assign_pool(CREATOR_A)
    proxy_health.assign_pool(CREATOR_B)
    pool_labels = [p["label"] for p in proxy_registry.pool_entries()]
    for client, mine in ((OWNER_A, CREATOR_A), (OWNER_B, CREATOR_B)):
        r = client.get("/admin/proxies")
        assert r.status_code == 200, r.text
        body = r.json()
        for needle in [*pool_labels, "pool-1.invalid", "pool-2.invalid", "pool-3.invalid", PW]:
            assert needle not in r.text, f"pool field {needle!r} leaked into GET /admin/proxies"
        assert body["pool"] == {"size": 3, "account_ids": [mine], "bad": 0}, body["pool"]
    assert "mine" in {p["label"] for p in OWNER_A.get("/admin/proxies").json()["proxies"]}


def case_generic_routes_refuse_pool():
    _reset(L1)
    label = proxy_registry.pool_entries()[0]["label"]
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    for client in (OWNER_A,):
        assert client.post("/admin/proxies/assign", json={"label": label, "account_id": CREATOR_A}).status_code == 404
        assert client.post(f"/admin/proxies/{label}/unbind", json={"account_id": CREATOR_A}).status_code == 404
        assert client.post(f"/admin/proxies/{label}/test").status_code == 404
        assert client.delete(f"/admin/proxies/{label}").status_code == 404
        r = client.post("/admin/proxies", json={"label": label, "host": "evil.invalid", "port": 1})
        assert r.status_code == 403, r.text
        r = client.post("/admin/proxies/bulk", json={"text": f"evil.invalid:1 {label}"})
        assert r.status_code == 200 and r.json()["added"] == [], r.text
        assert r.json()["errors"][0]["reason"] == "Inflowwww proxy is read-only", r.text
    assert proxy_registry.REGISTRY_PATH.read_bytes() == before, "a generic route wrote a pool entry"


def case_pool_routes():
    _reset(f"{L1},{L2}")
    r = OWNER_A.post("/admin/proxy-pool/assign", json={"account_id": CREATOR_A})
    assert r.status_code == 200 and r.json() == {"ok": True, "kept": False}, r.text
    assert PW not in r.text and "invalid" not in r.text
    held = proxy_registry.get_for_account(CREATOR_A)["label"]
    r = OWNER_A.post("/admin/proxy-pool/assign", json={"account_id": CREATOR_A})
    assert r.json() == {"ok": True, "kept": True} and proxy_registry.get_for_account(CREATOR_A)["label"] == held
    # Another Agency's owner can neither move nor drop A's Creator.
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    for path in ("/admin/proxy-pool/assign", "/admin/proxy-pool/unbind"):
        r = OWNER_B.post(path, json={"account_id": CREATOR_A})
        assert r.status_code in (403, 404), f"{path}: {r.status_code} {r.text}"
    assert proxy_registry.REGISTRY_PATH.read_bytes() == before
    from fastapi.testclient import TestClient
    anon = TestClient(server.app)
    assert anon.post("/admin/proxy-pool/assign", json={"account_id": CREATOR_A}).status_code == 401
    # Owner-only, like /admin/proxies: A's own chatter is refused too.
    chatter = fx.login_chatter("chatter_a")
    for path in ("/admin/proxy-pool/assign", "/admin/proxy-pool/unbind"):
        r = chatter.post(path, json={"account_id": CREATOR_A})
        assert r.status_code in (401, 403), f"chatter on {path}: {r.status_code} {r.text}"
    assert proxy_registry.REGISTRY_PATH.read_bytes() == before
    r = OWNER_A.post("/admin/proxy-pool/unbind", json={"account_id": CREATOR_A})
    assert r.json() == {"ok": True, "removed": True} and proxy_registry.get_for_account(CREATOR_A) is None
    proxy_registry.sync_pool("none")
    r = OWNER_A.post("/admin/proxy-pool/assign", json={"account_id": CREATOR_A})
    assert r.status_code == 409, r.text


def case_sync_fails_closed():
    _reset(f"{L1},{L2}")
    proxy_health.assign_pool(CREATOR_A)
    held = proxy_registry.get_for_account(CREATOR_A)["label"]
    before = proxy_registry.REGISTRY_PATH.read_bytes()
    for text in (None, "", "   ", "  \n , \n# comment", f"{L1},pool-x.invalid:notaport:u:{PW}"):
        r = proxy_registry.sync_pool(text)
        assert r["skipped"] and r["size"] == 2 and not r["changed"], (text, r)
        assert proxy_registry.REGISTRY_PATH.read_bytes() == before, f"sync rewrote the registry for {text!r}"
        assert proxy_registry.get_for_account(CREATOR_A)["label"] == held
    assert PW not in " ".join(r["errors"])
    # A valid, different set still drops and re-picks (see case_removed_proxy_is_repicked);
    # only `none` (any case) clears the pool.
    r = proxy_registry.sync_pool(" NONE ")
    assert r["skipped"] is None and r["size"] == 0 and r["dropped"] == 1, r
    assert proxy_registry.pool_entries() == [] and proxy_registry.get_for_account(CREATOR_A) is None
    assert proxy_registry.get_by_label("mine") is not None
    # No pool yet: an empty env is a plain no-op, and good lines next to a bad one are seeded.
    assert proxy_registry.sync_pool("")["changed"] is False
    r = proxy_registry.sync_pool(f"{L1},pool-x.invalid:notaport")
    assert r["size"] == 1 and len(r["errors"]) == 1 and r["skipped"] is None, r


def case_sync_skips_unreadable_registry():
    for junk in ("{not json", "[]", '{"other": 1}'):
        proxy_registry.REGISTRY_PATH.write_text(junk)
        r = proxy_registry.sync_pool(L1)
        assert r["skipped"] == "registry unreadable", r
        assert proxy_registry.REGISTRY_PATH.read_text() == junk, f"sync overwrote an unreadable registry ({junk!r})"


def case_reserved_labels():
    _reset()
    generated = "infloww-deadbeef"
    try:
        proxy_registry.upsert_from_line(f"evil.invalid:1 {generated}")
    except ValueError as e:
        assert "reserved" in str(e), e
    else:
        raise AssertionError("a new infloww-<8 hex> label was accepted")
    r = OWNER_A.post("/admin/proxies", json={"label": generated, "host": "evil.invalid", "port": 1})
    assert r.status_code == 400, r.text
    assert proxy_registry.get_by_label(generated) is None
    # Not the generated form: accepted, including `pool` (the pool routes live under /admin/proxy-pool).
    for label in ("pool", "infloww-mine", "Infloww-DEADBEEF"):
        assert proxy_registry.upsert_from_line(f"ok.invalid:1 {label}")["label"] == label
    r = OWNER_A.post("/admin/proxies", json={"label": "pool2", "host": "ok.invalid", "port": 2})
    assert r.status_code == 200, r.text
    assert proxy_registry.upsert_from_line("infloww-host.invalid:1")["label"] == "infloww-host.invalid:1"
    # An existing non-pool entry with the generated form (written before the rule) can still be edited.
    data = proxy_registry.load()
    data["proxies"].append({"label": generated, "host": "old.invalid", "port": 1, "user_id": IDS["agency_a_owner"]})
    proxy_registry.save(data)
    assert proxy_registry.upsert_from_line(f"new.invalid:2 {generated}")["host"] == "new.invalid"
    r = OWNER_A.post("/admin/proxies", json={"label": generated, "host": "newer.invalid", "port": 3})
    assert r.status_code == 200 and proxy_registry.get_by_label(generated)["host"] == "newer.invalid", r.text
    # A custom entry that already holds a pool label is never adopted by the sync.
    label = _labels(L1)[0]
    data = proxy_registry.load()
    data["proxies"].append({"label": label, "host": "theirs.invalid", "port": 1, "user_id": IDS["agency_a_owner"],
                            "assigned_account_ids": [CREATOR_B]})
    proxy_registry.save(data)
    r = proxy_registry.sync_pool(L1)
    held = proxy_registry.get_by_label(label)
    assert not proxy_registry.is_pool(held) and held["host"] == "theirs.invalid", held
    assert r["size"] == 0 and proxy_registry.pool_entries() == [], r


def case_save_is_in_place():
    _reset(L1)
    path = proxy_registry.REGISTRY_PATH
    inode = path.stat().st_ino
    import errno
    import os

    def _exdev(*a, **k):
        raise OSError(errno.EXDEV, "Invalid cross-device link")
    old_replace, old_rename = os.replace, os.rename
    os.replace = os.rename = _exdev
    try:
        proxy_registry.upsert({"label": "after", "host": "after.invalid", "port": 1})
        proxy_registry.sync_pool(f"{L1},{L2}")
    finally:
        os.replace, os.rename = old_replace, old_rename
    assert path.stat().st_ino == inode, "save replaced the file instead of writing it in place"
    assert proxy_registry.get_by_label("after") is not None and len(proxy_registry.pool_entries()) == 2
    assert [f.name for f in path.parent.iterdir()] == ["proxies.json"]


def case_pool_errors_are_scrubbed():
    _reset(L1)
    proxy_health.assign_pool(CREATOR_A)
    proxy_registry.assign_account("mine", CREATOR_B)
    label = proxy_registry.get_for_account(CREATOR_A)["label"]
    host = proxy_registry.get_for_account(CREATOR_A)["host"]
    raw = f"Failed to connect to {host} port 8001"
    assert server._pool_safe_error(CREATOR_A, raw) == server.POOL_PROXY_ERROR
    assert server._pool_safe_error(None, raw, label=label) == server.POOL_PROXY_ERROR
    custom = "Failed to connect to custom.invalid port 9000"
    assert server._pool_safe_error(CREATOR_B, custom) == custom, "custom-proxy text must be unchanged"
    assert server._pool_safe_error(None, custom) == custom
    # Unknown account, pool host in the text: still scrubbed.
    assert "pool-1.invalid" not in server._pool_safe_error(None, raw)

    class _C:
        def __init__(self, aid, fail):
            self.account_id, self.fail = aid, fail
            p = proxy_registry.get_for_account(aid)
            self.proxy_label, self.proxy_url = p["label"], proxy_registry.proxy_url(p)

        def me(self):
            if self.fail:
                raise OSError(raw if proxy_registry.is_pool(proxy_registry.get_for_account(self.account_id)) else custom)
            return {"id": 1, "name": "x"}

    old = server._load_client
    try:
        server._load_client = lambda aid: _C(aid, fail=False)
        row = server._probe_account_blocking(CREATOR_A)
        assert row["proxy"] == {"pool": True}, row
        assert server._probe_account_blocking(CREATOR_B)["proxy"]["label"] == "mine"
        server._load_client = lambda aid: _C(aid, fail=True)
        row = server._probe_account_blocking(CREATOR_A)
        assert row["error"] == server.POOL_PROXY_ERROR and host not in json.dumps(row), row
        assert server._probe_account_blocking(CREATOR_B)["error"] == f"OSError: {custom}", "custom text kept"
    finally:
        server._load_client = old


def case_scrub_pool_secrets():
    _reset("none")
    text = f"proxy http://pooluser1:{PW}@pool-1.invalid:8001 failed"
    assert proxy_registry.scrub_pool_secrets(text) is text, "no pool: text must come back unchanged"
    assert proxy_registry.scrub_pool_secrets(None) is None
    _reset(L1)
    out = proxy_registry.scrub_pool_secrets(text)
    for secret in ("pool-1.invalid", "pooluser1", PW, "8001"):
        assert secret not in out, (secret, out)
    assert proxy_registry.POOL_PLACEHOLDER in out and "custom.invalid" == proxy_registry.scrub_pool_secrets("custom.invalid")

    # POST /admin/errors and the unhandled-error middleware feed GET /admin/errors (not tenant-filtered).
    r = OWNER_A.post("/admin/errors", json={"message": text, "stack": text, "url": "http://x/", "context": {"e": text}})
    assert r.status_code == 200 and r.json()["ok"], r.text

    @server.app.get("/api/test-pool-boom")
    def _boom():
        raise RuntimeError(text)
    from fastapi.testclient import TestClient
    boom = TestClient(server.app, raise_server_exceptions=False, cookies=OWNER_A.cookies)
    boom.get("/api/test-pool-boom")
    listed = OWNER_A.get("/admin/errors", params={"limit": 50}).text
    assert "test-pool-boom" in listed and "/x/" in listed, listed[:500]
    # A browser error whose context is over the stored cap (a long component stack)
    # stays listable: the stored context is valid JSON, and a row cut off before
    # that (raw slice of the JSON text) is served as text, never a 500.
    big = OWNER_A.post("/admin/errors", json={"message": "big-context", "context": {"stack": "y" * 40000}})
    assert big.status_code == 200 and big.json()["ok"], big.text
    import asyncio
    from db.engine import get_session
    from db.models import AppError as _AE
    async def _legacy_row():
        async with get_session() as s:
            s.add(_AE(source="browser", kind="error", message="legacy-cut-context",
                      context_json=json.dumps({"stack": "z" * 100})[:40]))
    asyncio.run(_legacy_row())
    got = OWNER_A.get("/admin/errors", params={"limit": 50})
    assert got.status_code == 200, got.text[:500]
    rows = {r["message"]: r for r in got.json()["list"]}
    assert set(rows["big-context"]["context"]) == {"truncated"}, rows["big-context"]["context"].keys()
    assert rows["legacy-cut-context"]["context"] == {"unparsed": json.dumps({"stack": "z" * 100})[:40]}

    for secret in ("pool-1.invalid", PW):
        assert secret not in listed, f"{secret!r} served by /admin/errors"

    # Automation run + job records (the executor's one write path for repr(e) in stats and errors).
    import asyncio
    import automation_executor as ax
    from db.engine import get_session
    from db.models import AutomationRun, ScheduledJob

    async def _go():
        rid = await ax._open_run(CREATOR_A, "send_mass_message")
        await ax._finalize_run(rid, "ok", {"skipped": "error", "error": repr(OSError(text))}, text)
        jid = await ax.enqueue_job(CREATOR_A, "send_mass_message", payload={})
        await ax._mark_job_failure(jid, text)
        async with get_session() as s:
            run = await s.get(AutomationRun, rid)
            job = await s.get(ScheduledJob, jid)
            return run.stats_json + run.error_text + job.last_error
    stored = asyncio.run(_go())
    assert proxy_registry.POOL_PLACEHOLDER in stored
    for secret in ("pool-1.invalid", PW):
        assert secret not in stored, f"{secret!r} persisted in an automation record"



def case_sql_mirror_skips_pool():
    import os
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from service.db import import_legacy as il
    _reset(L1)
    pool_label = proxy_registry.pool_entries()[0]["label"]
    il.PROXIES_FILE = proxy_registry.REGISTRY_PATH
    eng = create_engine(os.environ["CHATTERLY_DB_URL"])
    try:
        with Session(eng) as s:
            s.add(il.Proxy(label=pool_label, scheme="http", host="pool-1.invalid", port=8001, password_encrypted=PW))
            s.commit()
            n = il.import_proxies(s, dry_run=False)
            s.commit()
            labels = set(s.scalars(select(il.Proxy.label)).all())
    finally:
        eng.dispose()
    assert n == 1 and "mine" in labels and pool_label not in labels, (n, labels)


_harness.run()
