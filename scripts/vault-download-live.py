#!/usr/bin/env python3
"""Vault Pro download, live: the real app (Next + relay containers), the real account, the real CDN, Chromium.

    ./venv/bin/python scripts/vault-download-live.py                         # select + folder modes
    ./venv/bin/python scripts/vault-download-live.py --modes vault           # whole vault (free-space guard first)
    ./venv/bin/python scripts/vault-download-live.py --modes select,folder,vault --folder 29254086 --headed

Per mode it drives Vault Pro like a user (select: Select, tick 3 photos + 1 video, Download selected; folder: the
rail row's ... > Download folder; vault: the header's Download full vault, `vault-header-download`), waits for the progress card to settle,
then checks every file on disk against the vault: count, size == bytes served (Content-Length / Content-Range total
of the response that delivered it), `file` + ffprobe valid. Direct vs relay per file: the browser's network log
(Playwright: a 200 from *.onlyfans.com = direct, a 200 from /admin/vault-ai/download = relay) cross-checked with the
relay's own `vault_download account=… media=…` log lines (docker logs). Whole vault: BEFORE downloading, every
media's size is read with a paced `Range: bytes=0-0` GET (Content-Range total) and the run aborts, printing count and
size, if saving would leave < --min-free-gb on the target disk.

Evidence: slop/evidence/<UTC>-vault-download-live-<sha>/ (gitignored): <mode>-trigger.png / <mode>-settled.png,
<mode>-network.json, <mode>-relay-log.txt, <mode>-files.json, report.json; the files under --target/<sha>/<mode>/.

Read-only toward OnlyFans: GETs only (the app's listing reads through the relay, the CDN file GETs, Range-0 GETs).
The one POST is our own sign-in (POST /auth/login on the relay). Owner credentials: .owner-login (line 1 username,
line 2 password; never printed). Declared bypass: the native folder picker cannot be clicked by Playwright, so
`showDirectoryPicker` is replaced in this page by Chromium's own origin-private file system root
(`navigator.storage.getDirectory()`, a real FileSystemDirectoryHandle: the app's createWritable / pipeTo path runs
unchanged); each saved file is then streamed from it to a loopback PUT sink in this script and dropped from OPFS. The
profile is on disk under --target (an incognito context keeps OPFS in memory), so the whole-vault guard budgets 2x the
vault (OPFS copy + exported copy). An item the UI lists as failed with a reason is accounted for, never dropped.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PANEL = "[aria-label='Vault download']"
CDN_SUFFIXES = (".onlyfans.com",)
_LOG = re.compile(r"vault_download account=(\S+) media=(\d+) status=(\S+) bytes=(\d+) resigned=(\S+)")
_RESIGN = re.compile(r"cdn_resign account=(\S+) media=(\d+) (\S+)")
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")
# Declared bypass (docstring): the picker -> the OPFS root's subfolder `__vdPickRoot`.
PICKER_JS = """window.showDirectoryPicker = async () => {
  const root = await navigator.storage.getDirectory();
  return root.getDirectoryHandle(window.__vdPickRoot || "root", { create: true });
};"""
# Every file under OPFS/<phase>/ as [relative path, size].
LIST_JS = """async (phase) => {
  const out = [];
  const walk = async (d, pre) => { for await (const [n, h] of d.entries()) {
    if (h.kind === "directory") await walk(h, pre + n + "/"); else out.push([pre + n, (await h.getFile()).size]); } };
  const root = await navigator.storage.getDirectory();
  await walk(await root.getDirectoryHandle(phase), "");
  return out; }"""
# Export one OPFS file to the script's loopback sink (streams the File as a PUT body), then drop it from OPFS
# (peak disk ~1x vault + one file while exporting).
EXPORT_JS = """async ([phase, rel, sink]) => {
  let d = await (await navigator.storage.getDirectory()).getDirectoryHandle(phase);
  const parts = rel.split("/"); const name = parts.pop();
  for (const p of parts) d = await d.getDirectoryHandle(p);
  const f = await (await d.getFileHandle(name)).getFile();
  const r = await fetch(sink + "/" + rel.split("/").map(encodeURIComponent).join("/"), { method: "PUT", body: f });
  if (!r.ok) throw new Error("sink " + r.status);
  await d.removeEntry(name);
  return f.size; }"""
CLEAR_JS = """async (phase) => { const r = await navigator.storage.getDirectory();
  try { await r.removeEntry(phase, { recursive: true }); } catch (e) {} }"""


async def wake(page) -> None:
    """Dismiss the app's inactivity modal ("has gone idle"); a long unattended run raises it and it blocks clicks."""
    b = page.get_by_role("button", name="Return to Inflowwww")
    if await b.count() and await b.first.is_visible():
        await b.first.click()


