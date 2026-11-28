#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

from _send_kill_cell import AID, SYNC_URL, cells, client, restart  # noqa: E402

import accounts  # noqa: E402
import automation_executor as ax  # noqa: E402
import cell_mode  # noqa: E402
import restore_reconcile  # noqa: E402
import send_ops  # noqa: E402
from of_reads import PEEK_CURSOR  # noqa: E402

accounts.get_platform = lambda aid: "onlyfans"
KIND = "scheduled_send"
FANS = iter(range(78001, 79000))
IDS = iter(range(8_800_000_000_001, 8_899_000_000_000))
NOW = datetime.utcnow().replace(microsecond=0)
SINCE, RESTORED = NOW - timedelta(hours=2), NOW - timedelta(minutes=10)


def _ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _db(sql: str, args: tuple = ()):
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute(sql, args).fetchall()


class PeekHttp:
    def __init__(self, pages: dict[int, list[dict]] | None = None, queue: list[dict] | None = None,
                 fail: bool = False):
        self.pages, self.queue, self.fail = pages or {}, queue or [], fail
        self.gets: list[tuple[str, dict]] = []
        self.sends: list[int] | None = None

    def get(self, url, headers=None, timeout=None):
        from _send_kill_cell import Resp
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.gets.append((parts.path.split("/api2/v2")[-1], q))
        if self.fail:
            return Resp(500, {"error": {"code": 500, "message": "down"}}, url)
        if parts.path.endswith("/messages/queue"):
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 10))
            rows = self.queue[off:off + lim]
            return Resp(200, {"list": rows, "hasMore": off + lim < len(self.queue)}, url)
        fan = int(parts.path.split("/chats/")[1].split("/")[0])
        top = int(q["id"]) if "id" in q else None
        rows = [m for m in self.pages.get(fan, []) if top is None or m["id"] < top]
        return Resp(200, {"list": rows[:50], "hasMore": len(rows) > 50}, url)

    def request(self, method, url, json=None, headers=None, timeout=None):
        if self.sends is None:
            raise AssertionError(f"peek made a write: {method} {url}")
        from _send_kill_cell import Resp
        self.sends.append(int(urlsplit(url).path.split("/chats/")[1].split("/")[0]))
        return Resp(200, {"id": next(IDS)}, url)


def _msg(at: datetime, creator: bool = True, fan: int = 0) -> dict:
    return {"id": next(IDS), "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "text": "gap",
            "fromUser": {"id": int(AID) if creator else fan}}


@contextlib.contextmanager
def restored(peek_until: datetime | None = NOW + timedelta(hours=23), http: PeekHttp | None = None):
    with cells():
        restart()
        cell_mode.install_meta(SYNC_URL)
        restore_reconcile.install(SYNC_URL)
        _db_exec("UPDATE cell_meta SET reconcile_since=?, restored_at=?, peek_until=?",
                 (_ts(SINCE), _ts(RESTORED), peek_until and _ts(peek_until)))
        with patch.object(ax, "_make_client", lambda account: client(http or PeekHttp())):
            yield
        _db_exec("UPDATE cell_meta SET reconcile_since=NULL, restored_at=NULL, peek_until=NULL, gap_confirmed_by=NULL, gap_confirmed_at=NULL")


def _db_exec(sql: str, args: tuple = ()) -> None:
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c, c:
        c.execute(sql, args)


def _send(fan: int, kind: str = KIND, anchor: str | None = None) -> tuple[str, list]:
    sent: list = []

    def wire():
        sent.append(fan)
        return {"id": next(IDS)}
    try:
        send_ops.automated_sync(AID, kind, fan, anchor or f"a-{next(IDS)}", wire)
    except send_ops.SendRefused as e:
        return e.detail["error"], sent
    except send_ops.send_tripwire.CellHeld as e:
        return e.hold.why, sent
    return "sent", sent


def _peeks(http: PeekHttp, fan: int) -> list[dict]:
    return [q for p, q in http.gets if p == f"/chats/{fan}/messages"]


