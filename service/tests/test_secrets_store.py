#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB
_harness.bootstrap()

import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import asyncio  # noqa: E402
import uuid  # noqa: E402

import auth  # noqa: E402
import secrets_store  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import User  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="secrets_test_")) / "secrets.json"
secrets_store._PATH = _TMP


def _reset(**env):
    # auth._read_admin_password falls back to service/.env; a missing path keeps a dev machine's real password out.
    auth._ENV_FILE = _TMP.parent / "no-such.env"
    secrets_store._atomic_write({})
    for k in list(secrets_store.KNOWN):
        os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = v


async def _seed(username: str, is_admin: bool) -> str:
    uid = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(id=uid, username=username, password="pw", is_admin=is_admin))
    return uid


def _login(username: str):
    client = _harness.make_client()
    r = client.post("/auth/login", json={"username": username, "password": "pw"})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return client


def case_unset_when_empty():
    _reset()
    st = secrets_store.status()
    assert st["DEEPSEEK_API_KEY"]["set"] is False, st["DEEPSEEK_API_KEY"]
    assert st["DEEPSEEK_API_KEY"]["source"] == "unset", st["DEEPSEEK_API_KEY"]
    assert secrets_store.stored("DEEPSEEK_API_KEY") == ""


def case_set_and_mask():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-test123456"})
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-test123456"
    k = secrets_store.status()["DEEPSEEK_API_KEY"]
    assert k["set"] and k["source"] == "store", k
    assert k["hint"] == "••••3456", k["hint"]
    assert "test123456" not in k["hint"]


def case_store_beats_env():
    _reset(ZAI_API_KEY="env-key")
    k = secrets_store.status()["ZAI_API_KEY"]
    assert k["set"] and k["source"] == "env", k
    secrets_store.set_many({"ZAI_API_KEY": "store-key"})
    assert secrets_store.stored("ZAI_API_KEY") == "store-key"
    assert secrets_store.get("ZAI_API_KEY") == "store-key"
    assert secrets_store.status()["ZAI_API_KEY"]["source"] == "store"


def case_clear_removes():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-x"})
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-x"
    secrets_store.set_many({"DEEPSEEK_API_KEY": ""})
    assert secrets_store.stored("DEEPSEEK_API_KEY") == ""
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["set"] is False


def case_unknown_key_ignored():
    _reset()
    secrets_store.set_many({"NOT_A_REAL_KEY": "x", "DEEPSEEK_API_KEY": "ok"})
    assert "NOT_A_REAL_KEY" not in secrets_store.status()
    assert secrets_store.stored("NOT_A_REAL_KEY") == ""
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "ok"


def _with_known(name, meta, fn):
    secrets_store.KNOWN[name] = {"label": name, "group": "Test", **meta}
    try:
        fn()
    finally:
        secrets_store.KNOWN.pop(name, None)


def case_nonsecret_shows_value():
    _reset()

    def check():
        secrets_store.set_many({"_TEST_CONFIG_ID": "abc123XYZ"})
        k = secrets_store.status()["_TEST_CONFIG_ID"]
        assert k["secret"] is False and k["hint"] == "abc123XYZ", k
    _with_known("_TEST_CONFIG_ID", {"secret": False}, check)


def case_multiline_hint_is_length_only():
    _reset()
    blob = '{"refresh_token": "secret-value-here"}'

    def check():
        secrets_store.set_many({"_TEST_TOKEN_JSON": blob})
        k = secrets_store.status()["_TEST_TOKEN_JSON"]
        assert k["hint"] == f"•••• ({len(blob)} chars)", k["hint"]
        assert "secret-value" not in k["hint"]
    _with_known("_TEST_TOKEN_JSON", {"multiline": True}, check)


def case_masked_placeholder_is_refused_not_stored():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-real-value"})
    hint = secrets_store.status()["DEEPSEEK_API_KEY"]["hint"]
    try:
        secrets_store.set_many({"DEEPSEEK_API_KEY": hint})
        assert False, "the masked placeholder was stored as a secret"
    except ValueError as e:
        assert "masked placeholder" in str(e), f"unhelpful error: {e}"
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-real-value", \
        "the rejected write damaged the stored value"


def case_masked_write_over_http_is_a_400():
    _reset(SHARE_TOKEN="")
    asyncio.run(_seed("secrets_master", is_admin=True))
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-real-value"})
    client = _login("secrets_master")
    r = client.put("/admin/secrets", json={"DEEPSEEK_API_KEY": "••••alue"})
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-real-value"


def case_house_keys_are_master_only():
    _reset(SHARE_TOKEN="")
    asyncio.run(_seed("secrets_agency", is_admin=False))
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-house-value"})

    agency = _login("secrets_agency")
    assert agency.get("/admin/secrets").status_code == 403
    r = agency.put("/admin/secrets", json={"DEEPSEEK_API_KEY": "sk-stolen"})
    assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-house-value", \
        "a non-master overwrote the deployment's house key"

    anon = _harness.make_client()
    assert anon.get("/admin/secrets").status_code in (401, 403)

    asyncio.run(_seed("secrets_master2", is_admin=True))
    master = _login("secrets_master2")
    assert master.get("/admin/secrets").status_code == 200


