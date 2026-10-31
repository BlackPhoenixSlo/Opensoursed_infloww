#!/usr/bin/env python3
"""convo_review_fetch: the ranking half of the convo reader (scripts/convo-review.sh) as tables.
No network, no real DB: pure helpers as tables, the SQL signals against an in-memory sqlite holding
only the `messages` / `transactions` columns they read (names from service/db/models.py).

Pins: break_score caps each signal at 4 and ignores unknown names; pick drops threads under min_msgs
(the edge is kept), selling needs revenue > 0, breaks needs a signal, each bucket honours its n, the
union is ordered money, then breakage, then inbound, and `why` reads in break-weight order;
_like_clause binds one `?` per needle and wraps each in %; media_priority puts unlocked PPVs, then
what he sent, then the rest, newest first in each tier. thread_stats counts per (account, fan);
add_revenue counts only cleared money of MONEY_KINDS and flags chargebacks; add_text_signals matches
inbound only; add_loop_signal needs 3+ identical outbound lines of >= 30 chars, unsent excluded;
add_tail_signals flags 3+ trailing inbound and an unopened trailing PPV. MASS_PLACEHOLDER_BASE
mirrors attribution._MASS_PLACEHOLDER_BASE (read via ast: importing attribution opens the DB).

run(parse_args([...])) end to end against a temp sqlite FILE with --no-media: exit 0, the payload
shape, the picked ids in union order.

Run as a script (the repo's convention, no pytest):
    ./venv/bin/python service/tests/test_convo_review_fetch.py
"""
from __future__ import annotations

import ast
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))

import convo_review_fetch as crf  # noqa: E402

def table(_cols, rows):
    """Attach the rows; the runner below calls `fn(*row)` for each."""
    def mark(fn):
        fn.rows = rows
        return fn
    return mark


def _no_network(*_a, **_k):
    raise AssertionError("network call in a DB-only test")


# Nothing reachable from these tests fetches media; if that ever changes, fail loudly, never fetch.
crf.fetch_thread_media = crf.fetch_still = crf.fetch_giphy = _no_network


# ── pure tables ──────────────────────────────────────────────────────────────

@table("signals, score", [
    ({}, 0),
    ({"ghosted": 1}, 12),
    ({"chargeback": 4}, 400),
    ({"chargeback": 5}, 400),                    # capped at 4
    ({"bot_callout": 100}, 240),
    ({"loop_out": 3, "angry": 1}, 90 + 45),
    ({"nonsense": 9}, 0),                        # unknown signal weighs nothing
    ({"dead_offer": 0}, 0),
])
def test_break_score(signals, score):
    assert crf.break_score({"signals": signals}) == score


@table("needles, sql, params", [
    ([], "", []),
    (["a"], "c LIKE ?", ["%a%"]),
    (["you're a bot", "u ai"], "c LIKE ? OR c LIKE ?", ["%you're a bot%", "%u ai%"]),
    (iter(["x", "y", "z"]), "c LIKE ? OR c LIKE ? OR c LIKE ?", ["%x%", "%y%", "%z%"]),
])
def test_like_clause(needles, sql, params):
    assert crf._like_clause("c", needles) == (sql, params)


@table("msg, prio", [
    ({"paid": 1, "dir": "out", "id": 5}, (0, -5)),
    ({"paid": 1, "dir": "in", "id": 5}, (0, -5)),      # paid beats inbound
    ({"paid": True, "dir": "out", "id": 5}, (0, -5)),  # sqlite bool reads as 1
    ({"paid": 0, "dir": "in", "id": 7}, (1, -7)),
    ({"paid": None, "dir": "out", "id": 9}, (2, -9)),
    ({"dir": "in"}, (1, 0)),                           # no id
    ({"id": None}, (2, 0)),
])
def test_media_priority(msg, prio):
    assert crf.media_priority(msg) == prio


def test_media_priority_orders():
    ms = [{"id": 1, "dir": "out"}, {"id": 2, "dir": "in"}, {"id": 3, "dir": "out", "paid": 1},
          {"id": 4, "dir": "in"}, {"id": 5, "dir": "out"}]
    assert [m["id"] for m in sorted(ms, key=crf.media_priority)] == [3, 4, 2, 5, 1]


def _st(name, total=10, inbound=5, rev=0, buys=0, tips=0, signals=None):
    return {"account_id": "a", "fan_id": name, "total": total, "inbound": inbound,
            "revenue_cents": rev, "buys": buys, "tips": tips, "signals": dict(signals or {})}


