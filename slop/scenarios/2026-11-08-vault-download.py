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
Stage relay-stale (also --no-ui): the first STALE_N of B's mirror urls expired (signed for its proxy, DateLessThan
2 h ago, as AE's browser held them on 2026-11-10), OF's by-id read limited to one per OF_MIN_GAP_S per Creator
(`min_gap`, a 429 when sooner), then `--users` concurrent relay downloads of them: each re-signed by id once, paced
on the Creator (of_pacing walk), all delivered.                                                 RELAY_STALE.
UI (one owner, Chromium 1440x900, Vault Pro on A, the folder picker stubbed, files on disk under the run's tmp):
  select   Select, tick the 3 newest photos + the newest video, Download selected (`vault-download-select-trigger`,
           `-settled`).                                                                        SELECT.
  select-folder  the rail folder that is NOT the first folder of 2 media in 2 folders: open it, tick them, Download
           selected (`vault-download-select-folder-trigger`, `-settled`): both under that folder only.  SELECT_IN_FOLDER.
  folder   the rail's first folder: its row menu > Download folder (`vault-download-folder-trigger`, `-settled`).
                                                                                               FOLDER.
  vault    STALE of A's mirror urls re-signed for a proxy A left (OLD_EGRESS), then the toolbar's Download whole vault
           (`vault-download-vault-trigger`, `-settled`): every media once; the stale ones 403 direct, are re-signed
           by id (one by-id OF read each) and fetched direct again.                            VAULT.
  switch   a fresh browser on A: Download whole vault, then, while it runs (SWITCH_FREE CDN fetches through, the
           next held), Creator B in the creator column (`vault-download-switch-trigger`: B's grid, A's card
           running, B's Download whole vault off with "A download is running"); the CDN released, the card
           settles (`-settled`): every one of A's media on disk once with exact bytes, data-phase done (not
           cancelled), data-failed 0, the card titled with A's name. The old per-model remount aborted it.  SWITCH.
  proxied  a fresh browser on B: Download selected of 3 photos + 1 video (`vault-download-proxied-trigger`,
           `-settled`): 0 browser CDN fetches, all relay.                                      PROXIED.
  phone    a fresh phone browser on B (390x844, touch, no folder picker, share stubbed): Select all (> 20) is off
           with "Phone: up to 20 at a time", 20 ticked is on, 21 off, Download folder / whole vault off with their
           reason (`vault-download-phone-cap`).                                                PHONE_CAP.
           Then 3 photos + 2 videos padded to PHONE_VIDEO_MB each (> SHARE_BATCH_BYTES/2, so never one batch):
           Download selected (`vault-download-phone-trigger`), the first "Save 1–N" (`-ready`) dismissed once
           (AbortError: the button stays), then every Save tapped until all are saved (`-settled`).  PHONE_SHARE.
Each check reads the files on disk: the path (creator = the Creator's nickname, folder = the downloaded folder or the
rail folder a selection was made in, else a copy in each of the media's custom OF folders, else Unfiled), a .jpg's bytes equal the CDN's seeded bytes (img_relay.asset_bytes),
an .mp4's SHA-256 equals the CDN source clip and its size equals what the fake served; no stray file; the panel's
data-done/-failed/-direct/-relay; the relay's own `vault_download account=… status=ok` log lines (0 for direct items);
the browser's CDN fetches (the harness route). p95 of the relay download vs the last green run.

Bypasses (declared):
- OF's per-account rate limit is lib/of_wire.py's `min_gap` on the by-id route only (OF_MIN_GAP_S, a guess; AE
  measured 76 unpaced reads in 19 s before the 429).
- OF at its wire (lib/of_wire.py + lib/vault_wire.py); the mirror seeded by SQL; OF's earlier-proxy listing (stale IP)
  written as mirror url rewrites (seed/vault_week.set_urls).
- OF's CDN is lib/img_relay.py's fake in the relay process. The BROWSER's CDN requests (https://cdn2.onlyfans.com/…)
  are taken at the browser's network boundary by a Playwright route and answered by that same fake (same bytes,
  Policy / SourceIp check, Range), egress "direct" (the browser is on this machine, as an unproxied account's relay
  is), with S3's CORS: `Access-Control-Allow-Origin: *` on 200/206, none on 403/404 (measured on the real CDN
  2026-11-08: a denied fetch rejects with TypeError). Playwright buffers each body (route.fulfill), so the
  browser side is not streamed byte by byte as from the real CDN.
