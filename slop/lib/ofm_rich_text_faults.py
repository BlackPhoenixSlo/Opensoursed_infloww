"""OF Manager (the OF mirror) rich text checks and break-it-once fault: lib/faults.py merges `register(Fault)` into
FAULTS. scenarios/2026-10-29-state-reducers.py (section "ofm-rich-text") imports the check names, so a target can never
name a check that does not exist.
"""
from __future__ import annotations

OFM_CHAT_DESKTOP = ("OF Manager chat, desktop: a formatted script picked in the Scripts column fills OF's editor "
                    "formatted, Send puts its markup on OF's wire byte-exact and the sent bubble renders it formatted; "
                    "a plain script picked after it reaches the wire as plain <p> text")
OFM_CHAT_PHONE = ("OF Manager chat, phone 390x844: the header's Scripts picker (the header row not overlapping) puts a "
                  "formatted script in OF's editor formatted and Send puts its markup on OF's wire byte-exact; the frame never "
                  "scrolls sideways and OF's Send sits fully inside it, before and after Send")
OFM_CHAT_TYPED = ("OF Manager chat, typed with its own Format text toolbar (no script): words selected and formatted "
                  "(desktop), and Large + Bold armed on an empty caret then typed (desktop and phone), each Send puts "
                  "OF's wire shape (span > strong) on the wire byte-exact and the sent bubble renders Large and bold")
OFM_BUBBLE = ("OF Manager chat: a fan's formatted message renders formatted in its bubble (colour, weight) and the "
              "chat list's last message shows its words, no tag")
OFM_MASS = ("OF Manager New message, desktop: Format text (Bold + Light blue on a word, Large on a line) "
            "-> Send puts the markup on OF's mass queue wire byte-exact")
OFM_POST = ("OF Manager New post (desktop and phone): Format text (Bold + Light blue on a word, Large on a line) "
            "-> Post puts the markup on OF's posts wire byte-exact")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --set only=ofm-rich-text --break --fault=ofm-script-drops-format
        # The fix reverted: a picked script goes on the mirror's Chat draft without its markup (plain text only).
        "ofm-script-drops-format": Fault(None, (OFM_CHAT_DESKTOP, OFM_CHAT_PHONE), browser=(
            (r"html: t\.displayText && [^\n]*?\? t\.displayText\.trim\(\) : undefined", "html: undefined"),
        ), browser_files=2),  # next dev serves it in the of-manager layout's chunk and the page's
        # slop/run 2026-10-29-state-reducers --set only=ofm-rich-text --break --fault=ofm-caret-unarmed --baseline=<green>
        # The fix reverted: a Format text tool on an empty caret arms nothing (it says "Select some text to format"),
        # so text typed after Large + Bold goes plain. Only the typed check goes red: script picks, New message and
        # New post format selected words.
        "ofm-caret-unarmed": Fault(None, (OFM_CHAT_TYPED,), browser=(
            (r"\(caret \? (\(0,[^)]*formatAtCaret\)|formatAtCaret)\(", r"(false ? \1("),
        ), browser_files=2),  # ofMirrorPost: in the of-manager layout's chunk and the page's, as applyScript
    }
