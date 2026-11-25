from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal

from isotime import parse_iso as _parse_iso

log = logging.getLogger("of-relay.automation.send_followup")

_STEP_THRESHOLDS_H = {1: 26, 2: 64, 3: 120}
_MIN_GAP_H = 18
# Step 3 must stay under this or the cap retires the fan before the final nudge fires.
# Never follow up a fan cold over a week: reminders waste sends and draw 'Cannot send message' rejections.
_MAX_SILENCE_H = 24 * 7

_REPLY_COOLDOWN_H = 26
_RESTART_COOLDOWN_H = 72

_COOLING = ("reply_cooldown", "restart_cooldown")
_DONE = ("all_sent_waiting", "completed")



@dataclass(frozen=True)
class Entry:
    phase: str = "tracking"
    cycle: int = 1
    silence_started_at: datetime | None = None
    fan_last_reply_at: datetime | None = None
    cooldown_until: datetime | None = None
    messages_sent: dict = field(default_factory=dict)
    sending_at: datetime | None = None
    sending_ctx: dict | None = None
    unconfirmed_at: datetime | None = None

    @property
    def marked(self) -> bool:
        return self.sending_at is not None or self.unconfirmed_at is not None

    @classmethod
    def from_row(cls, row) -> "Entry":
        if row is None:
            return cls()
        try:
            sent = json.loads(row.messages_sent or "{}") or {}
        except Exception:
            sent = {}
        try:
            ctx = json.loads(row.sending_ctx or "null")
        except Exception:
            ctx = None
        return cls(phase=row.phase or "tracking", cycle=row.cycle or 1,
                   silence_started_at=row.silence_started_at,
                   fan_last_reply_at=row.fan_last_reply_at,
                   cooldown_until=row.cooldown_until, messages_sent=sent,
                   sending_at=row.sending_at,
                   sending_ctx=ctx if isinstance(ctx, dict) else None,
                   unconfirmed_at=row.unconfirmed_at)

    # Anchored on silence_started_at, not the last outbound: another automation's send (a PPV blast) would bury the reply.
    def replied_since_anchor(self, last_fan: datetime | None) -> bool:
        return bool(last_fan and (self.silence_started_at is None
                                  or last_fan > self.silence_started_at))

    def last_sent_dt(self) -> datetime | None:
        best: datetime | None = None
        for iso in self.messages_sent.values():
            dt = _parse_iso(iso)
            if dt and (best is None or dt > best):
                best = dt
        return best



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



def _resolve_step_thresholds(payload: dict) -> dict[int, float]:
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
    if "1" not in sent and silence_hours >= thresholds[1]:
        return 1
    if "2" not in sent and silence_hours >= thresholds[2]:
        return 2
    if "3" not in sent and silence_hours >= thresholds[3]:
        return 3
    return None



def decide(e: Entry, ev: Tick | Seen | Sent,
           thresholds: dict[int, float]) -> tuple[Entry, list[Effect]]:
    if e.marked and not isinstance(ev, Sent):
        return e, []

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
                       phase="all_sent_waiting" if len(sent) >= 3 else e.phase,
                       sending_at=None, sending_ctx=None, unconfirmed_at=None), [Save()]

    now = ev.now
    if e.phase in _COOLING:
        return e, []

    if e.phase in _DONE:
        if e.replied_since_anchor(ev.last_in):
            return replace(e, phase="restart_cooldown",
                           cooldown_until=now + timedelta(hours=_RESTART_COOLDOWN_H),
                           fan_last_reply_at=ev.last_in), [Save(), Cooldown("restart")]
        return e, []

    if ev.last_in and (ev.last_out is None or ev.last_in > ev.last_out):
        return replace(e, phase="reply_cooldown",
                       cooldown_until=now + timedelta(hours=_REPLY_COOLDOWN_H),
                       fan_last_reply_at=ev.last_in), [Save(), Cooldown("reply")]

    if e.silence_started_at is None:
        e = replace(e, silence_started_at=ev.last_out or now)
    silence_hours = (now - e.silence_started_at).total_seconds() / 3600.0

    if silence_hours > _MAX_SILENCE_H:
        return replace(e, phase="completed"), [Save(), Complete()]

    step = _pick_next_step(silence_hours, e.messages_sent, thresholds)
    if step is None:
        return e, [Save()]

    last_sent = e.last_sent_dt()
    if last_sent and (now - last_sent).total_seconds() / 3600.0 < _MIN_GAP_H:
        return e, [Save()]

    if ev.guarded:
        return e, [Wait()]
    return e, [Send(step, silence_hours)]