def git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short=9", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip() or "nosha"


def safe(s: str) -> str:
    """vaultDownloadReducer.safeName."""
    t = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", s)
    t = re.sub(r"^[\s.]+|[\s.]+$", "", t)[:80]
    return t or "_"


def full_url(m: dict) -> str | None:
    u = ((m.get("files") or {}).get("full") or {}).get("url")
    return u if isinstance(u, str) and u.startswith("http") else None


def total_of(headers: dict) -> int | None:
    """Bytes the response carried in full: Content-Range's total, else Content-Length."""
    cr = headers.get("content-range") or ""
    m = re.search(r"/(\d+)$", cr)
    if m:
        return int(m.group(1))
    cl = headers.get("content-length")
    return int(cl) if cl and cl.isdigit() else None


def probe(p: Path) -> dict:
    out = {"file": subprocess.run(["file", "-b", "--mime-type", str(p)], capture_output=True, text=True).stdout.strip()}
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
                            "-of", "json", str(p)], capture_output=True, text=True, timeout=120)
        streams = (json.loads(r.stdout or "{}").get("streams") or []) if r.returncode == 0 else []
        out["ffprobe"] = {"ok": r.returncode == 0 and bool(streams), "streams": streams[:2], "err": r.stderr[-300:]}
    else:
        out["ffprobe"] = {"ok": None, "err": "ffprobe not installed"}
    out["ok"] = out["file"].startswith(("image/", "video/", "audio/")) and out["ffprobe"]["ok"] is not False
    return out


class Sink:
    """Loopback PUT sink: the page streams each OPFS file here; written under .dest (path checked)."""

    def __init__(self):
        sink = self
        self.dest: Path | None = None

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "PUT")
                self.send_header("Access-Control-Allow-Headers", "content-type")

            def do_OPTIONS(self):
                self.send_response(204); self._cors(); self.end_headers()

            def do_PUT(self):
                rel = unquote(urlsplit(self.path).path).lstrip("/")
                p = (sink.dest / rel).resolve()
                if sink.dest is None or not p.is_relative_to(sink.dest.resolve()):
                    self.send_response(400); self._cors(); self.end_headers(); return
                p.parent.mkdir(parents=True, exist_ok=True)
                left = int(self.headers.get("content-length") or 0)
                with open(p, "wb") as fh:
                    while left:
                        b = self.rfile.read(min(left, 1 << 20))
                        if not b:
                            break
                        fh.write(b); left -= len(b)
                self.send_response(200 if not left else 500); self._cors(); self.end_headers()

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


class Api:
    """Our relay, through the app's origin (the same proxy the UI uses), signed in as the owner."""

    def __init__(self, app: str, account: str, pace: float):
        self.c = httpx.AsyncClient(base_url=app, timeout=60)
        self.account, self.pace = account, pace

    async def login(self, login_file: Path) -> None:
        user, pw = login_file.read_text().splitlines()[:2]
        r = await self.c.post("/auth/login", json={"username": user.strip(), "password": pw.strip()})
        if r.status_code != 200 or "two" in r.text.lower() and "challenge" in r.text.lower():
            sys.exit(f"sign-in failed: HTTP {r.status_code} (2FA accounts are not supported here)")

    async def get(self, path: str, **params) -> dict:
        r = await self.c.get(path, params=params, headers={"X-Account-Id": self.account})
        r.raise_for_status()
        return r.json()

    async def listing(self, mirror: bool, folder: str | None = None, limit: int | None = None) -> list[dict]:
        """The media the UI's download lists: the mirror when collected, else live OF (paced)."""
        out: list[dict] = []
        off = 0
        while True:
            if mirror:
                p = {"account_id": self.account, "limit": 500, "offset": off, **({"of_folder_id": folder} if folder else {})}
                r = await self.get("/admin/vault-ai/items", **p)
            else:
                p = {"limit": 100, "offset": off, **({"list_id": folder} if folder else {})}
                r = await self.get("/api/of/v2/vault/media", **p)
            page = r.get("list") or []
            out += page
            if limit and len(out) >= limit or not r.get("hasMore") or not page:
                return out[:limit] if limit else out
            off += len(page)
            if not mirror:
                await asyncio.sleep(self.pace)


