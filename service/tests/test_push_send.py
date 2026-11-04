#!/usr/bin/env python3
"""push_send end to end in-process: frames enter through events.broadcast / _fanout (the real
publish path), the push service is an httpx.MockTransport (its wire boundary), keys are real ECDH,
sessions are real logins. Pins: one push per notice, a re-offered purchase pushes once, push_sent
survives a restart, 404/410 prune, 403 kept + counted, retry without a sleeping worker, dead
session prunes, send-time re-check (types off, revoked), unassigned chatter / no-session /
deactivated Creator get nothing, order kept per sub under jitter, a stalled push service never
blocks _fanout (inbox drops oldest), the payload decrypts to {v:1,tag,...}, /push/test reasons,
a failed send un-claims its tag (503 x3 then the re-offer pushes once), only purchase tags persist,
the scope cache's generation guard, a no-longer-allowed endpoint pruned on start, the VAPID raw-key
env path, the JWT cache refresh, the worst-case payload under 4 KB. The client is real httpx with
the transport patched in (no hook in service/).
Run: venv/bin/python -m pytest service/tests/test_push_send.py -q"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # pytest: tests/ is a package
import _harness  # noqa: E402  (first: temp DB)

import asyncio  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from unittest import mock  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

os.environ.setdefault("VAPID_SUBJECT", "mailto:push-test@example.com")

import http_ece  # noqa: E402
import httpx  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from sqlalchemy import delete, select, update  # noqa: E402

_harness.bootstrap()
import _agency_fixtures as fx  # noqa: E402
import account_health  # noqa: E402
import accounts as registry  # noqa: E402
import auth  # noqa: E402
import chatter_identity_cache  # noqa: E402
import chatters  # noqa: E402
import events  # noqa: E402
import push_decide as pd  # noqa: E402
import push_notice as pn  # noqa: E402
import push_scope  # noqa: E402
import push_send  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import ChatterUser, PushSent, PushSubscription, User  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
for _aid in (A, B):
    registry.save_meta(_aid, {"id": _aid, "nickname": f"c{_aid}", "platform": "onlyfans"})
    (registry.ACCOUNTS_DIR / _aid / "latest.json").write_text("{}")   # a captured session
OWNER_A = fx.login_owner("agency_a_owner")
CHATTER_A = fx.login_chatter("chatter_a")
CHATTER_B = fx.login_chatter("chatter_b")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Browser:
    """One subscription's client half: its ECDH key + auth secret, and what it received."""
    def __init__(self, client, kind="user", types=("purchases", "tip", "message")):
        self.priv = ec.generate_private_key(ec.SECP256R1())
        self.auth = secrets.token_bytes(16)
        self.id = uuid.uuid4().hex
        self.endpoint = f"https://fcm.googleapis.com/fcm/send/{self.id}"
        name = auth.COOKIE_NAME if kind == "user" else chatters.COOKIE_NAME
        parse = auth.parse_cookie_issued if kind == "user" else chatters.parse_cookie_issued
        pid, issued = parse(client.cookies.get(name))
        pub = self.priv.public_key().public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint)
        self.row = PushSubscription(id=self.id, endpoint=self.endpoint, p256dh=_b64(pub), auth=_b64(self.auth),
                                    principal_kind=kind, principal_id=pid, issued_ms=issued,
                                    types=json.dumps(sorted(types)), platforms="{}")
        self.got: list[dict] = []

    def decrypt(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.priv, auth_secret=self.auth, version="aes128gcm"))


class PushService:
    """The fake push service (MockTransport): routes by endpoint, answers `status(browser, n)`."""
    def __init__(self, browsers, status=lambda b, n: 201, delay=None):
        self.by_ep = {b.endpoint: b for b in browsers}
        self.status, self.delay, self.reqs, self.n = status, delay, [], 0

    async def __call__(self, req: httpx.Request) -> httpx.Response:
        self.n += 1
        n = self.n
        if self.delay:
            await self.delay(n)
        b = self.by_ep[str(req.url)]
        self.reqs.append(req)
        st = self.status(b, n)
        if 200 <= st < 300:
            b.got.append(b.decrypt(req.content))
        return httpx.Response(st)


