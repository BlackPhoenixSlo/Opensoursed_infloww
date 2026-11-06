"""OnlyFans' vault at its wire, for the vault flows (scenarios/2026-11-05-vault-collect.py, 2026-11-05-vault-thumbs.py,
2026-11-05-vault-refresh.py). Installs into lib/of_wire.FakeOF through its one generic hook, `extra_routes`,
so the built-in vault routes stay as other scenarios knew them.

Each Creator's vault is made on first sight of its `User-ID` (deterministic from `seed` + the id), so it is
served before the Creator exists in the DB: the background collector may reach OF the moment a session file
lands. A vault: `items` media (k = 0 newest; ~80% photo, ~20% video; createdAt one hour apart back from
install time), FOLDERS custom folders; each item sits in 0-2 of them (OF's `listStates[]`, `hasMedia`), and
every folder holds >= 1 item. `sizes` (uid -> items) overrides `items` per Creator. `add(uid, name, k)` is a
change made on OnlyFans now: a new folder holding k new media, created now (the newest).

  GET /api2/v2/vault/lists        offset/limit (OF's default 10); the folders, hasMore.
  GET /api2/v2/vault/media        list ("all" or a folder id) / type (photo|video|gif, omitted = all) /
                                  sort (asc|desc by createdAt, id) / offset / limit (default 24); list, hasMore.
  GET /api2/v2/vault/media/{id}   that media with FRESH signatures (a new `gen`, exp now + SIGN_TTL_S); 404 unknown.

Media urls: `files.{thumb,full}.url` on cdn2.onlyfans.com, path /files/v/<uid>/<mid>/{thumb,full}.jpg,
signed by seed/chat_media.sign (CloudFront-style Policy exp + gen), so lib/img_relay.py's fake CDN 403s an
expired or unsigned one. `assets()` is the CDN asset table for `img_relay.arm_run`. Listings carry the urls
of the Creator's current gen with exp = now + SIGN_TTL_S; `rotate(uid)` bumps the gen (OF re-signing: every
url string changes, the media does not).

`ip_bound` (off by default): every url OF answers is signed for the egress the request came through
(`AWS:SourceIp` = lib/proxy_wire.egress_of: a proxy's "127.0.0.1:<port>" or "direct"), as OF's are; the fake CDN
then 403s it through any other egress. `of_media(..., egress=)` signs for a given one (SQL seeding: what an
earlier proxy listed). `mp4` (off by default): each video also carries `videoSources["240"]`, a playable 12 s
clip at /files/v/<uid>/<mid>/240p.mp4 (in `assets()`; lib/img_relay.video_bytes), for /img/scrub and the player.
`gifs` (uid -> item indexes k, set before that Creator's vault is first made): those items are gifs, as OF stores
one (service/tests/fixtures/of_media_shapes.json): `files.full` a .mp4 (/files/v/<uid>/<mid>/gif.mp4, the same
clip), the thumb a jpg, no videoSources; the item's other draws are unchanged, so the rest of the vault is too.

Records (fake.vault_calls, arrival order after the fake's latency): {t, account, route ("lists" | "media" |
"by_id"), query (the parsed query string, one value per key; by_id: {"id": ...}), status, egress}. fake.calls
gets them too (h._record).

Bypasses (declared): media is never DRM (no poster frames); no audio; folder names are made up;
OF's `counters` / per-folder counts are omitted (the relay never reads them on these paths).
"""
from __future__ import annotations

import random
import re
import time
import zlib
from datetime import datetime, timezone
from urllib.parse import parse_qs

from slop.lib.proxy_wire import egress_of
from slop.seed.chat_media import sign

HOST = "cdn2.onlyfans.com"
FOLDERS = 6
SIGN_TTL_S = 6 * 3600
THUMB_SIZE, FULL_SIZE = (6_000, 20_000), (60_000, 200_000)
_BY_ID = re.compile(r"/api2/v2/vault/media/(\d+)")
_NAMES = ("Beach", "Gym", "Customs", "Lingerie", "Selfies", "B-roll", "Shower", "Outfits", "Bed", "Teasers")


def media_id(uid: str, k: int) -> int:
    return 4_000_000_000_000 + (zlib.crc32(uid.encode()) % 1_000_000) * 100_000 + k


