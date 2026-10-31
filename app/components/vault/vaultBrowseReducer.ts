/**
 * vaultBrowseReducer — what VaultManagePanel's grid is showing (folder, media
 * type, search) and the files ticked in it.
 *
 *   • Changing the folder, the type or the search CLEARS the selection. The
 *     selection is a set of media ids off the grid the operator was looking at;
 *     the old panel kept it across a folder switch, so the bar said "Selected 3"
 *     over a grid showing none of them and "Add to category" / "New OF folder
 *     with these" / "Describe selected" acted on files no longer on screen.
 *     Select mode itself stays on — only what was ticked goes.
 *   • Re-picking the same folder / type / search changes nothing.
 *   • Paging is not here: the grid's pages live in the query hooks, keyed by
 *     folder / type / search, so a change already starts from page one.
 *   • Sort is not here either: it reorders the same files, so the ticks stand.
 */

import type { MediaType } from "@/components/vault/VaultMediaToolbar";
import type { FanId } from "@/lib/fanId";

export interface BrowseState {
  type: MediaType;
  /** The OF folder (list id); null = All media. FanId: a Fansly album id is a snowflake past 2^53. */
  folderId: FanId | null;
  /** The settled search (the debounced box). */
  query: string;
  selectMode: boolean;
  selected: ReadonlySet<number>;
}

export type BrowseAction =
  | { type: "folder"; id: FanId | null }
  | { type: "mediaType"; value: MediaType }
  | { type: "query"; value: string }
  | { type: "toggleSelectMode" }
  /** The toolbar's Select all: select mode on, every loaded file ticked. */
  | { type: "selectAll"; ids: readonly number[] }
  | { type: "toggle"; id: number }
  | { type: "clearSelection" };

const NONE: ReadonlySet<number> = new Set();

export const initialBrowseState: BrowseState = {
  type: "all",
  folderId: null,
  query: "",
  selectMode: false,
  selected: NONE,
};

/** A new view of the vault: the ticks described the old one. */
function view(state: BrowseState, patch: Partial<BrowseState>): BrowseState {
  return { ...state, ...patch, selected: NONE };
}

export function vaultBrowseReducer(state: BrowseState, action: BrowseAction): BrowseState {
  switch (action.type) {
    case "folder":
      return action.id === state.folderId ? state : view(state, { folderId: action.id });
    case "mediaType":
      return action.value === state.type ? state : view(state, { type: action.value });
    case "query":
      return action.value === state.query ? state : view(state, { query: action.value });
    case "toggleSelectMode":
      return { ...state, selectMode: !state.selectMode, selected: NONE };
    case "selectAll":
      return { ...state, selectMode: true, selected: new Set(action.ids) };
    case "toggle": {
      const selected = new Set(state.selected);
      if (selected.has(action.id)) selected.delete(action.id);
      else selected.add(action.id);
      return { ...state, selected };
    }
    case "clearSelection":
      return state.selected.size === 0 ? state : { ...state, selected: NONE };
  }
}
