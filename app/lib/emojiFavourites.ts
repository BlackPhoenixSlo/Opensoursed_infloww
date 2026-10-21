/**
 * Emoji favourites store (Messages Pro ⚙; docs/spec/phase-04-composer-ppv-vault.md,
 * Contracts): one list per browser, in pick order, no duplicates, at most
 * 40. The emoji picker reads it each time it opens. The Composer's quick
 * emoji row (`QuickEmojiRow`) shows the list and follows each save live; until
 * a list is first saved it shows the defaults. The editor is EmojiFavourites.tsx.
 */

const LS_FAVOURITES_KEY = "chatterly:emoji_favourites";
export const MAX_FAVOURITES = 40;
/** Same-tab "favourites saved" pulse: the native `storage` event only fires
 *  in other tabs. */
export const FAVOURITES_EVENT = "chatterly:emoji_favourites:changed";

/** Whether a list was ever saved (an empty one included). */
export function hasSavedFavourites(): boolean {
  if (typeof window === "undefined") return false;
  try { return window.localStorage.getItem(LS_FAVOURITES_KEY) !== null; } catch { return false; }
}

export function loadFavourites(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const arr = JSON.parse(window.localStorage.getItem(LS_FAVOURITES_KEY) ?? "[]");
    if (!Array.isArray(arr)) return [];
    return [...new Set(arr.filter((s): s is string => typeof s === "string"))].slice(0, MAX_FAVOURITES);
  } catch { return []; }
}

export function saveFavourites(list: string[]) {
  try { window.localStorage.setItem(LS_FAVOURITES_KEY, JSON.stringify(list)); } catch { /* quota */ }
  window.dispatchEvent(new Event(FAVOURITES_EVENT));
}
