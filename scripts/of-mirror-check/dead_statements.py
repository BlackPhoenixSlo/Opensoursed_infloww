"""dead.py's Statements rows (dead.py's MODULES): tickets 20 and 24: Earning statistics' From … To button and its Apply
(PHASE1, READS, V2)."""
from datetime import date

# ticket 20
# Statements › Earning statistics' "From … To …" button ("proven": its title dropped on Live pass p1.statements.range.apply,
# D1; docs/of-manager/captures/statements--range.json) opens OF's
# Custom period picker (ofMirrorDatepicker) on today, from the Creator's start (/users/me/start-date-model, read as
# Statistics reads it; dead.py's answer has none: today only) to today: no GET, no write.
EARN20="statements/stats/earnings"
RANGE20="css:.b-stats-row__body button.m-time-period"
SNAP20="""() => ({
  picker: !!document.querySelector('[data-oi-picker] .vdatetime-popup'),
  title: document.querySelector('[data-oi-picker] .vdatetime-popup__title')?.textContent.trim() ?? null,
  next: document.querySelector('[data-oi-picker] [data-oi-month=next]')?.disabled ?? null,
  net: document.querySelector('.b-stats-row.m-expanded > .b-stats-row__head .b-stats-row__total-net')?.textContent.trim() ?? null,
  label: [...document.querySelectorAll('.b-stats-row.m-expanded .b-date-value')].map(e => e.textContent.trim()).join(' - '),
  note: document.getElementById('oi-note')?.textContent ?? null })"""
PHASE1=[(EARN20, RANGE20, "proven")]
# ticket 24
# Its Apply re-reads /payouts/stats for the picked days, OF's own startDate/endDate on the Relay too (YYYY-MM-DD, the
# owner's day: dead.py has no time zone set, so the browser's, as date.today() here), and All time then shows the range's
# totals and its days on the button; no ledger read. Only today is pickable (no Creator's start), so Apply asks today.
# ASSUMPTION: the check does not run across local midnight (the browser's today and date.today() agree); overturned by a
# flaky run at 00:00 (rung 5).
TODAY=date.today()
TODAY24=TODAY.isoformat()
LABEL24=f"{TODAY:%b} {TODAY.day}, {TODAY.year}"   # ofMirrorDatepicker's tabDate: "MMM D, YYYY"
V2={
    # All time's answer (the bare read) and the range's (startDate/endDate today); a drop of either param shows all time's.
    "/api/of/v2/payouts/stats": (lambda q: "range" if (q.get("startDate"), q.get("endDate"))==(TODAY24, TODAY24) else None,
        {"list":{"total":{"all":{"total_gross":2500,"total_net":2000}},"months":{}}},
        {"range":{"list":{"total":{"all":{"total_gross":14,"total_net":11.2},"tips":{"total_gross":14,"total_net":11.2}},"months":{}}}}),
}
READS=[
    # The button opens the picker on today (one day picked, no later month): no Relay call.
    {"page":EARN20, "steps":[("click", RANGE20)], "get":None, "settled":SNAP20,
     "shows":['"picker": true', '"title": "1 day selected"', '"next": true', '"note": null']},
    # ticket 24: its Apply closes it and reads /payouts/stats for today alone; All time shows the range's net and days.
    {"page":EARN20, "steps":[("click", RANGE20), ("click", "css:[data-oi-picker-apply]")],
     "get":[("/api/of/v2/payouts/stats", {"startDate":TODAY24, "endDate":TODAY24})], "settled":SNAP20,
     "shows":['"picker": false', '"net": "$11.20"', f'"label": "{LABEL24} - {LABEL24}"', '"note": null'],
     "hides":['"picker": true', '"net": "$2,000.00"']},
]
