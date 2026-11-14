"""Pure decisions of the bio app (and its owner admin API's validation, PR2a): byte-compatible with ofl.ink v2 (~/oflinkv2/app, Hono 4.13.13 + @hono/node-server).

Every function here is pure (no DB, no clock, no env); app.py feeds it the request and store.py's rows. Refs like
`server.js:68` are ~/oflinkv2/app/<file>. Regexes are ASCII-only and used with fullmatch: Python's `\\d`/`\\w` match
non-ASCII digits and letters, and its `$` allows a trailing newline, where JS's do neither.
"""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence
from urllib.parse import unquote

from bio_pages.jsval import geo_tracking_code, js_str, js_truthy

# gateway.js:25-32, verbatim
USERNAME = re.compile(r"[a-z0-9_]+")
LINK_ID = re.compile(r"[a-z0-9]{12}")
RECORD_ID = re.compile(r"[a-z0-9]{15}")
HOSTNAME = re.compile(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]")
# bin/reserved-usernames: the fixed names plus the routed top-level segments; a new Username must be USERNAME_NEW and
# not one of these (enforced by the editor, PR2).
RESERVED = ("api", "edit", "images", "internal", "netlify")
USERNAME_NEW = re.compile(r"[a-z0-9_]{3,30}")
MODES = ("direct", "escape_ig")
FILE_COLLECTIONS = ("profiles", "links")
FILENAME = re.compile(r"[A-Za-z0-9_.-]+")
_DIGITS = re.compile(r"[0-9]+")

CODE_MAX = 12  # the longest code a bio_daily row keeps (A10); a longer one is stored as ''


def reveal(link: Mapping | None, tracking_id: str | None, location: Mapping) -> tuple[str | None, str]:
    """destination.js:24-35: (the URL Reveal answers or None, the code it appended for bio_daily or '')."""
    if not link or not link.get("destination"):
        return None, ""
    url = link["destination"]
    code: Any = None
    if tracking_id == "geo":
        code = geo_tracking_code(link.get("geo"), location["country"], location["region"])
    elif isinstance(tracking_id, str) and _DIGITS.fullmatch(tracking_id):
        code = tracking_id
    if not js_truthy(code):
        return url, ""
    if url.endswith("/"):
        url = url[:-1]
    s = js_str(code)
    return url + "/c" + s, (s if len(s) <= CODE_MAX else "")


# ── headers ───────────────────────────────────────────────────────────

Header = Callable[[str], "str | None"]  # a lower-cased name to its value (duplicates joined with ", "), or None


def visitor_location(hdr: Header) -> dict:
    """visitor-location.js:5-10 (an empty value falls through, as JS `||`)."""
    return {"country": hdr("x-country") or hdr("cf-ipcountry") or "US",
            "region": hdr("x-nf-subdivision-code") or hdr("x-region") or hdr("cf-region-code") or ""}


_COUNTRY = re.compile(r"[A-Z]{2}")
_IN_APP = ((re.compile(r"Threads", re.I | re.A), "threads"), (re.compile(r"Instagram", re.I | re.A), "instagram"),
           (re.compile(r"FBAN|FBAV", re.I | re.A), "facebook"),
           (re.compile(r"musical_ly|Bytedance|TikTok", re.I | re.A), "tiktok"))


def event_country(hdr: Header) -> str:
    """event-recorder.js:13-16: CF-IPCountry only, upper-cased, two letters, else XX (never the US fallback)."""
    c = (hdr("cf-ipcountry") or "").upper()
    return c if _COUNTRY.fullmatch(c) else "XX"


def in_app(hdr: Header) -> str:
    ua = hdr("user-agent") or ""
    return next((name for rx, name in _IN_APP if rx.search(ua)), "")


_C0_SPACE = "".join(map(chr, range(0x21)))
_FORBIDDEN_HOST = frozenset(' #%/:<>?@[\\]^|') | frozenset(map(chr, range(0x20))) | {"\x7f"}


