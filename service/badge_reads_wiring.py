from __future__ import annotations

from fastapi import FastAPI

import badge_reads
import relay_hooks

relay_hooks.inbound_message.append(badge_reads.on_frame)
relay_hooks.mute.append(badge_reads.on_mute)
relay_hooks.background_loops.append(badge_reads.start)


def wire(app: FastAPI) -> None:
    pass
