#!/usr/bin/env python3
"""
Dead-session pause — an OF "Wrong user." rejection flags the account, the
executor skips every run for it, and the recovery probe / a re-capture
resumes it (service/account_health.py + the run_once gate).

  case_classifier_only_matches_dead_signatures:
      "Wrong user." OFAPIError and the no-captured-session FileNotFoundError
      classify as session-dead; a 404 OFAPIError, a plain ValueError and a
      generic FileNotFoundError do NOT.
  case_wrong_user_run_marks_account:
      an automation raising the "Wrong user." OFAPIError writes an error run
      AND flags the account session-dead.
  case_flagged_account_skips_every_kind:
      run_once on the flagged account returns skipped/session_unlinked for a
      DIFFERENT kind, without invoking the automation or writing a run row.
  case_other_account_unaffected:
      the same kind still runs fine on a healthy account.
  case_non_session_error_not_marked:
      a 404 OFAPIError errors the run but does NOT flag the account.
  case_no_session_file_marks_account:
      a missing session dir (account deleted / never captured) flags the
      account and subsequent runs skip.
  case_probe_recovers_account:
      _probe_dead_sessions with a working fake client clears the flag; the
      next run_once executes normally again.
  case_probe_failure_keeps_pause_and_rate_limits:
      a still-dead probe keeps the flag AND stamps last_probe_at so the next
      sweep inside the probe window skips the account (no OF hammering).
  case_probe_interval_widens_with_age:
      the backoff ladder: a fresh death probes at the base interval, a day-old
      one slower, a week-old one slower still — and it never goes BELOW base.
  case_long_dead_account_is_not_probed_at_the_base_interval:
      an account dead for weeks whose last probe was one base interval ago is
      NOT due (that is the ~4k-wasted-calls-a-month case), while a freshly
      dead account in the same sweep IS.
  case_dead_session_map_carries_reason:
      the /admin/accounts stamp exposes both the instant and the reason, so the
      UI can name the repair instead of just "something is wrong".
  case_otp_state_counts_only_on_a_400:
      the otpState body on a status other than 400 does not classify.
  case_the_first_reason_stays_while_dead:
      a second failure with another reason keeps the reason the owner was told.
  case_classifier_flags_otp_state:
      OF's HTTP 400 code 101 with `error.payload.otpState` (the login now needs
      a 2FA code) classifies as "otp_required", from OFClient's message and
      from the throughput scripts' one-line form; code 105 (OF's per-request
      step-up, retried after the code) and a 101 without otpState do NOT.
  case_otp_run_marks_account_and_pauses:
      an automation raising that 101 writes an error run, flags the account
      with reason "otp_required", and the next run of another kind skips.

Run: ./venv/bin/python service/tests/test_session_health.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import account_health  # noqa: E402
import automation_executor as ax  # noqa: E402
from automation_registry import register  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountHealth, AutomationRun  # noqa: E402
from of_client import OFAPIError  # noqa: E402

WRONG_USER_ERR = (
    "400 for https://onlyfans.com/api2/v2/users/me\n"
    '{"error":{"code":301,"message":"Wrong user."}}'
)

# OF's answer once the login needs a 2FA code: HTTP 400, error code 101 and the
# OTP state under `error.payload` (OF web's own interceptor reads
# `error.payload.otpState` and `error.payload.strong` on a 101 and opens its 2FA
# modal titled `error.message`; the message text here is invented).
OTP_BODY = (
    '{"error":{"code":101,"message":"Confirm it is you","payload":{"otpState":'
    '{"email":false,"phoneOtp":false,"appOtp":true,"faceOtp":false,"forceFaceOtp":false,'
    '"phoneLast4":"","phoneCode":{},"faceCode":{},"emailCode":{}},"strong":false}}}'
)
OTP_ERR = f"400 for https://onlyfans.com/api2/v2/users/me\n{OTP_BODY}"

CALLS = {"noop": 0}


@register("t_fail_wrong_user")
async def _t_fail_wrong_user(account_id: str, payload: dict, *, run_id: int) -> dict:
    raise OFAPIError(WRONG_USER_ERR)


@register("t_fail_not_found")
async def _t_fail_not_found(account_id: str, payload: dict, *, run_id: int) -> dict:
    raise OFAPIError("404 for https://onlyfans.com/api2/v2/vault/media\nMedia Not Found")


@register("t_fail_no_session")
async def _t_fail_no_session(account_id: str, payload: dict, *, run_id: int) -> dict:
    # Exact OFClient.from_account wording — the session dir is missing
    # entirely (account deleted / never captured on this host).
    raise FileNotFoundError(
        f"Account {account_id!r} has no captured session. "
        f"Run the bootstrap (paste-curl) for this account first."
    )


@register("t_fail_otp")
async def _t_fail_otp(account_id: str, payload: dict, *, run_id: int) -> dict:
    raise OFAPIError(OTP_ERR)


@register("t_noop")
async def _t_noop(account_id: str, payload: dict, *, run_id: int) -> dict:
    CALLS["noop"] += 1
    return {"did": "noop"}


class _FakeMeOK:
    def me(self) -> dict:
        return {"id": 12345}


class _FakeMeDead:
    def me(self) -> dict:
        raise OFAPIError(WRONG_USER_ERR)


async def _runs_for(account_id: str, kind: str) -> list[AutomationRun]:
    async with get_session() as s:
        return (await s.execute(
            select(AutomationRun).where(
                AutomationRun.account_id == account_id,
                AutomationRun.kind == kind,
            )
        )).scalars().all()


def case_classifier_only_matches_dead_signatures() -> None:
    assert account_health.is_session_dead_error(OFAPIError(WRONG_USER_ERR)) == "wrong_user"
    assert account_health.is_session_dead_error(
        FileNotFoundError("Account '267492960' has no captured session. Run the bootstrap ...")
    ) == "no_session"
    assert account_health.is_session_dead_error(OFAPIError("404 ... Media Not Found")) is None
    assert account_health.is_session_dead_error(ValueError("Wrong user")) is None
    # A generic missing file inside an automation must NOT pause the account.
    assert account_health.is_session_dead_error(FileNotFoundError("/tmp/media.jpg")) is None


async def case_wrong_user_run_marks_account() -> None:
    aid = "acct_dead"
    out = await ax.run_once(aid, "t_fail_wrong_user", payload={})
    assert out["status"] == "error", f"expected error run, got {out}"
    assert await account_health.is_session_dead(aid), "account not flagged session-dead"
    runs = await _runs_for(aid, "t_fail_wrong_user")
    assert len(runs) == 1 and runs[0].status == "error"


async def case_flagged_account_skips_every_kind() -> None:
    aid = "acct_dead"  # flagged by the previous case
    assert await account_health.is_session_dead(aid)
    before = CALLS["noop"]
    out = await ax.run_once(aid, "t_noop", payload={})
    assert out == {"status": "skipped", "reason": "session_unlinked"}, f"got {out}"
    assert CALLS["noop"] == before, "automation body ran on a paused account"
    assert await _runs_for(aid, "t_noop") == [], "skip must not write a run row"


async def case_other_account_unaffected() -> None:
    out = await ax.run_once("acct_alive", "t_noop", payload={})
    assert out["status"] == "ok", f"healthy account should run, got {out}"


async def case_non_session_error_not_marked() -> None:
    aid = "acct_flaky"
    out = await ax.run_once(aid, "t_fail_not_found", payload={})
    assert out["status"] == "error"
    assert not await account_health.is_session_dead(aid), \
        "a non-session OF error must not pause the account"


async def case_no_session_file_marks_account() -> None:
    aid = "acct_deleted"
    out = await ax.run_once(aid, "t_fail_no_session", payload={})
    assert out["status"] == "error"
    assert await account_health.is_session_dead(aid), \
        "a missing session dir must pause the account"
    out = await ax.run_once(aid, "t_noop", payload={})
    assert out == {"status": "skipped", "reason": "session_unlinked"}, f"got {out}"


async def case_probe_recovers_account() -> None:
    aid = "acct_dead"
    assert await account_health.is_session_dead(aid)
    real_make = ax._make_client
    ax._make_client = lambda _aid: _FakeMeOK()  # type: ignore[assignment]
    try:
        await ax._probe_dead_sessions()
    finally:
        ax._make_client = real_make  # type: ignore[assignment]
    assert not await account_health.is_session_dead(aid), "probe success must clear the flag"
    out = await ax.run_once(aid, "t_noop", payload={})
    assert out["status"] == "ok", f"recovered account should run again, got {out}"


async def case_probe_failure_keeps_pause_and_rate_limits() -> None:
    aid = "acct_dead2"
    await account_health.mark_session_dead(aid, "wrong_user")
    real_make = ax._make_client
    probes = {"n": 0}

    def _dead_client(_aid: str) -> _FakeMeDead:
        probes["n"] += 1
        return _FakeMeDead()

    ax._make_client = _dead_client  # type: ignore[assignment]
    try:
        await ax._probe_dead_sessions()
        assert probes["n"] == 1, "first sweep probes the account"
        assert await account_health.is_session_dead(aid), "failed probe must keep the pause"
        # Immediately again: last_probe_at was just stamped → inside the probe
        # window → the account is NOT probed a second time.
        await ax._probe_dead_sessions()
        assert probes["n"] == 1, "second sweep inside the window must not re-probe"
    finally:
        ax._make_client = real_make  # type: ignore[assignment]


async def _backdate(
    account_id: str, *, dead_ago: timedelta, probed_ago: timedelta,
) -> None:
    """Age an account's health row. The backoff ladder keys off
    `session_dead_at` and the due check off `last_probe_at`, so a test of their
    INTERACTION has to be able to set both."""
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            update(AccountHealth)
            .where(AccountHealth.account_id == account_id)
            .values(
                session_dead_at=now - dead_ago,
                last_probe_at=now - probed_ago,
            )
        )


def case_probe_interval_widens_with_age() -> None:
    base = 600
    assert account_health.probe_interval_s(base, timedelta(minutes=5)) == base
    assert account_health.probe_interval_s(base, timedelta(hours=3)) == base * 3
    assert account_health.probe_interval_s(base, timedelta(days=3)) == base * 6
    assert account_health.probe_interval_s(base, timedelta(days=30)) == base * 36
    # Clock skew (a dead_at stamped in the future) must land in the FIRST
    # bucket, never below base and never in some negative-index surprise.
    assert account_health.probe_interval_s(base, timedelta(seconds=-99)) == base
    ladder = [
        account_health.probe_interval_s(base, d)
        for d in (timedelta(seconds=-99), timedelta(minutes=5), timedelta(hours=3),
                  timedelta(days=3), timedelta(days=30))
    ]
    assert ladder == sorted(ladder), f"backoff must never shrink with age: {ladder}"
    assert min(ladder) >= base, f"backoff must never dip below base: {ladder}"


async def case_long_dead_account_is_not_probed_at_the_base_interval() -> None:
    base = 600
    await account_health.mark_session_dead("acct_stale", "no_session")
    await account_health.mark_session_dead("acct_fresh", "no_session")
    # Both were last probed one base interval ago. The only difference is HOW
    # LONG they have been dead — a month vs ten minutes.
    await _backdate("acct_stale", dead_ago=timedelta(days=30),
                    probed_ago=timedelta(seconds=base + 5))
    await _backdate("acct_fresh", dead_ago=timedelta(minutes=10),
                    probed_ago=timedelta(seconds=base + 5))
    due = await account_health.due_probe_ids(base)
    assert "acct_fresh" in due, "a freshly dead account must keep probing fast"
    assert "acct_stale" not in due, \
        "a month-dead account must NOT be re-probed every base interval"
    # Backoff widens the gap; it must not park the account forever.
    await _backdate("acct_stale", dead_ago=timedelta(days=30),
                    probed_ago=timedelta(seconds=base * 36 + 5))
    assert "acct_stale" in await account_health.due_probe_ids(base), \
        "a long-dead account must still be probed once its own interval elapses"


async def case_dead_session_map_carries_reason() -> None:
    await account_health.mark_session_dead("acct_map", "wrong_user")
    m = await account_health.dead_session_map()
    row = m.get("acct_map")
    assert row is not None, "a flagged account must appear in the map"
    assert row.reason == "wrong_user", f"reason not exposed to the UI: {row}"
    assert (row.at or "").endswith("Z"), f"instant must be an ISO-Z stamp: {row}"
    # A never-flagged account is ABSENT, not present-with-null — a listing
    # endpoint falls back to the null object, which stamps both fields None.
    assert "acct_alive" not in m, "healthy accounts must not appear in the map"
    fallback = m.get("acct_alive", account_health.NO_DEAD_SESSION)
    assert fallback.at is None and fallback.reason is None, \
        "the healthy-account fallback must stamp nothing"


def case_classifier_flags_otp_state() -> None:
    assert account_health.is_session_dead_error(OFAPIError(OTP_ERR)) == "otp_required"
    # scripts/throughput builds the error as `OFAPIError(f"{status} {body}")`.
    assert account_health.is_session_dead_error(OFAPIError(f"400 {OTP_BODY}")) == "otp_required"
    # OF's per-request step-up (code 105, otpState at the top of `error`) is
    # answered by retrying THAT request with the code: not a dead session.
    step_up = '{"error":{"code":105,"message":"Confirm","otpState":{"appOtp":true}}}'
    assert account_health.is_session_dead_error(
        OFAPIError(f"400 for https://onlyfans.com/api2/v2/users/me\n{step_up}")) is None
    # A 101 without the OTP state is not the 2FA signature: stay strict.
    assert account_health.is_session_dead_error(
        OFAPIError('400 for https://onlyfans.com/api2/v2/users/me\n{"error":{"code":101,"message":"x"}}')) is None
    # "otpState" in some other error's text is not it either.
    assert account_health.is_session_dead_error(
        OFAPIError('400 for https://onlyfans.com/api2/v2/x\n{"error":{"code":100,"message":"otpState"}}')) is None
    assert account_health.is_session_dead_error(ValueError(OTP_ERR)) is None

    # OFAPIError's message keeps 500 chars of the body; the response it carries has it all.
    class _Resp:
        status_code = 400

        def json(self):
            return json.loads(OTP_BODY)
    cut = OFAPIError(f"400 for https://onlyfans.com/api2/v2/users/me\n{OTP_BODY[:60]}", response=_Resp())
    assert account_health.is_session_dead_error(cut) == "otp_required"


def case_otp_state_counts_only_on_a_400() -> None:
    # OF answers its 2FA demand with HTTP 400. The same body on any other status
    # (a proxy's 403 page echoing it, a 200 relayed by a test double) is not it.
    class _Resp:
        def __init__(self, status: int):
            self.status_code = status

        def json(self):
            return json.loads(OTP_BODY)
    for status in (200, 403, 500):
        e = OFAPIError(f"{status} for https://onlyfans.com/api2/v2/users/me\n{OTP_BODY}", response=_Resp(status))
        assert account_health.is_session_dead_error(e) is None, status
        assert account_health.is_session_dead_error(OFAPIError(f"{status} {OTP_BODY}")) is None, status


async def case_the_first_reason_stays_while_dead() -> None:
    # The owner was told why (the notification, the badge); a later caller's
    # different failure on the same dead session must not rewrite it.
    aid = "acct_reason"
    assert await account_health.mark_session_dead(aid, "otp_required")
    assert not await account_health.mark_session_dead(aid, "wrong_user")
    assert (await account_health.dead_session_map())[aid].reason == "otp_required"


async def case_otp_run_marks_account_and_pauses() -> None:
    aid = "acct_otp"
    out = await ax.run_once(aid, "t_fail_otp", payload={})
    assert out["status"] == "error", f"expected error run, got {out}"
    assert await account_health.is_session_dead(aid), "an otpState 101 must pause the account"
    m = await account_health.dead_session_map()
    assert m[aid].reason == "otp_required", m.get(aid)
    before = CALLS["noop"]
    out = await ax.run_once(aid, "t_noop", payload={})
    assert out == {"status": "skipped", "reason": "session_unlinked"}, f"got {out}"
    assert CALLS["noop"] == before and await _runs_for(aid, "t_noop") == []


_harness.run(
    case_classifier_only_matches_dead_signatures,
    case_classifier_flags_otp_state,
    case_otp_state_counts_only_on_a_400,
    case_the_first_reason_stays_while_dead,
    case_otp_run_marks_account_and_pauses,
    case_wrong_user_run_marks_account,
    case_flagged_account_skips_every_kind,
    case_other_account_unaffected,
    case_non_session_error_not_marked,
    case_no_session_file_marks_account,
    case_probe_recovers_account,
    case_probe_failure_keeps_pause_and_rate_limits,
    case_probe_interval_widens_with_age,
    case_long_dead_account_is_not_probed_at_the_base_interval,
    case_dead_session_map_carries_reason,
)
