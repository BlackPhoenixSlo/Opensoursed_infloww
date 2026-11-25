from __future__ import annotations

GAP = ("followup drip: a due step inside 18h of the fan's last nudge is held "
       "(no send, nothing recorded, state unchanged)")
STEPS = ("followup drip: each due fan gets exactly its next step (step 1 at 26h of silence, "
         "step 2 at 64h), one nudge each, recorded in followup_state")
CAP = "followup drip: a fan silent over 7 days is retired (completed), never nudged"
REPLIES = ("followup drip: a reply mid-drip pauses it 26h (reply_cooldown), a reply after the drip "
           "restarts it after 72h (restart_cooldown); neither is nudged")
RESUME = ("followup drip: an expired cooldown resumes before the sweep (reply: same cycle; restart: "
          "cycle 2, steps reset) and the fan's step 1 goes out in the same tick")
HOLD = "followup drip: fans cooling down, finished without a reply, or not yet due get nothing and keep their state"
COUNTS = ("followup drip: every nudge is one LLM call, one OF send, one outbound followup row and one "
          "recorded step; the runs' followups_sent add up (nothing dropped, no duplicates, no errors)")
LIVE = "followup drip: every nudge reached every owner tab's /events stream"
AGAIN = ("followup drip: a second tick right after the first nudges nobody, held by the drip's own 18h gap "
         "(no just-nudged fan reaches the contact guard or the per-fan send rest)")


def _followup_skips_18h_gap() -> None:
    from automations import send_followup_decide

    assert hasattr(send_followup_decide, "_MIN_GAP_H"), "the gap constant moved: this fault would patch nothing"
    send_followup_decide._MIN_GAP_H = 0


def register(Fault) -> dict:
    return {
        "followup-skips-18h-gap": Fault(_followup_skips_18h_gap, (GAP, AGAIN)),
    }