def _pick(rows, n_sell=5, n_long=5, n_break=5, min_msgs=8):
    stats = {str(s["fan_id"]): s for s in rows}
    return crf.pick(stats, n_sell, n_long, n_break, min_msgs)


@table("rows, kw, want", [
    # min_msgs edge: 8 kept, 7 dropped
    ([_st(1, total=8), _st(2, total=7)], {"n_sell": 0, "n_break": 0}, [1]),
    # zero revenue is not selling; zero inbound still ranks long when n_long allows
    ([_st(1, rev=0, inbound=0)], {"n_long": 0, "n_break": 0}, []),
    ([_st(1, inbound=0)], {"n_sell": 0, "n_break": 0}, [1]),
    ([_st(1, rev=1)], {"n_long": 0, "n_break": 0}, [1]),
    # breaks need a signal
    ([_st(1), _st(2, signals={"ghosted": 3})], {"n_sell": 0, "n_long": 0}, [2]),
    # n caps each bucket, best-first
    ([_st(1, rev=100), _st(2, rev=300), _st(3, rev=200)], {"n_sell": 2, "n_long": 0, "n_break": 0}, [2, 3]),
    ([_st(1, inbound=3), _st(2, inbound=9)], {"n_sell": 0, "n_long": 1, "n_break": 0}, [2]),
    ([_st(1, signals={"ghosted": 1}), _st(2, signals={"chargeback": 1})],
     {"n_sell": 0, "n_long": 0, "n_break": 1}, [2]),
    # union order: money, then break score, then inbound
    ([_st(1, inbound=50), _st(2, rev=10, inbound=1), _st(3, signals={"angry": 1}, inbound=2)],
     {}, [2, 3, 1]),
    # nothing alive
    ([], {}, []),
])
def test_pick(rows, kw, want):
    assert [s["fan_id"] for s in _pick(rows, **kw)] == want


def test_pick_why():
    s = _st(1, rev=123_456, buys=1, tips=2, inbound=1234,
            signals={"ghosted": 3, "chargeback": 1, "nonsense": 1})
    [t] = _pick([s])
    assert t["buckets"] == ["selling", "long", "breaks"]
    assert t["why"] == ["$1,235 from 1 unlock + 2 tips", "1,234 messages from him",
                        "charged back", "he talked, nobody answered"]
    assert t["break_score"] == 100 + 36
    [u] = _pick([_st(2, rev=200, buys=2, tips=0)], n_long=0)
    assert u["why"] == ["$2 from 2 unlocks"]
    # signals only explain a thread that landed in breaks
    [v] = _pick([_st(3, inbound=9, signals={"angry": 1})], n_break=0)
    assert v["buckets"] == ["long"] and v["why"] == ["9 messages from him"]


# ── in-memory DB ─────────────────────────────────────────────────────────────

