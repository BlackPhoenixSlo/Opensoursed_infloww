import type { StyleConfig } from "@/hooks/useStyleConfig";

export interface StyleBox { key: keyof StyleConfig; label: string; hint: string; parent?: keyof StyleConfig }

export type StyleEngine = "autoreply" | "welcome_chatter_for_info";

// The style PUT merges, so a page keeps only the boxes touched there; an untouched default stays a default.
export const styleBoxes = (engine: StyleEngine): StyleBox[] => [
  { key: engine, label: "Human style",
    hint: "Short lowercase bursts, up to 3 quick bubbles, no robotic dashes or echoing." },
  { key: `typos_${engine}`, label: "Realistic typos",
    hint: 'The occasional thumb-typo, sometimes with a "*fix" bubble. Names, prices and links are never touched.' },
  { key: `nonnative_${engine}`, label: "Non-native English",
    hint: "Reads like a non-native speaker: consistent signature misspellings and slightly broken grammar." },
  { key: `nonnative_spacing_${engine}`, label: 'Space before "?"',
    hint: '"you like it ?", part of the non-native register. Needs Non-native English.', parent: `nonnative_${engine}` },
];

// A box toggled while the save was in flight stays an edit; only the boxes it wrote drop.
export function dropSaved(edits: StyleConfig, sent: StyleConfig): StyleConfig {
  const wrote = new Map(Object.entries(sent));
  return Object.fromEntries(Object.entries(edits).filter(([k, v]) => wrote.get(k) !== v));
}