- Switch stage only: that route is a slow CDN on demand (`_Hold`): after A's first SWITCH_FREE download fetches
  (resource type fetch, A's files) it holds the next ones until B's grid is up and shot, then answers them as
  above. Deterministic "still running at the switch" instead of a timing race; bytes and checks unchanged. None
  held within 60 s: SWITCH red with that error (never a hang). A held fetch the page dropped meanwhile can't be
  answered: counted (`held_dropped`), not raised.
- The native folder picker (`showDirectoryPicker`) is stubbed by an init script in this test only: a directory
  handle whose `createWritable()` is a real WritableStream; each chunk crosses a Playwright binding (base64) and is
  written under the run's tmp as `<file>.crswap`, renamed on close, deleted on abort (Chromium's own swap-file rule).
  The stub refuses separators and "."/".." in names, as the real API does. `__slopPickHold` keeps it open until
  `__slopPickClose()` (the user's Cancel: AbortError), for the hint shown while Chrome's picker is up.  PICK_HINT.
- The links .html is opened with page.set_content (its exact bytes), not file:// (the harness context aborts every
  non-loopback load); an app link is fetched with the context's session (APIRequestContext, its cookies), not by a
  click (a click would save it via the browser's download manager).
- One ffmpeg testsrc clip for every mp4 (img_relay.video_bytes); videos are never DRM here (unit-tested instead:
  service/tests/test_vault_download.py). The phone stage's 2 videos are that clip padded with a `free` box to
  PHONE_VIDEO_MB (img_relay.padded_mp4, the fake re-armed just before the stage).
- Phone: Chromium with mobile emulation (viewport, touch, is_mobile), not WebKit/iOS. `showDirectoryPicker` is deleted
  by an init script; `navigator.canShare` / `navigator.share` (the OS share sheet, not automatable) are stubbed at the
  page boundary (SHARE_JS): canShare true for files, share records each File's name / type / size and whether the
  call ran inside a user activation (`navigator.userActivation.isActive`), and rejects one call with AbortError when
  told to (the user dismissing the sheet). Save to Photos / Files itself and iOS memory limits are not exercised.
Links file (app/components/vault/vaultLinksFile.ts), every desktop phase: links-valid-*.txt + .html in
<creator>/[<folder>/], opened before any media (Disk.opened), one line / row per item; A: CDN urls, B: the app relay
url; the html opened in Chromium (`vault-download-links-html`, `-proxied`), a CDN link clicked (A), an app link
fetched with the session (B).                                                                  LINKS.
Phone: "Save links" tapped first: its own share, txt + html, inside the tap, app urls.          PHONE_LINKS.
Break-it-once: vault-download-resign-unpaced (service: the download's re-sign reads unpaced) turns only RELAY_STALE
red; vault-download-selection-ignores-folder (client: Download selected drops the rail folder) turns only
SELECT_IN_FOLDER red; vault-download-links-cdn-for-proxied (client: `linkRows` drops the direct rule) turns only LINKS and
PHONE_LINKS red; vault-download-direct-ignores-proxy (client: `sourceFor` drops the proxy rule) turns only PROXIED and
PHONE_SHARE red; vault-download-share-batch-drops-item (client: `addToBatches` loses the file that opens a batch)
turns only PHONE_SHARE red; vault-download-switch-aborts-run (client: VaultProPage's per-model keyed subtree mounts a
download of its own around VaultManagePanel, the pre-fix layout) turns only SWITCH red.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import html as html_lib
import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from collections import Counter

from slop.lib.img_relay import EGRESS, ORIG_HOST, arm_run, asset_bytes, video_bytes
from slop.lib.vault_ui import TOURS_SEEN, open_vault_pro
from slop.lib.vault_download_faults import (
    FOLDER, LINKS, PHONE_CAP, PICK_HINT, PHONE_LINKS, PHONE_SHARE, PROXIED, RELAY_LOAD, RELAY_STALE, SELECT,
    SELECT_IN_FOLDER, SWITCH, VAULT,
)
from slop.lib.vault_ui import cdn_count, cdn_calls, proxy_bind, captured
from slop.lib.vault_wire import HOST, VaultWire, path as cdn_path
from slop.seed import vault_week

_VIDEO_SHA = hashlib.sha256(video_bytes()).hexdigest()


@dataclass
class _UiWorld:
    w: object
    vw: VaultWire
    a: str
    b: str
    nick: dict
    peg: str
    port: int

PROFILE = "flat_agency"
UI = True
OF_WIRE = True
FAULT = "vault-download-direct-ignores-proxy"
RELAY_ENV = {"VAULT_COLLECT_ENABLED": "0", "SLOP_VAULT_STILLS": "1"}
P95_VS_LAST = (1.5, 200)
P95_VS_LAST_MIN_N = 20
CDN_LATENCY_S = 0.02
VIEWPORT = (1440, 900)
PHONE_VIEWPORT = (390, 844)
PHONE_MAX = 20                     # vaultDownloadReducer.SHARE_MAX_ITEMS
PHONE_VIDEO_MB = 110               # > SHARE_BATCH_BYTES (200 MB) / 2: two never share a batch
PHONE_COUNT_OFF = f"Phone: up to {PHONE_MAX} at a time"
PHONE_MODE_OFF = "Phone: only a selection downloads here; folders and the whole vault need desktop Chrome or Edge"
WAIT_MS = 120_000
SETTLE_S = 180
STALE = 3
SWITCH_FREE = 3                    # switch stage: A's download fetches let through before the hold (declared)
BUSY_OFF = "A download is running"  # vaultDownloadReducer.BUSY_OFF
STALE_N = 15                       # relay-stale: paced at ~1/s, so ~15 s
OF_MIN_GAP_S = 0.5
BY_ID = "GET /api2/v2/vault/media/{id}"
OLD_EGRESS = "127.0.0.1:1"
DOWNLOAD = "/admin/vault-ai/download"
LISTS_PATH = "/api/of/v2/vault/lists"
MEDIA_PATH = "/api/of/v2/vault/media"
PANEL = "[aria-label='Vault download']"
_LOG = re.compile(r"vault_download account=(\S+) media=(\d+) status=(\S+) bytes=(\d+)")

# The native folder picker, in this test only (declared above).
PICKER_JS = r"""(() => {
  const call = (...a) => window.__slopFs(...a);
  const b64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000)
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
  const check = (n) => { if (!n || n === "." || n === ".." || /[\/\\]/.test(n)) throw new TypeError("Name is not allowed."); };
  const unb64 = (s) => { const b = atob(s), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u; };
  const file = (p, name) => ({ kind: "file", name,
    async getFile() { return new File([unb64(await call("read", p))], name); },
    async createWritable() {
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
  window.showDirectoryPicker = async () => {
    if (window.__slopPickHold) return new Promise((_, no) => {
      window.__slopPickClose = () => no(new DOMException("The user aborted a request.", "AbortError")); });
    const r = window.__slopPickRoot || "root"; await call("mkdir", r); return dir(r, r); };
})();"""


# The phone: no folder picker, the share sheet stubbed at the page boundary (declared above).
SHARE_JS = r"""(() => {
  try { delete Window.prototype.showDirectoryPicker; } catch (e) {}
  try { delete window.showDirectoryPicker; } catch (e) {}
  const S = window.__slopShare = { calls: [], dismissed: [], abortNext: false };
  navigator.canShare = (d) => !!(d && Array.isArray(d.files) && d.files.length);
  navigator.share = async (d) => {
    const active = navigator.userActivation ? navigator.userActivation.isActive : null;
    const files = await Promise.all(Array.from((d && d.files) || []).map(async (f) => ({ name: f.name, type: f.type,
      size: f.size, text: f.type.startsWith("text/") ? await f.text() : null })));
    if (S.abortNext) { S.abortNext = false; S.dismissed.push({ files, active });
      throw new DOMException("Share canceled", "AbortError"); }
    S.calls.push({ files, active });
  };
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
        self.opened: list[str] = []   # every file opened, in order (rel to base): links files must come first

    def _p(self, rel: str) -> Path:
        p = (self.base / rel).resolve()
        if self.base not in p.parents and p != self.base:
            raise ValueError(f"outside the root: {rel}")
        return p

    async def binding(self, _source, op: str, *a):
        if op == "mkdir":
            self._p(a[0]).mkdir(parents=True, exist_ok=True)
            return None
        if op == "read":
            return base64.b64encode(self._p(a[0]).read_bytes()).decode()
        if op == "open":
            p = self._p(a[0])
            self.opened.append(str(p.relative_to(self.base)))
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


class _Hold:
    """The switch stage's slow CDN (declared): once armed, `aid`'s download fetches past the first `free` wait for
    `go`, so the run is still in flight when another Creator is picked. `first_held`: the first one is waiting."""

    def __init__(self, aid: str, free: int):
        self.aid, self.free = aid, free
        self.armed = False
        self.passed = self.held = self.dropped = 0
        self.first_held = asyncio.Event()
        self.go = asyncio.Event()

    def wrap(self, handler):
        """The CDN route `handler` behind the hold. A held request is answered after `go`; if the page dropped it
        meanwhile (an aborted fetch) its fulfill fails: counted in `dropped`, only for a request held here."""
        async def route(r) -> None:
            req = r.request
            if not (self.armed and req.resource_type == "fetch" and f"/files/v/{self.aid}/" in req.url):
                return await handler(r)
            if self.passed < self.free:
                self.passed += 1
                return await handler(r)
            self.held += 1
            self.first_held.set()
            await self.go.wait()
            await handler(_HeldRoute(r, self))
        return route


class _HeldRoute:
    """A route `_Hold` held, as the CDN handler sees it: a failed fulfill (the page gave up on it) is counted."""

    def __init__(self, route, hold: _Hold):
        self.request, self._route, self._hold = route.request, route, hold

    async def fulfill(self, **kw) -> None:
        try:
            await self._route.fulfill(**kw)
        except Exception:  # noqa: BLE001 — the page aborted this held fetch meanwhile (counted, the check reads disk)
            self._hold.dropped += 1


async def _open_vault(ctx, page, aid: str, port: int, browser_cdn: list[dict], hold: _Hold | None = None) -> None:
    """Vault Pro on `aid`, tours seen, the browser's CDN requests answered by the relay's fake (declared)."""
    bctx = page.context
    await bctx.add_init_script(TOURS_SEEN + f"localStorage.setItem('vault.accountId', '{aid}');")

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

    await bctx.route(f"https://{HOST}/**", hold.wrap(cdn) if hold else cdn)
    await open_vault_pro(page, ctx, timeout=WAIT_MS)
    await page.locator("section [title^='#']").first.wait_for(timeout=WAIT_MS)
    await page.wait_for_timeout(1000)


def _key(aid: str, m: dict) -> str:
    return f"{HOST}{cdn_path(aid, m['id'], 'src' if m['type'] == 'video' else 'full')}"


def _expected(vw, aid: str, creator: str, ms: list[dict], folder: str | None) -> dict[str, dict]:
    """{"creator/folder/id.ext": {mid, key, size (jpg) or None (mp4)}}: the forced folder, else one copy per custom
    folder of the media (vaultDownloadReducer.toItems), else Unfiled."""
    names = {f["id"]: f["name"] for f in vw.vault(aid)["folders"]}
    out = {}
    for m in ms:
        fs = [folder] if folder is not None else ([names[i] for i in m["folders"]] or ["Unfiled"])
        ext = "mp4" if m["type"] == "video" else "jpg"
        for f in dict.fromkeys(_safe(x) for x in fs):
            out[f"{creator}/{f}/{m['id']}.{ext}"] = {"mid": m["id"], "key": _key(aid, m),
                                                    "size": None if ext == "mp4" else m["sizes"][1]}
    return out


async def _card(panel) -> dict | None:
    """The download card's data-* counts and title; None once it is gone."""
    if not await panel.count():
        return None
    o = {k: await panel.get_attribute(f"data-{k}", timeout=5_000)
         for k in ("phase", "total", "done", "failed", "direct", "relay")}
    o["title"] = await panel.locator("div.font-medium").first.get_attribute("title", timeout=5_000)
    return o


def _is_links(name: str) -> bool:
    return name.startswith("links-valid-") and name.endswith((".txt", ".html"))


def _app_link(app: str, aid: str, mid: int) -> str:
    """vaultLinksFile.appLink (no share token here)."""
    return f"{app.rstrip('/')}{DOWNLOAD}?{urlencode({'account_id': aid, 'media_id': mid})}"


def _link_lines(txt: str) -> list[tuple[str, str]]:
    return [tuple(ln.split("  ", 1)) for ln in txt.splitlines() if ln and not ln.startswith("#")]


def _links(txt: str, html: str, aid: str, ms: list[dict], direct: bool, app: str) -> dict:
    """A links file vs the items: one line / row each, every id once; direct: the CDN url of that media, unexpired;
    proxied: the app relay url, no CDN host."""
    want = {f"{m['id']}.{'mp4' if m['type'] == 'video' else 'jpg'}": m for m in ms}
    lines = _link_lines(txt)
    names = Counter(n for n, _ in lines)
    bad = []
    for name, link in lines:
        m = want.get(name)
        if m is None:
            continue
        if direct:
            u = urlsplit(link)
            exp = _policy_exp(link)
            if f"{u.hostname}{u.path}" != _key(aid, m) or not exp or exp < time.time() + 600:
                bad.append([name, link[:120]])
        elif link != _app_link(app, aid, m["id"]):
            bad.append([name, link[:160]])
    rows = re.findall(r'<tr data-id="(\d+)" data-link="(\w+)">(.*?)</tr>', html, re.S)
    html_bad = []
    by_id = {str(m["id"]): m for m in ms}
    for mid, kind, body in rows:
        m = by_id.get(mid)
        if m is None:
            html_bad.append([mid, "unknown item"])
            continue
        hrefs = [html_lib.unescape(h) for h in re.findall(r'<a href="([^"]+)"', body)]
        backup = _app_link(app, aid, m["id"])
        if direct:
            primary = hrefs[0] if hrefs else ""
            u = urlsplit(primary)
            try:
                exp = _policy_exp(primary)
            except (ValueError, KeyError, IndexError):
                exp = None
            if (kind != "cdn" or len(hrefs) != 2 or f"{u.hostname}{u.path}" != _key(aid, m)
                    or not exp or exp < time.time() + 600 or hrefs[1] != backup):
                html_bad.append([mid, "primary or backup href"])
        elif kind != "app" or hrefs != [backup]:
            html_bad.append([mid, "app href"])
    return {"lines": len(lines), "want": len(want), "missing": sorted(set(want) - set(names))[:10],
            "twice": sorted(n for n, k in names.items() if k > 1)[:10], "stray": sorted(set(names) - set(want))[:10],
            "bad": bad[:10], "cdn_host_in_txt": HOST in txt, "html_rows": len(rows),
            "html_bad": html_bad[:10], "html_ids_ok": sorted(int(i) for i, _, _ in rows) == sorted(m["id"] for m in ms),
            "html_kinds": sorted({k for _, k, _ in rows}), "valid_line": next((ln for ln in txt.splitlines()
                                                                             if ln.startswith("# Valid")), "")}


def _links_ok(k: dict, direct: bool) -> bool:
    return (k["lines"] == k["want"] and not k["missing"] and not k["twice"] and not k["stray"] and not k["bad"]
            and k["html_rows"] == k["want"] and k["html_ids_ok"] and not k["html_bad"]
            and k["html_kinds"] == (["cdn"] if direct else ["app"]) and k["cdn_host_in_txt"] == direct)


def _policy_exp(url: str) -> int | None:
    p = parse_qs(urlsplit(url).query).get("Policy", [None])[0]
    if not p:
        return None
    raw = p.replace("-", "+").replace("_", "=").replace("~", "/")
    pol = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    return int(pol["Statement"][0]["Condition"]["DateLessThan"]["AWS:EpochTime"])


def _verify(root: Path, want: dict[str, dict], served: dict[str, int]) -> dict:
    """Files under `root` vs `want`: missing, stray, bad bytes."""
    got = {str(p.relative_to(root)): p for p in root.rglob("*") if p.is_file() and not _is_links(p.name)}
    bad = []
    for rel, e in want.items():
        p = got.get(rel)
        if p is None:
            continue
        b = p.read_bytes()
        if e["size"] is not None:
            if b != asset_bytes(e["key"], e["size"]):
                bad.append([rel, len(b), e["size"]])
        elif len(b) != served.get(e["key"], -1) or hashlib.sha256(b).hexdigest() != _VIDEO_SHA:
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
    assets = vw.assets([a, b])
    armed = await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S)
    owner = ctx.owner

    async with proxy_bind(owner, "slop-dl", notes="slop: vault-download", account_id=b) as proxy:
        bind = proxy.assign_status
        peg = f"127.0.0.1:{proxy.port}"
        vault_week.set_urls(w, vw, a, [m["id"] for m in vw.vault(a)["media"]], egress="direct")
        vault_week.set_urls(w, vw, b, [m["id"] for m in vw.vault(b)["media"]], egress=peg)
        ctx.note(f"A={a} (direct), B={b} on proxy {peg} (assign {bind}), {n_items} media each, cdn port {armed['port']}")

        # ── relay-load: B's whole vault through the relay, --users at once ──
        await _relay_load(ctx, vw, b, peg, proxy.bound)
        await _relay_stale(ctx, w, vw, b, peg)

        if ctx.app:
            await _ui(ctx, _UiWorld(w, vw, a, b, nick, peg, armed["port"]))
            await _phone(ctx, vw, b, peg, armed["port"], assets)
        else:
            for name in (SELECT, SELECT_IN_FOLDER, FOLDER, VAULT, SWITCH, PROXIED, PHONE_CAP, PHONE_SHARE, LINKS, PHONE_LINKS):
                ctx.skip(name, "needs UI (--no-ui)")
    s = ctx.rec.summary("relay-load").get(f"GET {DOWNLOAD}")
    if s:
        ctx.metric("p95_vs_last_green", {"relay download": s["p95_ms"]})
        ctx.metric("p95_vs_last_green_n", {"relay download": s["n"]})


async def _relay_load(ctx, vw, b: str, peg: str, bound: bool) -> None:
    ms = vw.vault(b)["media"]
    pool = ctx.owner.share(limits=max(10, ctx.users))
    sem = asyncio.Semaphore(max(1, ctx.users))
    n0 = await cdn_count(ctx)
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
    calls = await cdn_calls(ctx, n0)
    served = {c["key"]: c["bytes"] for c in calls if c["status"] == 200}
    bad, non200, names = [], [], []
    for m, st, cd, body in res:
        key, ext = _key(b, m), "mp4" if m["type"] == "video" else "jpg"
        if st != 200:
            non200.append([m["id"], st])
            continue
        if cd != f'attachment; filename="{m["id"]}.{ext}"':
            names.append([m["id"], cd])
        ok = body == asset_bytes(key, m["sizes"][1]) if ext == "jpg" else (len(body) == served.get(key) and hashlib.sha256(body).hexdigest() == _VIDEO_SHA)
        if not ok:
            bad.append([m["id"], len(body)])
    egress = sorted({c["egress"] for c in calls if c["key"] in {_key(b, m) for m in ms}})
    ctx.check(RELAY_LOAD, bound and len(res) == len(ms) and not non200 and not bad and not names and egress == [peg],
              media=len(ms), answered=len(res), non200=non200[:10], bad_bytes=bad[:10], bad_names=names[:10],
              cdn_egress=egress, bound=bound, users=ctx.users)


async def _relay_stale(ctx, w, vw, b: str, peg: str) -> None:
    fake = ctx.of_wire
    ms = vw.vault(b)["media"][:STALE_N]
    vault_week.set_urls(w, vw, b, [m["id"] for m in ms], exp=vault_week.expired_exp(), egress=peg)
    pool = ctx.owner.share(limits=max(10, ctx.users))
    sem = asyncio.Semaphore(max(1, ctx.users))
    n0 = len(fake.calls)
    res = []

    async def one(m):
        async with sem:
            r = await pool.get(f"{DOWNLOAD}?account_id={b}&media_id={m['id']}", timeout=120)
            res.append((m, r.status_code, r.content))

    fake.min_gap[(b, BY_ID)] = OF_MIN_GAP_S
    ctx.rec.stage = "relay-stale"
    try:
        await asyncio.gather(*(one(m) for m in ms))
    finally:
        ctx.rec.stage = None
        fake.min_gap.pop((b, BY_ID), None)
        await pool.aclose()
    by_id = [c for c in fake.calls[n0:] if c["account"] == b and c["route"] == BY_ID]
    st = Counter(c["status"] for c in by_id)
    ok_ids = Counter(c["path"].rsplit("/", 1)[1] for c in by_id if c["status"] == 200)
    non200 = [[m["id"], s] for m, s, _ in res if s != 200]
    bad = [m["id"] for m, s, body in res if s == 200 and m["type"] != "video"
           and body != asset_bytes(_key(b, m), m["sizes"][1])]
    ctx.check(RELAY_STALE, len(res) == len(ms) and not non200 and not bad and st.get(429, 0) == 0
              and sorted(ok_ids) == sorted(str(m["id"]) for m in ms) and max(ok_ids.values(), default=0) == 1,
              media=len(ms), answered=len(res), non200=non200[:10], bad_bytes=bad[:10], by_id_status=dict(st),
              reads_per_file_max=max(ok_ids.values(), default=0), users=ctx.users, of_min_gap_s=OF_MIN_GAP_S)


async def _ui(ctx, world: _UiWorld) -> None:
    from slop.actors import ui

    w, vw, a, b, nick, peg, port = (world.w, world.vw, world.a, world.b, world.nick, world.peg, world.port)

    disk = Disk(Path(ctx.stack.tmp) / "downloads")
    disk.base.mkdir(parents=True, exist_ok=True)
    browser_cdn: list[dict] = []
    relay_log = ctx.out / "relay.log"

    def log_mark() -> int:
        return relay_log.stat().st_size if relay_log.exists() else 0

    def log_since(off: int, aid: str) -> list[tuple[int, str, int]]:
        with open(relay_log, "rb") as fh:
            fh.seek(off)
            txt = fh.read().decode("utf-8", "replace")
        return [(int(m.group(2)), m.group(3), int(m.group(4))) for m in _LOG.finditer(txt) if m.group(1) == aid]

    async def setup(page, aid: str, hold: _Hold | None = None) -> None:
        await page.context.add_init_script(PICKER_JS)
        await page.context.expose_binding("__slopFs", disk.binding)
        await _open_vault(ctx, page, aid, port, browser_cdn, hold)

    async def download(page, phase: str, click, during=None) -> dict:
        """Point the stub at root `phase`, shoot the trigger, click, wait for the panel to settle, shoot it.
        `during(page, panel)`: runs once the card is up, before the settle wait, and shoots the trigger itself."""
        d: dict = {}
        await page.evaluate(f"window.__slopPickRoot = {json.dumps(phase)}")
        if during is None:
            d["trigger_shot"] = await ui.shot(ctx, page, f"vault-download-{phase}-trigger")
        await click()
        panel = page.locator(PANEL)
        await panel.wait_for(timeout=30_000)
        if during is not None:
            d.update(await during(page, panel))
        t0 = time.time()
        while time.time() - t0 < SETTLE_S:   # a card gone (unmounted) settles too: the check reads that
            if not await panel.count() or await panel.get_attribute("data-phase", timeout=5_000) in ("done", "cancelled"):
                break
            await asyncio.sleep(0.25)
        d["seconds"] = round(time.time() - t0, 1)
        await page.wait_for_timeout(300)
        d["panel"] = await _card(panel)
        d["settled_shot"] = await ui.shot(ctx, page, f"vault-download-{phase}-settled")
        return d

    def browser_since(i: int, aid: str) -> list[dict]:
        return [c for c in browser_cdn[i:] if f"/files/v/{aid}/" in c["key"]]

    async def phase_run(name, page, aid, ms, folder, click, extra=None, during=None) -> dict:
        creator = _safe(nick[aid])
        want = _expected(vw, aid, creator, ms, folder)
        n0, i0, l0, v0 = await cdn_count(ctx), len(browser_cdn), log_mark(), len(ctx.of_wire.vault_calls)
        o0 = len(disk.opened)
        d = {}
        async with captured(ctx, page, d, f"failed-vault-download-{name}"):
            d.update(await download(page, name, click, during))
        await asyncio.sleep(0.5)
        calls = await cdn_calls(ctx, n0)
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
        # The links file: in <creator>/ (a folder download: <creator>/<folder>/), opened before any media.
        ldir = disk.base / name / creator / (_safe(folder) if folder is not None else "")
        files = sorted(p for p in ldir.glob("links-valid-*") if p.is_file()) if ldir.is_dir() else []
        txt = next((p for p in files if p.suffix == ".txt"), None)
        html = next((p for p in files if p.suffix == ".html"), None)
        first = [Path(x).name for x in disk.opened[o0:o0 + 2]]
        lk = {"dir": str(ldir.relative_to(disk.base)), "files": [p.name for p in files], "first_opened": first,
              "first_ok": len(files) == 2 and sorted(first) == sorted(p.name for p in files)}
        if txt and html:
            lk.update(_links(txt.read_text(), html.read_text(), aid, ms, aid == a, ctx.app))
            lk["html_path"] = str(html)
            (ctx.out / f"links-{name}.txt").write_text(txt.read_text())   # evidence: the file's content
            (ctx.out / f"links-{name}.html").write_text(html.read_text())
        d["links"] = lk
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

    async def open_links(page, html_path: str, shot_name: str, m: dict, direct: bool) -> dict:
        """The links html in Chromium (its bytes via set_content, as double-clicked), shot; then m's link: CDN clicked (the popup's
        load through the browser's CDN boundary), app fetched with this context's session (its cookies)."""
        o: dict = {}
        hp = await page.context.new_page()
        try:
            # set_content, not file://: the harness context aborts every non-loopback load (declared)
            await hp.set_content(Path(html_path).read_text(), timeout=WAIT_MS)
            o["shot"] = await ui.shot(ctx, hp, shot_name)
            row = hp.locator(f'tr[data-id="{m["id"]}"]')
            href = await row.locator("a").first.get_attribute("href")
            o["href"] = (href or "")[:200]
            if direct:
                i0 = len(browser_cdn)
                async with hp.expect_popup(timeout=WAIT_MS) as pi:
                    await row.get_by_role("link", name="Open (CDN)").click(timeout=10_000)
                pop = await pi.value
                await pop.wait_for_load_state(timeout=WAIT_MS)
                o["opened_shot"] = await ui.shot(ctx, pop, shot_name + "-opened")
                hits = [c for c in browser_cdn[i0:] if c["key"] == _key(a, m)]
                o["cdn"] = [[c["status"], c["type"], c["bytes"]] for c in hits]
                o["ok"] = pop.url == href and any(c[0] == 200 and c[1] == "document" and c[2] == m["sizes"][1]
                                                   for c in o["cdn"])
            else:
                rr = await page.context.request.get(href, timeout=60_000)
                body = await rr.body()
                o["app"] = {"status": rr.status, "cd": rr.headers.get("content-disposition"), "bytes": len(body)}
                o["ok"] = (rr.status == 200 and o["app"]["cd"] == f'attachment; filename="{m["id"]}.jpg"'
                           and body == asset_bytes(_key(b, m), m["sizes"][1]))
        except Exception as e:  # noqa: BLE001 — the check reports it
            o["error"] = f"{type(e).__name__}: {e}"[:600]
            o["ok"] = False
        finally:
            await hp.close()
        return o

    lk_all: dict = {}

    # ── A: no proxy, direct ──
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(LISTS_PATH, MEDIA_PATH)) as page:
        try:
            await setup(page, a)
        except Exception as e:  # noqa: BLE001
            for name in (PICK_HINT, SELECT, SELECT_IN_FOLDER, FOLDER, VAULT, LINKS, SWITCH):
                ctx.check(name, False, error=f"setup: {type(e).__name__}: {e}"[:600])
            await ui.shot(ctx, page, "failed-vault-download-setup")
            return

        # the hint while Chrome's picker is up, then the user's Cancel
        h: dict = {}
        try:
            await page.evaluate("window.__slopPickHold = true")
            await page.get_by_role("button", name="Download whole vault").click(timeout=10_000)
            hint = page.get_by_test_id("dl-pick-hint")
            await hint.wait_for(timeout=10_000)
            h["text"] = await hint.inner_text()
            h["shot"] = await ui.shot(ctx, page, "vault-download-pick-hint")
            await page.evaluate("window.__slopPickClose(); window.__slopPickHold = false")
            await hint.wait_for(state="detached", timeout=10_000)
            h["panels_after"] = await page.locator(PANEL).count()
            h["closed_shot"] = await ui.shot(ctx, page, "vault-download-pick-hint-closed")
        except Exception as e:  # noqa: BLE001 — the check reports it
            h["error"] = f"{type(e).__name__}: {e}"[:600]
        ctx.check(PICK_HINT, "error" not in h and "New Folder" in h.get("text", "")
                  and "Desktop" in h.get("text", "") and h.get("panels_after") == 0, **h)

        # select
        sel = pick(a)
        await tick(page, sel)
        d = await phase_run("select", page, a, sel, None,
                            lambda: page.get_by_role("button", name="Download selected").click(timeout=10_000))
        lk_all["select"] = d["links"]
        ctx.check(SELECT, len(sel) == 4 and settled(d, 4) and disk_ok(d) and d["panel"]["direct"] == "4"
                  and d["relay_downloads"]["n"] == 0 and d["browser_cdn"]["n"] == 4, **d)
        await page.get_by_role("button", name="Close download").click(timeout=10_000)
        await page.get_by_role("button", name="Clear").click(timeout=10_000)
        await page.get_by_role("button", name="Selecting", exact=True).click(timeout=10_000)

        # select inside a rail folder: media whose FIRST folder is another one must still land in this one
        two = [m for m in vw.vault(a)["media"] if len(m["folders"]) == 2]
        fid = Counter(m["folders"][1] for m in two).most_common(1)[0][0] if two else None
        fname = next((f["name"] for f in vw.vault(a)["folders"] if f["id"] == fid), "")
        sf = [m for m in vw.listing(a, list_id=fid) if m["folders"][0] != fid][:2] if fid else []
        d: dict = {}
        try:
            await page.locator("aside [role='button']").filter(has_text=fname).first.click(timeout=10_000)
            await page.wait_for_timeout(1000)
            await tick(page, sf)
            d = await phase_run("select-folder", page, a, sf, fname,
                                lambda: page.get_by_role("button", name="Download selected").click(timeout=10_000))
            d.pop("browser_by_key", None)
            await page.get_by_role("button", name="Close download").click(timeout=10_000)
            await page.get_by_role("button", name="Clear").click(timeout=10_000)
            await page.get_by_role("button", name="Selecting", exact=True).click(timeout=10_000)
            await page.locator("aside button").filter(has_text="All media").first.click(timeout=10_000)
            await page.wait_for_timeout(1000)
        except Exception as e:  # noqa: BLE001 — the check reports it
            d["error"] = f"{type(e).__name__}: {e}"[:600]
            await ui.shot(ctx, page, "failed-vault-download-select-folder")
        ctx.check(SELECT_IN_FOLDER, len(sf) == 2 and "disk" in d and settled(d, 2) and disk_ok(d),
                  folder=fname, first_folders=[m["folders"] for m in sf], **d)

        # folder
        f = vw.vault(a)["folders"][0]
        fms = [m for m in vw.vault(a)["media"] if f["id"] in m["folders"]]

        async def open_folder_menu():
            row = page.locator("aside [role='button']").filter(has_text=f["name"]).first
            await row.get_by_role("button", name="More").click(timeout=10_000)
            await page.get_by_role("menuitem", name="Download folder").click(timeout=10_000)

        d = await phase_run("folder", page, a, fms, f["name"], open_folder_menu)
        lk_all["folder"] = d["links"]
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
        lk_all["vault"] = d["links"]
        fresh = next(m for m in every if m["type"] == "photo" and m not in stale)
        lk_all["vault"]["open"] = (await open_links(page, d["links"]["html_path"], "vault-download-links-html", fresh, True)
                                   if d["links"].get("html_path") else {"ok": False, "error": "no html"})
        # A stale primary CDN URL must leave a usable app backup in the same HTML row.
        if d["links"].get("html_path") and stale:
            hp = await page.context.new_page()
            try:
                await hp.set_content(Path(d["links"]["html_path"]).read_text(), timeout=WAIT_MS)
                row = hp.locator(f'tr[data-id="{stale[0]["id"]}"]')
                primary = await row.locator("a").first.get_attribute("href")
                backup = await row.locator("a").nth(1).get_attribute("href")
                i0 = len(browser_cdn)
                await hp.evaluate("async u => { try { await fetch(u) } catch {} }", primary)
                rr = await hp.context.request.get(backup, timeout=60_000)
                body = await rr.body()
                lk_all["vault"]["stale_backup"] = {
                    "ok": any(c["status"] == 403 and c["key"] == _key(a, stale[0]) for c in browser_cdn[i0:])
                          and rr.status == 200 and body == asset_bytes(_key(a, stale[0]), stale[0]["sizes"][1]),
                    "status": rr.status, "bytes": len(body)}
            except Exception as e:  # noqa: BLE001
                lk_all["vault"]["stale_backup"] = {"ok": False, "error": repr(e)[:300]}
            finally:
                await hp.close()

    # ── switch: A's whole vault running, Creator B picked; A's run must finish whole ──
    await _switch(ctx, world, setup, phase_run, settled, disk_ok)

    # ── B: on a proxy, relay only ──
    async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(LISTS_PATH, MEDIA_PATH)) as page:
        try:
            await setup(page, b)
            sel = pick(b)
            await tick(page, sel)
        except Exception as e:  # noqa: BLE001
            ctx.check(PROXIED, False, error=f"setup: {type(e).__name__}: {e}"[:600])
            ctx.check(LINKS, False, error=f"proxied setup: {type(e).__name__}: {e}"[:600], **lk_all)
            await ui.shot(ctx, page, "failed-vault-download-proxied-setup")
            return
        d = await phase_run("proxied", page, b, sel, None,
                            lambda: page.get_by_role("button", name="Download selected").click(timeout=10_000))
        d.pop("browser_by_key", None)
        ctx.check(PROXIED, len(sel) == 4 and settled(d, 4) and disk_ok(d) and d["browser_cdn"]["n"] == 0
                  and d["panel"]["relay"] == "4" and d["relay_downloads"]["ok"] == 4 and d["relay_cdn_egress"] == [peg],
                  **d)
        lk_all["proxied"] = d["links"]
        photo = next(m for m in sel if m["type"] == "photo")
        lk_all["proxied"]["open"] = (await open_links(page, d["links"]["html_path"], "vault-download-links-html-proxied",
                                                      photo, False)
                                     if d["links"].get("html_path") else {"ok": False, "error": "no html"})
    ok = all(lk_all.get(ph, {}).get("first_ok") and _links_ok(lk_all[ph], ph != "proxied")
             for ph in ("select", "folder", "vault", "proxied")) if len(lk_all) == 4 else False
    names_ok = (len(lk_all) == 4 and all(x.startswith("links-valid-until-") for ph in ("select", "folder", "vault")
                                         for x in lk_all[ph]["files"])
                and all(x.startswith("links-valid-while-logged-in.") for x in lk_all["proxied"]["files"]))
    ctx.check(LINKS, ok and names_ok and lk_all["vault"]["open"]["ok"] and lk_all["vault"].get("stale_backup", {}).get("ok")
              and lk_all["proxied"]["open"]["ok"],
              **{ph: {k: v for k, v in x.items() if k != "html_path"} for ph, x in lk_all.items()})


