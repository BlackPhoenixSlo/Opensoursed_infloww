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
