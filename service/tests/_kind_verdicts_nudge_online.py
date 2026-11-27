from __future__ import annotations

from datetime import timedelta

from _kind_verdict_seeds import _NUDGE_CFG, _rows, _seen

VERDICTS = {
    "fansly": {"nudge_online": {"run": "owner:50", "incomplete": "gated:platform_lacks:subscribers:incomplete"}},
    "onlyfans": {"nudge_online": {"run": "same", "incomplete": "same"}},
}

PAYLOADS = {"nudge_online": {"run": {}, "incomplete": {}}}

OWNER_RUNS = {"fansly": {"nudge_online": {"run": ("ok", None, ("job:nudge_online_fire", "table:nudge_state"), None)}}}

SAME_EFFECTS = {
    "onlyfans": {"nudge_online": dict.fromkeys(("run", "incomplete"), ("job:nudge_online_fire", "table:nudge_state"))},
}


def _short_roster(fake) -> None:
    fake.subscribers["stats"]["totalActive"] += 1


SEEDS = {("nudge_online", b): _rows(_NUDGE_CFG, _seen(1, timedelta(days=1))) for b in ("run", "incomplete")}

FAKE_STATE = {("nudge_online", "incomplete"): _short_roster}
