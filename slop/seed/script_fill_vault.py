"""Vaults and Sequences for Growth > Scripts' "Fill with content" (scenarios/2026-11-21-script-fill.py), by SQL, in two
steps around the scenario's arms of lib/vault_describe_relay.py and lib/vault_jev_relay.py (the short vault's
undescribed photos need the outcome files and the still stores the arm answers):

  plan(w, creators)   the items and rows below, in memory (`w.data["script_fill_vault"]`).
  seed(w, armed)      writes them: `vault_items`, `vault_folders` + `vault_folder_items` (the standard REVIEW
                      folder), `vault_folder_prices` (the OF list price), `vault_account_settings` (Creator A's
                      standard folders on), `saved_replies`; and each undescribed photo's still
                      (`IMAGE_DIR/<acct>/<id>.jpg`, its planned pixel size) and 300px grid thumb (`THUMB_DIR`).

Three Creators of the profile (agency_inbox small has 3), one Agency:
  A  creators[0]  the Fill Creator. Sequence SEQUENCE (STEPS_A, steps 1..13, the rest bridges): step 1 freebie,
     step 3 ppv (no price), step 5 "2 pics" at a saved (Fixed) $25, step 7 ppv clip (no price). Vault: one WHITE
     Shoot every item of which is Fillable, as service/tests/_script_fill_fixtures.py `shoot` writes it (described,
     solo readings `people_count` 1 / `partner_visible` false, Rungs sfw / suggestive / explicit, a current Jev
     reading per item): 3 free-safe sfw stills (Jev lane free), 4 suggestive $10 photos, a suggestive clip, 4
     explicit $50 photos and an explicit clip in OF list CLIP_LIST, whose folder price is FOLDER_CENTS. Then the
     decoys, same Shoot (same outfit, minutes later) and each the highest media id of its kind, so each ranks
     first (sorts last, the payoff end) wherever its Rung ties: a partner explicit clip (`people_count` 2,
     `partner_visible` true: not solo), a Jev-held explicit photo (`_jev` review fetch_failed, as
     `vault_jev_pass.held_blob` leaves one: lane5 review, read_lane5 $50) and an explicit photo in the standard
     REVIEW folder (`vault_standard:photo:uncategorised`, standard folders on).
  B  creators[1]  the same-named SEQUENCE (STEPS_B: same texts, saved prices on steps 3 and 5), no vault: the
     Agency's template prices for A (step 3's $15) and the isolation subject (its rows must stay byte-equal).
  C  creators[2]  the short vault. Sequence SHORT_SEQUENCE (a freebie, one ppv step) over SHORT_FREE described
     free-safe stills and SHORT_NEW photos never described (no AI fields), each with a Jev answer the scenario
     arms (SHORT_JEV, shuffled by `w.rng`): a bare vulva ($50) or topless ($10), so the describe sweep turns them
     into paid solo items through the fakes and the Fill plan goes from not_enough_content to ok.

Every row is one the product writes (a collect, a describe, a Scripts edit, a folder price, a vault switch).
Randomness only from `w.rng("script_fill_vault")`.

Output `w.data["script_fill_vault"]`: {"a", "b", "c": Creator ids; "items": [item]; "fillable": [A's Fillable
media ids]; "decoys": {role: media id}; "rows": {aid: [saved_replies row dicts, insert order]}; "short_new":
[C's undescribed items]}. An item: account_id, media_id, kind, duration, created_at (datetime), role (free |
paid | partner | held | review_folder | short_free | short_new), fields (None: undescribed), of_folders, size,
url (None), outcome ("ok" for short_new, the describe fake's answer), jev (short_new's profile, else None).
"""
from __future__ import annotations

import io
import json
import random
from datetime import timedelta
from pathlib import Path

from . import World, ts