async def _db(stmt):
    async with get_session() as s:
        r = await s.execute(stmt)
        return r.scalars().all() if hasattr(stmt, "column_descriptions") and stmt.is_select else None


async def _start(svc) -> None:
    """push_send.start() with the fake push service as its httpx transport."""
    real = httpx.AsyncClient
    with mock.patch.object(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(svc), **kw)):
        await push_send.start()


async def _boot(browsers, svc) -> None:
    await push_send.stop()
    push_scope.clear()
    push_send._platforms.clear()
    push_send._n.clear()
    push_send._lat_ms.clear()
    push_send._disabled = None
    async with get_session() as s:
        await s.execute(delete(PushSent))
        await s.execute(delete(PushSubscription))
        for b in browsers:
            s.add(b.row)
    await _start(svc)
    assert push_send.disabled() is None


async def _settle(cond=lambda: False, t=3.0) -> None:
    """Wait until `cond()` or the pipeline is idle for 0.15 s."""
    end, idle = time.monotonic() + t, 0
    while time.monotonic() < end:
        if cond():
            return
        busy = push_send._inbox.qsize() + sum(q.qsize() for q in push_send._workers) + len(push_send._retries)
        idle = idle + 1 if busy == 0 else 0
        if idle >= 15:
            return
        await asyncio.sleep(0.01)


def purchase(nid, aid=A, fan=4242, cents=1500):
    return {"purchase_notified": {"notif_id": str(nid), "fan_id": fan, "message_id": 1, "amount_cents": cents,
                                  "created_at": None, "name": "Tom"}, "__account_id": aid}


def dm(mid, aid=A, tip=False, fan=4242):
    m = {"id": mid, "fromUser": {"id": fan, "name": "Tom"}, "toUser": {"id": int(aid)}, "text": f"msg {mid}"}
    if tip:
        m.update(isTip=True, tipAmount=5)
    return {"api2_chat_message": m, "__account_id": aid}


def test_one_push_per_notice_headers_and_payload():
    async def go():
        b = Browser(OWNER_A)
        svc = PushService([b])
        await _boot([b], svc)
        for _ in range(3):
            await events.broadcast(purchase(9001))          # the 2 h purchase re-offer
        await events.broadcast(dm(777, tip=True))
        await events.broadcast(purchase(9002, aid=B))       # not owner A's Creator
        await events.broadcast({"chat_responded": {}, "__account_id": A})
        await _settle()
        assert [p["tag"] for p in b.got] == [f"{A}:9001", f"{A}:m777"], b.got
        assert b.got[0] == pn.payload(pn.notices_for(purchase(9001))[0])
        assert b.got[1]["type"] == "tip" and b.got[1]["body"] == "Tipped you $5"
        h = svc.reqs[0].headers
        assert h["ttl"] == "14400" and h["urgency"] == "high" and h["content-encoding"] == "aes128gcm"
        assert h["authorization"].startswith("vapid t=") and f"k={push_send.public_key()}" in h["authorization"]
        sent = await _db(select(PushSent.tag).where(PushSent.sub_id == b.id))
        assert sent == [f"{A}:9001"], "only the purchase lane (re-walked on restart) persists"
        st = push_send.stats()
        assert st["sent"] == 2 and st["p95_ms"] is not None and events.sse_stats()["push"]["sent"] == 2
        await push_send.stop()
    asyncio.run(go())


