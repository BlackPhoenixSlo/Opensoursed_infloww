#!/usr/bin/env python3

import _harness  # noqa: F401 — bind a temporary DB before service imports

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import of_client
import of_paging
import script_fill_decide
import vault_upload

ACCOUNT = "42"
TODAY = datetime.now(timezone.utc).date()
failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}")
    else:
        failure = f"{label}: got {got!r}, want {want!r}"
        failures.append(failure)
        print(f"  FAIL {failure}")


def schedule_row(post_id, days, text="Scheduled post"):
    return {"id": 900_000 + post_id, "type": "post",
            "publishDateTime": (TODAY + timedelta(days=days)).isoformat() + "T12:00:00Z",
            "entity": {"id": post_id, "rawText": text}}


class Calendar:
    def __init__(self, rows, *, syncing_day=None, has_more=False):
        self.rows = rows
        self.syncing_day = syncing_day
        self.has_more = has_more
        self.deleted = []
        self.listed = set()

    def schedules(self, *, publish_date, publish_date_end, limit):
        rows = [r for r in self.rows if publish_date <= r["publishDateTime"][:10] <= publish_date_end]
        if self.syncing_day and publish_date <= self.syncing_day <= publish_date_end:
            return {"list": rows, "syncInProcess": True}
        self.listed.update(r["id"] for r in rows)
        reply = {"list": rows, "syncInProcess": False}
        if rows and self.has_more:
            reply["hasMore"] = True
        return reply

    def delete_post(self, post_id):
        self.deleted.append(post_id)
        return {}


def sweep_intent(calendar):
    with TemporaryDirectory() as tmp:
        spool = Path(tmp)
        run_id = f"{ACCOUNT}-20261101T000000-ab1234"
        state_file = spool / run_id / "run.json"
        state_file.parent.mkdir()
        state = vault_upload._new_state(run_id, ACCOUNT, None)
        state.update(status="failed", finished_at=vault_upload._now(), items=[{
            "carrier_intent": {"at": state["created_at"], "marker": of_client.VAULT_MARKER},
            "carrier_post_id": None,
        }])
        state_file.write_text(json.dumps(state))
        with patch.multiple(vault_upload, SPOOL_ROOT=spool, LOCK_DIR=spool / "locks",
                            STAGE_ROOT=spool / "incoming"):
            vault_upload.sweep(lambda account: calendar)
        item = json.loads(state_file.read_text())["items"][0]
        return bool(item.get("carrier_scan_clear"))


def case_f1a():
    carriers = [schedule_row(101, 4, of_client.VAULT_MARKER),
                schedule_row(102, of_client.CARRIER_DAYS, of_client.VAULT_MARKER)]
    busy_day = (TODAY + timedelta(days=8)).isoformat()
    busy_rows = [schedule_row(1000 + i, 8) for i in range(of_paging.SCHEDULE_PAGE)]
    for label, calendar in [
        ("syncInProcess", Calendar(carriers, syncing_day=busy_day)),
        ("full day", Calendar(carriers + busy_rows)),
    ]:
        cleared = sweep_intent(calendar)
        far_carrier_listed = carriers[-1]["id"] in calendar.listed
        check(f"F1a {label}: reach far carrier, delete both carriers, keep intent pending",
              (far_carrier_listed, sorted(calendar.deleted), cleared), (True, [101, 102], False))


def case_f1b():
    row = schedule_row(201, 4)
    unreadable = {
        "null entity": {**row, "entity": None},
        "no post ID": {**row, "entity": {"rawText": of_client.VAULT_MARKER}},
        "unknown type": {**row, "type": "unknown"},
    }
    cleared = {label: sweep_intent(Calendar([bad_row])) for label, bad_row in unreadable.items()}
    check("F1b: unevaluable schedule rows must keep the on-disk intent pending",
          cleared, dict.fromkeys(unreadable, False))


def case_f1c():
    calendar = Calendar([schedule_row(301, 4, of_client.VAULT_MARKER)], has_more=True)
    cleared = sweep_intent(calendar)
    check("F1c: delete the visible carrier and keep intent pending when hasMore is true",
          (calendar.deleted, cleared), ([301], False))


