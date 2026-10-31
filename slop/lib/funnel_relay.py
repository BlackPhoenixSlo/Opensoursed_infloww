"""The house funnel's part of the slop relay (lib/relay.py loads it: `wire` runs at the
end of its `_wire`). The walker (`automations.reply_mass_funnel`) runs on demand through
relay.py's `POST /__slop/run-automation`; its OF client is the offline
walker client (it replaces `ax._make_client` for every flow when there is no
`OF_API_ORIGIN`): `send_message` answers as OF does, a priced one kept per fan
(`of_ppv` at /__slop/fake/calls).

Declared pacing bypass: `_STEP_GAP_S` (4 s, jittered, between a step's lines) to
SLOP_STEP_GAP_S (0.2). Typing holds are already 0
under CHATTERLY_TEST_MODE; the account's DM rate (`dm_rate`) stays real (a scenario
raises it through the real Concurrency panel route)."""
from __future__ import annotations

import os


def wire(app, _loopback, relay) -> None:
    from automations import reply_mass_funnel

    reply_mass_funnel._STEP_GAP_S = float(os.environ.get("SLOP_STEP_GAP_S", "0.2"))
