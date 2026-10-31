"""Inbound turn helpers: reaction tags, worded-inbound filter, TurnHandoff."""
from __future__ import annotations

from dataclasses import dataclass

from tip_ledger import TIP_LEDGER_PREFIX
from db.models import Message


# ── Reactions that are NOT her turn ─────────────────────────────────────────
# An outbound row whose `automation_kind` is one of these is a REACTION to
# something HE did — a freebie answering his photo, a bundle answering his tip.
# It is a real send (it belongs in the history the model reads, and she must know
# she sent it), but it did not ANSWER him, so it must not close the turn.
#
# Two gates used to read it as an answer, and both had to be fixed together or
# the bug just moves: `welcome_chatter_for_info._gather` would move `last_dir`
# to "out" (the free half — she never generates), and a wire-side "already
# answered" check would drop the reply (the METERED half — she generates, then
# the reply is dropped, every tick, until he speaks again). A fix to one alone
# converts a free bug into a paid one.
#
# Which is exactly what happened, for months, unnoticed: the gather half honoured
# this set and the wire half then re-admitted the same row through a second
# clause reading `sent_by_employee_id IS NOT NULL` — true of every automation
# send, since they all carry the Automation sentinel. One fan drafted and
# discarded a reply every 90 seconds for eighteen hours. Fixed 2026-09-11 in
# the since-removed AI Chatter engine; the lesson is the one above, stated
# harder — when this set grows, grep for every place that decides "somebody
# answered him" and count them, because there are more than two.
#
# Deliberately NOT in here: `autoreply`, `send_welcome`. Those answer IN WORDS — sending over them
# double-replies, which is the failure this set's exclusion is meant to avoid,
# not cause. (`send_welcome` has its own, narrower exemption: it is the
# caller-driven `ignore_welcome` flag on `_thread_moved_on`, live only on the
# turn-handoff job that a welcome bubble itself caused. A welcome is not a
# reaction to anything he did — it lands before he has said a word.)
# What such a row looks like in the transcript the model reads. Needed because a
# reaction row is usually TEXTLESS on the wire — `write_outbound_attribution`
# stored the caption (default "") with `media_count=0`, so an untagged
# `image_reply` rendered as a blank line and she could not tell she had already
# sent him something. Phrased as the fan experienced it, not as plumbing. Both
# kinds were removed; the tags stay for the rows already in his thread.
_REACTION_TAG = {
    "image_reply": "[you sent him a pic back]",
    "tip_reward": "[you sent him his tip reward]",
}
# DERIVED, not restated. Both engines do `if automation_kind in
# TURN_NEUTRAL_KINDS: tag = _REACTION_TAG[automation_kind]` — a subscript, not a
# `.get` — so a third kind added to a hand-written frozenset and forgotten in the
# dict is a KeyError INSIDE `_gather`: a whole-sweep crash on both engines, not a
# one-fan drop. The two collections are the same set; only one of them needs to
# exist, and this way the membership test cannot outrun the tag.
TURN_NEUTRAL_KINDS = frozenset(_REACTION_TAG)


# ── send_welcome's turn handoff, engine side (plans/welcome-pacing §C3) ──
#
# `send_welcome` enqueues a forced-turn job (`turn_handoff_ids`) when one of its
# own bubbles finished landing ON TOP of the fan's reply and moved `last_dir` to
# "out". The chat engine gates on "the fan spoke last", so without the job
# nothing answers him until he double-texts. `TurnHandoff` is the WHOLE engine
# side of that seam — the state, the two event hooks, and the admission — so a
# lane participates in exactly one way (`welcome_turn.handoff_engine` picks the
# lane, from account config).
#
# Each lane still owns the ONE thing that is genuinely its own: what "took the
# turn" means on its lane. welcome_chatter_for_info has no broadcast concept at
# all and a blast does take the turn there. That answer is passed IN to
# `on_outbound`, never re-derived here.

# How many characters of a message body a lane's history line keeps. Shared so
# the words the handoff installs as his line are clipped exactly like the line
# the history renders.
MSG_CLIP = 400


