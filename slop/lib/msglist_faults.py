"""The Thread's pin (app/components/chat/threadPin.ts, used by useThreadPin) break-it-once fault:
lib/faults.py merges `register(Fault)` into FAULTS. Client side: actors/ui.py rewrites the JS
`next dev` serves, never the repo files. The check it targets is scenarios/2026-10-26-mobile-gestures.py's
C_PIN: a Thread opened on a phone holds its auto-pin ("Jumping to latest") through a cancelled
sideways swipe and lets go on a vertical drag.

Not here: the requested `thread-pin-own-scroll-releases` (drop `onScrollDecision`'s programmatic
guard, so our own pin writes read as a user scroll). Measured 2026-10-30, run
20261030T130110Z-2026-10-26-mobile-gestures-break-45ee: it matched the served code (1 file) and
stayed NOT CAUGHT. The mobile-gestures Thread (agency_inbox, 4 messages) never overflows, so it emits
no `scroll` event for the guard to filter; no check sees that guard yet.
`thread-pin-sideways-swipe-releases` below is CAUGHT: run 20261030T130505Z-2026-10-26-mobile-gestures-break-aeb2.
"""
from __future__ import annotations

C_PIN = ("phone: a cancelled sideways swipe on the Thread keeps it pinned to the latest message; "
         "a vertical drag releases it")

# How many JS files `next dev` serves threadPin.ts in on that flow (measured: Messages Pro's page chunk only).
THREAD_PIN_FILES = 1


def register(Fault) -> dict:
    return {
        # slop/run mobile-gestures --break --fault=thread-pin-sideways-swipe-releases
        # `touchReleases`: any finger move releases the auto-pin, direction ignored, as before 2026-10-27: the
        # Thread's cancelled swipe back lets go of the latest message. The swipe back itself, Fan insights' swipe
        # and the vertical drag stay green.
        "thread-pin-sideways-swipe-releases": Fault(None, (C_PIN,), browser=(
            (r"Math\.abs\(t\.y - t0\.y\) <= Math\.abs\(t\.x - t0\.x\)", "false"),
        ), browser_files=THREAD_PIN_FILES),
    }
