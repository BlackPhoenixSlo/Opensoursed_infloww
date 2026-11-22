# A Fill puts one Shoot on a Sequence, or writes nothing

**Status: superseded** by ADR-0048 (2026-11-22): a Fill matches each Step across the vault, not one Shoot. Kept for the record; its Roles, status set and `free_unfilled` amendment still hold.

_Was:_ proposed (2026-11-21, `.scratch/script-fill-content` issue 01, Phase 1).

The client asked for vault media on the Sequences "with the right pricing … structured, like in a script". The obvious build matches each Step's text to the best vault item and fills whatever fits. We decided a Fill is deterministic code in two pure stages: Roles first (a saved price, then a price or format promise in the text; no LLM in v1), then one Shoot for the whole Sequence, best first by `shoot_rank_key` with the sell path's relaxed minimums, its Fillable items laid out in script send order (`_script_sort_key`), the last paid Step getting the highest unused Rung. If any free or paid Option cannot be given a Slice, nothing is written and the Sequence gets one reason: `no_paid_steps`, `not_enough_content` (describing may help, the only status that offers Describe) or `no_fit`. Amended 2026-11-21 (plan review): a `free_media` Option with no eligible free item is left empty with flag `free_unfilled` and does not refuse the Sequence; paid Options stay all-or-nothing. We chose this because a script is one shoot escalating from tease to explicit, so per-Step best match mixes outfits mid-sell, and a half-filled Sequence sells the tease and then has nothing, which a chatter cannot see until the Fan pays; one reason per Sequence also keeps the dialog, the Apply gate and the rollout report to a small closed set. Going back to per-Step matching or "fill what fits" rewrites the assignment stage and the Fill status set the dialog, Rollout driver and report all speak.

## Considered Options

- **Best match per Step by text.** Rejected for v1: mixes Shoots, and needs Step texts that name content, which is unmeasured on AE (issue 07). Returns if that measurement shows Steps naming content across outfits.
- **Fill what fits.** Rejected for v1; the owner may overturn it.
- **An LLM reading Step texts for Roles.** Deferred: Roles are an input to assignment, so a reader can join without touching it if most AE Sequences turn out unpriced.
- **The 10-item, 2-clip script-folder rule.** Rejected: it starves small vaults.
