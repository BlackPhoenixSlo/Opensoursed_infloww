"""Guarded throwaway relay for scripts/demo-shots (copied from scripts/ui-shots.sh).

Order matters: network guards and the dotenv no-ops first, then the secret store
redirected into the temp dir, then service/_run_ui_safe.py patches, then serve on
loopback under the stdlib asyncio loop (uvloop connects through libuv, past the guards).
"""
import ipaddress, json, os, socket, sys
from pathlib import Path

TMP = Path(os.environ["DEMO_SHOTS_TMP"])
LOG = TMP / "server-offhost.jsonl"


def _record(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None or host == "localhost":  # None: a local bind lookup, getaddrinfo(None, port)
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _refused(where, target):
    _record(LOG, {"process": "relay", "via": where, "target": str(target), "refused": True})
    return f"demo-shots: off-host {where} refused: {target!r}"


_real = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex,
         "create_connection": socket.create_connection, "getaddrinfo": socket.getaddrinfo,
         "gethostbyname": socket.gethostbyname, "gethostbyname_ex": socket.gethostbyname_ex}


def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.connect", address))
    return _real["connect"](self, address)


def connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.connect_ex", address))
    return _real["connect_ex"](self, address)


def create_connection(address, *a, **k):
    if not _loopback(address[0]):
        raise ConnectionRefusedError(_refused("socket.create_connection", address))
    return _real["create_connection"](address, *a, **k)


# Name lookups are refused before resolution, so no DNS query leaves the machine either.
def getaddrinfo(host, *a, **k):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.getaddrinfo", host))
    return _real["getaddrinfo"](host, *a, **k)


def gethostbyname(host):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.gethostbyname", host))
    return _real["gethostbyname"](host)


def gethostbyname_ex(host):
    if not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME, _refused("socket.gethostbyname_ex", host))
    return _real["gethostbyname_ex"](host)


socket.socket.connect, socket.socket.connect_ex, socket.create_connection = connect, connect_ex, create_connection
socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex = getaddrinfo, gethostbyname, gethostbyname_ex

# service/.env holds real keys; db/engine.py, llm_providers.py and auth.py
# read it through `from dotenv import ...`. No-op both before any import.
import dotenv  # noqa: E402
import dotenv.main  # noqa: E402


def _no_load_dotenv(*a, **k):
    return False


def _no_dotenv_values(*a, **k):
    return {}


for _m in (dotenv, dotenv.main):
    _m.load_dotenv, _m.dotenv_values = _no_load_dotenv, _no_dotenv_values

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
