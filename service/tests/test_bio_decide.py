#!/usr/bin/env python3
"""bio_pages.decide: the pure rules of the public bio app, as ofl.ink v2 (~/oflinkv2/app) answers them.

Tables: destination (destination.js), geo rule, visitor location + event fields, guard (click-guard.js), same-origin,
host normalisation, request grammar (host-resolver.js), bootstrap escaping (server.js), path normalisation (Hono +
@hono/node-server), Profile JSON (public-profile.js), reserved names, pinned asset md5s.

Run: ./venv/bin/python service/tests/test_bio_decide.py   (exit 0 = green)
"""
from __future__ import annotations

import _harness  # MUST be first

import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402

from bio_pages import assets, hono
from bio_pages import decide as d  # noqa: E402
from bio_pages import files  # noqa: E402
from bio_pages.guard import FixedWindow  # noqa: E402

US = {"country": "US", "region": ""}


def _hdr(**h):
    low = {k.replace("_", "-").lower(): v for k, v in h.items()}
    return low.get


def _link(dest="https://of.com/x", geo=None):
    return {"destination": dest, "geo": geo}


def case_destination_table():
    rows = [
        (None, None, None),
        (_link(""), "4242", None),
        (_link(), None, "https://of.com/x"),
        (_link(), "4242", "https://of.com/x/c4242"),
        (_link("https://of.com/x/"), "4242", "https://of.com/x/c4242"),
        (_link("https://of.com/x//"), "4242", "https://of.com/x//c4242"),
        (_link(), "abc", "https://of.com/x"),
        (_link(), "12a", "https://of.com/x"),
        (_link(), "٣", "https://of.com/x"),  # Arabic-Indic three: not a JS \d
        (_link(), "", "https://of.com/x"),
        (_link(), "-1", "https://of.com/x"),
        (_link(), "1.5", "https://of.com/x"),
        (_link(), "12\n", "https://of.com/x"),
        (_link(), "0", "https://of.com/x/c0"),  # "0" is a truthy string
    ]
    for link, tid, want in rows:
        got = d.reveal(link, tid, US)[0]
        assert got == want, (link, tid, got, want)


def case_geo_table():
    def geo(rule, country="US", region=""):
        return d.reveal(_link("https://of.com/x", rule), "geo", {"country": country, "region": region})[0]
    base = "https://of.com/x"
    rows = [
        (({"US": "11"},), base + "/c11"),
        (({"US": {"CA": "7", "default": "8"}}, "US", "CA"), base + "/c7"),
        (({"US": {"CA": "7", "default": "8"}}, "US", "TX"), base + "/c8"),
        (({"US": {}},), base),
        (({"default": "9"}, "DE"), base + "/c9"),
        (({"DE": "", "default": "9"}, "DE"), base + "/c9"),
        (({"US": 5},), base + "/c5"),
        (({"US": 5.0},), base + "/c5"),
        (({"US": 1.5},), base + "/c1.5"),
        (({"US": 1e21},), base + "/c1e+21"),
        (({"US": 1e-7},), base + "/c1e-7"),
        (({"US": 0.000001},), base + "/c0.000001"),
        (({"US": True},), base + "/ctrue"),
        (({"US": 0, "default": "4"},), base + "/c4"),
        (({"US": [1, 2]}, "US", "1"), base + "/c2"),
        (({"US": [1, 2]}, "US", "TX"), base),
        (({"US": [1, 2]}, "US", "01"), base),
        ((["a"], "0"), base + "/ca"),
        ((["a", "b", "c"], "length"), base + "/c3"),
        ((None,), base),
        (("x",), base),
        ((5,), base),
        (({"US": {"": "1", "default": "2"}}, "US", ""), base + "/c2"),
        (({"__proto__": "13"}, "__proto__"), base + "/c13"),
        (({"US": {"CA": [1, None, 3]}}, "US", "CA"), base + "/c1,,3"),
        (({"US": {"CA": {"a": 1}}}, "US", "CA"), base + "/c[object Object]"),
    ]
    for args, want in rows:
        got = geo(*args)
        assert got == want, (args, got, want)
    assert d.visitor_location(_hdr())["country"] == "US"


