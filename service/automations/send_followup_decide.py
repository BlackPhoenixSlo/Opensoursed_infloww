"""service/automations/send_followup_decide.py — the follow-up drip's per-fan phase
machine as ONE pure transition (docs/reducer-scan.md, Non-React #1):

    decide(entry, ev, thresholds) -> (entry', effects)

No I/O and no service imports beyond the pure isotime, so it loads and tests without a DB. send_followup.run()
is the shell: it loads, builds the event, calls decide() and performs the effects in
the order given. Every phase rule of the drip lives here and nowhere else.

Phases: tracking -> (steps 1..3 at the silence thresholds, >= _MIN_GAP_H apart) ->
all_sent_waiting; a reply mid-drip -> reply_cooldown (26 h) -> tracking, same cycle;
a reply after the drip (or after the cap retired him: completed) -> restart_cooldown
(72 h) -> tracking, cycle + 1, steps reset; silent past _MAX_SILENCE_H -> completed.

Events (what run() saw):
  Tick(now)                             the time-only pass over EVERY state row,
                                        before the LLM-key check and the sweep
  Seen(now, last_in, last_out, guarded) one eligible fan in the sweep: his latest
                                        inbound / outbound message times, and
                                        whether the contact guard holds him;
                                        fed again with fresh times right before
                                        his send (a reply mid-tick -> no Send)
  Sent(step, now)                       his step went out (OF returned the send)

Effects (what run() does, in list order; run() counts each by value):
  Save()                 upsert entry' into followup_state
  Resume()               a cooldown ran out: entry' is the fan's state from here on
                         (`transitioned`)
  Cooldown(kind)         'reply' | 'restart' (`state_advanced`; a reply also
                         `skipped_unread`)
  Complete()             retired by the 7-day silence cap (`completed`)
  Wait()                 a due step held by the contact guard (`skipped_guard`);
                         every other hold is simply no Send
  Send(step, silence_h)  generate + send this step (run() still checks the fan
                         cooldown and the lease first; on a returned send it feeds
                         Sent back in)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal

from isotime import parse_iso as _parse_iso  # dependency-free (no service imports)

log = logging.getLogger("of-relay.automation.send_followup")

# Silence thresholds per step (hours) and the minimum gap between consecutive
# sends. Carried over from the DOM script unchanged (07 §pick_next_step).
# Overridable per-rule via payload["step_hours"] = [h1, h2, h3] (see
# _resolve_step_thresholds) — the Brain panel's "Follow-ups" delays write it.
# Step 3 must sit UNDER _MAX_SILENCE_H or the cap retires the fan first and the
# final nudge never fires (it was 256h > the 168h cap — dead for every fan).
_STEP_THRESHOLDS_H = {1: 26, 2: 64, 3: 120}
_MIN_GAP_H = 18
# Hard cap: never follow up a fan who's been silent longer than this. A chat
# cold for over a week is ghosted/dead — reminders just waste sends and draw
# "Cannot send message to this user" rejections. A fan retired here is not gone
# for good: an inbound after the silence anchor restarts the cycle, same as a
# finished drip (see Entry.replied_since_anchor).
_MAX_SILENCE_H = 24 * 7

# Cooldowns (hours) for the reply / restart branches (07 §Core algorithm).
_REPLY_COOLDOWN_H = 26
_RESTART_COOLDOWN_H = 72

_COOLING = ("reply_cooldown", "restart_cooldown")
_DONE = ("all_sent_waiting", "completed")


# ── State ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entry:
    """One followup_state row (or a fresh tracking entry). Never mutated: decide()
    returns a new one. `messages_sent` is {"<step>": iso send time}."""
    phase: str = "tracking"
    cycle: int = 1
    silence_started_at: datetime | None = None
    fan_last_reply_at: datetime | None = None
    cooldown_until: datetime | None = None
    messages_sent: dict = field(default_factory=dict)

    @classmethod
    def from_row(cls, row) -> "Entry":
        """From a FollowupState row (duck-typed: no ORM import); None -> fresh."""
        if row is None:
            return cls()
        try:
            sent = json.loads(row.messages_sent or "{}") or {}
        except Exception:
            sent = {}
        return cls(phase=row.phase or "tracking", cycle=row.cycle or 1,
                   silence_started_at=row.silence_started_at,
                   fan_last_reply_at=row.fan_last_reply_at,
                   cooldown_until=row.cooldown_until, messages_sent=sent)

    def replied_since_anchor(self, last_fan: datetime | None) -> bool:
        """Fan wrote back after we started counting his silence. Anchored on
        `silence_started_at`, NOT the last outbound — any other automation's
        send (a PPV blast a minute later) would otherwise bury the reply."""
        return bool(last_fan and (self.silence_started_at is None
                                  or last_fan > self.silence_started_at))

    def last_sent_dt(self) -> datetime | None:
        """Latest send timestamp across messages_sent (for the >=18h gap)."""
        best: datetime | None = None
        for iso in self.messages_sent.values():
            dt = _parse_iso(iso)
            if dt and (best is None or dt > best):
                best = dt
        return best


# ── Events ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Tick:
    now: datetime


@dataclass(frozen=True)
class Seen:
    now: datetime
    last_in: datetime | None
    last_out: datetime | None
    guarded: bool = False


@dataclass(frozen=True)
class Sent:
    step: int
    now: datetime


# ── Effects ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Save:
    pass


@dataclass(frozen=True)
class Resume:
    pass


@dataclass(frozen=True)
class Cooldown:
    kind: Literal["reply", "restart"]


@dataclass(frozen=True)
class Complete:
    pass


@dataclass(frozen=True)
class Wait:
    pass


@dataclass(frozen=True)
class Send:
    step: int
    silence_hours: float


Effect = Save | Resume | Cooldown | Complete | Wait | Send


# ── Thresholds ────────────────────────────────────────────────────────

def _resolve_step_thresholds(payload: dict) -> dict[int, float]:
    """Per-step silence thresholds (hours). `payload['step_hours'] = [h1, h2, h3]`
    overrides the defaults; any missing/invalid entry falls back to that step's
    default ({1:26, 2:64, 3:120}). Written by the Brain panel's "Follow-ups"
    delays so an operator can tune the drip cadence per account.

    A threshold at/over _MAX_SILENCE_H counts as invalid: the cap retires the fan
    before that step could ever fire, so honouring it would silently kill it."""
    out = dict(_STEP_THRESHOLDS_H)
    sh = (payload or {}).get("step_hours")
    if isinstance(sh, (list, tuple)):
        for i, step in enumerate((1, 2, 3)):
            if i < len(sh):
                try:
                    val = float(sh[i])
                except (TypeError, ValueError):
                    continue
                if 0 < val < _MAX_SILENCE_H:
                    out[step] = val
                elif val >= _MAX_SILENCE_H:
                    log.warning("send_followup step %s override %.0fh ignored "
                                "(≥ %sh cap) — using %sh",
                                step, val, _MAX_SILENCE_H, out[step])
    return out


def _pick_next_step(
    silence_hours: float, sent: dict, thresholds: dict[int, float] = _STEP_THRESHOLDS_H,
) -> int | None:
    """The first unsent step whose threshold the silence has reached, else None.
    Steps are tried 1, 2, 3 in order, so a skipped step is sent before a later one."""
    if "1" not in sent and silence_hours >= thresholds[1]:
        return 1
    if "2" not in sent and silence_hours >= thresholds[2]:
        return 2
    if "3" not in sent and silence_hours >= thresholds[3]:
        return 3
    return None


# ── The transition ────────────────────────────────────────────────────

def decide(e: Entry, ev: Tick | Seen | Sent,
           thresholds: dict[int, float]) -> tuple[Entry, list[Effect]]:
    if isinstance(ev, Tick):
        if e.phase in _COOLING and e.cooldown_until and ev.now > e.cooldown_until:
            restart = e.phase == "restart_cooldown"
            e = replace(e, phase="tracking", silence_started_at=None, cooldown_until=None,
                        **({"messages_sent": {}, "cycle": e.cycle + 1} if restart else {}))
            return e, [Save(), Resume()]
        return e, []

    if isinstance(ev, Sent):
        sent = {**e.messages_sent, str(ev.step): ev.now.isoformat()}
        return replace(e, messages_sent=sent,
                       phase="all_sent_waiting" if len(sent) >= 3 else e.phase), [Save()]

    now = ev.now
    if e.phase in _COOLING:
        return e, []  # still cooling down (the Tick pass ran first)

    # He wrote back after we stopped counting his silence — either the drip ran
    # out of steps or the cap retired him. Same restart either way.
    if e.phase in _DONE:
        if e.replied_since_anchor(ev.last_in):
            return replace(e, phase="restart_cooldown",
                           cooldown_until=now + timedelta(hours=_RESTART_COOLDOWN_H),
                           fan_last_reply_at=ev.last_in), [Save(), Cooldown("restart")]
        return e, []  # finished, no reply: nothing to do

    # tracking: his latest message is newer than ours -> pause for a human.
    if ev.last_in and (ev.last_out is None or ev.last_in > ev.last_out):
        return replace(e, phase="reply_cooldown",
                       cooldown_until=now + timedelta(hours=_REPLY_COOLDOWN_H),
                       fan_last_reply_at=ev.last_in), [Save(), Cooldown("reply")]

    if e.silence_started_at is None:  # establish the silence anchor
        e = replace(e, silence_started_at=ev.last_out or now)
    silence_hours = (now - e.silence_started_at).total_seconds() / 3600.0

    if silence_hours > _MAX_SILENCE_H:  # cold for over a week: stop the drip
        return replace(e, phase="completed"), [Save(), Complete()]

    step = _pick_next_step(silence_hours, e.messages_sent, thresholds)
    if step is None:
        return e, [Save()]  # not due yet; persists an anchor just set

    last_sent = e.last_sent_dt()
    if last_sent and (now - last_sent).total_seconds() / 3600.0 < _MIN_GAP_H:
        return e, [Save()]  # inside the gap: the step waits

    # A blast/nudge/manual send touched him inside the guard window: the step
    # stays due and fires on a later tick. Nothing saved (as before).
    if ev.guarded:
        return e, [Wait()]
    return e, [Send(step, silence_hours)]
