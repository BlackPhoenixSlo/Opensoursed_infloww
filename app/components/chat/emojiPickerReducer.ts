import { ALL_ENTRIES, CATEGORIES } from "./emojiData";

export interface PickerState {
  open: boolean;
  tab: string;
  search: string;
  recents: string[];
  favourites: string[];
}

export type PickerAction =
  | { type: "toggled" }
  | { type: "closed" }
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

export function tabEmojis({ tab, recents, favourites }: PickerState): readonly string[] {
  const activeCategory = CATEGORIES.find((c) => c.id === tab) ?? CATEGORIES[0];
  return tab === "favourites" && favourites.length > 0 ? favourites
    : tab === "recents" && recents.length > 0 ? recents
      : activeCategory.items.map(([e]) => e);
}

export function filterEmojis(search: string): string[] {
  const q = search.trim().toLowerCase();
  if (!q) return [];
  return ALL_ENTRIES
    .filter(([e, kws]) => e.includes(q) || kws.some((k) => k.toLowerCase().includes(q)))
    .map(([e]) => e);
}
