"""Mobile gestures' break-it-once faults (client side, checked by scenarios/2026-10-26-mobile-gestures.py):
lib/faults.py merges `register(Fault)` into FAULTS. Every one rewrites the app's served JS (`browser=`).
The check names more than one fault targets are named once here (the scenario spells its own).
"""
from __future__ import annotations

# How many JS files `next dev` serves app/hooks/swipeGesture.ts and useSwipe.ts in (one per chunk that pulls
# them in: the shell's layout, Messages Pro's page; useExitGhost no longer pulls them into the dashboard's).
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
        # slop/run mobile-gestures --break (client side)
        # app/hooks/useChatBackEntry.ts: no history entry when a Thread opens on a phone, as before
        # 2026-10-26. Back from an open chat leaves Messages Pro, and the Thread's swipe right no longer
        # goes through an entry (it still returns to the Fan List); the drawer swipes, Fan insights'
        # swipe, the pin, the reload and desktop checks stay green.
        "mobile-chat-no-history-entry": Fault(None, (
            "phone: opening a chat adds one same-URL history entry; back returns to the Fan List on Messages Pro, "
            "and a second back leaves it",
            CHAT_FORWARD,
            CHAT_SWIPE_BACK,
        ), browser=((r"window\.history\.pushState(?=\(\{(?:\\n|\s)*\[CHAT_ENTRY\])", "(() => {})"),)),
        # app/hooks/useChatBackEntry.ts: Forward onto the chat's entry (no chat open) goes back again, as
        # before 2026-10-27, so it bounces and every entry after it is out of reach. Back, the reload (a
        # fresh mount still pops) and the Thread swipe stay green.
        "mobile-chat-forward-bounce": Fault(None, (
            CHAT_FORWARD,
        ), browser=((r"window\.history\.replaceState(?=\(unmarked\(\))", "(() => popOnce())"),)),
        # app/hooks/swipeGesture.ts `swipeReducer` (move, scroll): once a move locks sideways, a later vertical
        # move and a scroll of what the finger is on no longer cancel it, as before 2026-10-27: a drag that
        # turned into a scroll still opens the nav menu if it ends sideways. Every straight swipe stays green.
        # `next dev` serves the module once per chunk that pulls it in (the shell's layout, Messages Pro's page...).
        "mobile-swipe-ignores-turn": Fault(None, (
            "phone: a drag that starts sideways, turns vertical and ends sideways does not open the nav menu",
        ), browser=((r"else if \(!s\.sheet && Math\.abs\(dy\) >= Math\.abs\(dx\)\)", "else if (false)"),
                    (r"if \(!a\.own \|\|", "if (true || !a.own ||")),
            browser_files=SWIPE_FILES),
        # app/hooks/swipeGesture.ts, the sheet gesture (2026-10-29). Each turns only its own check red.
        # `SWIPE_DISMISS_AT`: the dismiss line at 55% instead of 75%: the nav menu let go at 60% closes.
        "mobile-sheet-dismisses-at-half": Fault(None, (
            "phone: the nav menu dragged slowly to 60% of its width and let go springs back open",
        ), browser=((r"SWIPE_DISMISS_AT = 0\.75", "SWIPE_DISMISS_AT = 0.55"),), browser_files=SWIPE_FILES),
        # `settlePlan`: a dismissal's slide takes 1500ms (no DISMISS_MS cap): a sheet let go at 80% unmounts
        # ~4x past the 350ms budget. Spring backs are untouched, and the closing checks wait for the slide.
        "mobile-sheet-slow-settle": Fault(None, (
            "phone: the nav menu dragged slowly to 80% of its width and let go closes, unmounted within budget of the release",
        ), browser=((r"duration: out \? Math\.min\(ms, DISMISS_MS\) : ms", "duration: out ? 1500 : ms"),),
            browser_files=SWIPE_FILES),
        # `swipeReducer` (end): position alone decides (no projection, no flick): the 60px flick springs back, and
        # so do the Thread's and Fan insights' swipes, which reach only 54% and 66% of their width but are quick,
        # and the taps-through' 50px throws (the menu stays, so each tap lands on it).
        "mobile-sheet-ignores-speed": Fault(None, (
            "phone: a short quick flick (60px) on the nav menu closes it",
            TAP_LANDS,
            TAP_FIELD,
            CHAT_SWIPE_BACK,
            "phone: a swipe right on Fan insights closes it and only it (the chat stays open)",
        ), browser=((r"releaseDismisses\(s\.pos, velocity, width, s\.dismissAt\)", "releaseDismisses(s.pos, 0, width, s.dismissAt)"),),
            browser_files=SWIPE_FILES),
        # `swipeReducer` (end): speed without its direction: a flick back toward open reads as a flick out and closes.
        "mobile-sheet-velocity-unsigned": Fault(None, (
            "phone: the nav menu dragged to 85% then flicked back stays open",
        ), browser=((r"sign \* releaseVelocity\(samples, a\.t\)", "Math.abs(releaseVelocity(samples, a.t))"),),
            browser_files=SWIPE_FILES),
        # `settlePlan`: the slide runs on past the screen edge (to width + 40px) before `onSwipe`, as before
        # 2026-10-29: the menu is gone from view but still mounted.
        "mobile-sheet-unmounts-late": Fault(None, (
            TAP_LANDS,
        ), browser=((r"springKeyframes\(from, to, velocity, out \? width : undefined\)", "springKeyframes(from, to, velocity, out ? to : undefined)"),),
            browser_files=SWIPE_FILES),
        # app/hooks/useSwipe.ts `letGo`: a decided dismissal keeps the modal drawer's Radix hold on <body>
        # (pointer-events: none) until it unmounts, as before 2026-10-30: a tap during the slide lands on nothing,
        # a text field's included. Matched without the line's quotes: next dev serves the module as an eval string,
        # where they are escaped.
        "mobile-sheet-holds-body": Fault(None, (
            TAP_LANDS,
            TAP_FIELD,
        ), browser=((r"&& !others\.length\)", "&& false)"),),
            browser_files=SWIPE_FILES),
        # app/hooks/useSwipe.ts `OPEN_DIALOG`: the open-dialog lookup does not skip a leaving copy
        # (`useExitGhost`'s, which keeps the dialog's role for ~260ms; no `notInGhost`): the shell's open swipe
        # (ignoreWhile OPEN_DIALOG) takes a backdrop tap's copy for a dialog and ignores the swipe.
        "mobile-ghost-taken-for-dialog": Fault(None, (
            "phone: the copy a backdrop tap leaves behind is not taken for an open dialog, so the open "
            "swipe made while it is there opens the menu",
        ), browser=((r"OPEN_DIALOG = [^;]*?\(DIALOGS\)", "OPEN_DIALOG = DIALOGS"),), browser_files=SWIPE_FILES),
        # app/components/shell/AppShell.tsx `onLetGo`: a swipe's release leaves the drawer's Radix layer open,
        # focus trap and all, until it unmounts, as before 2026-10-30: a tap on a text field in the page during
        # the slide is pulled back into the drawer, and a tap's outside click closes it at once (its slide cut
        # short). Lazy up to the first dispatch after `onLetGo:`, whatever `next dev` wraps the callback in.
        "mobile-drawer-traps-focus": Fault(None, (
            TAP_LANDS,
            TAP_FIELD,
        ), browser=((r"(onLetGo: [^}]*?)dispatchDrawer\(", r"\1void ("),), browser_files=1),
    }
