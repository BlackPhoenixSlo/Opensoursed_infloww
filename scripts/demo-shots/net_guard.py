"""Loopback-only network and dotenv guards for the throwaway relay and bio launchers.

Both launchers force uvicorn loop=asyncio: uvloop connects past these socket guards.
"""
import ipaddress
import json
import os
import socket
from pathlib import Path

TMP = Path(os.environ["DEMO_SHOTS_TMP"])
LOG = TMP / "server-offhost.jsonl"
PROCESS = os.environ.get("DEMO_SHOTS_PROCESS", "relay")


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


# DEMO_SHOTS_ALLOW_HOSTS (comma-separated host names, default none): the only
# off-host names a run may reach, for a declared live call to a test-keyed API
# (slop's `SLOP_LIVE=1` single runs: api.typesafe.ai, api.deepseek.com). A name
# on the list resolves for real and only the addresses it resolved to may be
# connected; every other name and address is refused as before. Each allowed
# lookup is logged next to the refusals.
_ALLOW = {h.strip().lower().rstrip(".") for h in os.environ.get("DEMO_SHOTS_ALLOW_HOSTS", "").split(",")
          if h.strip()}
_ALLOWED_IPS: set = set()


def _allowed_name(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return bool(_ALLOW) and str(host or "").lower().rstrip(".") in _ALLOW


def _allowed_ip(host) -> bool:
    return str(host).split("%")[0] in _ALLOWED_IPS


def _refused(where, target):
    _record(LOG, {"process": PROCESS, "via": where, "target": str(target), "refused": True})
    return f"demo-shots: off-host {where} refused: {target!r}"


_real = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex,
         "create_connection": socket.create_connection, "getaddrinfo": socket.getaddrinfo,
         "gethostbyname": socket.gethostbyname, "gethostbyname_ex": socket.gethostbyname_ex}


def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not (_loopback(address[0]) or _allowed_ip(address[0])):
        raise ConnectionRefusedError(_refused("socket.connect", address))
    return _real["connect"](self, address)


def connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not (_loopback(address[0]) or _allowed_ip(address[0])):
        raise ConnectionRefusedError(_refused("socket.connect_ex", address))
    return _real["connect_ex"](self, address)


def create_connection(address, *a, **k):
    if not (_loopback(address[0]) or _allowed_ip(address[0]) or _allowed_name(address[0])):
        raise ConnectionRefusedError(_refused("socket.create_connection", address))
    return _real["create_connection"](address, *a, **k)


# Name lookups are refused before resolution, so no DNS query leaves the machine either.
def getaddrinfo(host, *a, **k):
    if _allowed_name(host):
        res = _real["getaddrinfo"](host, *a, **k)
        ips = sorted({r[4][0] for r in res})
        _ALLOWED_IPS.update(ips)
        _record(LOG, {"process": PROCESS, "via": "socket.getaddrinfo", "target": str(host), "allowed": True,
                      "ips": ips})
        return res
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
