/**
 * Emoji picker state — open, tab, search, recents, favourites. Opening
 * reloads recents + favourites and resets the search together, and the
 * favourites load picks the tab, so one reducer owns them (CLAUDE.md).
 * The tab survives close/reopen.
 */

import { ALL_ENTRIES, CATEGORIES } from "./emojiData";

export interface PickerState {
  open: boolean;
  /** A category id, "recents" or "favourites". */
  tab: string;
  search: string;
  recents: string[];
  favourites: string[];
}

export type PickerAction =
  | { type: "toggled" }
  | { type: "closed" }
  /** The open effect's load; any favourites select the Favourites tab. */
  | { type: "opened"; recents: string[]; favourites: string[] }
  | { type: "recentsRefreshed"; recents: string[] }
  | { type: "tabSet"; tab: string }
  | { type: "searchSet"; search: string };

export const initialPickerState: PickerState = {
  open: false,
  tab: CATEGORIES[0].id,
  search: "",
  recents: [],
  favourites: [],
};

export function emojiPickerReducer(state: PickerState, action: PickerAction): PickerState {
  switch (action.type) {
    case "toggled":
      return { ...state, open: !state.open };
    case "closed":
      return { ...state, open: false };
    case "opened": {
      const { recents, favourites } = action;
      return { ...state, recents, favourites, search: "", tab: favourites.length ? "favourites" : state.tab };
    }
    case "recentsRefreshed":
      return { ...state, recents: action.recents };
    case "tabSet":
      return { ...state, tab: action.tab };
    case "searchSet":
      return { ...state, search: action.search };
  }
}

/** The active tab's grid; an empty Favourites / Recent tab shows the first category. */
export function tabEmojis({ tab, recents, favourites }: PickerState): readonly string[] {
  const activeCategory = CATEGORIES.find((c) => c.id === tab) ?? CATEGORIES[0];
  return tab === "favourites" && favourites.length > 0 ? favourites
    : tab === "recents" && recents.length > 0 ? recents
      : activeCategory.items.map(([e]) => e);
}

/** Search hits by emoji or keyword; [] for a blank query. */
export function filterEmojis(search: string): string[] {
  const q = search.trim().toLowerCase();
  if (!q) return [];
  return ALL_ENTRIES
    .filter(([e, kws]) => e.includes(q) || kws.some((k) => k.toLowerCase().includes(q)))
    .map(([e]) => e);
}