def test_push_sent_survives_restart():
    async def go():
        b = Browser(OWNER_A)
        svc = PushService([b])
        await _boot([b], svc)
        await events.broadcast(purchase(9100))
        await _settle()
        await push_send.stop()
        await _start(svc)   # restart, same DB
        assert push_send._subs[b.id].seen.has(f"{A}:9100", time.monotonic())
        await events.broadcast(purchase(9100))      # the feed re-walk after a restart
        await events.broadcast(purchase(9101))
        await _settle()
        assert [p["tag"] for p in b.got] == [f"{A}:9100", f"{A}:9101"], b.got
        async with get_session() as s:                # rows past 24 h are pruned on start
            await s.execute(update(PushSent).values(sent_at=datetime.utcnow() - timedelta(hours=25)))
        await push_send.stop()
        await _start(svc)
        assert await _db(select(PushSent)) == []
        await push_send.stop()
    asyncio.run(go())


def test_gone_prunes_forbidden_kept():
    async def go():
        g410, g404, f403 = Browser(OWNER_A), Browser(OWNER_A), Browser(OWNER_A)
        code = {g410.id: 410, g404.id: 404, f403.id: 403}
        svc = PushService([g410, g404, f403], status=lambda b, n: code[b.id])
        await _boot([g410, g404, f403], svc)
        await events.broadcast(purchase(9200))
        await _settle()
        left = await _db(select(PushSubscription.id))
        assert left == [f403.id] and set(push_send._subs) == {f403.id}
        st = push_send.stats()
        assert (st["pruned"], st["failed"], st["forbidden"]) == (2, 1, 1), st
        await push_send.stop()
    asyncio.run(go())


def test_retry_is_a_task_not_a_sleeping_worker():
    async def go():
        old = pd.RETRY_DELAYS_S
        pd.RETRY_DELAYS_S = (0.3, 0.3)
        try:
            flaky, ok = Browser(OWNER_A), Browser(OWNER_A)
            svc = PushService([flaky, ok], status=lambda b, n: 503 if b is flaky and len(flaky.got) == 0
                              and sum(r.url == flaky.endpoint for r in svc.reqs) == 1 else 201)
            # every sub on ONE worker: a sleeping retry would hold `ok` back
            push_send.N_WORKERS, n_old = 1, push_send.N_WORKERS
            await _boot([flaky, ok], svc)
            await events.broadcast(purchase(9300))
            await _settle(lambda: len(ok.got) == 1, 0.25)
            assert len(ok.got) == 1, "the worker did not wait on flaky's retry"
            await _settle(lambda: len(flaky.got) == 1)
            assert len(flaky.got) == 1 and push_send.stats()["retries"] == 1
        finally:
            pd.RETRY_DELAYS_S = old
            push_send.N_WORKERS = n_old
            await push_send.stop()
    asyncio.run(go())


def test_dead_session_prunes():
    async def go():
        b = Browser(OWNER_A)
        svc = PushService([b])
        await _boot([b], svc)
        async with get_session() as s:
            await s.execute(update(User).where(User.id == IDS["agency_a_owner"])
                            .values(sessions_valid_after=datetime.utcnow() + timedelta(seconds=5)))
        await events.broadcast({"sessions_revoked": {}, "__account_id": A})   # clears the scope cache
        await events.broadcast(purchase(9400))
        await _settle()
        assert b.got == [] and b.id not in push_send._subs and await _db(select(PushSubscription)) == []
        async with get_session() as s:
            await s.execute(update(User).where(User.id == IDS["agency_a_owner"]).values(sessions_valid_after=None))
        await push_send.stop()
    asyncio.run(go())


def test_send_time_recheck():
    async def go():
        gate = asyncio.Event()

        async def hold(n):
            if n == 1:
                await gate.wait()
        b = Browser(OWNER_A)
        svc = PushService([b], delay=hold)
        await _boot([b], svc)
        await events.broadcast(dm(1))      # in flight, held
        await events.broadcast(dm(2))      # queued behind it on the same worker
        await events.broadcast(purchase(9500))
        await _settle(lambda: svc.n == 1)
        cur = push_send._subs[b.id]
        push_send.upsert(push_send.Sub(cur.id, cur.endpoint, cur.p256dh, cur.auth, cur.kind, cur.principal_id,
                                       cur.issued_ms, frozenset({"purchases"}), {}))   # PUT: messages off
        gate.set()
        await _settle()
        assert [p["tag"] for p in b.got] == [f"{A}:m1", f"{A}:9500"], b.got
        assert push_send.stats()["skipped"] == 1
        await push_send.stop()
    asyncio.run(go())


