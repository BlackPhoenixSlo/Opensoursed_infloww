import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit

TMP = Path(os.environ["DEMO_SHOTS_TMP"])
LOG = TMP / "server-offhost.jsonl"
PROCESS = os.environ.get("DEMO_SHOTS_PROCESS", "relay")


def _record(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is None or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


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

if os.environ.get("DEMO_SHOTS_CURL_GUARD") == "1":
    from curl_cffi import Curl, CurlOpt

    _curl_setopt = Curl.setopt


    def _check_curl_url(value, proxy=False):
        url = value.decode("ascii", "replace") if isinstance(value, bytes) else value
        if proxy and "://" not in url:
            url = "http://" + url
        try:
            parts = urlsplit(url)
            host = parts.hostname
        except ValueError:
            host = None
        if (not host or not _loopback(host) or "\\" in url or any(ord(c) <= 32 for c in url)
                or (not proxy and parts.scheme not in ("http", "https", "ws", "wss"))):
            raise ConnectionRefusedError(_refused("curl_cffi.proxy" if proxy else "curl_cffi", host))


    def curl_setopt(self, option, value):
        if option == CurlOpt.URL:
            _check_curl_url(value)
            _curl_setopt(self, CurlOpt.PROXY, "")
        elif option in (CurlOpt.PROXY, CurlOpt.PRE_PROXY) and value:
            _check_curl_url(value, proxy=True)
        elif option == CurlOpt.FOLLOWLOCATION:
            value = 0
        return _curl_setopt(self, option, value)


    Curl.setopt = curl_setopt

# service/.env holds real keys: no-op dotenv loading before anything imports it.
import dotenv  # noqa: E402
import dotenv.main  # noqa: E402


def _no_load_dotenv(*a, **k):
    return False


def _no_dotenv_values(*a, **k):
    return {}


for _m in (dotenv, dotenv.main):
    _m.load_dotenv, _m.dotenv_values = _no_load_dotenv, _no_dotenv_values