def inbound_is_words(body: str | None) -> bool:
    """Did this INBOUND row carry WORDS? — the Python twin of
    `worded_inbound_where`, the SQL `welcome_turn.newest_worded_inbound` runs to
    decide whether to abort a welcome burst and enqueue the handoff job.

    Two clauses, both easy to lose. The first is the operator's own rule
    ("dont stop on single tip only on text"): a caption-less photo is NOT words,
    so `stop_on_reply` lets the rest of the burst land over it — which means a
    wordless row can be, and routinely is, NEWER than the words the handoff
    exists to answer. The second is `transaction_ingest`'s bookkeeping row: a
    bare tip is written into the thread as an inbound "💸 Sent a $5.00 tip" up to
    five minutes late, and that string is OURS, not his.

    ⚠️ Takes the RAW body, before any lane renders it. The rendering is where
    lanes diverge (`welcome_chatter_for_info` synthesises text for a
    caption-less photo); only the raw row can be asked "did he say something".

    One deliberate narrowing: the SQL's `body != ""` counts a WHITESPACE-ONLY
    body as words and the `.strip()` here does not. The Python may be narrower
    and must be — it hands this row's rendering to the model as his line, and a
    blank fan line is the failure `TurnHandoff.admit` exists to prevent. It may
    never be WIDER: admitting on a row the burst never aborted for is the whole
    defect. `test_welcome_chatter_for_info.case_words_predicate_matches_the_sql`
    drives both halves over a body matrix; if the SQL grows a third clause, that
    case is what goes red."""
    b = (body or "").strip()
    # `.lower()` on both sides because SQLite's LIKE is case-insensitive for ASCII
    # and `str.startswith` is not — the one input on which this copy was WIDER.
    # (`TIP_LEDGER_PREFIX` has no `%` or `_`, so the LIKE carries no wildcard.)
    return bool(b) and not b.lower().startswith(TIP_LEDGER_PREFIX.lower())


def worded_inbound_where():
    """The SQL half of `inbound_is_words`, next to it: the two `Message.body`
    clauses that pick his newest inbound that USED WORDS."""
    return (Message.body != "", Message.body.notlike(f"{TIP_LEDGER_PREFIX}%"))


@dataclass(slots=True)
class TurnHandoff:
    """send_welcome's turn handoff, engine side — one object per candidate.

    `last_worded_in` is HIS newest inbound that used words, rendered and clipped
    to `MSG_CLIP`. Deliberately not "his newest inbound": a caption-less selfie or
    the ledger's bare-tip row lands newer than his words without being speech,
    and a wordless row must never clobber the words the handoff exists to answer.

    `window_open` — since his newest inbound, has EVERY turn-taking outbound been
    a welcome bubble? It is what makes the job self-verifying: by the time it
    runs (~3 min after the abort) a human or another automation may have
    answered him, and then the job is a no-op instead of a second voice.

    A `_gather` calls `on_inbound` / `on_outbound` on every row; the selection
    pass calls `admit` for every candidate — REGARDLESS of `last_dir`. A newer
    wordless row (an undescribed photo) already makes it his turn, and without
    the rewrite the intent detectors and the prompt's "his line" would parse
    `''` or our own `[he sent: …]` synthesis instead of the words he was
    talked over on."""
    last_worded_in: str = ""
    window_open: bool = False

    def on_inbound(self, body: str | None, rendered: str | None) -> None:
        """One INBOUND row. `rendered` is the rendering of the BODY ALONE
        (`_strip_html(body)` on both lanes) — NOT the lane's history line, which
        on welcome_chatter_for_info appends the image describe.

        A tags-only body (`"<br>"`) is words to the SQL and to `inbound_is_words`
        alike, so the burst really was aborted for it — but it renders to `""`,
        and storing that would wipe the words the handoff exists to answer."""
        text = (rendered or "").strip()
        if text and inbound_is_words(body):
            self.last_worded_in = text[:MSG_CLIP]
        self.window_open = True

    def on_outbound(self, *, took_the_turn: bool,
                    automation_kind: str | None) -> None:
        """One OUTBOUND row. A row that did not take the turn is transparent (a
        reaction says nothing). A row that DID take the turn closes the window unless it is the
        welcome bubble itself — the one send that leaves the handoff valid,
        because it is the send that caused it. Once closed it stays closed."""
        if took_the_turn and automation_kind != "welcome":
            self.window_open = False

    def admit(self, fan_id: int, handoff_ids: set[int]) -> str | None:
        """The words to install as his line, or None when the job does not
        admit him. Three conditions, all required: he is named in the job, he
        actually SAID something, and every turn-taking outbound since he said
        it was a welcome bubble. The caller installs
        `c.last_dir, c.last_body = "in", words` and counts the handoff."""
        if fan_id in handoff_ids and self.last_worded_in.strip() and self.window_open:
            return self.last_worded_in
        return None
