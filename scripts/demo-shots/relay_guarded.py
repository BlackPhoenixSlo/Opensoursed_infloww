import os
import runpy
import sys
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("net_guard.py")))
TMP = Path(os.environ["DEMO_SHOTS_TMP"])
os.environ["BIO_FILES_DIR"] = str(TMP / "bio_files")

SERVICE = Path(os.environ["DEMO_SHOTS_ROOT"]) / "service"
sys.path.insert(0, str(SERVICE))

import secrets_store  # noqa: E402
secrets_store._DIR = TMP / "secrets"
secrets_store._PATH = secrets_store._DIR / "secrets.json"
secrets_store._CACHE = None

import accounts as _accounts  # noqa: E402
_accounts.SESSIONS_DIR = TMP / "sessions"
_accounts.ACCOUNTS_DIR = _accounts.SESSIONS_DIR / "accounts"
_accounts.ACTIVE_FILE = _accounts.SESSIONS_DIR / "active.json"
_accounts.MIGRATED_MARKER = _accounts.SESSIONS_DIR / ".migrated"
_accounts.ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
_accounts.MIGRATED_MARKER.write_text("demo-shots")
import of_client as _of_client  # noqa: E402
_of_client.SESSIONS_DIR = _accounts.SESSIONS_DIR
import session_bootstrap as _session_bootstrap  # noqa: E402
_session_bootstrap.SESSIONS_DIR = _accounts.SESSIONS_DIR
import db.import_legacy as _import_legacy  # noqa: E402
_import_legacy.SESSIONS_DIR = _accounts.SESSIONS_DIR
_import_legacy.ACCOUNTS_DIR = _accounts.ACCOUNTS_DIR
_import_legacy.ACTIVE_FILE = _accounts.ACTIVE_FILE
_import_legacy.PROXIES_FILE = TMP / "proxies.json"
import proxies as _proxies  # noqa: E402
_proxies.REGISTRY_PATH = _import_legacy.PROXIES_FILE

import _run_ui_safe  # noqa: E402,F401  (sets CHATTERLY_TEST_MODE, neuters loops)
import uvicorn  # noqa: E402

uvicorn.run(_run_ui_safe.server.app, host="127.0.0.1", port=int(os.environ["DEMO_SHOTS_RELAY_PORT"]),
            loop="asyncio", log_level="warning")
