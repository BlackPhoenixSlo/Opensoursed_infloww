"""
The scheduled-jobs lane's decisions as pure functions (the shells:
automation_executor.run_once / _reconcile_orphans and job_queue._park_failed_job):

    bind_claim(payload_json, job_rule_id, rule_live) -> Drop(rule_id) | Bind(rule_id | None)
    park(attempts, rule_live, max_attempts) -> Cancelled | Retry(backoff_s) | Error
    outcome(kind, guard_status, err, once=, wrote=) -> (run_status, job_status, error_text)
    sends_once(kind) / one_shot_family(): the send-once kinds (ONE_SHOT_KINDS)

Send once: a ONE_SHOT_KINDS job (one human/broadcast send) is never sent twice.
Once OnlyFans may have taken its write (RunWrites, which
automation_executor.of_write_paced keeps per attempt), a failure parks it ('error',
the reason naming "may have sent") instead of requeueing it; so does a restart that
finds it running (the boot heal parks every orphaned one-shot). Every other kind
(the sweeps) requeues as before.

No DB, no clock, no executor import: the shell reads the facts (the claimed
row, the liveness of `tagged_rule(...) or job_rule_id`, the attempts) and does
what these say. The shells call them through this module (`run_decide.park(...)`), so a
slop fault patching one here is what the real run performs. Tables in
service/tests/test_run_decide.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, assert_never

from automation_registry import canonical_kind, kind_family

# `_finalize_run(job_status=)`: park the job via job_queue._park_failed_job.
JOB_RETRY = "retry"
# Payload marker on a rule's FOLLOW-ON jobs (job_queue re-exports it; see enqueue_followup).
FOLLOWUP_MARK = "_followup"
JOB_RETRY_BACKOFF_S = 60   # requeue delay after a failed attempt (park's Retry)


def parse_payload(payload_json: str | None) -> dict:
    """The payload run_once runs: a non-dict or unparsable one is {}."""
    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _rule_id_in(payload: dict) -> int | None:
    try:
        rid = payload.get("_rule_id")
        return int(rid) if rid is not None else None
    except Exception:
        return None


def payload_rule_id(payload_json: str | None) -> int | None:
    """The `_rule_id` a job's payload names (see run_once), or None."""
    return _rule_id_in(parse_payload(payload_json))


def tagged_rule(payload: dict, job_rule_id: int | None) -> int | None:
    """The rule a claimed job (its `parse_payload`) lives and dies with: a
    real-time job tagged `_rule_id` (webhook_dispatch) or a follow-on leg
    (FOLLOWUP_MARK, its rule_id). A Run-now job also carries rule_id but is
    not tagged. The shell reads the liveness of `tagged or job_rule_id`."""
    return _rule_id_in(payload) or (job_rule_id if payload.get(FOLLOWUP_MARK) else None)


@dataclass(frozen=True)
class Drop:
    """Cancel the claimed job (RULE_OFF_REASON): its tagged rule is off or gone."""
    rule_id: int


@dataclass(frozen=True)
class Bind:
    """Run it; `rule_id` is what follow-ons carry (None: a one-shot)."""
    rule_id: int | None


def bind_claim(payload_json: str | None, job_rule_id: int | None,
               rule_live: bool | None) -> Drop | Bind:
    """A tagged job on a dead rule is dropped; only a LIVE rule's run hands its
    id on (Run-now on a disabled rule runs as a one-shot). `rule_live` None:
    no rule was read."""
    tagged = tagged_rule(parse_payload(payload_json), job_rule_id)
    if tagged is not None and not rule_live:
        return Drop(tagged)
    return Bind(job_rule_id if rule_live else None)


@dataclass(frozen=True)
class Cancelled:
    """The job's rule went off/away while it ran: no requeue."""


@dataclass(frozen=True)
class Retry:
    """Back to pending, due `backoff_s` (JOB_RETRY_BACKOFF_S) from now."""
    backoff_s: float


@dataclass(frozen=True)
class Error:
    """Out of attempts: left 'error' for inspection."""


