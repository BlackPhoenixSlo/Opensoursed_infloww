"""Bio pages (ofl.ink ported, service/bio_pages on BIO_PORT): Profiles, their Links, domains and past daily counts.

SQL, as the PR2 editor will write them (product-writable rows only): per Creator `profiles` bio_profiles (owner = the
Agency's user, account_id = the Creator on even profiles, NULL on odd), each with `links` bio_links mixing modes,
18+, tracking and default codes, a geo rule on every 4th (a country's code, a country's region object, a default
only; those links carry the default code `geo`, as v2's editor stores it). Each destination holds a unique token
`slopdest-<p>-<l>` (p the profile's global index): the leak oracle. Every 3rd destination ends in `/`. One spare domain
SPARE; per Creator profile 0 has the live custom domain `c<i>.bio.slop.test` and profile 1 the pending
`c<i>p.bio.slop.test`. bio_daily: DAYS days (today included) of past views and clicks per profile. With `files_dir`
(the bio process's BIO_FILES_DIR) the first profile whose default mode is Escape Mode gets an avatar: a 512px WebP
made from the OF-mirror background image at AVATAR_SRC (its build-hash path must exist), written under files_dir
like an upload (the Escape Overlay's backdrop).

`w.data["bio_pages"]`: {profiles: [{id, username, gp, json (the exact Profile JSON bytes, built here, not by the
service), avatar (file name or ""), links: [{id, link_id, destination, geo, tracking, default, is_adult, mode}],
live, pending}], spare,
past: {(profile id, link row id or '', UTC day): (views, clicks)}}. Deterministic from the World's seed (stream
"bio_pages")."""
from __future__ import annotations

import io
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from PIL import Image

from . import World, merge_sizes, ts

SIZES = {
    "bio_pages_profiles": (2, 5, 20),      # per Creator
    "bio_pages_links": (6, 12, 12),        # per profile
    "bio_pages_visits": (600, 8_000, 30_000),
}
merge_sizes(SIZES)

SPARE = "spare.bio.slop.test"
DAYS = 7
MODES = ("direct", "escape_ig")
COUNTRIES = ("US", "DE", "GB", "BR")
REGIONS = ("CA", "TX", "NY", "")
IN_APP = ("", "", "instagram", "tiktok")
AVATAR_SRC = Path(__file__).resolve().parents[2] / "app/public/of-mirror/static/202610091632-c45cc0ac3f/img/background-call.png"
AVATAR_NAME = "avatar_slopseed01.webp"


def _code(rng) -> str:
    return str(rng.randint(1, 99_999))


def _geo(rng, k: int) -> dict:
    """The three rule shapes v2's editor stores: a country's code, a country's regions (+ default), a default only."""
    shape = k % 3
    if shape == 0:
        return {c: _code(rng) for c in rng.sample(COUNTRIES, 2)}
    if shape == 1:
        return {"US": {"CA": _code(rng), "TX": _code(rng), "default": _code(rng)}, "default": _code(rng)}
    return {"default": _code(rng)}


def _dumps(v) -> bytes:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode()


def _write_avatar(files_dir: Path, pid: str) -> None:
    buf = io.BytesIO()
    with Image.open(AVATAR_SRC) as source:
        im = source.convert("RGB")
    im.thumbnail((512, 512))
    im.save(buf, "WEBP", quality=80, method=4)
    d = files_dir / "profiles" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / AVATAR_NAME).write_bytes(buf.getvalue())


