#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

_TMP = Path(tempfile.gettempdir()) / f"chatterly_syncdisk_{uuid.uuid4().hex}"
_TMP.mkdir()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'db.sqlite'}"
os.environ["CHATTERLY_DB_URL"] = f"sqlite:///{_TMP / 'db.sqlite'}"
os.environ["SHARE_TOKEN"] = ""
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod")
os.environ.setdefault("CHATTER_SESSION_SECRET", "test-chatter-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import import_legacy, repo  # noqa: E402
from db.engine import init_db  # noqa: E402


# Overlapping syncs both inserted the new proxy label and the second died on UNIQUE proxies.label.
def _slow_accounts(_s, dry_run: bool):
    time.sleep(0.3)
    return 0, 0


async def case_two_syncs_at_once_both_succeed() -> None:
    await init_db()
    f = _TMP / "proxies.json"
    f.write_text(json.dumps({"proxies": [{"label": "custom-a", "scheme": "socks5", "host": "127.0.0.1",
                                          "port": 1080}]}))
    import_legacy.PROXIES_FILE = f
    import_legacy.import_accounts_and_sessions = _slow_accounts
    a, b = await asyncio.gather(repo.sync_from_disk(), repo.sync_from_disk())
    assert a["proxies"] == 1 and b["proxies"] == 1, (a, b)


async def main() -> None:
    await case_two_syncs_at_once_both_succeed()
    print("all cases passed")


if __name__ == "__main__":
    asyncio.run(main())
