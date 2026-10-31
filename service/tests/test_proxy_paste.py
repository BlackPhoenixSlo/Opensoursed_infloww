#!/usr/bin/env python3
"""
Paste proxies: many at once (POST /admin/proxies/bulk).
Contract: docs/proxies.md, "Paste many at once". The registry is repointed at
a temp file.

  case_every_format_parses:
      the five table formats, with the body scheme applied where the line has
      none and the line's scheme winning where it has one.
  case_trailing_label_and_default_label:
      a label after a space/tab is used; otherwise the label is host:port.
  case_bad_lines_raise_with_reason:
      no host, non-numeric port, out-of-range port, unsupported scheme,
      3-segment colon form and auth without a password are ValueErrors.
  case_redact_masks_passwords:
      redact_line never echoes the password, in any shape.
  case_upsert_from_line_keeps_bindings:
      re-pasting an existing label refreshes credentials but keeps the bound
      accounts (password lives in the registry file, as with upsert).
  case_bulk_mixed_good_and_bad:
      the bulk handler skips blank/# lines, adds the good ones, reports the bad
      ones by 1-based line number with the password redacted, and no password
      appears anywhere in the response.
  case_bulk_ownership_mirrors_single_upsert:
      a signed-in caller owns what they add; another user's label is a
      per-line error, not an overwrite.

Run: PYTHONPATH=service ./venv/bin/python service/tests/test_proxy_paste.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextvars  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

import auth  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import proxies_admin_api  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"proxy_paste_test_{uuid.uuid4().hex}"
_TMP.mkdir(parents=True, exist_ok=True)
proxy_registry.REGISTRY_PATH = _TMP / "proxies.json"

PW = "s3cretPW"


def _reset() -> None:
    proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))


class _U:
    def __init__(self, uid):
        self.id = uid
        self.account_ids: list[str] = []


def as_user(user, fn, *a):
    def run():
        tok = auth._request_user.set(user)
        try:
            return fn(*a)
        finally:
            auth._request_user.reset(tok)
    return contextvars.copy_context().run(run)


def _stub_server():
    """Silence the pool/db side effects the routes fire; return the call log."""
    import server as _srv
    calls: list[str] = []
    _srv._invalidate_client = lambda aid=None: calls.append(f"invalidate:{aid}")
    _srv._kick_db_sync = lambda reason: calls.append(f"sync:{reason}")
    return _srv, calls


def case_every_format_parses() -> None:
    p = proxy_registry.parse_proxy_line
    assert p(f"socks5://bob:{PW}@1.2.3.4:1080", "http") == {
        "label": "1.2.3.4:1080", "host": "1.2.3.4", "port": 1080, "scheme": "socks5",
        "username": "bob", "password": PW}
    assert p(f"bob:{PW}@1.2.3.4:8080", "https") == {
        "label": "1.2.3.4:8080", "host": "1.2.3.4", "port": 8080, "scheme": "https",
        "username": "bob", "password": PW}
    assert p(f"gate.example.com:12323:bob:{PW}") == {
        "label": "gate.example.com:12323", "host": "gate.example.com", "port": 12323,
        "scheme": "http", "username": "bob", "password": PW}
    assert p(f"1.2.3.4:8080@bob:{PW}") == {
        "label": "1.2.3.4:8080", "host": "1.2.3.4", "port": 8080, "scheme": "http",
        "username": "bob", "password": PW}
    assert p("1.2.3.4:8080") == {
        "label": "1.2.3.4:8080", "host": "1.2.3.4", "port": 8080, "scheme": "http"}
    # Passwords containing ':' or '@' and an all-digit password still parse.
    assert p("h.example:1:bob:pa:ss")["password"] == "pa:ss"
    assert p("bob:p@ss@h.example:1")["password"] == "p@ss"
    r = p("1.2.3.4:8080@bob:1234")
    assert (r["host"], r["port"], r["password"]) == ("1.2.3.4", 8080, "1234"), r
    assert p("HTTPS://1.2.3.4:1")["scheme"] == "https"


def case_trailing_label_and_default_label() -> None:
    p = proxy_registry.parse_proxy_line
    assert p(f"  1.2.3.4:8080:bob:{PW} hu-1  ")["label"] == "hu-1"
    assert p(f"1.2.3.4:8080\tBudapest 2")["label"] == "Budapest 2"
    assert p("1.2.3.4:8080")["label"] == "1.2.3.4:8080"


def case_bad_lines_raise_with_reason() -> None:
    bad = {
        ":8080": "no host",
        "1.2.3.4:http": "port must be a number",
        "1.2.3.4:70000": "out of range",
        "1.2.3.4:0": "out of range",
        "ftp://1.2.3.4:21": "unsupported scheme",
        "1.2.3.4:8080:bob": "unrecognised format",
        "1.2.3.4": "unrecognised format",
        "bob@1.2.3.4:8080": "user:pass",
        "": "empty",
    }
    for line, why in bad.items():
        try:
            proxy_registry.parse_proxy_line(line)
        except ValueError as e:
            assert why in str(e), (line, str(e))
        else:
            raise AssertionError(f"{line!r} should not parse")
    try:
        proxy_registry.parse_proxy_line("1.2.3.4:1", "ftp")
    except ValueError as e:
        assert "unsupported scheme" in str(e)
    else:
        raise AssertionError("a bad default scheme must not parse")


def case_redact_masks_passwords() -> None:
    lines = [
        f"socks5://bob:{PW}@1.2.3.4:badport",
        f"bob:{PW}@:8080",
        f"1.2.3.4:x@bob:{PW}",
        f"1.2.3.4:x:bob:{PW} lbl",
        f"1.2.3.4:x:{PW}",
    ]
    for line in lines:
        red = proxy_registry.redact_line(line)
        assert PW not in red, (line, red)
        assert "***" in red, red
    assert proxy_registry.redact_line(f"1.2.3.4:x:bob:{PW} lbl") == "1.2.3.4:x:bob:*** lbl"
    assert proxy_registry.redact_line("1.2.3.4:x") == "1.2.3.4:x"


def case_upsert_from_line_keeps_bindings() -> None:
    _reset()
    e = proxy_registry.upsert_from_line(f"1.2.3.4:8080:bob:{PW} hu-1")
    assert e["label"] == "hu-1" and e["user_id"] is None
    proxy_registry.assign_account("hu-1", "acct1")
    proxy_registry.upsert_from_line("1.2.3.4:8080:bob:newpw hu-1")
    got = proxy_registry.get_by_label("hu-1")
    assert got["password"] == "newpw", "re-paste must refresh credentials"
    assert got["assigned_account_ids"] == ["acct1"], got
    assert proxy_registry.proxy_url(got) == "http://bob:newpw@1.2.3.4:8080"
    assert len(proxy_registry.list_proxies()) == 1


def case_bulk_mixed_good_and_bad() -> None:
    _reset()
    _srv, calls = _stub_server()
    text = "\n".join([
        f"bob:{PW}@1.2.3.4:8080",          # 1
        "",                                # 2 blank
        "# a comment",                     # 3
        f"5.6.7.8:9000:bob:{PW} hu-2",     # 4
        f"1.2.3.4:99999:bob:{PW}",         # 5 bad port
        f"ftp://bob:{PW}@1.2.3.4:21",      # 6 bad scheme
        "   9.9.9.9:3128   ",              # 7
    ])
    body = proxies_admin_api._ProxyBulkBody(text=text, scheme="socks5")
    out = as_user(None, proxies_admin_api.admin_proxies_bulk, body)
    assert [a["label"] for a in out["added"]] == ["1.2.3.4:8080", "hu-2", "9.9.9.9:3128"], out
    assert out["added"][0] == {"label": "1.2.3.4:8080", "host": "1.2.3.4", "port": 8080,
                               "scheme": "socks5", "username": "bob"}
    assert out["added"][2]["username"] is None
    assert [e["line"] for e in out["errors"]] == [5, 6], out["errors"]
    assert "out of range" in out["errors"][0]["reason"]
    assert "unsupported scheme" in out["errors"][1]["reason"]
    assert all("***" in e["text_redacted"] for e in out["errors"])
    assert PW not in json.dumps(out), "a password leaked into the bulk response"
    # Stored like any other proxy (password in the registry file).
    assert proxy_registry.get_by_label("hu-2")["password"] == PW
    assert calls == ["invalidate:None", "sync:proxy-bulk-3"], calls

    # Nothing good → no pool invalidation.
    calls.clear()
    out = as_user(None, proxies_admin_api.admin_proxies_bulk, proxies_admin_api._ProxyBulkBody(text="#x\n\nnope"))
    assert out["added"] == [] and out["errors"][0]["line"] == 3
    assert calls == []


def case_bulk_ownership_mirrors_single_upsert() -> None:
    _reset()
    _srv, _ = _stub_server()
    proxy_registry.upsert_from_line("1.1.1.1:1 shared")         # shared default
    out = as_user(_U("u1"), proxies_admin_api.admin_proxies_bulk, proxies_admin_api._ProxyBulkBody(
        text=f"2.2.2.2:2:bob:{PW} mine\n1.1.1.1:1:bob:{PW} shared"))
    assert [a["label"] for a in out["added"]] == ["mine"]
    assert proxy_registry.get_by_label("mine")["user_id"] == "u1"
    assert out["errors"][0]["reason"] == "shared default proxy is read-only"
    assert proxy_registry.get_by_label("shared").get("username") is None
    out = as_user(_U("u2"), proxies_admin_api.admin_proxies_bulk, proxies_admin_api._ProxyBulkBody(text="3.3.3.3:3 mine"))
    assert out["errors"][0]["reason"] == "not your proxy"
    assert proxy_registry.get_by_label("mine")["host"] == "2.2.2.2"
    # The owner sees it in the list; the other user does not.
    seen = {p["label"] for p in as_user(_U("u1"), proxies_admin_api.admin_proxies_list)["proxies"]}
    assert "mine" in seen
    seen = {p["label"] for p in as_user(_U("u2"), proxies_admin_api.admin_proxies_list)["proxies"]}
    assert "mine" not in seen


_harness.run()
