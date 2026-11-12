"""The contract-diff corpus: every request both apps get, as raw request targets (never normalised by a client).

A case: {"name", "method", "target" (bytes, sent as-is), "host" (None: no Host header), "headers", "xff" (False: no
X-Forwarded-For), "legit" (None, or why the answers may differ: the PR1 spec's legit list)}. Burst cases ("burst": n)
are sent n times back to back from one address and compared answer by answer.
"""
from __future__ import annotations

# Re-pin both sides together after reviewing asset changes; also update the MD5 table in
# service/tests/test_bio_decide.py:case_assets_pinned.
ASSET_SHA256 = {
    "index.html": ("09cffdaf12cf606398d4d6ddb1e96e7cc94a6843364f76a626014a9adcae8464",
                   "96b81351b6a3b6fd77d24acc94cdbed87a94e11e6e70d25cab63df29d894307d"),
    "script.js": ("12f0936460ceb2e17f32f0b77327111409f623059e851618fac2c1b9393e03dc",
                  "34aa2a993971ce1ada0fce6a901e83b5147983df886219b305a7ef0b6bd82433"),
    "style.css": ("19738d2c5370860356cc36a71cdca6e9d83d825dc3297c4f6beb24976fc3f262",
                  "28714ba9316b1952e44ad7adae2a7738245011b13ffe790ac179da81182f99c4"),
}

HOSTS = ("localhost", "LOCALHOST:80", "ofl.test.", "spare.test", "alice.test", "bob.test", "nobody.test", "127.0.0.1")
A1, A2, A3, A4, A5, A6 = (f"aaaaaaaaaaa{i}" for i in range(1, 7))
SAME = {"Sec-Fetch-Site": "same-origin"}
AVATAR = "{avatar}"   # run.py puts PocketBase's stored avatar file name here

LEGIT_EDIT = "editor dropped: /edit* is the stub 404"
LEGIT_STUB = "landing: stub vs v2's marketing page (/, /landing.html, /netlify*)"
LEGIT_LANDING_IMG = "marketing landing images dropped (public/images/landing)"
LEGIT_API = "/api/upload|domain-check|collections/* not routed: #6"
LEGIT_NO_XFF = "no X-Forwarded-For: v2 500, ours keyed on the peer"
LEGIT_HOST = "malformed or missing Host: node-server 400, ours an unknown host"
LEGIT_PARSER = "raw non-ASCII target bytes: both parsers 400, uvicorn's carries a text body"
LEGIT = {
    LEGIT_EDIT: frozenset({"status", "body_sha"}),
    LEGIT_STUB: frozenset({"body_sha"}),
    LEGIT_LANDING_IMG: frozenset({"content-type", "body_sha"}),
    LEGIT_API: frozenset({"status", "cache-control", "body_sha"}),
    LEGIT_NO_XFF: frozenset({"status", "content-type", "body_sha"}),
    LEGIT_HOST: frozenset({"status", "content-type", "cache-control", "body_sha"}),
    LEGIT_PARSER: frozenset({"content-type", "body_sha"}),
}


def _c(name, target, method="GET", host="localhost", headers=None, legit=None, **kw):
    return {"name": name, "method": method, "target": target.encode("utf-8") if isinstance(target, str) else target,
            "host": host, "headers": headers or {}, "legit": legit, **kw}


