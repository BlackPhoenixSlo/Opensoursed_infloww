"""The session-outage flow's break-it-once faults (scenarios/2026-10-30-session-relay-outage.py):
lib/faults.py merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's
served JS (actors/ui.py), app/contexts/userSessionReducer.ts. The check names live here and the
scenario imports them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

LOGIN = ("session outage: the owner signs in through the sign-in form and lands in the app shell "
         "(the browser's GET /auth/me 200 with the owner, snapshot written)")
REVAL_KEEP = ("session outage: relay killed, a window focus + visibilitychange whose /auth/me fails keeps "
              "the shell (no sign-in form, no retry screen, snapshot kept)")
REVAL_BACK = ("session outage: relay restarted, a focus revalidates /auth/me 200 and the shell stays "
              "(the browser's GET /auth/me 200 with the owner)")
BOOT_RETRY = ("session outage: a reload with the relay killed shows the retry screen [data-auth-unreachable], "
              "not the sign-in form, snapshot kept; a focus there sends no /auth/me and changes nothing")
RETRY_IN = ("session outage: relay restarted, Retry on the retry screen signs back in to the shell "
            "(the browser's GET /auth/me 200 with the owner, snapshot the owner)")
LOGOUT_OUT = ("session outage: after POST /auth/logout from the browser's session, a focus revalidates to "
              "null and the sign-in form replaces the shell, snapshot cleared")

# `next dev` serves userSessionReducer.ts in the root layout's chunk and again in the page chunk
# importing UserContext: the scenario opens one page, so 2 files (measured).
_FILES = 2


def register(Fault) -> dict:
    return {
        # slop/run session-relay-outage --break (the scenario's FAULT)
        # `revalidateNetErr` signs out like a refusal: a focus while the relay is down throws the
        # owner onto the sign-in form. The same rewrite as reducers_faults' revalidate-neterror-signs-out,
        # with this flow's target. The next focus with the relay back signs in again, so only REVAL_KEEP.
        "outage-revalidate-signs-out": Fault(None, (REVAL_KEEP,), browser=(
            (r"return \{(?:\\n|\s)*state: \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*revalidating: false(?:\\n|\s)*\},"
             r"(?:\\n|\s)*effects: \[\](?:\\n|\s)*\}",
             "return commit({ ...state, revalidating: false }, null)"),
        ), browser_files=_FILES),
        # slop/run session-relay-outage --break --fault=outage-boot-signs-out
        # `bootNetErr` settles the boot signed out (the pre-0357a072c rule): a reload while the relay is
        # down shows the sign-in form and clears the snapshot, so there is no Retry to sign back in with.
        "outage-boot-signs-out": Fault(None, (BOOT_RETRY, RETRY_IN), browser=(
            (r"return \{(?:\\n|\s)*state: \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*user: null,(?:\\n|\s)*"
             r"boot: \\?\"unreachable\\?\"(?:\\n|\s)*\},(?:\\n|\s)*effects: \[\](?:\\n|\s)*\}",
             "return settleBoot(state, null)"),
        ), browser_files=_FILES),
    }
