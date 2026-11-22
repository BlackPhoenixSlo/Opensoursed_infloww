"""service/tests/_script_fill_fixtures.py — vault rows and Sequences for the Fill route suites
(`test_script_fill_api`, `test_script_fill_lock_hold`). Field shapes are `test_script_fill_decide`'s (described,
solo, rung-placed, a Jev reading), written as `vault_items` / `saved_replies` rows.

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap `_harness` FIRST, then import this.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import insert

import vault_ai_brief
import vault_dupes
import vault_jev_flags
import vault_jev_rules
from db.engine import get_session
from db.models import SavedReply, VaultFolderPrice, VaultItem

T0 = datetime(2026, 7, 1)


def _jev(lane: str, kind: str = "photo", bare: str = "n") -> dict[str, Any]:
    j = {"v": vault_jev_rules.VERSION, "status": "ok", "lane5": lane, "state": {}, "kind": kind,
         "breasts_bare": bare, "crotch_bare": bare, "penetration": "n", "tags": {}}
    if kind == "video":
        j.update(vv=vault_jev_rules.VIDEO_VERSION, frames=[])
    return j


def _flags(vulva: str, breasts: str, *, underwear: bool = True, ov: str = "", ob: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"underwear_visible": underwear, "vulva_vis": vulva, "breasts_vis": breasts,
                           "anus_vis": "not_in_frame"}
    if ov:
        out["over_vulva"] = ov
    if ob:
        out["over_breasts"] = ob
    return out


SOLO = {"people_count": 1, "partner_visible": False}
TIERS = {
    "sfw": {"clothing_state": "dressed", "acts": ["posing"], "penetration": "none", "explicitness": "sfw",
            **_flags("covered", "covered", ov="jeans", ob="t-shirt")},
    "suggestive": {"clothing_state": "lingerie_on", "acts": ["posing"], "penetration": "none",
                   "explicitness": "suggestive", **_flags("covered", "covered", ov="panties", ob="bra")},
    "explicit": {"clothing_state": "fully_nude", "acts": ["posing"], "penetration": "none",
                 "explicitness": "explicit", **_flags("bare", "bare", underwear=False)},
}


def fields(tier: str, kind: str = "photo", lane: str = "$10", colour: str = "white") -> dict[str, Any]:
    raw = {**TIERS[tier], "clothing_items": [f"{colour} bra"], **SOLO,
           vault_jev_rules.JEV_KEY: _jev(lane, kind, "y" if tier == "explicit" else "n")}
    if lane in vault_jev_rules.PAID:   # the flags + tier the mapper writes a paid lane, never sfw / suggestive (W30 D1)
        m = vault_jev_flags.apply(raw, raw[vault_jev_rules.JEV_KEY])
        raw.update({k: m[k] for k in ("explicitness", "breasts_vis", "vulva_vis", "anus_vis")})
    return vault_ai_brief.settled_reading(raw)


def _hash(n: int) -> str:
    h = hashlib.sha256(str(n).encode()).digest()
    return vault_dupes.pack_hash(h[:16].hex(), int.from_bytes(h[16:24], "big"), int.from_bytes(h[24:32], "big"))


def vault_row(account_id: str, mid: int, tier: str, kind: str = "photo", lane: str = "$10",
              colour: str = "white", *, created_at: datetime | None = None, dupe_of: int | None = None,
              folders: Iterable[str] = (), **kw: Any) -> dict[str, Any]:
    """One `vault_items` row (core insert values). `dupe_of`: an exact copy of that media id (same
    content hash, so `vault_dupes.find_duplicates` sets them together)."""
    row = {"account_id": account_id, "media_id": mid, "kind": kind,
           "created_at": created_at or T0 + timedelta(minutes=mid),
           "duration_seconds": 12 if kind == "video" else None,
           "thumb_url": f"https://cdn.example/{account_id}/{mid}_t.jpg", "tags": "[]", "send_count": 0,
           "ai_fields_json": json.dumps(fields(tier, kind, lane, colour)), "describe_status": "described",
           "of_folder_ids": json.dumps(list(folders)), "content_hash": _hash(dupe_of if dupe_of else mid)}
    row.update(kw)
    return row


def shoot(account_id: str, base: int, colour: str = "white", *, at: datetime | None = None) -> list[dict[str, Any]]:
    """`test_script_fill_decide`'s WHITE Shoot at ids base+1..base+13: 3 free-safe sfw photos, 4 suggestive
    $10 photos, a suggestive clip, 4 explicit $50 photos, an explicit clip."""
    t = at or T0
    spec = ([(1, "sfw", "photo", "free"), (2, "sfw", "photo", "free"), (3, "sfw", "photo", "free")]
            + [(n, "suggestive", "photo", "$10") for n in (4, 5, 6, 7)] + [(8, "suggestive", "video", "$50")]
            + [(n, "explicit", "photo", "$50") for n in (9, 10, 11, 12)] + [(13, "explicit", "video", "$50")])
    return [vault_row(account_id, base + n, tier, kind, lane, colour, created_at=t + timedelta(minutes=n))
            for n, tier, kind, lane in spec]


async def insert_vault(rows: list[dict[str, Any]], prices: dict[tuple[str, str], int] | None = None) -> None:
    async with get_session() as s:
        for at in range(0, len(rows), 500):
            await s.execute(insert(VaultItem), rows[at:at + 500])
        for (acct, ref), cents in (prices or {}).items():
            s.add(VaultFolderPrice(account_id=acct, folder_ref=ref, price_cents=cents))
        await s.commit()


# Issue 07's typical shape (`test_script_fill_decide.S1`): a freebie, three paid Steps between bridges, the
# last a clip. {step: (notes, text, price)}; every other step 1..13 is a bridge.
S1 = {1: ("1/3, freebie", "hey babe here's a little something", 0),
      3: ("1/3, ppv", "wanna see more? 😈", 0),
      5: ("2/3", "sending you 2 pics 🙈", 0),
      7: ("3/3, ppv", "the full video, all of me", 0)}


def sequence_rows(account_id: str, script: str, steps: dict[int, tuple[str, str, int]],
                  last: int = 13) -> list[dict[str, Any]]:
    out = []
    for step in range(1, max([last, *steps]) + 1):
        notes, text, price = steps.get(step, (f"{step}/13, bridge", "how's your day going?", 0))
        out.append({"account_id": account_id, "script_id": script, "script_step": step, "text": text,
                    "notes": notes, "price_cents": price, "media_json": "[]", "previews_json": "[]",
                    "tagged_users_json": "[]", "tags_json": "[]", "locked_text": False,
                    "created_at": T0, "updated_at": T0})
    return out


async def insert_sequence(rows: list[dict[str, Any]]) -> None:
    async with get_session() as s:
        await s.execute(insert(SavedReply), rows)
        await s.commit()
