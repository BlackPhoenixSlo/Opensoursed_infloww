#!/usr/bin/env python3
import _harness

import os  # noqa: E402

SECRET = "f" * 40
os.environ["FLEET_SECRET"] = SECRET

_harness.bootstrap()

import asyncio  # noqa: E402
import logging  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import quote  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import login_throttle  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Chatter  # noqa: E402

IDS = fx.seed_two_agencies()
client = _harness.make_client()
PATH = "/auth/fleet/whois"


def _whois(username: str, secret: str | None = SECRET):
    headers = {"X-Fleet-Username": quote(username, safe="")}
    if secret is not None:
        headers["X-Fleet-Secret"] = secret
    return client.get(PATH, headers=headers)


def _status_without_mount(secret: str | None) -> int:
    env = {k: v for k, v in os.environ.items() if k != "FLEET_SECRET"}
    if secret is not None:
        env["FLEET_SECRET"] = secret
    code = (
        "import _harness; _harness.bootstrap(); c = _harness.make_client(); "
        f"print(c.get({PATH!r}, headers={{'X-Fleet-Username': 'agency_a_owner', "
        f"'X-Fleet-Secret': {(secret or 'x')!r}}}).status_code)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent,
                         env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    return int(out.stdout.strip().splitlines()[-1])


def case_not_mounted_without_a_secret_or_with_a_short_one():
    assert _status_without_mount(None) == 404
    assert _status_without_mount("s" * 31) == 404


def case_a_wrong_or_missing_secret_is_403_and_never_says_whether_the_name_exists():
    for secret in (None, "", "f" * 39, "g" * 40, SECRET + "f"):
        r = _whois("agency_a_owner", secret)
        assert r.status_code == 403, (secret, r.status_code, r.text)
        assert r.json() == {"detail": "forbidden"}
        assert r.headers["cache-control"] == "no-store"


def case_an_owner_an_employee_and_a_lone_chatter_exist():
    lone = f"fleet_{uuid.uuid4().hex[:8]}"

    async def _write():
        now = datetime.utcnow()
        async with get_session() as s:
            s.add(Chatter(id=uuid.uuid4().hex, username=lone, password=fx.PASSWORD,
                          display_name=lone, created_at=now, last_seen_at=now))
    asyncio.run(_write())
    for name in ("agency_a_owner", "chatter_a", lone):
        r = _whois(name)
        assert r.status_code == 200, (name, r.text)
        assert r.json() == {"exists": True}, (name, r.json())
        assert r.headers["cache-control"] == "no-store"


def case_the_username_is_normalized_as_sign_in_does():
    assert _whois("  Agency_A_Owner ").json() == {"exists": True}
    assert _whois("ågency_a_owner").json() == {"exists": False}


def case_an_unknown_or_empty_name_does_not_exist():
    for name in ("nobody_here", "", "   "):
        r = _whois(name)
        assert r.status_code == 200 and r.json() == {"exists": False}, (name, r.text)


def case_a_name_over_64_chars_is_refused():
    assert _whois("a" * 65).status_code == 422
    assert _whois("a" * 64).json() == {"exists": False}


def case_it_spends_no_sign_in_throttle_token_and_no_log_line_or_url_has_the_username():
    login_throttle.reset()
    seen: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())
    grab = _Grab(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(grab)
    try:
        for i in range(50):
            assert _whois("agency_b_owner" if i % 2 else "ghost_user_xyz").status_code == 200
    finally:
        root.removeHandler(grab)
    assert len(login_throttle._buckets) == 0, len(login_throttle._buckets)
    assert not [m for m in seen if "agency_b_owner" in m or "ghost_user_xyz" in m], seen


_harness.run()
