"""service/assistant_evidence_full_ai.py — the fan evidence pack's Full AI Chat lines.

Moved out of `assistant_evidence` as is: the raw `FullAi` record the fetcher (`assistant_fan_pack`) fills, and the
renderers `assistant_evidence.proven_lines` / `current_lines` call (`_full_ai_rows`, `_full_ai_state`, `_fans_line`).
Same rules as there: pure (no session, engine or network), reason codes and timestamps only, never a fan's words.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from assistant_evidence import at, clean_label, humanize, usd

if TYPE_CHECKING:
    from automations.full_ai_owner_io import FansRead


class FullAiJob(NamedTuple):
    """One `full_ai_chat` scheduled_jobs row aimed at this fan, raw."""

    id: int
    status: str                  # pending | running | done | error | cancelled
    run_at: datetime | None      # when it is (was) due
    created_at: datetime | None
    anchor_at: datetime | None   # his message it was queued off; None = not read
    tries: int                   # busy re-queues so far (payload `tries`)
    last_error: str | None
    decided: bool = False        # a live decision on its anchor or a later message


class FullAiDecision(NamedTuple):
    """One live `ai_decisions` row of his, raw. `reply` holds ONLY the
    `FULL_AI_REPLY_KEYS` (the fetcher drops the rest): reply_json also carries
    her bubbles and `fan_info`, i.e. words, and no word goes in this pack."""

    created_at: datetime | None
    anchor_at: datetime | None
    route: str
    status: str                  # sending | sent | unconfirmed | no_send | failed
    reply: dict
    jev_error: str | None


# The reply_json keys that say WHY a Turn sent nothing or less than all of it.
FULL_AI_REPLY_KEYS = ("floor_reason", "dropped_reason", "stood_down", "cut",
                      "refusal", "offer_dropped", "attempts")


class FullAi(NamedTuple):
    """Full AI Chat for this account and fan, as LOCAL rows show it.

    `stop` is `full_ai_owner.who_owns` over the facts readable here — never a
    copy of its order. Fans list MEMBERSHIP is an OnlyFans read: only a FRESH
    cached read (`fans_read`, full_ai_owner_io.FansRead) goes into that call;
    otherwise a set list is assumed passed and the Fans line says what is known."""

    off: str | None              # full_ai_owner.OFF_REASONS, None = Live
    mode: str | None             # the rule's trigger_json mode
    every_s: Any                 # the rule's every_seconds: the sweep's cadence
    speed: str                   # checkpoint reply_speed
    by_webhook: bool             # checkpoint reply_by_webhook
    fans: Any                    # checkpoint fans {include, exclude}
    fans_ok: bool                # full_ai_config._fans_error(fans) is None
    spend_cents: int
    top_spend_cents: int         # 0 = no limit
    stop: str | None             # who_owns' reason; None = nothing local stops him
    audience_why: str | None
    jobs: list[FullAiJob]        # pending/running first, then newest
    decisions: list[FullAiDecision]   # newest first
    open_at: datetime | None     # his unanswered message (the sweep's Turn end)
    open_due: datetime | None    # its due time by Reply speed (full_ai_live.due)
    open_decided: bool           # a live decision row exists on it
    # Fans list membership off the relay's cached OnlyFans read; None = unknown.
    fans_read: "FansRead | None" = None


# Presentation of full_ai_config.REPLY_SPEEDS (full_ai_test._SPEEDS draws them); a test pins the key set. Not
# imported: full_ai_config pulls the automation executor into this pure renderer.
_SPEED_WORDS = {"0-2m": "0-2 min", "0-15-60": "most near 15 min, none past 1h"}

# One phrase per full_ai_owner.REASONS entry (a test pins the key set).
FULL_AI_STOP = {
    "off_global": "the global switch FULL_AI_CHAT_OFF is on",
    "off_rule": "its rule is switched off",
    "off_mode": "its rule is not in Live mode",
    "not_listed": "he is NOT on its Fans list (a fresh OnlyFans read; Fans "
                  "list line)",
    "hard_skip": "hard skip — blacklist, a hard skip_list reason / "
                 "unreachable, or a muted creator (rows above)",
    "audience": "outside the account's audience limits",
    "human": "a human answered him since his message",
    "human_of_app": "a human answered him in the OnlyFans app since his message",
    "funnel_walk": "an Auto Funnel walk is running for him",
    "top_spend": "his lifetime spend reached the top spend limit (left to "
                 "humans)",
}
# not_listed off a malformed stored list.
_STOP_MALFORMED = "the Fans list's stored config is malformed, so nobody is listed"


# ── Full AI Chat ──────────────────────────────────────────────────────

def _speed(fa: FullAi) -> str:
    words = _SPEED_WORDS.get(fa.speed)
    return f"Reply speed {fa.speed}" + (f" ({words})" if words else "")


def _job_line(fa: FullAi, j: FullAiJob, now: datetime) -> str:
    """The pending (or running) job: THE answer when a reply is merely waiting."""
    msg = f"his message of {at(j.anchor_at)}" if j.anchor_at else "his message"
    if j.status == "running":
        return f"- Full AI queue: a reply to {msg} is RUNNING now (job {j.id})."
    retry = (f", busy retry {j.tries} — he was paused or held by another lane"
             if j.tries else "")
    if j.run_at is not None and j.run_at > now:
        return (f"- Full AI queue: QUEUED — a reply to {msg} is due "
                f"{at(j.run_at)} (job {j.id}, queued {at(j.created_at)}{retry})."
                f" Not a failure: it waits on {_speed(fa)}; when it runs it "
                "answers all his unanswered messages.")
    late = humanize(int((now - j.run_at).total_seconds() // 60)) if j.run_at else "?"
    return (f"- Full AI queue: a reply to {msg} was due {at(j.run_at)} and is "
            f"STILL PENDING {late} later (job {j.id}{retry}) — the queue has "
            "not run it.")


def _old_job(j: FullAiJob) -> str:
    bit = f"job {j.id} {j.status}, due {at(j.run_at)}"
    if j.anchor_at:
        bit += f", off his message of {j.anchor_at:%Y-%m-%d %H:%M:%S}"
    if j.last_error:
        bit += f", error '{clean_label(j.last_error)}'"
    if j.status == "done" and j.anchor_at and not j.decided:
        bit += (" — no decision row on that or a later message: it stood down before its "
                "Router, was busy 3 times, or found no open Turn (the reason is "
                "in the relay log only)")
    return bit


def _why(d: FullAiDecision) -> str:
    """Why a Turn sent nothing or less than all of it — reason codes only."""
    r, bits = d.reply, []
    if d.route == "no_send":
        bits.append("the Router chose no_send")
    for key, label in (("stood_down", "stood down"), ("cut", "cut")):
        v = r.get(key)
        if isinstance(v, dict):
            bits.append(f"{label} at {clean_label(str(v.get('check')))}: "
                        f"{clean_label(str(v.get('reason')))}")
    for key, label in (("floor_reason", "floor"), ("dropped_reason", "dropped"),
                       ("refusal", "sell refused"),
                       ("offer_dropped", "offer dropped")):
        if r.get(key):
            bits.append(f"{label} '{clean_label(str(r[key]))}'")
    tries = [a for a in r.get("attempts") or [] if isinstance(a, dict)]
    if d.status == "failed" and tries and not any(a.get("outcome") == "ok" for a in tries):
        bits.append("every Writer failed: " + ", ".join(
            f"{clean_label(str(a.get('writer')))} {clean_label(str(a.get('outcome')))}"
            for a in tries[:4]))
    if d.jev_error:
        bits.append(f"Router error '{clean_label(d.jev_error)}'")
    if d.status == "unconfirmed":
        bits.append("a run died mid-send; a bubble may be on OnlyFans unseen, "
                    "never re-sent")
    return (" — " + "; ".join(bits)) if bits else ""


def _full_ai_rows(fa: FullAi) -> list[str]:
    """The stored Full AI rows: his queue job(s) and his newest decisions."""
    now = datetime.utcnow()
    live = [j for j in fa.jobs if j.status in ("pending", "running")]
    out = [_job_line(fa, j, now) for j in live[:1]]
    rest = [j for j in fa.jobs if j not in live[:1]]
    if rest:
        out.append("- Full AI earlier jobs for him: "
                   + "; ".join(_old_job(j) for j in rest) + ".")
    if not fa.jobs:
        out.append("- Full AI queue: no job for him in the last 48h.")
    if fa.decisions:
        out.append("- Full AI decisions (live, newest first; a stand-down "
                   "before its Router leaves no row): "
                   + "; ".join(
                       f"{at(d.created_at)} for his message of "
                       + (f"{d.anchor_at:%Y-%m-%d %H:%M:%S}" if d.anchor_at else "?")
                       + f": {d.route}, {d.status}{_why(d)}"
                       for d in fa.decisions) + ".")
    else:
        out.append("- Full AI decisions: none live — it has never run a Turn "
                   "for him.")
    return out


def _full_ai_state(fa: FullAi) -> list[str]:
    """Is Full AI on for this Creator, and what stops it for him? ESSENTIAL."""
    if fa.off == "off_global":
        return ["- Full AI Chat: OFF on every creator — the global switch "
                "FULL_AI_CHAT_OFF is on. It answers nobody."]
    if fa.off == "off_rule":
        return ["- Full AI Chat: OFF — its rule is switched off. It answers "
                "nobody."]
    if fa.off is not None:
        return [f"- Full AI Chat: not Live — its rule is in old "
                f"{fa.mode or 'Shadow'} mode: records what it would do, sends "
                "nothing."]
    out = [f"- Full AI Chat: LIVE; {_speed(fa)}; "
           + ("his DM queues the reply at that speed" if fa.by_webhook
              else "reply_by_webhook off: only the sweep queues replies")
           + f"; its sweep re-checks every {fa.every_s}s."]
    pending = any(j.status in ("pending", "running") for j in fa.jobs)
    if fa.open_at is not None and not fa.open_decided and not pending:
        due = fa.open_due
        when = ("has no readable due time" if due is None
                else f"is due {at(due)}" if due > datetime.utcnow()
                else f"was due {at(due)}")
        out.append(f"- Full AI: his message of {at(fa.open_at)} is UNANSWERED "
                   f"with NOTHING QUEUED — no decision row, no pending job. By "
                   f"Reply speed it {when}; the sweep queues a due message "
                   "unless he is paused / leased or the check below stops him.")
    out.append("- Full AI's own check on local rows: "
               + (_stop_words(fa) + " — it will not answer him"
                  if fa.stop else "nothing stops him")
               + f". Lifetime {usd(fa.spend_cents)} vs top spend "
               + (usd(fa.top_spend_cents) if fa.top_spend_cents else "off") + "."
               + (f" Audience: {fa.audience_why}." if fa.audience_why else ""))
    return out


def _stop_words(fa: FullAi) -> str:
    """The stop's phrase; not_listed says which of its two causes it is."""
    if fa.stop == "not_listed" and not fa.fans_ok:
        return _STOP_MALFORMED
    return FULL_AI_STOP.get(fa.stop, fa.stop)


