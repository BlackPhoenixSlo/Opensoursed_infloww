const LS_FAVOURITES_KEY = "chatterly:emoji_favourites";
export const MAX_FAVOURITES = 40;
export const FAVOURITES_EVENT = "chatterly:emoji_favourites:changed";

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
  try { window.localStorage.setItem(LS_FAVOURITES_KEY, JSON.stringify(list)); } catch { }
  window.dispatchEvent(new Event(FAVOURITES_EVENT));
}
