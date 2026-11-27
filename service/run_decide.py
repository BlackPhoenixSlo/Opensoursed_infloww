from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, assert_never

from automation_registry import canonical_kind, kind_family
from side_effect_gate import PLATFORM_LACKS_PREFIX, PLATFORM_UNKNOWN_PREFIX

JOB_RETRY = "retry"
FOLLOWUP_MARK = "_followup"
JOB_RETRY_BACKOFF_S = 60


def parse_payload(payload_json: str | None) -> dict:
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
    return _rule_id_in(parse_payload(payload_json))


def tagged_rule(payload: dict, job_rule_id: int | None) -> int | None:
    return _rule_id_in(payload) or (job_rule_id if payload.get(FOLLOWUP_MARK) else None)


@dataclass(frozen=True)
class Drop:
    rule_id: int


@dataclass(frozen=True)
class Bind:
    rule_id: int | None


def bind_claim(payload_json: str | None, job_rule_id: int | None,
               rule_live: bool | None) -> Drop | Bind:
    tagged = tagged_rule(parse_payload(payload_json), job_rule_id)
    if tagged is not None and not rule_live:
        return Drop(tagged)
    return Bind(job_rule_id if rule_live else None)


@dataclass(frozen=True)
class Cancelled:
    pass


@dataclass(frozen=True)
class Retry:
    backoff_s: float


@dataclass(frozen=True)
class Error:
    pass


def park(attempts: int, rule_live: bool | None, max_attempts: int,
         backoff_s: float = JOB_RETRY_BACKOFF_S) -> Cancelled | Retry | Error:
    if rule_live is False:
        return Cancelled()
    if attempts < max_attempts:
        return Retry(backoff_s)
    return Error()


RunKind = Literal["ok", "words_blocked", "cancelled", "exception", "unknown_kind"]

WriteState = Literal["none", "unanswered", "accepted"]


@dataclass
class RunWrites:
    state: WriteState = "none"


# Kinds whose run is ONE send OF must never get twice (composer deferred DM, ready-made broadcast, one-shot mass); sweeps re-read who is owed, so a requeue is safe. Not s4s_post: it guards itself.
ONE_SHOT_KINDS: frozenset[str] = frozenset({"scheduled_send", "mass_premade", "send_mass_message"})

MAY_HAVE_SENT = "may have sent"
ORPHAN_REASON = f"interrupted, {MAY_HAVE_SENT}"
RESTORE_REASON = f"{MAY_HAVE_SENT} (restore)"
_PARK_REASON: dict[WriteState, str] = {
    "accepted": f"{MAY_HAVE_SENT}: OnlyFans took the send, then the run failed; not resent",
    "unanswered": f"{MAY_HAVE_SENT}: the OnlyFans send got no answer; not resent",
}


# Proxy refusals where nothing reached OF are retried PROXY_RETRY_MINUTES out; `proxy_retry:<n>` tags are read back by `proxy_tries`.
PROXY_REFUSED = "proxy_refused"
PROXY_RETRY = "proxy_retry"
PROXY_RETRIES = 3
PROXY_RETRY_MINUTES = 5
PROXY_DEFER_KINDS: frozenset[str] = frozenset({"mass_premade", "send_mass_message"})


def defers_refusal(kind: str, refused: bool, wrote: WriteState) -> bool:
    return refused and wrote == "none" and canonical_kind(kind) in PROXY_DEFER_KINDS


def proxy_retry_reason(n: int, err: str) -> str:
    return f"{PROXY_RETRY}:{n} ({err})"


def proxy_refused_reason(err: str) -> str:
    return f"{PROXY_REFUSED} ({err})"


def proxy_tries(reason: str | None) -> int:
    head, _, rest = (reason or "").partition(":")
    n = rest.split(" ", 1)[0]
    return int(n) if head == PROXY_RETRY and n.isdigit() else 0


def sends_once(kind: str) -> bool:
    return canonical_kind(kind) in ONE_SHOT_KINDS


def one_shot_family() -> tuple[str, ...]:
    return tuple(name for kind in sorted(ONE_SHOT_KINDS) for name in kind_family(kind))


def outcome(kind: RunKind, guard_status: str | None, err: str | None = None, *,
            once: bool = False, wrote: WriteState = "none",
            plugin_reason: object = None) -> tuple[str, str, str | None]:
    match kind:
        case "ok" | "words_blocked":
            if guard_status == "skipped":
                return "skipped", "done", "sensitive_words"
            if isinstance(plugin_reason, str) and plugin_reason.startswith(
                    (PLATFORM_LACKS_PREFIX, PLATFORM_UNKNOWN_PREFIX)):
                return "skipped", "done", plugin_reason
            if plugin_reason == "fan_held":
                return "skipped", "done", "fan_held"
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
