# A Platform banks only money codes a Proof purchase showed; Fansly banks chat PPV alone

**Status: accepted** (2026-11-25, `.scratch/multi-platform-p1/plan.md` Phase 1b; ticket 03; built in issues 13 and 14).

`service/fansly_revenue.py` banks notification codes 2007, 2008 and 32007 and accepts generic `price`/`amount` keys, yet only 2007 was ever observed with a price (`fansly/capture/RECIPES.md:884-904`), and a Fansly chat message carrying `totalTipAmount` is passed raw into `tipAmount` and banked as a cleared tip in dollars with no provider id (`fansly_shim.py:654-670`). We decided a Platform's Banking set holds only codes a Proof purchase showed, each with the one price key it carried: Fansly's is `{2007}` from `accountMediaPrice`, kind `ppv_message`, 1/1000 dollar, gross only. The Banking set is split from the Unlock set, so 2008 and 32007 still drive unlock chips and the Buys & tips rail but bank nothing; the Shim emits `isTip` without an amount; the notification poll is the only money writer, keyed by notification id, and the websocket may only wake it. Tips (7001) and paid subs wait for the owner's Proof purchases, and a Seen-code counter shows how much is left out. We chose under-reporting over guessing because a wrong transaction lands in revenue and stats and is hard to find and unwind once banked, while a missed one is recovered by re-reading after proof. The cost: Fansly revenue reads low (tips, subs, any post unlock labelled `ppv_message`) until the owner buys, and ingestion still reads only the first notification page.

ASSUMPTION: a post unlock shares grant code 2007 and is mislabelled `ppv_message` (rung 5); overturned by a post-unlock capture, then split by the grant's parent.

## Considered Options

- **Keep banking 2008 and 32007 with the generic price keys.** Rejected: unobserved payloads could bank any number they carry.
- **Bank Fansly tips from the chat message's `totalTipAmount`.** Rejected: unit unproven, and a later notification would double-count.
- **Bank from the websocket.** Rejected: one writer with one idempotency key is how the house keeps a sale one row (rung 3); two writers need a join nobody has proven.
