import type { MediaType } from "@/components/vault/VaultMediaToolbar";
import type { FanId } from "@/lib/fanId";
import type { VaultMedia } from "@/lib/relay";

export interface BrowseState {
  type: MediaType;
  folderId: FanId | null;
  standardFolderId: number | null;
  query: string;
  tags: readonly string[];
  selectMode: boolean;
  selected: ReadonlyMap<number, VaultMedia>;
}

export type BrowseAction =
  | { type: "folder"; id: FanId | null }
  | { type: "standardFolder"; id: number; kind: "photo" | "video" }
  | { type: "mediaType"; value: MediaType }
  | { type: "query"; value: string }
  | { type: "toggleTag"; tag: string }
  | { type: "clearTags" }
  | { type: "toggleSelectMode" }
  | { type: "selectAll"; media: readonly VaultMedia[] }
  | { type: "toggle"; media: VaultMedia }
  | { type: "clearSelection" };

const NONE: ReadonlyMap<number, VaultMedia> = new Map();

export const initialBrowseState: BrowseState = {
  type: "all",
  folderId: null,
  standardFolderId: null,
  query: "",
  tags: [],
  selectMode: false,
  selected: NONE,
};

// A new view of the vault: the ticks described the old one, so a folder/search/tag change clears them.
function view(state: BrowseState, patch: Partial<BrowseState>): BrowseState {
  return { ...state, ...patch, selected: NONE };
}

export function vaultBrowseReducer(state: BrowseState, action: BrowseAction): BrowseState {
  switch (action.type) {
    case "folder":
      return action.id === state.folderId && state.standardFolderId === null ? state
        : view(state, { folderId: action.id, standardFolderId: null });
    case "standardFolder":
      return action.id === state.standardFolderId ? state
        : view(state, { folderId: null, standardFolderId: action.id, type: action.kind, tags: [] });
    // The Photo / Video filter keeps the ticks (owner): downloads can span both.
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

export function hiddenByFilter(s: Pick<BrowseState, "type" | "selected">): number {
  if (s.type === "all") return 0;
  let n = 0;
  for (const m of s.selected.values()) if (m.type !== s.type) n += 1;
  return n;
}

export function selectionText(count: number, hidden: number): string {
  return hidden > 0 ? `${count} selected · ${hidden} hidden by filter` : `Selected ${count}`;
}

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
