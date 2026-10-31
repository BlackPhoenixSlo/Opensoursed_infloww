"""Fan facts/notes, nickname push and template placeholders."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime

from db.engine import get_session
from db.models import Fan
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

log = logging.getLogger("of-relay.automation.common")


_FACTS_NOTE_MAX = 200


def build_facts_note(facts: dict, max_len: int = _FACTS_NOTE_MAX,
                     short_bio: str = "") -> str:
    """Compact, useful-first fact line built from a fan's extracted facts.

    Shared by apply_profiles (→ fans.applied_notes / the drawer) and fan_data
    (→ the User data bullet_points column) so the note and that column NEVER drift. Order is
    most-useful-first with SHORT labels, ONE FACT PER LINE: Recent → Intr (hobbies)
    → Job → Rel → Kinks, then the short_bio appended at the BOTTOM. EMPTY fields are
    skipped entirely (never a bare "Job:" line). Name, age and location are omitted
    (they live in the nickname) and lifetime spend too (the sheet prints it), so
    nothing is duplicated. Deterministic; whole-fact BULLETS are kept-or-skipped by
    budget, then the short_bio fills the remaining space and the whole note is
    hard-cut at max_len (the bio may be cut mid-sentence). '' when nothing is known.

    `facts` keys (all optional, str): hobbies, job, relationship, fetishes, and
    recent_events (a JSON-array TEXT value or a plain string). `short_bio` is the
    fan's one-line bio, appended last (lowest priority).
    """
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
            continue                            # skip empty fields entirely
        piece = f"{label}: {val}"
        add = (1 if out else 0) + len(piece)   # "\n" separator (one fact per line)
        if used + add > max_len:
            continue                            # skip; a shorter later fact may fit
        out.append(piece)
        used += add
    # short_bio at the BOTTOM, lowest priority: fill whatever budget the whole-fact
    # bullets left and HARD-CUT the whole note at max_len. Unlike the bullets (which
    # are kept whole or skipped), the bio may be cut mid-sentence — the rule is simply
    # "bullets, then bio, up to max_len chars".
    bio = (short_bio or "").strip()
    if bio:
        out.append(bio)
    return "\n".join(out)[:max_len]


# ── R2: the APP-ONLY rich note ───────────────────────────────────────
# The OF note is capped at 200 (build_facts_note above, pushed by apply_profiles /
# welcome_chatter_for_info). Our UI can show much more. build_rich_note is a SEPARATE,
# app-only projection that reads the STORED gen_info bullet_points (the rich text that
# actually carries the "Important:" section — the fan_data rebuild drops it) plus
# the short_bio, and caps by the fan's spend tier (higher spend ⇒ longer). It is NEVER
# pushed to OnlyFans and never fed to build_facts_note. Drawer + stats table only.
_RICH_NOTE_TIERS = (        # (min lifetime cents, char cap)
    (50000, 3000),          # whale ≥ $500
    (5000, 1500),           # spender ≥ $50
    (1, 800),               # buyer > $0
    (0, 400),               # free $0
)


def rich_note_cap(lifetime_spend_cents: int) -> int:
    """The app-side rich-note length cap for a fan, by spend tier (higher = longer)."""
    cents = int(lifetime_spend_cents or 0)
    for floor, cap in _RICH_NOTE_TIERS:
        if cents >= floor:
            return cap
    return _RICH_NOTE_TIERS[-1][1]


def build_rich_note(bullet_points: str | None, short_bio: str = "",
                    lifetime_spend_cents: int = 0) -> str:
    """The app-only rich note: the STORED bullet_points (kept whole — it already holds
    Recent/Intr/Important/Job/Rel/Kinks from gen_info) followed by the short_bio, hard-cut
    at the fan's spend-tier cap. '' when nothing is stored. The structured facts
    (employer/pets/…) are shown as their own cells in the drawer, so they're not
    duplicated here."""
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
    """The fact dict `build_facts_note` consumes, lifted off a Fan row."""
    return {
        "hobbies": f.hobbies or "",
        "job": f.occupation or "",
        "relationship": getattr(f, "relationship_status", "") or "",
        "fetishes": f.fetishes or "",
        "recent_events": f.recent_events or "[]",
    }


async def push_nick_and_notes(client, account_id: str, fan_id: int, *,
                              nick: str = "", notes: str = "") -> tuple[bool, bool]:
    """Push the custom nickname (displayName — ANY fan) and/or note (notice —
    SUBSCRIBERS only) to OF via of_client, then MIRROR what stuck into the local
    columns the UI reads (`fans.custom_nickname` / `fans.notes`). SEPARATE OF calls
    so a non-subscriber note 404 can't swallow the nickname. of_client is sync →
    off-thread. Best-effort: each push failure is logged and swallowed. Returns
    (nick_pushed, note_pushed)."""
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
    """Fill `{name}`/`{city}`/`{age}`/`{hobby}`/`{pet}` in a template line from a
    Fan row (nudge_online tease/qa pools). Used so the variation arrays can carry
    natural personalization without each automation re-deriving it.

    `fan` may be a Fan ORM row, a dict of the same fields, or None. `name` overrides
    the {name} value (callers pass the already-resolved real first name); when it's
    empty/None we fall back to a soft 'babe' rather than leaving a hole like
    'morning sleepyhead  ☀️'. Unknown placeholders are left untouched. An EMPTY
    fact (no city/pet/…) collapses its placeholder to '' (the surrounding copy is
    written to read fine without it)."""
    def _get(attr: str) -> str:
        if fan is None:
            return ""
        if isinstance(fan, dict):
            return str(fan.get(attr) or "").strip()
        return str(getattr(fan, attr, "") or "").strip()

    # {hobby}: first comma/semicolon-separated hobby. {pet}: first pet name from the
    # JSON pets array (falls back to the kind, e.g. 'dog').
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
    for k, v in repl.items():
        if k in out:
            out = out.replace(k, v)
    # Tidy any double spaces left by an empty fact, but keep newlines.
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def template_fan_name(fan) -> str | None:
    """The `{name}` a Smart Messages text (purchase_followup, the lifecycle
    messages) greets a Fan row by: his real first name when it is known real,
    else his chosen nickname, else None (`substitute_placeholders` then says
    "babe")."""
    if fan is None:
        return None
    if fan.real_name and fan.is_name_real:
        return fan.real_name.split()[0]
    return fan.fan_chosen_nickname or None
