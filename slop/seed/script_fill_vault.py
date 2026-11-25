from __future__ import annotations

import io
import json
import random
from datetime import timedelta
from pathlib import Path

from . import World, ts

SEQUENCE = "Slop Fill S1"
SHORT_SEQUENCE = "Slop Fill Short"
A_BASE, C_BASE = 7_210_000_000, 7_230_000_000
CLIP_LIST = 7701
FOLDER_CENTS = 9900
REVIEW_KEY = "vault_standard:photo:uncategorised"
JEV_V, JEV_VV = "v8+nn.10", "jv1"  # service/vault_jev_rules.VERSION / VIDEO_VERSION
HELD = "fetch_failed"
M30 = "qwen3-vl-30b"
STEPS_A = {1: ("1/3, freebie", "hey babe here's a little something", 0),
           3: ("1/3, ppv", "wanna see more? 😈", 0),
           5: ("2/3", "sending you 2 pics 🙈", 2500),
           7: ("3/3, ppv", "the full video, all of me", 0)}
STEPS_B = {1: STEPS_A[1], 3: ("1/3, ppv", STEPS_A[3][1], 1500), 5: ("2/3", STEPS_A[5][1], 3000), 7: STEPS_A[7]}
SHORT_STEPS = {1: ("1/2, freebie", "a little gift for you", 0), 2: ("2/2, ppv", "unlock this one 😈", 0)}
LAST_STEP = 13
SHORT_FREE = 2
SHORT_JEV = ("vulva", "vulva", "vulva", "nipple", "nipple", "nipple")
SOLO = {"people_count": 1, "partner_visible": False}
PARTNER = {"people_count": 2, "partner_visible": True}


def _flags(vulva: str, breasts: str, *, underwear: bool = True, ov: str = "", ob: str = "") -> dict:
    out = {"underwear_visible": underwear, "vulva_vis": vulva, "breasts_vis": breasts, "anus_vis": "not_in_frame"}
    if ov:
        out["over_vulva"] = ov
    if ob:
        out["over_breasts"] = ob
    return out


TIERS = {
    "sfw": {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
            **_flags("covered", "covered", ov="jeans", ob="t-shirt")},
    "suggestive": {"clothing_state": "lingerie_on", "acts": ["posing"], "penetration": "none",
                   "explicitness": "suggestive", **_flags("covered", "covered", ov="panties", ob="bra")},
    "explicit": {"clothing_state": "fully_nude", "acts": ["posing"], "penetration": "none",
                 "explicitness": "explicit", **_flags("bare", "bare", underwear=False)},
}


def _jev(lane: str, kind: str, bare: str) -> dict:
    j = {"v": JEV_V, "status": "ok", "lane5": lane, "state": {}, "kind": kind, "breasts_bare": bare,
         "crotch_bare": bare, "penetration": "n", "tags": {}}
    if kind == "video":
        j.update(vv=JEV_VV, frames=[])
    return j


def fields(tier: str, kind: str = "photo", lane: str = "$10", colour: str = "white", people: dict = SOLO) -> dict:
    return {**TIERS[tier], "clothing_items": [f"{colour} bra"], **people,
            "_jev": _jev(lane, kind, "y" if tier == "explicit" else "n")}


def _held(f: dict) -> dict:
    j = f["_jev"]
    return {**f, "_jev": {**j, "status": HELD, "lane5": "review", "read_lane5": j["lane5"], "review": HELD,
                          "retries": 3, "error": "slop: source fetch failed"}}


def _item(aid: str, mid: int, kind: str, at, role: str, f: dict | None, folders=()) -> dict:
    return {"account_id": aid, "media_id": mid, "kind": kind, "duration": 12 if kind == "video" else None,
            "created_at": at, "role": role, "fields": f, "of_folders": [str(x) for x in folders],
            "size": (400, 400), "url": None, "outcome": None, "jev": None}


def vault_a(aid: str, t0) -> list[dict]:
    spec = ([(1, "sfw", "photo", "free"), (2, "sfw", "photo", "free"), (3, "sfw", "photo", "free")]
            + [(n, "suggestive", "photo", "$10") for n in (4, 5, 6, 7)] + [(8, "suggestive", "video", "$50")]
            + [(n, "explicit", "photo", "$50") for n in (9, 10, 11, 12)] + [(13, "explicit", "video", "$50")])
    out = [_item(aid, A_BASE + n, kind, t0 + timedelta(minutes=n), "free" if lane == "free" else "paid",
                 fields(tier, kind, lane), (CLIP_LIST,) if n == 13 else ())
           for n, tier, kind, lane in spec]
    out.append(_item(aid, A_BASE + 14, "video", t0 + timedelta(minutes=14), "partner",
                     fields("explicit", "video", "$50", people=PARTNER)))
    out.append(_item(aid, A_BASE + 15, "photo", t0 + timedelta(minutes=15), "held",
                     _held(fields("explicit", "photo", "$50"))))
    out.append(_item(aid, A_BASE + 16, "photo", t0 + timedelta(minutes=16), "review_folder",
                     fields("explicit", "photo", "$50")))
    return out


def vault_c(aid: str, t0, profiles) -> list[dict]:
    out = [_item(aid, C_BASE + n, "photo", t0 + timedelta(minutes=n), "short_free", fields("sfw", lane="free",
                                                                                          colour="red"))
           for n in range(1, SHORT_FREE + 1)]
    for k, prof in enumerate(profiles):
        n = SHORT_FREE + 1 + k
        it = _item(aid, C_BASE + n, "photo", t0 + timedelta(minutes=n), "short_new", None)
        it.update(outcome="ok", jev=prof)
        out.append(it)
    return out