def test_chatter_scope_and_unassign():
    async def go():
        ca, cb = Browser(CHATTER_A, "chatter"), Browser(CHATTER_B, "chatter")
        svc = PushService([ca, cb])
        await _boot([ca, cb], svc)
        await events.broadcast(purchase(9600))
        await _settle()
        assert [p["tag"] for p in ca.got] == [f"{A}:9600"] and cb.got == []
        async with get_session() as s:      # owner A unlinks chatter_a
            await s.execute(delete(ChatterUser).where(ChatterUser.chatter_id == IDS["chatter_a"]))
        chatter_identity_cache.invalidate()
        await events.broadcast({"assignment_changed": {}, "__agency": IDS["agency_a_owner"]})
        await events.broadcast(purchase(9601))
        await _settle()
        assert len(ca.got) == 1 and ca.id in push_send._subs, "no push, but the session lives"
        async with get_session() as s:
            s.add(ChatterUser(chatter_id=IDS["chatter_a"], user_id=IDS["agency_a_owner"], created_at=datetime.utcnow()))
        chatter_identity_cache.invalidate()
        await push_send.stop()
    asyncio.run(go())


def test_live_account_filter():
    async def go():
        b = Browser(OWNER_A)
        svc = PushService([b])
        latest = registry.ACCOUNTS_DIR / A / "latest.json"
        latest.unlink()
        try:
            await _boot([b], svc)
            await events.broadcast(purchase(9700))
            await _settle()
            assert b.got == [], "no captured session: not a live Creator"
        finally:
            latest.write_text("{}")
        assert await account_health.deactivate(A)
        push_scope.clear()
        await events.broadcast(purchase(9701))
        await _settle()
        assert b.got == [], "deactivated"
        await account_health.activate(A)
        push_scope.clear()
        await events.broadcast(purchase(9702))
        await _settle()
        assert [p["tag"] for p in b.got] == [f"{A}:9702"], "live again"
        await push_send.stop()
    asyncio.run(go())


def test_order_kept_per_sub_under_jitter():
    async def go():
        rnd = random.Random(7)

        async def jitter(n):
            await asyncio.sleep(rnd.random() * 0.004)
        bs = [Browser(OWNER_A, types=("message",)) for _ in range(6)]
        svc = PushService(bs, delay=jitter)
        await _boot(bs, svc)
        assert len({pd.shard(b.id, push_send.N_WORKERS) for b in bs}) > 1
        for i in range(40):
            await events.broadcast(dm(1000 + i))
        await _settle(lambda: all(len(b.got) == 40 for b in bs), 10)
        want = [f"{A}:m{1000 + i}" for i in range(40)]
        assert all([p["tag"] for p in b.got] == want for b in bs), [(len(b.got), [p["tag"][-4:] for p in b.got][:12]) for b in bs]
        await push_send.stop()
    asyncio.run(go())


def test_stalled_push_service_never_blocks_fanout():
    async def go():
        stall = asyncio.Event()

        async def hang(n):
            await stall.wait()
        b = Browser(OWNER_A, types=("message",))
        await _boot([b], PushService([b], delay=hang))
        N = push_send.INBOX_MAX + 5000
        frames = [dm(50_000 + i) for i in range(N)]
        t = time.perf_counter()
        for f in frames:
            events._fanout(f)                 # no await between: the inbox fills
        dt = time.perf_counter() - t
        assert push_send.stats()["dropped"] == 5000 and push_send._inbox.qsize() == push_send.INBOX_MAX
        assert dt < 5.0, f"{N} fan-outs took {dt:.2f}s"
        await push_send.stop()               # cancels the hung POST
        return dt
    asyncio.run(go())