SEQUENCE = "Slop Fill S1"          # A's and B's same-named Sequence
SHORT_SEQUENCE = "Slop Fill Short"  # C's
A_BASE, C_BASE = 7_210_000_000, 7_230_000_000
CLIP_LIST = 7701                   # A's OF list holding the explicit clip
FOLDER_CENTS = 9900                # its folder price (vault_folder_prices "of:7701")
REVIEW_KEY = "vault_standard:photo:uncategorised"   # vault_standard_rules.key("photo", REVIEW)
JEV_V, JEV_VV = "v8+nn.10", "jv1"  # service/vault_jev_rules.VERSION / VIDEO_VERSION
HELD = "fetch_failed"              # service/vault_jev_rules.HELD
M30 = "qwen3-vl-30b"
# {step: (notes, text, saved price cents)}; every other step 1..13 is a bridge.
STEPS_A = {1: ("1/3, freebie", "hey babe here's a little something", 0),
           3: ("1/3, ppv", "wanna see more? 😈", 0),
           5: ("2/3", "sending you 2 pics 🙈", 2500),
           7: ("3/3, ppv", "the full video, all of me", 0)}
STEPS_B = {1: STEPS_A[1], 3: ("1/3, ppv", STEPS_A[3][1], 1500), 5: ("2/3", STEPS_A[5][1], 3000), 7: STEPS_A[7]}
SHORT_STEPS = {1: ("1/2, freebie", "a little gift for you", 0), 2: ("2/2, ppv", "unlock this one 😈", 0)}
LAST_STEP = 13
SHORT_FREE = 2
SHORT_JEV = ("vulva", "vulva", "vulva", "nipple", "nipple", "nipple")   # lib/vault_jev_relay.py PROFILES
SOLO = {"people_count": 1, "partner_visible": False}
PARTNER = {"people_count": 2, "partner_visible": True}


def _flags(vulva: str, breasts: str, *, underwear: bool = True, ov: str = "", ob: str = "") -> dict:
    out = {"underwear_visible": underwear, "vulva_vis": vulva, "breasts_vis": breasts, "anus_vis": "not_in_frame"}
    if ov:
        out["over_vulva"] = ov
    if ob:
        out["over_breasts"] = ob
    return out


# The three Rungs' readings (service/tests/_script_fill_fixtures.py TIERS): each agrees with its flags, so
# `settled_reading` leaves it as it is.
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
    """One described item's `ai_fields_json` (the fixture's `fields`, unsettled: it needs no settling)."""
    return {**TIERS[tier], "clothing_items": [f"{colour} bra"], **people,
            "_jev": _jev(lane, kind, "y" if tier == "explicit" else "n")}


def _held(f: dict) -> dict:
    """`f` with its `_jev` held as `vault_jev_pass.held_blob(terminal=False)` leaves a failed $50 reading."""
    j = f["_jev"]
    return {**f, "_jev": {**j, "status": HELD, "lane5": "review", "read_lane5": j["lane5"], "review": HELD,
                          "retries": 3, "error": "slop: source fetch failed"}}


def _item(aid: str, mid: int, kind: str, at, role: str, f: dict | None, folders=()) -> dict:
    return {"account_id": aid, "media_id": mid, "kind": kind, "duration": 12 if kind == "video" else None,
            "created_at": at, "role": role, "fields": f, "of_folders": [str(x) for x in folders],
            "size": (400, 400), "url": None, "outcome": None, "jev": None}


def vault_a(aid: str, t0) -> list[dict]:
    """Creator A's vault (module docstring): the WHITE Shoot at A_BASE+1..13, then the decoys at +14..16."""
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
    """Creator C's short vault: SHORT_FREE described free-safe stills, then one undescribed photo per profile."""
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
    """A Sequence's `saved_replies` rows, step 1..`last` (the fixture's `sequence_rows`)."""
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
    """A 300px 9x8 grey-grid tile from `seed`, as seed/vault_items_describe.py draws them (no near copies)."""
    from PIL import Image
    r = random.Random(seed)
    g = Image.new("L", (9, 8))
    g.putdata([r.randrange(256) for _ in range(72)])
    buf = io.BytesIO()
    g.resize((300, 300), Image.NEAREST).convert("RGB").save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def of_media(it: dict) -> dict:
    """The item in OnlyFans' vault shape (`raw_json`; lib/of_wire.py's vault page answers the same)."""
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
            if it["fields"] is not None:   # described by an earlier sweep
                cols.update(describe_status="described", describe_model=M30, describe_generated_at=now,
                            explicitness_tier=it["fields"]["explicitness"], ai_fields_json=json.dumps(it["fields"]))
            else:                          # collected, never described: the describe sweep's stills
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
