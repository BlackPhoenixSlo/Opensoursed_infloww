#!/usr/bin/env python3
"""Audit log keeps no credential (W30 F1).

  case_snapshot_*:   audit_log._safe_snapshot — a credential write (keys_only)
                     keeps names + set/cleared only, nested too; elsewhere secret
                     names (incl. `*_key`) are redacted at any depth; a pasted curl
                     over 4 KB is redacted, not stored as raw text.
  case_single_head / case_upgrade_scrubs_only_credential_rows: migration 0134
                     scrubs historic rows, leaves every other row, idempotent.
  case_init_db_scrubs_once: boxes run it through init_db (data_migrations marker).

Run: ./venv/bin/python service/tests/test_audit_credential_scrub.py
"""
from __future__ import annotations

import _harness  # MUST be first: temp DB env guard

import json  # noqa: E402
import os  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from audit_log import _safe_snapshot  # noqa: E402
from db.models import Base  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations"
PREV, REV = "0133_tracking_clicks_unclassified", "0134_audit_credential_scrub"
KEY = "sk-live-0123456789abcdef"


def _snap(body: dict, keys_only: bool) -> dict:
    return json.loads(_safe_snapshot(json.dumps(body).encode(), keys_only=keys_only))


def case_snapshot_credential_write_keeps_names_only():
    got = _snap({"typesafe": KEY, "deepseek": "", "TYPESAFE_API_KEY": None}, True)
    assert got == {"typesafe": "set", "deepseek": "cleared", "TYPESAFE_API_KEY": "cleared"}, got
    got = _snap({"admin_password": "pw-founder", "providers": {"typesafe": KEY}}, True)
    assert got == {"admin_password": "set", "providers": {"typesafe": "set"}}, got


def case_snapshot_other_writes_keep_values_but_nested_secrets():
    got = _snap({"name": "hu-1", "proxy": {"password": "pw", "host": "h"}, "code": "1"}, False)
    assert got == {"name": "hu-1", "proxy": {"password": "***", "host": "h"}, "code": "***"}, got
    got = _snap({"countries": [{"code": "US"}]}, False)      # a nested `code` is data
    assert got == {"countries": [{"code": "US"}]}, got
    got = _snap({"cfg": {"HELP_ASSISTANT_DEEPSEEK_KEY": KEY, "check_key": "c"}, "keys": ["a"]}, False)
    assert got == {"cfg": {"HELP_ASSISTANT_DEEPSEEK_KEY": "***", "check_key": "***"}, "keys": ["a"]}, got


def case_snapshot_long_bootstrap_curl_is_redacted():
    curl = "curl 'https://onlyfans.com/api2/v2/users/me' -b 'sess=" + "s" * 5000 + "; auth_id=1'"
    snap = _safe_snapshot(json.dumps({"mode": "paste-curl", "curl": curl, "nickname": "N"}).encode(), keys_only=False)
    assert "sess=" not in snap and json.loads(snap) == {"mode": "paste-curl", "curl": "***", "nickname": "N"}, snap


def case_snapshot_non_json_credential_body_is_dropped():
    assert _safe_snapshot(b"typesafe=" + KEY.encode(), keys_only=True) is None
    assert _safe_snapshot(b"plain text", keys_only=False) == "plain text"


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def _alembic(url: str, fn, rev: str) -> None:
    prior = os.environ["CHATTERLY_DB_URL"]
    os.environ["CHATTERLY_DB_URL"] = url
    try:
        fn(_cfg(), rev)
    finally:
        os.environ["CHATTERLY_DB_URL"] = prior


def case_single_head():
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1 and REV in {r.revision for r in script.iterate_revisions(heads[0], PREV)}, heads
    assert script.get_revision(REV).down_revision == PREV


# (action, stored payload, payload after the scrub)
ROWS = [
    ("PUT /admin/my-llm-keys", {"typesafe": KEY, "deepseek": ""}, {"typesafe": "set", "deepseek": "cleared"}),
    ("PUT /admin/users/u1/llm-keys", {"admin_password": "***", "providers": {"deepseek": KEY}},
     {"admin_password": "***", "providers": {"deepseek": "set"}}),
    ("PUT /admin/secrets", {"HELP_ASSISTANT_ANTHROPIC_KEY": KEY, "SHARE_TOKEN": "***"},
     {"HELP_ASSISTANT_ANTHROPIC_KEY": "set", "SHARE_TOKEN": "***"}),
    ("POST /admin/session/bootstrap", {"mode": "paste-curl", "curl": "curl -b 'sess=" + KEY + "'"},
     {"mode": "paste-curl", "curl": "***"}),
    ("POST /admin/proxies/bulk", {"text": "1.2.3.4:80:u:" + KEY, "scheme": "http"},
     {"text": "set", "scheme": "set"}),
    ("POST /admin/session/fansly", {"token": KEY, "check_key": KEY, "accountId": "a1"},
     {"token": "***", "check_key": "set", "accountId": "set"}),
    ("POST /admin/employees", {"name": KEY}, {"name": KEY}),                  # not a credential write
    ("GET /admin/my-llm-keys", {"typesafe": KEY}, {"typesafe": KEY}),        # not that action
]
CUT = '{"mode": "paste-curl", "curl": "curl -b \'sess=' + KEY   # an old 4 KB cut: not JSON


def case_upgrade_scrubs_only_credential_rows():
    with tempfile.TemporaryDirectory(prefix="audit_scrub_") as tmp:
        url = f"sqlite:///{Path(tmp) / 'db.db'}"
        engine = sa.create_engine(url)
        Base.metadata.create_all(engine)
        with engine.begin() as con:
            for action, payload, _ in ROWS:
                con.execute(sa.text("INSERT INTO actions (action, payload_json, at) VALUES (:a, :p, '2026-11-01')"),
                            {"a": action, "p": json.dumps(payload)})
            con.execute(sa.text("INSERT INTO actions (action, payload_json, at) VALUES (:a, :p, '2026-11-01')"),
                        {"a": "POST /admin/session/bootstrap", "p": CUT})
        _alembic(url, command.stamp, PREV)
        _alembic(url, command.upgrade, REV)

        def _got():
            with engine.connect() as con:
                return [(a, p) for a, p in con.execute(sa.text("SELECT action, payload_json FROM actions ORDER BY id"))]
        got = _got()
        want = [(a, json.dumps(w)) for a, _, w in ROWS] + [("POST /admin/session/bootstrap", None)]
        assert got == want, got
        _alembic(url, command.downgrade, PREV)      # no-op
        _alembic(url, command.upgrade, REV)         # idempotent
        assert _got() == want, _got()
        engine.dispose()


def case_init_db_scrubs_once():
    import asyncio
    _harness.bootstrap()
    from db.engine import init_db
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        con.execute("DELETE FROM data_migrations WHERE name = '20261122_audit_credential_scrub'")
        con.execute("INSERT INTO actions (action, payload_json, at) VALUES ('PUT /admin/my-llm-keys', ?, "
                    "'2026-11-01')", (json.dumps({"typesafe": KEY}),))
        con.commit()
    finally:
        con.close()
    asyncio.run(init_db())
    con = sqlite3.connect(str(_harness.DB_PATH))
    try:
        assert con.execute("SELECT payload_json FROM actions").fetchall() == [('{"typesafe": "set"}',)]
        assert con.execute("SELECT 1 FROM data_migrations WHERE name = '20261122_audit_credential_scrub'").fetchone()
    finally:
        con.close()


_harness.run()
