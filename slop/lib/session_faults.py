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
BLOCKED_LOGIN = ("session outage: /auth/me answered 403 at the wire, a reload shows the sign-in form with the "
                 "[data-auth-blocked] 'Proxy blocked (403)' banner (1440x900 and 390x844, no horizontal scroll); "
                 "Retry still 403 keeps the form mounted and the typed username; 403 lifted, Retry signs in to "
                 "the shell (the browser's GET /auth/me 200 with the owner)")
HUNG_LOGIN = ("session outage: /auth/me and /chatter/me held unanswered at the wire, a cold reload shows the "
              "sign-in form with the [data-auth-blocked] 'Relay not answering' banner within ME_SLOW_MS + slack "
              "(not the 15 s abort); a late /auth/me null with /chatter/me still held keeps the form mounted "
              "(typed username kept); a late /auth/me with the owner, /chatter/me still held, is the shell")

_FILES = 2  # measured: next dev serves userSessionReducer.ts in the root layout chunk and the page chunk


def register(Fault) -> dict:
    return {
        "outage-revalidate-signs-out": Fault(None, (REVAL_KEEP,), browser=(
            (r"return \{(?:\\n|\s)*state: \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*revalidating: false(?:\\n|\s)*\},"
             r"(?:\\n|\s)*effects: \[\](?:\\n|\s)*\}",
             "return commit({ ...state, revalidating: false }, null)"),
        ), browser_files=_FILES),
        "outage-boot-signs-out": Fault(None, (BOOT_RETRY, RETRY_IN), browser=(
            (r"return \{(?:\\n|\s)*state: \{(?:\\n|\s)*\.\.\.state,(?:\\n|\s)*user: null,(?:\\n|\s)*"
             r"boot: \\?\"unreachable\\?\",(?:\\n|\s)*banner: slow \? \\?\"slow\\?\" : null,(?:\\n|\s)*"
             r"formUp: slow(?:\\n|\s)*\},(?:\\n|\s)*effects: \[\](?:\\n|\s)*\}",
             "return settleBoot(state, null)"),
        ), browser_files=_FILES),
        "auth-403-as-unreachable": Fault(None, (BLOCKED_LOGIN,), browser=(
            (r'(blocked: \\?")bootBlocked', r"\g<1>bootNetErr"),
        ), browser_files=_FILES),
        "auth-me-waits-15s": Fault(None, (HUNG_LOGIN,), browser=(
            (r'send\(\{(?:\\n|\s)*type: \\?"probeSlow\\?"(?:\\n|\s)*\}\)', "void 0"),
        ), browser_files=_FILES),
        "gate-waits-chatter-probe": Fault(None, (HUNG_LOGIN,), browser=(
            (r"if \(s\.formUp\)", "if (s.formUp && !chatter.loading)"),
        ), browser_files=_FILES),
        "late-answer-drops-form": Fault(None, (HUNG_LOGIN,), browser=(
            (r"(boot: \\?\"settled\\?\",(?:\\n|\s)*painted: null,(?:\\n|\s)*banner: null)", r"\g<1>, formUp: false"),
        ), browser_files=_FILES),
    }
