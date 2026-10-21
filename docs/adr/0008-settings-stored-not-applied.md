# Settings store what Infloww stores and apply none of it

Status: superseded in part by ADR-0012. The fields ADR-0012 makes Applied (Phases 2 and 4 of the infloww-parity-next-steps plan) are read and acted on, Permission roles only under Role enforcement. This decision still holds for the fields left Not applied yet (the Agency name, Language and the AI Translator prompt) and for Security, Billing and Balance actions, which stay Not wired.

The Settings tabs are to look and save like Infloww's, but Inflowwww has no 2FA, no password change, no rename, no session list, no permission enforcement, no Sales attribution engine and no LLM AI translation. We decided the Settings tabs enforce nothing. Permission roles, Sales attribution, AI translation and its prompt, Time tracking, the preferences and the agency name are saved to their Settings blobs and read by nothing else, and a Panel whose values are Not applied yet says "Saved for your organization; not applied yet." A control whose action has no Relay endpoint and is not a blob field is Not wired: disabled with the tooltip "not wired", never stored, never faking success. The 2FA switch on Security (organization) is Not wired rather than stored, because a saved "on" would claim a protection that does not exist. Building each enforcement is its own project, and hiding the unbacked controls would break parity with Infloww's layout and hide what is missing.

ASSUMPTION: the plan names roles, attribution and the translation toggle as the Panels that show the note, but preferences, time tracking and the agency name are equally unread ("No consumer yet"), so every Blob tab's Panel shows it. Overturned if the human meant only the three named.

## Consequences

Values an Agency saves now, believing them inert, take effect on the day a consumer starts reading them. That is the hard-to-reverse part: a later plan that wires a consumer (for example Permission roles that lock Employees out of pages, or Sales attribution that moves credit) must treat existing blobs as unreviewed and say how it handles them.

## Considered Options

- **Hide controls that have no backend.** Rejected: it breaks Geometry parity and hides the gap.
- **Show them enabled and report success.** Rejected: the house rule for Not wired forbids faking success.
- **Store the 2FA switch like any other field.** Rejected: a security setting that reads "on" while doing nothing is worse than a disabled one.
