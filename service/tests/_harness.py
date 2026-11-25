#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVICE = _REPO_ROOT / "service"
for _p in (_REPO_ROOT, _SERVICE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Bind a temp DB before any engine import: engine/alembic fall back to the prod DB if the env is unset.
DB_PATH = Path(tempfile.gettempdir()) / f"chatterly_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SHARE_TOKEN"] = ""
# Server startup early-returns in test mode instead of spawning WS pump / ingest supervisors.
os.environ["CHATTERLY_TEST_MODE"] = "1"
# run() gives every case its own event loop, so no DB connection may persist across cases.
os.environ["CHATTERLY_DB_NULLPOOL"] = "1"
os.environ.pop("INFLOWW_PROXIES", None)
os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-not-for-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
# A resolving Anthropic key changes help_assistant's default model; keep it empty so a developer's service/.env cannot leak in.
_HERMETIC_KEYS = ("ANTHROPIC_API_KEY", "HELP_ASSISTANT_ANTHROPIC_KEY")
for _k in _HERMETIC_KEYS:
    os.environ.setdefault(_k, "")
os.environ.setdefault("VAPID_KEY_FILE", str(Path(tempfile.gettempdir()) / f"vapid_test_{uuid.uuid4().hex}.pem"))


def bootstrap() -> None:
    from db.engine import init_db  # noqa: E402 — env already bound above

    try:
        import secrets_store
        _store_dir = Path(tempfile.mkdtemp(prefix="harness_secrets_"))
        secrets_store._DIR = _store_dir
        secrets_store._PATH = _store_dir / "secrets.json"
        secrets_store._CACHE = None
    except Exception:
        pass

    import llm_providers
    _file_backed = llm_providers._api_key

    def _api_key(env_name: str) -> str:
        if env_name in _HERMETIC_KEYS:
            import secrets_store
            return (secrets_store.stored(env_name)
                    or os.environ.get(env_name, "")).strip()
        return _file_backed(env_name)
    llm_providers._api_key = _api_key

    asyncio.run(init_db())
    import runtime_switches
    asyncio.run(runtime_switches.load())


def make_client():
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


@contextlib.contextmanager
def slot_lost_at_hold(module, n: int):
    import run_slot
    real, calls = module.hold_with_typing, [0]

    async def _hold(*a, **k):
        calls[0] += 1
        if calls[0] >= n:
            raise run_slot.SlotLost("test: take-back budget spent")
        return await real(*a, **k)
    module.hold_with_typing = _hold
    try:
        yield calls
    finally:
        module.hold_with_typing = real


def parking_chat(fake, n=1):
    calls = [0]

    async def chat(**kw):
        calls[0] += 1
        if (n(kw) if callable(n) else calls[0] == n) and not chat.parked.is_set():
            chat.parked.set()
            await chat.go.wait()
        return await fake(**kw)
    chat.parked, chat.go = asyncio.Event(), asyncio.Event()
    return chat


async def slot_parked(run, chat, *, keep_s: float = 0.0, wait_s: float = 5.0):
    import run_slot
    pool, took = run_slot.SlotPool(1), []

    async def first():
        async with run_slot.hold(pool):
            return await run()

    async def second():
        async with run_slot.hold(pool):
            took.append(True)
            chat.go.set()
            await asyncio.sleep(keep_s)

    task = asyncio.create_task(first())
    try:
        await asyncio.wait_for(chat.parked.wait(), wait_s)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(second(), wait_s + keep_s)
    finally:
        chat.go.set()
    (res,) = await asyncio.gather(task, return_exceptions=True)
    assert took, "no second run got the slot while the model answered: the wait pinned it"
    if isinstance(res, BaseException):
        raise res
    return res


def xfail(reason: str, strict: bool = True):
    def deco(fn):
        fn._xfail_reason = reason
        fn._xfail_strict = strict
        return fn
    return deco


def _module_cases(depth: int = 2) -> list:
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
                failures.append((name, f"XPASS: marked xfail ({reason}) but PASSED — drop the marker"))
                continue
            print(f"[ok] {name}")
    for name, msg in failures:
        print(f"[FAIL] {name}: {msg}")
    if failures:
        print(f"{len(failures)} case(s) failed")
        sys.exit(1)
    print("all cases passed")
