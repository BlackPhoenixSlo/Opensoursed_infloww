#!/usr/bin/env python3
"""
`_account_isolation_middleware` — the defense-in-depth gate that 403s a
request naming an account the signed-in principal doesn't own.

It is the ONLY cross-account check on most per-account endpoints (8
`assert_account_owned` call sites against 58 `/admin/*` routes plus all of
`/api/of/*`), and until now it had no direct test at all.

Why these cases exist. The gate used to ask `list_account_ids()` for the whole
id set and 403 on `cand in all_ids and cand not in allowed_ids`. That helper
swallowed OSError and returned an empty set — and an empty set makes the `in`
test False for every candidate, so the gate returned **200, not 403**. During
the 2026-07-28 / 07-30 fd exhaustions the isolation gate therefore switched
itself off exactly when the process was degraded. "Couldn't read the account
tree" and "not an account" were the same answer, and the caller reads the
second one as "let it through".

It now asks `is_account(cand)` — one `stat(2)`, which takes a path rather
than a descriptor and so keeps answering while the process is out of fds.
Case 4 pins that; case 5 pins that a tree we genuinely cannot read raises
instead of quietly allowing; case 6 pins every READ surface against the raw
`?account_id=` query param it is handed verbatim; case 7 pins the other half —
writers must RAISE on the same inputs, and must do so before touching disk.

Plain-assert standalone script (no pytest), run via:

    ./venv/bin/python service/tests/test_account_isolation_gate.py

Exit 0 = all pass.
"""
from __future__ import annotations

import asyncio
import errno
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlencode

# ── Hard-bind a throwaway DB BEFORE importing any service module (same
# PROD-fallback guard as the other service tests).
_TMP_DB = Path(tempfile.gettempdir()) / f"chatterly_isogate_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")

HERE = Path(__file__).resolve().parent
SERVICE_ROOT = HERE.parent
sys.path.insert(0, str(SERVICE_ROOT))

from starlette.responses import Response  # noqa: E402

import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import server  # noqa: E402

_MINE = "8000149"
_THEIRS = "800000075"
_NOT_AN_ACCOUNT = "8675309"   # account-SHAPED (5-12 digits) but a fan id


def _sandbox_accounts() -> None:
    """A real on-disk account tree, so `is_account` does real syscalls."""
    root = Path(tempfile.gettempdir()) / f"chatterly_isogate_{uuid.uuid4().hex}"
    account_registry.SESSIONS_DIR = root
    account_registry.ACCOUNTS_DIR = root / "accounts"
    for aid in (_MINE, _THEIRS):
        (account_registry.ACCOUNTS_DIR / aid).mkdir(parents=True)


async def _gate(path: str, query: bytes = b"", *, signed_in: bool = True) -> Response:
    """Drive the real middleware for `path` as a user who owns only _MINE.

    `signed_in=False` drives it with NO principal at all — the anonymous
    caller the gate used to wave straight through (cases 12-15).

    `query` is real: the middleware's other candidate source is `?account_id=`,
    taken verbatim with no shape filter at all (the path scan at least demands
    5-12 digits). Case 6 is the only caller that sets it, and before it did,
    nothing here had ever exercised that half of the gate.

    Exceptions propagate deliberately. An earlier version funnelled them into
    the return value, which made a negative assertion ("did not return 200")
    pass for ANY escaping exception — including one the case never meant to
    allow. A case that expects a raise has to say which one.
    """
    from starlette.requests import Request

    request = Request({
        "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
        "query_string": query, "headers": [], "scheme": "http",
        "server": ("test", 80), "client": ("test", 1),
    })

    async def _call_next(_req):
        return Response("allowed through", status_code=200)

    token = auth._request_user.set(
        auth.AuthedUser(id_="u1", username="friend", account_ids=frozenset({_MINE}))
        if signed_in else None
    )
    try:
        return await server._account_isolation_middleware(request, _call_next)
    finally:
        auth._request_user.reset(token)