def case_reveal_code_for_stats():
    assert d.reveal(_link(), "4242", US) == ("https://of.com/x/c4242", "4242")
    assert d.reveal(_link(), None, US) == ("https://of.com/x", "")
    assert d.reveal(_link(geo={"US": "77"}), "geo", US) == ("https://of.com/x/c77", "77")
    long = "1" * 13
    assert d.reveal(_link(), long, US) == ("https://of.com/x/c" + long, ""), "a code over 12 chars is not kept"


def case_location_and_event_fields():
    h = _hdr(x_country="DE", cf_ipcountry="FR")
    assert d.visitor_location(h)["country"] == "DE" and d.event_country(h) == "FR"
    assert d.visitor_location(_hdr(x_country="", cf_ipcountry="FR"))["country"] == "FR", "empty falls through"
    assert d.visitor_location(_hdr(cf_region_code="CA"))["region"] == "CA"
    assert d.visitor_location(_hdr(x_nf_subdivision_code="NY", x_region="CA"))["region"] == "NY"
    assert d.event_country(_hdr(cf_ipcountry="fr")) == "FR"
    for bad in ("XXX", "1A", "T1", "Us\n", "", None):
        assert d.event_country(_hdr(cf_ipcountry=bad)) == "XX", bad
    assert d.event_country(_hdr(x_country="DE")) == "XX", "never the US fallback, never x-country"
    rows = [("Mozilla Instagram 300 Threads", "threads"), ("Mozilla FBAV/1", "facebook"), ("musical_ly_2", "tiktok"),
            ("x instagram y", "instagram"), ("Mozilla/5.0 Safari", ""), (None, "")]
    for ua, want in rows:
        assert d.in_app(_hdr(user_agent=ua)) == want, ua


def case_guard_table():
    t = [59.9]
    w = FixedWindow(3, clock=lambda: t[0])
    assert [w("a") for _ in range(5)] == [True, True, True, False, False]
    t[0] = 60.0
    assert w("a") is True, "a new minute drops the table"
    w2 = FixedWindow(1, clock=lambda: 10.0)
    assert w2("a") and not w2("a") and w2("b"), "per key"
    from bio_pages import guard
    guard.configure(1, clock=lambda: 100.0)
    try:
        assert guard.allow_ping("1.2.3.4", "Foo") is True
        assert guard.allow_ping("1.2.3.4", "foo") is False, "/v/Foo and /v/foo share a window"
        assert guard.allow("1.2.3.4") is True, "the ping window does not touch Reveal's"
        assert guard.allow("1.2.3.4") is False
    finally:
        guard.configure(60)


def case_same_origin_table():
    rows = [
        ({}, True),
        ({"sec_fetch_site": "same-origin"}, True),
        ({"sec_fetch_site": "none"}, True),
        ({"sec_fetch_site": "cross-site"}, False),
        ({"sec_fetch_site": "same-site"}, False),
        ({"origin": "http://ofl.test", "host": "ofl.test"}, True),
        ({"origin": "http://ofl.test", "host": "ofl.test", "x_forwarded_proto": "https"}, False),
        ({"origin": "https://OFL.TEST:443", "host": "ofl.test", "x_forwarded_proto": "https"}, True),
        ({"origin": "http://ofl.test:80/x?y", "host": "ofl.test"}, True),
        ({"origin": "null", "host": "ofl.test"}, False),
        ({"origin": "garbage", "host": "ofl.test"}, False),
        ({"origin": "ftp://ofl.test", "host": "ofl.test"}, False),
        ({"origin": "http://ofl.test", "host": "ofl.test:8080"}, False),
        ({"origin": "http://127.0.0.1:3000", "host": "127.0.0.1:3000"}, True),
        ({"origin": "http://[::1]:3000", "host": "[0:0::1]:3000"}, True),
    ]
    for h, want in rows:
        assert d.same_origin(_hdr(**h)) is want, (h, want)
    # Path mode via a trusted proxy (Next's /p rewrite): Host is the bio container, X-Forwarded-Host the browser's.
    via_next = {"origin": "https://app.test", "host": "openinflowwww-bio:8788", "x_forwarded_host": "app.test",
                "x_forwarded_proto": "https"}
    fwd = [
        (via_next, True, True),
        (via_next, False, False),  # host mode / untrusted peer: X-Forwarded-Host is not believed
        ({**via_next, "x_forwarded_host": "evil.test"}, True, False),
        ({**via_next, "x_forwarded_host": "app.test, evil.test"}, True, False),
        ({**via_next, "x_forwarded_proto": None}, True, False),
        ({"origin": "http://ofl.test", "host": "ofl.test"}, True, True),  # no X-Forwarded-Host: Host as ever
        ({**via_next, "sec_fetch_site": "cross-site"}, True, False),
    ]
    for h, forwarded, want in fwd:
        assert d.same_origin(_hdr(**h), forwarded) is want, (h, forwarded, want)


