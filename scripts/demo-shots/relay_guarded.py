"""Guarded throwaway relay; network/dotenv guard precedes service imports."""
import os
import runpy
import sys
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("net_guard.py")))
TMP = Path(os.environ["DEMO_SHOTS_TMP"])
os.environ["BIO_FILES_DIR"] = str(TMP / "bio_files")  # bio admin uploads (service/bio_pages/files.py), as slop/lib/bio.py

SERVICE = Path(os.environ["DEMO_SHOTS_ROOT"]) / "service"
sys.path.insert(0, str(SERVICE))

# The stored secret outranks the env (server._effective_share_token), so point
# the store into the temp dir before anything can read it (_harness.py:75-80).
import secrets_store  # noqa: E402
secrets_store._DIR = TMP / "secrets"
secrets_store._PATH = secrets_store._DIR / "secrets.json"
secrets_store._CACHE = None

# The account registry lives on disk (service/sessions/accounts/<id>/), next to real
# sessions. Point every module-level path into the temp dir before server.py imports
# (it runs account_registry.migrate_legacy() at import time), so the demo Creators are
# written there and the real ones are never read or touched.
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
# The SQL mirror every session registration runs (db.repo.sync_from_disk) reads the
# account dirs and proxies.json through db/import_legacy.py's own paths: the temp dir
# too, or a captured session never gets its `accounts` row (the owner link then fails
# its foreign key) and the real service/sessions and proxies.json would be imported.
import db.import_legacy as _import_legacy  # noqa: E402
_import_legacy.SESSIONS_DIR = _accounts.SESSIONS_DIR
_import_legacy.ACCOUNTS_DIR = _accounts.ACCOUNTS_DIR
_import_legacy.ACTIVE_FILE = _accounts.ACTIVE_FILE
_import_legacy.PROXIES_FILE = TMP / "proxies.json"
# The proxy registry itself (service/proxies.json) the same file: a proxy added through
# /admin/proxies is written there, and a checkout's real proxies never reach a client.
import proxies as _proxies  # noqa: E402
_proxies.REGISTRY_PATH = _import_legacy.PROXIES_FILE

import _run_ui_safe  # noqa: E402,F401  (sets CHATTERLY_TEST_MODE, neuters loops)
import uvicorn  # noqa: E402

uvicorn.run(_run_ui_safe.server.app, host="127.0.0.1", port=int(os.environ["DEMO_SHOTS_RELAY_PORT"]),
            loop="asyncio", log_level="warning")
