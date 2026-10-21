#!/usr/bin/env python3
"""Setup → Keys store (secrets_store) + its consumer wiring.

A value pasted into the UI lands in service/secrets.json and must (a) win over
the process env, (b) be reported back only masked, (c) take effect for the
actual consumers (llm_client provider keys) without a
restart.

Run: ./venv/bin/python service/tests/test_secrets_store.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
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

# Point the store at a throwaway file so we never touch a real secrets.json.
_TMP = Path(tempfile.mkdtemp(prefix="secrets_test_")) / "secrets.json"
secrets_store._PATH = _TMP


def _reset(**env):
    # `auth._read_admin_password` falls back to reading service/.env directly,
    # so a developer machine with a real ADMIN_PASSWORD in that file would make
    # every case here see a password it never set — and the two rotation cases
    # would pass or fail depending on whose laptop ran them. Point it at a path
    # that does not exist; the cases that WANT an env value set os.environ.
    auth._ENV_FILE = _TMP.parent / "no-such.env"
    secrets_store._atomic_write({})
    # clear any env the store consults for the keys under test
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
    """A signed-in client. These routes are role-gated, so every HTTP case here
    needs a real principal — `ALLOW_ANONYMOUS_ADMIN` resolves to no user and is
    therefore refused, which is the point of the gate."""
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
    # masked: last 4 only, never the raw value
    assert k["hint"] == "••••3456", k["hint"]
    assert "test123456" not in k["hint"]


def case_store_beats_env():
    _reset(ZAI_API_KEY="env-key")
    # env-only → reported as set via env
    k = secrets_store.status()["ZAI_API_KEY"]
    assert k["set"] and k["source"] == "env", k
    # store value overrides env
    secrets_store.set_many({"ZAI_API_KEY": "store-key"})
    assert secrets_store.stored("ZAI_API_KEY") == "store-key"
    assert secrets_store.get("ZAI_API_KEY") == "store-key"
    assert secrets_store.status()["ZAI_API_KEY"]["source"] == "store"


def case_clear_removes():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-x"})
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-x"
    secrets_store.set_many({"DEEPSEEK_API_KEY": ""})  # empty clears
    assert secrets_store.stored("DEEPSEEK_API_KEY") == ""
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["set"] is False


def case_unknown_key_ignored():
    _reset()
    secrets_store.set_many({"NOT_A_REAL_KEY": "x", "DEEPSEEK_API_KEY": "ok"})
    assert "NOT_A_REAL_KEY" not in secrets_store.status()
    assert secrets_store.stored("NOT_A_REAL_KEY") == ""
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "ok"


def _with_known(name, meta, fn):
    """Run `fn` with a temporary KNOWN entry (no shipped key is non-secret or
    multiline today; the store still supports both flags)."""
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
    """The status view renders `••••abcd` as a hint. A form that round-trips that
    back — or an operator retyping what they see — must not replace a working
    secret with bullets. It RAISES rather than dropping the field, so the caller
    cannot report "Saved" for a write that did not happen."""
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
    """...and the endpoint turns that refusal into a 400 rather than a 500."""
    # _reset() pops every KNOWN key (SHARE_TOKEN included, so restore it empty);
    # the route itself is master-only, hence the login.
    _reset(SHARE_TOKEN="")
    asyncio.run(_seed("secrets_master", is_admin=True))
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-real-value"})
    client = _login("secrets_master")
    r = client.put("/admin/secrets", json={"DEEPSEEK_API_KEY": "••••alue"})
    assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-real-value"


def case_house_keys_are_master_only():
    """These are the SERVER's keys, not a tenant's.

    Both verbs were ungated from the day they were written, while a comment
    above them claimed otherwise — and `/auth/register` is open, so ANY agency
    that signed up could read the masked house-key status and overwrite the
    deployment's credentials. The READ is gated too: the hint still exposes the
    last four characters of every house key.

    An anonymous caller is refused for the same reason a non-master is — the
    role has to be proven, not merely un-contradicted.
    """
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

    # ...and the founder still gets through, or the gate is just an outage.
    asyncio.run(_seed("secrets_master2", is_admin=True))
    master = _login("secrets_master2")
    assert master.get("/admin/secrets").status_code == 200


def case_founder_password_bootstraps_from_the_ui_then_locks():
    """The second factor has to be settable once, and only once, from here.

    This deployment shipped with ADMIN_PASSWORD undocumented AND unset, so every
    founder-only write answered 503 — a second factor nobody can configure is
    not a second factor. But the page that edits this store is gated by the
    master SESSION, so if a session could ROTATE the password the two factors
    would collapse into one and a stolen cookie would be the whole defence.
    Create yes, change no.
    """
    _reset()
    assert auth._read_admin_password() == "", "expected no password to start"

    secrets_store.set_many({"ADMIN_PASSWORD": "founder-pw"})
    assert secrets_store.stored("ADMIN_PASSWORD") == "founder-pw"
    # ...and the gate now actually reads it, which the env-only version did not.
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
    """An operator who set it the old way must not be locked out by the new
    store lookup, and the store must not let a session overwrite theirs."""
    _reset(ADMIN_PASSWORD="from-env")
    assert auth._read_admin_password() == "from-env"
    try:
        secrets_store.set_many({"ADMIN_PASSWORD": "hijack"})
        assert False, "an env-configured founder password was overwritten"
    except ValueError as e:
        assert "already configured" in str(e)


def case_env_rotates_a_store_bootstrapped_founder_password():
    """The documented rotation path has to actually rotate.

    `secrets_store.get` is store-first, which is right for keys the UI owns —
    but ADMIN_PASSWORD is ALSO bootstrap-only, and the two together made a
    UI-set password PERMANENT: the store refused to change it, and a new `.env`
    value could never outrank it. Both the refusal message and DEPLOY.md tell
    the operator to rotate in `.env`, so store-first turned the only documented
    escape into a silent no-op. Its one reader is env-first for exactly this.
    """
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "bootstrapped-in-ui"})
    assert auth._read_admin_password() == "bootstrapped-in-ui"

    os.environ["ADMIN_PASSWORD"] = "rotated-in-env"
    assert auth._read_admin_password() == "rotated-in-env", \
        "the .env rotation DEPLOY.md documents did nothing — the stored value won"

    # And the stale store value must not come back when the env is cleared to
    # something empty-ish rather than removed.
    os.environ["ADMIN_PASSWORD"] = "   "
    assert auth._read_admin_password() == "bootstrapped-in-ui"


def case_status_reports_the_founder_password_env_first():
    """The card must name the value that is actually in force.

    `status()` is store-first for every key, which is right — except the one
    whose READER is env-first. Reporting store-first there shows "set · via UI"
    with the stored hint while every founder write is being checked against the
    environment, i.e. the card names a dead credential as the live one.
    """
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

    # An ordinary key stays store-first — the exception is narrow on purpose.
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-from-ui"})
    os.environ["DEEPSEEK_API_KEY"] = "sk-from-env"
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["source"] == "store"


def case_a_superseded_founder_password_can_be_retired():
    """Retiring a copy the env has already replaced is not a rotation.

    Once the environment carries the live password the store row is a dead
    credential — and one that comes back to life the moment the env var goes
    missing, on a file that now survives deploys. So a CLEAR is allowed while
    the env holds a value, and nothing else is: a session still cannot set or
    change the password actually in force.
    """
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "old-bootstrapped"})
    os.environ["ADMIN_PASSWORD"] = "live-from-env"

    secrets_store.set_many({"ADMIN_PASSWORD": ""})
    assert secrets_store.stored("ADMIN_PASSWORD") == "", "the dead copy survived"

    # ...but a session still cannot CHANGE the live one, nor plant a new copy.
    for attempt in ("session-chosen-pw", "another"):
        try:
            secrets_store.set_many({"ADMIN_PASSWORD": attempt})
            assert False, f"a session set the founder password to {attempt!r}"
        except ValueError as e:
            assert "already configured" in str(e), e

    # And with NO env value, the clear is refused as before — that is a rotation.
    os.environ.pop("ADMIN_PASSWORD", None)
    secrets_store._atomic_write({"ADMIN_PASSWORD": "only-copy"})
    try:
        secrets_store.set_many({"ADMIN_PASSWORD": ""})
        assert False, "the only copy of the founder password was cleared from the UI"
    except ValueError as e:
        assert "already configured" in str(e), e


def case_a_non_string_cannot_smuggle_past_the_founder_gate():
    """Type confusion between the gate and the writer let a session CHOOSE the
    founder password — the one thing _BOOTSTRAP_ONLY exists to forbid.

    The gate asked `not str(raw or "").strip()`, so a falsy non-string (False,
    0, [], {}) read as BLANK and took the permitted "retire the superseded copy"
    branch. The write loop then coerced the same value with `str(v)` and saw the
    TRUTHY "False" / "0" / "[]", so it stored it. The planted row is dormant
    while the env holds a value and becomes the live second factor the moment
    that env var goes missing — and knowing ADMIN_PASSWORD alone is enough to
    grant, revoke, transfer and delete.

    The sibling store already rejected this class at the boundary
    (`tenant_keys.set_keys`); this one now does too.
    """
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

    # ...and the same coercion silently overwrote ordinary keys with a repr.
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-working"})
    try:
        secrets_store.set_many({"DEEPSEEK_API_KEY": {"a": 1}})
        assert False, "an object was stored over a working house key"
    except ValueError as e:
        assert "expected a string" in str(e), e
    assert secrets_store.stored("DEEPSEEK_API_KEY") == "sk-working"


def case_clearable_matches_what_set_many_actually_permits():
    """The clear affordance is the server's answer, not the UI's guess.

    KeysCard used to derive it from `source`, which answers a different question
    — and for a bootstrap-only key the exactly complementary one, so the link
    appeared in the one state the store refuses and vanished in the one state it
    permits. This walks every state that has something to clear and asserts the
    flag and the store agree.
    """
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

    # Nothing stored ⇒ nothing to remove ⇒ no link, whatever the env says.
    _reset(DEEPSEEK_API_KEY="only-in-env")
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["clearable"] is False


def case_a_bootstrap_only_secret_is_never_previewed():
    """`mask` shows the last four characters — a fine tail for `sk-…7132`, a
    real leak for a passphrase, and it also reveals the short-vs-long length
    bucket. Nobody needs to RECOGNISE the founder password in a list; they only
    need to know one is set."""
    _reset()
    secrets_store.set_many({"ADMIN_PASSWORD": "correct-horse-battery"})
    st = secrets_store.status()["ADMIN_PASSWORD"]
    assert st["set"] is True, st
    assert st["hint"] == "••••••••", st
    for leak in ("horse", "tery", "correct", "battery"):
        assert leak not in st["hint"], f"the hint leaked {leak!r}: {st['hint']!r}"

    # An API key in the same store still gets its recognisable tail.
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-abcdefgh7132"})
    assert secrets_store.status()["DEEPSEEK_API_KEY"]["hint"] == "••••7132"


def case_llm_provider_key_reads_store():
    _reset()
    secrets_store.set_many({"DEEPSEEK_API_KEY": "sk-from-ui"})
    import llm_providers
    assert llm_providers._api_key("DEEPSEEK_API_KEY") == "sk-from-ui"


def _count_opens(fn):
    """Run `fn`, returning how many times it open()ed the store file."""
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
    """`_effective_share_token` calls this in the OUTERMOST middleware, so an
    unconditional open() here was one descriptor per request in the hottest
    path in the process — and descriptors are what the relay runs out of."""
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "tok-abc"})
    opens = _count_opens(lambda: [secrets_store.stored("SHARE_TOKEN")
                                  for _ in range(200)])
    assert opens == 0, (
        f"200 gate checks opened secrets.json {opens} times — this runs on "
        "every single request"
    )


def case_out_of_process_write_is_seen():
    """The cache must not outlive the file. A hand-edited secrets.json (or one
    written by another worker) has to land on the very next read — a stale
    access token is a lockout or an open door, depending which way it went."""
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "before"})
    assert secrets_store.stored("SHARE_TOKEN") == "before"
    # Deliberately NOT via set_many — this is the out-of-process path.
    secrets_store._PATH.write_text('{"SHARE_TOKEN": "after-a-longer-value"}')
    assert secrets_store.stored("SHARE_TOKEN") == "after-a-longer-value", \
        "a write that bypassed set_many was masked by the cache"


def case_unreadable_file_keeps_the_token():
    """The security-shaped one. `_load` used to answer {} for ANY read error,
    and `_effective_share_token` then fell back to the env default — so a
    transient fd shortage silently SWAPPED the live access token, and the gate
    changed because the process was busy. Serve the last known good instead."""
    _reset()
    secrets_store.set_many({"SHARE_TOKEN": "still-the-real-token"})
    assert secrets_store.stored("SHARE_TOKEN") == "still-the-real-token"

    import builtins
    real_open = builtins.open

    def _emfile_open(file, *a, **kw):
        if str(file) == str(secrets_store._PATH):
            raise OSError(24, "Too many open files", str(file))
        return real_open(file, *a, **kw)

    # Force a stamp change so the read is actually attempted, then break it.
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