async def precount(api: Api, media: list[dict], pace: float) -> dict:
    """Every media's size by a paced Range: bytes=0-0 GET of its full url (re-signed once through the relay on a
    non-206); unknown ones are counted at the largest size seen (conservative)."""
    sizes, unknown = {}, []
    async with httpx.AsyncClient(timeout=30) as cdn:
        for i, m in enumerate(media):
            u = full_url(m)
            got = None
            for attempt in (0, 1):
                if not u:
                    break
                try:
                    r = await cdn.get(u, headers={"Range": "bytes=0-0"})
                    if r.status_code in (200, 206):
                        got = total_of({k.lower(): v for k, v in r.headers.items()})
                        break
                except httpx.HTTPError:
                    pass
                if attempt == 0:
                    try:
                        u = (await api.get("/admin/vault-ai/download/resign", account_id=api.account,
                                           media_id=m["id"], u=u)).get("url")
                    except httpx.HTTPError:
                        u = None
            if got is None:
                unknown.append(m["id"])
            else:
                sizes[m["id"]] = got
            if (i + 1) % 50 == 0:
                print(f"  precount {i + 1}/{len(media)}", flush=True)
            await asyncio.sleep(pace)
    biggest = max(sizes.values(), default=0)
    return {"count": len(media), "known": len(sizes), "unknown": unknown,
            "bytes": sum(sizes.values()) + biggest * len(unknown)}


def relay_lines(since: str) -> str:
    r = subprocess.run(["docker", "logs", "--since", since, "openinflowwww-relay"], capture_output=True, text=True)
    return "\n".join(ln for ln in (r.stdout + r.stderr).splitlines() if "vault_download " in ln or "cdn_resign " in ln)


