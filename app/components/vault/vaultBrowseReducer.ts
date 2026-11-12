/**
 * vaultBrowseReducer — what VaultManagePanel's grid is showing (folder, media
 * type, search) and the files ticked in it.
 *
 *   • Changing the folder or the search CLEARS the selection. The selection is
 *     media off the grid the operator was looking at; the old panel kept it
 *     across a folder switch, so the bar said "Selected 3" over a grid showing
 *     none of them and "Add to category" / "New OF folder with these" /
 *     "Describe selected" acted on files no longer on screen. Select mode
 *     itself stays on — only what was ticked goes.
 *   • The Photo / Video filter KEEPS the ticks: it narrows the same folder, and
 *     ticking photos then videos for one download is the point (owner, 11-11).
 *     The ticks hold the media themselves, so a download still has the ones the
 *     filter hides.
 *   • The tag chips (`tags`, AND) are a new view too: toggling one CLEARS the
 *     ticks, as a search does. They stay across a folder or type change (they
 *     narrow whatever is open), as the search does.
 *   • Re-picking the same folder / type / search changes nothing.
 *   • Paging is not here: the grid's pages live in the query hooks, keyed by
 *     folder / type / search, so a change already starts from page one.
 *   • Sort is not here either: it reorders the same files, so the ticks stand.
 *
 * `browseMapReducer`: one BrowseState per model (memory only, the page's
 * lifetime), so switching model and back finds its folder, select mode and
 * ticks as they were; another model's ticks never apply to this one.
 */

import type { MediaType } from "@/components/vault/VaultMediaToolbar";
import type { FanId } from "@/lib/fanId";
import type { VaultMedia } from "@/lib/relay";

export interface BrowseState {
  type: MediaType;
  /** The OF folder (list id); null = All media. FanId: a Fansly album id is a snowflake past 2^53. */
  folderId: FanId | null;
  /** The settled search (the debounced box). */
  query: string;
  /** The picked tag chips (lower-case, in pick order); the grid shows items carrying all of them. */
  tags: readonly string[];
  selectMode: boolean;
  /** The ticked media by id, in tick order. */
  selected: ReadonlyMap<number, VaultMedia>;
}

export type BrowseAction =
  | { type: "folder"; id: FanId | null }
  | { type: "mediaType"; value: MediaType }
  | { type: "query"; value: string }
  /** A tag chip tapped: picked if it was not, else dropped. */
  | { type: "toggleTag"; tag: string }
  | { type: "clearTags" }
  | { type: "toggleSelectMode" }
  /** The toolbar's Select all: select mode on, every loaded file ticked. */
  | { type: "selectAll"; media: readonly VaultMedia[] }
  | { type: "toggle"; media: VaultMedia }
  | { type: "clearSelection" };

const NONE: ReadonlyMap<number, VaultMedia> = new Map();

export const initialBrowseState: BrowseState = {
  type: "all",
  folderId: null,
  query: "",
  tags: [],
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
      return action.value === state.type ? state : { ...state, type: action.value };
    case "query":
      return action.value === state.query ? state : view(state, { query: action.value });
    case "toggleTag": {
      const tag = action.tag.trim().toLowerCase();
      if (!tag) return state;
      const tags = state.tags.includes(tag) ? state.tags.filter((t) => t !== tag) : [...state.tags, tag];
      return view(state, { tags });
    }
    case "clearTags":
      return state.tags.length === 0 ? state : view(state, { tags: [] });
    case "toggleSelectMode":
      return { ...state, selectMode: !state.selectMode, selected: NONE };
    case "selectAll":
      return { ...state, selectMode: true, selected: new Map(action.media.map((m) => [m.id, m])) };
    case "toggle": {
      const selected = new Map(state.selected);
      if (selected.has(action.media.id)) selected.delete(action.media.id);
      else selected.set(action.media.id, action.media);
      return { ...state, selected };
    }
    case "clearSelection":
      return state.selected.size === 0 ? state : { ...state, selected: NONE };
  }
}

/** Ticked media the Photo / Video filter hides. Every bar action (download, Add to category, new OF folder, describe)
 *  still takes all ticks, so the bar names how many of them are off screen. */
export function hiddenByFilter(s: Pick<BrowseState, "type" | "selected">): number {
  if (s.type === "all") return 0;
  let n = 0;
  for (const m of s.selected.values()) if (m.type !== s.type) n += 1;
  return n;
}

/** The selection bar's count: "Selected" + N, or "N selected · M hidden by filter" when the filter hides some. */
export function selectionText(count: number, hidden: number): string {
  return hidden > 0 ? `${count} selected · ${hidden} hidden by filter` : `Selected ${count}`;
}

/** Each model's browse state by account id (absent: initialBrowseState). */
export type BrowseMap = Readonly<Record<string, BrowseState>>;
export type BrowseMapAction = { accountId: string; action: BrowseAction };

export function browseFor(m: BrowseMap, accountId: string): BrowseState {
  return m[accountId] ?? initialBrowseState;
}

export function browseMapReducer(m: BrowseMap, a: BrowseMapAction): BrowseMap {
  const prev = browseFor(m, a.accountId);
  const next = vaultBrowseReducer(prev, a.action);
  return next === prev ? m : { ...m, [a.accountId]: next };
}
