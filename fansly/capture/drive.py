#!/usr/bin/env python3
"""
drive.py — steer the recording Chrome from the CLI. PORT is required (9222 is refused).

  PORT=9223 ../../venv/bin/python drive.py list
  ../../venv/bin/python drive.py nav https://fansly.com/messages
  ../../venv/bin/python drive.py shot /tmp/page.png
  ../../venv/bin/python drive.py click 'a[href*="statements"]'
  ../../venv/bin/python drive.py eval 'document.title'
  ../../venv/bin/python drive.py links            # every visible link+button

Attaches straight to a PAGE target's own debugger socket, so it does not touch
the browser-level auto-attach that record.py is holding — the two run side by
side and driving the page is itself captured.

`shot` matters more than it looks: it lets the agent LOOK at the page instead of
guessing selectors, which is how you find a view (a creator sales/statements
page) whose URL nobody has written down.

Mirror capture verbs (refused unless `gate.py run` holds a fresh armed gate on PORT;
`--root R` finds it, default ~/Downloads/fansly-live-capture):

  drive.py tclick <sel>                       trusted mouse click at the element centre
  drive.py key <Escape|Tab|ArrowUp|ArrowDown|ArrowLeft|ArrowRight>
  drive.py wait [--gone] <sel> [--timeout s]
  drive.py save <id> --state <page|name> --opener <sel> --settled <sel> [--reset-key K --reset-gone <sel>]
  drive.py assets                             CSS, fonts, SVG of the tab into static/
  drive.py skip <id> --reason <text> --tried <sel> [<sel> ...]

With a gate session open on PORT only nav, list, shot, links, text and the mirror verbs
run, only while the gate is armed, fresh, untripped and not halted, and only on the
capture tab the gate recorded; nav goes to https://fansly.com only. On the creator
capture port 9231 every verb needs that gate.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import posixpath
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

import gate
import store
from audit import read_jsonl
from mirror import FANSLY_ORIGIN, fill, load_plan, url_matches

CAPTURE_PORT = 9231
MIRROR_VERBS = frozenset({"tclick", "key", "wait", "save", "assets", "skip"})
SESSION_VERBS = MIRROR_VERBS | {"nav", "list", "shot", "links", "text", "probe"}
KEYS = {"Escape": 27, "Tab": 9, "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40}
USER_MEDIA_LABELS = frozenset({"cdn3", "mediav2"})


def env_port():
    try:
        return int(os.environ["PORT"])
    except (KeyError, ValueError):
        return None


def guard(port, verb: str, root: Path, now: float):
    if port is None:
        return "PORT is not set: drive.py needs an explicit PORT", None
    if port == gate.REFUSED_PORT:
        return f"PORT {gate.REFUSED_PORT} is the unrelated Chrome; never touched", None
    ports = store.read_ports(root, port)
    if ports is None:
        if port == CAPTURE_PORT:
            return f"no armed gate on :{port}, the creator capture port: every verb needs gate.py run", None
        if verb in MIRROR_VERBS:
            return f"no armed gate on :{port}: {verb} needs gate.py run", None
        return None, None
    if verb not in SESSION_VERBS:
        return (f"{verb} is refused while a gate session is open on :{port}; "
                f"only {', '.join(sorted(SESSION_VERBS))}"), None
    sdir = store.session_dir(root, str(ports.get("session")))
    if (sdir / "WATCHDOG_TRIP").exists():
        why = "the watchdog tripped"
    elif (sdir / "HALT").exists():
        why = "the session halted"
    elif not ports.get("armed"):
        why = "the session is not armed yet"
    elif store.is_stale(store.read_beat(sdir / "heartbeat")[0], now, gate.STALE_AFTER):
        why = "the gate heartbeat is stale"
    else:
        return None, ports
    return f"no armed gate on :{port} (session {ports.get('session')}): {why}", None


def thread_allowed(group_id: str, unread_obs: list) -> bool:
    if not unread_obs:
        return False
    return (unread_obs[-1].get("groups") or {}).get(str(group_id)) == 0


def nav_refusal(url: str, unread_obs: list):
    s = urllib.parse.urlsplit((url or "").strip())
    if f"{s.scheme}://{s.netloc}".lower() != FANSLY_ORIGIN:
        return f"nav under the gate goes to {FANSLY_ORIGIN} only, not {s.scheme}://{s.netloc}"
    path = posixpath.normpath("/" + urllib.parse.unquote(s.path).replace("\\", "/"))
    segs = [x for x in path.split("/") if x]
    if len(segs) >= 2 and segs[0].lower() == "messages" and not thread_allowed(segs[1], unread_obs):
        return ("that thread is not at zero unread in the gate's latest /messaging/groups "
                "observation; nav /messages first")
    return None


def save_allowed(entry, tab_url: str, last_nav):
    if entry is None:
        return "not a mirror plan entry"
    if url_matches(entry["url"], tab_url):
        return None
    if last_nav and last_nav.get("final_url") == tab_url and url_matches(entry["url"], last_nav.get("url", "")):
        return None
    s = urllib.parse.urlsplit(tab_url or "")
    return f"the tab is on {s.netloc}{s.path}, not {entry['id']}'s {entry['url']}"


def theme_refusal(theme: str):
    return None if theme == "light" else f"the page shows theme {theme!r}; capture is light only"


def key_refusal(key: str):
    return None if key in KEYS else f"key {key!r} refused: only {', '.join(KEYS)}"


def asset_wanted(url: str, resource_type: str, mime: str) -> bool:
    s = urllib.parse.urlsplit(url)
    if s.scheme not in ("http", "https"):
        return False
    if USER_MEDIA_LABELS & set((s.hostname or "").lower().split(".")):
        return False
    if resource_type in ("Stylesheet", "Font"):
        return True
    return "svg" in (mime or "") or s.path.lower().endswith(".svg")


def asset_file(url: str) -> str:
    s = urllib.parse.urlsplit(url)
    segs = [re.sub(r"[^A-Za-z0-9._-]", "_", x) for x in s.path.split("/") if x not in ("", ".", "..")]
    segs = [x for x in segs if x.strip(".")] or ["index"]
    if s.query:
        segs[-1] += "__" + hashlib.sha1(s.query.encode()).hexdigest()[:8]
    host = re.sub(r"[^A-Za-z0-9.-]", "_", s.hostname or "host")
    return "/".join(["static", host, *segs])


_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.S)


def css_font_urls(css: str, base: str) -> list[str]:
    out = []
    for _, ref in _CSS_URL.findall(css):
        url = urllib.parse.urldefrag(urllib.parse.urljoin(base, ref.strip()))[0]
        s = urllib.parse.urlsplit(url)
        if s.scheme in ("http", "https") and s.path.lower().endswith(".woff2") and url not in out:
            out.append(url)
    return out


def save_args_refusal(entry, a):
    if entry["kind"] == "state" and not a.reset_gone:
        return f"save {a.id}: a State needs --reset-key or --reset-click, and --reset-gone"
    return key_refusal(a.reset_key) if a.reset_key else None


def save_meta(entry, a, tab_url: str, last_nav, snap: dict, session: str, now: float) -> dict:
    redirected = bool(last_nav) and last_nav.get("final_url") == tab_url
    return {"id": a.id, "kind": entry["kind"], "url": last_nav["url"] if redirected else tab_url,
            "final_url": tab_url, "state": a.state, "opener": a.opener, "settled_selector": a.settled,
            "reset": ({"click": a.reset_click} if a.reset_click else {"key": a.reset_key}) | {"gone": a.reset_gone}
            if a.reset_gone else None,
            "bundle_hash": snap["bundle_hash"], "theme": snap["theme"], "session": session,
            "canvases": snap["canvases"], "shadow_roots": snap["shadow_roots"], "iframes": snap["iframes"],
            "saved_at": now}


def stage_save(root: Path, entry_id: str, html: str, png: bytes, meta: dict) -> list:
    base = root / "pages" / entry_id
    base.parent.mkdir(parents=True, exist_ok=True)
    staged = []
    html_bytes = html.encode()
    saved = {**meta, "sha256": {"file": hashlib.sha256(html_bytes).hexdigest(),
                               "png": hashlib.sha256(png).hexdigest()}}
    for ext, data in ((".html", html_bytes), (".png", png),
                      (".meta.json", json.dumps(saved, ensure_ascii=False).encode())):
        final = base.with_name(base.name + ext)
        tmp = final.with_name(f".{final.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        staged.append((tmp, final))
    return staged


def commit_save(staged: list, keep: bool) -> None:
    for tmp, final in staged:
        if keep:
            os.replace(tmp, final)
        else:
            tmp.unlink(missing_ok=True)


async def finish_save(root: Path, entry_id: str, html: str, png: bytes, meta: dict, close_state) -> bool:
    staged = stage_save(root, entry_id, html, png, meta)
    closed = False
    try:
        closed = meta["reset"] is None or (await close_state()) is True
    finally:
        commit_save(staged, keep=closed)
    return closed


def page_targets(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


_dlg_id = [9000]


async def call(ws, mid: int, method: str, params: dict | None = None) -> dict:
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))

        # A native dialog blocks the page and Page.navigate never returns. beforeunload/alert: accept; confirm/prompt: DISMISS (auto-confirming an unknown native dialog could commit something destructive).
        if msg.get("method") == "Page.javascriptDialogOpening":
            dtype = (msg.get("params") or {}).get("type", "")
            accept = dtype in ("beforeunload", "alert")
            _dlg_id[0] += 1
            await ws.send(json.dumps({"id": _dlg_id[0],
                                      "method": "Page.handleJavaScriptDialog",
                                      "params": {"accept": accept}}))
            print(f"[js dialog {dtype} -> {'accept' if accept else 'dismiss'}]",
                  file=sys.stderr)
            continue

        if msg.get("id") == mid:
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


async def evaluate(ws, mid: int, expr: str):
    res = await call(ws, mid, "Runtime.evaluate", {
        "expression": expr, "returnByValue": True, "awaitPromise": True,
        "userGesture": True,
    })
    if res.get("exceptionDetails"):
        return {"error": str(res["exceptionDetails"])[:400]}
    return res.get("result", {}).get("value")


SNAPSHOT_JS = """(() => {
  const dt = document.doctype ? new XMLSerializer().serializeToString(document.doctype) + '\\n' : '';
  const rgb = el => { if (!el) return null; const m = getComputedStyle(el).backgroundColor.match(/[\\d.]+/g);
    return !m || (m.length > 3 && +m[3] === 0) ? null : m.slice(0, 3).map(Number) };
  const bg = rgb(document.body) || rgb(document.documentElement) || [255, 255, 255];
  let shadow = 0; for (const e of document.querySelectorAll('*')) if (e.shadowRoot) shadow++;
  const hash = [...document.scripts].map(s => (s.src.match(/\\/main[.-]([0-9a-f]{6,})/) || [])[1]).find(Boolean);
  return {html: dt + document.documentElement.outerHTML,
          theme: (0.2126 * bg[0] + 0.7152 * bg[1] + 0.0722 * bg[2]) / 255 >= 0.5 ? 'light' : 'dark',
          bundle_hash: hash || '', canvases: document.querySelectorAll('canvas').length,
          shadow_roots: shadow, iframes: document.querySelectorAll('iframe').length};
})()"""


def _refuse(msg: str) -> int:
    print(f"refused: {msg}", file=sys.stderr)
    return 2


def _pop_root(argv: list) -> tuple[Path, list]:
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser(), argv[:i] + argv[i + 2:]
    return gate.DEFAULT_ROOT, argv


def _verb_args(cmd: str, rest: list):
    ap = argparse.ArgumentParser(prog=f"drive.py {cmd}")
    if cmd == "save":
        ap.add_argument("id")
        ap.add_argument("--state", required=True)
        ap.add_argument("--opener", required=True)
        ap.add_argument("--settled", required=True)
        ap.add_argument("--reset-key")
        ap.add_argument("--reset-click")
        ap.add_argument("--reset-gone")
        ap.add_argument("--timeout", type=float, default=15.0)
        a = ap.parse_args(rest)
        if a.reset_key and a.reset_click:
            ap.error("--reset-key and --reset-click are exclusive")
        if bool(a.reset_key or a.reset_click) != bool(a.reset_gone):
            ap.error("--reset-key or --reset-click goes with --reset-gone")
        return a
    elif cmd == "wait":
        ap.add_argument("selector")
        ap.add_argument("--gone", action="store_true")
        ap.add_argument("--timeout", type=float, default=15.0)
    elif cmd == "skip":
        ap.add_argument("id")
        ap.add_argument("--reason", required=True)
        ap.add_argument("--tried", nargs="+", required=True)
    elif cmd in ("tclick", "key"):
        ap.add_argument("arg")
    return ap.parse_args(rest)


def _plan_entry(entry_id: str, root: Path):
    entry = {e["id"]: e for e in load_plan()}.get(entry_id)
    if entry is None:
        return None
    creator = next((i for i in store.known_identities(root) if i.get("role") == "creator"), {})
    return {**entry, "url": fill(entry["url"], {"username": creator.get("username")} if creator else {})}


def cmd_skip(a, root: Path, session: str) -> int:
    entry = {e["id"]: e for e in load_plan()}.get(a.id)
    if entry is None:
        return _refuse(f"{a.id} is not a mirror plan entry")
    if not entry.get("optional"):
        return _refuse(f"{a.id} is not optional; only an optional entry can be skipped")
    if not a.reason.strip() or not any(t.strip() for t in a.tried):
        return _refuse("skip needs a --reason and the --tried selectors")
    path = root / "skipped.json"
    rows = [r for r in (store.read_json(path) or []) if r.get("id") != a.id]
    rows.append({"id": a.id, "reason": a.reason, "tried": a.tried, "session": session, "ts": time.time()})
    store.write_json(path, rows)
    print(f"skipped {a.id}")
    return 0


async def wait_for(ws, selector: str, gone: bool, timeout: float) -> bool:
    end = time.time() + timeout
    js = (f"[...document.querySelectorAll({json.dumps(selector)})]"
          ".some(e=>e.getClientRects().length>0)")
    while True:
        if (await evaluate(ws, 40, js)) is (not gone):
            return True
        if time.time() >= end:
            return False
        await asyncio.sleep(0.2)


async def press(ws, key: str) -> None:
    code = KEYS[key]
    for typ in ("rawKeyDown", "keyUp"):
        await call(ws, 41, "Input.dispatchKeyEvent", {"type": typ, "key": key, "code": key,
                                                      "windowsVirtualKeyCode": code,
                                                      "nativeVirtualKeyCode": code})


async def settled_href(ws, quiet: float = 2.0, cap: float = 10.0) -> str:
    href, since, waited = await evaluate(ws, 3, "location.href"), 0.0, 0.0
    while since < quiet and waited < cap:
        await asyncio.sleep(0.5)
        waited += 0.5
        now = await evaluate(ws, 3, "location.href")
        since = since + 0.5 if now == href else 0.0
        href = now
    return href


async def tclick(ws, selector: str):
    js = (f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return null;"
          "e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();"
          "return {x:r.left+r.width/2,y:r.top+r.height/2,"
          "label:(e.innerText||e.getAttribute('aria-label')||e.tagName).slice(0,40)};})()")
    at = await evaluate(ws, 42, js)
    if not isinstance(at, dict) or "x" not in at:
        return None
    base = {"x": at["x"], "y": at["y"], "button": "left", "clickCount": 1}
    await call(ws, 43, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": at["x"], "y": at["y"]})
    await call(ws, 44, "Input.dispatchMouseEvent", {"type": "mousePressed", **base})
    await call(ws, 45, "Input.dispatchMouseEvent", {"type": "mouseReleased", **base})
    return at["label"]


async def cmd_save(ws, a, root: Path, session: str) -> int:
    entry = _plan_entry(a.id, root)
    if entry and "{username}" in entry["url"]:
        return _refuse("the creator username is not read yet; open a page so /account/me is seen")
    sdir = store.session_dir(root, session)
    tab_url = await evaluate(ws, 50, "location.href")
    last_nav = store.read_json(sdir / "last_nav.json")
    if r := save_allowed(entry, tab_url, last_nav):
        return _refuse(f"save {a.id}: {r}")
    if r := save_args_refusal(entry, a):
        return _refuse(r)
    if not await wait_for(ws, a.settled, False, a.timeout):
        return _refuse(f"save {a.id}: {a.settled!r} never appeared")
    snap = await evaluate(ws, 51, SNAPSHOT_JS)
    if not isinstance(snap, dict) or "html" not in snap:
        return _refuse(f"save {a.id}: snapshot failed {str(snap)[:200]}")
    if r := theme_refusal(snap["theme"]):
        return _refuse(f"save {a.id}: {r}")
    png = base64.b64decode((await call(ws, 52, "Page.captureScreenshot", {"format": "png"}))["data"])
    meta = save_meta(entry, a, tab_url, last_nav, snap, session, time.time())

    async def close_state() -> bool:
        if a.reset_click:
            if await tclick(ws, a.reset_click) is None:
                return False
        else:
            await press(ws, a.reset_key)
        return await wait_for(ws, a.reset_gone, True, a.timeout)

    if not await finish_save(root, a.id, snap["html"], png, meta, close_state):
        return _refuse(f"save {a.id}: reset left {a.reset_gone!r} open; no entry written")
    print(f"saved {a.id}: canvases {snap['canvases']} shadow_roots {snap['shadow_roots']} "
          f"iframes {snap['iframes']} theme {snap['theme']}")
    return 0


def _frames(tree: dict):
    yield tree
    for child in tree.get("childFrames") or ():
        yield from _frames(child)


async def fetch_resource(ws, frame_id: str, url: str) -> bytes:
    r = (await call(ws, 62, "Network.loadNetworkResource", {
        "frameId": frame_id, "url": url, "options": {"disableCache": False, "includeCredentials": False},
    })).get("resource") or {}
    stream, status = r.get("stream"), r.get("httpStatusCode")
    chunks = []
    try:
        if not r.get("success") or not stream or (status is not None and not 200 <= status < 300):
            raise RuntimeError(r.get("netErrorName") or f"http {status}")
        while True:
            c = await call(ws, 63, "IO.read", {"handle": stream})
            d = c.get("data", "")
            chunks.append(base64.b64decode(d) if c.get("base64Encoded") else d.encode())
            if c.get("eof"):
                break
    finally:
        if stream:
            await call(ws, 64, "IO.close", {"handle": stream})
    return b"".join(chunks)


def _keep(root: Path, rows: list, have: set, url: str, data: bytes, session: str) -> None:
    rel = asset_file(url)
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    rows.append({"url": url, "file": rel, "session": session})
    have.add(url)


async def cmd_assets(ws, root: Path, session: str) -> int:
    tree = (await call(ws, 60, "Page.getResourceTree"))["frameTree"]
    path = root / "assets.json"
    rows = store.read_json(path) or []
    have = {r.get("url") for r in rows}
    start, failed = len(rows), 0
    for fr in _frames(tree):
        fid = fr["frame"]["id"]
        for res in fr.get("resources") or ():
            url = res.get("url", "")
            if url in have or not asset_wanted(url, res.get("type", ""), res.get("mimeType", "")):
                continue
            try:
                c = await call(ws, 61, "Page.getResourceContent", {"frameId": fid, "url": url})
            except RuntimeError as e:
                failed += 1
                print(f"assets: failed {url}: {e}", file=sys.stderr)
                continue
            data = base64.b64decode(c["content"]) if c.get("base64Encoded") else c["content"].encode()
            _keep(root, rows, have, url, data, session)
    for row in list(rows):
        url, css = row.get("url") or "", root / (row.get("file") or "")
        if not urllib.parse.urlsplit(url).path.lower().endswith(".css") or not css.is_file():
            continue
        for font in css_font_urls(css.read_text(errors="replace"), url):
            if font in have or not asset_wanted(font, "Font", ""):
                continue
            try:
                data = await fetch_resource(ws, tree["frame"]["id"], font)
            except RuntimeError as e:
                failed += 1
                print(f"assets: failed {font}: {e}", file=sys.stderr)
                continue
            _keep(root, rows, have, font, data, session)
    store.write_json(path, rows)
    print(f"assets: {len(rows) - start} new, {len(rows)} total, {failed} failed")
    return 0


async def main() -> int:
    root, argv = _pop_root(sys.argv[1:])
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    arg = rest[0] if rest else ""
    port = env_port()
    r, ports = guard(port, cmd, root, time.time())
    if r:
        return _refuse(r)
    a = _verb_args(cmd, rest) if cmd in MIRROR_VERBS else None
    if cmd == "key" and (r := key_refusal(a.arg)):
        return _refuse(r)
    session = str(ports["session"]) if ports else ""
    if cmd == "skip":
        return cmd_skip(a, root, session)

    targets = page_targets(port)
    if not targets:
        print("no page targets — is Chrome running with start_chrome.sh?", file=sys.stderr)
        return 2

    if cmd == "list":
        for i, t in enumerate(targets):
            print(f"[{i}] {t.get('title','')[:60]!r}\n     {t.get('url','')[:140]}")
        return 0

    if ports:
        tgt = next((t for t in targets if t.get("id") == ports.get("capture_target_id")), None)
        if tgt is None:
            return _refuse("the gate's capture tab is gone; gate.py stop and start a new session")
    else:
        tgt = next((t for t in targets if "fansly.com" in (t.get("url") or "")), targets[0])

    if cmd == "nav" and arg.startswith("/"):
        arg = FANSLY_ORIGIN + arg
    if ports and cmd == "nav" and (r := nav_refusal(arg, read_jsonl(
            store.session_dir(root, session) / "unread.jsonl"))):
        return _refuse(r)

    async with websockets.connect(tgt["webSocketDebuggerUrl"],
                                  max_size=100 * 1024 * 1024) as ws:
        # Page domain on for every command: without it the beforeunload dialog event never arrives and the command times out.
        await call(ws, 900, "Page.enable")

        if cmd == "nav":
            await call(ws, 2, "Page.navigate", {"url": arg})
            await asyncio.sleep(3.0)
            final = await settled_href(ws)
            if ports:
                store.write_json(store.session_dir(root, session) / "last_nav.json",
                                {"url": arg, "final_url": final, "ts": time.time()})
            print(final)

        elif cmd == "tclick":
            label = await tclick(ws, a.arg)
            if label is None:
                print("NOT FOUND")
                return 1
            print(f"tclicked: {label}")
            await asyncio.sleep(1.0)

        elif cmd == "key":
            await press(ws, a.arg)
            print(f"key {a.arg}")

        elif cmd == "wait":
            ok = await wait_for(ws, a.selector, a.gone, a.timeout)
            print(f"{'gone' if a.gone else 'present'}: {a.selector}" if ok else f"timeout: {a.selector}")
            return 0 if ok else 1

        elif cmd == "save":
            return await cmd_save(ws, a, root, session)

        elif cmd == "assets":
            return await cmd_assets(ws, root, session)

        elif cmd == "shot":
            res = await call(ws, 1, "Page.captureScreenshot", {"format": "png"})
            path = arg or "/tmp/page.png"
            open(path, "wb").write(base64.b64decode(res["data"]))
            print(path)

        elif cmd == "eval":
            print(json.dumps(await evaluate(ws, 1, arg), indent=2, ensure_ascii=False)[:6000])

        elif cmd == "click":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "if(!e)return 'NOT FOUND';e.scrollIntoView({block:'center'});"
                  "e.click();return 'clicked: '+(e.innerText||e.getAttribute('href')||e.tagName);})()")
            print(await evaluate(ws, 1, js))
            await asyncio.sleep(2.5)


        elif cmd == "type":
            sel = rest[1] if len(rest) > 1 else None
            if sel:
                await evaluate(ws, 1, f"(()=>{{const e=document.querySelector({json.dumps(sel)});"
                                      "if(e){e.focus();return 'focused';}return 'NOT FOUND';})()")
            mid = 10
            for ch in arg:
                # REAL key events: Angular's composer ignores a synthetic .value assignment.
                for typ in ("keyDown", "char", "keyUp"):
                    mid += 1
                    p = {"type": typ, "text": ch, "key": ch}
                    if typ != "char":
                        p = {"type": typ, "key": ch, "text": ch,
                             "unmodifiedText": ch}
                    await call(ws, mid, "Input.dispatchKeyEvent", p)
                await asyncio.sleep(0.12)
            print(f"typed {len(arg)} chars")

        elif cmd == "focus":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "if(!e)return 'NOT FOUND';e.focus();e.click();return 'focused '+e.tagName;})()")
            print(await evaluate(ws, 1, js))


        elif cmd == "insert":
            sel = rest[1] if len(rest) > 1 else "textarea.message-input"
            print(await evaluate(ws, 1,
                f"(()=>{{const e=document.querySelector({json.dumps(sel)});"
                "if(!e)return 'NOT FOUND';e.focus();e.click();return 'focused';})()"))
            # Input.insertText goes through the real editing pipeline so ngModel fires; dispatchKeyEvent alone left the textarea empty.
            mid = 20
            for ch in arg:
                mid += 1
                await call(ws, mid, "Input.insertText", {"text": ch})
                await asyncio.sleep(0.15)
            print("value now:", await evaluate(ws, 99,
                f"document.querySelector({json.dumps(sel)}).value"))

        elif cmd == "links":
            js = """(()=>{const seen=new Set();const out=[];
              document.querySelectorAll('a,button,[role="button"],[role="tab"]').forEach(e=>{
                const r=e.getBoundingClientRect(); if(r.width<2||r.height<2) return;
                const t=(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,50);
                const h=e.getAttribute('href')||'';
                const k=t+'|'+h; if(!t&&!h) return; if(seen.has(k))return; seen.add(k);
                out.push({t,h,tag:e.tagName.toLowerCase()});});
              return out;})()"""
            for it in (await evaluate(ws, 1, js)) or []:
                print(f"  {it['tag']:7s} {it['t'][:45]:45s} {it['h'][:60]}")

        elif cmd == "text":
            js = (f"(()=>{{const e=document.querySelector({json.dumps(arg)});"
                  "return e?e.innerText.slice(0,4000):'NOT FOUND';})()")
            print(await evaluate(ws, 1, js))

        elif cmd == "probe":
            js = (f"[...document.querySelectorAll({json.dumps(arg)})].slice(0,15).map(e=>({{"
                  "v:e.getClientRects().length>0,tag:e.tagName.toLowerCase(),"
                  "c:(typeof e.className==='string'?e.className:'').slice(0,70),"
                  "t:(e.innerText||e.getAttribute('aria-label')||'').trim().replace(/\\s+/g,' ').slice(0,40)}))")
            for i, it in enumerate((await evaluate(ws, 1, js)) or []):
                print(f"  {i:2d} {'V' if it['v'] else '-'} {it['tag']:10s} {it['c']:70s} {it['t']}")

        else:
            print(f"unknown command {cmd!r}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