def case_host_table():
    primary = d.parse_primary_hosts("localhost,ofl.test")
    for h in ("localhost", "LocalHost:4173", "localhost.", "OFL.test:"):
        assert d.host_kind(h, primary)[0] == "primary", h
    for h in ("1.2.3.4", "[::1]:3000", "a_b.test", "", None, "bad host!"):
        assert d.host_kind(h, primary)[0] == "unknown", h
    assert d.host_kind("Spare.Test.", primary) == ("lookup", "spare.test")
    assert d.is_askable("localhost", primary) and d.is_askable("x.example.com", primary)
    assert not d.is_askable("", primary) and not d.is_askable("bad host!", primary)
    assert d.parse_primary_hosts("") == frozenset() and d.parse_primary_hosts(",,") == frozenset()


def case_request_grammar_table():
    g = d.resolve_profile_request
    assert g("primary", None, "/") == {"username": "", "trackingCode": None, "profilePath": "/"}
    assert g("primary", None, "/alice") == {"username": "alice", "trackingCode": None, "profilePath": "/alice"}
    assert g("primary", None, "/alice/123/deep") == {"username": "alice", "trackingCode": "123", "profilePath": "/alice"}
    assert g("spare", None, "//alice//123") == {"username": "alice", "trackingCode": "123", "profilePath": "/alice"}
    assert g("custom", "u", "/") == {"username": "u", "trackingCode": None, "profilePath": "/"}
    assert g("custom", "u", "/123") == {"username": "u", "trackingCode": "123", "profilePath": "/"}
    assert g("custom", "u", "/a/b") is None
    assert g("unknown", None, "/alice")["username"] == "alice"
    assert g("primary", None, "/Al%69ce")["username"] == "Al%69ce", "kept encoded"
    assert list(g("primary", None, "/a/1")) == ["username", "trackingCode", "profilePath"], "key order"


def case_bootstrap_escaping_table():
    html = assets.INDEX.read_text()
    for seg in ("a&b", "$&", "$1", "%3C/script%3E", "</script>", "café", " "):
        req = {"username": seg, "trackingCode": "$'", "profilePath": "/" + seg}
        page = d.bootstrap_page(html, req)
        start = page.index('<script type="application/json" id="profile-bootstrap">')
        block = page[start + len('<script type="application/json" id="profile-bootstrap">'):page.index("</script>", start)]
        assert not re.search(r"[<>&]", block), (seg, block)
        assert json.loads(block) == req, "the block parses back to the request ($ patterns copied literally)"
        assert page.count('id="profile-bootstrap"') == 1
        assert page[page.index("</script>", start):].startswith('</script>\n    <script src="/script.js"></script>')
    assert d.as_script_json(None) == "null"
    assert d.as_script_json({"username": "<&>"}) == '{"username":"\\u003c\\u0026\\u003e"}'


def case_escape_flag_is_rendered_on_card():
    html = assets.INDEX.read_text()
    req = {"username": "alice", "trackingCode": "12", "profilePath": "/alice"}
    tag = '<script type="application/json" id="profile-bootstrap">'
    for flag in (True, False):
        rendered = d.render_index(html, flag)
        assert f'data-escape-tap="{int(flag)}"' in rendered
        page = d.bootstrap_page(rendered, req)
        start = page.index(tag) + len(tag)
        assert json.loads(page[start:page.index("</script>", start)]) == req
        assert d.parse_bootstrap(page.encode()) == req
    assert d.parse_bootstrap(html.encode()) is d.NO_BOOTSTRAP


