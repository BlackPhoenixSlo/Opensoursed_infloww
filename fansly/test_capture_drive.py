from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "capture"))

import drive  # noqa: E402

NOW = 1000.0
PORT = 9241
TMP = tempfile.TemporaryDirectory()


def check(cond, label, fails):
    if not cond:
        fails.append(label)


def make_root(armed=True, beat=NOW - 0.5, files=(), ports=True, port=PORT):
    root = Path(tempfile.mkdtemp(dir=TMP.name))
    sid = "s1"
    sdir = root / "sessions" / sid
    sdir.mkdir(parents=True)
    if ports:
        (root / "ports").mkdir()
        (root / "ports" / f"{port}.json").write_text(json.dumps(
            {"session": sid, "armed": armed, "capture_target_id": "T1", "browser_id": "b"}))
    if beat is not None:
        (sdir / "heartbeat").write_text(json.dumps({"ts": beat}))
    for name in files:
        (sdir / name).write_text("reason\n")
    return root


def guard_table(fails):
    rows = [
        ("no port", None, "list", {}, "PORT"),
        ("9222", 9222, "list", {}, "9222"),
        ("not armed", PORT, "nav", {"armed": False}, "not armed"),
        ("stale heartbeat", PORT, "nav", {"beat": NOW - 5}, "stale"),
        ("no heartbeat", PORT, "list", {"beat": None}, "stale"),
        ("watchdog trip", PORT, "nav", {"files": ("WATCHDOG_TRIP",)}, "watchdog"),
        ("halt", PORT, "tclick", {"files": ("HALT",)}, "halted"),
        ("mirror verb, no gate", PORT, "save", {"ports": False}, "no armed gate"),
        ("skip, no gate", PORT, "skip", {"ports": False}, "no armed gate"),
        ("key, no gate", PORT, "key", {"ports": False}, "no armed gate"),
        ("wait, no gate", PORT, "wait", {"ports": False}, "no armed gate"),
        ("assets, no gate", PORT, "assets", {"ports": False}, "no armed gate"),
        ("legacy verb, no session file", PORT, "nav", {"ports": False}, None),
        ("legacy list, no session file", PORT, "list", {"ports": False}, None),
        ("legacy eval, no session file", PORT, "eval", {"ports": False}, None),
        ("9231 list, no session file", 9231, "list", {"ports": False, "port": 9231}, "no armed gate"),
        ("9231 nav, no session file", 9231, "nav", {"ports": False, "port": 9231}, "no armed gate"),
        ("9231 eval, no session file", 9231, "eval", {"ports": False, "port": 9231}, "no armed gate"),
        ("9231 nav, stale gate", 9231, "nav", {"port": 9231, "beat": NOW - 5}, "stale"),
        ("9231 nav, armed and fresh", 9231, "nav", {"port": 9231}, None),
        ("armed and fresh, mirror verb", PORT, "save", {}, None),
        ("armed and fresh, read verb", PORT, "nav", {}, None),
        ("armed and fresh, probe", 9231, "probe", {"port": 9231}, None),
        ("armed and fresh, eval", PORT, "eval", {}, "eval is refused"),
        ("armed and fresh, click", PORT, "click", {}, "click is refused"),
        ("armed and fresh, focus", PORT, "focus", {}, "focus is refused"),
        ("armed and fresh, type", PORT, "type", {}, "type is refused"),
        ("armed and fresh, insert", PORT, "insert", {}, "insert is refused"),
        ("armed and fresh, unknown verb", PORT, "submit", {}, "submit is refused"),
        ("not armed, eval", PORT, "eval", {"armed": False}, "refused"),
    ]
    for name, port, verb, kw, want in rows:
        root = make_root(**kw)
        got, ports = drive.guard(port, verb, root, NOW)
        if want is None:
            check(got is None, f"guard {name}: refused {got!r}", fails)
            on_file = kw.get("ports", True)
            check((ports or {}).get("session") == "s1" if on_file else ports is None,
                  f"guard {name}: returned ports {ports!r}", fails)
        else:
            check(got is not None and want in got, f"guard {name}: {got!r} lacks {want!r}", fails)
            check(ports is None, f"guard {name}: a refusal returns no ports", fails)
    print("guard: port rule, gate state and session verb allowlist table")


