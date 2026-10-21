#!/usr/bin/env python3
"""The Vault import status read says whether the Drive import is on
(docs/spec/infloww-parity-round-2/phase-05-drive-import.md, Testing Decisions, Seam 2; ticket 46).

`GET /api/of/v2/vault/upload/status` carries `drive_import_configured` on every answer, the no-run answer included,
resolved by the Drive key's own reader (`gdrive.api_key()`: the secrets store first, then the environment). The key,
or any hint of it, never leaves the relay, and the field does not open the route to another Agency.

  1. key unset: Owner A's status for A's Creator is 200 with the field false, on the no-run path.
  2. a fake key in the store: true, and the response text holds neither the value nor its last four characters.
  3. a key only in the environment: true (the reader's fallback).
  4. a seeded finished run on the spool: the run path still carries the field.
  5. Owner B asking for A's Creator still gets 403.
  6. every answer carries `upload_limits`, this server's own per-file size limit and files per import, the
     `VAULT_UPLOAD_MAX_MB` and `VAULT_UPLOAD_MAX_FILES` the batch route enforces (ticket 58: the import card's rules row
     shows them in place of Infloww's limits): case 1 checks the no-run answer, case 6 a named run.

Offline by construction: no case resolves or downloads a Drive link, and `gdrive._session` (the module's one session
factory, which every Drive call goes through) is replaced with a function that raises. The vault spool is a
`tempfile.mkdtemp` tree, the secrets store is the harness's throwaway file, and the key is removed from the process
environment at the start.

Run: ./venv/bin/python service/tests/test_vault_drive_configured.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ.pop("GOOGLE_DRIVE_API_KEY", None)
_SPOOL = Path(tempfile.mkdtemp(prefix="vault_drive_configured_spool_"))
os.environ["VAULT_SPOOL_DIR"] = str(_SPOOL)
# Off the defaults (4000 MB, 40 files), so case 6 proves the answer is the configured limit, not a constant.
os.environ["VAULT_UPLOAD_MAX_MB"] = "1234"
os.environ["VAULT_UPLOAD_MAX_FILES"] = "7"

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import gdrive  # noqa: E402
import secrets_store  # noqa: E402
import vault_upload  # noqa: E402

vault_upload.SPOOL_ROOT = _SPOOL
vault_upload.LOCK_DIR = _SPOOL / "locks"


def _no_network(*_a, **_k):
    raise AssertionError("a Drive session was opened: the status read must not contact Google")


gdrive._session = _no_network

IDS = fx.seed_two_agencies()
CREATOR_A = IDS["creator_a"]
account_registry.upsert_account(CREATOR_A, nickname="Drive Creator Alpha")
account_registry.upsert_account(IDS["creator_b"], nickname="Drive Creator Beta")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")

FAKE_KEY = "test-drive-key-not-real"
LIMITS = {"max_file_mb": 1234, "max_files": 7}
STATUS = "/api/of/v2/vault/upload/status"


def _status(client, account_id: str = CREATOR_A):
    return client.get(STATUS, headers={"X-Account-Id": account_id})


def _clear_key():
    secrets_store.set_many({"GOOGLE_DRIVE_API_KEY": None})
    os.environ.pop("GOOGLE_DRIVE_API_KEY", None)


def case_1_key_unset_reads_false_on_the_no_run_answer():
    _clear_key()
    r = _status(OWNER_A)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    body = r.json()
    assert body.get("run") is None and body.get("running") is False, body
    assert body.get("drive_import_configured") is False, body
    assert body.get("upload_limits") == LIMITS, body


def case_2_key_in_the_store_reads_true_and_never_leaves():
    _clear_key()
    secrets_store.set_many({"GOOGLE_DRIVE_API_KEY": FAKE_KEY})
    try:
        r = _status(OWNER_A)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json().get("drive_import_configured") is True, r.json()
        assert FAKE_KEY not in r.text, "the key's value is in the status answer"
        assert FAKE_KEY[-4:] not in r.text, "the key's last four characters are in the status answer"
    finally:
        _clear_key()


def case_3_key_only_in_the_environment_reads_true():
    _clear_key()
    os.environ["GOOGLE_DRIVE_API_KEY"] = FAKE_KEY
    try:
        r = _status(OWNER_A)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json().get("drive_import_configured") is True, r.json()
        assert FAKE_KEY not in r.text and FAKE_KEY[-4:] not in r.text, "the key leaked"
    finally:
        _clear_key()


def case_4_a_finished_run_still_carries_the_field():
    _clear_key()
    run_id = f"{CREATOR_A}-20261017T120000-abcdef"
    d = _SPOOL / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "account_id": CREATOR_A, "status": "done", "phase": "finished",
        "created_at": "2026-10-17T12:00:00+00:00", "finished_at": "2026-10-17T12:01:00+00:00",
        "error": None, "items": [{"name": "placeholder.jpg", "source": "local", "size": 1, "status": "done",
                                  "error": None, "vault_id": 1, "deduped": False}],
    }))
    r = _status(OWNER_A)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    body = r.json()
    assert body.get("run_id") == run_id, body
    assert body.get("drive_import_configured") is False, body
    secrets_store.set_many({"GOOGLE_DRIVE_API_KEY": FAKE_KEY})
    try:
        r = _status(OWNER_A)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert r.json().get("run_id") == run_id and r.json().get("drive_import_configured") is True, r.json()
        assert FAKE_KEY not in r.text and FAKE_KEY[-4:] not in r.text, "the key leaked on the run path"
    finally:
        _clear_key()


def case_5_owner_b_still_gets_403_for_owner_a_creator():
    secrets_store.set_many({"GOOGLE_DRIVE_API_KEY": FAKE_KEY})
    try:
        r = _status(OWNER_B)
        assert r.status_code == 403, f"Owner B reads A's import status: {r.status_code} {r.text}"
        assert "drive_import_configured" not in r.text, r.text
    finally:
        _clear_key()


def case_6_a_named_run_carries_this_servers_upload_limits():
    run_id = f"{CREATOR_A}-20261017T130000-abcdef"
    d = _SPOOL / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "account_id": CREATOR_A, "status": "done", "phase": "finished",
        "created_at": "2026-10-17T13:00:00+00:00", "finished_at": "2026-10-17T13:01:00+00:00",
        "error": None, "items": [],
    }))
    r = OWNER_A.get(f"{STATUS}?run_id={run_id}", headers={"X-Account-Id": CREATOR_A})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json().get("run_id") == run_id and r.json().get("upload_limits") == LIMITS, r.json()


if __name__ == "__main__":
    _harness.run()