def _origin(s: str) -> tuple | None:
    """`new URL(s).origin` for http/https as a comparable tuple; None where URL throws or the scheme is another one
    (it then can never equal the http(s) origin it is compared with)."""
    s = s.strip(_C0_SPACE).replace("\t", "").replace("\n", "").replace("\r", "")
    m = re.match(r"([A-Za-z][A-Za-z0-9+.\-]*):", s)
    if not m or m.group(1).lower() not in ("http", "https"):
        return None
    scheme = m.group(1).lower()
    rest = s[m.end():].lstrip("/\\")
    auth = re.split(r"[/\\?#]", rest, maxsplit=1)[0]
    auth = auth.rsplit("@", 1)[-1]
    if auth.startswith("["):
        end = auth.find("]")
        if end < 0:
            return None
        try:
            host = "[" + ipaddress.IPv6Address(auth[1:end]).compressed + "]"
        except ValueError:
            return None
        after = auth[end + 1:]
        if after and not after.startswith(":"):
            return None
        port = after[1:]
    else:
        host, _, port = auth.partition(":")
        if not host:
            return None
        host = unquote(host, errors="replace")
        if host.isascii():
            host = host.lower()
        else:
            try:
                host = host.encode("idna").decode("ascii").lower()
            except UnicodeError:
                return None
        if any(c in _FORBIDDEN_HOST for c in host):
            return None
    if port and not re.fullmatch(r"[0-9]+", port):
        return None
    p = int(port) if port else None
    if p is not None and p > 65535:
        return None
    if p == {"http": 80, "https": 443}[scheme]:
        p = None
    return scheme, host, p


def same_origin(hdr: Header, forwarded: bool = False) -> bool:
    """click-guard.js:60-79. `forwarded` (path mode via a trusted proxy): Next's rewrite sets Host to the bio
    container and X-Forwarded-Host to the browser's host, so the Origin is held against the latter."""
    site = hdr("sec-fetch-site")
    if site in ("cross-site", "same-site"):
        return False
    origin = hdr("origin")
    if origin is None:
        return True
    proto = "https" if hdr("x-forwarded-proto") == "https" else "http"
    host = (forwarded and hdr("x-forwarded-host")) or hdr("host")
    a = _origin(origin)
    return a is not None and a == _origin(f"{proto}://{'null' if host is None else host}")


# ── hosts (host-resolver.js) ─────────────────────────────────────────

def normalize_host(host: str | None) -> str:
    """`Host: Creator.Test:4173` and `creator.test.` both name creator.test (host-resolver.js:10)."""
    s = (host or "").lower()
    s = re.sub(r":[0-9]*\Z", "", s, count=1)
    return re.sub(r"\.\Z", "", s, count=1)


def parse_primary_hosts(raw: str | None) -> frozenset[str]:
    return frozenset(h for h in map(normalize_host, (raw or "").split(",")) if h)


HostKind = Literal["primary", "lookup", "unknown", "spare", "custom"]


def host_kind(host: str | None, primary: frozenset[str]) -> tuple[HostKind, str]:
    """(kind, name) before any DB read: 'primary', 'unknown' (not a hostname) or 'lookup' (spare/custom/unknown)."""
    name = normalize_host(host)
    if name in primary:
        return "primary", name
    if not HOSTNAME.fullmatch(name):
        return "unknown", name
    return "lookup", name


def is_askable(domain: str, primary: frozenset[str]) -> bool:
    name = normalize_host(domain)
    return name in primary or bool(HOSTNAME.fullmatch(name))


def resolve_profile_request(kind: HostKind, custom_username: str | None, upath: str, prefix: str = "") -> dict | None:
    """host-resolver.js resolveProfileRequest: segments still percent-encoded, empties dropped. `prefix` (path mode,
    BIO_PATH_PREFIX, already cut from `upath`) leads the path grammar's profilePath; a Custom Domain never has one."""
    segs = [s for s in upath.split("/") if s]
    if kind == "custom":
        if len(segs) > 1:
            return None
        return {"username": custom_username, "trackingCode": segs[0] if segs else None, "profilePath": "/"}
    username = segs[0] if segs else ""
    return {"username": username, "trackingCode": segs[1] if len(segs) > 1 else None,
            "profilePath": prefix + "/" + username}