def nav_table(fails):
    obs = [{"ts": 1, "groups": {"111": 0, "222": 3}}]
    rows = [
        ("thread at zero", "https://fansly.com/messages/111", None),
        ("thread unread", "https://fansly.com/messages/222", "zero unread"),
        ("thread unknown", "https://fansly.com/messages/333", "zero unread"),
        ("deeper path under an unread thread", "https://fansly.com/messages/222/media", "zero unread"),
        ("trailing slash and query", "https://fansly.com/messages/222/?x=1", "zero unread"),
        ("case folded", "https://fansly.com/Messages/222", "zero unread"),
        ("percent-encoded segment", "https://fansly.com/%6Dessages/222", "zero unread"),
        ("dot segment", "https://fansly.com/./x/../messages/222", "zero unread"),
        ("backslash", "https://fansly.com/messages\\222", "zero unread"),
        ("inbox", "https://fansly.com/messages", None),
        ("inbox, trailing slash", "https://fansly.com/messages/", None),
        ("other page", "https://fansly.com/creator/stats/overview", None),
        ("http scheme", "http://fansly.com/messages/222", "https://fansly.com only"),
        ("www host", "https://www.fansly.com/messages/222", "https://fansly.com only"),
        ("explicit port", "https://fansly.com:443/home", "https://fansly.com only"),
        ("userinfo", "https://x" + "@fansly.com/home", "https://fansly.com only"),
        ("other origin", "https://evil.example/home", "https://fansly.com only"),
        ("javascript url", "javascript:alert(1)", "https://fansly.com only"),
    ]
    for name, url, want in rows:
        got = drive.nav_refusal(url, obs)
        if want is None:
            check(got is None, f"nav_refusal {name}: refused {got!r}", fails)
        else:
            check(got is not None and want in got, f"nav_refusal {name}: {got!r} lacks {want!r}", fails)
    print("nav_refusal: Fansly origin only, any /messages/<seg> path needs zero unread")


def thread_table(fails):
    obs = [{"ts": 1, "groups": {"g1": 2, "g2": 0}}, {"ts": 2, "groups": {"g1": 0, "g2": 1}}]
    check(drive.thread_allowed("g1", obs) is True, "thread zero in latest allowed", fails)
    check(drive.thread_allowed("g2", obs) is False, "thread unread in latest refused", fails)
    check(drive.thread_allowed("g3", obs) is False, "thread missing from latest refused", fails)
    check(drive.thread_allowed("g1", []) is False, "no observation refused", fails)
    print("thread_allowed: latest observation at zero unread")


def save_table(fails):
    entry = {"id": "creator/stats/overview", "kind": "page", "url": "/creator/stats/overview"}
    thread = {"id": "messages/thread", "kind": "page", "url": "/messages/{groupId}"}
    rows = [
        ("not in plan", None, "https://fansly.com/home", None, "plan"),
        ("url mismatch", entry, "https://fansly.com/creator/stats/content", None, "/creator/stats/content"),
        ("other origin", entry, "https://evil.example/creator/stats/overview", None, "evil.example"),
        ("match", entry, "https://fansly.com/creator/stats/overview", None, None),
        ("match, trailing slash and query", entry, "https://fansly.com/creator/stats/overview/?a=1", None, None),
        ("placeholder segment", thread, "https://fansly.com/messages/900000000000000002", None, None),
        ("placeholder is one segment", thread, "https://fansly.com/messages/1/2", None, "/messages/1/2"),
        ("redirect recorded as final_url", entry, "https://fansly.com/creator/earnings-new",
         {"url": "https://fansly.com/creator/stats/overview",
          "final_url": "https://fansly.com/creator/earnings-new"}, None),
        ("redirect from another nav", entry, "https://fansly.com/creator/earnings-new",
         {"url": "https://fansly.com/home", "final_url": "https://fansly.com/creator/earnings-new"}, "earnings-new"),
    ]
    for name, e, tab, last, want in rows:
        got = drive.save_allowed(e, tab, last)
        if want is None:
            check(got is None, f"save_allowed {name}: refused {got!r}", fails)
        else:
            check(got is not None and want in got, f"save_allowed {name}: {got!r} lacks {want!r}", fails)
    check(drive.theme_refusal("light") is None, "light theme allowed", fails)
    for theme in ("dark", "unknown", ""):
        got = drive.theme_refusal(theme)
        check(got is not None and "light" in got, f"theme {theme!r} refused: {got!r}", fails)
    print("save_allowed: plan id, URL template, recorded redirect, theme")


