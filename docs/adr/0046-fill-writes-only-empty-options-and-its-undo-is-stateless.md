# Fill writes only empty Options, never reprices, and its undo is stateless

**Status: proposed** (2026-11-21, `.scratch/script-fill-content` issues 02 and 04, Phase 1; nothing built yet).

Saved replies have no fill history, and `PUT /admin/saved-replies/{id}` replaces a whole row. We decided `fill/apply` re-derives the Fill plan and writes inside one `immediate_session`, touching only Options that carry no media and a `free_media` or `paid_media` Role, and on them only `media_json`, `previews_json`, and `price_cents` where the saved price is 0 and the Role is paid. A Fixed price is never changed: it bounds the new prices under the Escalation rule, and a Sequence whose Fixed prices descend, or sit in (0, $3) or above $200, gets `price_conflict` or `price_out_of_range` and nothing is written until the price is fixed in the editor. Undo is stateless: the caller sends back the Undo list, and the server empties each row whose media, previews, price and Sequence membership still equal it (media and previews empty, price 0), leaving edited rows and reporting them. No table, no migration; the Undo list lives in the page's memory and the Rollout journal, and is gone after a reload. We chose this because a Fill that only writes into empty fields can be undone by clearing them, which any caller allowed to fill could already do in the editor, so undo needs no signed receipt and no stored before-values; repricing agency-typed prices would need both. The cost: no undo after a reload, and a price conflict needs a manual edit before Fill runs. Going back (Fill may reprice, or "undo last fill" survives a reload) means a fill-history table, a migration, and re-deciding who may undo what.

## Considered Options

- **Per-row compare-and-swap on media, previews and price.** Rejected: misses text, Step and membership changes between plan and apply.
- **A signed undo receipt.** Rejected: undo can only clear, so it grants nothing the editor does not.
- **`accept_conflicts`, filling past a price conflict.** Rejected: a saved price under $3 blocks Send.
- **An undo table.** Deferred until the owner wants "undo last fill".
