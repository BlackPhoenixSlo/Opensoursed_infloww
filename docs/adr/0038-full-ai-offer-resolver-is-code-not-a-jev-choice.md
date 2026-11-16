# Which Offer he asks about is a pure code lookup over recorded facts, not a Jev Choice

**Status: proposed** (2026-11-16, `goal_offer_details.txt` tickets B and D; nothing built yet).

ADR-0032 makes every behavioural "if" a Router question, and the Router already asks Jev Choices (`asks_subject`, `asks_format`). Picking which earlier Offer an Offer-details question means could have been one more Choice. We decided Jev answers only whether the Turn is an Offer-details question; the Offer resolver, a pure read-only function shared by live and test, names the Offer: Quote-reply (inbound `replyToMessage.id` equal to an Offer's `offer_message_id`), then a unique match on Quoted price and/or media type, then the newest Open Offer, else none, and she asks which one. Two Offers at the same price with nothing else to tell them apart are none, never a guess. It reads only the same Creator and Fan (Test chat: session and side), over a bounded look-back of his Offer rows kept apart from the 24 h open-offer window selling uses (`OFFER_OPEN_S`, unchanged). The price stated is the Quoted price on the row, never today's Folder price. The Offer answer check is local code too, as the Claim audit is. We chose this because naming an Offer is matching ids, cents and media kinds already on the row, where a wrong pick states a wrong price or wrong contents (the measured "3 vids total" for a one-video Offer); code is table-testable and records the step that matched, while a Jev Choice would need a per-Fan option list on every Turn and a `question_version` change for each wording fix. Going back means a new Router question and re-deciding the tie and none cases.

## Considered Options

- **A Jev Choice over his recent Offers.** Rejected: per-Fan options, and a probability where an exact id or price match exists.
- **Give the Writer every recent Offer and let it pick.** Rejected: that is the measured wrong-facts failure.