def case_the_audit_row_keeps_house_key_names_never_values():
    import json
    from sqlalchemy import select
    from db.models import Action
    _reset(SHARE_TOKEN="")
    asyncio.run(_seed("secrets_audit_master", is_admin=True))
    master = _login("secrets_audit_master")
    r = master.put("/admin/secrets", json={"HELP_ASSISTANT_DEEPSEEK_KEY": "sk-house-audit-1234",
                                           "DEEPSEEK_API_KEY": ""})
    assert r.status_code == 200, r.text

    async def _rows():
        async with get_session() as s:
            return (await s.execute(select(Action.payload_json).where(
                Action.action == "PUT /admin/secrets"))).scalars().all()
    rows = asyncio.run(_rows())
    assert rows and all("sk-house-audit-1234" not in (p or "") for p in rows), rows
    assert json.loads(rows[-1]) == {"HELP_ASSISTANT_DEEPSEEK_KEY": "set", "DEEPSEEK_API_KEY": "cleared"}, rows


def case_founder_password_bootstraps_from_the_ui_then_locks():
    _reset()
    assert auth._read_admin_password() == "", "expected no password to start"

    secrets_store.set_many({"ADMIN_PASSWORD": "founder-pw"})
    assert secrets_store.stored("ADMIN_PASSWORD") == "founder-pw"
    assert auth._read_admin_password() == "founder-pw"

    for attempt in ("rotated-pw", "", None):
        try:
            secrets_store.set_many({"ADMIN_PASSWORD": attempt})
            assert False, f"the founder password was changed to {attempt!r} from the UI"
        except ValueError as e:
            assert "already configured" in str(e), f"unhelpful error: {e}"
    assert secrets_store.stored("ADMIN_PASSWORD") == "founder-pw", \
        "a refused write damaged the stored password"


def case_founder_password_still_falls_back_to_env():
    _reset(ADMIN_PASSWORD="from-env")
    assert auth._read_admin_password() == "from-env"
    try:
        secrets_store.set_many({"ADMIN_PASSWORD": "hijack"})
        assert False, "an env-configured founder password was overwritten"
    except ValueError as e:
        assert "already configured" in str(e)


def case_env_rotates_a_store_bootstrapped_founder_password():
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "bootstrapped-in-ui"})
    assert auth._read_admin_password() == "bootstrapped-in-ui"

    os.environ["ADMIN_PASSWORD"] = "rotated-in-env"
    assert auth._read_admin_password() == "rotated-in-env", \
        "the .env rotation DEPLOY.md documents did nothing — the stored value won"

    os.environ["ADMIN_PASSWORD"] = "   "
    assert auth._read_admin_password() == "bootstrapped-in-ui"


def case_status_reports_the_founder_password_env_first():
    _reset()
    import auth
    secrets_store.set_many({"ADMIN_PASSWORD": "bootstrapped"})
    assert secrets_store.status()["ADMIN_PASSWORD"]["source"] == "store"

    os.environ["ADMIN_PASSWORD"] = "rotated-in-env"
    st = secrets_store.status()["ADMIN_PASSWORD"]
    assert st["source"] == "env", f"the card still credits the superseded copy: {st}"
    assert st["set"] is True, st
    assert auth._read_admin_password() == "rotated-in-env", \
        "status() and the reader disagree about which value is live"

    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-from-ui"})
    os.environ["DEEPSEEK_API_KEY"] = "sk-from-env"
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["source"] == "store"


def case_a_superseded_founder_password_can_be_retired():
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "old-bootstrapped"})
    os.environ["ADMIN_PASSWORD"] = "live-from-env"

    secrets_store.set_many({"ADMIN_PASSWORD": ""})
    assert secrets_store.stored("ADMIN_PASSWORD") == "", "the dead copy survived"

    for attempt in ("session-chosen-pw", "another"):
        try:
            secrets_store.set_many({"ADMIN_PASSWORD": attempt})
            assert False, f"a session set the founder password to {attempt!r}"
        except ValueError as e:
            assert "already configured" in str(e), e

    os.environ.pop("ADMIN_PASSWORD", None)
    secrets_store._atomic_write({"ADMIN_PASSWORD": "only-copy"})
    try:
        secrets_store.set_many({"ADMIN_PASSWORD": ""})
        assert False, "the only copy of the founder password was cleared from the UI"
    except ValueError as e:
        assert "already configured" in str(e), e