def seed(w: World, creators: list[dict], *, profiles: int, links: int, files_dir: Path | None = None) -> dict:
    rng = w.rng("bio_pages")
    out: dict = {"profiles": [], "spare": SPARE, "past": {}}
    prof_rows, link_rows, dom_rows = [], [], []
    gp = 0
    avatar_left = files_dir is not None
    for ci, c in enumerate(creators):
        for p in range(profiles):
            pid = f"bp{ci:03d}{p:010d}"
            username = f"slopbio{ci}_{p}"
            mode = rng.choice(MODES + ("", "legacy"))
            verified = p % 2 == 0
            display, bio = f"Slop Bio {gp}", f"Bio {gp} — café <&>"
            avatar = ""
            if avatar_left and mode != "direct":   # "", "legacy" and escape_ig all default to Escape Mode
                avatar, avatar_left = AVATAR_NAME, False
                _write_avatar(files_dir, pid)
            prof_rows.append((pid, w.user_id, c["id"] if p % 2 == 0 else None, username, display, bio, avatar, mode,
                              int(verified), ts(w.now - timedelta(days=30)), ts(w.now - timedelta(days=30))))
            pub_links, oracle_links = [], []
            for k in range(links):
                lid, key = f"bl{ci:03d}{p:04d}{k:06d}", f"k{ci:03d}{p:04d}{k:04d}"
                geo = _geo(rng, k // 4) if k % 4 == 3 else None
                tracking = geo is not None or k % 2 == 0
                default = "geo" if geo else rng.choice(("", "", _code(rng)))
                is_adult = k % 3 == 1
                lmode = rng.choice(MODES + ("",))
                dest = f"https://dest.slop.test/slopdest-{gp}-{k}" + ("/" if k % 3 == 2 else "")
                title = f"Link {gp}.{k}"
                link_rows.append((lid, pid, key, title, dest, default, lmode, json.dumps(geo) if geo else None,
                                  int(is_adult), int(tracking), float(k)))
                oracle_links.append({"id": lid, "link_id": key, "destination": dest, "geo": geo,
                                     "tracking": tracking, "default": default, "is_adult": is_adult,
                                     "title": title})
                pl = {"id": key, "title": title, "isAdult": is_adult, "tracking": tracking}
                if default:
                    pl["default_tracknumber"] = default
                pl.update({"mode": lmode if lmode in MODES else (mode if mode in MODES else "escape_ig"),
                           "icon": "", "backgroundImage": ""})
                pub_links.append(pl)
            body = {"profile": {"id": pid, "username": username, "displayName": display, "bio": bio,
                                "avatarUrl": f"/api/files/profiles/{pid}/{avatar}" if avatar else "",
                                "verified": verified, "mode": mode if mode in MODES else "escape_ig"},
                    "links": pub_links}
            live = f"c{ci}.bio.slop.test" if p == 0 else None
            pending = f"c{ci}p.bio.slop.test" if p == 1 else None
            if live:
                dom_rows.append((f"bd{ci:03d}{p:010d}", pid, live, "live"))
            if pending:
                dom_rows.append((f"bd{ci:03d}{p:010d}", pid, pending, "pending"))
            out["profiles"].append({"id": pid, "username": username, "gp": gp, "json": _dumps(body),
                                    "avatar": avatar, "links": oracle_links, "live": live, "pending": pending})
            gp += 1

    daily: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for prof in out["profiles"]:
        for d in range(DAYS):
            day = (w.now - timedelta(days=d)).strftime("%Y-%m-%d")
            for _ in range(rng.randint(1, 4)):
                daily[(day, prof["id"], "", rng.choice(COUNTRIES + ("XX",)), rng.choice(IN_APP), "")][0] += \
                    rng.randint(1, 40)
            for lk in rng.sample(prof["links"], min(3, len(prof["links"]))):
                code = lk["default"] if lk["default"].isdigit() else ""
                daily[(day, prof["id"], lk["id"], rng.choice(COUNTRIES), rng.choice(IN_APP), code)][1] += \
                    rng.randint(1, 20)
    for (day, pid, lid, *_), (v, k) in daily.items():
        prev = out["past"].get((pid, lid, day), (0, 0))
        out["past"][(pid, lid, day)] = (prev[0] + v, prev[1] + k)

    con = w.sql()
    try:
        with con:
            con.executemany("INSERT INTO bio_profiles(id, owner_user_id, account_id, username, display_name, bio, avatar,"
                            " mode, verified, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", prof_rows)
            con.executemany("INSERT INTO bio_links(id, profile_id, link_id, title, destination, default_tracking_code,"
                            " mode, geo, is_adult, tracking, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?)", link_rows)
            con.execute("INSERT INTO bio_spare_domains(id, domain) VALUES ('bs000000000000s', ?)", (SPARE,))
            con.executemany("INSERT INTO bio_custom_domains(id, profile_id, domain, status) VALUES (?,?,?,?)", dom_rows)
            con.executemany("INSERT INTO bio_daily(day, profile_id, link_id, country, in_app, code, views, clicks)"
                            " VALUES (?,?,?,?,?,?,?,?)", [(*key, v, k) for key, (v, k) in daily.items()])
    finally:
        con.close()
    w.data["bio_pages"] = out
    return out