async def _switch(ctx, world: _UiWorld, setup, phase_run, settled, disk_ok) -> None:
    """A fresh browser on A: Download whole vault (`phase_run`), B picked in the creator column mid-run (A's CDN
    held after SWITCH_FREE fetches, declared), released once B is on screen; A's run must still finish every file."""
    from slop.actors import ui

    vw, a, b, nick = world.vw, world.a, world.b, world.nick
    every = vw.vault(a)["media"]
    creator = _safe(nick[a])
    hold = _Hold(a, SWITCH_FREE)

    def row(page, aid: str):
        """aid's row in the creator column (as ui.pick_creator finds it)."""
        rows = page.get_by_test_id("of-creator-column").get_by_test_id("of-creator-row")
        return rows.filter(has=page.get_by_text(nick[aid], exact=True)).first

    async def during(page, panel) -> dict:
        o: dict = {}
        try:   # mid-flight: SWITCH_FREE through, the next held
            await asyncio.wait_for(hold.first_held.wait(), 60)
        except asyncio.TimeoutError:
            raise RuntimeError(f"switch: none of A's CDN fetches was held within 60 s ({hold.passed} let through)") from None
        o["held_before_switch"] = hold.held
        o["before"] = await _card(panel)
        await ui.pick_creator(page, nick[b], timeout_ms=WAIT_MS)   # waits for B's row to be aria-current
        newest_b = vw.listing(b)[0]["id"]
        await page.locator(f"section [title^='#{newest_b} ']").first.wait_for(timeout=WAIT_MS)
        o["b_grid"] = {"b_current": await row(page, b).get_attribute("aria-current"),
                       "a_current": await row(page, a).get_attribute("aria-current"), "b_newest_tile": newest_b}
        btn = page.get_by_role("button", name="Download whole vault")
        o["b_download"] = {"disabled": await btn.is_disabled(timeout=10_000),
                           "title": await btn.get_attribute("title", timeout=10_000)}
        o["at_switch"] = await _card(panel)
        o["trigger_shot"] = await ui.shot(ctx, page, "vault-download-switch-trigger")
        hold.go.set()
        return o

    d: dict = {"free": SWITCH_FREE}
    try:
        async with ui.owner_browser(ctx, viewport=VIEWPORT, through=(LISTS_PATH, MEDIA_PATH)) as page:
            try:
                await setup(page, a, hold)
                hold.armed = True
                d.update(await phase_run(
                    "switch", page, a, every, None,
                    lambda: page.get_by_role("button", name="Download whole vault").click(timeout=10_000),
                    during=during))
            finally:
                hold.go.set()
            d.update(held=hold.held, held_dropped=hold.dropped)
    except Exception as e:  # noqa: BLE001 — the check reports it
        d.setdefault("error", f"{type(e).__name__}: {e}"[:600])
    d.pop("browser_by_key", None)
    p, sw = d.get("panel") or {}, d.get("at_switch") or {}
    parts = {
        "browser": "error" not in d,
        "running_at_switch": bool(d.get("held_before_switch")) and (d.get("before") or {}).get("phase") == "running"
                             and sw.get("phase") == "running" and sw.get("title") == f"Downloading {creator}: whole vault",
        "b_shown": d.get("b_grid", {}).get("b_current") == "true" and d.get("b_grid", {}).get("a_current") is None,
        "b_download_off": d.get("b_download") == {"disabled": True, "title": BUSY_OFF},
        "panel_done": settled(d, len(every)) and p.get("title") == f"Downloaded {creator}: whole vault",
        "disk": "disk" in d and disk_ok(d),
    }
    ctx.check(SWITCH, all(parts.values()), failed=[k for k, ok in parts.items() if not ok], parts=parts, **d)