def build() -> list[dict]:
    cases: list[dict] = []
    add = cases.append

    # ── #1 Profile JSON ──
    for t in ("/api/profiles/alice.json", "/api/profiles/Alice.json", "/api/profiles/alice.JSON",
              "/api/profiles/a/b.json", "/api/profiles/a%2Fb.json", "/api/profiles/nobody.json",
              "/api/profiles/carol.json", "/api/profiles/bob.json", "/api/profiles/alice",
              "/api/profiles/.json", "/api/profiles/al%69ce.json", "/api/profiles/alice.json?x=1&x=2",
              "/api/profiles/a-b.json"):
        add(_c(f"json {t}", t))
        add(_c(f"json HEAD {t}", t, method="HEAD"))

    # ── #2 ping ──
    for t in ("/v/alice", "/v/Alice", "/v/nobody", "/v/alice/", "/v/a%2Fb", "/v/carol", "/v/"):
        add(_c(f"ping POST {t}", t, method="POST", headers={"CF-IPCountry": "de", "User-Agent": "x Instagram y"}))
    for m in ("GET", "PUT", "DELETE"):
        add(_c(f"ping {m} /v/alice", "/v/alice", method=m))

    # ── #3 Reveal ──
    r = "/.netlify/functions/reveal"
    loc = {"de_by": {"CF-IPCountry": "DE", "CF-Region-Code": "BY"}, "de": {"CF-IPCountry": "DE"},
           "us": {"X-Country": "US"}, "none": {}, "ca": {"CF-IPCountry": "CA"}, "it": {"CF-IPCountry": "IT"},
           "xc_de_cf_fr": {"X-Country": "DE", "CF-IPCountry": "FR"}, "nf": {"X-Nf-Subdivision-Code": "BY",
                                                                             "X-Country": "DE"}}
    for q in (f"?id={A1}", f"?id={A1}&trackingId=4242", f"?id={A2}", f"?id={A2}&trackingId=4242",
              f"?id={A2}&trackingId=abc", f"?id={A2}&trackingId=", f"?id={A2}&trackingId=-1",
              f"?id={A2}&trackingId=1.5", f"?id={A2}&trackingId=0", f"?id={A2}&trackingId=%D9%A3",
              f"?id={A2}&trackingId=12%0A", f"?id={A2}&trackingId=1&trackingId=2", f"?id={A5}",
              f"?id={A6}&trackingId=77", "?id=nope", "?id=AAAAAAAAAAA1", "", f"?id={A1}&id=bbbbbbbbbbb1",
              f"?id={A1}x", "?id=aaaaaaaaaaa%31", f"?id={A1}&user=bob"):
        add(_c(f"reveal {q}", r + q, headers=SAME))
    for where, h in loc.items():
        add(_c(f"reveal geo {where}", f"{r}?id={A3}&trackingId=geo", headers={**SAME, **h}))
    for country, region in (("US", ""), ("GB", ""), ("FR", "1"), ("FR", "TX"),
                                   ("BR", ""), ("JP", ""), ("MX", ""),
                                   ("length", ""), ("__proto__", ""), ("ZZ", "")):
        h = {**SAME, "X-Country": country, **({"X-Region": region} if region else {})}
        add(_c(f"reveal exotic {country}/{region}", f"{r}?id={A4}&trackingId=geo", headers=h))
    origin_rows = (
        ("cross-site", {"Sec-Fetch-Site": "cross-site"}), ("same-site", {"Sec-Fetch-Site": "same-site"}),
        ("none", {"Sec-Fetch-Site": "none"}), ("no headers", {}),
        ("origin same", {"Origin": "http://localhost"}), ("origin other", {"Origin": "http://evil.test"}),
        ("origin https vs http", {"Origin": "https://localhost"}),
        ("origin https + proto", {"Origin": "https://LOCALHOST:443", "X-Forwarded-Proto": "https"}),
        ("origin null", {"Origin": "null"}), ("origin garbage", {"Origin": "garbage"}),
        ("origin ftp", {"Origin": "ftp://localhost"}), ("origin port", {"Origin": "http://localhost:8080"}),
        ("origin path", {"Origin": "http://localhost:80/x?y"}),
    )
    for name, h in origin_rows:
        add(_c(f"reveal {name}", f"{r}?id={A2}", headers=h))
    add(_c("reveal on custom host", f"{r}?id={A1}", host="alice.test", headers=SAME))
    add(_c("reveal HEAD", f"{r}?id={A1}", method="HEAD", headers=SAME))
    add(_c("reveal POST", f"{r}?id={A1}", method="POST", headers=SAME))

    # ── #4 files ──
    pid = "p00000000000001"
    for t in (f"/api/files/profiles/{pid}/{AVATAR}", f"/api/files/users/{pid}/{AVATAR}",
              f"/api/files/profiles/{pid[:-1]}/{AVATAR}", f"/api/files/profiles/{pid}/..%2F..%2Fx",
              f"/api/files/profiles/{pid}/.hidden", f"/api/files/profiles/{pid}/missing.webp",
              "/api/files/links/l00000000000001/x.webp", f"/api/files/profiles/{pid}/{AVATAR}/x"):
        add(_c(f"files {t}", t))
    add(_c("files HEAD", f"/api/files/profiles/{pid}/{AVATAR}", method="HEAD"))

    # ── #5/#6 api ──
    for t, m, legit in (("/api", "GET", None), ("/api/", "GET", None), ("/api/x", "GET", None),
                        ("/api/x", "DELETE", None), ("/api/upload/x", "POST", None),
                        ("/api/domain-check/x", "GET", None), ("/api/domain-check/x", "POST", LEGIT_API),
                        ("/api/collections/links/records", "GET", LEGIT_API),
                        ("/api/collections/links/records", "POST", LEGIT_API), ("/api/health", "GET", None),
                        ("/%61pi/x", "GET", None)):
        add(_c(f"api {m} {t}", t, method=m, legit=legit))

    # ── #7 #8 #9 #10 ──
    for t in ("/edit", "/edit/", "/edit/x", "/edit/index.html"):
        add(_c(f"edit {t}", t, legit=LEGIT_EDIT))
    add(_c("healthz", "/internal/healthz"))
    add(_c("healthz/", "/internal/healthz/"))
    add(_c("healthz POST", "/internal/healthz", method="POST"))
    for d in (None, "", "bad%20host!", "localhost", "ofl.test", "LOCALHOST", "spare.test", "alice.test", "bob.test",
              "nobody.test", "127.0.0.1", "a_b.test", "spare.test."):
        q = "" if d is None else f"?domain={d}"
        add(_c(f"tls-ask {d!r}", "/internal/tls-ask" + q))
    for t in ("/netlify", "/netlify/", "/netlify/functions/x"):
        add(_c(f"netlify {t}", t, legit=LEGIT_STUB))
    add(_c("netlify reveal on /.netlify other", "/.netlify/functions/other"))

    # ── #11 pages × hosts ──
    pages = ("/", "/alice", "/alice/123", "/alice/123/deep", "//alice//123", "/Al%69ce", "/index.html", "/style.css",
             "/script.js", "/images/igicon.webp", "/images", "/images/", "/123", "/a/b", "/nobody", "/landing.html")
    for h in HOSTS:
        for t in pages:
            legit = LEGIT_STUB if (t in ("/landing.html",) or (t == "/" and h not in ("alice.test",))) else None
            add(_c(f"page {h} {t}", t, host=h, legit=legit))
    add(_c("landing image", "/images/landing/age-gate-mobile.webp", legit=LEGIT_LANDING_IMG))

    # ── path fuzz ──
    fuzz = ("/a/../alice", "/alice/%2e%2e/bob", "/a\\b", "/%2e%2e/alice", "/%2E/alice", "/%25", "/%25alice",
            "/a%2Fb", "/%zz", "/<x>", '/"{}`', "/café", "/caf%C3%A9", "/$&", "/a&b", "/%3C/script%3E",
            "/alice?x=1", "/alice/%E2%82", "/alice/%F0%9F%98%80", "/ ", "/alice/123?trackingId=9", "/./alice",
            "/alice/.", "/alice/..", "/x/%2e%2e%2fstyle.css", "/style.css%00", "/%2e%2e%2fserver.js",
            "/images/../style.css", "/%2e%2e%2fstyle.css", "/a%2F..%2F..%2Fstyle.css",
            "/.netlify/functions/reveal/", "/v", "/api%2Fx")
    for h in ("localhost", "alice.test", "nobody.test"):
        for t in fuzz:
            raw = not t.isascii()
            to_root = t == "/alice/.." and h != "alice.test"   # resolves to / (the stub)
            add(_c(f"fuzz {h} {t!r}", t, host=h, legit=LEGIT_PARSER if raw else LEGIT_STUB if to_root else None))
    add(_c("raw latin-1 byte", b"/caf\xe9", legit=LEGIT_PARSER))
    add(_c("raw utf-8 bytes", "/café/é".encode("utf-8"), legit=LEGIT_PARSER))
    add(_c("raw #", "/alice#frag"))

    # ── methods matrix ──
    for t in ("/alice", "/api/profiles/alice.json", "/v/alice", f"{r}?id={A1}", "/internal/healthz", "/edit",
              "/netlify", "/api/x", "/", "/style.css"):
        for m in ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            legit = (LEGIT_EDIT if t == "/edit" and m in ("GET", "HEAD") else
                     LEGIT_STUB if (t == "/netlify" and m == "GET") or (t == "/" and m == "GET") else None)
            add(_c(f"method {m} {t}", t, method=m, headers=SAME if t.startswith(r) else {}, legit=legit))

    # ── headers ──
    add(_c("no XFF page", "/alice", xff=False))
    add(_c("no XFF reveal", f"{r}?id={A1}", headers=SAME, xff=False, legit=LEGIT_NO_XFF,
           extra_count=("p00000000000001", "l00000000000001", "XX", "c")))
    add(_c("no XFF ping", "/v/alice", method="POST", xff=False, legit=LEGIT_NO_XFF,
           extra_count=("p00000000000001", "", "XX", "v")))
    add(_c("no Host", "/alice", host=None, legit=LEGIT_HOST))
    add(_c("bad Host", "/alice", host="bad host!", legit=LEGIT_HOST))
    add(_c("Host with path", "/alice", host="localhost/x", legit=LEGIT_HOST))
    add(_c("in-app UA ping", "/v/carol", method="POST", headers={"User-Agent": "Barcelona Threads Instagram"}))
    add(_c("two XFF hops", "/alice", headers={"X-Forwarded-For": "1.2.3.4, 10.9.255.1"}, xff=False))

    # ── 429 bursts: one address, back to back ──
    add(_c("burst reveal", f"{r}?id={A1}", headers=SAME, burst=7))
    add(_c("burst ping", "/v/bob", method="POST", burst=7))
    add(_c("burst ping other case", "/v/BOB", method="POST", burst=2, same_ip_as="burst ping"))
    add(_c("burst reveal cross-site first", f"{r}?id={A1}", headers={"Sec-Fetch-Site": "cross-site"}, burst=3))
    add(_c("burst reveal after cross-site", f"{r}?id={A1}", headers=SAME, burst=6,
           same_ip_as="burst reveal cross-site first"))
    return cases
