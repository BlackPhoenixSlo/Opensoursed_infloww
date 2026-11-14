/**
 * The Inflowwww folders editor's state (`VaultInternalFoldersModal`): which folder is open, the grid's filter, the
 * ticked media, the open dialog and the write in flight. A pure reducer (the modal only dispatches) plus the pure
 * rules beside it: which bar actions a view offers (`barActions`), where a reorder press lands (`reorderTarget`),
 * the request bodies (`buildAdd` / `buildRemove` / `buildReorder`), a name's validity (`nameError`) and the line a
 * finished write says (`addedNote`).
 *
 *   • Opening a folder is a new view: the filter, select mode, the ticks and the notice go.
 *   • A write keeps the ticks only for a reorder (press Earlier three times); every other write clears them, since
 *     the media left the view or the job is done.
 *   • "All media" (`ALL`) is the source to add from: it has no remove, move or reorder.
 *   • Nothing here writes to OnlyFans; the relay's routes (`vault_internal_folders.py`) touch our DB only.
 */

import type { InternalFolder } from "@/hooks/useInternalFolders";
import type { VaultMedia } from "@/lib/relay";

/** The whole vault, as a source to add from. */
export const ALL = "all" as const;
export type OpenId = number | typeof ALL | null;
export type FolderType = "all" | "photo" | "video";

export type Dialog =
  | { kind: "create" }
  | { kind: "rename"; folderId: number }
  | { kind: "price"; folderId: number }
  /** Pick the folder the ticked media go to: a copy, or a move out of the open one. */
  | { kind: "target"; mode: "copy" | "move" };

export interface Notice { tone: "ok" | "err"; text: string }

export interface FoldersState {
  /** null: the folder list (a phone shows it alone). */
  openId: OpenId;
  type: FolderType;
  /** The search box as typed; it settles into `query` after a pause. */
  draft: string;
  /** The settled search. */
  query: string;
  selectMode: boolean;
  selected: ReadonlyMap<number, VaultMedia>;
  dialog: Dialog | null;
  /** What is being written ("" = nothing): every write control is off meanwhile. */
  busy: string;
  notice: Notice | null;
}

export type Action =
  | { type: "open"; id: OpenId }
  | { type: "mediaType"; value: FolderType }
  | { type: "draft"; value: string }
  | { type: "query"; value: string }
  | { type: "toggleSelectMode" }
  | { type: "toggle"; media: VaultMedia }
  | { type: "selectAll"; media: readonly VaultMedia[] }
  | { type: "clearSelection" }
  | { type: "dialog"; dialog: Dialog | null }
  | { type: "start"; busy: string }
  /** A write landed. `keepSelection`: a reorder. `openId`: the view to show now (a created folder, the list after a delete). */
  | { type: "done"; text: string; keepSelection?: boolean; openId?: OpenId }
  | { type: "failed"; text: string }
  | { type: "dismissNotice" };

const NONE: ReadonlyMap<number, VaultMedia> = new Map();

export const INITIAL: FoldersState = {
  openId: null, type: "all", draft: "", query: "", selectMode: false, selected: NONE, dialog: null, busy: "", notice: null,
};

export function foldersReducer(state: FoldersState, action: Action): FoldersState {
  switch (action.type) {
    case "open":
      return action.id === state.openId ? state : { ...INITIAL, openId: action.id };
    case "mediaType":
      return action.value === state.type ? state : { ...state, type: action.value };
    case "draft":
      return { ...state, draft: action.value };
    case "query":
      return action.value === state.query ? state : { ...state, query: action.value, selected: NONE };
    case "toggleSelectMode":
      return { ...state, selectMode: !state.selectMode, selected: NONE };
    case "toggle": {
      const selected = new Map(state.selected);
      if (selected.has(action.media.id)) selected.delete(action.media.id);
      else selected.set(action.media.id, action.media);
      return { ...state, selectMode: true, selected };
    }
    case "selectAll":
      return { ...state, selectMode: true, selected: new Map(action.media.map((m) => [m.id, m])) };
    case "clearSelection":
      return state.selected.size === 0 ? state : { ...state, selected: NONE };
    case "dialog":
      return state.busy ? state : { ...state, dialog: action.dialog };
    case "start":
      return { ...state, busy: action.busy, notice: null };
    case "done": {
      const next = { ...state, busy: "", dialog: null, notice: { tone: "ok" as const, text: action.text } };
      if (action.openId !== undefined && action.openId !== state.openId) {
        return { ...INITIAL, openId: action.openId, notice: next.notice };
      }
      return action.keepSelection ? next : { ...next, selected: NONE };
    }
    case "failed":
      // The dialog stays: the name or the target can be corrected.
      return { ...state, busy: "", notice: { tone: "err", text: action.text } };
    case "dismissNotice":
      return state.notice ? { ...state, notice: null } : state;
  }
}

// ── The list ─────────────────────────────────────────────────────────

export type FolderKind = InternalFolder["kind"];

/** The rail's sections, in order; empty ones are left out. */
export const SECTIONS: { kind: FolderKind; title: string; hint: string }[] = [
  { kind: "own", title: "Yours", hint: "Made or edited by you. Build AI folders never touches these." },
  { kind: "ai", title: "AI folders", hint: "Generated. Build AI folders rewrites them; editing one makes it yours." },
  { kind: "pack", title: "Feet pack", hint: "The Feet pack's rungs. Edits follow the pack's rules: photos only, the free rung only for a safe body." },
];