def _ingest(fan: int, msg: dict, ingested: datetime) -> None:
    _db_exec("INSERT INTO messages (account_id, fan_id, message_id, direction, created_at, ingested_at, sender_name,"
             " body, media_ids, media_count, price_cents, is_tip, is_unsent, is_promise)"
             " VALUES (?,?,?,?,?,?,'','','[]',0,0,0,0,0)", (AID, fan, msg["id"], "out", _ts(SINCE + timedelta(minutes=30)), _ts(ingested)))


def case_unmatched_ingested_after_restore_holds_the_fan():
    fan = next(FANS)
    lost = _msg(SINCE + timedelta(minutes=30))
    http = PeekHttp({fan: [lost]})
    with restored(http=http):
        _ingest(fan, lost, NOW)
        got = _send(fan)
        again = _send(fan)
        listed = [r["kind"] for r in send_ops.uncertain(AID) if r["target"] == str(fan)]
        rows = _db("SELECT kind, state, upstream_id FROM send_ops WHERE account=? AND target=?", (AID, str(fan)))
    assert got == ("fan_held", []) and again == ("fan_held", []), (got, again)
    assert listed == ["restore_peek"] and rows == [("restore_peek", "uncertain", str(lost["id"]))], (listed, rows)
    peeks = _peeks(http, fan)
    assert len(peeks) == 1 and peeks[0]["id"] == str(PEEK_CURSOR), http.gets


def case_known_before_restore_or_send_op_sends_and_peeks_once():
    fan, fan2 = next(FANS), next(FANS)
    a, b = _msg(SINCE + timedelta(minutes=5)), _msg(SINCE + timedelta(minutes=6))
    http = PeekHttp({fan: [a], fan2: [b]})
    with restored(http=http):
        _ingest(fan, a, RESTORED - timedelta(minutes=1))
        _db_exec(f"INSERT INTO send_ops (account, op_id, kind, target, digest, state, upstream_id, attempts,"
                 f" created_at, updated_at) VALUES (?,?,?,?,?,'sent',?,1,{send_ops._NOW},{send_ops._NOW})",
                 (AID, f"seed-{b['id']}", KIND, str(fan2), "d", str(b["id"])))
        got = [_send(fan), _send(fan), _send(fan2)]
    assert [g[0] for g in got] == ["sent"] * 3, got
    assert len(_peeks(http, fan)) == 1 and len(_peeks(http, fan2)) == 1, http.gets


def case_fan_and_out_of_gap_messages_are_not_lost():
    fan = next(FANS)
    msgs = [_msg(SINCE + timedelta(minutes=9), creator=False, fan=fan), _msg(SINCE - timedelta(minutes=1)),
            _msg(RESTORED + timedelta(minutes=1))]
    http = PeekHttp({fan: sorted(msgs, key=lambda m: m["createdAt"], reverse=True)})
    with restored(http=http):
        got = _send(fan)
        peeked = _db("SELECT unmatched FROM reconcile_peeks WHERE account=? AND target=?", (AID, str(fan)))
    assert got[0] == "sent" and peeked == [(0,)], (got, peeked)


def case_no_read_marking_get_ever():
    fan = next(FANS)
    http = PeekHttp({fan: [_msg(SINCE + timedelta(minutes=1 + i)) for i in range(60)][::-1]})
    with restored(http=http):
        _send(fan)
    assert http.gets and all("id" in q for _, q in http.gets), http.gets
    assert len(_peeks(http, fan)) == 2, http.gets


def case_page_limit_leaves_fan_unreconciled():
    fan = next(FANS)
    lost = _msg(SINCE + timedelta(minutes=1))
    recent = [_msg(RESTORED + timedelta(minutes=1)) for _ in range(250)]
    http = PeekHttp({fan: [*reversed(recent), lost]})
    with restored(http=http):
        got = _send(fan)
        peeked = _db("SELECT 1 FROM reconcile_peeks WHERE account=? AND target=?", (AID, str(fan)))
    assert got == ("peek_failed", []) and peeked == [], (got, peeked)
    assert len(_peeks(http, fan)) == 5


