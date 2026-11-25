from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from db.models import (
    Blacklist, Fan, FollowupState, MassRun, SkipList, WelcomeSent, parse_ts,
)

if TYPE_CHECKING:
    from assistant_evidence_full_ai import FullAi

# No fan-written text ever enters the pack (prompt injection); custom_nickname is the one exception, via clean_label.
CAP_CHARS = 4000
TIMELINE_SCAN = 40
TIMELINE_LINES = 14
LABEL_CAP = 60
MAX_LISTS = 8
MAX_AUDIENCES = 3
# Consecutive same-engine rows closer than this are bubbles of ONE reply (the humanizer types 3-5 rows, seconds apart).
_BUBBLE_WINDOW = timedelta(minutes=2)

_FAN_HEADER = (
    "FAN EVIDENCE PACK (wins over the manual for this fan\'s facts).\n"
    "Two kinds of line follow, and the difference is the whole point.\n"
    "PROVEN = a stored row. State it as fact, with its stored reason and date.\n"
    "CURRENT-STATE = how things stand right now. It supports a RANKED "
    "HYPOTHESIS, never proof of what happened in the past.\n"
    "There is NO per-tick decision log in this product. Whether an engine "
    "looked at this fan on a given tick and chose silence is an INFERENCE from "
    "the rows below, and must be stated as one.")

# Presentation of the per-kind split only; the verdict comes from content_payer_fans.
CONTENT_TX_KINDS = ("ppv_message", "ppv_post", "tip")


class AudienceHome(NamedTuple):

    keys: frozenset[str]
    where: str
    nested_under: str | None = None


# WHITELIST: a payload also holds message text, vault ids, price ladders; an absent key means the engine's default, not "off".
_RULE_AUDIENCE = AudienceHome(frozenset({
    "excluded_user_lists", "excluded_users", "exclude_inbound_hours",
    "exclude_last_chat_hours", "exclude_list_ids", "exclude_replied_hours",
    "fan_ids", "filters", "included_users", "list_ids",
    "online_only", "recent_chat_hours", "recent_chat_limit", "unread_limit",
    "user_lists",
}), "the rule payload")

_AUDIENCE_HOMES: dict[str, AudienceHome] = {
    # mass_premade's payload is a LIST of premade messages, each carrying its own audience; the top level holds none.
    "mass_premade": AudienceHome(
        _RULE_AUDIENCE.keys, "the first premade message",
        nested_under="messages"),
}


# Rule kinds whose sends are tagged with a different automation_kind; every other one tags its own.
BEAT_TAG = {"send_followup": "followup", "send_welcome": "welcome"}

def audience_home(kind: str) -> AudienceHome:
    return _AUDIENCE_HOMES.get(kind, _RULE_AUDIENCE)


class Beat(NamedTuple):

    ts: datetime | None
    direction: str
    kind: str | None
    price_cents: int
    media_count: int
    mass_run_id: int | None
    is_tip: bool
    is_unsent: bool
    message_id: int | None
    count: int
    through: datetime | None


class Evidence(NamedTuple):

    account_id: str
    label: str | None
    fan: Fan
    skip: SkipList | None
    banned: Blacklist | None
    welcomed: WelcomeSent | None
    drip: FollowupState | None
    memberships: list[tuple[str, str, datetime]]
    rows: list
    paid_ids: set[int]
    runs: dict[int, MassRun]
    money: list[tuple[str, int, int]]
    missing: list[str]
    is_payer: bool
    muted_creator: bool
    audiences: list[tuple[str, str | None, bool]]
    audiences_other: bool
    full_ai: "FullAi | None" = None
    full_ai_failed: bool = False



