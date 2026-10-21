/**
 * Infloww's two 32px Settings buttons (page-parity ticket 20, measured on the live Time tracking capture).
 * Its own module so both SettingsPanel and StickySaveBar's `SaveRow` read it without importing each other.
 */

import { cn } from "@/lib/utils";

/** Infloww's 32px default button (the Panel header's Edit / Cancel): a 1px `--if-line` border, white text,
 *  no fill, no icon. */
export const IF_BTN = cn(
  "h-8 px-[15px] rounded-[6px] text-sm border border-[var(--if-line)] text-white",
  "hover:border-[var(--if-accent)] hover:text-[var(--if-accent)] disabled:opacity-50 disabled:cursor-not-allowed",
  "disabled:hover:border-[var(--if-line)] disabled:hover:text-white",
);
/** Infloww's 32px primary button (Save): `--if-accent` fill, white text, no icon. */
export const IF_BTN_PRIMARY =
  "h-8 px-[15px] rounded-[6px] text-sm bg-[var(--if-accent)] text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed";