def folder_id(uid: str, j: int) -> int:
    return 3_000_000_000 + (zlib.crc32(uid.encode()) % 1_000_000) * 100 + j


def path(uid: str, mid: int, variant: str) -> str:
    return f"/files/v/{uid}/{mid}/{variant}.{'mp4' if variant in ('240p', 'gif') else 'jpg'}"


def owner_of(key: str) -> tuple[str, int, str] | None:
    """CDN key "host/files/v/<uid>/<mid>/<variant>.jpg" -> (uid, mid, variant), else None."""
    m = re.fullmatch(r"[^/]+/files/v/([^/]+)/(\d+)/(\w+)\.jpg", key)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class VaultWire:
    def __init__(self, fake, *, seed: int, items: int, folders: int = FOLDERS, sizes: dict[str, int] | None = None,
                 ip_bound: bool = False, mp4: bool = False):
        self.fake, self.seed, self.items, self.folders = fake, seed, items, folders
        self.ip_bound, self.mp4 = ip_bound, mp4
        self.sizes = dict(sizes or {})
        self.gifs: dict[str, set[int]] = {}
        self.t0 = int(time.time())
        self.gen: dict[str, int] = {}
        self._v: dict[str, dict] = {}
        fake.vault_calls = []
        fake.extra_routes.append(self.handle)

    # ── the vault ──
    def vault(self, uid: str) -> dict:
        """{"folders": [OF list item], "media": [{id, type, created, folders: [ids], sizes}] newest first}."""
        v = self._v.get(uid)
        if v is None:
            rng = random.Random(f"vault_wire:{self.seed}:{uid}")
            fids = [folder_id(uid, j) for j in range(self.folders)]
            media = []
            for k in range(self.sizes.get(uid, self.items)):
                inn = rng.sample(fids, rng.choice((0, 0, 1, 1, 1, 2)))
                if k < len(fids):  # every folder holds at least one item
                    inn = sorted(set(inn) | {fids[k]})
                kind = "video" if rng.random() < 0.2 else "photo"
                media.append({"id": media_id(uid, k), "type": "gif" if k in self.gifs.get(uid, ()) else kind,
                              "created": self.t0 - (k + 1) * 3600, "folders": inn,
                              "sizes": (rng.randint(*THUMB_SIZE), rng.randint(*FULL_SIZE))})
            names = rng.sample(_NAMES, self.folders)
            folders = [{"id": f, "type": "custom", "name": names[j], "hasMedia": True, "canUpdate": True,
                        "canDelete": True, "medias": []} for j, f in enumerate(fids)]
            v = self._v[uid] = {"folders": folders, "media": media, "by_id": {m["id"]: m for m in media}}
        return v

    def of_media(self, uid: str, m: dict, *, exp: int | None = None, gen: int | None = None,
                 egress: str | None = None) -> dict:
        """The media dict OF answers (vault_mirror.row_values' input); `egress` its SourceIp (ip_bound only)."""
        exp = exp if exp is not None else int(time.time()) + SIGN_TTL_S
        gen = self.gen.get(uid, 0) if gen is None else gen
        ip = egress if self.ip_bound else None
        names = {f["id"]: f["name"] for f in self.vault(uid)["folders"]}
        url = {v: sign(HOST, path(uid, m["id"], v), exp, gen, ip) for v in ("thumb", "full")}
        if m["type"] == "gif":
            url["full"] = sign(HOST, path(uid, m["id"], "gif"), exp, gen, ip)
        vid = m["type"] == "video"
        return {"id": m["id"], "type": m["type"], "createdAt": _iso(m["created"]), "isReady": True,
                "hasError": False, "canView": True, "convertedToVideo": False,
                **({"duration": 12} if vid else {}),
                **({"videoSources": {"240": sign(HOST, path(uid, m["id"], "240p"), exp, gen, ip), "720": None}}
                   if vid and self.mp4 else {}),
                "files": {"thumb": {"url": url["thumb"], "width": 300, "height": 300},
                          "full": {"url": url["full"], "width": 960, "height": 1280}},
                "listStates": [{"id": f, "type": "custom", "name": names[f], "hasMedia": True,
                                "canAddMedia": True} for f in m["folders"]]}

    def assets(self, uids) -> dict:
        """img_relay.arm_run's table: {"host/path": {"size": n}} for every thumb and full of these Creators."""
        out = {}
        for uid in uids:
            for m in self.vault(uid)["media"]:
                out[f"{HOST}{path(uid, m['id'], 'thumb')}"] = {"size": m["sizes"][0]}
                out[f"{HOST}{path(uid, m['id'], 'full')}"] = {"size": m["sizes"][1]}
                if self.mp4 and m["type"] == "video":
                    out[f"{HOST}{path(uid, m['id'], '240p')}"] = {"size": m["sizes"][1]}  # size ignored: a clip
                if m["type"] == "gif":
                    out[f"{HOST}{path(uid, m['id'], 'gif')}"] = {"size": m["sizes"][1]}  # size ignored: a clip
        return out

    def add(self, uid: str, name: str, k: int) -> tuple[dict, list[dict]]:
        """Made on OnlyFans now: folder `name` holding `k` new media (photos), created now, one second apart.
        Returns (the folder's OF list item, the new media oldest first)."""
        v = self.vault(uid)
        rng = random.Random(f"vault_wire:add:{self.seed}:{uid}:{len(v['media'])}")
        folder = {"id": folder_id(uid, len(v["folders"])), "type": "custom", "name": name, "hasMedia": True,
                  "canUpdate": True, "canDelete": True, "medias": []}
        now, n0 = int(time.time()), len(v["media"])
        news = [{"id": media_id(uid, n0 + i), "type": "photo", "created": now + i, "folders": [folder["id"]],
                 "sizes": (rng.randint(*THUMB_SIZE), rng.randint(*FULL_SIZE))} for i in range(k)]
        with self.fake.lock:
            v["folders"].append(folder)
            v["media"][:0] = reversed(news)   # newest first
            v["by_id"].update({m["id"]: m for m in news})
        return folder, news

    def rotate(self, uid: str) -> int:
        self.gen[uid] = self.gen.get(uid, 0) + 1
        return self.gen[uid]

    def newest(self, uid: str, n: int) -> list[int]:
        return [m["id"] for m in self.vault(uid)["media"][:n]]

    def listing(self, uid: str, *, list_id=None, type_=None, sort="desc") -> list[dict]:
        ms = self.vault(uid)["media"]
        if list_id not in (None, "all"):
            ms = [m for m in ms if int(list_id) in m["folders"]]
        if type_ and type_ != "all":
            ms = [m for m in ms if m["type"] == type_]
        return sorted(ms, key=lambda m: (m["created"], m["id"]), reverse=(sort != "asc"))

    # ── the wire ──
    def _rec(self, uid, route, query, status, egress) -> None:
        with self.fake.lock:
            self.fake.vault_calls.append({"t": time.time(), "account": uid, "route": route,
                                          "query": query, "status": status, "egress": egress})

    def handle(self, h, method, u, uid, route, raw) -> bool:
        if method != "GET" or not u.path.startswith("/api2/v2/vault/"):
            return False
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        eg = egress_of(h.client_address[1])
        if u.path == "/api2/v2/vault/lists":
            off, lim = int(q.get("offset") or 0), int(q.get("limit") or 10)
            fs = self.vault(uid)["folders"]
            self._rec(uid, "lists", q, 200, eg)
            h._record(uid, route, 200, {"list": fs[off:off + lim], "hasMore": off + lim < len(fs)})
            return True
        if u.path == "/api2/v2/vault/media":
            off, lim = int(q.get("offset") or 0), int(q.get("limit") or 24)
            ms = self.listing(uid, list_id=q.get("list"), type_=q.get("type"), sort=q.get("sort") or "desc")
            self._rec(uid, "media", q, 200, eg)
            h._record(uid, route, 200, {"list": [self.of_media(uid, m, egress=eg) for m in ms[off:off + lim]],
                                        "hasMore": off + lim < len(ms)})
            return True
        bm = _BY_ID.fullmatch(u.path)
        if bm:
            m = self.vault(uid)["by_id"].get(int(bm.group(1)))
            self._rec(uid, "by_id", {"id": int(bm.group(1))}, 200 if m else 404, eg)
            if m is None:
                h._record(uid, route, 404, {"error": {"code": 0, "message": "Media not found"}})
            else:
                h._record(uid, route, 200, self.of_media(uid, m, gen=self.rotate(uid), egress=eg))
            return True
        return False
