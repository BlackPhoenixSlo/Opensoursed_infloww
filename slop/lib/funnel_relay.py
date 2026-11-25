from __future__ import annotations

import os


def wire(app, _loopback, relay) -> None:
    from automations import reply_mass_funnel

    reply_mass_funnel._STEP_GAP_S = float(os.environ.get("SLOP_STEP_GAP_S", "0.2"))