def humanize(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 48 * 60:
        return f"{minutes // 60}h"
    return f"{minutes // (24 * 60)}d"


def clean_label(value: str | None) -> str:
    flat = " ".join((value or "").split())
    return flat[:LABEL_CAP]


def usd(cents: Any) -> str:
    return f"${int(cents or 0) / 100:,.2f}"


def at(ts: datetime | None) -> str:
    if ts is None:
        return "unknown time"
    stamp = f"{ts:%Y-%m-%d %H:%M:%S}"
    now = datetime.utcnow()
    # Future timestamps need their own branch: unclamped, a fan under a 7-day quarantine would read "(0m ago)".
    if ts > now:
        return f"{stamp} (in {humanize(int((ts - now).total_seconds() // 60))})"
    return f"{stamp} ({humanize(max(0, int((now - ts).total_seconds() // 60)))} ago)"



def _folds(last: Beat, row: Any, ts: datetime | None, window) -> bool:
    # Priced, tipped, broadcast or media rows never fold: the amount, run id or photo is itself the evidence.
    return (last.direction == row.direction
            and last.kind == row.automation_kind
            and last.price_cents == 0 and int(row.price_cents or 0) == 0
            and last.mass_run_id is None and row.mass_run_id is None
            and not last.is_tip and not row.is_tip
            and not last.media_count and not row.media_count
            and last.is_unsent == bool(row.is_unsent)
            and last.ts is not None and ts is not None
            and (last.ts - ts) <= window)


def collapse(rows: Iterable[Any]) -> list[Beat]:
    beats: list[Beat] = []
    for row in rows:
        ts = parse_ts(row.created_at)
        last = beats[-1] if beats else None
        if last is not None and _folds(last, row, ts, _BUBBLE_WINDOW):
            beats[-1] = last._replace(ts=ts, count=last.count + 1)
            continue
        beats.append(Beat(
            ts=ts, direction=row.direction, kind=row.automation_kind,
            price_cents=int(row.price_cents or 0),
            media_count=int(row.media_count or 0), mass_run_id=row.mass_run_id,
            is_tip=bool(row.is_tip), is_unsent=bool(row.is_unsent),
            message_id=row.message_id, count=1, through=ts))
    return beats


def beat_line(b: Beat, paid_ids: set[int],
              runs: dict[int, MassRun], fan_id: int | None = None) -> str:
    bits = [at(b.ts), {"in": "IN ", "out": "OUT"}.get(b.direction, "SYS")]
    bits.append(b.kind or ("fan" if b.direction == "in" else "human send"))
    if b.count > 1 and b.through is not None:
        bits.append(f"x{b.count} bubbles through {b.through:%H:%M:%S}")
    if b.is_tip:
        bits.append("TIP")
    if b.price_cents:
        bits.append(usd(b.price_cents))
    if b.media_count:
        bits.append(f"{b.media_count} media")
    if b.price_cents:
        # Purchase truth is the ledger: messages.is_paid is set on ~1.4% of priced sends.
        bits.append("PURCHASED" if b.message_id in paid_ids
                    else "no LINKED purchase row")
    if b.mass_run_id is not None:
        run = runs.get(b.mass_run_id)
        bits.append(f"mass_run {b.mass_run_id}"
                    + (f" [{mass_summary(run, fan_id)}]" if run is not None else ""))
    if b.is_unsent:
        bits.append("UNSENT since")
    return "  " + "  ".join(bits)


# included_users is the audience the engine already RESOLVED, never hand-picked ids; render as this fan's membership.
_RECIPIENT_LIST_KEYS = frozenset({"included_users", "fan_ids"})
_EXCLUSION_KEYS = frozenset({"excluded_users"})


def _is_id_list(value: Any, key: str = "") -> bool:
    # Shape OR key: operator-written payloads carry string ids ("123") that a shape-only test lets into the prompt.
    if not isinstance(value, list) or not value:
        return False
    if key in _RECIPIENT_LIST_KEYS or key in _EXCLUSION_KEYS:
        return True
    return all(isinstance(v, int) and not isinstance(v, bool) for v in value)


def _holds(ids: list, fan_id: int) -> bool:
    # Compare as str: 123 in ["123"] is False, yet string ids are an ordinary payload shape.
    want = str(fan_id)
    return any(str(i) == want for i in ids)


def _knob(key: str, value: Any, fan_id: int | None = None) -> str:
    if _is_id_list(value, key):
        n = len(value)
        if fan_id is not None and key in _RECIPIENT_LIST_KEYS:
            where = ("THIS FAN IS ON IT" if _holds(value, fan_id)
                     else "THIS FAN IS NOT ON IT")
            return f"{key}={n} recipients the run had already resolved — {where}"
        if fan_id is not None and key in _EXCLUSION_KEYS:
            where = "including this fan" if _holds(value, fan_id) else "not this fan"
            return f"{key}={n} ids held back ({where})"
        return f"{key}={n} ids"
    if isinstance(value, list) and len(value) > 4:
        return f"{key}=[{len(value)} entries]"
    return f"{key}={json.dumps(value)}"


_KNOB_BUDGET = 220


def _fit_knobs(audience: dict, fan_id: int | None = None) -> str:
    # Never slice a joined string (min_cents=5000 -> 50): drop whole knobs. Empties are kept: present-and-empty differs from never written.
    kept, used, dropped = [], 0, 0
    for k, v in sorted(audience.items()):
        knob = _knob(k, v, fan_id)
        if kept and used + len(knob) + 2 > _KNOB_BUDGET:
            dropped += 1
            continue
        kept.append(knob)
        used += len(knob) + 2
    if dropped:
        kept.append(f"(+{dropped} more knob(s) not shown)")
    return ", ".join(kept) if kept else "nothing set — engine defaults throughout"


def mass_summary(run: MassRun, fan_id: int | None = None) -> str:
    # "0 recipients" is a MISSING count (list-or-filter sends are resolved by OnlyFans), not nobody.
    bits = [run.automation_kind or "manual broadcast"]
    bits.append(f"{run.recipient_count} recipients" if run.recipient_count
                else "recipient count not recorded — a list/filter send is "
                     "resolved by OnlyFans, so we never counted it here")
    try:
        audience = json.loads(run.audience_filter or "{}")
    except (TypeError, ValueError):
        audience = None
    if isinstance(audience, dict) and audience:
        bits.append("audience at send time: " + _fit_knobs(audience, fan_id))
    return "; ".join(bits)


def audience_now(kind: str, raw: str | None, enabled: bool) -> str:
    home = audience_home(kind)
    where = home.where
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        payload = None
    if home.nested_under and isinstance(payload, dict):
        first = (payload.get(home.nested_under) or [None])[0]
        payload = first if isinstance(first, dict) else None
    if not isinstance(payload, dict):
        return (f"- {kind} audience as configured today: {where} is unreadable "
                f"(rule is {'on' if enabled else 'off'}).")
    parts = [_knob(k, payload[k]) for k in sorted(home.keys & set(payload))]
    return (f"- {kind} audience as configured today, from {where} "
            f"({'rule ON' if enabled else 'rule OFF'}): "
            + (", ".join(parts) if parts else
               "nothing set — every audience knob is on its engine default."))


def skip_line(skip: SkipList | None) -> str:
    if skip is None:
        return "- skip_list: no row."
    return (f"- skip_list: reason '{skip.reason or ''}', added {at(skip.added_at)} "
            "— the info-gather lane, Follow up quiet fans and Nudge Online read "
            "the skip list with NO reason filter, so this row stops all three. "
            "Auto-reply does not read it.")



def proven_lines(ev: Evidence) -> list[str]:
    # Order is cut order; skip_list leads because a lifted row named as the blocker is the one wrong answer to prevent.
    out = [skip_line(ev.skip)]
    out.append("- blacklist: no row." if ev.banned is None else
               f"- blacklist: BANNED GLOBALLY, reason '{ev.banned.reason}', "
               f"added {at(ev.banned.added_at)}. This applies across every "
               f"model.")
    if ev.memberships:
        # Bounded so a fan on thirty lists cannot push the thread out of the pack.
        for name, kind, added in ev.memberships[:MAX_LISTS]:
            out.append(f'- list membership: "{clean_label(name)}" (kind '
                       f"{kind}), added {at(added)}.")
        if len(ev.memberships) > MAX_LISTS:
            out.append(f"- list membership: and "
                       f"{len(ev.memberships) - MAX_LISTS} more, not shown.")
    else:
        out.append("- list membership: on no local list — not on an exclude "
                   "list, and not inside an include-only audience folder.")
    out.append("- welcome_sent: no row; he was never sent the welcome."
               if ev.welcomed is None else
               f"- welcome_sent: {at(ev.welcomed.sent_at)}.")
    out.append(
        "- followup_state: no row; the follow-up drip has never tracked him."
        if ev.drip is None else
        f"- followup_state: phase {ev.drip.phase}, cycle {ev.drip.cycle}, "
        f"completed={bool(ev.drip.completed)}, updated {at(ev.drip.updated_at)}.")
    out.append(
        "- ABSENCE IS EVIDENCE — this account has NO rule at all of these "
        "scheduled fan-facing kinds: "
        + ", ".join(k + (f' (its beats read "{BEAT_TAG[k]}")' if k in BEAT_TAG
                         else "") for k in ev.missing)
        + ". None of them reaches him FROM NOW ON; that says nothing about a "
        "send from before a rule was deleted, which only a beat in the thread "
        "tagged as listed above can show, and only if it is among the rows read."
        if ev.missing else
        "- every fan-facing kind has a rule row on this account; the LIVE "
        "STATE block says which of them are switched on.")
    out += _money_lines(ev)
    # Lazy: assistant_evidence_full_ai imports this module's formatting primitives.
    from assistant_evidence_full_ai import _full_ai_rows
    if ev.full_ai is not None:
        out += _full_ai_rows(ev.full_ai)
    elif ev.full_ai_failed:
        out.append("- Full AI Chat: this account has a full_ai_chat rule, but "
                   "its rows could not be read just now. Say so; do not guess.")
    return out


def _money_lines(ev: Evidence) -> list[str]:
    # The payer gate is a UNION of ledger and messages table (40% of content buyers exist in only one), so $0 can sit beside payer YES.
    content = sum(int(c or 0) for k, _n, c in ev.money if k in CONTENT_TX_KINDS)
    other = sum(int(c or 0) for k, _n, c in ev.money if k not in CONTENT_TX_KINDS)
    if not ev.money:
        out = ["- transactions ledger: no rows at all."]
    else:
        out = ["- transactions ledger (a priced send is PURCHASED only if it "
               "has a row here — messages.is_paid carries it on ~1.4% of "
               "them): "
               + "; ".join(f"{n} x {k} {usd(c)}" for k, n, c in ev.money)
               + f". Content money {usd(content)}, subscription/other "
                 f"{usd(other)}."]
    if ev.is_payer and not content:
        out.append(
            "  …and the ledger is not the whole story: he clears the payer "
            "gate on a purchase recorded in `messages` (an unlock or a tip) "
            "that never got a ledger row. Both count; the gate reads both.")
    return out


class Current(NamedTuple):

    head: list[str]
    essential: list[str]
    core: list[str]
    figures: list[str]


class Thread(NamedTuple):

    head: list[str]
    beats: list[str]
    tail: list[str]


def thread_lines(ev: Evidence) -> Thread:
    shown = collapse(ev.rows)[:TIMELINE_LINES]
    # No "covers X to Y" span line here: _fit sheds beats afterwards, so a span would name days whose rows were dropped.
    head = ["- thread, newest first. Directions, times, engines and amounts "
            "only; message text is deliberately excluded. Only his newest "
            f"{TIMELINE_SCAN} stored messages were read, and not all are shown: "
            "a date older than the oldest beat below was not shown or not "
            "read, so say it is not in what you can see — never that no row "
            "exists for it:"]
    if any(b.price_cents for b in shown):
        head.append(
            '  ("no LINKED purchase row" means no transactions row points at '
            "that message — a real unlock whose ledger row never got linked "
            "looks the same, so weigh it against the money line above.)")
    beats = [beat_line(b, ev.paid_ids, ev.runs, ev.fan.fan_id) for b in shown]
    if not beats:
        beats = ["  (no messages stored for this fan at all)"]
    tail = [audience_now(kind, raw, on) for kind, raw, on in ev.audiences]
    if tail:
        # Once per group: repeated three times it reads as three facts.
        tail.insert(0, "  THE LINE(S) BELOW DESCRIBE NO PAST SEND. They are who "
                       "each engine would reach FROM NOW ON — never why anyone "
                       "was in a broadcast that has already gone out. For that, "
                       "read the mass_run summary on the beat itself."
                    + (" NONE OF THESE ENGINES SENT A MASS IN THE THREAD ABOVE: "
                       "no rule is left for what did, or no mass is in the "
                       "rows read. Name them as other engines, never "
                       "as the one that sent it or its successor."
                       if ev.audiences_other else ""))
    tail.append("  NOTE: a list broadcast hands the audience to "
                "OnlyFans and writes NO per-fan row, so its absence above is "
                "not proof he was left out of one.")
    return Thread(head, beats, tail)


def current_lines(ev: Evidence) -> Current:
    essential = [_turn_line(ev)]
    essential.append(
        f"- lifetime_spend_cents: {usd(ev.fan.lifetime_spend_cents)}. CONTENT "
        "payer: " + ("YES — he has bought a tip or a PPV unlock, so the "
                     "info-gather lane is finished with him."
                     if ev.is_payer else
                     "NO — he has never bought content. A SUBSCRIPTION IS NOT A "
                     "PURCHASE, however large that lifetime number looks. Only "
                     "the info-gather lane reads this; no mass stream filters "
                     "on it."))
    core = [_pause_line(ev.fan.automation_paused_until),
            "- muted-creator hard skip: "
            + ("YES — a peer creator we follow whose chat is muted. Every "
               "automation skips him."
               if ev.muted_creator else "no.")
            + f" subscription_status: {ev.fan.subscription_status or 'unknown'}"
            + (f", expires {at(ev.fan.subscription_expires_at)}"
               if ev.fan.subscription_expires_at else "") + "."]
    if ev.full_ai is not None:
        # Lazy, as in proven_lines.
        from assistant_evidence_full_ai import _fans_line, _full_ai_state
        fa = ev.full_ai
        essential += _full_ai_state(fa)
        # A SET list can be the whole answer (he may not be on it), so while Live it outlives the knobs.
        every = fa.fans_ok and not (fa.fans.get("include") or fa.fans.get("exclude"))
        (core if every or fa.off is not None else essential).append(_fans_line(fa))

    return Current(
        head=["", "CURRENT-STATE — supports a ranked hypothesis, never proof "
              "of the past:"],
        essential=essential, core=core, figures=[])


def _turn_line(ev: Evidence) -> str:
    # A broadcast does not take the turn (chat engines set last_dir off non-broadcast rows).
    turn = next((b for b in collapse(ev.rows)
                 if b.mass_run_id is None and not b.is_unsent
                 and b.direction in ("in", "out")), None)
    if turn is None:
        return ("- turn ownership: unknown — no non-broadcast message on the "
                "thread.")
    if turn.direction == "in":
        return (f"- turn ownership: the FAN spoke last ({at(turn.ts)}). He is a "
                "candidate for every engine that answers an unanswered message.")
    return (f"- turn ownership: WE spoke last ({turn.kind or 'a human'}, "
            f"{at(turn.ts)}). Auto-reply and the info-gather lane only speak when "
            "the FAN spoke last, so neither will re-open him on its own. A mass "
            "broadcast does not take the turn and was skipped for this line; "
            "the one blind spot is a blast fired from the OnlyFans app, which "
            "carries no run id.")


def _pause_line(pause: datetime | None) -> str:
    # Two writers: the post-reply brake stamps minutes, quarantine_if_undeliverable stamps 7 days.
    if pause is None:
        return "- automation_paused_until: not set."
    now = datetime.utcnow()
    if pause <= now:
        why = ("EXPIRED, so it blocks nothing now — this is the post-reply "
               "brake, stamped after her last send.")
    elif (pause - now).days >= 2:
        why = ("STILL ACTIVE, and days out — that is the UNDELIVERABLE "
               "QUARANTINE: a send came back with no id, so his subscription "
               "has lapsed or the account is gone, and every sender rests him "
               "for a week before re-checking.")
    else:
        why = ("STILL ACTIVE; every pause-aware sender skips him until then. "
               "Minutes out, this is the post-reply brake.")
    return f"- automation_paused_until: {at(pause)} — {why}"


def render(ev: Evidence) -> str:
    nick = clean_label(ev.fan.custom_nickname)
    head = [f"{_FAN_HEADER}\n",
            f"Subject: fan {int(ev.fan.fan_id)}"
            + (f' "{nick}"' if nick else "")
            + f" on account {ev.account_id} ({ev.label}).", ""]
    return _fit(head, ["PROVEN — stored rows:"] + proven_lines(ev),
                thread_lines(ev), current_lines(ev))


# Five beats reach back past a mass send to the last real exchange on live threads.
THREAD_FLOOR = 5


def _fit(head: list[str], proven: list[str], thread: Thread,
         current: Current) -> str:
    # The order of sacrifice IS the policy; stored rows go last, the badge outranks knobs.
    groups = (head, proven, thread.head, thread.beats, thread.tail,
              current.head, current.essential, current.core, current.figures)

    def joined() -> str:
        return "\n".join(line for group in groups for line in group)

    def shed(group: list[str], down_to: int = 0) -> None:
        while len(group) > down_to and len(joined()) > CAP_CHARS:
            group.pop()

    shed(current.figures)
    shed(thread.beats, THREAD_FLOOR)
    shed(current.core)
    shed(thread.beats, 1)
    shed(current.essential)
    shed(current.head)
    # rstrip: shedding all of CURRENT-STATE leaves its blank spacer last, a dangling newline.
    out = joined().rstrip("\n")
    if len(out) <= CAP_CHARS:
        return out
    # Cut at a line boundary so no fact reads half-written; rfind -1 would silently keep the overlong string.
    cut = out.rfind("\n", 0, CAP_CHARS)
    return out[:cut if cut > 0 else CAP_CHARS].rstrip("\n")
