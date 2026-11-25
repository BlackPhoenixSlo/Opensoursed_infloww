import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_check  # noqa: E402  (puts scripts/of-live-proof on the path)
from proofs import phase4  # noqa: E402

SCHEDULE, DASH, GO="streaming/dashboard/create", "streaming/dashboard", "streaming/index"
LANDMARKS={SCHEDULE: "Schedule", DASH: "css=a[href='/of-manager/streaming/dashboard/create']",
           GO: "Start Live Video"}
SCHEDULE_FORM=[]
DASHBOARD=[]
GO_LIVE=[]
RED_NOTES=[]
READS={}
AFTER=[]

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
    return [{"page": page, **row} for row in table]


if __name__=="__main__":
    phase_check.run("golive", phase4.PROOFS,
                    [*rows(SCHEDULE, SCHEDULE_FORM), *rows(DASH, DASHBOARD), *rows(GO, GO_LIVE)],
                    RED_NOTES, READS, AFTER, pages=LANDMARKS, one_creator_pass=True)