def key_table(fails):
    for k in ("Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"):
        check(drive.key_refusal(k) is None, f"key {k} allowed", fails)
    for k in ("Enter", "Return", " ", "a", "NumpadEnter", "escape"):
        check(drive.key_refusal(k) is not None, f"key {k!r} refused", fails)
    print("key: Escape, Tab and arrows only")


def asset_table(fails):
    rows = [
        ("https://assets.fansly.com/styles.abc.css", "Stylesheet", "text/css", True),
        ("https://assets.fansly.com/f/x.woff2", "Font", "font/woff2", True),
        ("https://assets.fansly.com/i/logo.svg", "Image", "image/svg+xml", True),
        ("https://assets.fansly.com/i/logo.png", "Image", "image/png", False),
        ("https://cdn3.fansly.com/x/a.svg", "Image", "image/svg+xml", False),
        ("https://mediav2.fansly.com/x/a.css", "Stylesheet", "text/css", False),
        ("https://assets.fansly.com/main.js", "Script", "text/javascript", False),
        ("data:text/css,x", "Stylesheet", "text/css", False),
    ]
    for url, rtype, mime, want in rows:
        check(drive.asset_wanted(url, rtype, mime) is want, f"asset_wanted {url}: != {want}", fails)
    f = drive.asset_file("https://assets.fansly.com/a/../../b/c.css?v=1")
    check(f.startswith("static/assets.fansly.com/") and ".." not in f, f"asset_file stays in static/: {f}", fails)
    print("assets: CSS, fonts, SVG; never cdn3/mediav2")


SNAP = {"html": "<html></html>", "theme": "light", "bundle_hash": "abc", "canvases": 2, "shadow_roots": 1,
        "iframes": 3}


def save_args(*extra):
    return drive._verb_args("save", ["messages/thread/state-menu", "--state", "menu", "--opener", "button.more",
                                     "--settled", ".cdk-overlay-pane", *extra])


