/**
 * The Inflowwww extras of Messages Pro: one catalogue of every control we
 * add on top of Infloww, and where it lives (ADR-0003;
 * docs/spec/phase-07-ours-kept-marked.md, Interfaces). The automation extras
 * that once rendered behind the Legacy flag went with it. Every extra sits in
 * its Region's Extras overflow, a "+"
 * named `EXTRAS_OVERFLOW_LABEL` (the Chat header's, the Kebab menu's
 * "Inflowwww extras ▸" row, ticket 140), but for the Window header, which
 * has no overflow since TODO.md B2 (2026-10-16): there All Models sits
 * inline; and for Fan insights, whose extras are Insights blocks of their
 * own since 2026-10-21 (ADR-0003's amendment). The
 * extras audit (`app/messages-pro/extras.test.tsx`) checks the rendered tree
 * against it.
 */

/** The word every extra's tooltip starts with. */
export const EXTRA_LABEL = "Inflowwww extra";

/** The accessible name and tooltip of every Extras overflow trigger. */
export const EXTRAS_OVERFLOW_LABEL = "Inflowwww extras";

/** Where an extra renders. */
export type Host =
  | "Window header"
  | "Fan List" | "Fan List overflow"
  | "Chat header overflow"
  | "Fan insights";

/** One extra. A host is listed once per labelled element the audit's fixture
 *  Fan renders there, so an extra with two entry points lists both. */
export type Extra = {
  name: string;
  hosts: readonly Host[];
};

/** The thirteen extras: the twenty-one of the spec's three Gap tables, less
 *  the Composer's three: since TODO.md A2 (2026-10-16) free previews, the
 *  "at" presets and the quick emojis are plain Composer controls (the PPV
 *  row, ⏱ and row 1), and the Composer has no Extras overflow. Less two more:
 *  the AI strip and the AI seller chip went with the legacy selling engine
 *  they surfaced. Less one more: the extra Fan stats, dropped 2026-10-21. The Top bar's scope switcher and error badge, which once
 *  followed the Window header in the app, stay in the main window: Messages
 *  Pro is always a window of its own (ADR-0002). Plus one: the Fan List's
 *  Priority chip, an OF filter Infloww's chip row lacks, tagged inline
 *  since page-parity 07. Less three: the automation extras (Persona button,
 *  Broadcast, Automation restrict) went with the Legacy flag. The Generated
 *  profile note and Persona claims stay: they show in Fan insights by default
 *  since 2026-10-21 (ADR-0003's amendment). */
export const EXTRAS = [
  { name: "Scheduled chip", hosts: ["Chat header overflow"] },
  { name: "Owe reply", hosts: ["Fan List overflow"] },
  // OF's Priority filter, which Infloww's chip row lacks: inline, after the
  // Creator's lists (page-parity 07).
  { name: "Priority chip", hosts: ["Fan List"] },
  { name: "Group chat", hosts: ["Chat header overflow"] },
  { name: "All Models", hosts: ["Window header"] },
  { name: "Generated profile note", hosts: ["Fan insights"] },
  { name: "Persona claims", hosts: ["Fan insights"] },
  { name: "Mass exclude", hosts: ["Chat header overflow", "Fan insights"] },
  { name: "Mark as unread", hosts: ["Chat header overflow"] },
  { name: "Phone focus", hosts: ["Chat header overflow"] },
  { name: "Fan identity", hosts: ["Fan insights"] },
  { name: "Unsold PPVs", hosts: ["Fan insights"] },
  {
    name: "Extra sort orders",
    hosts: ["Fan List overflow", "Fan List overflow", "Fan List overflow"],
  },
] as const satisfies readonly Extra[];

/** An extra's name: a misspelt one fails typecheck. */
export type ExtraName = (typeof EXTRAS)[number]["name"];

/** An extra's tooltip: "Inflowwww extra — <name>", then the control's old
 *  tooltip, if it had one, on the second line. */
export function extraTitle(name: ExtraName, detail?: string): string {
  const first = `${EXTRA_LABEL} — ${name}`;
  return detail ? `${first}\n${detail}` : first;
}