# ── path mode (BIO_PATH_PREFIX: `<app host>/p/<username>` through the Next app's rewrite) ──

PATH_PREFIX = re.compile(r"(?:/[a-z0-9_-]+)+")


def parse_path_prefix(raw: str | None) -> str:
    """BIO_PATH_PREFIX as `/seg[/seg]` (no trailing slash), or "" (host mode only). Anything else raises: the prefix
    is written into the page's attributes and script URLs, so only these characters may reach them."""
    s = (raw or "").strip().rstrip("/")
    if s and not PATH_PREFIX.fullmatch(s):
        raise ValueError("invalid BIO_PATH_PREFIX")
    return s


def cut_prefix(prefix: str, upath: str) -> str | None:
    """`upath` without `prefix` when it starts with it as whole segments (`/p` and `/p/...`, never `/px`), else None."""
    if not prefix or not (upath == prefix or upath.startswith(prefix + "/")):
        return None
    return upath[len(prefix):] or "/"


def to_json(value: Any) -> bytes:
    """JSON.stringify: compact, non-ASCII as is."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def as_script_json(value: Any) -> str:
    """server.js asScriptJson: JSON with `<`, `>`, `&` as \\u003c, \\u003e, \\u0026, so nothing ends the block."""
    s = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


BOOTSTRAP_BEFORE = '<script src="/script.js"></script>'
BOOTSTRAP_OPEN = '<script type="application/json" id="profile-bootstrap">'
NO_BOOTSTRAP = object()


def bootstrap_page(index_html: str, req: dict | None, prefix: str = "") -> str:
    """index.html with the Profile bootstrap block before the first `<script src="/script.js">` (server.js:286-299);
    a page rendered with a path prefix has that prefix on the script's src."""
    before = f'<script src="{prefix}/script.js"></script>'
    block = f'{BOOTSTRAP_OPEN}{as_script_json(req)}</script>\n    '
    return index_html.replace(before, block + before, 1)


def parse_bootstrap(page: bytes):
    """Read the block emitted by bootstrap_page; distinguish absent from JSON null."""
    text = page.decode("utf-8")
    start = text.find(BOOTSTRAP_OPEN)
    if start < 0:
        return NO_BOOTSTRAP
    start += len(BOOTSTRAP_OPEN)
    end = text.find("</script>", start)
    if end < 0:
        raise ValueError("unterminated bootstrap")
    return json.loads(text[start:end])


_ROOT_ATTR = re.compile(r'\b(href|src)="/(?!/)')


def render_index(index_html: str, escape_tap: bool, prefix: str = "") -> str:
    """Render the process-wide flag on the Escape Overlay card; with a path prefix (parse_path_prefix), lead every
    root-relative href/src with it and name it on <body data-base> for script.js's own URLs."""
    needle = '<a id="igCard" class="ig-card">'
    if index_html.count(needle) != 1:
        raise ValueError("igCard anchor missing or duplicated")
    out = index_html.replace(needle, f'<a id="igCard" class="ig-card" data-escape-tap="{int(escape_tap)}">', 1)
    if not prefix:
        return out
    if out.count("<body>") != 1:
        raise ValueError("body tag missing or duplicated")
    out = _ROOT_ATTR.sub(lambda m: f'{m.group(1)}="{prefix}/', out)
    return out.replace("<body>", f'<body data-base="{prefix}">', 1)


# ── Profile JSON (public-profile.js) ──────────────────────────────────

def lookup_username(raw: str) -> str | None:
    """The Username a request names, lower-cased, or None (no query) when it is not one (gateway.js:93-98)."""
    name = raw.lower()
    return name if USERNAME.fullmatch(name) else None


def _file_url(collection: str, row: Mapping, field: str, prefix: str = "") -> str:
    return f"{prefix}/api/files/{collection}/{row['id']}/{row[field]}" if row.get(field) else ""