def case_after_window_or_manual_or_queue_kind_no_peek():
    fan = next(FANS)
    http = PeekHttp({fan: [_msg(SINCE + timedelta(minutes=30))]})
    with restored(peek_until=NOW - timedelta(seconds=1), http=http):
        late = _send(fan)
    with restored(http=http):
        manual = _send(fan, "composer")
        manual_queue = _send(fan, "manual_mass_send")
        queue = _send(fan, "mass_job")
        direct_op = send_ops.op_id("onlyfans", AID, "mass_job", str(fan), "direct", 0)
        try:
            send_ops.begin("onlyfans", AID, direct_op, "mass_job", str(fan), send_ops.digest({}))
        except send_ops.send_tripwire.CellHeld as e:
            assert e.hold.why == "restore_gap_unconfirmed"
        else:
            raise AssertionError("direct queue claim accepted during the restore gap")
        assert not _db("SELECT 1 FROM send_ops WHERE op_id=?", (direct_op,))
        _db_exec("UPDATE cell_meta SET peek_until=?", (_ts(NOW - timedelta(seconds=1)),))
        expired = _send(fan, "mass_job")
        assert restore_reconcile.confirm_gap("test-owner")
        confirmed = _send(fan, "mass_job")
    assert (late[0], manual[0], queue[0], expired[0], confirmed[0]) == (
        "sent", "sent", "restore_gap_unconfirmed", "restore_gap_unconfirmed", "sent")
    assert manual_queue[0] == "sent"
    assert not queue[1] and not expired[1] and not http.gets


def case_peek_failure_refuses_that_fan_only_and_retries():
    fan = next(FANS)
    http = PeekHttp(fail=True)
    with restored(http=http):
        got = _send(fan)
        rows = _db("SELECT 1 FROM send_ops WHERE account=? AND target=?", (AID, str(fan)))
        http.fail = False
        retry = _send(fan)
    assert got == ("peek_failed", []) and rows == [] and retry[0] == "sent", (got, rows, retry)
    assert "peek_failed" in send_ops._FAN_REFUSALS


def case_async_path_peeks_too():
    fan = next(FANS)
    http = PeekHttp({fan: [_msg(SINCE + timedelta(minutes=30))]})

    async def wire():
        raise AssertionError("sent past a lost gap message")

    async def go():
        try:
            await send_ops.automated(AID, KIND, fan, "async-anchor", wire)
        except send_ops.SendRefused as e:
            return e.detail["error"]
    with restored(http=http):
        got = asyncio.run(go())
    assert got == "fan_held" and len(_peeks(http, fan)) == 1, (got, http.gets)


def case_planned_move_and_env_unset_never_peek():
    fan = next(FANS)
    http = PeekHttp({fan: [_msg(SINCE + timedelta(minutes=30))]})
    with cells():
        restart()
        cell_mode.install_meta(SYNC_URL)
        restore_reconcile.install(SYNC_URL)
        with patch.object(ax, "_make_client", lambda account: client(http)):
            moved = _send(fan)
    with patch.object(ax, "_make_client", lambda account: client(http)):
        plain = _send(fan)
    assert (moved[0], plain[0]) == ("sent", "sent") and http.gets == [], (moved, plain, http.gets)


