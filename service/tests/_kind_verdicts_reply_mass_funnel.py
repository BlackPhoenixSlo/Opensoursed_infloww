from __future__ import annotations

import contextlib
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from _kind_verdict_seeds import FAN, PLATFORM_MESSAGE
from db.engine import get_session
from db.models import Fan, FunnelState, MassMessageFunnel, MassRun, Message

VERDICTS = {
    "fansly": {"reply_mass_funnel": {"idle": "noop:no_active_funnel_runs", "landed": "same", "walk": "same",
                                     "locked": "gated:platform_lacks:locked_text"}},
    "onlyfans": {"reply_mass_funnel": {"idle": "noop:no_active_funnel_runs", "landed": "same", "walk": "same",
                                       "locked": "same"}},
}

PAYLOADS = {"reply_mass_funnel": {"idle": {}, "landed": {}, "walk": {}, "locked": {}}}

SAME_EFFECTS = {
    "fansly": {"reply_mass_funnel": {"landed": ("table:funnel_state",),
                                     "walk": ("POST /message", "table:chats", "table:fans", "table:funnel_state",
                                              "table:messages")}},
    "onlyfans": {"reply_mass_funnel": {"landed": ("table:funnel_state",),
                                       "walk": ("send_message", "table:chats", "table:fans", "table:funnel_state",
                                                "table:messages"),
                                       "locked": ("send_message", "table:chats", "table:fans", "table:funnel_state",
                                                  "table:messages")}},
}


def _walking(step: dict):
    async def seed(aid: str, platform: str) -> None:
        started = datetime.utcnow() - timedelta(days=30)
        async with get_session() as s:
            funnel = MassMessageFunnel(name=f"walk {aid}", opening_message="hey", steps_json=json.dumps([step]))
            s.add(funnel)
            await s.flush()
            run = MassRun(account_id=aid, funnel_id=funnel.id, status="ok", started_at=started)
            s.add(run)
            await s.flush()
            s.add_all([Fan(account_id=aid, fan_id=int(FAN)),
                       FunnelState(mass_run_id=run.id, fan_id=int(FAN), status="pending", current_step=0),
                       Message(account_id=aid, fan_id=int(FAN), message_id=PLATFORM_MESSAGE[platform] + 2,
                               direction="in", body="hey whats up", created_at=datetime.utcnow() - timedelta(hours=1))])
    return seed


@contextlib.contextmanager
def _cotag_off(_aid):
    with patch.dict(os.environ, {"OF_COTAG_ENABLED": "0"}):
        yield


SEEDS = {
    ("reply_mass_funnel", "walk"): _walking({"step": 1, "messages": ["m1"]}),
    ("reply_mass_funnel", "locked"): _walking({"step": 1, "type": "paid_ppv", "messages": ["m1"],
                                              "media_files": [901], "price": 10, "locked_text": True}),
}

WORLDS = {("reply_mass_funnel", "locked"): _cotag_off}