def meta_table(fails):
    a = save_args("--reset-key", "Escape", "--reset-gone", ".cdk-overlay-pane")
    entry = {"id": "messages/thread/state-menu", "kind": "state", "url": "/messages/{groupId}"}
    tab = "https://fansly.com/messages/111"
    m = drive.save_meta(entry, a, tab, None, SNAP, "s1", 5.0)
    want = {"id": "messages/thread/state-menu", "kind": "state", "url": tab, "final_url": tab, "state": "menu",
            "opener": "button.more", "settled_selector": ".cdk-overlay-pane",
            "reset": {"key": "Escape", "gone": ".cdk-overlay-pane"}, "bundle_hash": "abc", "theme": "light",
            "session": "s1", "canvases": 2, "shadow_roots": 1, "iframes": 3, "saved_at": 5.0}
    check(m == want, f"meta of a State save: {m}", fails)
    redirect = {"url": "https://fansly.com/creator/stats/overview", "final_url": "https://fansly.com/creator/x"}
    m = drive.save_meta({"id": "creator/stats/overview", "kind": "page", "url": "/creator/stats/overview"},
                        save_args(), "https://fansly.com/creator/x", redirect, SNAP, "s1", 5.0)
    check(m["url"] == "https://fansly.com/creator/stats/overview" and m["final_url"] == "https://fansly.com/creator/x"
          and m["reset"] is None and m["kind"] == "page",
          f"a redirected page stores the nav URL as url and the tab as final_url: {m}", fails)
    m = drive.save_meta(entry, a, tab, {"url": "https://fansly.com/home", "final_url": "https://fansly.com/home"},
                        SNAP, "s1", 5.0)
    check(m["url"] == tab, f"an older nav to another page is not taken as a redirect: {m['url']}", fails)
    m = drive.save_meta(entry, save_args("--reset-click", "button.more", "--reset-gone", ".open"), tab, None,
                        SNAP, "s1", 5.0)
    check(m["reset"] == {"click": "button.more", "gone": ".open"}, f"meta of a click-reset State: {m['reset']}", fails)
    check(drive.save_args_refusal({"kind": "state"}, save_args("--reset-click", "button.more", "--reset-gone", ".open"))
          is None, "a click-reset State is allowed", fails)
    for extra in (["--reset-key", "Escape"], ["--reset-gone", ".x"], ["--reset-click", ".x"],
                  ["--reset-key", "Escape", "--reset-click", ".x", "--reset-gone", ".y"]):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                save_args(*extra)
            ok = False
        except SystemExit:
            ok = True
        check(ok, f"save {' '.join(extra)} alone is refused when parsing", fails)
    check(drive.save_args_refusal({"kind": "state"}, save_args()) is not None, "a State needs the reset flags", fails)
    check(drive.save_args_refusal({"kind": "page"}, save_args()) is None, "a page needs no reset", fails)
    got = drive.save_args_refusal({"kind": "state"}, save_args("--reset-key", "Enter", "--reset-gone", ".x"))
    check(got is not None and "Enter" in got, f"reset key Enter refused: {got!r}", fails)
    print("save_meta: every field, redirect, reset flags both or neither")


def save_roundtrip(fails):
    root = Path(tempfile.mkdtemp(dir=TMP.name))
    pages = root / "pages" / "messages" / "thread"
    entry = {"id": "messages/thread/state-menu", "kind": "state", "url": "/messages/{groupId}"}
    meta = drive.save_meta(entry, save_args("--reset-key", "Escape", "--reset-gone", ".cdk-overlay-pane"),
                           "https://fansly.com/messages/111", None, SNAP, "s1", 5.0)
    calls = []

    def closer(result):
        async def close():
            calls.append(result)
            check(not (pages / "state-menu.meta.json").exists(), "no meta before the State closed", fails)
            if isinstance(result, Exception):
                raise result
            return result
        return close

    def files():
        return sorted(p.name for p in pages.iterdir()) if pages.exists() else []

    for result in (False, None, RuntimeError("ws gone")):
        try:
            kept = asyncio.run(drive.finish_save(root, meta["id"], "<html></html>", b"png", meta, closer(result)))
        except RuntimeError:
            kept = "raised"
        check(kept in (False, "raised") and files() == [], f"failed reset {result!r} leaves no entry: {files()}", fails)
    kept = asyncio.run(drive.finish_save(root, meta["id"], "<html>1</html>", b"png", meta, closer(True)))
    check(kept is True and files() == ["state-menu.html", "state-menu.meta.json", "state-menu.png"],
          f"closed State kept, no temp files: {files()}", fails)
    check(json.loads((pages / "state-menu.meta.json").read_text()) == meta, "meta written as built", fails)
    check((pages / "state-menu.png").read_bytes() == b"png", "png kept", fails)
    n = len(calls)
    page_meta = {**meta, "reset": None, "session": "s2"}
    kept = asyncio.run(drive.finish_save(root, meta["id"], "<html>2</html>", b"png2", page_meta, closer(False)))
    check(kept is True and len(calls) == n, "a save with no reset keeps its files without a reset", fails)
    got = json.loads((pages / "state-menu.meta.json").read_text())
    check(got["session"] == "s2" and (pages / "state-menu.html").read_text() == "<html>2</html>",
          "re-save replaces the entry", fails)
    print("save: kept only once the State closed, re-save replaces")


FA_CSS = "https://assets.fansly.com/fonts/fontawesome-pro-plus-7.2/css/all.min.css"
FA_FONTS = "https://assets.fansly.com/fonts/fontawesome-pro-plus-7.2/webfonts/"


