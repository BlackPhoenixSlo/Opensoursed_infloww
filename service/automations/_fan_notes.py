from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime

from db.engine import get_session
from db.models import Fan
from of_rich_text import is_of_html
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

log = logging.getLogger("of-relay.automation.common")


_FACTS_NOTE_MAX = 200


def build_facts_note(facts: dict, max_len: int = _FACTS_NOTE_MAX,
                     short_bio: str = "") -> str:
    f = facts or {}
    events = ""
    try:
        ev = json.loads(f.get("recent_events") or "[]")
        if isinstance(ev, list):
            events = "; ".join(str(x).strip() for x in ev if str(x).strip())
    except (json.JSONDecodeError, TypeError):
        events = (f.get("recent_events") or "").strip().strip("[]")
    candidates = [
        ("Recent", events),
        ("Intr", f.get("hobbies", "")),
        ("Job", f.get("job", "")),
        ("Rel", f.get("relationship", "")),
        ("Kinks", f.get("fetishes", "")),
    ]
    out: list[str] = []
    used = 0
    for label, val in candidates:
        val = (val or "").strip()
        if not val:
            continue
        piece = f"{label}: {val}"
        add = (1 if out else 0) + len(piece)
        if used + add > max_len:
            continue
        out.append(piece)
        used += add
    bio = (short_bio or "").strip()
    if bio:
        out.append(bio)
    return "\n".join(out)[:max_len]


# App-only: never pushed to OnlyFans (its note is capped at 200) and never fed to build_facts_note.
_RICH_NOTE_TIERS = (
    (50000, 3000),
    (5000, 1500),
    (1, 800),
    (0, 400),
)


def rich_note_cap(lifetime_spend_cents: int) -> int:
    cents = int(lifetime_spend_cents or 0)
    for floor, cap in _RICH_NOTE_TIERS:
        if cents >= floor:
            return cap
    return _RICH_NOTE_TIERS[-1][1]


def build_rich_note(bullet_points: str | None, short_bio: str = "",
                    lifetime_spend_cents: int = 0) -> str:
    cap = rich_note_cap(lifetime_spend_cents)
    parts = []
    bp = (bullet_points or "").strip()
    if bp:
        parts.append(bp)
    bio = (short_bio or "").strip()
    if bio and bio not in bp:
        parts.append(bio)
    return "\n\n".join(parts)[:cap]


def facts_from_fan(f: Fan) -> dict:
    return {
        "hobbies": f.hobbies or "",
        "job": f.occupation or "",
        "relationship": getattr(f, "relationship_status", "") or "",
        "fetishes": f.fetishes or "",
        "recent_events": f.recent_events or "[]",
    }


async def push_nick_and_notes(client, account_id: str, fan_id: int, *,
                              nick: str = "", notes: str = "") -> tuple[bool, bool]:
    nick_ok = note_ok = False
    if nick:
        try:
            await asyncio.to_thread(client.set_fan_custom_name, int(fan_id), nick)
            nick_ok = True
        except Exception:
            log.warning("push_nick_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
    if notes:
        try:
            await asyncio.to_thread(client.set_fan_note, int(fan_id), notes)
            note_ok = True
        except Exception as e:
            log.info("push_note_skipped account=%s fan=%s (%s)", account_id, fan_id,
                     type(e).__name__)
    mirror: dict = {}
    if nick_ok:
        mirror["custom_nickname"] = nick
    if note_ok:
        mirror["notes"] = notes
    if mirror:
        now = datetime.utcnow()
        mirror["updated_at"] = now
        async with get_session() as s:
            await s.execute(
                sqlite_insert(Fan)
                .values(account_id=str(account_id), fan_id=int(fan_id), **mirror)
                .on_conflict_do_update(index_elements=["account_id", "fan_id"], set_=mirror)
            )
    return nick_ok, note_ok


def substitute_placeholders(text: str, fan, *, name: str | None = None) -> str:
    def _get(attr: str) -> str:
        if fan is None:
            return ""
        if isinstance(fan, dict):
            return str(fan.get(attr) or "").strip()
        return str(getattr(fan, attr, "") or "").strip()

    hobby = ""
    raw_hobby = _get("hobbies")
    if raw_hobby:
        hobby = re.split(r"[,;\n]", raw_hobby)[0].strip()
    pet = ""
    raw_pets = _get("pets")
    if raw_pets and raw_pets not in ("[]", "{}"):
        try:
            arr = json.loads(raw_pets)
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                pet = str(arr[0].get("name") or arr[0].get("kind") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pet = ""

    nm = (name or "").strip() or "babe"
    repl = {
        "{name}": nm,
        "{city}": _get("home_city"),
        "{age}": _get("his_age"),
        "{job}": _get("occupation"),
        "{hobby}": hobby,
        "{pet}": pet,
    }
    out = text or ""
    markup = is_of_html(out)
    for k, v in repl.items():
        if k in out:
            out = out.replace(k, html.escape(v, quote=False) if markup else v)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def template_fan_name(fan) -> str | None:
    if fan is None:
        return None
    if fan.real_name and fan.is_name_real:
        return fan.real_name.split()[0]
    return fan.fan_chosen_nickname or None
