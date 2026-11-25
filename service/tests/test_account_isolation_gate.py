#!/usr/bin/env python3
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

# Hard-bind a throwaway DB before importing any service module.
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
_NOT_AN_ACCOUNT = "8675309"


def _sandbox_accounts() -> None:
    root = Path(tempfile.gettempdir()) / f"chatterly_isogate_{uuid.uuid4().hex}"
    account_registry.SESSIONS_DIR = root
    account_registry.ACCOUNTS_DIR = root / "accounts"
    for aid in (_MINE, _THEIRS):
        (account_registry.ACCOUNTS_DIR / aid).mkdir(parents=True)


async def _gate(path: str, query: bytes = b"", *, signed_in: bool = True) -> Response:
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

    res = await _gate(f"/admin/vault/{_MINE}/items")
    assert res.status_code == 200, f"case1: own account was blocked: {res.status_code}"

    res = await _gate(f"/admin/vault/{_THEIRS}/items")
    assert res.status_code == 403, f"case2: cross-account request was allowed: {res.status_code}"

    res = await _gate(f"/admin/fan/{_NOT_AN_ACCOUNT}/notes")
    assert res.status_code == 200, \
        f"case3: a fan id was mistaken for an account: {res.status_code}"

    # Under fd exhaustion the gate must still refuse: iterdir needs a descriptor, stat does not.
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

    # EACCES must propagate (deny loudly), not read as 'not an account'; assert that error.
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

    # Readers must answer 'not an account', never raise (a raise is a 500 per request); writers must keep raising (case 7).
    for bad, why in (
        ("/etc", "an absolute id replaces the join and answered True for /etc"),
        ("../../../etc", "traversal escaped the account tree"),
        ("9" * 3000, "an over-long id raised ENAMETOOLONG — a 500 per request"),
        # NAME_MAX is 255 bytes: 200 emoji is 800 bytes, so a len(str) guard misses it.
        ("\U0001F642" * 200, "a multibyte id passed a character-count guard"),
        ("a\x00b", "a NUL byte passed the shape guard"),
        # Lone surrogate: Starlette's query decoder turns it into U+FFFD, so the middleware leg proves less than the reader legs.
        ("\ud800", "a lone surrogate raised out of the guard's own length check"),
        ("", "the empty id resolved to ACCOUNTS_DIR itself and answered True"),
        (".", "'.' resolved to ACCOUNTS_DIR itself"),
        ("..", "'..' resolved to the parent of the account tree"),
    ):
        assert account_registry.is_account(bad) is False, f"case6 is_account: {why}"
        assert account_registry.get_account(bad) is None, f"case6 get_account: {why}"
        assert account_registry.latest_session_path(bad) is None, \
            f"case6 latest_session_path: {why}"
        res = await _gate("/admin/vault/items",
                          urlencode({"account_id": bad}, errors="surrogatepass").encode())
        assert res.status_code == 200, f"case6 middleware: {why} -> {res.status_code}"

    assert account_registry.is_account(_MINE) is True, \
        "case6: the shape guard rejected a REAL account id"
    assert account_registry.is_account(_NOT_AN_ACCOUNT) is False, \
        "case6: a well-formed non-account id was accepted"

    res = await _gate("/admin/vault/items", urlencode({"account_id": _THEIRS}).encode())
    assert res.status_code == 403, \
        f"case6: foreign account via ?account_id= was allowed: {res.status_code}"

    account_registry.set_active_account_id("../../../etc")
    assert account_registry.get_active_account_id() is None, \
        "case6: a poisoned active.json did not fall back"
    account_registry.set_active_account_id(None)

    # Must be safe with the guard broken: disposable deep tree plus an untouched canary, never /etc (relay runs as root).
    blast = Path(tempfile.mkdtemp(prefix="chatterly_isogate_blast_"))
    canary = blast / "canary"
    canary.mkdir()
    (canary / "keep.txt").write_text("untouched")
    real_accounts_dir = account_registry.ACCOUNTS_DIR
    account_registry.ACCOUNTS_DIR = blast / "a" / "b" / "accounts"
    account_registry.ACCOUNTS_DIR.mkdir(parents=True)
    try:
        for bad in (
            str(canary),
            "../../../canary",
            "a\x00b",
            "\ud800",
            "",
            "..",
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

    account_registry._IDS_CACHE = None

    ids = account_registry.account_ids()
    assert ids == {_MINE, _THEIRS}, f"case8: wrong id set: {sorted(ids)}"

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

    # No TTL: a new account is visible on the next call and a deleted one gone at once.
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

    # A cold cache that cannot look must raise, never answer an empty set (empty reads as a verdict).
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

    # Anonymous callers were waved through both layers: GET /admin/accounts returned 200 with no cookie.
    res = await _gate("/admin/accounts", signed_in=False)
    assert res.status_code == 401, \
        f"case12: an anonymous caller reached /admin/*: {res.status_code}"

    res = await _gate("/events", signed_in=False)
    assert res.status_code == 200, \
        f"case13: the fail-closed branch escaped its path prefix: {res.status_code}"

    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        res = await _gate("/admin/accounts", signed_in=False)
        assert res.status_code == 200, \
            f"case14: ALLOW_ANONYMOUS_ADMIN=1 did not re-open the gate: {res.status_code}"
    finally:
        del os.environ["ALLOW_ANONYMOUS_ADMIN"]

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