def test_send_test_reasons():
    async def go():
        b = Browser(OWNER_A)
        codes = iter([201, 403, 410])
        svc = PushService([b], status=lambda _b, n: next(codes))
        await _boot([b], svc)
        assert await push_send.send_test(b.id, 0) == {"status": 201, "reason": "accepted"}
        assert b.got[0]["type"] == "test" and b.got[0]["href"] == "/" and "account_id" not in b.got[0]
        r = await push_send.send_test(b.id, 0)
        assert r["status"] == 403 and "VAPID" in r["reason"] and push_send.stats()["forbidden"] == 1
        r = await push_send.send_test(b.id, 0)
        assert r["status"] == 410 and b.id not in push_send._subs
        assert (await push_send.send_test(b.id, 0))["reason"] == "subscription gone"
        await push_send.stop()
    asyncio.run(go())


def test_failed_send_unclaims_tag():
    """503 x3 (retries exhausted): the tag is not left claimed, so the 2 h re-offer pushes once."""
    async def go():
        old = pd.RETRY_DELAYS_S
        pd.RETRY_DELAYS_S = (0.05, 0.05)
        try:
            b = Browser(OWNER_A)
            svc = PushService([b], status=lambda _b, n: 503 if n <= 3 else 201)
            await _boot([b], svc)
            await events.broadcast(purchase(9800))
            await _settle(lambda: svc.n == 3 and not push_send._retries)
            await _settle()
            assert svc.n == 3 and b.got == [] and push_send.stats()["failed"] == 1
            for _ in range(2):
                await events.broadcast(purchase(9800))          # the re-offer, twice
            await _settle()
            assert [p["tag"] for p in b.got] == [f"{A}:9800"], b.got
        finally:
            pd.RETRY_DELAYS_S = old
            await push_send.stop()
    asyncio.run(go())


def test_dropped_worker_item_unclaims_tag():
    async def go():
        stall = asyncio.Event()

        async def hang(n):
            if n == 1:
                await stall.wait()
        b = Browser(OWNER_A)
        svc = PushService([b], delay=hang)
        push_send.WORKER_MAX, w_old = 1, push_send.WORKER_MAX
        try:
            await _boot([b], svc)
            for nid in (9900, 9901, 9902):          # 9900 in flight, 9901 queued then dropped by 9902
                await events.broadcast(purchase(nid))
                await asyncio.sleep(0.1)                # dispatched (the worker is held)
            assert push_send.stats()["dropped"] == 1
            stall.set()
            await _settle()
            await events.broadcast(purchase(9901))      # its re-offer
            await _settle()
            assert sorted(p["tag"] for p in b.got) == [f"{A}:9900", f"{A}:9901", f"{A}:9902"], b.got
        finally:
            push_send.WORKER_MAX = w_old
            await push_send.stop()
    asyncio.run(go())


def test_scope_cache_generation_guard():
    """A scope read racing a clear() (assignment_changed) must not cache the pre-clear scope."""
    async def go():
        push_scope.clear()
        entered, gate = asyncio.Event(), asyncio.Event()
        real = push_scope._owner

        async def slow(uid, issued):
            r = await real(uid, issued)
            entered.set()
            await gate.wait()
            return r
        pid, issued = auth.parse_cookie_issued(OWNER_A.cookies.get(auth.COOKIE_NAME))
        key = ("user", pid, issued)
        with mock.patch.object(push_scope, "_owner", slow):
            t = asyncio.create_task(push_scope.accounts_for("user", pid, issued))
            await entered.wait()
            push_scope.clear()
            gate.set()
            assert A in await t, "the caller still gets its read"
            assert key not in push_scope._cache, "the racing read was cached past the clear"
            gate.set()
            await push_scope.accounts_for("user", pid, issued)
            assert key in push_scope._cache
    asyncio.run(go())