def gated(link: Mapping | None, site_key: str | None) -> bool:
    """Reveal needs a Turnstile token: the Link's bot_check while the keys are set (`site_key` None = unset)."""
    return bool(site_key and link and link.get("bot_check"))


def public_profile(profile: Mapping, links: Sequence[Mapping], site_key: str | None = None, prefix: str = "") -> dict:
    """The Profile JSON. Never sent: destination, geo, owner/account, slot, v1_key. A gated Link (gated()) carries
    `botCheck: true` and the JSON the Turnstile site key; with the keys unset the shape is v2's."""
    pmode = profile["mode"] if profile["mode"] in MODES else "escape_ig"
    out_links = []
    for link in links:
        item = {"id": link["link_id"], "title": link["title"], "isAdult": bool(link["is_adult"]),
                "tracking": bool(link["tracking"])}
        if link["default_tracking_code"]:
            item["default_tracknumber"] = link["default_tracking_code"]
        item["mode"] = link["mode"] if link["mode"] in MODES else pmode
        item["icon"] = _file_url("links", link, "icon", prefix)
        item["backgroundImage"] = _file_url("links", link, "background_image", prefix)
        if gated(link, site_key):
            item["botCheck"] = True
        out_links.append(item)
    out = {"profile": {"id": profile["id"], "username": profile["username"], "displayName": profile["display_name"],
                       "bio": profile["bio"], "avatarUrl": _file_url("profiles", profile, "avatar", prefix),
                       "backgroundUrl": _file_url("profiles", profile, "background_image", prefix),
                       "verified": bool(profile["verified"]), "mode": pmode},
           "links": out_links}
    if any(item.get("botCheck") for item in out_links):
        out["turnstileSiteKey"] = site_key
    return out


# ── owner admin validation (PR2a; pure, table-tested; the editor mirrors these) ──

@dataclass(frozen=True)
class Invalid:
    field: str
    msg: str


STOCK_ICONS = ("onlyicon", "linkicon", "twitchicon", "igicon")
LINK_MODES = ("", *MODES)
# PB 0002's destination pattern with Go RE2's `\s` ([\t\n\f\r ]); Python's `\s` is wider (\v, NBSP).
DESTINATION = re.compile(r"(?:https?://[^\t\n\f\r \\/]|/[^\t\n\f\r \\/])[^\t\n\f\r \\]*")
TRACKING_CODE = re.compile(r"[0-9]{0,12}")
MAX_DISPLAY_NAME, MAX_BIO, MAX_TITLE, MAX_DESTINATION, MAX_GEO = 100, 500, 200, 2000, 8192
MAX_LINKS = 200
_PROFILE_CREATE = ("username", "display_name", "account_id", "mode")
_PROFILE_PATCH = ("display_name", "bio", "mode", "verified", "account_id")
_LINK_KEYS = ("title", "destination", "icon", "is_adult", "mode", "tracking", "default_tracking_code", "geo")
GEO_MSG = 'Geo Rule: write a JSON object, such as {"US": "5"}, or leave it empty for no Geo Rule.'
DEST_MSG = "Destination: start with https://, http:// or /; no spaces or backslashes."


def _unknown(body: Mapping, allowed: Sequence[str]) -> Invalid | None:
    bad = next((k for k in body if k not in allowed), None)
    if bad is None:
        return None
    name = str(bad).encode("utf-8", "backslashreplace").decode()  # a lone surrogate must not 500 the 422
    return Invalid(name, f"{name} can't be set here")


def _text(v: Any, field: str, lo: int, hi: int, empty_msg: str, strip: bool = True) -> str | Invalid:
    if not isinstance(v, str):
        return Invalid(field, f"{field} must be text")
    s = v.strip() if strip else v
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return Invalid(field, f"{field} must be valid UTF-8 text")
    if len(s) < lo:
        return Invalid(field, empty_msg)
    if len(s) > hi:
        return Invalid(field, f"{field}: at most {hi} characters")
    return s


def _flag(v: Any, field: str) -> bool | Invalid:
    return v if isinstance(v, bool) else Invalid(field, f"{field} must be true or false")


