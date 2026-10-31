#!/usr/bin/env python3
"""
session_secret.load_secret — table tests over the env -> file -> generate
order both session secrets load through (session_stamps: SESSION_SECRET,
service/.session_secret; chatters: CHATTER_SESSION_SECRET,
service/.chatter_secret). Every case uses a temp dir, never service/:

  case_table:          env wins (stripped), blank env ignored, file read
                       (stripped), file created 0600, read-only dir falls back
                       to an in-process secret.
  case_old_bytes:      the bytes the old per-module loaders returned (recorded
                       at fbde43777 for a padded non-ASCII env and file).
  case_callers_wired:  each caller keeps its env name and file path.

Run: ./venv/bin/python service/tests/test_session_secret.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from session_secret import load_secret  # noqa: E402

ENV = "W13_TEST_SESSION_SECRET"


def _run(env: str | None, file_text: str | None, read_only: bool = False):
    """`(secret, file_after, mode_after)` for one load in a fresh dir."""
    d = Path(tempfile.mkdtemp())
    path = d / ".secret"
    if file_text is not None:
        path.write_text(file_text)
    if env is None:
        os.environ.pop(ENV, None)
    else:
        os.environ[ENV] = env
    if read_only:
        os.chmod(d, 0o500)
    try:
        got = load_secret(ENV, path)
    finally:
        os.chmod(d, 0o700)
        os.environ.pop(ENV, None)
    if not path.exists():
        return got, None, None
    return got, path.read_text(), stat.S_IMODE(path.stat().st_mode)


def case_table():
    got, after, _ = _run("  env-secret \n", "file-secret")
    assert got == b"env-secret" and after == "file-secret", ("env wins, stripped", got, after)

    got, after, _ = _run("   ", "  file-secret\n")
    assert got == b"file-secret" and after == "  file-secret\n", ("blank env ignored, file stripped", got)

    got, after, _ = _run("", "file-secret")
    assert got == b"file-secret", ("empty env ignored", got)

    got, after, mode = _run(None, None)
    assert after is not None and got == after.encode("utf-8"), ("created file holds the secret", got, after)
    assert len(after) == 64 and mode == 0o600, ("token_urlsafe(48), mode 0600", len(after), oct(mode or 0))

    got, after, _ = _run(None, None, read_only=True)
    assert after is None and len(got) == 64, ("read-only dir: in-process secret, no file", got, after)
    assert got != _run(None, None, read_only=True)[0], "in-process secrets are fresh per load"


# Recorded from the old session_stamps._load_session_secret and
# chatters._load_session_secret (both identical): strip(), then UTF-8.
OLD_ENV_BYTES = "env-sécret-".encode("utf-8")
OLD_FILE_BYTES = "file-sécret-x".encode("utf-8")


def case_old_bytes():
    assert _run("  env-sécret-\t\n", None)[0] == OLD_ENV_BYTES
    assert _run("   ", "  file-sécret-x \n")[0] == OLD_FILE_BYTES


def case_callers_wired():
    import chatters
    import session_stamps
    service = Path(session_stamps.__file__).resolve().parent
    assert session_stamps._SECRET_FILE == service / ".session_secret"
    assert chatters._SECRET_FILE == service / ".chatter_secret"
    assert session_stamps.SESSION_SECRET == os.environ["SESSION_SECRET"].strip().encode("utf-8")
    assert chatters._SESSION_SECRET == os.environ["CHATTER_SESSION_SECRET"].strip().encode("utf-8")


if __name__ == "__main__":
    _harness.run()
