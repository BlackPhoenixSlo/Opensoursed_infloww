import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_core import Proof, Write  # noqa: E402,F401

PROOFS = ()


SCHEDULE = "streaming/dashboard/create"
SEARCH_BOX = "input[name='feed-search-input']"
SEARCH_TEXT = "fan"
VALID_FORM = f"{SCHEDULE}?date=2030-01-15&time=18:30"
OPEN_VALID = (("click", SEARCH_BOX), ("goto", VALID_FORM))
from proofs.phase1 import _fans_found, _ids  # noqa: E402


def _search(get, fan=None):
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
