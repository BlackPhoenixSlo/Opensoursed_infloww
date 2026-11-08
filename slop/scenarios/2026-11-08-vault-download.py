"""Vault Pro's download (selection, a folder, the whole vault) into a folder the user picks, as
<creator>/<folder>/<mediaId>.<ext>: direct from OF's CDN when the Creator has no proxy, else through the relay
(`GET /admin/vault-ai/download`, app/components/vault/vaultDownload.ts, docs/spec/vault-download.md).

World: `flat_agency`, 2 Creators, real OFClient sessions against lib/of_wire.py (`OF_WIRE`) + lib/vault_wire.py
(vault_download_items media each, 6 folders; `ip_bound`: every url signed for the egress that listed it, OF's
`AWS:SourceIp`; `full_mp4`: a video's full file is its source mp4), the mirror seeded by SQL as a finished collector
run leaves it (seed/vault_week.py). Creator A has no proxy: its mirror urls are signed for "direct" (this machine,
the browser's egress too). Creator B is on a proxy (lib/proxy_wire.py, the product's POST /admin/proxies + assign):
its urls are signed for the proxy. OF's CDN is lib/img_relay.py's fake (exact seeded bytes per key, Policy expiry +
SourceIp checked, one-spec Range).

Stage relay-load (also --no-ui): `--users` concurrent GET /admin/vault-ai/download for every one of B's media
(through its proxy).                                                                            RELAY_LOAD.
UI (one owner, Chromium 1440x900, Vault Pro on A, the folder picker stubbed, files on disk under the run's tmp):
  select   Select, tick the 3 newest photos + the newest video, Download selected (`vault-download-select-trigger`,
           `-settled`).                                                                        SELECT.
  folder   the rail's first folder: its row menu > Download folder (`vault-download-folder-trigger`, `-settled`).
                                                                                               FOLDER.
  vault    STALE of A's mirror urls re-signed for a proxy A left (OLD_EGRESS), then the toolbar's Download whole vault
           (`vault-download-vault-trigger`, `-settled`): every media once; the stale ones 403 direct, are re-signed
           by id (one by-id OF read each) and fetched direct again.                            VAULT.
  proxied  a fresh browser on B: Download selected of 3 photos + 1 video (`vault-download-proxied-trigger`,
           `-settled`): 0 browser CDN fetches, all relay.                                      PROXIED.
Each check reads the files on disk: the path (creator = the Creator's nickname, folder = the downloaded folder, else
the media's first custom OF folder, else Unfiled), a .jpg's bytes equal the CDN's seeded bytes (img_relay.asset_bytes),
an .mp4's size equals what the fake served for that key and it starts with an ftyp box; no stray file; the panel's
data-done/-failed/-direct/-relay; the relay's own `vault_download account=… status=ok` log lines (0 for direct items);
the browser's CDN fetches (the harness route). p95 of the relay download vs the last green run.

Bypasses (declared):
- OF at its wire (lib/of_wire.py + lib/vault_wire.py); the mirror seeded by SQL; OF's earlier-proxy listing (stale IP)
  written as mirror url rewrites (seed/vault_week.set_urls).
- OF's CDN is lib/img_relay.py's fake in the relay process. The BROWSER's CDN requests (https://cdn2.onlyfans.com/…)
  are taken at the browser's network boundary by a Playwright route and answered by that same fake (same bytes,
  Policy / SourceIp check, Range), egress "direct" (the browser is on this machine, as an unproxied account's relay
  is), with S3's CORS: `Access-Control-Allow-Origin: *` on 200/206, none on 403/404 (measured on the real CDN
  2026-11-08: a denied fetch rejects with TypeError). Playwright buffers each body (route.fulfill), so the
  browser side is not streamed byte by byte as from the real CDN.
- The native folder picker (`showDirectoryPicker`) is stubbed by an init script in this test only: a directory
  handle whose `createWritable()` is a real WritableStream; each chunk crosses a Playwright binding (base64) and is
  written under the run's tmp as `<file>.crswap`, renamed on close, deleted on abort (Chromium's own swap-file rule).
  The stub refuses separators and "."/".." in names, as the real API does.
- One ffmpeg testsrc clip for every mp4 (img_relay.video_bytes); videos are never DRM here (unit-tested instead:
  service/tests/test_vault_download.py).
Break-it-once: vault-download-direct-ignores-proxy (client: `sourceFor` drops the proxy rule) turns only PROXIED red.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from slop.lib.img_relay import EGRESS, ORIG_HOST, arm_run, asset_bytes
from slop.lib.proxy_wire import ProxyWire
from slop.lib.vault_download_faults import FOLDER, PROXIED, RELAY_LOAD, SELECT, VAULT
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.seed import vault_week

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = "vault-download-direct-ignores-proxy"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
P95_VS_LAST = (1.5, 200)
P95_VS_LAST_MIN_N = 20
CDN_LATENCY_S = 0.02
VIEWPORT = (1440, 900)
WAIT_MS = 120_000
SETTLE_S = 180
STALE = 3
OLD_EGRESS = "127.0.0.1:1"
DOWNLOAD = "/admin/vault-ai/download"
LISTS_PATH = "/api/of/v2/vault/lists"
MEDIA_PATH = "/api/of/v2/vault/media"
PANEL = "[aria-label='Vault download']"
TOURS_SEEN = ("localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', "
              "uploadPageStep: '1', batchEdit: '1', uploadBtn: '1'}));")
_LOG = re.compile(r"vault_download account=(\S+) media=(\d+) status=(\S+) bytes=(\d+)")

# The native folder picker, in this test only (declared above).
PICKER_JS = r"""(() => {
  const call = (...a) => window.__slopFs(...a);
  const b64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000)
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
  const check = (n) => { if (!n || n === "." || n === ".." || /[\/\\]/.test(n)) throw new TypeError("Name is not allowed."); };
  const file = (p, name) => ({ kind: "file", name, async createWritable() {
    const id = await call("open", p);
    return new WritableStream({
      async write(c) { await call("write", id, b64(c instanceof Uint8Array ? c : new Uint8Array(c))); },
      async close() { await call("close", id); },
      async abort() { await call("abort", id); },
    });
  } });
  const dir = (p, name) => ({ kind: "directory", name,
    async getDirectoryHandle(n) { check(n); await call("mkdir", p + "/" + n); return dir(p + "/" + n, n); },
    async getFileHandle(n) { check(n); return file(p + "/" + n, n); } });
  window.showDirectoryPicker = async () => { const r = window.__slopPickRoot || "root"; await call("mkdir", r); return dir(r, r); };
})();"""


def _safe(s: str) -> str:
    """vaultDownloadReducer.safeName."""
    t = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", s)
    t = re.sub(r"^[\s.]+|[\s.]+$", "", t)[:80]
    return t or "_"


class Disk:
    """The picker stub's far side: paths under `base`, Chromium's swap-file rule."""

    def __init__(self, base: Path):
        self.base = base.resolve()
        self.open: dict[int, tuple[Path, object]] = {}
        self.n = 0

    def _p(self, rel: str) -> Path:
        p = (self.base / rel).resolve()
        if self.base not in p.parents and p != self.base:
            raise ValueError(f"outside the root: {rel}")
        return p

    async def binding(self, _source, op: str, *a):
        if op == "mkdir":
            self._p(a[0]).mkdir(parents=True, exist_ok=True)
            return None
        if op == "open":
            p = self._p(a[0])
            self.n += 1
            self.open[self.n] = (p, open(p.with_name(p.name + ".crswap"), "wb"))
            return self.n
        p, fh = self.open[a[0]]
        if op == "write":
            fh.write(base64.b64decode(a[1]))
        elif op == "close":
            fh.close()
            p.with_name(p.name + ".crswap").replace(p)
            del self.open[a[0]]
        elif op == "abort":
            fh.close()
            p.with_name(p.name + ".crswap").unlink(missing_ok=True)
            del self.open[a[0]]
        return None


def _key(aid: str, m: dict) -> str:
    return f"{HOST}{cdn_path(aid, m['id'], 'src' if m['type'] == 'video' else 'full')}"


def _expected(vw, aid: str, creator: str, ms: list[dict], folder: str | None) -> dict[str, dict]:
    """{"creator/folder/id.ext": {mid, key, size (jpg) or None (mp4)}}."""
    names = {f["id"]: f["name"] for f in vw.vault(aid)["folders"]}
    out = {}
    for m in ms:
        f = folder if folder is not None else (names[m["folders"][0]] if m["folders"] else "Unfiled")
        ext = "mp4" if m["type"] == "video" else "jpg"
        out[f"{creator}/{_safe(f)}/{m['id']}.{ext}"] = {"mid": m["id"], "key": _key(aid, m),
                                                       "size": None if ext == "mp4" else m["sizes"][1]}
    return out


def _verify(root: Path, want: dict[str, dict], served: dict[str, int]) -> dict:
    """Files under `root` vs `want`: missing, stray, bad bytes."""
    got = {str(p.relative_to(root)): p for p in root.rglob("*") if p.is_file()}
    bad = []
    for rel, e in want.items():
        p = got.get(rel)
        if p is None:
            continue
        b = p.read_bytes()
        if e["size"] is not None:
            if b != asset_bytes(e["key"], e["size"]):
                bad.append([rel, len(b), e["size"]])
        elif b[4:8] != b"ftyp" or len(b) != served.get(e["key"], -1):
            bad.append([rel, len(b), served.get(e["key"])])
    return {"want": len(want), "got": len(got), "missing": sorted(set(want) - set(got))[:20],
            "stray": sorted(set(got) - set(want))[:20], "bad_bytes": bad[:20],
            "bytes": sum(p.stat().st_size for p in got.values())}


async def run(ctx):
    w, fake = ctx.world, ctx.of_wire
    n_items = int(ctx.param("items", w.size["vault_download_items"]))
    vw = VaultWire(fake, seed=ctx.seed, items=n_items, ip_bound=True, full_mp4=True)
    w.data["flat_creators"] = 2
    await ctx.build(PROFILE)
    a, b = (c["id"] for c in w.data["creators"][:2])
    nick = {c["id"]: c["nickname"] for c in w.data["creators"]}
    vault_week.mirror(w, vw, [a, b])
    armed = await arm_run(ctx.owner, ctx.stack.tmp, vw.assets([a, b]), CDN_LATENCY_S)
    owner = ctx.owner

    async def cdn_since(n: int) -> list[dict]:
        return (await owner.get(f"/__slop/img/calls?since={n}")).json()["calls"]

    async def cdn_n() -> int:
        return (await owner.get("/__slop/img/stats")).json()["n"]

    proxy = ProxyWire().__enter__()
    try:
        await owner.post("/admin/proxies", json={"label": "slop-dl", "scheme": "socks5", "host": "127.0.0.1",
                                                 "port": proxy.port, "notes": "slop: vault-download"})
        await asyncio.sleep(1.0)
        bind = (await owner.post("/admin/proxies/assign", json={"label": "slop-dl", "account_id": b})).status_code
        await asyncio.sleep(1.0)
        peg = f"127.0.0.1:{proxy.port}"
        vault_week.set_urls(w, vw, a, [m["id"] for m in vw.vault(a)["media"]], egress="direct")
        vault_week.set_urls(w, vw, b, [m["id"] for m in vw.vault(b)["media"]], egress=peg)
        ctx.note(f"A={a} (direct), B={b} on proxy {peg} (assign {bind}), {n_items} media each, cdn port {armed['port']}")

        # ── relay-load: B's whole vault through the relay, --users at once ──
        await _relay_load(ctx, vw, b, peg, cdn_n, cdn_since)

        if ctx.app:
            await _ui(ctx, w, vw, a, b, nick, peg, armed["port"], cdn_n, cdn_since)
        else:
            for name in (SELECT, FOLDER, VAULT, PROXIED):
                ctx.skip(name, "needs UI (--no-ui)")
    finally:
        await owner.post("/admin/proxies/slop-dl/unbind", json={"account_id": b})
        await asyncio.sleep(1.0)
        proxy.__exit__(None, None, None)

    s = ctx.rec.summary("relay-load").get(f"GET {DOWNLOAD}")
    if s:
        ctx.metric("p95_vs_last_green", {"relay download": s["p95_ms"]})
        ctx.metric("p95_vs_last_green_n", {"relay download": s["n"]})


async def _relay_load(ctx, vw, b: str, peg: str, cdn_n, cdn_since) -> None:
    ms = vw.vault(b)["media"]
    pool = ctx.owner.share(limits=max(10, ctx.users))
    sem = asyncio.Semaphore(max(1, ctx.users))
    n0 = await cdn_n()
    res = []

    async def one(m):
        async with sem:
            r = await pool.get(f"{DOWNLOAD}?account_id={b}&media_id={m['id']}", timeout=120)
            res.append((m, r.status_code, r.headers.get("content-disposition", ""), r.content))

    ctx.rec.stage = "relay-load"
    try:
        await asyncio.gather(*(one(m) for m in ms))
    finally:
        ctx.rec.stage = None
        await pool.aclose()
    calls = await cdn_since(n0)
    served = {c["key"]: c["bytes"] for c in calls if c["status"] == 200}
    bad, non200, names = [], [], []
    for m, st, cd, body in res:
        key, ext = _key(b, m), "mp4" if m["type"] == "video" else "jpg"
        if st != 200:
            non200.append([m["id"], st])
            continue
        if cd != f'attachment; filename="{m["id"]}.{ext}"':
            names.append([m["id"], cd])
        ok = body == asset_bytes(key, m["sizes"][1]) if ext == "jpg" else (body[4:8] == b"ftyp" and len(body) == served.get(key))
        if not ok:
            bad.append([m["id"], len(body)])
    egress = sorted({c["egress"] for c in calls if c["key"] in {_key(b, m) for m in ms}})
    ctx.check(RELAY_LOAD, len(res) == len(ms) and not non200 and not bad and not names and egress == [peg],
              media=len(ms), answered=len(res), non200=non200[:10], bad_bytes=bad[:10], bad_names=names[:10],
              cdn_egress=egress, users=ctx.users)


async def _ui(ctx, w, vw, a: str, b: str, nick: dict, peg: str, port: int, cdn_n, cdn_since) -> None:
    from slop.actors import ui

    disk = Disk(Path(ctx.stack.tmp) / "downloads")
    disk.base.mkdir(parents=True, exist_ok=True)
    browser_cdn: list[dict] = []
    relay_log = Path(ctx.stack.logdir) / "relay.log"

    def log_mark() -> int:
        return relay_log.stat().st_size if relay_log.exists() else 0

    def log_since(off: int, aid: str) -> list[tuple[int, str, int]]:
        with open(relay_log, "rb") as fh:
            fh.seek(off)
            txt = fh.read().decode("utf-8", "replace")
        return [(int(m.group(2)), m.group(3), int(m.group(4))) for m in _LOG.finditer(txt) if m.group(1) == aid]

    async def setup(page, aid: str) -> None:
        bctx = page.context
        await bctx.add_init_script(TOURS_SEEN + f"localStorage.setItem('vault.accountId', '{aid}');" + PICKER_JS)
        await bctx.expose_binding("__slopFs", disk.binding)

        async def cdn(route):  # the browser -> CDN boundary (declared): the relay's fake CDN, S3's CORS
            req = route.request
            u = urlsplit(req.url)
            hdrs = {ORIG_HOST: u.hostname, EGRESS: "direct", "user-agent": "slop-browser"}
            if req.headers.get("range"):
                hdrs["range"] = req.headers["range"]
            r = await bctx.request.get(f"http://127.0.0.1:{port}{u.path}?{u.query}", headers=hdrs, timeout=60_000)
            body = await r.body()
            out = {k: v for k, v in r.headers.items() if k in ("content-type", "content-length", "content-range")}
            if r.status in (200, 206):
                out["access-control-allow-origin"] = "*"
            browser_cdn.append({"key": f"{u.hostname}{u.path}", "status": r.status, "type": req.resource_type,
                                "bytes": len(body), "t": time.time()})
            await route.fulfill(status=r.status, headers=out, body=body)

        await bctx.route(f"https://{HOST}/**", cdn)
        await page.goto(f"{ctx.app}/growth/vault-pro", wait_until="domcontentloaded", timeout=WAIT_MS)
        await page.locator("section [title^='#']").first.wait_for(timeout=WAIT_MS)
        await page.wait_for_timeout(1000)

    async def download(page, phase: str, click) -> dict:
        """Point the stub at root `phase`, shoot the trigger, click, wait for the panel to settle, shoot it."""
        d: dict = {}
        await page.evaluate(f"window.__slopPickRoot = {json.dumps(phase)}")
        d["trigger_shot"] = await ui.shot(ctx, page, f"vault-download-{phase}-trigger")
        await click()
        panel = page.locator(PANEL)
        await panel.wait_for(timeout=30_000)
        t0 = time.time()
        while time.time() - t0 < SETTLE_S:
            if await panel.get_attribute("data-phase") in ("done", "cancelled"):
                break
            await asyncio.sleep(0.25)
        d["seconds"] = round(time.time() - t0, 1)
        await page.wait_for_timeout(300)
        d["panel"] = {k: await panel.get_attribute(f"data-{k}")
                      for k in ("phase", "total", "done", "failed", "direct", "relay")}
        d["settled_shot"] = await ui.shot(ctx, page, f"vault-download-{phase}-settled")
        return d

    def browser_since(i: int, aid: str) -> list[dict]:
        return [c for c in browser_cdn[i:] if f"/files/v/{aid}/" in c["key"]]

    async def phase_run(name, page, aid, ms, folder, click, extra=None) -> dict:
        creator = _safe(nick[aid])
        want = _expected(vw, aid, creator, ms, folder)
        n0, i0, l0, v0 = await cdn_n(), len(browser_cdn), log_mark(), len(ctx.of_wire.vault_calls)
        try:
            d = await download(page, name, click)
        except Exception as e:  # noqa: BLE001 — the check reports it
            d = {"error": f"{type(e).__name__}: {e}"[:600]}
            try:
                d["failed_shot"] = await ui.shot(ctx, page, f"failed-vault-download-{name}")
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(0.5)
        calls = await cdn_since(n0)
        served = {c["key"]: c["bytes"] for c in calls if c["status"] == 200}
        d["disk"] = _verify(disk.base / name, want, served)
        br = browser_since(i0, aid)
        d["browser_cdn"] = {"n": len(br), "status": sorted({c["status"] for c in br}),
                            "types": sorted({c["type"] for c in br})}
        d["browser_by_key"] = {}
        for c in br:
            d["browser_by_key"].setdefault(c["key"], []).append(c["status"])
        lines = log_since(l0, aid)
        d["relay_downloads"] = {"n": len(lines), "ok": sum(1 for _, s, _ in lines if s == "ok")}
        d["relay_cdn_egress"] = sorted({c["egress"] for c in calls if c["key"] in {e["key"] for e in want.values()}
                                        and c.get("ua") != "slop-browser"})
        d["by_id"] = [c["query"]["id"] for c in ctx.of_wire.vault_calls[v0:] if c["route"] == "by_id"
                      and c["account"] == aid]
        d["want"] = len(want)
        if extra:
            d.update(extra)
        return d

    def settled(d: dict, n: int) -> bool:
        p = d.get("panel") or {}
        return ("error" not in d and p.get("phase") == "done" and p.get("total") == str(n)
                and p.get("done") == str(n) and p.get("failed") == "0")

    def disk_ok(d: dict) -> bool:
        k = d["disk"]
        return k["got"] == k["want"] and not k["missing"] and not k["stray"] and not k["bad_bytes"]

    def pick(aid: str) -> list[dict]:
        newest = vw.listing(aid)[:40]
        return [m for m in newest if m["type"] == "photo"][:3] + [m for m in newest if m["type"] == "video"][:1]

    async def tick(page, ms) -> None:
        await page.get_by_role("button", name="Select", exact=True).click(timeout=10_000)
        for m in ms:
            t = page.locator(f"section [title^='#{m['id']} ']").first
            await t.scroll_into_view_if_needed(timeout=10_000)
            await t.click(timeout=10_000)
        await page.get_by_role("button", name="Download selected").wait_for(timeout=10_000)

    # ── A: no proxy, direct ──
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(LISTS_PATH, MEDIA_PATH)) as page:
        try:
            await setup(page, a)
        except Exception as e:  # noqa: BLE001
            for name in (SELECT, FOLDER, VAULT):
                ctx.check(name, False, error=f"setup: {type(e).__name__}: {e}"[:600])
            await ui.shot(ctx, page, "failed-vault-download-setup")
            return

        # select
        sel = pick(a)
        await tick(page, sel)
        d = await phase_run("select", page, a, sel, None,
                            lambda: page.get_by_role("button", name="Download selected").click(timeout=10_000))
        ctx.check(SELECT, len(sel) == 4 and settled(d, 4) and disk_ok(d) and d["panel"]["direct"] == "4"
                  and d["relay_downloads"]["n"] == 0 and d["browser_cdn"]["n"] == 4, **d)
        await page.get_by_role("button", name="Close download").click(timeout=10_000)
        await page.get_by_role("button", name="Clear").click(timeout=10_000)
        await page.get_by_role("button", name="Selecting", exact=True).click(timeout=10_000)

        # folder
        f = vw.vault(a)["folders"][0]
        fms = [m for m in vw.vault(a)["media"] if f["id"] in m["folders"]]

        async def open_folder_menu():
            row = page.locator("aside [role='button']").filter(has_text=f["name"]).first
            await row.get_by_role("button", name="More").click(timeout=10_000)
            await page.get_by_role("menuitem", name="Download folder").click(timeout=10_000)

        d = await phase_run("folder", page, a, fms, f["name"], open_folder_menu)
        ctx.check(FOLDER, bool(fms) and settled(d, len(fms)) and disk_ok(d) and d["panel"]["direct"] == str(len(fms))
                  and d["relay_downloads"]["n"] == 0, folder=f["name"], **d)
        await page.get_by_role("button", name="Close download").click(timeout=10_000)

        # whole vault, STALE urls signed for a proxy A left
        every = vw.vault(a)["media"]
        stale = [m for m in every if m["type"] == "photo"][-STALE:]
        vault_week.set_urls(w, vw, a, [m["id"] for m in stale], egress=OLD_EGRESS)
        d = await phase_run("vault", page, a, every, None,
                            lambda: page.get_by_role("button", name="Download whole vault").click(timeout=10_000),
                            extra={"stale": [m["id"] for m in stale]})
        stale_keys = {_key(a, m) for m in stale}
        stale_ok = (sorted(d["by_id"]) == sorted(m["id"] for m in stale)
                    and all(d["browser_by_key"].get(k) == [403, 200] for k in stale_keys))
        d["stale_browser"] = {k: d["browser_by_key"].get(k) for k in stale_keys}
        ctx.check(VAULT, settled(d, len(every)) and disk_ok(d) and d["panel"]["direct"] == str(len(every))
                  and d["relay_downloads"]["n"] == 0 and stale_ok, **{k: v for k, v in d.items() if k != "browser_by_key"})

    # ── B: on a proxy, relay only ──
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(LISTS_PATH, MEDIA_PATH)) as page:
        try:
            await setup(page, b)
            sel = pick(b)
            await tick(page, sel)
        except Exception as e:  # noqa: BLE001
            ctx.check(PROXIED, False, error=f"setup: {type(e).__name__}: {e}"[:600])
            await ui.shot(ctx, page, "failed-vault-download-proxied-setup")
            return
        d = await phase_run("proxied", page, b, sel, None,
                            lambda: page.get_by_role("button", name="Download selected").click(timeout=10_000))
        d.pop("browser_by_key", None)
        ctx.check(PROXIED, len(sel) == 4 and settled(d, 4) and disk_ok(d) and d["browser_cdn"]["n"] == 0
                  and d["panel"]["relay"] == "4" and d["relay_downloads"]["ok"] == 4 and d["relay_cdn_egress"] == [peg],
                  **d)
