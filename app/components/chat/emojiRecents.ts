/**
 * Emoji recents — the last picks, newest first, in localStorage so the
 * picker and every quick row remember them across reloads.
 */

import { QUICK_EMOJIS } from "./emojiData";

const LS_RECENTS_KEY = "chatterly:emoji_recents";
const MAX_RECENTS = 24;
/** Cross-instance "recents changed" pulse so every mounted EmojiQuickRow
 *  / picker re-reads from localStorage after a pick. The native `storage`
 *  event only fires on OTHER tabs, not within the same tab — so we
 *  dispatch our own `CustomEvent` on `window`. */
const RECENTS_EVENT = "chatterly:emoji_recents:changed";

function loadRecents(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LS_RECENTS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.slice(0, MAX_RECENTS).filter((s) => typeof s === "string") : [];
  } catch { return []; }
}

function pushRecent(emoji: string) {
  if (typeof window === "undefined") return;
  try {
    const cur = loadRecents();
    const next = [emoji, ...cur.filter((e) => e !== emoji)].slice(0, MAX_RECENTS);
    window.localStorage.setItem(LS_RECENTS_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent(RECENTS_EVENT));
  } catch { /* ignore quota */ }
}

/** Calls `cb` whenever recents change: our pulse (same tab) + the native
 *  `storage` event (other tabs). Returns the unsubscribe. */
function subscribeRecents(cb: () => void): () => void {
  window.addEventListener(RECENTS_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(RECENTS_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

/** Build the quick-row: most-recent leftmost, then fall back to defaults
 *  for any unused slots — without duplicating emojis already in recents. */
function buildQuickRow(recents: string[], slots: number): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const e of recents) {
    if (out.length >= slots) break;
    if (seen.has(e)) continue;
    seen.add(e);
    out.push(e);
  }
  for (const e of QUICK_EMOJIS) {
    if (out.length >= slots) break;
    if (seen.has(e)) continue;
    seen.add(e);
    out.push(e);
  }
  return out;
}

export { LS_RECENTS_KEY, buildQuickRow, loadRecents, pushRecent, subscribeRecents };
