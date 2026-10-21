# The Dashboard bundle, read with REA, is the layout truth for the eight round-2 pages; the Clone is fixed to match it

Status: accepted (owner, 2026-10-17; replaces the owner's 2026-10-16 line that made the Clone the layout truth).

The infloww-parity-next-steps sign-off graded eight pages as not matching Infloww: Dashboard, Smart Messages, Scripts, Vault Pro, Tracking links, Creator reports, Manage creators and Custom proxy. Those pages had been built from the Clone (`ui-redesign/infloww-exact/`), which is a hand-made copy. We decided that the layout truth for these eight pages is the Dashboard bundle (`~/Downloads/infloww-remote-web/`), which is Infloww's own shipped SPA, read with REA. Each page gets one Layout capture in `docs/infloww-layouts/<page>.md`, and every label, tab, column, button, empty state, spacing value and colour in it cites its chunk or CSS file and offset. When a Clone page disagrees with the capture, the capture wins and the Clone page is edited to match. The Inventory (`docs/infloww-screens.md`) remains the truth for which controls exist, and the Parity matrix's grading rules still decide what counts as `matched`. Any difference from the capture without the "Inflowwww extra" label is a review rejection. We made this choice because the Clone was wrong on exactly these pages, while the bundle is what Infloww actually renders and can be cited down to a byte offset. It is hard to reverse because eight Layout captures, the Clone edits and eight rebuilt pages all depend on it. The cost is that the bundle is untrusted input: it is read-only, never committed, served only on 127.0.0.1, any Python that reads it runs with `-I`, and no key, token or credentialed URL is copied out of it.

ASSUMPTION: this covers the eight named pages only. Messages Pro keeps the Clone as its Geometry reference (ADR-0001), and Settings already measured the bundle (ADR-0009). This is overturned if the owner extends bundle-first to every page.

ASSUMPTION: for these eight pages, a Layout capture outranks an Infloww capture (a desktop screenshot that CONTEXT.md ranks first for look and feel) on layout. This rests on the plan's "the layout truth is the bundle" (rung 2). A disagreement between the two is recorded in the capture as version drift. This is overturned if the owner ranks the desktop screenshots above the bundle.

## Considered Options

- **Keep the Clone as layout truth (the owner's 2026-10-16 line).** Rejected by the owner on 2026-10-17. The Clone is what the eight failing pages were built from.
- **Infloww captures as layout truth.** Rejected. They contain real handles, so they cannot be committed or quoted, and they only show the states someone happened to screenshot.
