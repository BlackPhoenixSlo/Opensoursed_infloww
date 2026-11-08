"""Probes through a registry proxy (a proxies.py entry), one cookie-less GET
each, nothing written, nothing tied to a Creator. Blocking; safe from a request
handler.

  probe     Cloudflare's trace: egress ip, country, colo. Display and region
            only (proxy_health.note_trace, the Test button), never counted.
  probe_of  OnlyFans' API host: health (proxy_health judges by it alone; the
            Test button's `ok`), as a proxy can answer the trace yet refuse
            CONNECT to OF.
"""
from __future__ import annotations

import logging
from typing import Any

from of_origin import IMPERSONATE, OF_WEB_ORIGIN
from proxies import proxies_dict_for_requests

log = logging.getLogger(__name__)

TRACE_URL = "https://1.1.1.1/cdn-cgi/trace"


def parse_trace(text: str) -> dict[str, str]:
    """Cloudflare's trace body: `key=value` lines (ip, loc, colo, ...)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def _get(p: dict[str, Any], url: str, timeout_s: int,
         impersonate: str | None = None) -> tuple[Any | None, dict[str, Any]]:
    """One GET of `url` through `p`: (the response, or None on a curl error;
    {ok: False, ttfb_ms, error, refused?}). `refused` marks the refused CONNECT
    alone (ProxyError, as of_client._attempt): proxy_health's refusal window.
    A malformed entry raises (`proxies_dict_for_requests`, outside the try)."""
    from curl_cffi import CurlInfo, requests as curl_requests

    routes = proxies_dict_for_requests(p)
    out: dict[str, Any] = {"ok": False, "ttfb_ms": None, "error": None}
    try:
        with curl_requests.Session(impersonate=impersonate,
                                   curl_infos=[CurlInfo.STARTTRANSFER_TIME]) as s:
            r = s.get(url, proxies=routes, timeout=timeout_s)
    except Exception as e:  # curl errors: refused CONNECT, timeout, TLS, DNS
        out.update(error=f"proxy_probe_failed: {e}",
                   refused=isinstance(e, curl_requests.exceptions.ProxyError))
        return None, out
    ttfb = r.infos.get(CurlInfo.STARTTRANSFER_TIME)
    out["ttfb_ms"] = round(ttfb * 1000) if isinstance(ttfb, (int, float)) else None
    return r, out


def probe(p: dict[str, Any], timeout_s: int = 15) -> dict[str, Any]:
    """Cloudflare's trace through the proxy: the egress ip, its country
    (`loc`, kept as `geo`), the Cloudflare `colo` and the time to first byte.
    No OnlyFans call and no third-party key. Returns {ok, ip, geo, colo,
    ttfb_ms, error, refused?}."""
    r, out = _get(p, TRACE_URL, timeout_s)
    out.update(ip=None, geo=None, colo=None)
    if r is not None and r.status_code != 200:
        out["error"] = f"proxy_probe_failed: HTTP {r.status_code}"
    elif r is not None:
        trace = parse_trace(r.text)
        out.update(ip=trace.get("ip") or None, geo=trace.get("loc") or None, colo=trace.get("colo") or None)
        out["ok"] = out["ip"] is not None
        if not out["ok"]:
            out["error"] = "proxy_probe_failed: no ip in the trace"
    log.info("proxy_probe label=%s ok=%s", p.get("label") or "-", out["ok"])
    return out


def probe_of(p: dict[str, Any], timeout_s: int = 15) -> dict[str, Any]:
    """OnlyFans through the proxy: one GET of `robots.txt` on the API's own
    host (of_origin.OF_WEB_ORIGIN, the host every `/api2/` call CONNECTs to;
    the x-hash CDN is another host a proxy may tunnel to while refusing the
    API) with no cookies, no session headers and Chrome's TLS profile. Any
    HTTP answer means the proxy opened the tunnel to OF: ok. No ip/geo (the
    trace's). Returns {ok, ttfb_ms, error, refused?}."""
    r, out = _get(p, f"{OF_WEB_ORIGIN}/robots.txt", timeout_s, impersonate=IMPERSONATE)
    out["ok"] = r is not None
    log.info("proxy_probe_of label=%s ok=%s", p.get("label") or "-", out["ok"])
    return out
