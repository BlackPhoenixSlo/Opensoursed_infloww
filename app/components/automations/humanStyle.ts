/**
 * The Human style boxes Auto-reply and Get to know fans show: one engine's realism layers in the style blob
 * (`/admin/style-config`, as service/automations read them). The style PUT merges, so a page keeps only the boxes
 * touched there (`edits`) and an untouched default stays a default.
 */

import type { StyleConfig } from "@/hooks/useStyleConfig";

export interface StyleBox { key: keyof StyleConfig; label: string; hint: string; parent?: keyof StyleConfig }

export type StyleEngine = "autoreply" | "welcome_chatter_for_info";

/** One engine's boxes. Space before "?" only applies while Non-native is on, so it is disabled (value kept) while
 *  that is off. */
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

/** The edits left once a save of `sent` landed: only the boxes it wrote drop. A box toggled while the save was in
 *  flight (a new one, or the sent one flipped back) stays an edit. */
export function dropSaved(edits: StyleConfig, sent: StyleConfig): StyleConfig {
  const wrote = new Map(Object.entries(sent));
  return Object.fromEntries(Object.entries(edits).filter(([k, v]) => wrote.get(k) !== v));
}
