#!/usr/bin/env python3
"""The `s4s_post` automation: a due S4S slot posts on its own Creator's
account through Auto Post, behind the live-posting flag
(docs/spec/phase-03-share-for-share.md, Interfaces and Testing Decisions;
ticket 19).

The seam is the one `test_auto_posts.py` uses: the automation is run directly
(`s4s_post.run`, and once through the executor's `run_once` on the job Accept
queued) with the of-client patched to a fake, so no OnlyFans call is
possible. Slots are booked over HTTP (send, then Accept) on the two-Agency
bench; a request cannot be sent for a past time, so each case then moves its
slots' `slot_at` into the past straight in the temp DB. `S4S_LIVE_POSTING`
defaults on; it is set only inside this process, per call (`with_env`). Every case books on its
own UTC days, so one case never fills another's Daily limit.

Run: ./venv/bin/python service/tests/test_s4s_post.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, update  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402 — the shared _make_client seam
import automations.s4s_post as s4s_post  # noqa: E402 — module under test (registers)
from _s4s_fixtures import IDS, audit_rows, db, list_in_discovery, profile, seed_creators, with_env  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automation_registry import get_automation, load_automation_plugins  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import S4SSlot, ScheduledJob, User, UserAccount  # noqa: E402

A = IDS["creator_a"]
B = IDS["creator_b"]
P1, P2 = "1000031", "1000032"   # the opt-out pair (Agency A, Agency B)
X, LEAVER = "1000033", "1000034"  # LEAVER (Agency B) later leaves every Agency
X2, ORPHAN = "1000035", "1000036"  # ORPHAN's Agency C is later deleted
seed_creators({P1: "agency_a_owner", P2: "agency_b_owner", X: "agency_a_owner", LEAVER: "agency_b_owner",
               X2: "agency_a_owner", ORPHAN: "agency_c_owner"}, users=("agency_c_owner",))

OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
OWNER_C = fx.login_owner("agency_c_owner")

NAMES = {A: ("Fixture Alpha", "fixture_alpha"), B: ("Fixture Beta", "fixture_beta"),
         P1: ("Fixture Pine", "fixture_pine"), P2: ("Fixture Pond", "fixture_pond"),
         X: ("Fixture Xeno", "fixture_xeno"), LEAVER: ("Fixture Leaving", "fixture_leaving"),
         X2: ("Fixture Xylo", "fixture_xylo"), ORPHAN: ("Fixture Orphan", "fixture_orphan")}
OWNER_OF = {A: OWNER_A, P1: OWNER_A, X: OWNER_A, X2: OWNER_A, B: OWNER_B, P2: OWNER_B, LEAVER: OWNER_B,
            ORPHAN: OWNER_C}
CAPTION = {aid: list_in_discovery(OWNER_OF[aid], aid, *NAMES[aid]) for aid in NAMES}
PID = {aid: profile(OWNER_OF[aid], aid)["profile_id"] for aid in NAMES}

FLAG = "S4S_LIVE_POSTING"


class Fakes:
    """One fake of-client per account, all recording into one list: each
    create_post call with the account whose client made it."""

    def __init__(self, result=None, raises: Exception | None = None, during_post=None):
        self.calls: list[dict] = []
        self.deletes: list[tuple[str, int]] = []
        self._next = 70000
        self._result = result
        self._raises = raises
        # Called inside create_post, which Auto Post runs in a worker thread
        # (ax.of_write_with_retry: asyncio.to_thread(fn)), so it may commit
        # through the `db` fixture while the run's post call is in flight.
        self._during_post = during_post
        ax._make_client = self._client  # type: ignore[attr-defined]
        ax._next_write_at.clear()  # no 11s spacing left over from an earlier case's post

    def _client(self, account_id):
        fakes = self

        class Client:
            user_id = "999"

            def create_post(self, text, media_files=None, price=0, previews=None):
                fakes.calls.append({"account_id": account_id, "text": text, "media_files": list(media_files or []),
                                    "price": price})
                if fakes._during_post is not None:
                    fakes._during_post()
                if fakes._raises is not None:
                    raise fakes._raises
                if fakes._result is not None:
                    return fakes._result
                fakes._next += 1
                return {"id": fakes._next}

            def delete_post(self, post_id):
                fakes.deletes.append((account_id, int(post_id)))
                return {"success": True}

        return Client()


def day(n: int, hour: int = 10) -> datetime:
    """`n` UTC days after today, at hour:00 UTC."""
    today = datetime.utcnow().date()
    return datetime(today.year, today.month, today.day) + timedelta(days=n, hours=hour)


def z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _rows(model, **where) -> list:
    async with get_session() as s:
        q = select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return list((await s.execute(q.order_by(model.id))).scalars().all())


def rows(model, **where) -> list:
    return asyncio.run(_rows(model, **where))


def slot(slot_id: int) -> S4SSlot:
    (row,) = rows(S4SSlot, id=slot_id)
    return row


def booked(from_id: str, to_id: str, n: int, late: timedelta = timedelta(minutes=1)) -> dict[str, S4SSlot]:
    """Send and accept one request for day `n`, then move both slots to `late`
    before now (a request cannot be sent for a past time). The slots by poster."""
    r = OWNER_OF[from_id].post("/admin/s4s/requests", json={
        "from_account_id": from_id, "to_profile_id": PID[to_id], "slot_at": z(day(n))})
    assert r.status_code == 201, f"send {from_id}→{to_id}: {r.status_code} {r.text}"
    request_id = r.json()["id"]
    r = OWNER_OF[to_id].post(f"/admin/s4s/requests/{request_id}/accept")
    assert r.status_code == 200, f"accept: {r.status_code} {r.text}"
    db(update(S4SSlot).where(S4SSlot.request_id == request_id).values(slot_at=datetime.utcnow() - late))
    return {s.poster_account_id: s for s in rows(S4SSlot, request_id=request_id)}


def run(account_id: str, slot_id: int) -> dict:
    return asyncio.run(s4s_post.run(account_id, {"slot_id": slot_id}, run_id=0))


def run_live(account_id: str, slot_id: int) -> dict:
    return with_env(FLAG, "1", lambda: run(account_id, slot_id))


def run_off(account_id: str, slot_id: int) -> dict:
    return with_env(FLAG, "0", lambda: run(account_id, slot_id))


def reads(client, sl: S4SSlot) -> tuple:
    first = datetime(sl.slot_at.year, sl.slot_at.month, 1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    r = client.get(f"/admin/s4s/schedule?from={z(first)}&to={z(nxt)}")
    assert r.status_code == 200, f"GET schedule: {r.status_code} {r.text}"
    (item,) = [i for i in r.json() if i["id"] == sl.id]
    return item["status"], item["display_status"], item["reason"]


def state(slot_id: int) -> tuple:
    row = slot(slot_id)
    return row.status, row.reason


def last_audit(action: str, slot_id: int) -> tuple:
    """(account_id, employee_id, payload) of the newest `action` row on this slot."""
    found = [a for a in audit_rows(action) if a.target_type == "s4s_slot" and a.target_id == str(slot_id)]
    assert found, f"no {action} row for slot {slot_id}"
    return found[-1].account_id, found[-1].employee_id, json.loads(found[-1].payload_json)


# ── Registration ─────────────────────────────────────────────────────

def case_s4s_post_is_the_registered_runner_for_the_jobs_accept_queues():
    load_automation_plugins()
    assert get_automation("s4s_post") is s4s_post.run


# ── The live-posting flag ────────────────────────────────────────────

def case_with_the_flag_set_off_a_due_slot_ends_canceled_live_posting_off_with_zero_calls():
    fakes = Fakes()
    slots = booked(A, B, 1)
    mine = slots[A]
    res = run_off(A, mine.id)
    assert res["status"] == "skipped", res
    assert state(mine.id) == ("canceled", "live posting off")
    assert fakes.calls == [], fakes.calls
    assert reads(OWNER_A, mine) == ("canceled", "Canceled", "live posting off")
    account_id, employee_id, payload = last_audit("s4s.slot_cancel", mine.id)
    assert (account_id, employee_id) == (A, None)
    assert (payload["slot_id"], payload["request_id"], payload["reason"]) == (
        mine.id, mine.request_id, "live posting off"), payload
    assert payload["agency_user_id"] == IDS["agency_a_owner"], payload
    # A canceled slot is left alone, flag or no flag.
    run_live(A, mine.id)
    assert state(mine.id) == ("canceled", "live posting off") and fakes.calls == []


def case_the_flag_is_read_on_every_call_never_at_import():
    fakes = Fakes()
    slots = booked(A, B, 2)
    assert run_off(B, slots[B].id)["status"] == "skipped"
    assert fakes.calls == [] and state(slots[B].id) == ("canceled", "live posting off")
    # The same imported module, the flag now unset in this process: on by default, it posts.
    assert FLAG not in os.environ
    assert run(A, slots[A].id)["status"] == "ok"
    assert len(fakes.calls) == 1 and state(slots[A].id)[0] == "posted"


def case_with_the_flag_on_it_posts_once_on_the_posters_own_account_and_queues_the_24h_removal():
    fakes = Fakes()
    slots = booked(A, B, 3)
    mine, theirs = slots[B], slots[A]  # B posts A's caption; A posts B's
    before = datetime.utcnow()
    res = run_live(B, mine.id)
    assert res["status"] == "ok", res

    assert len(fakes.calls) == 1, fakes.calls
    call = fakes.calls[0]
    assert call["account_id"] == B, f"posted on {call['account_id']}, not the poster's own account"
    assert call["text"].startswith(CAPTION[A]) and call["text"].endswith("@fixture_alpha\n#advertisement"), call["text"]
    assert call["text"] == f"{mine.text}\n#advertisement" and (call["media_files"], call["price"]) == ([], 0), call

    row = slot(mine.id)
    assert row.status == "posted" and row.reason is None, (row.status, row.reason)
    assert row.post_id is not None and row.of_post_id == 70001, (row.post_id, row.of_post_id)
    assert row.posted_at is not None and before - timedelta(seconds=1) <= row.posted_at <= datetime.utcnow()
    assert abs((row.remove_at - row.posted_at) - timedelta(hours=24)) < timedelta(seconds=2), row.remove_at
    assert state(theirs.id) == ("scheduled", None), "the partner's slot was touched"

    (unsend,) = rows(ScheduledJob, kind="unsend_messages", account_id=B)
    assert unsend.status == "pending", unsend.status
    hours = (unsend.run_at - datetime.utcnow()).total_seconds() / 3600
    assert 23.9 < hours < 24.1, hours
    target = json.loads(unsend.payload_json)["targets"][0]
    assert (target["post_id"], target["local_post_id"]) == (70001, row.post_id), target

    account_id, employee_id, payload = last_audit("s4s.slot_post", mine.id)
    assert (account_id, employee_id) == (B, None)
    assert payload["agency_user_id"] == IDS["agency_b_owner"], payload
    assert (payload["slot_id"], payload["request_id"], payload["post_id"], payload["of_post_id"]) == (
        mine.id, mine.request_id, row.post_id, 70001), payload
    assert CAPTION[A] not in json.dumps(payload), "the audit row carries the caption"

    # A posted slot is never posted again.
    assert run_live(B, mine.id)["status"] == "skipped"
    assert len(fakes.calls) == 1

    # "In progress" until the unsend automation deletes the post, then "Completed".
    assert reads(OWNER_B, mine) == ("posted", "In progress", None)
    db(update(ScheduledJob).where(ScheduledJob.id == unsend.id).values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    done = asyncio.run(run_once(B, "unsend_messages"))
    assert done["status"] == "ok", done
    assert fakes.deletes == [(B, 70001)], fakes.deletes
    assert reads(OWNER_B, mine) == ("posted", "Completed", None)


def case_the_executor_runs_the_job_accept_queued_and_marks_it_done():
    fakes = Fakes()
    mine = booked(A, B, 4)[B]
    db(update(ScheduledJob).where(ScheduledJob.id == mine.job_id).values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    res = with_env(FLAG, "1", lambda: asyncio.run(run_once(B, "s4s_post")))
    assert res["status"] == "ok" and res["job_id"] == mine.job_id, res
    assert [c["account_id"] for c in fakes.calls] == [B], fakes.calls
    assert state(mine.id) == ("posted", None)
    (job,) = rows(ScheduledJob, id=mine.job_id)
    assert job.status == "done", job.status


def case_a_slot_runs_only_on_its_posters_account():
    fakes = Fakes()
    slots = booked(A, B, 5)
    res = run_live(A, slots[B].id)  # the partner's account names B's slot
    assert res["status"] == "skipped", res
    assert fakes.calls == [] and state(slots[B].id) == ("scheduled", None)


# ── The #advertisement tag ───────────────────────────────────────────

def case_each_side_posts_the_partners_caption_its_mention_and_the_advertisement_tag_last():
    """Infloww: "Infloww will automatically insert #advertisement at the end
    of each post." Each poster's text names the OTHER Creator, whose @mention
    OnlyFans renders as the link to onlyfans.com/<partner>."""
    fakes = Fakes()
    slots = booked(A, B, 15)
    assert run_live(A, slots[A].id)["status"] == "ok"
    assert run_live(B, slots[B].id)["status"] == "ok"
    by_poster = {c["account_id"]: c["text"] for c in fakes.calls}
    assert by_poster == {A: f"{CAPTION[B]}\n@fixture_beta\n#advertisement",
                         B: f"{CAPTION[A]}\n@fixture_alpha\n#advertisement"}, by_poster
    # The tag is added at post time; the slot keeps the caption plus @mention.
    assert slot(slots[A].id).text == f"{CAPTION[B]}\n@fixture_beta", slot(slots[A].id).text
    assert slot(slots[B].id).text == f"{CAPTION[A]}\n@fixture_alpha", slot(slots[B].id).text


def case_the_advertisement_tag_is_never_added_twice():
    assert s4s_post._advertised("hi\n@x") == "hi\n@x\n#advertisement"
    once = s4s_post._advertised("hi\n@x")
    assert s4s_post._advertised(once) == once, s4s_post._advertised(once)
    assert s4s_post._advertised(once + "\n  ") == once
    # A slot whose text already ends with the tag posts it once, and its retry posts nothing.
    fakes = Fakes()
    mine = booked(A, B, 16)[A]
    db(update(S4SSlot).where(S4SSlot.id == mine.id).values(text=f"{mine.text}\n#advertisement"))
    assert run_live(A, mine.id)["status"] == "ok"
    assert run_live(A, mine.id)["status"] == "skipped"
    assert [c["text"].count("#advertisement") for c in fakes.calls] == [1], fakes.calls


# ── Interrupted, missed, failed ──────────────────────────────────────

def case_a_slot_left_mid_post_ends_failed_interrupted_with_zero_calls():
    fakes = Fakes()
    mine = booked(A, B, 6)[A]
    db(update(S4SSlot).where(S4SSlot.id == mine.id).values(status="posting"))
    run_live(A, mine.id)
    assert state(mine.id) == ("failed", "interrupted_mid_post")
    assert fakes.calls == []
    assert reads(OWNER_A, mine) == ("failed", "Failed", "interrupted_mid_post")
    account_id, _, payload = last_audit("s4s.slot_fail", mine.id)
    assert account_id == A and payload["agency_user_id"] == IDS["agency_a_owner"], payload
    assert (payload["slot_id"], payload["request_id"], payload["reason"]) == (
        mine.id, mine.request_id, "interrupted_mid_post"), payload
    run_live(A, mine.id)
    assert fakes.calls == [] and state(mine.id) == ("failed", "interrupted_mid_post")


def case_a_run_24_hours_or_more_late_ends_canceled_missed_with_zero_calls():
    fakes = Fakes()
    late = booked(A, B, 7, late=timedelta(hours=24, seconds=5))
    run_live(A, late[A].id)
    assert state(late[A].id) == ("canceled", "missed")
    assert fakes.calls == []
    # Just under a day late still posts.
    nearly = booked(A, B, 8, late=timedelta(hours=23, minutes=50))
    assert run_live(A, nearly[A].id)["status"] == "ok"
    assert [c["account_id"] for c in fakes.calls] == [A]


def case_an_error_result_ends_failed_with_its_reason():
    fakes = Fakes(result={})  # OF answered without a post id
    mine = booked(A, B, 9)[A]
    res = run_live(A, mine.id)
    assert res["status"] == "error", res
    assert len(fakes.calls) == 1
    assert state(mine.id) == ("failed", "no_post_id")
    assert reads(OWNER_A, mine) == ("failed", "Failed", "no_post_id")
    account_id, _, payload = last_audit("s4s.slot_fail", mine.id)
    assert account_id == A and payload["reason"] == "no_post_id", payload
    assert run_live(A, mine.id)["status"] == "skipped" and len(fakes.calls) == 1


def case_a_raised_post_call_ends_failed_and_the_retry_posts_nothing():
    fakes = Fakes(raises=RuntimeError("of_error 500"))
    mine = booked(A, B, 10)[A]
    try:
        run_live(A, mine.id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("the post call's error was swallowed; the executor would never see it")
    assert len(fakes.calls) == 1
    status, reason = state(mine.id)
    assert status == "failed" and "of_error 500" in reason, (status, reason)
    assert "of_error 500" in last_audit("s4s.slot_fail", mine.id)[2]["reason"]
    # The executor's retry finds a failed slot and posts nothing.
    run_live(A, mine.id)
    assert len(fakes.calls) == 1 and state(mine.id)[0] == "failed"


def case_a_slot_another_run_failed_mid_post_is_neither_recorded_posted_nor_ok():
    """The posted step is status-guarded like every other: a slot some other
    run marked `failed` while this run's post call was in flight keeps that
    end, gets no `s4s.slot_post` row, and the run does not answer ok."""
    mine = booked(A, B, 14)[A]
    # The other run's `interrupted_mid_post`, committed while this run's post call is in flight.
    fakes = Fakes(during_post=lambda: db(update(S4SSlot).where(S4SSlot.id == mine.id)
                                         .values(status="failed", reason="interrupted_mid_post")))
    res = run_live(A, mine.id)
    assert len(fakes.calls) == 1, fakes.calls
    assert res["status"] != "ok", res
    row = slot(mine.id)
    assert (row.status, row.reason, row.post_id, row.posted_at) == ("failed", "interrupted_mid_post", None, None), (
        row.status, row.reason, row.post_id, row.posted_at)
    assert not [a for a in audit_rows("s4s.slot_post") if a.target_id == str(mine.id)], "a failed slot got s4s.slot_post"


# ── Opt-out and departed Creators ────────────────────────────────────

def case_after_an_opt_out_both_slots_end_canceled_with_zero_calls():
    fakes = Fakes()
    slots = booked(P1, P2, 11)
    r = OWNER_B.put(f"/admin/s4s/profiles/{P2}", json={"opted_in": False})
    assert r.status_code == 200, f"opt out: {r.status_code} {r.text}"
    assert state(slots[P2].id) == ("scheduled", None), "the cascade cancels future slots only"
    run_live(P1, slots[P1].id)
    run_live(P2, slots[P2].id)
    assert fakes.calls == [], fakes.calls
    assert state(slots[P1].id) == ("canceled", "partner_opted_out")
    assert state(slots[P2].id) == ("canceled", "opted_out")
    assert last_audit("s4s.slot_cancel", slots[P1].id)[2]["reason"] == "partner_opted_out"


def case_after_a_creator_leaves_every_agency_both_slots_end_canceled_with_zero_calls():
    fakes = Fakes()
    slots = booked(X, LEAVER, 12)
    db(delete(UserAccount).where(UserAccount.account_id == LEAVER))
    run_live(X, slots[X].id)
    run_live(LEAVER, slots[LEAVER].id)
    assert fakes.calls == [], fakes.calls
    assert state(slots[X].id) == ("canceled", "partner_opted_out")
    assert state(slots[LEAVER].id) == ("canceled", "no_agency")
    account_id, _, payload = last_audit("s4s.slot_cancel", slots[LEAVER].id)
    assert account_id == LEAVER and payload["agency_user_id"] is None, payload


def case_after_a_creators_agency_is_deleted_both_slots_end_canceled_with_zero_calls():
    fakes = Fakes()
    slots = booked(X2, ORPHAN, 13)
    db(delete(User).where(User.username == "agency_c_owner"))
    run_live(X2, slots[X2].id)
    run_live(ORPHAN, slots[ORPHAN].id)
    assert fakes.calls == [], fakes.calls
    assert state(slots[X2].id) == ("canceled", "partner_opted_out")
    assert state(slots[ORPHAN].id) == ("canceled", "no_agency")


_harness.run()