def case_path_normalisation_table():
    rows = [
        (b"/a/../b/%2e%2e/c", "/c", "/c"),
        (b"/a\\b/<x>/%25/%41", "/a/b/%3Cx%3E/%25/%41", "/a/b/<x>/%25/A"),
        (b"/a/.", "/a/", "/a/"),
        (b"/a/..", "/", "/"),
        (b"/%2E%2e/x", "/x", "/x"),
        (b"/x%2Fy", "/x%2Fy", "/x%2Fy"),
        (b"/a%zz/%41%FF/%41", "/a%zz/%41%FF/%41", "/a%zz/%41%FF/A"),
        (b"/%61pi", "/%61pi", "/api"),
        (b'/"{}`', "/%22%7B%7D%60", '/"{}`'),
        (b"", "/", "/"),
    ]
    for raw, want_url, want_route in rows:
        u = hono.url_path(raw)
        assert u == want_url, (raw, u)
        assert hono.route_path(u) == want_route, (raw, hono.route_path(u))
    assert hono.param("a%2Fb.json") == "a/b.json" and hono.param("a%2Eb.json") == "a.b.json"
    assert hono.param("%zz") == "%zz" and hono.param("%E2%82") == "%E2%82"
    assert assets.public_key("/style.css") == "style.css"
    assert assets.public_key("/images/igicon.webp") == "images/igicon.webp"
    for p in ("/index.html", "//index.html", "/", "/../decide.py", "/x%2F..%2F..%2Fdecide.py",
              "/%zz"):
        assert assets.public_key(p) is None, p
    assert assets.public_key("/x%2F..%2Fstyle.css") == "style.css", "path.resolve semantics"
    assert assets.public_key("/%2e%2e%2fstyle.css") is None


def case_public_profile_shape():
    profile = {"id": "p" * 15, "username": "alice", "display_name": "Alice", "bio": "hi", "avatar": "a.webp",
               "mode": "junk", "verified": 1}
    links = [{"id": "l" * 15, "link_id": "k" * 12, "title": "T", "is_adult": 0, "tracking": 1,
              "default_tracking_code": "55", "mode": "direct", "icon": "", "background_image": "b.webp",
              "destination": "https://secret.example/slopdest", "geo": {"US": "1"}},
             {"id": "m" * 15, "link_id": "j" * 12, "title": "U", "is_adult": 1, "tracking": 0,
              "default_tracking_code": "", "mode": "", "icon": "i.webp", "background_image": "",
              "destination": "x", "geo": None}]
    got = d.to_json(d.public_profile(profile, links)).decode()
    want = ('{"profile":{"id":"ppppppppppppppp","username":"alice","displayName":"Alice","bio":"hi",'
            '"avatarUrl":"/api/files/profiles/ppppppppppppppp/a.webp","backgroundUrl":"","verified":true,'
            '"mode":"escape_ig"},'
            '"links":[{"id":"kkkkkkkkkkkk","title":"T","isAdult":false,"tracking":true,"default_tracknumber":"55",'
            '"mode":"direct","icon":"","backgroundImage":"/api/files/links/lllllllllllllll/b.webp"},'
            '{"id":"jjjjjjjjjjjj","title":"U","isAdult":true,"tracking":false,"mode":"escape_ig",'
            '"icon":"/api/files/links/mmmmmmmmmmmmmmm/i.webp","backgroundImage":""}]}')
    assert got == want, got
    assert "slopdest" not in got and "geo" not in got
    links[0]["bot_check"] = 1
    assert d.public_profile(profile, links, None) == json.loads(got), "keys unset: v2's shape, no botCheck"
    gated = d.public_profile(profile, links, "SITE", "/p")
    assert gated["turnstileSiteKey"] == "SITE"
    assert gated["links"][0]["botCheck"] is True and "botCheck" not in gated["links"][1]
    assert gated["profile"]["avatarUrl"] == "/p/api/files/profiles/ppppppppppppppp/a.webp"
    assert d.public_profile({**profile, "background_image": "g.webp"}, links, None, "/p")["profile"][
        "backgroundUrl"] == "/p/api/files/profiles/ppppppppppppppp/g.webp"
    assert gated["links"][1]["icon"] == "/p/api/files/links/mmmmmmmmmmmmmmm/i.webp"
    links[0]["bot_check"] = 0
    assert "turnstileSiteKey" not in d.public_profile(profile, links, "SITE"), "no gated Link: no site key"
    assert d.gated({"bot_check": 1}, "S") and not d.gated({"bot_check": 1}, None)
    assert not d.gated({"bot_check": 0}, "S") and not d.gated(None, "S")


