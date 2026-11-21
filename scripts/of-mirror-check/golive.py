"""Phase 4's Mirror check (docs/spec/ofm-not-yet/phase-04-go-live.md, Testing Decisions): the stream schedule form
(streaming/dashboard/create), the dashboard (streaming/dashboard) and Go live (streaming/index), relay mocked, on
phase_check.py's harness (its docstring: mocks, table rows, checks, --plant, --captures). Nothing for Go live itself is
built here (D7, ticket 83).

Its control list is the Phase 4 proof list (scripts/of-live-proof/proofs/phase4.py PROOFS: page, control as the Not-yet
sweep labels it), each control's capture record found as `phase4.py --check-sweep` finds it (check 1, runtime state,
D18): a control whose record holds a Live-proof pass has no Not-yet title, every other listed control still has it (D1).
Each Phase 4 track A control ticket adds its Proof there and its rows here, in its own `# ticket NN` block:
SCHEDULE_FORM and DASHBOARD (control, click, then its expected request with X-Account-Id 1 from its proof's capture
record, or zero requests: harness `requests` rows on this table's page), RED_NOTES, READS/AFTER (the mocked reads a write changes). GO_LIVE (streaming/index, `requests` rows) is
filled only by track B's follow-ups, after its gate ticket closes (D7, D28). Whatever the tables hold, the check loads
the three pages, each showing its LANDMARKS control, with no console errors. Then phase_check's one_creator (run here
only: a saved "all" scope posts as the first creator with a live session, unsaved).
Screenshots: /tmp/of-mirror-shots/inapp-golive-*.png. Exit 1 on a failed check.

    PORT=3091 python3 -I scripts/of-mirror-check/golive.py [--plant rows.json] [--captures dir]
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_check  # noqa: E402  (puts scripts/of-live-proof on the path)
from proofs import phase4  # noqa: E402

SCHEDULE, DASH, GO="streaming/dashboard/create", "streaming/dashboard", "streaming/index"
# A control each page shows with every table empty (harness `pages`): a 404 or blank frame fails.
LANDMARKS={SCHEDULE: "Schedule", DASH: "css=a[href='/of-manager/streaming/dashboard/create']",  # its Schedule link
           GO: "Start Live Video"}
SCHEDULE_FORM=[]  # {"steps", "want": [[method, path, body]]} ([] = zero requests) or {"proof", "steps", "fill"}
DASHBOARD=[]      # as SCHEDULE_FORM, on streaming/dashboard
GO_LIVE=[]        # as SCHEDULE_FORM, on streaming/index: track B's follow-ups only (D7)
RED_NOTES=[]      # {"page", "steps", "fail": [method, path], "kept": js, "note": text}
READS={}          # GET /api/of/v2/<path> -> JSON
AFTER=[]          # (method, path regex, fn(reads, match, body))

# ticket 84: the schedule form's right column search (Home's), the box and its Search button (check 1: Wired, Not-yet
# title kept, no Live-proof pass). On the form opened valid (the Queue's ?date=&time= prefill, a far-future day), typing
# then Search lists the mocked rows, each linking to its OF profile, and sends nothing (no POST /streams). Enter is
# dead.py's row (dead_golive.py: the harness steps only click or type).
SEARCH_BOX, SEARCH_BTN="css=input[name='feed-search-input']", "css=button.m-search-btn"
_fan=lambda i: {"id": i, "name": f"Synthetic Fan {i}", "username": f"u_synthetic_{i}", "avatar": None}
READS.update({"/api/of/v2/users/search": [_fan(9101), _fan(9102)],
              "/api/of/v2/posts/search": [{"id": 9201, "text": "<p>Synthetic post</p>", "author": _fan(9101)}]})
SCHEDULE_FORM+=[{"page": f"{SCHEDULE}?date=2030-01-15&time=18:30", "steps": [[SEARCH_BOX, "synth"], SEARCH_BTN], "want": [],
                 "after": ["""[[...document.querySelectorAll('#oi-search-results a')].map((a) => [a.textContent.trim(),
                              a.getAttribute('href')]), document.querySelector("input[name='date']")?.value]""",
                           [[["Synthetic Fan 9101 @u_synthetic_9101", "https://onlyfans.com/u_synthetic_9101"],
                             ["Synthetic Fan 9102 @u_synthetic_9102", "https://onlyfans.com/u_synthetic_9102"],
                             ["Synthetic post · @u_synthetic_9101", "https://onlyfans.com/u_synthetic_9101"]],
                            "Jan 15, 2030"]]}]


def rows(page, table):
    """A table's rows as harness `requests` rows on the table's page."""
    return [{"page": page, **row} for row in table]


if __name__=="__main__":
    phase_check.run("golive", phase4.PROOFS,
                    [*rows(SCHEDULE, SCHEDULE_FORM), *rows(DASH, DASHBOARD), *rows(GO, GO_LIVE)],
                    RED_NOTES, READS, AFTER, pages=LANDMARKS, one_creator_pass=True)