def test_start_skips_but_keeps_off_host_endpoint():
    """PUSH_ENDPOINT_HOSTS replaces the default list: a host it leaves out is skipped in memory,
    never deleted (adding one host must not wipe every FCM sub); back in the list, it sends."""
    async def go():
        ok, apple = Browser(OWNER_A), Browser(OWNER_A)
        apple.row.endpoint = apple.endpoint = f"https://web.push.apple.com/{apple.id}"
        svc = PushService([ok, apple])
        with mock.patch.object(push_send, "HOSTS", pd.parse_hosts("fcm.googleapis.com")):
            await _boot([ok, apple], svc)
            assert set(push_send._subs) == {ok.id}
            assert sorted(await _db(select(PushSubscription.id))) == sorted([ok.id, apple.id]), "row kept"
            st = push_send.stats()
            assert (st["off_hosts"], st["pruned"]) == (1, 0), st
            await push_send.stop()
        await _start(svc)                                   # default hosts again
        assert set(push_send._subs) == {ok.id, apple.id} and push_send.stats()["off_hosts"] == 0
        await events.broadcast(purchase(9950))
        await _settle()
        assert len(ok.got) == len(apple.got) == 1
        await push_send.stop()
    asyncio.run(go())


def test_live_accounts_single_flight():
    """9 concurrent misses right after a clear(): one disk walk."""
    async def go():
        walks = [0]
        real = registry.list_accounts

        def counted(*a, **kw):
            walks[0] += 1
            time.sleep(0.05)
            return real(*a, **kw)
        with mock.patch.object(registry, "list_accounts", counted):
            push_scope.clear()
            got = await asyncio.gather(*(push_scope.live_accounts() for _ in range(9)))
            assert walks[0] == 1, walks
            assert all(g == got[0] for g in got) and A in got[0]
            await push_scope.live_accounts()                # cached now
            assert walks[0] == 1
            push_scope.clear()
            await push_scope.live_accounts()
            assert walks[0] == 2
    asyncio.run(go())


def test_vapid_raw_env_key_and_jwt_refresh():
    priv = ec.generate_private_key(ec.SECP256R1())
    raw = _b64(priv.private_numbers().private_value.to_bytes(32, "big"))   # deploy's old format
    pub = _b64(priv.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint))
    saved = push_send._vapid
    push_send._vapid = None
    push_send._jwt.clear()
    try:
        with mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": raw}):
            assert push_send.public_key() == pub
            ep = "https://fcm.googleapis.com/fcm/send/x"
            h1 = push_send.vapid_headers(ep)
            assert f"k={pub}" in h1["Authorization"]
            assert push_send.vapid_headers(ep) is h1, "cached within JWT_CACHE_S"
            aud = "https://fcm.googleapis.com"
            at, _ = push_send._jwt[aud]
            push_send._jwt[aud] = (at - push_send.JWT_CACHE_S - 1, h1)   # age the entry past the TTL
            h2 = push_send.vapid_headers(ep)
            assert h2 is not h1 and h2["Authorization"] != h1["Authorization"]
            claims = json.loads(push_send.b64d(h2["Authorization"].split("t=")[1].split(",")[0].split(".")[1]))
            assert claims["aud"] == aud and 0 < claims["exp"] - time.time() <= push_send.JWT_EXP_S
    finally:
        push_send._vapid = saved
        push_send._jwt.clear()


def test_worst_case_payload_fits_4k():
    b = Browser(OWNER_A)
    sub = push_send.sub_from_row(b.row)
    huge = "\U0001F525" * 2000
    n = pn.Notice("9" * 20, A, "purchases", huge, huge, "/m/" + "%F0" * 400, "purchases")
    body = push_send.encrypt(sub, push_send.wire(n))
    assert len(body) <= 4096, len(body)
    p = b.decrypt(body)
    assert len(p["title"]) == pn.TITLE_MAX and len(p["body"]) == pn.BODY_MAX and p["href"] is None


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