def font_url_table(fails):
    rows = [
        ("double quoted", 'src:url("../webfonts/a.woff2") format("woff2")', [FA_FONTS + "a.woff2"]),
        ("single quoted", "src:url('../webfonts/a.woff2')", [FA_FONTS + "a.woff2"]),
        ("unquoted, spaces", "src:url( ../webfonts/a.woff2 )", [FA_FONTS + "a.woff2"]),
        ("absolute", "src:url(https://assets.fansly.com/f/b.woff2)", ["https://assets.fansly.com/f/b.woff2"]),
        ("protocol relative", "src:url(//assets.fansly.com/f/b.woff2)", ["https://assets.fansly.com/f/b.woff2"]),
        ("query kept, fragment dropped", "src:url(../webfonts/a.woff2?v=7#x)", [FA_FONTS + "a.woff2?v=7"]),
        ("upper case extension", "src:url(../webfonts/A.WOFF2)", [FA_FONTS + "A.WOFF2"]),
        ("other formats dropped", "src:url(a.woff) format('woff'),url(a.ttf),url(a.eot?#iefix),url(a.svg#fa)", []),
        ("data uri ignored", "src:url(data:font/woff2;base64,AAAA) format('woff2')", []),
        ("quoted data uri ignored", 'src:url("data:font/woff2;base64,d09GMg==")', []),
        ("duplicates once", "src:url(../webfonts/a.woff2);src:url('../webfonts/a.woff2')", [FA_FONTS + "a.woff2"]),
        ("order kept", "url(../webfonts/b.woff2) url(../webfonts/a.woff2)", [FA_FONTS + "b.woff2", FA_FONTS + "a.woff2"]),
        ("non-http resolution dropped", "src:url(javascript:x.woff2)", []),
        ("none", "a{color:red}", []),
    ]
    for name, css, want in rows:
        got = drive.css_font_urls(css, FA_CSS)
        check(got == want, f"css_font_urls {name}: {got}", fails)
    print("css_font_urls: url() refs resolved against the stylesheet, woff2 only, no data:")


class FakeCDP:
    def __init__(self, routes):
        self.routes, self.sent, self.inbox = routes, [], []

    async def send(self, raw):
        m = json.loads(raw)
        self.sent.append(m)
        got = self.routes(m["method"], m.get("params") or {})
        reply = {"id": m["id"], "error": got["error"]} if "error" in got else {"id": m["id"], "result": got}
        self.inbox.append(json.dumps(reply))

    async def recv(self):
        return self.inbox.pop(0)