def _account(v: Any) -> str | None | Invalid:
    return v if v is None or (isinstance(v, str) and v) else Invalid("account_id", "account_id must be an id or null")


def check_profile(body: Mapping, create: bool) -> dict | Invalid:
    """A profile body, normalized; or the first refusal. PATCH checks only the keys sent (legacy values elsewhere
    never block an edit)."""
    if bad := _unknown(body, _PROFILE_CREATE if create else _PROFILE_PATCH):
        return bad
    out: dict[str, Any] = {}
    if create:
        for req in ("username", "display_name"):
            if req not in body:
                return Invalid(req, "Enter a display name." if req == "display_name"
                               else "Username: 3-30 lowercase letters, digits or _.")
        u = body["username"]
        u = u.strip().lower() if isinstance(u, str) else ""
        if not USERNAME_NEW.fullmatch(u):
            return Invalid("username", "Username: 3-30 lowercase letters, digits or _.")
        if u in RESERVED:
            return Invalid("username", "That username is reserved.")
        out["username"] = u
        out["mode"] = "escape_ig"
    for k, v in body.items():
        if k == "username":
            continue
        if k == "display_name":
            r = _text(v, k, 1, MAX_DISPLAY_NAME, "Enter a display name.")
        elif k == "bio":
            r = _text(v, k, 0, MAX_BIO, "", strip=False)
        elif k == "mode":
            r = v if v in MODES else Invalid(k, "mode must be direct or escape_ig")
        elif k == "verified":
            r = _flag(v, k)
        else:  # account_id
            r = _account(v)
        if isinstance(r, Invalid):
            return r
        out[k] = r
    return out


def check_link(body: Mapping, create: bool) -> dict | Invalid:
    """A link body, normalized (geo as compact JSON text or None; icon a stock stem or None = remove); or the first
    refusal. Create needs a title and a destination; PATCH checks only the keys sent."""
    if bad := _unknown(body, _LINK_KEYS):
        return bad
    if create:
        if "title" not in body:
            return Invalid("title", "Enter a title.")
        if "destination" not in body:
            return Invalid("destination", DEST_MSG)
    out: dict[str, Any] = {}
    for k, v in body.items():
        if k == "title":
            r = _text(v, k, 1, MAX_TITLE, "Enter a title.")
        elif k == "destination":
            r = _text(v, k, 0, MAX_DESTINATION, DEST_MSG)
            if isinstance(r, str):
                if r == "https://":
                    r = Invalid(k, "Enter a Destination after https://.")
                elif not DESTINATION.fullmatch(r):
                    r = Invalid(k, DEST_MSG)
        elif k == "default_tracking_code":
            r = v if isinstance(v, str) and TRACKING_CODE.fullmatch(v) else Invalid(
                k, "Default Tracking Code: digits only, or leave it empty.")
        elif k == "geo":
            if v is None:
                r = None
            elif isinstance(v, dict):
                try:
                    text_ = json.dumps(v, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
                    size = len(text_.encode("utf-8"))
                except (ValueError, UnicodeEncodeError):
                    r = Invalid(k, GEO_MSG)
                else:
                    r = text_ if size <= MAX_GEO else Invalid(k, "Geo Rule: at most 8 KB.")
            else:
                r = Invalid(k, GEO_MSG)
        elif k == "mode":
            r = v if v in LINK_MODES else Invalid(k, "mode must be '', direct or escape_ig")
        elif k in ("is_adult", "tracking"):
            r = _flag(v, k)
        else:  # icon
            r = v if v is None or v in STOCK_ICONS else Invalid(k, "Icon: none, onlyicon, linkicon, twitchicon or igicon")
        if isinstance(r, Invalid):
            return r
        out[k] = r
    return out


def icon_stock(icon: str) -> str | None:
    """The stock stem a stored icon was copied from (`<stem>_<r10>.webp`), else None (links.js:71-73)."""
    return next((s for s in STOCK_ICONS if icon.startswith(s + "_")), None)