async def main() -> None:
    _sandbox_accounts()

    # ── Case 1: my own account passes. Without this, a gate that 403'd
    #            everything would satisfy every other case.
    res = await _gate(f"/admin/vault/{_MINE}/items")
    assert res.status_code == 200, f"case1: own account was blocked: {res.status_code}"

    # ── Case 2: someone else's REAL account is refused.
    res = await _gate(f"/admin/vault/{_THEIRS}/items")
    assert res.status_code == 403, f"case2: cross-account request was allowed: {res.status_code}"

    # ── Case 3: an account-shaped id that is NOT an account passes — that is
    #            the documented false-positive domain (fan ids share the shape).
    res = await _gate(f"/admin/fan/{_NOT_AN_ACCOUNT}/notes")
    assert res.status_code == 200, \
        f"case3: a fan id was mistaken for an account: {res.status_code}"

    # ── Case 4: THE REGRESSION. Under fd exhaustion the gate must still
    #            refuse. `iterdir`/scandir needs a descriptor and dies; `stat`
    #            does not. Killing iterdir proves the gate no longer depends
    #            on it — with the old set-scan it returned 200 here.
    real_iterdir = Path.iterdir

    def _emfile_iterdir(self):
        raise OSError(24, "Too many open files", str(self))

    Path.iterdir = _emfile_iterdir
    try:
        res = await _gate(f"/admin/vault/{_THEIRS}/items")
    finally:
        Path.iterdir = real_iterdir
    assert res.status_code == 403, (
        "case4: fd exhaustion turned the isolation gate OFF — cross-account "
        f"request got {res.status_code}, expected 403"
    )

    # ── Case 5: a tree we genuinely cannot read (EACCES) must NOT be read as
    #            "not an account". The OSError propagating is the correct
    #            outcome — it denies loudly. Assert THAT error, not merely
    #            "something other than 200": a bare negative would be
    #            satisfied by any unrelated exception a later refactor added.
    real_stat, raised = Path.stat, None

    def _eacces_stat(self, *a, **kw):
        raise OSError(errno.EACCES, "Permission denied", str(self))

    Path.stat = _eacces_stat
    try:
        res = await _gate(f"/admin/vault/{_THEIRS}/items")
    except OSError as e:
        raised = e
    finally:
        Path.stat = real_stat
    assert raised is not None and raised.errno == errno.EACCES, (
        "case5: an unreadable account tree was resolved to a verdict instead "
        f"of raising — got {res.status_code if raised is None else raised!r}"
    )

    # ── Case 6: ONE hostile-input table, asserted against EVERY read surface.
    #
    #  Each of these ids shipped past a guard that claimed to cover it, and
    #  each of the last three rounds fixed one reader and left the next one
    #  raising — because every reader owned a private copy of the rule. So
    #  the table is the fixture and the readers are the parameters: adding a
    #  reader below is how you find out it forgot the rule.
    #
    #  A reader must ANSWER ("not an account"), never raise. A raise out of a
    #  reader is a 500 per request for any authed principal — `get_account` is
    #  the first statement of all three /admin/accounts/{id} routes, which is
    #  where the ENAMETOOLONG 500 survived a round of "fixing" it.
    #
    #  Writers are deliberately absent: save_meta, record_session and
    #  delete_account's rmtree must keep RAISING on these. That asymmetry is
    #  the design, and case 7 pins it.
    for bad, why in (
        ("/etc", "an absolute id replaces the join and answered True for /etc"),
        ("../../../etc", "traversal escaped the account tree"),
        ("9" * 3000, "an over-long id raised ENAMETOOLONG — a 500 per request"),
        # NAME_MAX is 255 BYTES. 200 emoji is 200 characters and 800 bytes, so
        # a `len(str)` guard waves it through into ENAMETOOLONG — the same 500,
        # one encoding away. This is the door the character-count guard left.
        ("\U0001F642" * 200, "a multibyte id passed a character-count guard"),
        # NUL is legal in a str and illegal in a path: it clears every shape
        # clause, then makes mkdir/write_text/rmtree raise ValueError — the
        # same type `account_dir` raises to MEAN "not an account", so the
        # verdict and a filesystem refusal became indistinguishable. That
        # collision is why the verdict is now its own type, `NotAnAccountId`.
        ("a\x00b", "a NUL byte passed the shape guard"),
        # A lone surrogate is the third of that kind, and the nastiest: the
        # guard's OWN NAME_MAX clause, `aid.encode()`, raises on it. While the
        # verdict was a bare ValueError, `_account_path` swallowed that
        # UnicodeEncodeError and returned the right answer BY ACCIDENT.
        # Reachable — `_ActivateBody.account_id` is a plain str handed to
        # `get_account` (server.py:6898) and `json.loads('"\\ud800"')` yields
        # one from an all-ASCII request body. The three reader asserts below
        # carry the real surrogate; the middleware leg cannot, because
        # Starlette's query decoder replaces it with U+FFFD (also a fine
        # non-account, so the assertion still holds — it just proves less).
        ("\ud800", "a lone surrogate raised out of the guard's own length check"),
        ("", "the empty id resolved to ACCOUNTS_DIR itself and answered True"),
        (".", "'.' resolved to ACCOUNTS_DIR itself"),
        ("..", "'..' resolved to the parent of the account tree"),
    ):
        assert account_registry.is_account(bad) is False, f"case6 is_account: {why}"
        assert account_registry.get_account(bad) is None, f"case6 get_account: {why}"
        assert account_registry.latest_session_path(bad) is None, \
            f"case6 latest_session_path: {why}"
        # …and end-to-end through the middleware, with the id really in the
        # query string — the one candidate source that gets no shape filter.
        res = await _gate("/admin/vault/items",
                          urlencode({"account_id": bad}, errors="surrogatepass").encode())
        assert res.status_code == 200, f"case6 middleware: {why} -> {res.status_code}"

    assert account_registry.is_account(_MINE) is True, \
        "case6: the shape guard rejected a REAL account id"
    assert account_registry.is_account(_NOT_AN_ACCOUNT) is False, \
        "case6: a well-formed non-account id was accepted"

    # A REAL foreign account named in the query string is still refused — the
    # table above must not have been satisfied by a gate that stopped looking
    # at query params at all.
    res = await _gate("/admin/vault/items", urlencode({"account_id": _THEIRS}).encode())
    assert res.status_code == 403, \
        f"case6: foreign account via ?account_id= was allowed: {res.status_code}"

    # A poisoned active.json must not raise on every subsequent request.
    # `set_active_account_id` is the one write that does NOT go through
    # `account_dir`, so a bad id can reach the file — and
    # `get_active_account_id` is then read by of_client and
    # four routes, i.e. nearly every request path. It has to fall back.
    account_registry.set_active_account_id("../../../etc")
    assert account_registry.get_active_account_id() is None, \
        "case6: a poisoned active.json did not fall back"
    account_registry.set_active_account_id(None)

    # ── Case 7: the other half of the contract. Readers answer; WRITERS raise.
    #            A write that can't name its target must not guess one — a
    #            silent fallback here would `mkdir`/`rmtree` outside the
    #            account tree. This is why `_account_path` exists as a
    #            reader-only door instead of `account_dir` simply not raising.
    #
    #  THIS CASE ONLY MEANS ANYTHING WHILE THE GUARD IS BROKEN. That is what a
    #  RED proof is, and every round of this fix has produced one by deleting a
    #  clause and re-running this file — so the case has to be safe to run in
    #  exactly that state. It named `/etc` before, and it was not: with the
    #  `"/" in aid` clause removed, `save_meta` wrote /etc/meta.json and
    #  `delete_account` reached `shutil.rmtree(Path("/etc"))` — its `is_dir()`
    #  check waves a real directory straight through, and the relay container
    #  runs as root. A test must never depend for its own safety on the
    #  invariant it exists to test.
    #
    #  So: a disposable tree, nested deep enough that nothing below can name
    #  anything outside it, plus a canary we assert is UNTOUCHED. The canary is
    #  strictly stronger than "it raised" — it also catches a writer that
    #  deletes first and refuses second, which no exception assertion can see.
    blast = Path(tempfile.mkdtemp(prefix="chatterly_isogate_blast_"))
    canary = blast / "canary"
    canary.mkdir()
    (canary / "keep.txt").write_text("untouched")
    real_accounts_dir = account_registry.ACCOUNTS_DIR
    account_registry.ACCOUNTS_DIR = blast / "a" / "b" / "accounts"
    account_registry.ACCOUNTS_DIR.mkdir(parents=True)
    try:
        for bad in (
            str(canary),        # absolute — replaces the join outright
            "../../../canary",  # traversal — from a/b/accounts that IS the canary
            "a\x00b",           # NUL: mkdir/rmtree raise ValueError of their own
            "\ud800",           # surrogate: the guard's own encode() raises
            "",                 # resolves to ACCOUNTS_DIR itself
            "..",               # resolves to its parent
        ):
            for label, call in (
                ("save_meta", lambda: account_registry.save_meta(bad, {"id": bad})),
                ("record_session", lambda: account_registry.record_session(
                    bad, Path("session_20260101T000000Z.json"))),
                ("delete_account", lambda: account_registry.delete_account(bad)),
            ):
                try:
                    call()
                except account_registry.NotAnAccountId:
                    # The verdict is a TYPE now, so this needs no string match.
                    # A ValueError from BELOW the guard — mkdir's embedded NUL,
                    # encode()'s surrogate — is not caught here and escapes the
                    # test uncaught, which is louder than a failed assert.
                    continue
                raise AssertionError(
                    f"case7: {label}({bad[:20]!r}) did NOT raise NotAnAccountId "
                    "— a write accepted an id that cannot name a directory in "
                    "the account tree"
                )
            assert (canary / "keep.txt").read_text() == "untouched", (
                f"case7: a writer TOUCHED the canary via {bad[:20]!r}. It "
                "refused the id, but only after doing the damage."
            )
    finally:
        account_registry.ACCOUNTS_DIR = real_accounts_dir
        shutil.rmtree(blast, ignore_errors=True)

    # ── Cases 8-11: `account_ids()`, the OTHER registry answer the auth layer
    #    asks for on every request. `auth.session_middleware` needs the full id
    #    set for an admin, and it used to get it from `list_accounts()` — which
    #    scandirs and then opens a meta.json per account, on every request the
    #    master makes. Same lesson as `is_account` above, different call site.
    account_registry._IDS_CACHE = None

    # ── Case 8: it answers correctly at all. A cache that returned the empty
    #            set would satisfy every "no rescan" assertion below.
    ids = account_registry.account_ids()
    assert ids == {_MINE, _THEIRS}, f"case8: wrong id set: {sorted(ids)}"

    # ── Case 9: THE POINT. Repeat calls must not touch the directory again.
    #            Kill iterdir and keep asking: a warm cache answers from a
    #            `stat`, which needs no descriptor. With the uncached version
    #            this raised on the very first call.
    scans = 0
    real_iterdir = Path.iterdir

    def _counting_iterdir(self):
        nonlocal scans
        scans += 1
        return real_iterdir(self)

    Path.iterdir = _counting_iterdir
    try:
        for _ in range(50):
            assert account_registry.account_ids() == {_MINE, _THEIRS}
    finally:
        Path.iterdir = real_iterdir
    assert scans == 0, (
        f"case9: 50 calls cost {scans} directory scans — the cache is not "
        "holding, and this runs on EVERY request an admin makes"
    )

    # ── Case 10: a freshly captured account is visible on the NEXT call, with
    #             no TTL to wait out. `auth.py` recomputes the master's set per
    #             request precisely so a new account never needs a re-login, so
    #             a time-based cache would have been the wrong device. Deleting
    #             it must land just as fast — a TTL would keep a removed account
    #             authorised until it expired.
    fresh = "1234567"
    (account_registry.ACCOUNTS_DIR / fresh).mkdir()
    assert fresh in account_registry.account_ids(), (
        "case10: a newly captured account was invisible — the id-set cache "
        "outlived the change it was supposed to notice"
    )
    (account_registry.ACCOUNTS_DIR / fresh).rmdir()
    assert fresh not in account_registry.account_ids(), (
        "case10: a DELETED account stayed in the master's authorised set"
    )

    # ── Case 11: a cold cache that genuinely cannot look must RAISE, never
    #             answer an empty set. Empty means "there are no accounts", and
    #             the caller reads that as a verdict — conflating it with "I
    #             could not look" is the exact fail-open that took the gate
    #             down in case 4's incident.
    account_registry._IDS_CACHE = None
    Path.iterdir = _emfile_iterdir
    try:
        account_registry.account_ids()
    except OSError as exc:
        assert exc.errno == errno.EMFILE, f"case11: wrong error: {exc!r}"
    else:
        raise AssertionError(
            "case11: account_ids() SWALLOWED an fd exhaustion and answered a "
            "set — a falsy default here is fail-open, not fail-closed"
        )
    finally:
        Path.iterdir = real_iterdir

    # ── Case 12: THE ANONYMOUS HOLE. A caller with no principal at all used to
    #             be waved through this middleware AND through
    #             `assert_account_owned` — both abstained when they could not
    #             identify the caller, so the only people either one constrained
    #             were the ones who had signed in. Measured against prod on
    #             2026-08-10: GET /admin/accounts returned 200 with no cookie.
    #             `/admin/accounts` names no account id on purpose: the leak
    #             needs no id to reach, which is exactly why the id-scan below
    #             never caught it.
    res = await _gate("/admin/accounts", signed_in=False)
    assert res.status_code == 401, \
        f"case12: an anonymous caller reached /admin/*: {res.status_code}"

    # ── Case 13: …and the close is SCOPED. Everything that is not /admin/* or
    #             /api/of/* still serves anonymously, or this change would take
    #             the login page and the health probes down with it.
    res = await _gate("/events", signed_in=False)
    assert res.status_code == 200, \
        f"case13: the fail-closed branch escaped its path prefix: {res.status_code}"

    # ── Case 14: the escape hatch really re-opens it. It exists so a lockout is
    #             one env var plus a restart instead of a redeploy — a hatch
    #             nobody has proven works is not a hatch.
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        res = await _gate("/admin/accounts", signed_in=False)
        assert res.status_code == 200, \
            f"case14: ALLOW_ANONYMOUS_ADMIN=1 did not re-open the gate: {res.status_code}"
    finally:
        del os.environ["ALLOW_ANONYMOUS_ADMIN"]

    # ── Case 15: a SIGNED-IN principal still passes the same path. Without this,
    #             cases 12-14 are all satisfied by a middleware that 401s
    #             everything — which is exactly what the first attempt at this
    #             fix did to every chatter in test_chatter_auth.
    res = await _gate("/admin/accounts", signed_in=True)
    assert res.status_code == 200, \
        f"case15: the gate 401'd a signed-in owner: {res.status_code}"

    print("[account_isolation_gate] all cases passed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(account_registry.SESSIONS_DIR, ignore_errors=True)
        _TMP_DB.unlink(missing_ok=True)
    sys.exit(0)