def case_f1d():
    row = schedule_row(401, 4)
    cases = {
        "no text field": ({**row, "entity": {"id": 401}}, False),
        "text None": ({**row, "entity": {"id": 401, "rawText": None, "text": None}}, False),
        "plain text, no marker": (row, True),
    }
    got = {}
    for label, (r, _) in cases.items():
        calendar = Calendar([r])
        got[label] = (sweep_intent(calendar), calendar.deleted)
    check("F1d: a post row without text keeps the intent pending, nothing deleted",
          got, {label: (want, []) for label, (_, want) in cases.items()})


def case_f38():
    carrier = schedule_row(501, 10, of_client.VAULT_MARKER)
    half = of_paging.SCHEDULE_PAGE // 2
    busy = ([schedule_row(5000 + i, 9) for i in range(half)]
            + [schedule_row(6000 + i, 11) for i in range(half)])

    class Cut(Calendar):
        def schedules(self, *, publish_date, publish_date_end, limit):
            reply = super().schedules(publish_date=publish_date,
                                      publish_date_end=publish_date_end, limit=limit)
            span = (datetime.fromisoformat(publish_date_end)
                    - datetime.fromisoformat(publish_date)).days
            if span > 1:
                reply["list"] = [{**r, "entity": {"id": r["entity"]["id"]}}
                                 if r is carrier else r for r in reply["list"]]
            return reply

    calendar = Cut([carrier] + busy)
    cleared = sweep_intent(calendar)
    check("F38: the day re-read's marker row wins over the cut chunk's text-less row",
          (calendar.deleted, cleared), ([501], True))


def case_f39():
    carrier = schedule_row(601, of_client.CARRIER_DAYS, of_client.VAULT_MARKER)

    class Bad(Calendar):
        def schedules(self, *, publish_date, publish_date_end, limit):
            if publish_date <= TODAY.isoformat() <= publish_date_end:
                raise RuntimeError("HTTP 502")
            return super().schedules(publish_date=publish_date,
                                     publish_date_end=publish_date_end, limit=limit)

    calendar = Bad([carrier])
    cleared = sweep_intent(calendar)
    check("F39: a failed early chunk does not stop the walk; carrier deleted, intent pending",
          (calendar.deleted, cleared), ([601], False))


def case_f4():
    rows = [
        {"id": 1, "script_id": "Intro", "script_step": 1, "text": "a video", "price_cents": 1000},
        {"id": 2, "script_id": "Intro", "script_step": 2, "text": "a photo", "price_cents": 1500},
    ]
    fields = {"people_count": 1, "partner_visible": False, "clothing_state": "lingerie_on",
              "explicitness": "suggestive", "acts": ["posing"], "penetration": "none",
              "underwear_visible": True, "vulva_vis": "covered", "breasts_vis": "covered",
              "over_vulva": "panties", "over_breasts": "bra"}
    items = [script_fill_decide.effective({
        "media_id": media_id, "kind": kind, "account_id": ACCOUNT, "describe_status": "described",
        "fields": fields, "folder_cents": 1000, "created_at": datetime(2026, 11, 1, 12, media_id),
        "duration_seconds": duration,
    }) for media_id, kind, duration in [(11, "video", 12), (12, "photo", None)]]
    for row, item in zip(rows, items):
        control = script_fill_decide.plan_over_vault([row], [item], account_id=ACCOUNT)
        check(f"F4 setup: Step {row['script_step']} can use its item on its own",
              (control["status"], control["options"][0]["media"]), ("ok", [item["media_id"]]))

    plan = script_fill_decide.plan_over_vault(rows, items, account_id=ACCOUNT)
    check("F4: the required clip goes to Step 1 and the photo goes to Step 2",
          (plan["status"], {o["step"]: o["media"] for o in plan["options"]}),
          ("ok", {1: [11], 2: [12]}))


if __name__ == "__main__":
    case_f1a()
    case_f1b()
    case_f1c()
    case_f1d()
    case_f38()
    case_f39()
    case_f4()
    if failures:
        print(f"{len(failures)} failed")
        sys.exit(1)
    print("All W30 script-fill service regressions passed")