def case_path_prefix_table():
    for raw, want in (("", ""), (None, ""), ("/p", "/p"), (" /p/ ", "/p"), ("/bio/x", "/bio/x")):
        assert d.parse_path_prefix(raw) == want, raw
    for bad in ("p", "/P", "/p q", '/p"', "//p", "/p//x", "/<x>"):
        try:
            d.parse_path_prefix(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert d.cut_prefix("/p", "/p") == "/" and d.cut_prefix("/p", "/p/") == "/"
    assert d.cut_prefix("/p", "/p/alice/12") == "/alice/12"
    assert d.cut_prefix("/p", "/px") is None and d.cut_prefix("/p", "/alice") is None
    assert d.cut_prefix("", "/p/alice") is None
    g = d.resolve_profile_request
    assert g("primary", None, "/alice/12", "/p") == {"username": "alice", "trackingCode": "12",
                                                     "profilePath": "/p/alice"}
    html = assets.INDEX.read_text()
    assert d.render_index(html, True, "") == d.render_index(html, True), "no prefix: today's page"
    page = d.render_index(html, True, "/p")
    assert '<body data-base="/p">' in page and 'href="/p/style.css"' in page
    assert 'src="/p/images/verified.svg"' in page and 'src="/p/script.js"' in page
    assert 'href="#i-lock"' in page and 'href="landing.html"' in page, "fragment and relative links untouched"
    assert not re.search(r'(?:href|src)="/(?!p/)', page), "every root-relative URL carries the prefix"
    req = {"username": "alice", "trackingCode": None, "profilePath": "/p/alice"}
    boot = d.bootstrap_page(page, req, "/p")
    assert d.parse_bootstrap(boot.encode()) == req
    assert '</script>\n    <script src="/p/script.js"></script>' in boot


def case_username_lookup():
    assert d.lookup_username("Alice") == "alice"
    for bad in ("a-b", "", "a b", "٣", "a\n"):
        assert d.lookup_username(bad) is None, bad


def case_reserved_matches_v2():
    # ~/oflinkv2/app/bin/reserved-usernames prints FIXED + routed segments + public/ entries, USERNAME-shaped only;
    # every routed segment and public entry of the v2 app is one of these or fails the 3-30 pattern.
    assert d.RESERVED == ("api", "edit", "images", "internal", "netlify")
    assert all(d.USERNAME_NEW.fullmatch(n) for n in d.RESERVED)


def case_assets_pinned():
    # Re-pin with scripts/bio-contract-diff/corpus.py:ASSET_SHA256 after reviewing both asset versions.
    pins = {"index.html": "9d3bf69e6730643866b6fd62695f8a3f", "script.js": "fa31e2e787cd4f0c536e9a8ce4a80271",
            "style.css": "29d2294e4395b02c9ad9589f93a0bbef"}
    for name, md5 in pins.items():
        assert hashlib.md5((assets.PUBLIC / name).read_bytes()).hexdigest() == md5, name
    stub = (assets.PUBLIC / "landing.html").read_text()
    assert "noindex" in stub and "href" not in stub and "src=" not in stub and "inflowwww" not in stub.lower()
    for f in assets.PUBLIC.rglob("*"):
        if f.is_file() and f.suffix in (".html", ".js", ".css"):
            assert "inflowwww" not in f.read_text().lower(), f


def case_public_page_loads_nothing_off_origin():
    # Instagram visitors' browsers must contact only our host: no CDN stylesheet, font, badge or script.
    absolute = re.compile(r"(?:https?:)?//[\w.-]+", re.I)
    for sample in ('<link href="https://cdnjs.example/x.css">',
                   '<img src="https://upload.wikimedia.example/badge.svg">',
                   '<style>@import url("https://cdn.example/x.css")</style>',
                   '<div style="background:url(https://cdn.example/x.png)">',
                   '<script>fetch("https://cdn.example/x")</script>',
                   '<style>@font-face{src:url(//cdn.example/x.woff)}</style>'):
        assert absolute.search(sample), sample
    # asHttps regex, Instagram scheme, and Turnstile's script: loaded only for a Profile JSON with a gated Link
    allowed_js_matches = {"//i", "//extbrowser", "https://challenges.cloudflare.com"}
    for sample in ('fetch("https://cdn.example/x")', '"//cdn.example/x.css"'):
        assert any(m.group() not in allowed_js_matches for m in absolute.finditer(sample)), sample
    for f in assets.PUBLIC.rglob("*"):
        if f.suffix not in (".html", ".css", ".js"):
            continue
        source = f.read_text()
        found = [m.group() for m in absolute.finditer(source)]
        bad = found if f.suffix in (".html", ".css") else [u for u in found if u not in allowed_js_matches]
        assert not bad, (f, bad)
    for f in assets.PUBLIC.rglob("*.svg"):
        assert not re.search(r"(?:href|src)\s*=\s*[\"']?(?:https?:)?//", f.read_text(), re.I), f


# ── owner admin validation (PR2a) ────────────────────────────────────

def _bad(r, field, msg=None):
    assert isinstance(r, d.Invalid) and r.field == field and (msg is None or r.msg == msg), (r, field, msg)


def case_check_profile_table():
    ok = d.check_profile({"username": " Alice_1 ", "display_name": "  Al  "}, True)
    assert ok == {"username": "alice_1", "display_name": "Al", "mode": "escape_ig"}, ok
    assert d.check_profile({"username": "abc", "display_name": "A", "mode": "direct", "account_id": None},
                           True)["mode"] == "direct"
    fmt = "Username: 3-30 lowercase letters, digits or _."
    for u in ("ab", "a" * 31, "a-b", "a b", "٣٣٣", 5, None):
        _bad(d.check_profile({"username": u, "display_name": "A"}, True), "username", fmt)
    for u in ("api", "EDIT", "images", "internal", "netlify"):
        _bad(d.check_profile({"username": u, "display_name": "A"}, True), "username", "That username is reserved.")
    _bad(d.check_profile({"display_name": "A"}, True), "username", fmt)
    _bad(d.check_profile({"username": "abc"}, True), "display_name", "Enter a display name.")
    for name in ("", "   ", "x" * 101, 3):
        _bad(d.check_profile({"display_name": name}, False), "display_name")
    _bad(d.check_profile({"display_name": "  "}, False), "display_name", "Enter a display name.")
    assert d.check_profile({"display_name": "x" * 100}, False) == {"display_name": "x" * 100}
    assert d.check_profile({"bio": "  kept as typed  "}, False) == {"bio": "  kept as typed  "}
    assert d.check_profile({"bio": ""}, False) == {"bio": ""}
    _bad(d.check_profile({"bio": "x" * 501}, False), "bio")
    for m in ("", "Direct", None, "reveal"):
        _bad(d.check_profile({"mode": m}, False), "mode")
    for v in (1, 0, "true", None):
        _bad(d.check_profile({"verified": v}, False), "verified")
    assert d.check_profile({"verified": False, "account_id": None}, False) == {"verified": False, "account_id": None}
    assert d.check_profile({"account_id": "1000001"}, False) == {"account_id": "1000001"}
    for a in ("", 5, False):
        _bad(d.check_profile({"account_id": a}, False), "account_id")
    for key in ("username", "id", "link_id", "owner_user_id", "v1_key", "slot", "sort_order", "avatar",
                "background_image", "whatever"):
        _bad(d.check_profile({key: "x"}, False), key, f"{key} can't be set here")
    _bad(d.check_profile({"\ud800": "x"}, False), "\\ud800", "\\ud800 can't be set here")
    _bad(d.check_link({"\ud800": "x"}, False), "\\ud800", "\\ud800 can't be set here")
    for key in ("id", "bio", "verified", "owner_user_id"):
        _bad(d.check_profile({"username": "abc", "display_name": "A", key: "x"}, True), key)
    assert d.check_profile({}, False) == {}


def case_check_link_table():
    base = {"title": " T ", "destination": " https://x.test/a "}
    assert d.check_link(base, True) == {"title": "T", "destination": "https://x.test/a"}
    _bad(d.check_link({"destination": "https://x"}, True), "title", "Enter a title.")
    _bad(d.check_link({"title": "T"}, True), "destination", d.DEST_MSG)
    for t in ("", "   ", "x" * 201, None):
        _bad(d.check_link({"title": t}, False), "title")
    _bad(d.check_link({"destination": "https://"}, False), "destination", "Enter a Destination after https://.")
    _bad(d.check_link({"destination": " https:// "}, False), "destination", "Enter a Destination after https://.")
    for dest in ("https://x", "http://x/y?z=1#f", "/x", "/x/y", "https://a\vb", "https://a\u00a0b", "/\u00a0x"):
        assert d.check_link({"destination": dest}, False) == {"destination": dest}, repr(dest)
    for dest in ("HTTPS://x", "//x", "ftp://x", "https://a b", "https://a\tb", "https://a\\b", "/\\x", "x",
                 "", "https:///x", "/", "/\u00a0", "https://" + "a" * 1993, 5):
        _bad(d.check_link({"destination": dest}, False), "destination")
    assert d.check_link({"destination": "https://" + "a" * 1992}, False)["destination"].startswith("https://")
    for code in ("", "0", "123456789012"):
        assert d.check_link({"default_tracking_code": code}, False) == {"default_tracking_code": code}
    for code in ("12a", "1234567890123", " 1", "٣", 5, None):
        _bad(d.check_link({"default_tracking_code": code}, False), "default_tracking_code",
             "Default Tracking Code: digits only, or leave it empty.")
    assert d.check_link({"geo": None}, False) == {"geo": None}
    assert d.check_link({"geo": {"US": "5", "DE": {"BY": "7"}}}, False) == {"geo": '{"US":"5","DE":{"BY":"7"}}'}
    for g in ([1], 5, "x", '{"US":"5"}', True):
        _bad(d.check_link({"geo": g}, False), "geo", d.GEO_MSG)
    for value in (float("nan"), float("inf")):
        _bad(d.check_link({"geo": {"US": value}}, False), "geo", d.GEO_MSG)
    _bad(d.check_profile({"display_name": "\ud800"}, False), "display_name")
    _bad(d.check_link({"title": "\ud800"}, False), "title")
    _bad(d.check_link({"geo": {"x": "y" * 8200}}, False), "geo")
    for m in ("", "direct", "escape_ig"):
        assert d.check_link({"mode": m}, False) == {"mode": m}
    _bad(d.check_link({"mode": None}, False), "mode")
    for k in ("is_adult", "tracking"):
        assert d.check_link({k: True}, False) == {k: True}
        _bad(d.check_link({k: 1}, False), k)
    for icon in (None, "onlyicon", "linkicon", "twitchicon", "igicon"):
        assert d.check_link({"icon": icon}, False) == {"icon": icon}
    for icon in ("", "x.webp", "../onlyicon", 1):
        _bad(d.check_link({"icon": icon}, False), "icon")
    for key in ("id", "link_id", "sort_order", "background_image", "v1_key", "bot_check", "profile_id"):
        _bad(d.check_link({key: "x"}, False), key, f"{key} can't be set here")
    assert d.icon_stock("onlyicon_abcdefghij.webp") == "onlyicon"
    assert d.icon_stock("custom.webp") is None and d.icon_stock("") is None and d.icon_stock("only.webp") is None


def case_new_id():
    for n in (10, 12, 15):
        ids = {files.new_id(n) for _ in range(200)}
        assert len(ids) == 200 and all(re.fullmatch(f"[a-z0-9]{{{n}}}", i) for i in ids), n
    assert d.RECORD_ID.fullmatch(files.new_id(15)) and d.LINK_ID.fullmatch(files.new_id(12))


_harness.run()
