# Settings take Infloww's colours as well as its Geometry, through `--if-*` tokens

ADR-0001 gives Messages Pro Infloww's Geometry and Inflowwww's colours. The Settings tabs depart from it on purpose and take Infloww's colours too. Every measured Dashboard bundle value becomes an Infloww token in one `--if-*` block in `app/app/globals.css`: the light `--tc-*` palette under `html[data-theme="light"]`, and, because `--tc-*` has no dark values, the dark palette sampled in `docs/infloww-screens.md` §1.4 beside the `@theme` defaults, plus Geometry such as the 64px tab row. Only the components under `app/components/settings/` that the Settings tabs effort creates read them; the Legacy tabs, the app shell and Messages Pro keep the app's own tokens. The font is the exception: Settings stays on `--font-sans`, because Infloww's "Suisse Int'l" is licensed and served from Infloww's host, so the font is a recorded visual gap.

ASSUMPTION: the plan states the colour rule without a reason. The reason inferred here is that Settings is a small, self-contained screen judged by its likeness to Infloww's, and a separate token block keeps the departure from leaking into other screens. Overturned if the human gives another reason, which could change whether a new shared component may read `--if-*`.

## Consequences

Settings and Messages Pro show two colour systems, deliberately. Moving an `--if-*` value into the shared tokens, or reading `--if-*` outside the Settings components, re-opens ADR-0001. The Settings walk asserts computed styles against the tokens, so changing a token is a test change.

## Considered Options

- **Follow ADR-0001 and use the app's colours.** Rejected by the plan's binding Constraint "Infloww's colours via `--if-*` tokens".
- **Inline the measured values in components.** Rejected: the Settings walk asserts against tokens, and magic numbers in JSX are what ADR-0001's token module avoided.
