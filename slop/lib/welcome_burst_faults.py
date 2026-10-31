"""The welcome burst's break-it-once faults (scenarios/2026-10-30-welcome-burst.py):
lib/faults.py merges `register(Fault)` into FAULTS. The check names live here and the
scenario imports them, so a target can never name a check that does not exist.

Both patch `automations.send_welcome_decide.partition` (send_welcome calls it through the
module attribute) in the relay process, never the repo files.
"""
from __future__ import annotations

ONCE = ("welcome burst: exactly once: every new sub of an OF-welcome-off Creator gets one greeting "
        "and one follow-back, a fan already in welcome_sent gets nothing, and a second toast + "
        "tick sends nobody anything")
ESTABLISHED = ("welcome burst: a renewal with real history (> 2 out / > 8 in, no claim) is never "
               "welcomed, followed or claimed")
OF_ON = ("welcome burst: a Creator whose OnlyFans welcome is on sends no message of its own; "
         "each new sub is claimed and followed back once")
COUNTS = ("welcome burst: OF sends = new outbound welcome rows, fans sent to = the runs' welcomes_sent, "
          "follows = the runs' followed_back, no errors")
POKE = ("welcome burst: a subscribe toast runs the Creator's rule on the next supervisor pass, "
        "inside its cadence; a pass with no toast runs nothing; a toast inside the 60 s poke floor is spent")
LIVE = "welcome burst: every welcome bubble reached every owner tab's /events stream"


def _patch_partition(drop: str) -> None:
    """Blank one `Reads` field by name on every `partition` call; a renamed arg or
    field fails here, loudly, instead of patching nothing."""
    import dataclasses
    import inspect

    from automations import send_welcome_decide as swd

    real = swd.partition
    sig = inspect.signature(real)
    if "reads" not in sig.parameters:
        raise RuntimeError(f"partition{sig} has no `reads`: this fault would patch nothing")
    if drop not in {f.name for f in dataclasses.fields(swd.Reads)}:
        raise RuntimeError(f"Reads has no field {drop!r}: this fault would patch nothing")

    def broken(*a, **kw):
        bound = sig.bind(*a, **kw)
        bound.arguments["reads"] = dataclasses.replace(bound.arguments["reads"],
                                                       **{drop: frozenset()})
        return real(*bound.args, **bound.kwargs)

    swd.partition = broken


def _rewelcomes() -> None:
    """partition ignores `welcome_sent`: a renewal the welcome already greeted (2 outbound
    rows, at the NOT-NEW tolerance, so only the claim kept him out) is greeted and followed
    again. Only the exactly-once check can see it."""
    _patch_partition("welcomed")


def _to_established() -> None:
    """partition ignores the NOT-NEW scan: a renewal with a real conversation gets a
    first-contact welcome. Only the established check can see it."""
    _patch_partition("established")


def register(Fault) -> dict:
    return {
        # slop/run welcome-burst --break (the scenario's FAULT)
        "welcome-burst-rewelcomes": Fault(_rewelcomes, (ONCE,)),
        "welcome-to-established": Fault(_to_established, (ESTABLISHED,)),
    }
