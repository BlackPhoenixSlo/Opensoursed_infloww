"use client";

/**
 * Our theme in the OF mirror (public/of-mirror/pages). OF's dark theme is just
 * the class `m-mode-dark` on <html> (its stylesheets carry the rules); the
 * generator's boot script sets it before first paint, this keeps it in step
 * with useTheme on every frame load and theme change. OF's own "Dark mode"
 * switch (settings/display) sets our theme.
 *
 * Unless "Synchronize platform display settings" for OnlyFans is off (Your
 * Preferences, Infloww's per-platform switch; on by default): then the mirror
 * keeps OF's own light look whatever our theme, and OF's Dark mode switch only
 * darkens the mirror (kept, as OF keeps its own). Known flash: the generator's
 * THEME_BOOT still follows our theme before first paint, so with sync off and
 * our theme dark a page shows dark until its load event (until the next mirror
 * regeneration teaches THEME_BOOT the sync key).
 */

import { useEffect, useSyncExternalStore, type RefObject } from "react";
import { useTheme } from "@/hooks/useTheme";
import { persistJSON, readJSON } from "@/lib/persist";

const SWITCH = "dark_mode_switcher";

const SYNC_KEY = "chatterly:of-display-sync:v1";
/** The mirror's own Dark mode, used while sync is off. */
const OWN_DARK_KEY = "chatterly:of-own-dark:v1";
const SYNC_EVENT = "chatterly:of-display-sync";

/** Whether the OF mirror follows our display settings (default on). */
export const readOfDisplaySync = (): boolean => readJSON<boolean>(SYNC_KEY) !== false;

export function writeOfDisplaySync(on: boolean): void {
  persistJSON(SYNC_KEY, on);
  try { window.dispatchEvent(new CustomEvent(SYNC_EVENT)); } catch { /* ignore */ }
}

const readOwnDark = (): boolean => readJSON<boolean>(OWN_DARK_KEY) === true;

function writeOwnDark(on: boolean): void {
  persistJSON(OWN_DARK_KEY, on);
  try { window.dispatchEvent(new CustomEvent(SYNC_EVENT)); } catch { /* ignore */ }
}

function subscribeSync(cb: () => void): () => void {
  const onStorage = (e: StorageEvent) => { if (e.key === SYNC_KEY || e.key === OWN_DARK_KEY) cb(); };
  window.addEventListener(SYNC_EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(SYNC_EVENT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

/** The OnlyFans display sync switch, live across components and tabs. */
export const useOfDisplaySync = (): boolean => useSyncExternalStore(subscribeSync, readOfDisplaySync, () => true);

/** Set OF's dark mode class and its Dark mode switch in `doc`. */
export function applyTheme(doc: Document, dark: boolean): void {
  doc.documentElement.classList.toggle("m-mode-dark", dark);
  const sw = doc.getElementById(SWITCH);
  if (sw?.tagName !== "INPUT") return;
  (sw as HTMLInputElement).checked = dark;
  sw.setAttribute("data-oi-wired", ""); // useOfTheme owns it
}

/** Keep the frame's OF theme on ours; returns whether it is dark. */
export function useOfTheme(frameRef: RefObject<HTMLIFrameElement | null>, src: string): boolean {
  const { theme, setTheme } = useTheme();
  const sync = useOfDisplaySync();
  const ownDark = useSyncExternalStore(subscribeSync, readOwnDark, () => false);
  const dark = sync ? theme === "dark" : ownDark;

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const onChange = (ev: Event) => {
      const t = ev.target as HTMLInputElement | null;
      if (t?.id !== SWITCH) return;
      if (sync) setTheme(t.checked ? "dark" : "light");
      else writeOwnDark(t.checked);
    };
    let bound: Document | null = null;
    const apply = () => {
      const doc = frame.contentDocument;
      if (!doc?.body) return;
      applyTheme(doc, dark);
      if (bound !== doc) {
        bound?.removeEventListener("change", onChange);
        doc.addEventListener("change", onChange);
        bound = doc;
      }
    };
    if (frame.contentDocument?.readyState === "complete") apply();
    frame.addEventListener("load", apply);
    return () => {
      frame.removeEventListener("load", apply);
      bound?.removeEventListener("change", onChange);
    };
  }, [frameRef, src, dark, sync, setTheme]);
  return dark;
}
