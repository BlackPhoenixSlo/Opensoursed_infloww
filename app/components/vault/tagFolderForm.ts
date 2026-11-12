/**
 * The tag chips' "Save as folder" form and its saved row (VaultTagChips only dispatches): open, the name, the save in
 * flight, the last failure line, then the saved folder ("Saved locally · <name> · N items") and its Publish.
 *
 *   • The name follows the picked chips ("feet + lace") until the operator types in it (`name` null = follow);
 *     a save or a close goes back to following.
 *   • One save at a time: `canSubmit` is off while one runs, with no chip picked, a blank name, nothing to save or
 *     more than `TAG_FOLDER_MAX` items (the relay's `vault_tags.FOLDER_MAX_ITEMS`; `capText` says why).
 *   • A save is local only (an internal folder). The saved row stays (chips cleared or changed) until dismissed or the
 *     next save; Publish asks first, stating N items, then calls the existing publish route. One publish at a time.
 *   • `buildPayload` sends the grid's own filters (chips, type, search, open folder): the relay resolves the
 *     items itself (POST /admin/vault-ai/folders/from-tags), never from the grid's loaded page.
 */

import type { FanId } from "@/lib/fanId";

/** Items one saved folder may hold: `vault_tags.FOLDER_MAX_ITEMS`. */
export const TAG_FOLDER_MAX = 5000;

export interface SavedTagFolder {
  folderId: number;
  name: string;
  items: number;
}

export type PublishState =
  | { step: "idle" }
  | { step: "confirm" }
  | { step: "publishing" }
  | { step: "done"; text: string }
  | { step: "failed"; text: string };

export interface TagFolderForm {
  open: boolean;
  /** The typed name; null = the chips' default (`defaultFolderName`). */
  name: string | null;
  saving: boolean;
  /** The last save's failure (the form stays open to retry). */
  error: string | null;
  saved: SavedTagFolder | null;
  publish: PublishState;
}

export type TagFolderAction =
  | { type: "open" }
  | { type: "close" }
  | { type: "name"; value: string }
  | { type: "start" }
  /** Saved: closes the form, the saved row replaces any earlier one. */
  | { type: "done"; folder: SavedTagFolder }
  /** Not saved: stays open with what was typed, to retry. */
  | { type: "failed"; text: string }
  | { type: "dismiss" }
  | { type: "publishAsk" }
  | { type: "publishCancel" }
  | { type: "publishStart" }
  | { type: "publishDone"; text: string }
  | { type: "publishFailed"; text: string };

const IDLE: PublishState = { step: "idle" };

export const INITIAL_TAG_FOLDER_FORM: TagFolderForm = {
  open: false, name: null, saving: false, error: null, saved: null, publish: IDLE,
};

const publishing = (s: TagFolderForm) => s.publish.step === "publishing";

export function tagFolderFormReducer(state: TagFolderForm, action: TagFolderAction): TagFolderForm {
  switch (action.type) {
    case "open":
      return state.open ? state : { ...state, open: true, error: null };
    case "close":
      return state.saving ? state : { ...state, open: false, name: null, error: null };
    case "name":
      return { ...state, name: action.value };
    case "start":
      return state.saving || publishing(state) ? state : { ...state, saving: true, error: null };
    case "done":
      return { ...INITIAL_TAG_FOLDER_FORM, saved: action.folder };
    case "failed":
      return { ...state, saving: false, error: action.text };
    case "dismiss":
      return publishing(state) || !state.saved ? state : { ...state, saved: null, publish: IDLE };
    case "publishAsk":
      return state.saved && (state.publish.step === "idle" || state.publish.step === "failed")
        ? { ...state, publish: { step: "confirm" } } : state;
    case "publishCancel":
      return state.publish.step === "confirm" ? { ...state, publish: IDLE } : state;
    case "publishStart":
      return state.publish.step === "confirm" ? { ...state, publish: { step: "publishing" } } : state;
    case "publishDone":
      return publishing(state) ? { ...state, publish: { step: "done", text: action.text } } : state;
    case "publishFailed":
      return publishing(state) ? { ...state, publish: { step: "failed", text: action.text } } : state;
  }
}

/** The name before any typing: the picked tags joined. */
export function defaultFolderName(tags: readonly string[]): string {
  return tags.join(" + ").slice(0, 120);
}

export function folderName(s: TagFolderForm, tags: readonly string[]): string {
  return s.name ?? defaultFolderName(tags);
}

/** Why `total` items cannot be saved (over the cap), else null. */
export function capText(total: number): string | null {
  return total > TAG_FOLDER_MAX
    ? `${total.toLocaleString("en-US")} items match; a saved folder holds at most ${TAG_FOLDER_MAX.toLocaleString("en-US")}. Pick another chip or filter to narrow it.`
    : null;
}

export function canSubmit(s: TagFolderForm, tags: readonly string[], total: number): boolean {
  return s.open && !s.saving && tags.length > 0 && total > 0 && total <= TAG_FOLDER_MAX
    && folderName(s, tags).trim().length > 0;
}

export interface TagFolderView {
  accountId: string;
  tags: readonly string[];
  type: string;
  query: string;
  ofFolderId: FanId | null;
}

export interface TagFolderPayload {
  account_id: string;
  name: string;
  tags: string[];
  type: string;
  query: string;
  of_folder_id: FanId | null;
}

export function buildPayload(s: TagFolderForm, v: TagFolderView): TagFolderPayload {
  return {
    account_id: v.accountId,
    name: folderName(s, v.tags).trim(),
    tags: [...v.tags],
    type: v.type,
    query: v.query,
    of_folder_id: v.ofFolderId,
  };
}

const items = (n: number) => `${n.toLocaleString("en-US")} item${n === 1 ? "" : "s"}`;

/** The saved row's line. */
export function savedText(f: SavedTagFolder): string {
  return `Saved locally · ${f.name} · ${items(f.items)}`;
}

/** The publish confirm's question. */
export function publishQuestion(f: SavedTagFolder): string {
  return `Publish "${f.name}" to OnlyFans? This creates an OnlyFans vault folder and adds all ${items(f.items)} to it. Removing items later does not remove them on OnlyFans.`;
}

/** After the publish route answered (`pushed`: the folder's items sent to the OnlyFans list). */
export function publishedText(r: { pushed: number }): string {
  return `Published to OnlyFans · ${items(r.pushed)}`;
}