def assets_roundtrip(fails):
    import base64
    root = Path(tempfile.mkdtemp(dir=TMP.name))
    old_css = "https://assets.fansly.com/old/site.css"
    old_rel = drive.asset_file(old_css)
    (root / old_rel).parent.mkdir(parents=True)
    (root / old_rel).write_text("@font-face{src:url(fonts/old.woff2)}@font-face{src:url(fonts/have.woff2)}")
    have = "https://assets.fansly.com/old/fonts/have.woff2"
    (root / "assets.json").write_text(json.dumps([
        {"url": old_css, "file": old_rel, "session": "s0"},
        {"url": have, "file": drive.asset_file(have), "session": "s0"},
    ]))
    fa = ("@font-face{src:url(../webfonts/fa-solid-900.woff2) format('woff2'),url(../webfonts/fa-solid-900.ttf)}"
          "@font-face{src:url('../webfonts/fa-gone.woff2')}@font-face{src:url(../webfonts/fa-404.woff2)}"
          "@font-face{src:url(https://cdn3.fansly.com/x/user.woff2)}")
    tree = {"frameTree": {"frame": {"id": "F1"}, "resources": [
        {"url": FA_CSS, "type": "Stylesheet", "mimeType": "text/css"},
        {"url": "https://assets.fansly.com/broken.css", "type": "Stylesheet", "mimeType": "text/css"},
    ]}}
    streams = {"s1": [{"data": base64.b64encode(b"wOF2").decode(), "base64Encoded": True, "eof": False},
                      {"data": "xyz", "eof": True}],
               "s2": [{"data": base64.b64encode(b"OLD").decode(), "base64Encoded": True, "eof": True}]}
    by_url = {FA_FONTS + "fa-solid-900.woff2": "s1", "https://assets.fansly.com/old/fonts/old.woff2": "s2"}

    def routes(method, p):
        if method == "Page.getResourceTree":
            return tree
        if method == "Page.getResourceContent":
            if p["url"] == FA_CSS:
                return {"content": fa, "base64Encoded": False}
            return {"error": {"code": -32000, "message": "No resource with given URL found"}}
        if method == "Network.loadNetworkResource":
            if p["url"] == FA_FONTS + "fa-404.woff2":
                return {"resource": {"success": True, "httpStatusCode": 404, "stream": "s3"}}
            if p["url"] in by_url:
                return {"resource": {"success": True, "httpStatusCode": 200, "stream": by_url[p["url"]]}}
            return {"resource": {"success": False, "netError": -6, "netErrorName": "net::ERR_FILE_NOT_FOUND"}}
        if method == "IO.read":
            return streams[p["handle"]].pop(0)
        if method == "IO.close":
            return {}
        return {"error": {"code": -32601, "message": f"unexpected {method}"}}

    ws = FakeCDP(routes)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = asyncio.run(drive.cmd_assets(ws, root, "s1"))
    check(rc == 0, f"assets returns 0: {rc}", fails)
    check(out.getvalue().strip() == "assets: 3 new, 5 total, 3 failed", f"assets summary: {out.getvalue()!r}", fails)
    rows = json.loads((root / "assets.json").read_text())
    urls = [r["url"] for r in rows]
    check(urls == [old_css, have, FA_CSS, "https://assets.fansly.com/old/fonts/old.woff2",
                   FA_FONTS + "fa-solid-900.woff2"], f"assets rows: {urls}", fails)
    check(all(r["session"] == "s1" and r["file"] == drive.asset_file(r["url"]) for r in rows[2:]),
          f"new rows carry session and file: {rows[2:]}", fails)
    check((root / drive.asset_file(FA_FONTS + "fa-solid-900.woff2")).read_bytes() == b"wOF2xyz",
          "font stream read to eof, base64 and text chunks", fails)
    check((root / drive.asset_file("https://assets.fansly.com/old/fonts/old.woff2")).read_bytes() == b"OLD",
          "font of a stylesheet already on disk fetched", fails)
    loads = [m["params"] for m in ws.sent if m["method"] == "Network.loadNetworkResource"]
    check([x["url"] for x in loads] == ["https://assets.fansly.com/old/fonts/old.woff2",
                                        FA_FONTS + "fa-solid-900.woff2", FA_FONTS + "fa-gone.woff2",
                                        FA_FONTS + "fa-404.woff2"],
          f"fonts fetched: woff2 only, no user media, none already saved: {[x['url'] for x in loads]}", fails)
    check(all(x["frameId"] == "F1" and x["options"] == {"disableCache": False, "includeCredentials": False}
              for x in loads), f"loadNetworkResource on the main frame without credentials: {loads}", fails)
    closed = [m["params"]["handle"] for m in ws.sent if m["method"] == "IO.close"]
    check(closed == ["s2", "s1", "s3"], f"every stream closed: {closed}", fails)
    lines = err.getvalue().splitlines()
    check(len(lines) == 3 and "broken.css" in lines[0] and "ERR_FILE_NOT_FOUND" in lines[1] and "404" in lines[2],
          f"each failure printed: {lines}", fails)
    print("assets: stylesheet fonts fetched over the network, failures counted")


def main(argv) -> int:
    fails: list[str] = []
    guard_table(fails)
    thread_table(fails)
    nav_table(fails)
    meta_table(fails)
    save_table(fails)
    key_table(fails)
    asset_table(fails)
    save_roundtrip(fails)
    font_url_table(fails)
    assets_roundtrip(fails)
    for f in fails:
        print(f"  FAIL {f}", file=sys.stderr)
    if fails:
        print(f"{len(fails)} check(s) failed", file=sys.stderr)
        return 1
    print("all capture drive checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
