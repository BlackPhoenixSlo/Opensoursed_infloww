"""OF rich text (service/of_rich_text.py, app/lib/ofRichText.ts, components/ui/OfRichTextEditor.tsx) checks and
break-it-once fault: lib/faults.py merges `register(Fault)` into FAULTS. scenarios/2026-10-29-state-reducers.py
(section "rich-text" and `_rich_volume`) imports the check names, so a target can never name a check that does
not exist. scenarios/2026-11-05-rich-text-sends.py (formatted scripts saved, then sent to Fansly and posted to OF)
imports the second block the same way.
"""
from __future__ import annotations

RT_SCRIPT_DESKTOP = ("rich text, desktop: a script made with the toolbar (Bold + blue on a word, Large on a line) "
                     "saves OF's markup in its saved_replies row and its row renders it formatted")
RT_SCRIPT_PHONE = ("rich text, phone 390x844: the toolbar wraps with 44px taps, no sideways scroll; a script made "
                   "by tapping it saves OF's markup and its row renders it formatted")
RT_SEND = ("rich text, chat send: the formatted script picked in Messages Pro opens formatted in the rich editor (no "
           "second preview) and reaches OF's wire as its markup; a typed plain message reaches it as plain <p> text")
RT_AA = ("rich text, chat Aa: 'Aa' shows the toolbar; a message typed and formatted there (Shift+Enter, Bold + blue, "
         "Large) reaches OF's wire as its markup and the toolbar stays on")
RT_AA_PHONE = ("rich text, chat Aa on a 390x844 phone: tapped formatting reaches OF's wire as its markup; the toolbar "
               "wraps (no sideways scroll), its tools are 44px, the text box stays on screen")
RT_MASS = ("rich text, mass composer: the formatted script picked keeps its formatting (rich editor, desktop and "
           "phone) and reaches OF's queue wire as its markup")
RT_FANSLY = ("rich text, Fansly account: no Aa and no toolbar; a formatted script goes in as its plain text and is "
             "sent plain (no OF markup on the wire)")
RT_BUBBLE = "rich text, received: a fan's formatted message (pump frame) renders formatted in its chat bubble"
RT_VOLUME = ("rich text at volume: every formatted chat and mass send reaches OF's wire byte-exact as the allow-list "
             "leaves it (foreign tags, attributes and classes gone), every plain one stays plain, none dropped")

# scenarios/2026-11-05-rich-text-sends.py
SAVED = "saved script: stored text is OF's allow-list only (route answer and saved_replies row)"
OVER = "saved script past 6500 plain characters: 400 on create and update, no row written; 6500 accepted"
FANSLY_PLAIN = "Fansly send of a formatted script: the wire content is the plain text a fan reads"
FANSLY_SENT = "Fansly sends: every one 200, exactly one POST /message each, signed, one DM group per fan"
POST_MARKUP = "OF post of a formatted script: the wire text is its sanitized markup"
SEND_ROUTE, SAVE_ROUTE = "POST /api/of/v2/chats/:id/messages", "POST /admin/saved-replies"
BUDGET = {r: f"p95 {r} at --users within the scenario's P95_MS" for r in (SEND_ROUTE, SAVE_ROUTE)}


def _unsanitized() -> None:
    """The send boundary forwards a body's markup as typed: no allow-list (sanitize = identity)."""
    import of_client
    import of_rich_text
    of_rich_text.sanitize_of_html = lambda html: html
    of_client.sanitize_of_html = lambda html: html


def _fansly_sends_markup() -> None:
    """The Fansly shim's outbound text is the word guard's only, as before the fix: OF markup goes to Fansly raw."""
    import fansly_shim
    from of_client import _guard_outbound

    fansly_shim._guard_outbound = _guard_outbound


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --no-ui --break --fault=rich-text-unsanitized
        # Only RT_VOLUME's dirty bodies differ: the UI sends clean editor markup, which the allow-list keeps as is.
        "rich-text-unsanitized": Fault(_unsanitized, (RT_VOLUME,)),
        # slop/run rich-text-sends --break
        "fansly-sends-markup": Fault(_fansly_sends_markup, (FANSLY_PLAIN,)),
        # slop/run 2026-10-29-state-reducers --break --fault=rich-pick-plain --set only=rich-text,rich-volume --baseline=<green>
        # Composer.tsx onPickTemplate: the pick no longer keeps the script's formatting (the fix reverted: rich: false),
        # so the picked script goes in plain. Only the chat send check goes red: "Aa" typing, the mass composer
        # (its own file) and Fansly (plain anyway) are untouched. Composer.tsx is in Messages Pro's chunk only.
        "rich-pick-plain": Fault(None, (RT_SEND,), browser=(
            # next dev serves each module as a JS string (eval): quotes as \", newlines as \n.
            (r'(\bact\(\{(?:\\n|\s)*type: \\"pickTemplate\\",(?:\\n|\s)*t,(?:\\n|\s)*rich: )allowRich\b', r'\1false'),
        )),
    }
