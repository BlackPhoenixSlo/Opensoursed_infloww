"""OF rich text (service/of_rich_text.py, app/lib/ofRichText.ts, components/ui/OfRichTextEditor.tsx) checks and
break-it-once fault: lib/faults.py merges `register(Fault)` into FAULTS. scenarios/2026-10-29-state-reducers.py
(section "rich-text" and `_rich_volume`) imports the check names, so a target can never name a check that does
not exist.
"""
from __future__ import annotations

RT_SCRIPT_DESKTOP = ("rich text, desktop: a script made with the toolbar (Bold + blue on a word, Large on a line) "
                     "saves OF's markup in its saved_replies row and its row renders it formatted")
RT_SCRIPT_PHONE = ("rich text, phone 390x844: the toolbar wraps with 44px taps, no sideways scroll; a script made "
                   "by tapping it saves OF's markup and its row renders it formatted")
RT_SEND = ("rich text, chat send: the formatted script picked in Messages Pro shows its preview and reaches OF's "
           "wire as its markup; a typed plain message reaches it as plain <p> text")
RT_BUBBLE = "rich text, received: a fan's formatted message (pump frame) renders formatted in its chat bubble"
RT_VOLUME = ("rich text at volume: every formatted chat and mass send reaches OF's wire byte-exact as the allow-list "
             "leaves it (foreign tags, attributes and classes gone), every plain one stays plain, none dropped")


def _unsanitized() -> None:
    """The send boundary forwards a body's markup as typed: no allow-list (sanitize = identity)."""
    import of_client
    import of_rich_text
    of_rich_text.sanitize_of_html = lambda html: html
    of_client.sanitize_of_html = lambda html: html


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-29-state-reducers --no-ui --break --fault=rich-text-unsanitized
        # Only RT_VOLUME's dirty bodies differ: the UI sends clean editor markup, which the allow-list keeps as is.
        "rich-text-unsanitized": Fault(_unsanitized, (RT_VOLUME,)),
    }
