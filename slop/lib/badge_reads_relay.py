"""Badge reads' part of the slop relay (lib/relay.py loads it: `wire` runs at the end of its `_wire`).

The product starts `badge_reads.start` through `relay_hooks.start_background_loops()` in `_start_event_pumps`,
which CHATTERLY_TEST_MODE=1 skips here, so with no hook no Attribution read or socket-down poll ever ran.
Only this loop is started, not every `*_wiring.py` loop (the others would change other
scenarios). `start()` is a no-op unless the scenario's RELAY_ENV sets SHARED_REFRESHER=1 and UNREAD_TOTAL=1
(and BADGE_READS is not off).
"""


def wire(app, _loopback, _relay) -> None:
    async def start_badge_reads() -> None:
        import badge_reads
        badge_reads.start()

    app.on_event("startup")(start_badge_reads)
