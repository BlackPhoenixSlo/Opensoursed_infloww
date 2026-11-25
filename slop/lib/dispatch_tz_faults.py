from __future__ import annotations

BAD_TZ = ("dispatch plan: a rule with a bad tz_offset_minutes is skipped; every other rule still "
          "fires on time (one supervisor pass makes each good rule's job; its next_due_at was due "
          "before the pass and is the next slot after it)")


def _bad_tz_aborts_pass() -> None:
    import dispatch_plan as dp

    # the return is unused: only the raise matters
    dp._bad_tz = lambda raw: int(raw)


def register(Fault) -> dict:
    return {
        "dispatch-bad-tz-aborts-pass": Fault(_bad_tz_aborts_pass, (BAD_TZ,)),
    }
