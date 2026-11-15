"""The Mode gate (04a seam 3). Leaf, no imports.

`test` (the Test chat) and `live` (OF sends) run the full Turn: every Test chat behaviour is on and
one Creator config decides, not the Mode (owner 2026-11-15). `shadow` decides and records only,
on Phase 01's request (its question version and Jev bytes stay pinned by the shipped golden)."""

MODES = ("test", "shadow", "live")


def full(mode: str | None) -> bool:
    """True for test and live: every Test chat behaviour is on."""
    return mode in ("test", "live")
