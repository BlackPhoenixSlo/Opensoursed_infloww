/**
 * Growth > Scripts' navigation and selection as a pure reducer: the open view, the open tag and sequence, the
 * checked scripts and the tags added on this page before any script carries them.
 *
 *   • Moving to another list (`view`, `open`, `addTag`) clears the checked scripts.
 *   • The open entry of a kind is `activeEntry(open[kind], order)`: the stored pick while the sidebar lists it,
 *     else the sidebar's first entry (All scripts on Tag, the first sequence on Sequence).
 *   • Deleting the open entry opens its neighbour in the sidebar (the next, else the previous, else none);
 *     deleting another keeps the open one.
 *   • Renaming the open entry keeps it open under its new name; renaming another keeps the open one. Checked
 *     scripts stay through a rename.
 */

export type View = "tags" | "sequences" | "manage";
export type EntryKind = "tag" | "sequence";

/** The view that lists a kind's entries in its sidebar. */
const VIEW_OF: Record<EntryKind, View> = { tag: "tags", sequence: "sequences" };

/** The kind a view's sidebar lists (`VIEW_OF` read backwards); Manage scripts has no sidebar. */
const KIND_OF: Record<View, EntryKind | null> = { tags: "tag", sequences: "sequence", manage: null };
export function kindOf(view: View): EntryKind | null {
  return KIND_OF[view];
}

/** The Tag sidebar's two fixed entries (the bundle's `UncategorizedCommon`): every script, and the untagged ones. */
export const ALL = "\u0000all";
export const UNCATEGORIZED = "\u0000uncategorized";

export interface ScriptsPageState {
  view: View;
  /** The picked tag and sequence; null opens the first in the sidebar (ALL on Tag). */
  open: Record<EntryKind, string | null>;
  /** The checked scripts' ids. */
  checked: ReadonlySet<number>;
  /** Tags added from the More menu with nothing checked; shown while no script carries them (`livePending`). */
  pendingTags: readonly string[];
}

export type Action =
  /** Open a view (a tab, Manage scripts); clears the checked scripts. */
  | { type: "view"; view: View }
  /** Open an entry in its view (a sidebar row, a chip, a new sequence); clears the checked scripts. */
  | { type: "open"; kind: EntryKind; name: string }
  | { type: "check"; ids: readonly number[]; on: boolean }
  /** Replace the checked scripts (select all, or none). */
  | { type: "setChecked"; ids: readonly number[] }
  /** Open the tag `name`; `pending` lists it before any script carries it. */
  | { type: "addTag"; name: string; pending: boolean }
  /** `order` (both): the kind's sidebar as drawn when the user acted, before the server's answer refetches it. */
  | { type: "renameEntry"; kind: EntryKind; from: string; to: string; order: readonly string[] }
  | { type: "deleteEntry"; kind: EntryKind; name: string; order: readonly string[] }
  /** Another Creator: nothing of this one's carries over but the view. */
  | { type: "reset" };

export const INITIAL: ScriptsPageState = {
  view: "tags",
  open: { tag: null, sequence: null },
  checked: new Set(),
  pendingTags: [],
};

/** The open entry: `sel` while `order` lists it, else the first entry, else none. */
export function activeEntry(sel: string | null, order: readonly string[]): string | null {
  return sel != null && order.includes(sel) ? sel : (order[0] ?? null);
}

/** The entry that takes `name`'s place when it goes: the next in `order`, else the previous, else none. */
export function neighbour(order: readonly string[], name: string): string | null {
  const i = order.indexOf(name);
  if (i < 0) return null;
  return order[i + 1] ?? order[i - 1] ?? null;
}

/** The pending tags no script carries yet: once one does, it is an ordinary tag (renamed and deleted on the server). */
export function livePending(
  pendingTags: readonly string[],
  replies: readonly { tags?: string[] | null }[],
): string[] {
  return pendingTags.filter((t) => !replies.some((r) => (r.tags ?? []).includes(t)));
}

export function scriptsPageReducer(s: ScriptsPageState, a: Action): ScriptsPageState {
  switch (a.type) {
    case "view":
      return { ...s, view: a.view, checked: new Set() };
    case "open":
      return { ...s, view: VIEW_OF[a.kind], open: { ...s.open, [a.kind]: a.name }, checked: new Set() };
    case "check": {
      const checked = new Set(s.checked);
      for (const id of a.ids) {
        if (a.on) checked.add(id);
        else checked.delete(id);
      }
      return { ...s, checked };
    }
    case "setChecked":
      return { ...s, checked: new Set(a.ids) };
    case "addTag": {
      const pendingTags = a.pending ? [...s.pendingTags, a.name] : s.pendingTags;
      return scriptsPageReducer({ ...s, pendingTags }, { type: "open", kind: "tag", name: a.name });
    }
    case "renameEntry": {
      const pendingTags = a.kind === "tag" ? s.pendingTags.map((t) => (t === a.from ? a.to : t)) : s.pendingTags;
      const wasOpen = activeEntry(s.open[a.kind], a.order) === a.from;
      return { ...s, pendingTags, open: wasOpen ? { ...s.open, [a.kind]: a.to } : s.open };
    }
    case "deleteEntry": {
      const pendingTags = a.kind === "tag" ? s.pendingTags.filter((t) => t !== a.name) : s.pendingTags;
      if (activeEntry(s.open[a.kind], a.order) !== a.name) return { ...s, pendingTags };
      return { ...s, pendingTags, open: { ...s.open, [a.kind]: neighbour(a.order, a.name) }, checked: new Set() };
    }
    case "reset":
      return { ...INITIAL, view: s.view };
  }
}
