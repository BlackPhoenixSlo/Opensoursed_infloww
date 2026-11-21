"""Fake-only fixture proofs (ticket 08): driver behaviours no shipped Phase proof uses yet, proven in fake mode.

They never ship in a Phase's proofs file and are for `--of fake` only.
ASSUMPTION: ticket 08's ASSUMPTION (rung 5: no new seam; fake-only fixtures beside the pure tests). Live mode is not
built yet, and every proof here is `fake_only` (prove.py refuses it under `--of live` before anything starts).
Overturned if the reviewer wants these behaviours proven only through a real Phase's proof.

  fixture.message-parked    a message proof with no Proof fan: listed as parked, never started, no Fan picked.
  fixture.delete-at-once    the tracer's control tagged delete_at_once, then held past its deadline: the forced-undo
                            timer undoes the list mid-proof (during the `wait` step) and the row closes undone.
  fixture.read-stray-write  a read proof (nothing armed) whose clicks send a write: the proof fails.
"""
from proof_core import Proof, Write
from proofs.phase0 import DIALOG, TRACER

_CREATE = TRACER.trigger

MESSAGE_PARKED = Proof(
    id="fixture.message-parked", phase=0, page="chats/index", control="Send message (fixture)", kind="live",
    fake_only=True,
    tags=frozenset({"message"}),
    arm=(Write("POST", "/api2/v2/chats/{fan}/messages"),),
    effect=lambda before, after: True,
    undo=(Write("DELETE", "/api2/v2/messages/{id}"),),
)

DELETE_AT_ONCE = Proof(
    id="fixture.delete-at-once", phase=0, page=TRACER.page, control=TRACER.control, kind="live",
    fake_only=True,
    tags=frozenset({"delete_at_once"}),
    arm=TRACER.arm,
    # The note fades after 2 s, so it is waited for as a step; the proof then stays busy past the 50 s forced undo.
    trigger=(*_CREATE, ("text", "#oi-note", "List created"), ("wait", 58)),
    settled=("text", "body", "Collections"),
    of_read=TRACER.of_read, effect=TRACER.effect, undo=TRACER.undo, find=TRACER.find,
)

READ_STRAY_WRITE = Proof(
    id="fixture.read-stray-write", phase=0, page=TRACER.page, control=TRACER.control, kind="live",
    fake_only=True,
    trigger=_CREATE,
    settled=("text", f"{DIALOG} .v-messages__message", "Could not save"),
    of_read=TRACER.of_read,
)

PROOFS = (MESSAGE_PARKED, DELETE_AT_ONCE, READ_STRAY_WRITE)