def park(attempts: int, rule_live: bool | None, max_attempts: int) -> Cancelled | Retry | Error:
    """A failed job: a retry must not outlive its rule (`rule_live` False: the
    operator switched it OFF or deleted it while this attempt ran; None: the
    job has no rule); else retry while attempts remain."""
    if rule_live is False:
        return Cancelled()
    if attempts < max_attempts:
        return Retry(JOB_RETRY_BACKOFF_S)
    return Error()


RunKind = Literal["ok", "words_blocked", "cancelled", "exception", "unknown_kind"]

# The run's OF writes (automation_executor.of_write_paced keeps it per attempt): none
# OnlyFans may have taken (none started, or each one surely refused), one in flight or
# one that ended without an answer (unanswered: a read timeout, a 5xx, a cancel while
# the call was out), or one OF answered OK (accepted).
WriteState = Literal["none", "unanswered", "accepted"]


@dataclass
class RunWrites:
    """One run's WriteState, the cell run_once hands of_write_paced (a ContextVar)."""
    state: WriteState = "none"


# Job kinds whose run is ONE send OnlyFans must never get twice: the composer's
# deferred DM, a ready-made broadcast (each resend / drip leg is its own job and
# its own send), a one-shot mass message. Not s4s_post: it guards itself (a slot
# found `posting` ends failed / interrupted_mid_post on the rerun, which a park
# would leave stuck). Not the sweeps (auto replies, welcome, follow-ups,
# priority_mass): they re-read who is owed a message, so a requeue is safe.
# A constant here, not a registry flag: automation_registry is shared by every lane
# and only these three kinds need it. Read at call time (sends_once, one_shot_family),
# so the slop fault emptying it is the pre-fix lane in run_once and the boot heal alike.
ONE_SHOT_KINDS: frozenset[str] = frozenset({"scheduled_send", "mass_premade", "send_mass_message"})

MAY_HAVE_SENT = "may have sent"
ORPHAN_REASON = f"interrupted, {MAY_HAVE_SENT}"   # a one-shot left running by a dead process
_PARK_REASON: dict[WriteState, str] = {
    "accepted": f"{MAY_HAVE_SENT}: OnlyFans took the send, then the run failed; not resent",
    "unanswered": f"{MAY_HAVE_SENT}: the OnlyFans send got no answer; not resent",
}


def sends_once(kind: str) -> bool:
    """Whether a `kind` job (a retired alias too) is one send never sent twice."""
    return canonical_kind(kind) in ONE_SHOT_KINDS


def one_shot_family() -> tuple[str, ...]:
    """Every name a stored one-shot job may carry (live names and retired aliases)."""
    return tuple(name for kind in sorted(ONE_SHOT_KINDS) for name in kind_family(kind))


def outcome(kind: RunKind, guard_status: str | None, err: str | None = None, *,
            once: bool = False, wrote: WriteState = "none") -> tuple[str, str, str | None]:
    """(run row status, job status, error text) a run ends with. `guard_status`: the
    word guard's `run_status()` when it blocked something, else None. A words block
    is never retried (the text won't get cleaner); an unknown kind consumes the job
    (error, no retry). A cancel or an exception parks the job (JOB_RETRY), except a
    one-shot (`once`, sends_once) whose write OnlyFans may have taken (`wrote` not
    "none"): 'error', never resent, its error text headed by the MAY_HAVE_SENT reason.
    `err` is the run's own error text (None on success)."""
    match kind:
        case "ok" | "words_blocked":
            return (guard_status if guard_status is not None else "ok"), "done", err
        case "cancelled" | "exception":
            if not once:
                return "error", JOB_RETRY, err
            match wrote:
                case "none":
                    return "error", JOB_RETRY, err
                case "accepted" | "unanswered":
                    return "error", "error", f"{_PARK_REASON[wrote]} ({err})"
                case _:
                    assert_never(wrote)
        case "unknown_kind":
            return "error", "error", err
        case _:
            assert_never(kind)
