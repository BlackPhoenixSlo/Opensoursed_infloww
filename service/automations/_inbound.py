from __future__ import annotations

from dataclasses import dataclass

from tip_ledger import TIP_LEDGER_PREFIX
from db.models import Message


_REACTION_TAG = {
    "image_reply": "[you sent him a pic back]",
    "tip_reward": "[you sent him his tip reward]",
}
# Derived from the tag dict: callers subscript it, so a kind missing from one would KeyError the whole sweep.
TURN_NEUTRAL_KINDS = frozenset(_REACTION_TAG)



MSG_CLIP = 400


def inbound_is_words(body: str | None) -> bool:
    b = (body or "").strip()
    # lower() on both sides: SQLite LIKE is case-insensitive, startswith is not.
    return bool(b) and not b.lower().startswith(TIP_LEDGER_PREFIX.lower())


def worded_inbound_where():
    return (Message.body != "", Message.body.notlike(f"{TIP_LEDGER_PREFIX}%"))


@dataclass(slots=True)
class TurnHandoff:
    last_worded_in: str = ""
    window_open: bool = False

    def on_inbound(self, body: str | None, rendered: str | None) -> None:
        text = (rendered or "").strip()
        if text and inbound_is_words(body):
            self.last_worded_in = text[:MSG_CLIP]
        self.window_open = True

    def on_outbound(self, *, took_the_turn: bool,
                    automation_kind: str | None) -> None:
        if took_the_turn and automation_kind != "welcome":
            self.window_open = False

    def admit(self, fan_id: int, handoff_ids: set[int]) -> str | None:
        if fan_id in handoff_ids and self.last_worded_in.strip() and self.window_open:
            return self.last_worded_in
        return None
