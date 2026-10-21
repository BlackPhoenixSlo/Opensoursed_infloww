# The OF mirror is wired at runtime, never by editing its pages

Mirror pages under `app/public/of-mirror/` are generated and scrubbed by `scripts/of-mirror.mjs` from logged-in captures, and `node scripts/of-mirror.mjs --check` re-runs the leak guard over the committed pages. We decided that all wiring (writes, Data parts, the Post draft, file inputs, the Read-only fallback) is DOM work done at runtime by the `app/lib/ofMirror*.ts` hooks that `app/components/of-manager/OfMirrorFrame.tsx` mounts, keyed by selectors measured in the captures, and that no committed Mirror page is ever hand-edited. Hand edits would be wiped by the next regeneration and would weaken the guard's proof that the pages carry no live data. The price is coupling to OnlyFans's markup: a recapture that changes a selector breaks the wiring without a type error, so every Wired control and Data part has a Mirror check that fails when that happens. Because a State page is a separate document, state that must survive between pages (the Post draft) lives in `sessionStorage`, not in the page.

## Considered Options

- **Patch the generated HTML in the generator.** Rejected because wiring would then live in two places, the generator and the hooks, and every wiring change would need a regeneration from captures that are not in the repo.
