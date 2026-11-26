import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dm_peak_rates  # noqa: E402

BUSY = [(1, "10:07"), (1, "10:08"), (2, "10:09"), (1, "10:10"), (3, "10:12"), (4, "10:16"),
        (1, "10:19"), (5, "10:20")]
TRAP = [(6, "14:01"), (7, "14:05"), (8, "14:09"), (9, "14:13")]
OLD_CROWD = [(20 + i, f"09:0{i}") for i in range(8)]


def _ts(day: str, hm: str) -> str:
    return f"{day} {hm}:00.000000"


def _make(path: Path, rows: list[tuple]) -> str:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE messages (account_id TEXT, fan_id INTEGER, message_id INTEGER, "
                "direction TEXT NOT NULL, sent_by_employee_id INTEGER, created_at DATETIME NOT NULL, "
                "mass_run_id INTEGER, automation_kind TEXT)")
    con.execute("CREATE TABLE employees (id INTEGER, display_name TEXT, is_active BOOL)")
    con.executemany("INSERT INTO messages VALUES ('a', 1, ?, ?, ?, ?, NULL, NULL)",
                    [(i, d, e, t) for i, (d, e, t) in enumerate(rows)])
    con.commit()
    con.close()
    return str(path)


@pytest.fixture
def db(tmp_path):
    rows = [("out", e, _ts("2026-11-10", hm)) for e, hm in BUSY]
    rows += [("in", 50, _ts("2026-11-10", "10:11")), ("in", 51, _ts("2026-11-10", "10:13")),
             ("out", None, _ts("2026-11-10", "10:14")), ("out", None, _ts("2026-11-10", "10:15"))]
    rows += [("out", e, _ts("2026-11-10", hm)) for e, hm in TRAP]
    rows += [("out", e, _ts("2026-10-01", hm)) for e, hm in OLD_CROWD]
    rows += [("out", 1, _ts("2026-11-20", "12:00")),
             ("in", None, _ts("2026-11-25", "12:00")), ("out", None, _ts("2026-11-25", "12:00"))]
    return _make(tmp_path / "copy.db", rows)


def _run(capsys, *args) -> str:
    assert dm_peak_rates.main(list(args)) == 0
    return capsys.readouterr().out


def test_trap_reads_differently_when_aligned():
    buckets: dict[int, set] = {}
    for e, hm in BUSY + TRAP:
        t = datetime.fromisoformat(f"2026-11-10T{hm}:00").replace(tzinfo=timezone.utc).timestamp()
        buckets.setdefault(int(t // 900), set()).add(e)
    assert max(len(s) for s in buckets.values()) == 4


def test_sliding_window_json(db, capsys):
    out = json.loads(_run(capsys, db, "--chatter-peak", "--json"))
    assert out == {"P": 5, "window_start": "2026-11-10 10:07:00", "window_end": "2026-11-10 10:22:00",
                   "weeks": 4, "senders": ["1", "2", "3", "4", "5"]}


def test_plain_line_only(db, capsys):
    out = _run(capsys, db, "--chatter-peak")
    assert out == ("chatter peak P=5 window 2026-11-10 10:07:00..2026-11-10 10:22:00 UTC "
                   "(15 min, last 4 weeks to 2026-11-20 12:00:00)\n")


def test_weeks_widens_to_old_crowd(db, capsys):
    out = json.loads(_run(capsys, db, "--chatter-peak", "--json", "--weeks", "8"))
    assert out["P"] == 8 and out["weeks"] == 8
    assert out["senders"] == [str(20 + i) for i in range(8)]
    assert out["window_start"] == "2026-10-01 09:00:00"


def test_empty_db(tmp_path, capsys):
    path = _make(tmp_path / "empty.db", [])
    assert json.loads(_run(capsys, path, "--chatter-peak", "--json")) == {
        "P": 0, "window_start": None, "window_end": None, "weeks": 4, "senders": []}
    assert _run(capsys, path, "--chatter-peak") == "chatter peak P=0 window -..- UTC (15 min, last 4 weeks to -)\n"


@pytest.mark.parametrize("last,peak", [("15:00.000000", 2), ("15:00.000100", 1)])
def test_sliding_window_uses_stored_precision(tmp_path, capsys, last, peak):
    path = _make(tmp_path / "copy.db", [("out", 1, "2026-11-10 10:00:00.000100"),
                                        ("out", 2, f"2026-11-10 10:{last}")])
    assert json.loads(_run(capsys, path, "--chatter-peak", "--json"))["P"] == peak


def test_peak_excludes_mass_and_automated_sends(tmp_path, capsys):
    path = _make(tmp_path / "copy.db", [("out", emp, "2026-11-10 10:00:00") for emp in range(1, 5)])
    with sqlite3.connect(path) as con:
        con.execute("UPDATE messages SET mass_run_id = 1 WHERE sent_by_employee_id = 2")
        con.execute("UPDATE messages SET automation_kind = 'welcome' WHERE sent_by_employee_id = 3")
        con.execute("INSERT INTO employees VALUES (4, 'Automation', 0)")
    assert json.loads(_run(capsys, path, "--chatter-peak", "--json"))["senders"] == ["1"]


@pytest.mark.parametrize("args", [("--since", "2026-11-01"), ("--account=a",), ("--clock=received",),
                                  ("--top", "10"), ("--all-events",)])
def test_chatter_peak_rejects_inbound_options(db, capsys, args):
    with pytest.raises(SystemExit) as exc:
        dm_peak_rates.main([db, "--chatter-peak", *args])
    assert exc.value.code == 2 and "cannot use" in capsys.readouterr().err


def test_chatter_peak_refuses_pre_automation_kind_schema(db, capsys):
    with sqlite3.connect(db) as con:
        con.execute("ALTER TABLE messages DROP COLUMN automation_kind")
    with pytest.raises(SystemExit) as exc:
        dm_peak_rates.main([db, "--chatter-peak"])
    assert exc.value.code == 2
    assert "requires Alembic revision 0032_automation_kind or later" in capsys.readouterr().err
