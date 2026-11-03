"""Chat media: photo messages in existing threads (seed/threads.py) and their `message_media` rows, as the
transcoder (`messages.media_ids` / `media_count`) and `messages.reconcile_rest_media` (thumb_url / source_url from
OF's `files.thumb.url` / `files.full.url`, dims) leave them. Used by scenarios/2026-11-02-img-chat-media.py.

`seed(w, n_assets)`: about `n_assets` CDN assets (each photo = a thumb + its full source) over 3-6 photos per chat in
1-3 messages, older than the thread's history (ids below threads.HISTORY_ID_BASE, so `chats.last_message_id` stays
right). Chats are `fresh` (OF's URLs signed until w.now + 6 h) or `stale` (~10% of photos, at least one chat: their
Policy expired 2 h ago, what a chat not re-listed since leaves). Fresh photos: ~15% on `public.onlyfans.com`
(unsigned, img_api's direct lane), the rest on synthetic `cdn2/cdn3.onlyfans.com` with Policy / Signature /
Key-Pair-Id; max(2, photos // 25) fresh signed sources are > 2 MiB (never disk-cached). Ids are synthetic
(messages 8_900_000_000_000+, media 900_000_000+); randomness only from w.rng("chat_media").

`rotate(w, data)`: OF re-signed every fresh signed URL (a REST refresh's `reconcile_rest_media` overwrote
thumb_url / source_url): same host + path, new Policy / Signature. Returns the new URLs by asset key.

Output (`w.data["chat_media"]`): {chats: [{account_id, fan_id, stale, media: [{media_id, message_id, thumb, source}]}],
assets: {"host/path": {host, path, size, sha256, account_id, media_id, variant, big, direct, stale, url}}}.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta, timezone

from slop.lib.img_relay import asset_bytes, signed

from . import World, threads, ts

MSG_ID_BASE = 8_900_000_000_000   # < threads.HISTORY_ID_BASE: these photos are older than the thread's lines
MEDIA_ID_BASE = 900_000_000
SIGNED_HOSTS = ("cdn2.onlyfans.com", "cdn3.onlyfans.com")
DIRECT_HOST = "public.onlyfans.com"
KEY_PAIR_ID = "SLOPKEYPAIRID0"
MAX_CACHE = 2 * 1024 * 1024       # img_api._IMG_CACHE_MAX_BYTES
THUMB = (6_000, 30_000)
SOURCE = (40_000, 250_000)
BIG = (2_200_000, 3_200_000)
STALE_FRAC, DIRECT_FRAC = 0.10, 0.15
assert threads.HISTORY_ID_BASE > MSG_ID_BASE + 10_000_000


def sign(host: str, path: str, exp_epoch: int, gen: int = 0) -> str:
    """`host/path` as OF hands it out: the signed hosts with a CloudFront-style query, the direct one bare."""
    if not signed(host):
        return f"https://{host}{path}"
    policy = base64.urlsafe_b64encode(json.dumps({"exp": exp_epoch}).encode()).decode().rstrip("=")
    sig = hashlib.sha256(f"slop:{path}:{exp_epoch}:{gen}".encode()).hexdigest()[:40]
    return f"https://{host}{path}?Policy={policy}&Signature={sig}&Key-Pair-Id={KEY_PAIR_ID}"


def _epoch(dt) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def seed(w: World, n_assets: int) -> dict:
    rng = w.rng("chat_media")
    names = {f["id"]: f["name"] for fl in w.data["fans"].values() for f in fl}
    n_photos = max(8, int(n_assets) // 2)
    n_stale = max(3, int(n_photos * STALE_FRAC))
    pool = rng.sample(w.data["threads"], len(w.data["threads"]))
    fresh_exp, stale_exp = _epoch(w.now + timedelta(hours=6)), _epoch(w.now - timedelta(hours=2))
    chats, assets, mrows, mmrows = [], {}, [], []
    mid, media_id, done = MSG_ID_BASE, MEDIA_ID_BASE, 0
    for t in pool:
        if done >= n_photos:
            break
        stale = done < n_stale
        aid, fan = t["account_id"], t["fan_id"]
        t0 = t["last_at"] - timedelta(minutes=7 * (t["msgs"] - 1))
        chat = {"account_id": aid, "fan_id": fan, "stale": stale, "media": []}
        left = min(rng.randint(3, 6), n_photos - done)
        k = 0
        while left > 0:
            per = min(left, rng.randint(1, 3))
            mid += 1
            k += 1
            inbound = rng.random() < 0.4
            at = t0 - timedelta(minutes=11 * k)
            ids = []
            for _ in range(per):
                media_id += 1
                direct = not stale and rng.random() < DIRECT_FRAC
                host = DIRECT_HOST if direct else rng.choice(SIGNED_HOSTS)
                h = hashlib.sha1(f"slop-media:{media_id}".encode()).hexdigest()[:32]
                urls = {}
                for variant, (lo, hi) in (("thumb", THUMB), ("source", SOURCE)):
                    path = f"/files/{h[0]}/{h[:2]}/{h}/{variant}_960x1280.jpg"
                    key = f"{host}{path}"
                    urls[variant] = key
                    assets[key] = {"host": host, "path": path, "size": rng.randint(lo, hi), "account_id": aid,
                                   "media_id": media_id, "variant": variant, "big": False, "direct": direct,
                                   "stale": stale, "url": sign(host, path, stale_exp if stale else fresh_exp)}
                ids.append(media_id)
                chat["media"].append({"media_id": media_id, "message_id": mid, **urls})
            mrows.append((aid, fan, mid, "in" if inbound else "out", names.get(fan, "fan") if inbound else aid, "",
                          json.dumps(ids), len(ids), 0, 0, None, None, ts(at), ts(at)))
            left -= per
            done += per
        chats.append(chat)
    big_pool = [a for a in assets.values() if a["variant"] == "source" and not a["direct"] and not a["stale"]]
    for a in rng.sample(big_pool, min(len(big_pool), max(2, n_photos // 25))):
        a.update(big=True, size=rng.randint(*BIG))
    for a in assets.values():
        assert (a["size"] > MAX_CACHE) == a["big"], a
        a["sha256"] = hashlib.sha256(asset_bytes(f"{a['host']}{a['path']}", a["size"])).hexdigest()
    for c in chats:
        for m in c["media"]:
            th, src = assets[m["thumb"]], assets[m["source"]]
            mmrows.append((c["account_id"], c["fan_id"], m["message_id"], m["media_id"], "photo", 960, 1280,
                           th["url"], src["url"], ts(w.now), ts(w.now)))
    con = w.sql()
    with con:
        con.executemany(
            "INSERT INTO messages(account_id, fan_id, message_id, direction, sender_name, body, media_ids, media_count, "
            "price_cents, is_paid, is_tip, purchased_at, is_unsent, is_promise, sent_by_employee_id, created_at, "
            "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0,0,?,?,?)", mrows)
        con.executemany(
            "INSERT INTO message_media(account_id, fan_id, message_id, media_id, type, width, height, thumb_url, "
            "source_url, duration_ms, ingested_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?)", mmrows)
    con.close()
    out = {"chats": chats, "assets": assets}
    w.data["chat_media"] = out
    return out


def rotate(w: World, data: dict) -> dict[str, str]:
    """OF re-signed every fresh signed URL (module docstring): the message_media rows a REST refresh rewrites."""
    exp = _epoch(w.now + timedelta(hours=7))
    new = {k: sign(a["host"], a["path"], exp, gen=1) for k, a in data["assets"].items()
           if not a["stale"] and signed(a["host"])}
    rows = [(new.get(m["thumb"]), new.get(m["source"]), ts(w.now), c["account_id"], c["fan_id"], m["message_id"],
             m["media_id"]) for c in data["chats"] if not c["stale"] for m in c["media"]]
    con = w.sql()
    with con:
        con.executemany(
            "UPDATE message_media SET thumb_url = COALESCE(?, thumb_url), source_url = COALESCE(?, source_url), "
            "updated_at = ? WHERE account_id = ? AND fan_id = ? AND message_id = ? AND media_id = ?", rows)
    con.close()
    return new
