#!/usr/bin/env python3
"""
Shared test harness for service/tests/*.py.

⚠️ IMPORT THIS MODULE FIRST — before any `service.*`, `db.*`, or `server`
import. It binds a throwaway temp SQLite DB to DATABASE_URL + CHATTERLY_DB_URL
*at import time*, so a test can NEVER accidentally touch PROD
(`service/chatterly.db`). This is the project's #1 footgun: the engine /
alembic silently fall back to the prod DB if these env-vars are unset.

Usage (matches the repo's plain-assert, no-pytest convention):

    import _harness                      # MUST be the first import
    _harness.bootstrap()                 # create schema via init_db()
    client = _harness.make_client()      # FastAPI TestClient(server.app)

    def case_foo():
        assert 1 + 1 == 2, "math broke"

    _harness.run()                       # runs every case_* in the file, in order
    _harness.run(case_foo, case_bar)     # explicit order; unlisted case_* = hard error

Run a test file with:  ./venv/bin/python service/tests/test_X.py
Exit 0 = all cases passed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import uuid
from pathlib import Path

# ── Make service modules importable from repo root OR service/tests/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE = _REPO_ROOT / "service"
for _p in (_REPO_ROOT, _SERVICE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ── Bind a UNIQUE temp DB BEFORE any engine import (PROD-fallback footgun).
DB_PATH = Path(tempfile.gettempdir()) / f"chatterly_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SHARE_TOKEN"] = ""  # disable share-token gate for test requests
# Signal test mode so server startup can early-return instead of spawning the WS
# pump / tx-ingest supervisors + live_rev network refresh (which would hang a test).
os.environ["CHATTERLY_TEST_MODE"] = "1"
# run() gives every case its own event loop, so no DB connection may be kept
# across cases: the engine skips its pool (db/engine.py).
os.environ["CHATTERLY_DB_NULLPOOL"] = "1"
# The startup pool sync is not behind the test-mode guard; with the env unset it
# never writes the registry (proxies.sync_pool fails closed).
os.environ.pop("INFLOWW_PROXIES", None)
# Stable, obviously-fake secrets so cookies/keys are reproducible across reruns.
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-not-for-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
# Fake LLM keys so llm_client construction never reads the real ones in tests.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")


def bootstrap() -> None:
    """Create the schema in the temp DB via init_db() (additive create_all),
    and point the secret store at a throwaway file.

    The store redirect is not tidiness. `secrets_store._PATH` defaults to a real
    path under service/, `_atomic_write` creates its parent, and ANY test that
    reaches `/admin/secrets` over HTTP — or any probe that imports the module
    without thinking — writes the DEVELOPER'S OWN store. That happened
    (2026-08-20): a stray write left a placeholder DEEPSEEK_API_KEY there, the
    store outranks the env by design, and the live-API case in
    test_llm_millicents.py started failing 401 with no connection to the change
    that "broke" it. Redirecting once here protects every suite; the store's own
    test still overrides `_PATH` for its own reasons.
    """
    from db.engine import init_db  # noqa: E402 — env already bound above

    try:
        import secrets_store
        _store_dir = Path(tempfile.mkdtemp(prefix="harness_secrets_"))
        secrets_store._DIR = _store_dir
        secrets_store._PATH = _store_dir / "secrets.json"
        secrets_store._CACHE = None
    except Exception:
        # A suite that cannot import the store must not fail to bootstrap.
        pass

    asyncio.run(init_db())


def make_client():
    """Return a FastAPI TestClient bound to the in-process app.

    server is imported here (not at module top) so the engine + models load
    against the temp DB the env-vars above point at.

    The app's background supervisors (WS pump, tx-ingest, live_rev network
    refresh) are NEUTRALIZED so a request test never hangs or hits OF. Two
    layers: (1) CHATTERLY_TEST_MODE is set above so a TEST_MODE-aware server
    startup early-returns; (2) we also no-op `_start_event_pumps` and
    `live_rev.refresh` post-import as a belt-and-suspenders for the lifespan
    path. Use the returned client WITHOUT a `with` block for request-only tests.
    """
    from fastapi.testclient import TestClient  # noqa: E402
    import server  # noqa: E402 — registers routers + middleware

    async def _noop_async(*_a, **_k):  # pragma: no cover
        return None

    if hasattr(server, "_start_event_pumps"):
        server._start_event_pumps = _noop_async  # type: ignore[attr-defined]
    live_rev = getattr(server, "live_rev", None)
    if live_rev is not None and hasattr(live_rev, "refresh"):
        try:
            live_rev.refresh = lambda *_a, **_k: None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    return TestClient(server.app)


def xfail(reason: str, strict: bool = True):
    """Mark a case as KNOWN-FAILING: it still RUNS, but its failure does not fail the
    suite — and by default, if it starts PASSING that IS a failure, so the marker
    cannot outlive the bug it documents.

    This exists because the registration guard in `run()` below has exactly one escape
    hatch — rename the function so it is not a `case_*` — and using that to park a
    red test would recreate the silent-skip problem the guard was written to kill. A
    known-failing test must stay LOUD. Always give a reason that names the bug.

    `strict=False` for a bug that manifests INTERMITTENTLY: the case is reported
    `[xpass]` when it happens to pass instead of failing the run. Strict is the
    default because a bug that is reliably fixed should break its own marker; use
    non-strict only when you have actually observed the case flapping, or the marker
    hands the suite the flakiness it was supposed to contain.
    """
    def deco(fn):
        fn._xfail_reason = reason
        fn._xfail_strict = strict
        return fn
    return deco


def _module_cases(depth: int = 2) -> list:
    """Every `case_*` DEFINED `depth` frames up, in definition order. The default of 2
    resolves to the test module when called from inside `run()` — its only caller.

    `__module__` is checked so a `case_*` imported from a helper module is not
    silently adopted as one of this file's tests.
    """
    caller = sys._getframe(depth).f_globals
    here = caller.get("__name__")
    found = [v for k, v in caller.items()
             if k.startswith("case_") and callable(v) and getattr(v, "__module__", None) == here]
    return sorted(found, key=lambda f: getattr(getattr(f, "__code__", None), "co_firstlineno", 0))


def run(*cases) -> None:
    """Run independent case callables; collect ALL failures; exit 1 if any.

    Cases may be sync or async (coroutine fns). Failures don't short-circuit,
    so one run surfaces every regression — matching test_chatter_auth.py.

    Call `run()` with NO arguments to run every `case_*` in the module, in
    definition order — that is the preferred form, because a hand-maintained
    argument list is bookkeeping whose failure mode is SILENTLY NOT RUNNING YOUR
    TEST. Two cases were written, committed and never executed that way
    (test_vault_scripts.py), and the same list swallowed two more the day this
    guard was written.

    An explicit `run(a, b, ...)` still works — ordering sometimes matters — but a
    `case_*` defined in the module and missing from the list is now a hard error
    rather than a silent skip. To keep one out of the run deliberately, give it a
    name that does not start with `case_`.
    """
    if not cases:
        cases = tuple(_module_cases())
    else:
        listed = {getattr(c, "__name__", None) for c in cases}
        missing = [f.__name__ for f in _module_cases() if f.__name__ not in listed]
        if missing:
            print(f"[FAIL] {len(missing)} case(s) defined but never registered with run():")
            for name in missing:
                print(f"    - {name}")
            print("Add them, or call run() with no arguments to collect them automatically.")
            sys.exit(1)

    failures: list[tuple[str, str]] = []
    for case in cases:
        name = getattr(case, "__name__", repr(case))
        reason = getattr(case, "_xfail_reason", None)
        try:
            result = case()
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except AssertionError as exc:
            if reason is not None:
                print(f"[xfail] {name} — {reason}")
                continue
            failures.append((name, str(exc) or "assertion failed"))
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the run
            if reason is not None:
                print(f"[xfail] {name} — {reason}")
                continue
            failures.append((name, f"ERROR: {exc!r}"))
        else:
            if reason is not None:
                if not getattr(case, "_xfail_strict", True):
                    print(f"[xpass] {name} — intermittent; still marked xfail ({reason})")
                    continue
                # The bug is fixed. The marker is now a lie — fail until it is removed.
                failures.append((name, f"XPASS: marked xfail ({reason}) but PASSED — drop the marker"))
                continue
            print(f"[ok] {name}")
    for name, msg in failures:
        print(f"[FAIL] {name}: {msg}")
    if failures:
        print(f"{len(failures)} case(s) failed")
        sys.exit(1)
    print("all cases passed")