def case_held_fan_job_does_not_starve_the_creators_other_jobs():
    import of_write
    held, other = next(FANS), next(FANS)
    http = PeekHttp({held: [_msg(SINCE + timedelta(minutes=30))]})
    http.sends = []
    paced = of_write.of_write_paced

    async def unpaced(*a, **k):
        return await paced(*a, **{**k, "min_gap_s": 0})

    async def go():
        from db.engine import get_session
        from db.models import Account
        async with get_session() as s:
            if await s.get(Account, AID) is None:
                s.add(Account(id=AID, nickname=AID))
        first = await ax.enqueue_job(AID, KIND, payload={"fan_id": held, "text": "a", "send_purpose": "manual"},
                                     run_at=datetime.utcnow() - timedelta(minutes=2))
        await ax.enqueue_job(AID, KIND, payload={"fan_id": other, "text": "b", "send_purpose": "manual"},
                             run_at=datetime.utcnow() - timedelta(minutes=1))
        return first, [(await ax.run_once(AID, KIND)).get("reason") for _ in range(2)]
    with restored(http=http), patch.object(ax, "_CELLS", True), patch.object(ax, "of_write_paced", unpaced):
        first, got = asyncio.run(go())
        job = _db("SELECT status, run_at > datetime('now', '+30 seconds') FROM scheduled_jobs WHERE id=?", (first,))
    assert got[0] == "fan_held" and http.sends == [other], (got, http.sends)
    assert job == [("pending", 1)], job


def case_native_queue_lists_items_missing_from_the_db():
    known_op, known_run, missing = next(IDS), next(IDS), next(IDS)
    http = PeekHttp(queue=[{"id": i, "scheduledDate": "2026-12-01T10:00:00+00:00"} for i in
                           [known_op, known_run, *range(missing, missing + 55)]])
    with restored(http=http):
        _db_exec(f"INSERT INTO send_ops (account, op_id, kind, target, digest, state, upstream_id, attempts,"
                 f" created_at, updated_at) VALUES (?,?,?,?,?,'sent',?,1,{send_ops._NOW},{send_ops._NOW})",
                 (AID, f"q-{known_op}", "native_schedule", "0", "d", str(known_op)))
        _db_exec("INSERT INTO mass_runs (account_id, audience_filter, recipient_count, queue_id, status)"
                 " VALUES (?,'{}',0,?,'scheduled')", (AID, known_run))
        unknown = restore_reconcile.native_queue_unknown(AID, client(http))
    assert [i["id"] for i in unknown] == list(range(missing, missing + 55)), [i["id"] for i in unknown][:3]
    assert [q["offset"] for p, q in http.gets if p == "/messages/queue"] == ["0", "50"], http.gets


async def case_held_mass_job_has_no_list_writes_or_run_mint():
    class Lists:
        def __init__(self):
            self.writes = []

        def get_lists(self, **_):
            return {"list": [], "hasMore": False}

        def create_list(self, name):
            self.writes.append(name)
            return {"id": 777, "name": name}

        def list_users_in(self, *_, **__):
            return {"list": [], "hasMore": False}

        def add_user_to_list(self, list_id, user_id):
            self.writes.append((list_id, user_id))

        def send_mass_message(self, **_):
            raise AssertionError("held mass job reached the send")

    from db.engine import get_session
    from db.models import Account
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname=AID))
    wire = Lists()
    _db_exec("CREATE TABLE gap_mass_mints (id INTEGER)")
    _db_exec("CREATE TRIGGER gap_mass_mint AFTER INSERT ON mass_runs "
             "BEGIN INSERT INTO gap_mass_mints VALUES (NEW.id); END")
    try:
        with restored(), patch.object(ax, "_CELLS", True), patch.object(ax, "_make_client", lambda _: wire):
            job = await ax.enqueue_job(AID, "send_mass_message", payload={
                "text": "list broadcast", "user_lists": ["123"], "excluded_users": [next(FANS)],
                "exclude_replied_hours": 0, "exclude_inbound_hours": 0,
            })
            result = await ax.run_once(AID, "send_mass_message")
            assert (result.get("reason"), wire.writes, _db("SELECT id FROM gap_mass_mints")) == (
                "cell_held", [], []), (result, wire.writes, _db("SELECT id FROM gap_mass_mints"))
            assert _db("SELECT status FROM scheduled_jobs WHERE id=?", (job,)) == [("pending",)]
            _db_exec("DELETE FROM scheduled_jobs WHERE id=?", (job,))
    finally:
        _db_exec("DROP TRIGGER gap_mass_mint")
        _db_exec("DROP TABLE gap_mass_mints")


if __name__ == "__main__":
    _harness.run()