export function sections(list: readonly InternalFolder[]) {
  return SECTIONS.map((s) => ({ ...s, folders: list.filter((f) => f.kind === s.kind) })).filter((s) => s.folders.length > 0);
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "12 photos · 3 videos", "4 items" when neither kind is known, or "empty". */
export function countsText(f: Pick<InternalFolder, "items" | "photos" | "videos">): string {
  if (f.items === 0) return "empty";
  const parts = [f.photos > 0 ? plural(f.photos, "photo") : "", f.videos > 0 ? plural(f.videos, "video") : ""].filter(Boolean);
  const other = f.items - f.photos - f.videos;
  if (other > 0) parts.push(`${other} other`);
  return parts.join(" · ");
}

/** What an edit does to a folder of this kind, said before the first one; "" for the operator's own. */
export function kindNote(kind: FolderKind): string {
  if (kind === "ai") return "Generated by Build AI folders. Edit it and it becomes yours: a rebuild then leaves it alone and makes a fresh AI copy beside it.";
  if (kind === "pack") return "A Feet pack rung: photos only, and filing a photo here takes it off the pack's other rungs. It keeps its name.";
  return "";
}

/** Why a name can't be saved; "" when it can. `folderId`: the folder being renamed (its own name is free). */
export function nameError(text: string, list: readonly InternalFolder[], folderId: number | null = null): string {
  const name = text.trim();
  if (!name) return "Name it first.";
  if (name.length > 120) return "120 characters at most.";
  if (list.some((f) => f.name === name && f.id !== folderId)) return "A folder with this name already exists.";
  return "";
}

// ── The selection bar ────────────────────────────────────────────────

export interface BarActions {
  /** All media: add the ticks to a folder. */
  add: boolean;
  remove: boolean;
  copy: boolean;
  move: boolean;
  reorder: boolean;
}

/** What the bar offers for the open view: All media only adds; a folder removes, copies, moves and reorders.
 *  Copy and move need another folder to go to. Reorder is off under a search or a type filter: "earlier" would
 *  jump the items the filter hides. */
export function barActions(openId: OpenId, folderCount: number, filtered = false): BarActions {
  if (openId === null) return { add: false, remove: false, copy: false, move: false, reorder: false };
  if (openId === ALL) return { add: folderCount > 0, remove: false, copy: false, move: false, reorder: false };
  const others = folderCount > 1;
  return { add: false, remove: true, copy: others, move: others, reorder: !filtered };
}

export type ReorderDir = "first" | "earlier" | "later" | "last";

/** Where a reorder press puts the ticked block: `{ before }` (a media id, or null = the folder's end), or null when
 *  the press would change nothing or can't be answered from the loaded page. `items`: the grid as loaded, in folder
 *  order; `hasMore`: the folder has unloaded pages after them. The ticks keep their grid order. */
export function reorderTarget(
  items: readonly { id: number }[], selected: ReadonlySet<number>, dir: ReorderDir, hasMore: boolean,
): { ids: number[]; before: number | null } | null {
  const ids = items.filter((m) => selected.has(m.id)).map((m) => m.id);
  if (ids.length === 0) return null;
  const rest = items.filter((m) => !selected.has(m.id));
  const at = (i: number) => items.findIndex((m) => m.id === ids[i]);
  const firstAt = at(0);
  const lastAt = at(ids.length - 1);
  const contiguous = lastAt - firstAt + 1 === ids.length;
  if (dir === "first") {
    if (rest.length === 0 || (contiguous && firstAt === 0)) return null;
    return { ids, before: rest[0].id };
  }
  if (dir === "last") {
    if (!hasMore && (rest.length === 0 || (contiguous && lastAt === items.length - 1))) return null;
    return { ids, before: null };
  }
  if (dir === "earlier") {
    // In front of the nearest unticked item before the block's first.
    const prev = [...items.slice(0, firstAt)].reverse().find((m) => !selected.has(m.id));
    if (!prev) return contiguous ? null : { ids, before: rest[0]?.id ?? null };
    return { ids, before: prev.id };
  }
  // later: behind the nearest unticked item after the block's last.
  const after = items.slice(lastAt + 1).filter((m) => !selected.has(m.id));
  if (after.length === 0) return contiguous || hasMore ? null : { ids, before: null };
  if (after.length === 1) return hasMore ? null : { ids, before: null };
  return { ids, before: after[1].id };
}

// ── Request bodies ───────────────────────────────────────────────────

const idsOf = (selected: ReadonlyMap<number, VaultMedia>) => [...selected.keys()];

/** POST …/{target}/add: a copy, or (given `moveFrom`, the open folder) a move. */
export function buildAdd(accountId: string, selected: ReadonlyMap<number, VaultMedia>, moveFrom: number | null) {
  return { account_id: accountId, media_ids: idsOf(selected), ...(moveFrom === null ? {} : { move_from: moveFrom }) };
}

export function buildRemove(accountId: string, selected: ReadonlyMap<number, VaultMedia>) {
  return { account_id: accountId, media_ids: idsOf(selected) };
}

export function buildReorder(accountId: string, target: { ids: number[]; before: number | null }) {
  return { account_id: accountId, media_ids: target.ids, before: target.before };
}

/** The add's answer as one line: "Moved 3 to feet-nude", "Added 2 to beach · 1 already there". */
export function addedNote(res: { added: number; already: number }, name: string, moved: boolean): string {
  const verb = moved ? "Moved" : "Added";
  const tail = res.already > 0 ? ` · ${res.already} already there` : "";
  return `${verb} ${res.added} to ${name}${tail}`;
}

/** A failed write as one line: the relay's sentence when it sent one (a rung's rule, a taken name), else a plain
 *  one (its bare error codes arrive as JSON text). */
export function errorNote(message: string): string {
  const text = message.trim();
  return !text || text.startsWith("{") || text.startsWith("relay ") ? "Couldn't save that. Reload and try again." : text;
}
