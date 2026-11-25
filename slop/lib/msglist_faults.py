from __future__ import annotations

C_PIN = ("phone: a cancelled sideways swipe on the Thread keeps it pinned to the latest message; "
         "a vertical drag releases it")

THREAD_PIN_FILES = 1  # measured: Messages Pro's page chunk only


def register(Fault) -> dict:
    return {
        "thread-pin-sideways-swipe-releases": Fault(None, (C_PIN,), browser=(
            (r"Math\.abs\(t\.y - t0\.y\) <= Math\.abs\(t\.x - t0\.x\)", "false"),
        ), browser_files=THREAD_PIN_FILES),
    }