async def _phone(ctx, vw, b: str, peg: str, port: int, assets: dict) -> None:
    """The phone sink on B (proxied: relay only): the 20 cap and the mode reasons, then a selection shared in batches."""
    from slop.actors import ui

    ms = vw.listing(b)
    vids = [m for m in ms if m["type"] == "video"][1:3]   # not the newest: PROXIED's
    photos = [m for m in ms if m["type"] == "photo"][3:6]
    sel = photos + vids
    big = {_key(b, m): PHONE_VIDEO_MB << 20 for m in vids}
    await arm_run(ctx.owner, ctx.stack.tmp, assets, CDN_LATENCY_S, mp4_sizes=big)
    browser_cdn: list[dict] = []
    cap: dict = {}
    d: dict = {"selected": [m["id"] for m in sel], "videos": [m["id"] for m in vids]}

    async def tick(page, mids) -> None:
        for mid in mids:
            t = page.locator(f"section [title^='#{mid} ']").first
            await t.scroll_into_view_if_needed(timeout=10_000)
            await t.tap(timeout=10_000)

    async def dl_state(page) -> dict:
        btn = page.get_by_role("button", name="Download selected")
        off = page.get_by_test_id("download-off")
        bar = page.locator("div", has=btn).filter(has_text="Selected").last
        count = await bar.evaluate("(el) => el.querySelector('div span:nth-child(2)')?.textContent ?? ''")
        return {"count": count, "enabled": await btn.is_enabled(),
                "reason": (await off.inner_text()) if await off.count() else ""}

    async with ui.owner_browser(ctx, viewport=PHONE_VIEWPORT, through=(LISTS_PATH, MEDIA_PATH), touch=True) as page:
        try:
            await page.context.add_init_script(SHARE_JS)
            await _open_vault(ctx, page, b, port, browser_cdn)
            cap["picker"] = await page.evaluate("typeof window.showDirectoryPicker")
            await page.get_by_role("button", name="Select", exact=True).tap(timeout=10_000)
            await page.get_by_role("button", name="Select all").tap(timeout=10_000)
            await page.get_by_role("button", name="Download selected").wait_for(timeout=10_000)
            cap["all"] = await dl_state(page)
            vault_btn = page.get_by_role("button", name="Download whole vault")
            cap["vault"] = {"enabled": await vault_btn.is_enabled(), "title": await vault_btn.get_attribute("title")}
            cap["shot"] = await ui.shot(ctx, page, "vault-download-phone-cap")
            await page.get_by_role("button", name="Clear").tap(timeout=10_000)
            await tick(page, [m["id"] for m in ms[:PHONE_MAX]])
            cap["twenty"] = await dl_state(page)
            await tick(page, [ms[PHONE_MAX]["id"]])
            cap["twentyone"] = await dl_state(page)
            await page.get_by_role("button", name="Clear").tap(timeout=10_000)
            row = page.locator("aside [role='button']").filter(has_text=vw.vault(b)["folders"][0]["name"]).first
            await row.scroll_into_view_if_needed(timeout=10_000)
            await row.get_by_role("button", name="More").tap(timeout=10_000)
            item = page.get_by_role("menuitem", name=re.compile(r"^Download folder"))
            cap["folder"] = {"label": await item.inner_text(), "enabled": await item.is_enabled(),
                             "title": await item.get_attribute("title")}
            await row.get_by_role("button", name="More").tap(timeout=10_000)   # closes the menu
        except Exception:  # noqa: BLE001 — the check reports it
            async with captured(ctx, page, cap, "failed-vault-download-phone-cap"):
                raise
        ok = "error" not in cap
        ctx.check(PHONE_CAP, ok and cap["picker"] == "undefined"
                  and int(cap["all"]["count"] or 0) > PHONE_MAX and not cap["all"]["enabled"]
                  and cap["all"]["reason"] == PHONE_COUNT_OFF
                  and cap["twenty"] == {"count": str(PHONE_MAX), "enabled": True, "reason": ""}
                  and cap["twentyone"] == {"count": str(PHONE_MAX + 1), "enabled": False, "reason": PHONE_COUNT_OFF}
                  and cap["vault"] == {"enabled": False, "title": PHONE_MODE_OFF}
                  and cap["folder"]["enabled"] is False and cap["folder"]["title"] == PHONE_MODE_OFF, **cap)

        n0, s0 = await cdn_count(ctx), len(page.slop["statuses"])
        try:
            await tick(page, [m["id"] for m in sel])
            d["trigger_shot"] = await ui.shot(ctx, page, "vault-download-phone-trigger")
            await page.get_by_role("button", name="Download selected").tap(timeout=10_000)
            panel = page.locator(PANEL)
            links = page.get_by_test_id("dl-save-links")
            save = page.get_by_test_id("dl-save")
            await save.wait_for(timeout=WAIT_MS)
            # Save links before any media share (tapped once the big fetches are in, outside their streams)
            d["links_shot"] = await ui.shot(ctx, page, "vault-download-phone-links")
            await links.tap(timeout=10_000)
            await links.wait_for(state="detached", timeout=10_000)   # linksSaved: the button goes
            d["first_label"] = await save.inner_text()
            d["ready_title"] = await panel.locator("div.font-medium").first.inner_text()
            d["ready_shot"] = await ui.shot(ctx, page, "vault-download-phone-ready")
            await page.evaluate("window.__slopShare.abortNext = true")
            await save.tap(timeout=10_000)
            await page.wait_for_timeout(500)
            d["after_dismiss"] = {"visible": await save.is_visible(), "label": await save.inner_text()}
            labels, t0 = [], time.time()
            while time.time() - t0 < SETTLE_S:
                if await panel.get_attribute("data-phase") == "done" and await panel.get_attribute("data-unsaved") == "0":
                    break
                if await save.count() and await save.is_visible():
                    lab = await save.inner_text()
                    labels.append(lab)
                    await save.tap(timeout=10_000)
                    t1 = time.time()   # until this batch leaves (the label changes or the button goes)
                    while time.time() - t1 < 30 and await save.count() and await save.inner_text() == lab:
                        await asyncio.sleep(0.1)
                else:
                    await asyncio.sleep(0.25)
            d["labels"] = labels
            d["panel"] = {k: await panel.get_attribute(f"data-{k}") for k in
                          ("phase", "total", "done", "failed", "relay", "direct", "batches", "saved", "unsaved")}
            d["settled_shot"] = await ui.shot(ctx, page, "vault-download-phone-settled")
        except Exception:  # noqa: BLE001
            async with captured(ctx, page, d, "failed-vault-download-phone"):
                raise
        share = await page.evaluate("window.__slopShare")
        statuses = page.slop["statuses"][s0:]
    calls = await cdn_calls(ctx, n0)
    served = {c["key"]: c["bytes"] for c in calls if c["status"] == 200}
    want = {f"{m['id']}.{'mp4' if m['type'] == 'video' else 'jpg'}":
            ["video/mp4", served.get(_key(b, m), -1)] if m["type"] == "video" else ["image/jpeg", m["sizes"][1]]
            for m in sel}
    is_links = [all(_is_links(f["name"]) for f in c["files"]) for c in share["calls"]]
    lcalls = [c for c, k in zip(share["calls"], is_links) if k]
    share["calls"] = [c for c, k in zip(share["calls"], is_links) if not k]   # the media batches
    shared = [f for c in share["calls"] for f in c["files"]]
    got = Counter(f["name"] for f in shared)
    d["shared"] = {"calls": [[f["name"] for f in c["files"]] for c in share["calls"]],
                   "active": [c["active"] for c in share["calls"]], "dismissed": len(share["dismissed"]),
                   "twice": sorted(k for k, n in got.items() if n > 1), "missing": sorted(set(want) - set(got)),
                   "stray": sorted(set(got) - set(want)),
                   "bad": [[f["name"], f["type"], f["size"], want.get(f["name"])] for f in shared
                           if want.get(f["name"]) != [f["type"], f["size"]]]}
    d["video_bytes"] = {k: served.get(k) for k in big}
    d["browser_cdn"] = len([c for c in browser_cdn if f"/files/v/{b}/" in c["key"]])
    d["relay_cdn_egress"] = sorted({c["egress"] for c in calls if c.get("ua") != "slop-browser"
                                    and c["key"] in {_key(b, m) for m in sel}})
    d["http_5xx"] = [[st, u] for st, u in statuses if st >= 500][:10]
    p = d.get("panel") or {}
    sh = d["shared"]
    n = len(sel)
    lf = {f["type"]: f for c in lcalls for f in c["files"]}
    lt, lh = lf.get("text/plain") or {}, lf.get("text/html") or {}
    pl: dict = {"calls": len(lcalls), "first": bool(is_links) and is_links[0], "active": [c["active"] for c in lcalls],
                "names": sorted(f["name"] for c in lcalls for f in c["files"])}
    if lt.get("text") and lh.get("text"):
        pl.update(_links(lt["text"], lh["text"], b, sel, False, ctx.app))
        (ctx.out / "links-phone.txt").write_text(lt["text"])
        (ctx.out / "links-phone.html").write_text(lh["text"])
    ctx.check(PHONE_LINKS, "error" not in d and pl["calls"] == 1 and pl["first"] and pl["active"] == [True]
              and pl["names"] == ["links-valid-while-logged-in.html", "links-valid-while-logged-in.txt"]
              and "lines" in pl and _links_ok(pl, False), **pl)
    batches = int(p.get("batches") or 0)
    parts = {
        "browser": "error" not in d,
        "selection": len(vids) == 2 and len(photos) == 3,
        "video_size": len(d["video_bytes"]) == 2 and all(v == PHONE_VIDEO_MB << 20 for v in d["video_bytes"].values()),
        "panel_done": p.get("phase") == "done" and p.get("total") == str(n) and p.get("done") == str(n),
        "panel_counts": p.get("failed") == "0" and p.get("relay") == str(n) and p.get("unsaved") == "0",
        "batches": batches >= 2 and p.get("batches") == p.get("saved") and len(sh["calls"]) == batches,
        "activation": all(a is True for a in sh["active"]),
        "files": not sh["twice"] and not sh["missing"] and not sh["stray"] and not sh["bad"],
        "dismiss": str(d.get("ready_title", "")).startswith("Ready to save") and sh["dismissed"] == 1
                   and d.get("after_dismiss") == {"visible": True, "label": d.get("first_label")},
        "network": d["browser_cdn"] == 0 and d["relay_cdn_egress"] == [peg] and not d["http_5xx"],
    }
    ctx.check(PHONE_SHARE, all(parts.values()), failed=[k for k, ok in parts.items() if not ok], parts=parts, **d)
