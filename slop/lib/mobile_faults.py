from __future__ import annotations

# JS files `next dev` serves swipeGesture.ts/useSwipe.ts in: one per chunk that pulls them in
SWIPE_FILES = 2

TAP_LANDS = ("phone: a tap during a swiped-away nav menu's slide lands on the page under it, and the menu "
             "unmounts within budget of going off screen")
TAP_FIELD = ("phone: a tap on a text field during a swiped-away nav menu's slide leaves the field focused "
             "(the menu's focus trap let go)")
CHAT_FORWARD = ("phone: Forward onto an open chat's history entry stays on it (Fan List, entry unmarked, no bounce) "
                "and the next Forward reaches the later page")
CHAT_SWIPE_BACK = ("phone: a swipe right on an open chat returns to the Fan List through its history entry "
                   "(Messages Pro kept, the entry popped, nothing else navigated)")


def register(Fault) -> dict:
    return {
        "mobile-chat-no-history-entry": Fault(None, (
            "phone: opening a chat adds one same-URL history entry; back returns to the Fan List on Messages Pro, "
            "and a second back leaves it",
            CHAT_FORWARD,
            CHAT_SWIPE_BACK,
        ), browser=((r"window\.history\.pushState(?=\(\{(?:\\n|\s)*\[CHAT_ENTRY\])", "(() => {})"),)),
        "mobile-chat-forward-bounce": Fault(None, (
            CHAT_FORWARD,
        ), browser=((r"window\.history\.replaceState(?=\(unmarked\(\))", "(() => popOnce())"),)),
        "mobile-swipe-ignores-turn": Fault(None, (
            "phone: a drag that starts sideways, turns vertical and ends sideways does not open the nav menu",
        ), browser=((r"else if \(!s\.sheet && Math\.abs\(dy\) >= Math\.abs\(dx\)\)", "else if (false)"),
                    (r"if \(!a\.own \|\|", "if (true || !a.own ||")),
            browser_files=SWIPE_FILES),
        "mobile-sheet-dismisses-at-half": Fault(None, (
            "phone: the nav menu dragged slowly to 60% of its width and let go springs back open",
        ), browser=((r"SWIPE_DISMISS_AT = 0\.75", "SWIPE_DISMISS_AT = 0.55"),), browser_files=SWIPE_FILES),
        "mobile-sheet-slow-settle": Fault(None, (
            "phone: the nav menu dragged slowly to 80% of its width and let go closes, unmounted within budget of the release",
        ), browser=((r"duration: out \? Math\.min\(ms, DISMISS_MS\) : ms", "duration: out ? 1500 : ms"),),
            browser_files=SWIPE_FILES),
        "mobile-sheet-ignores-speed": Fault(None, (
            "phone: a short quick flick (60px) on the nav menu closes it",
            TAP_LANDS,
            TAP_FIELD,
            CHAT_SWIPE_BACK,
            "phone: a swipe right on Fan insights closes it and only it (the chat stays open)",
        ), browser=((r"releaseDismisses\(s\.pos, velocity, width, s\.dismissAt\)", "releaseDismisses(s.pos, 0, width, s.dismissAt)"),),
            browser_files=SWIPE_FILES),
        "mobile-sheet-velocity-unsigned": Fault(None, (
            "phone: the nav menu dragged to 85% then flicked back stays open",
        ), browser=((r"sign \* releaseVelocity\(samples, a\.t\)", "Math.abs(releaseVelocity(samples, a.t))"),),
            browser_files=SWIPE_FILES),
        "mobile-sheet-unmounts-late": Fault(None, (
            TAP_LANDS,
        ), browser=((r"springKeyframes\(from, to, velocity, out \? width : undefined\)", "springKeyframes(from, to, velocity, out ? to : undefined)"),),
            browser_files=SWIPE_FILES),
        "mobile-sheet-holds-body": Fault(None, (
            TAP_LANDS,
            TAP_FIELD,
        ), browser=((r"&& !others\.length\)", "&& false)"),),
            browser_files=SWIPE_FILES),
        "mobile-ghost-taken-for-dialog": Fault(None, (
            "phone: the copy a backdrop tap leaves behind is not taken for an open dialog, so the open "
            "swipe made while it is there opens the menu",
        ), browser=((r"OPEN_DIALOG = [^;]*?\(DIALOGS\)", "OPEN_DIALOG = DIALOGS"),), browser_files=SWIPE_FILES),
        "mobile-drawer-traps-focus": Fault(None, (
            TAP_LANDS,
            TAP_FIELD,
        ), browser=((r"(onLetGo: [^}]*?)dispatchDrawer\(", r"\1void ("),), browser_files=1),
    }