def _db(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE messages (
            account_id TEXT NOT NULL, fan_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            direction TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
            media_count INTEGER NOT NULL DEFAULT 0, price_cents INTEGER NOT NULL DEFAULT 0,
            is_paid BOOLEAN, is_unsent BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME NOT NULL,
            PRIMARY KEY (account_id, fan_id, message_id));
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, fan_id INTEGER, kind TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, status TEXT NOT NULL);
    """)
    return conn


_seq = [0]


def _msg(conn, fan, direction, body="", acct="a", media=0, price=0, paid=None, unsent=0, mid=None):
    _seq[0] += 1
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (acct, fan, mid or _seq[0], direction, body, media, price, paid, unsent,
                  f"2026-01-01 00:00:00.{_seq[0]:06d}"))


def _tx(conn, fan, kind, cents, status="cleared", acct="a"):
    conn.execute("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, status) "
                 "VALUES (?,?,?,?,?)", (acct, fan, kind, cents, status))


def test_thread_stats():
    c = _db()
    _msg(c, 1, "in")
    _msg(c, 1, "out", media=2, paid=1)
    _msg(c, 1, "out", media=0, paid=0)
    _msg(c, 1, "system")
    _msg(c, 2, "in", acct="b")
    st = crf.thread_stats(c)
    assert set(st) == {"a:1", "b:2"}
    s = st["a:1"]
    assert (s["total"], s["inbound"], s["outbound"], s["media_msgs"], s["unlocked"]) == (4, 1, 2, 1, 1)
    assert s["first_at"] < s["last_at"]
    assert (s["revenue_cents"], s["signals"]) == (0, {})
    assert st["b:2"]["outbound"] == 0                       # SUM over none → 0, not None
    assert crf.thread_stats(_db()) == {}


def test_add_revenue():
    c = _db()
    for f in (1, 2, 3):
        _msg(c, f, "in")
    _tx(c, 1, "ppv_message", 1000)
    _tx(c, 1, "ppv_post", 500)
    _tx(c, 1, "tip", 250)
    _tx(c, 1, "tip", 999, status="pending")                 # not cleared: no money
    _tx(c, 1, "subscription", 7777)                         # not a MONEY_KIND
    _tx(c, 2, "ppv_message", 300, status="chargedback")
    _tx(c, 2, "tip", 100, status="refund_pending")
    _tx(c, 9, "tip", 100)                                   # no thread: ignored
    c.execute("INSERT INTO transactions (account_id, fan_id, kind, amount_cents, status) "
              "VALUES ('a', NULL, 'tip', 5, 'cleared')")
    st = crf.thread_stats(c)
    crf.add_revenue(c, st)
    a1, a2, a3 = st["a:1"], st["a:2"], st["a:3"]
    assert (a1["revenue_cents"], a1["buys"], a1["tips"], a1["chargebacks"]) == (1750, 2, 1, 0)
    assert a1["signals"] == {}
    assert (a2["revenue_cents"], a2["chargebacks"], a2["signals"]) == (0, 2, {"chargeback": 2})
    assert a3["revenue_cents"] == 0 and "a:9" not in st


def test_add_text_signals():
    c = _db()
    _msg(c, 1, "in", "ARE YOU A BOT??", mid=11)
    _msg(c, 1, "in", "you're a bot lol", mid=12)
    _msg(c, 1, "in", "this is a scam, refund", mid=13)       # one row, one hit for `angry`
    _msg(c, 1, "out", "are you a bot", mid=14)              # outbound never counts
    _msg(c, 2, "in", "on the bottom of both", mid=21)       # no loose '%bot%'
    _msg(c, 2, "in", "you already said that", mid=22)
    st = crf.thread_stats(c)
    hits: dict = {}
    crf.add_text_signals(c, st, hits)
    assert st["a:1"]["signals"] == {"bot_callout": 2, "angry": 1}
    assert sorted(hits["a:1"]) == [11, 12, 13]
    assert st["a:2"]["signals"] == {"repeat_callout": 1}
    assert hits["a:2"] == [22]


LINE = "hey babe, this one is just for you x"                 # 36 chars


def test_add_loop_signal():
    c = _db()
    for _ in range(3):
        _msg(c, 1, "out", LINE)
    for _ in range(2):
        _msg(c, 2, "out", LINE)                             # 2 is not a loop
    for _ in range(3):
        _msg(c, 3, "out", "short line x3")                  # < 30 chars
    for i in range(3):
        _msg(c, 4, "out", LINE, unsent=1 if i == 0 else 0)  # unsent excluded → 2
    for _ in range(3):
        _msg(c, 5, "in", LINE)                              # inbound never loops
    for _ in range(2):
        _msg(c, 2, "out", LINE, acct="b")                   # same fan id, other Creator: still 2
    _msg(c, 7, "out", LINE)                                 # spread across fans is a mass blast
    st = crf.thread_stats(c)
    hits: dict = {}
    crf.add_loop_signal(c, st, hits)
    assert st["a:1"]["signals"] == {"loop_out": 1} and len(hits["a:1"]) == 3
    for k in ("a:2", "b:2", "a:3", "a:4", "a:5", "a:7"):
        assert st[k]["signals"] == {} and k not in hits, k


def test_add_tail_signals():
    c = _db()
    _msg(c, 1, "out", "hi")
    for _ in range(3):
        _msg(c, 1, "in", "hello?")                          # ghosted at exactly 3
    _msg(c, 2, "out", "hi")
    for _ in range(2):
        _msg(c, 2, "in", "hello?")                          # 2: not ghosted
    for _ in range(8):
        _msg(c, 3, "in", "hello?")                          # only the last 6 are read
    _msg(c, 4, "in", "hi")
    _msg(c, 4, "out", "ppv", price=1500, paid=0)            # dead offer
    _msg(c, 5, "out", "ppv", price=1500, paid=1)            # opened: fine
    _msg(c, 6, "out", "ppv", price=1500, paid=None)         # never answered: dead
    _msg(c, 7, "out", "ppv", price=1500, paid=0)
    _msg(c, 7, "in", "nah")                                 # reply after: not dead
    _msg(c, 8, "out", "free pic", price=0, paid=0)          # free: not an offer
    st = crf.thread_stats(c)
    crf.add_tail_signals(c, st)
    sig = {k: v["signals"] for k, v in st.items()}
    assert sig == {"a:1": {"ghosted": 3}, "a:2": {}, "a:3": {"ghosted": 6}, "a:4": {"dead_offer": 1},
                   "a:5": {}, "a:6": {"dead_offer": 1}, "a:7": {}, "a:8": {}}


def test_mass_placeholder_mirrors_attribution():
    tree = ast.parse((SERVICE / "attribution.py").read_text())
    vals = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
            and any(getattr(t, "id", None) == "_MASS_PLACEHOLDER_BASE" for t in n.targets)]
    assert vals == [crf.MASS_PLACEHOLDER_BASE], vals


def test_run_end_to_end_no_media():
    """The CLI's own entry: parse_args → run, on a FILE (connect opens it read-only by URI)."""
    with tempfile.TemporaryDirectory(prefix="crf_") as tmp:
        d = Path(tmp)
        db, out = d / "c.db", d / "out.json"
        c = _db(str(db))
        for i in range(8):                                      # fan 1: 8 msgs, one cleared unlock
            _msg(c, 1, "in" if i % 2 == 0 else "out", f"m{i}")
        _tx(c, 1, "ppv_message", 1500)
        for i in range(7):                                      # fan 2: 7 msgs, under --min-msgs
            _msg(c, 2, "in" if i % 2 == 0 else "out", f"m{i}")
        for i in range(9):                                      # fan 3: a bot callout, no money
            _msg(c, 3, "in" if i % 2 == 0 else "out", "are you a bot" if i == 4 else f"m{i}")
        # Columns only load_messages / fan_names / account_names read; added after the
        # positional _msg inserts so those keep working.
        c.executescript("""
            ALTER TABLE messages ADD COLUMN media_ids TEXT;
            ALTER TABLE messages ADD COLUMN is_tip BOOLEAN NOT NULL DEFAULT 0;
            ALTER TABLE messages ADD COLUMN automation_kind TEXT;
            ALTER TABLE messages ADD COLUMN image_desc TEXT;
            ALTER TABLE messages ADD COLUMN sender_name TEXT;
            CREATE TABLE fans (account_id TEXT, fan_id INTEGER, of_username TEXT,
                of_display_name TEXT, custom_nickname TEXT, generated_nickname TEXT,
                real_name TEXT, lifetime_spend_cents INTEGER);
            CREATE TABLE accounts (id TEXT PRIMARY KEY, nickname TEXT);
            INSERT INTO fans (account_id, fan_id, of_username, custom_nickname)
                VALUES ('a', 1, 'u1', 'Bob');
            INSERT INTO accounts VALUES ('a', 'Ava');
        """)
        c.commit()
        c.close()
        real_path = crf.DB_PATH
        crf.DB_PATH = str(db)
        try:
            rc = crf.run(crf.parse_args(["--out", str(out), "--no-media", "--selling", "5",
                                         "--long", "0", "--breaks", "5"]))
        finally:
            crf.DB_PATH = real_path
        assert rc == 0, rc
        got = json.loads(out.read_text())
        assert set(got) == {"generated_at", "threads", "media", "media_meta", "counts"}, set(got)
        assert got["counts"] == {"scanned": 3, "picked": 2, "media_new": 0}, got["counts"]
        assert (got["media"], got["media_meta"]) == ({}, {})
        ts = got["threads"]
        assert [t["fan_id"] for t in ts] == [1, 3], [t["fan_id"] for t in ts]   # money, then breaks
        assert [t["buckets"] for t in ts] == [["selling"], ["breaks"]], [t["buckets"] for t in ts]
        assert [(t["account_name"], t["fan_name"]) for t in ts] == [("Ava", "Bob"), ("Ava", "fan 3")]
        assert [(t["shown"], t["truncated"]) for t in ts] == [(8, False), (9, False)]
        assert [m["body"] for m in ts[0]["messages"]] == [f"m{i}" for i in range(8)]
        assert [m["hit"] for m in ts[1]["messages"]].count(True) == 1


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