async def run_mode(args, api, sink, page, mode: str, ev: Path, target: Path, creator: str, mirror: bool) -> dict:
    out: dict = {"mode": mode}
    # What the UI will save, from the same source it reads.
    if mode == "select":
        first = await api.listing(mirror, limit=40)
        photos = [m for m in first if m.get("type") == "photo" and full_url(m)][:3]
        videos = [m for m in first if m.get("type") == "video" and full_url(m)][:1]
        want, folder_name = photos + videos, None
        if len(photos) < 3 or not videos:
            return {**out, "ok": False, "error": "the first page has fewer than 3 photos + 1 video with a full file"}
    elif mode == "folder":
        lists = (await api.get("/api/of/v2/vault/lists", view="main", limit=50, offset=0)).get("list") or []
        custom = [f for f in lists if f.get("type") == "custom"]
        f = next((x for x in custom if str(x["id"]) == str(args.folder) or x.get("name") == args.folder), None) \
            if args.folder else next((x for x in custom if (x.get("photosCount") or 0) + (x.get("videosCount") or 0) > 0), None)
        if not f:
            return {**out, "ok": False, "error": f"no folder {args.folder or '(non-empty custom)'}"}
        want, folder_name = await api.listing(mirror, folder=str(f["id"])), f["name"]
        out["folder"] = {"id": f["id"], "name": f["name"]}
    else:
        want, folder_name = await api.listing(mirror), None
        target.mkdir(parents=True, exist_ok=True)
        pc = await precount(api, want, args.pace_cdn)
        free = shutil.disk_usage(target).free
        quota = await page.evaluate("navigator.storage.estimate().then(e => e.quota - e.usage)")
        # The OPFS stub holds every file (browser profile, same disk) until it is exported: budget 2x.
        need = 2 * pc["bytes"]
        out["precount"] = {**pc, "free_bytes": free, "budget_bytes": need, "opfs_quota_free": quota}
        left = free - need
        print(f"whole vault: {pc['count']} items, {pc['bytes'] / 1e9:.2f} GB ({len(pc['unknown'])} sizes unknown, "
              f"counted at the largest), x2 for the OPFS stub, free {free / 1e9:.1f} GB -> {left / 1e9:.1f} GB left, "
              f"OPFS quota free {quota / 1e9:.1f} GB", flush=True)
        if left < args.min_free_gb * 1e9:
            return {**out, "ok": False, "aborted": f"would leave {left / 1e9:.1f} GB < {args.min_free_gb} GB free"}
        if quota < pc["bytes"]:
            return {**out, "ok": False, "aborted": f"OPFS quota {quota / 1e9:.1f} GB < {pc['bytes'] / 1e9:.1f} GB"}
    ids = {m["id"] for m in want}
    out["want"] = len(ids)

    # Drive it.
    net: list[dict] = []

    def on_resp(r) -> None:
        u = urlsplit(r.url)
        host = (u.hostname or "").lower()
        if host.endswith(CDN_SUFFIXES) or u.path.startswith("/admin/vault-ai/download"):
            q = parse_qs(u.query)
            net.append({"t": time.time(), "url": r.url.split("?")[0], "host": host, "path": u.path,
                        "media_id": (q.get("media_id") or [None])[0], "status": r.status,
                        "type": r.request.resource_type, "headers": {k: v for k, v in r.headers.items()
                        if k in ("content-length", "content-range", "content-type", "content-disposition")}})

    page.on("response", on_resp)
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await page.evaluate(CLEAR_JS, mode)
    await page.evaluate(f"window.__vdPickRoot = {json.dumps(mode)}")
    try:
        await wake(page)
        if mode == "select":
            await page.get_by_role("button", name="Select", exact=True).click(timeout=10_000)
            for m in want:
                t = page.locator(f"section [title^='#{m['id']} ']").first
                await t.scroll_into_view_if_needed(timeout=20_000)
                await t.click(timeout=10_000)
            await page.screenshot(path=str(ev / f"{mode}-trigger.png"))
            await page.get_by_role("button", name="Download selected").click(timeout=10_000)
        elif mode == "folder":
            row = page.locator("aside [role='button']").filter(has_text=folder_name).first
            await row.scroll_into_view_if_needed(timeout=10_000)
            await row.get_by_role("button", name="More").click(timeout=10_000)
            await page.screenshot(path=str(ev / f"{mode}-trigger.png"))
            await page.get_by_role("menuitem", name="Download folder").click(timeout=10_000)
        else:
            await page.screenshot(path=str(ev / f"{mode}-trigger.png"))
            await page.get_by_test_id("vault-header-download").click(timeout=10_000)
        panel = page.locator(PANEL)
        await panel.wait_for(timeout=30_000)
        t0 = time.time()
        while time.time() - t0 < args.settle_s:
            if await panel.get_attribute("data-phase") in ("done", "cancelled"):
                break
            await asyncio.sleep(1)
        out["panel"] = {k: await panel.get_attribute(f"data-{k}") for k in ("phase", "total", "done", "failed", "direct", "relay")}
        out["seconds"] = round(time.time() - t0, 1)
        out["failed_ui"] = await page.locator("[aria-label='Failed items'] li").evaluate_all(
            "els => els.map(e => [...e.querySelectorAll('span')].map(s => s.title || s.textContent))")
        await page.screenshot(path=str(ev / f"{mode}-settled.png"))
    finally:
        page.remove_listener("response", on_resp)

    # Files out of OPFS onto disk.
    dest = target / mode
    shutil.rmtree(dest, ignore_errors=True)
    files = await page.evaluate(LIST_JS, mode)
    dest.mkdir(parents=True, exist_ok=True)
    sink.dest = dest
    for rel, _size in files:
        await page.evaluate(EXPORT_JS, [mode, rel, sink.url])
    await page.evaluate(CLEAR_JS, mode)

    # Verify.
    logs = relay_lines(since)
    (ev / f"{mode}-relay-log.txt").write_text(logs + "\n")
    (ev / f"{mode}-network.json").write_text(json.dumps(net, indent=1))
    relay_ok = {int(m.group(2)): int(m.group(4)) for m in _LOG.finditer(logs)
                if m.group(1) == api.account and m.group(3) == "ok"}
    by_media: dict[int, dict] = {}
    names = {}
    for m in want:
        u = full_url(m)
        names[m["id"]] = urlsplit(u).path if u else None
    for n in net:
        if n["status"] not in (200, 206):
            continue
        if n["media_id"]:
            by_media.setdefault(int(n["media_id"]), {"relay": n})
        else:
            for mid, pth in names.items():
                if pth and n["path"] == pth:
                    by_media.setdefault(mid, {})["direct"] = n
    rows, problems = [], []
    lists_names = {}
    for m in want:
        ls = [x for x in (m.get("listStates") or []) if x.get("type") == "custom" and x.get("hasMedia") is not False and x.get("name")]
        lists_names[m["id"]] = safe(folder_name) if folder_name else safe(ls[0]["name"] if ls else "Unfiled")
    on_disk = {str(p.relative_to(dest)): p for p in dest.rglob("*")
               if p.is_file() and not p.name.startswith(".")}  # not Finder's .DS_Store if dest.exists() else {}
    for m in want:
        mid = m["id"]
        hit = next((rel for rel in on_disk if rel.split("/")[-1].split(".")[0] == str(mid)), None)
        src = by_media.get(mid, {})
        source = "direct" if "direct" in src else "relay" if "relay" in src else None
        served = total_of(src[source]["headers"]) if source else None
        row = {"media_id": mid, "type": m.get("type"), "path": hit, "source": source, "served_bytes": served,
               "relay_log_bytes": relay_ok.get(mid)}
        if hit:
            p = on_disk[hit]
            row["size"] = p.stat().st_size
            row["path_ok"] = hit.split("/")[:2] == [creator, lists_names[mid]]
            row.update(probe(p))
            row["size_ok"] = served is not None and row["size"] == served
            row["source_ok"] = (source == "direct" and mid not in relay_ok) or (source == "relay" and relay_ok.get(mid) == row["size"])
            if not (row["path_ok"] and row["size_ok"] and row["ok"] and row["source_ok"]):
                problems.append(mid)
        else:
            problems.append(mid)
        rows.append(row)
    stray = sorted(set(on_disk) - {r["path"] for r in rows if r["path"]})
    (ev / f"{mode}-files.json").write_text(json.dumps(rows, indent=1))
    out.update(saved=len(on_disk), stray=stray, problems=problems,
               direct=sum(1 for r in rows if r["source"] == "direct"), relay=sum(1 for r in rows if r["source"] == "relay"),
               resigns=len([1 for m in _RESIGN.finditer(logs) if m.group(1) == api.account]))
    failed_ids = {int(re.sub(r"\D.*", "", f[0].split("/")[-1]) or 0) for f in out["failed_ui"] if f and len(f) > 1 and f[1]}
    out["failed_with_reason"] = sorted(failed_ids & ids)
    unexplained = [mid for mid in problems if mid not in failed_ids or any(r["media_id"] == mid and r["path"] for r in rows)]
    out["unexplained"] = unexplained
    out["ok"] = (out["panel"].get("phase") == "done" and len(on_disk) + len(out["failed_with_reason"]) == len(ids)
                 and int(out["panel"].get("failed") or 0) == len(out["failed_with_reason"]) and not unexplained and not stray)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--app", default="http://127.0.0.1:3001")
    ap.add_argument("--account", required=True, help="the connected Creator account id to test")
    ap.add_argument("--modes", default="select,folder", help="comma list of select, folder, vault")
    ap.add_argument("--folder", help="folder id or name for the folder mode (default: first non-empty custom folder)")
    ap.add_argument("--target", default="/tmp/vault-download-live", help="where the saved files land (<target>/<sha>/<mode>/)")
    ap.add_argument("--login-file", default=str(ROOT / ".owner-login"))
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--pace-cdn", type=float, default=0.25, help="seconds between precount Range-0 GETs")
    ap.add_argument("--pace", type=float, default=1.5, help="seconds between live OF listing pages")
    ap.add_argument("--settle-s", type=float, default=3600)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if not set(modes) <= {"select", "folder", "vault"}:
        sys.exit(f"unknown mode in {modes}")

    sha = git_sha()
    ev = ROOT / "slop" / "evidence" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-vault-download-live-{sha}"
    ev.mkdir(parents=True, exist_ok=True)
    target = Path(args.target) / sha
    api = Api(args.app, args.account, args.pace)
    sink = Sink()
    await api.login(Path(args.login_file))
    accts = await api.c.get("/admin/accounts")
    rows = accts.json().get("accounts", []) if accts.status_code == 200 else []
    acc = next((a for a in rows if str(a.get("id")) == args.account), None)
    if acc is None:
        sys.exit(f"the owner cannot see account {args.account} (GET /admin/accounts): link it to this owner first")
    creator = safe(acc.get("nickname") or acc.get("name") or args.account)
    summ = await api.get("/admin/vault-ai/cache/summary", account_id=args.account)
    mirror = (summ.get("count") or 0) > 0
    info = await api.get("/admin/vault-ai/download/info", account_id=args.account)
    report = {"sha": sha, "account": args.account, "creator": creator, "source": "mirror" if mirror else "live",
              "direct_allowed": info.get("direct"), "modes": {}}
    print(f"evidence {ev}\naccount {args.account} ({creator}), listing from {report['source']}, "
          f"direct allowed: {info.get('direct')}", flush=True)

    host = urlsplit(args.app).hostname
    async with async_playwright() as pw:
        # On-disk profile under the target: OPFS of an incognito context lives in memory.
        prof = target / ".chromium-profile"
        shutil.rmtree(prof, ignore_errors=True)
        bctx = await pw.chromium.launch_persistent_context(str(prof), headless=not args.headed,
                                                           viewport={"width": 1440, "height": 900})
        await bctx.add_cookies([{"name": c.name, "value": c.value, "domain": host, "path": "/"} for c in api.c.cookies.jar])
        await bctx.add_init_script(TOURS_SEEN + f"localStorage.setItem('vault.accountId', '{args.account}');" + PICKER_JS)
        page = bctx.pages[0] if bctx.pages else await bctx.new_page()
        await page.goto(f"{args.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=120_000)
        await page.locator("section [title^='#']").first.wait_for(timeout=120_000)
        for mode in modes:
            print(f"== {mode}", flush=True)
            try:
                r = await run_mode(args, api, sink, page, mode, ev, target, creator, mirror)
            except Exception as e:  # noqa: BLE001 — reported, the next mode still runs
                r = {"mode": mode, "ok": False, "error": f"{type(e).__name__}: {e}"[:800]}
                await page.screenshot(path=str(ev / f"{mode}-failed.png"))
            report["modes"][mode] = r
            print(json.dumps({k: v for k, v in r.items() if k not in ("problems",)} | {"problems": r.get("problems", [])[:10]},
                             indent=1), flush=True)
            await wake(page)
            if await page.locator("[aria-label='Close download']").count():
                await page.locator("[aria-label='Close download']").click()
            if mode == "select" and await page.get_by_role("button", name="Clear").count():
                await page.get_by_role("button", name="Clear").click()
                await page.get_by_role("button", name="Selecting", exact=True).click()
        await bctx.close()
        shutil.rmtree(prof, ignore_errors=True)
    report["ok"] = all(r.get("ok") for r in report["modes"].values())
    (ev / "report.json").write_text(json.dumps(report, indent=1))
    print(f"{'PASS' if report['ok'] else 'FAIL'}  evidence {ev}", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