def sequence_rows(aid: str, script: str, steps: dict, at, last: int = LAST_STEP) -> list[dict]:
    out = []
    for step in range(1, max([last, *steps]) + 1):
        notes, text, price = steps.get(step, (f"{step}/{last}, bridge", "how's your day going?", 0))
        out.append({"account_id": aid, "script_id": script, "script_step": step, "text": text, "notes": notes,
                    "price_cents": price, "media_json": "[]", "previews_json": "[]", "tagged_users_json": "[]",
                    "tags_json": "[]", "locked_text": 0, "created_at": at, "updated_at": at})
    return out


def plan(w: World, creators: list[dict]) -> dict:
    if len(creators) < 3:
        raise ValueError(f"slop: script_fill_vault needs 3 Creators, the profile made {len(creators)}")
    rng = w.rng("script_fill_vault")
    a, b, c = (creators[i]["id"] for i in range(3))
    t0 = w.now - timedelta(days=30)
    profiles = list(SHORT_JEV)
    rng.shuffle(profiles)
    va, vc = vault_a(a, t0), vault_c(c, t0, profiles)
    at = ts(w.now - timedelta(days=7))
    out = {"a": a, "b": b, "c": c, "items": va + vc,
           "fillable": [it["media_id"] for it in va if it["role"] in ("free", "paid")],
           "decoys": {it["role"]: it["media_id"] for it in va if it["role"] not in ("free", "paid")},
           "rows": {a: sequence_rows(a, SEQUENCE, STEPS_A, at), b: sequence_rows(b, SEQUENCE, STEPS_B, at),
                    c: sequence_rows(c, SHORT_SEQUENCE, SHORT_STEPS, at, last=len(SHORT_STEPS))},
           "short_new": [it for it in vc if it["role"] == "short_new"]}
    w.data["script_fill_vault"] = out
    return out


def _cdn(aid: str, mid: int) -> str:
    return f"https://cdn2.onlyfans.com/files/slop/{aid}/{mid}"


def _jpeg(wh, rgb) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", tuple(wh), rgb).save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _thumb(seed: str) -> bytes:
    from PIL import Image
    r = random.Random(seed)
    g = Image.new("L", (9, 8))
    g.putdata([r.randrange(256) for _ in range(72)])
    buf = io.BytesIO()
    g.resize((300, 300), Image.NEAREST).convert("RGB").save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def of_media(it: dict) -> dict:
    cdn = _cdn(it["account_id"], it["media_id"])
    return {"id": it["media_id"], "type": it["kind"], "createdAt": it["created_at"].isoformat() + "+00:00",
            "isReady": True, "hasError": False, "canView": True, "duration": it["duration"] or 0,
            "files": {"thumb": {"url": f"{cdn}_thumb.jpg"}, "preview": {"url": f"{cdn}_preview.jpg"}}}


async def seed(w: World, armed: dict) -> dict:
    d = w.data["script_fill_vault"]
    dirs = {k: Path(v) for k, v in armed["dirs"].items()}
    now = ts(w.now)
    con = w.sql()
    with con:
        for it in d["items"]:
            aid, mid = it["account_id"], it["media_id"]
            cols = {"account_id": aid, "media_id": mid, "kind": it["kind"], "duration_seconds": it["duration"],
                    "width": it["size"][0], "height": it["size"][1], "thumb_url": f"{_cdn(aid, mid)}_thumb.jpg",
                    "tags": "[]", "send_count": 0, "raw_json": json.dumps(of_media(it)),
                    "of_folder_ids": json.dumps(it["of_folders"]), "created_at": ts(it["created_at"]),
                    "updated_at_of": it["created_at"].isoformat() + "+00:00", "updated_at": now}
            if it["fields"] is not None:
                cols.update(describe_status="described", describe_model=M30, describe_generated_at=now,
                            explicitness_tier=it["fields"]["explicitness"], ai_fields_json=json.dumps(it["fields"]))
            else:
                for k, data in (("images", _jpeg(it["size"], (mid % 200 + 30, (mid // 7) % 200 + 30, 120))),
                                ("thumbs", _thumb(f"script-fill:{aid}:{mid}"))):
                    (dirs[k] / aid).mkdir(parents=True, exist_ok=True)
                    (dirs[k] / aid / f"{mid}.jpg").write_bytes(data)
            con.execute(f"INSERT INTO vault_items ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        tuple(cols.values()))
        a = d["a"]
        con.execute("INSERT INTO vault_folder_prices (account_id, folder_ref, price_cents) VALUES (?,?,?)",
                    (a, f"of:{CLIP_LIST}", FOLDER_CENTS))
        con.execute("INSERT INTO vault_account_settings (account_id, folder_price_final, standard_folders, "
                    "updated_at) VALUES (?,0,1,?)", (a, now))
        fid = con.execute("INSERT INTO vault_folders (account_id, name, of_list_id, created_by, created_at) "
                          "VALUES (?,?,?,?,?)", (a, "Uncategorised / Needs Review", None, REVIEW_KEY, now)).lastrowid
        con.execute("INSERT INTO vault_folder_items (account_id, folder_id, media_id, added_at) VALUES (?,?,?,?)",
                    (a, fid, d["decoys"]["review_folder"], now))
        for aid, rows in d["rows"].items():
            for r in rows:
                con.execute(f"INSERT INTO saved_replies ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                            tuple(r.values()))
    con.close()
    return d
