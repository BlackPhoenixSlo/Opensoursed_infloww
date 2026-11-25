from datetime import date

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
TODAY=date.today()
TODAY24=TODAY.isoformat()
LABEL24=f"{TODAY:%b} {TODAY.day}, {TODAY.year}"
V2={
    "/api/of/v2/payouts/stats": (lambda q: "range" if (q.get("startDate"), q.get("endDate"))==(TODAY24, TODAY24) else None,
        {"list":{"total":{"all":{"total_gross":2500,"total_net":2000}},"months":{}}},
        {"range":{"list":{"total":{"all":{"total_gross":14,"total_net":11.2},"tips":{"total_gross":14,"total_net":11.2}},"months":{}}}}),
}
READS=[
    {"page":EARN20, "steps":[("click", RANGE20)], "get":None, "settled":SNAP20,
     "shows":['"picker": true', '"title": "1 day selected"', '"next": true', '"note": null']},
    {"page":EARN20, "steps":[("click", RANGE20), ("click", "css:[data-oi-picker-apply]")],
     "get":[("/api/of/v2/payouts/stats", {"startDate":TODAY24, "endDate":TODAY24})], "settled":SNAP20,
     "shows":['"picker": false', '"net": "$11.20"', f'"label": "{LABEL24} - {LABEL24}"', '"note": null'],
     "hides":['"picker": true', '"net": "$2,000.00"']},
]