def _ago(seconds: float) -> str:
    return "<1m" if seconds < 60 else humanize(int(seconds // 60))


def _fans_line(fa: FullAi) -> str:
    """The Fans list's setting, and his membership as far as the relay's cached
    OnlyFans read knows it: a stale read is never stated as fact."""
    if not fa.fans_ok:
        return "- Full AI Fans list: stored config is malformed — nobody is listed."
    inc, exc = fa.fans.get("include") or [], fa.fans.get("exclude") or []
    if not inc and not exc:
        return "- Full AI Fans list: every fan (nothing included or excluded)."
    head = (f"- Full AI Fans list: {len(inc)} include list(s), {len(exc)} exclude "
            "list(s).")
    r = fa.fans_read
    if r is not None and r.failed_age_s is not None:
        return (f"{head} The last OnlyFans read of the list FAILED "
                f"{_ago(r.failed_age_s)} ago — Full AI treated him as not listed "
                "then; its next read may succeed.")
    if r is None or r.listed is None or r.age_s is None:
        return (f"{head} Whether he is on them is NOT known here — read on "
                "OnlyFans at reply time; a failed read = not listed.")
    if r.fresh:
        return (f"{head} OnlyFans read {_ago(r.age_s)} ago: "
                + ("he IS on it." if r.listed else
                   "he is NOT on it — Full AI will not answer him."))
    return (f"{head} Last OnlyFans read {_ago(r.age_s)} ago said he was "
            + ("" if r.listed else "NOT ")
            + "on it; a fresh read at his next Turn may differ.")