def case_a_non_string_cannot_smuggle_past_the_founder_gate():
    for payload in (False, 0, 0.0, [], {}, {"a": 1}):
        _reset()
        secrets_store._atomic_write({"ADMIN_PASSWORD": "old-bootstrap"})
        os.environ["ADMIN_PASSWORD"] = "the-real-founder-password"
        try:
            secrets_store.set_many({"ADMIN_PASSWORD": payload})
            assert False, (
                f"a session planted the founder password via {payload!r} -> "
                f"{secrets_store.stored('ADMIN_PASSWORD')!r}")
        except ValueError as e:
            assert "expected a string" in str(e) or "already configured" in str(e), e
        assert secrets_store.stored("ADMIN_PASSWORD") == "old-bootstrap", \
            "the refused write still changed the stored value"

    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-working"})
    try:
        secrets_store.set_many({"DEEPSEEK_API_KEY": {"a": 1}})
        assert False, "an object was stored over a working house key"
    except ValueError as e:
        assert "expected a string" in str(e), e
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-working"


def case_clearable_matches_what_set_many_actually_permits():
    for key in ("ADMIN_PASSWORD", "DEEPSEEK_API_KEY"):
        for env in (None, "", "   ", "env-value"):
            _reset()
            secrets_store._atomic_write({key: "stored-value"})
            if env is not None:
                os.environ[key] = env
            flag = secrets_store.status()[key]["clearable"]
            try:
                secrets_store.set_many({key: ""})
                permitted = True
            except ValueError:
                permitted = False
            assert flag is permitted, (
                f"{key} env={env!r}: clear link {'shown' if flag else 'hidden'} "
                f"but the store {'permits' if permitted else 'refuses'} it")

    _reset(DEEPSEEK_API_KEY="only-in-env")
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["clearable"] is False


def case_a_bootstrap_only_secret_is_never_previewed():
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "correct-horse-battery"})
    st = secrets_store.status()["ADMIN_PASSWORD"]
    assert st["set"] is True, st
    assert st["hint"] == "••••••••", st
    for leak in ("horse", "tery", "correct", "battery"):
        assert leak not in st["hint"], f"the hint leaked {leak!r}: {st['hint']!r}"

    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-abcdefgh7132"})
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["hint"] == "••••7132"


def case_llm_provider_key_reads_store():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-from-ui"})
    import llm_providers
    assert llm_providers._api_key("DEEPSEEK_API_KEY") == "sk-from-ui"


def _count_opens(fn):
    import builtins
    real_open, seen = builtins.open, 0

    def _counting_open(file, *a, **kw):
        nonlocal seen
        if str(file) == str(secrets_store._PATH):
            seen += 1
        return real_open(file, *a, **kw)

    builtins.open = _counting_open
    try:
        fn()
    finally:
        builtins.open = real_open
    return seen


def case_repeat_reads_cost_no_descriptor():
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "tok-abc"})
    opens = _count_opens(lambda: [secrets_store.stored("SHARE_TOKEN")
                                  for _ in range(200)])
    assert opens == 0, (
        f"200 gate checks opened secrets.json {opens} times — this runs on "
        "every single request"
    )


def case_out_of_process_write_is_seen():
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "before"})
    assert secrets_store.stored("SHARE_TOKEN") == "before"
    secrets_store._PATH.write_text('{"SHARE_TOKEN": "after-a-longer-value"}')
    assert secrets_store.stored("SHARE_TOKEN") == "after-a-longer-value", \
        "a write that bypassed set_many was masked by the cache"


def case_unreadable_file_keeps_the_token():
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "still-the-real-token"})
    assert secrets_store.stored("SHARE_TOKEN") == "still-the-real-token"

    import builtins
    real_open = builtins.open

    def _emfile_open(file, *a, **kw):
        if str(file) == str(secrets_store._PATH):
            raise OSError(24, "Too many open files", str(file))
        return real_open(file, *a, **kw)

    secrets_store._PATH.write_text('{"SHARE_TOKEN": "still-the-real-token"}')
    builtins.open = _emfile_open
    try:
        got = secrets_store.stored("SHARE_TOKEN")
    finally:
        builtins.open = real_open
    assert got == "still-the-real-token", (
        f"fd exhaustion silently changed the access token to {got!r} — the "
        "gate must not move because the process ran out of descriptors"
    )


_harness.run(
    case_unset_when_empty,
    case_set_and_mask,
    case_store_beats_env,
    case_clear_removes,
    case_unknown_key_ignored,
    case_nonsecret_shows_value,
    case_multiline_hint_is_length_only,
    case_masked_placeholder_is_refused_not_stored,
    case_masked_write_over_http_is_a_400,
    case_house_keys_are_master_only,
    case_the_audit_row_keeps_house_key_names_never_values,
    case_founder_password_bootstraps_from_the_ui_then_locks,
    case_founder_password_still_falls_back_to_env,
    case_env_rotates_a_store_bootstrapped_founder_password,
    case_status_reports_the_founder_password_env_first,
    case_a_superseded_founder_password_can_be_retired,
    case_a_non_string_cannot_smuggle_past_the_founder_gate,
    case_clearable_matches_what_set_many_actually_permits,
    case_a_bootstrap_only_secret_is_never_previewed,
    case_llm_provider_key_reads_store,
    case_repeat_reads_cost_no_descriptor,
    case_out_of_process_write_is_seen,
    case_unreadable_file_keeps_the_token,
)
