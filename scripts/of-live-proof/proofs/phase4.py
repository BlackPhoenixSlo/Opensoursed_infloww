"""Phase 4's proofs (docs/spec/ofm-not-yet/phase-04-go-live.md): one `Proof` per track A control on the stream schedule
form (`streaming/dashboard/create`) and the dashboard (`streaming/dashboard`), each naming its sweep `page` and
`control` label, kind `live`, or `mocked` for no-OF-write and parked rows (Phase 0's format, data only). Each Phase 4
control ticket adds its own in a `# ticket NN` block; empty until then (ticket 83). Go live's (`streaming/index`) are
track B's alone, after its gate ticket (D7, D28). Its capture record is `docs/of-manager/captures/streaming--<control
-slug>.json` with the same label and page; a control ends proven, or parked with its reason ("wired, Live proof awaiting
owner go"), never by implication (story 33).

    ./venv/bin/python -I scripts/of-live-proof/proofs/phase4.py --ids | --check-records <dir> | --check-sweep <sweep> <dir>

(proof_list.py says what each does.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import Proof, Write  # noqa: E402,F401

PROOFS = ()


# ticket 84: the schedule form's right column search (Home's, bindFeedSearch), the box and its Search button: read
# proofs (empty arm, zero writes, Phase 0 story 32). Each opens the form valid (the Queue's ?date=&time= prefill, a
# far-future day), types SEARCH_TEXT and runs the search (Enter in the box, or the Search button): the rows list under
# the box, and the wire holds no write (no POST /streams). Labels as the sweep's. of_read: the two reads as the Relay
# sends them (of_reads.py search_users, search_posts; 5 of each), the users' ids then the posts'.
# ASSUMPTION: "fan" names users in both modes: FakeOF's fans (soakfan<n>, soak/fake_of/search.py) and real OnlyFans
# accounts (a common word in usernames) (inferred, rung 4); overturned by ticket 91's live run finding none, or by
# ticket 26 naming the Proof fan, whose username then replaces it.
SCHEDULE = "streaming/dashboard/create"
SEARCH_BOX = "input[name='feed-search-input']"
SEARCH_TEXT = "fan"
VALID_FORM = f"{SCHEDULE}?date=2030-01-15&time=18:30"
# prove.py waits for the first step's selector on the bare page before any step, so a focus click on the box leads.
OPEN_VALID = (("click", SEARCH_BOX), ("goto", VALID_FORM))
# phase1's FAN_TEXT ("you") names no FakeOF fan (soakfan<n>), so its _aside (FAN_TEXT fixed) is not reused whole.
from proofs.phase1 import _fans_found, _ids  # noqa: E402


def _search(get, fan=None):   # prove.run_proof calls of_read(get, fan)
    """Notifications' aside read (phase1 _aside), with SEARCH_TEXT for its FAN_TEXT."""
    posts = get("/api2/v2/posts", {"limit": 5, "query": SEARCH_TEXT, "skip_users": "all", "format": "infinite"})
    return _fans_found(get, SEARCH_TEXT) + _ids(posts, "list")


PROOFS += (
    Proof(id="p4.schedule.search-box", phase=4, page=SCHEDULE, control="Search users or posts", kind="live",
          trigger=(*OPEN_VALID, ("fill", SEARCH_BOX, SEARCH_TEXT), ("wait", 2), ("press", SEARCH_BOX, "Enter"),
                   ("wait", 2)),
          settled=("text", "#oi-search-results", "Users"), of_read=_search),
    Proof(id="p4.schedule.search-button", phase=4, page=SCHEDULE, control="Search", kind="live",
          trigger=(*OPEN_VALID, ("fill", SEARCH_BOX, SEARCH_TEXT), ("click", "button.m-search-btn"),
                   ("wait", 2)),
          settled=("text", "#oi-search-results", "Users"), of_read=_search),
)

if __name__ == "__main__":
    import proof_list
    sys.exit(proof_list.main(PROOFS, sys.argv[1:], prog="phase4.py"))
