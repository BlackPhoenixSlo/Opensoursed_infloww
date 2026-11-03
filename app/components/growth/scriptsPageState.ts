/**
 * Growth > Scripts' page state as a pure reducer: the open view, the open tag and sequence, the checked scripts, the
 * tags added on this page before any script carries them, the scripts a remove / delete is still running on (`busy`)
 * and its last failure (`error`), the open overlay (`modal`), the search and Manage scripts' sort. Below it, the
 * page's pure derivations: tag counts, sequences, the open list's rows and the selection over them.
 *
 *   • Moving to another list (`view`, `open`, `addTag`) clears the checked scripts.
 *   • The open entry of a kind is `activeEntry(open[kind], order)`: the stored pick while the sidebar lists it,
 *     else the sidebar's first entry (All scripts on Tag, the first sequence on Sequence).
 *   • Deleting the open entry opens its neighbour in the sidebar (the next, else the previous, else none);
 *     deleting another keeps the open one.
 *   • Renaming the open entry keeps it open under its new name; renaming another keeps the open one. Checked
 *     scripts stay through a rename.
 *   • A run (a remove, a delete, a tag or sequence delete) marks its ids busy and clears the last error; its one
 *     `runEnd` frees its own ids only (an overlapping run's stay busy), then sets its error if it failed, else
 *     unchecks its ids (the server took them; a failed run keeps the ticks for a retry).
 *   • The name prompt and the Excel / Import / Share dialogs are one overlay (`modal`): opening one replaces another.
 *   • Closing the search clears its text.
 *   • Another Creator (`reset`) keeps the view and the sort (view preferences) and the busy ids (see `reset`): none
 *     of the last Creator's picks, checks, pending tags, error, overlay or search. An answer (a run's end, an
 *     entry's rename or delete) carries the Creator it was asked on: on another Creator's page it is dropped
 *     (`otherCreator`), but a run's end still frees its ids. Back on that Creator, its answers apply again.
 */

import type { SavedReply } from "@/lib/relay";

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

/** The open name modal, as data: its props (and `onOk`) are built each render, so OK acts on the page as it is
 *  then, not as it was when the modal opened (a refetch in between may have given a new tag its first script). */
export type NamePrompt =
  | { kind: "sequence" }
  | { kind: "tag"; ids?: number[] }
  | { kind: "rename"; entry: EntryKind; from: string };

/** The page's one overlay: the name prompt, or an Import / Share dialog. */
export type Modal =
  | { kind: "name"; prompt: NamePrompt }
  | { kind: "excel" }
  | { kind: "import" }
  | { kind: "share"; ids?: number[] };

export type SortBy = "recent" | "name";
export type SortOrder = "asc" | "desc";
/** Manage scripts' sort (#33). */
export interface Sort {
  by: SortBy;
  order: SortOrder;
}

export interface ScriptsPageState {
  view: View;
  /** The picked tag and sequence; null opens the first in the sidebar (ALL on Tag). */
  open: Record<EntryKind, string | null>;
  /** The checked scripts' ids. */
  checked: ReadonlySet<number>;
  /** Tags added from the More menu with nothing checked; shown while no script carries them (`livePending`). */
  pendingTags: readonly string[];
  /** Scripts a remove or delete is still running on: their delete buttons and the selection bar wait. */
  busy: ReadonlySet<number>;
  /** The last run's failure, shown above the list until the next run starts. */
  error: string | null;
  modal: Modal | null;
  /** The toolbar search; closed, it has no text. */
  search: { open: boolean; q: string };
  sort: Sort;
  /** The Creator the page shows (`reset`); null until the first pick. */
  account: string | null;
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
  /** `order` (both): the kind's sidebar as drawn when the user acted, before the server's answer refetches it;
   *  `account` (here and on runEnd): the Creator the user acted on. */
  | { type: "renameEntry"; kind: EntryKind; from: string; to: string; order: readonly string[]; account: string | null }
  | { type: "deleteEntry"; kind: EntryKind; name: string; order: readonly string[]; account: string | null }
  /** A run started on `ids` (none for a tag or sequence delete): they are busy, the last error goes. */
  | { type: "runStart"; ids: readonly number[] }
  /** A run ended: its `ids` are free (another run's stay busy); `error`: its failure, null when the server took it. */
  | { type: "runEnd"; ids: readonly number[]; error: string | null; account: string | null }
  | { type: "openModal"; modal: Modal }
  | { type: "closeModal" }
  /** The search icon: opens the search, or closes it and clears its text. */
  | { type: "searchToggle" }
  | { type: "searchQ"; q: string }
  | { type: "sortBy"; by: SortBy }
  | { type: "sortOrder"; order: SortOrder }
  /** Another Creator (`account`): nothing of this one's carries over but the view, the sort and the busy ids. */
  | { type: "reset"; account: string | null };

export const INITIAL: ScriptsPageState = {
  view: "tags",
  open: { tag: null, sequence: null },
  checked: new Set(),
  pendingTags: [],
  busy: new Set(),
  error: null,
  modal: null,
  search: { open: false, q: "" },
  sort: { by: "recent", order: "desc" },
  account: null,
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

/** An answer to what was asked on `account` while the page shows another Creator: dropped. */
const otherCreator = (s: ScriptsPageState, account: string | null) => account !== s.account;

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
      if (otherCreator(s, a.account)) return s;
      const pendingTags = a.kind === "tag" ? s.pendingTags.map((t) => (t === a.from ? a.to : t)) : s.pendingTags;
      const wasOpen = activeEntry(s.open[a.kind], a.order) === a.from;
      return { ...s, pendingTags, open: wasOpen ? { ...s.open, [a.kind]: a.to } : s.open };
    }
    case "deleteEntry": {
      if (otherCreator(s, a.account)) return s;
      const pendingTags = a.kind === "tag" ? s.pendingTags.filter((t) => t !== a.name) : s.pendingTags;
      if (activeEntry(s.open[a.kind], a.order) !== a.name) return { ...s, pendingTags };
      return { ...s, pendingTags, open: { ...s.open, [a.kind]: neighbour(a.order, a.name) }, checked: new Set() };
    }
    case "runStart":
      return { ...s, error: null, busy: new Set([...s.busy, ...a.ids]) };
    case "runEnd": {
      const freed = { ...s, busy: new Set([...s.busy].filter((id) => !a.ids.includes(id))) };
      if (otherCreator(s, a.account)) return freed;
      if (a.error != null) return { ...freed, error: a.error };
      return scriptsPageReducer(freed, { type: "check", ids: a.ids, on: false });
    }
    case "openModal":
      return { ...s, modal: a.modal };
    case "closeModal":
      return { ...s, modal: null };
    case "searchToggle":
      return { ...s, search: s.search.open ? { open: false, q: "" } : { ...s.search, open: true } };
    case "searchQ":
      return { ...s, search: { ...s.search, q: a.q } };
    case "sortBy":
      return { ...s, sort: { ...s.sort, by: a.by } };
    case "sortOrder":
      return { ...s, sort: { ...s.sort, order: a.order } };
    case "reset":
      // `busy` stays: script ids are global DB ids, so the last Creator's never show on this one, and a run still
      // out on them keeps their rows waiting if the user comes back (no second POST); its `runEnd` frees them.
      return { ...INITIAL, view: s.view, sort: s.sort, busy: s.busy, account: a.account };
  }
}

/* ── derivations ─────────────────────────────────────────────────────────── */

export const byName = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: "base" });

/** Each tag's script count: the pending tags at 0, then every tag a script carries. */
export function tagCountsOf(replies: readonly SavedReply[], pending: readonly string[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const t of pending) m.set(t, 0);
  for (const r of replies) for (const t of r.tags ?? []) m.set(t, (m.get(t) ?? 0) + 1);
  return m;
}

/** Each sequence's scripts, in list order. */
export function sequencesOf(replies: readonly SavedReply[]): Map<string, SavedReply[]> {
  const m = new Map<string, SavedReply[]>();
  for (const r of replies) if (r.script_id) m.set(r.script_id, [...(m.get(r.script_id) ?? []), r]);
  return m;
}

/** A sequence's scripts in step order, each with its label: the step, or "step.option" when a step holds several. */
export function sequenceSteps(rows: readonly SavedReply[]): Array<{ r: SavedReply; label: string }> {
  const sorted = [...rows].sort((a, b) => (a.script_step ?? 0) - (b.script_step ?? 0) || a.id - b.id);
  const perStep = new Map<number, number>();
  for (const r of sorted) perStep.set(r.script_step ?? 0, (perStep.get(r.script_step ?? 0) ?? 0) + 1);
  const seen = new Map<number, number>();
  return sorted.map((r) => {
    const step = r.script_step ?? 0;
    const i = (seen.get(step) ?? 0) + 1;
    seen.set(step, i);
    return { r, label: (perStep.get(step) ?? 1) > 1 ? `${step}.${i}` : String(step) };
  });
}

/** The first step number a sequence skips: the chat's next-step suggestion stops before it. */
export function firstGap(rows: readonly SavedReply[]): number | null {
  const steps = new Set(rows.map((r) => r.script_step ?? 0));
  const max = Math.max(0, ...steps);
  for (let s = 1; s <= max; s++) if (!steps.has(s)) return s;
  return null;
}

/** The step Add script / Add step seeds in a sequence: one past its last. */
export function nextStep(rows: readonly SavedReply[]): number {
  return Math.max(0, ...rows.map((r) => r.script_step ?? 0)) + 1;
}

/** A sequence's header dates: its first script's creation and its last edit (none when no script has one). */
export function sequenceDates(rows: readonly SavedReply[]): { created?: string; modified?: string } {
  return {
    created: rows.map((r) => r.created_at ?? "").filter(Boolean).sort()[0],
    modified: rows.map((r) => r.updated_at ?? "").filter(Boolean).sort().at(-1),
  };
}

/** Whether the search `q` finds the script: in its name, text, notes or tags, case-blind; no text finds all. */
export function matchesSearch(r: SavedReply, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [r.title, r.text, r.notes, ...(r.tags ?? [])].some((v) => (v ?? "").toLowerCase().includes(needle));
}

export interface ScriptListRow {
  r: SavedReply;
  /** In a sequence: the step label (`sequenceSteps`). */
  stepLabel?: string;
}

/** The open view's list: the open sequence's steps, the open tag's (or all, or the untagged) scripts, or Manage
 *  scripts' sorted list; each filtered by the search. */
export function scriptRows(p: {
  view: View;
  replies: readonly SavedReply[];
  sequences: ReadonlyMap<string, SavedReply[]>;
  activeSeq: string | null;
  activeTag: string;
  q: string;
  sort: Sort;
}): ScriptListRow[] {
  const { view, replies, sequences, activeSeq, activeTag, q, sort } = p;
  if (view === "sequences") {
    return activeSeq ? sequenceSteps(sequences.get(activeSeq) ?? []).filter(({ r }) => matchesSearch(r, q)).map(
      ({ r, label }) => ({ r, stepLabel: label }),
    ) : [];
  }
  let list = replies.filter((r) => matchesSearch(r, q));
  if (view === "tags") {
    if (activeTag === UNCATEGORIZED) list = list.filter((r) => !(r.tags ?? []).length);
    else if (activeTag !== ALL) list = list.filter((r) => (r.tags ?? []).includes(activeTag));
  } else {
    const dir = sort.order === "asc" ? 1 : -1;
    list = [...list].sort((a, b) =>
      sort.by === "name"
        ? dir * byName(a.title ?? "", b.title ?? "")
        : dir * ((a.updated_at ?? "").localeCompare(b.updated_at ?? "") || a.id - b.id),
    );
  }
  return list.map((r) => ({ r }));
}

/** The selection over the list as shown: its ids, the checked ones among them, whether all are, and whether any
 *  checked one is still being removed / deleted (the selection bar waits for its answer: no second POST). */
export function selectionOf(
  rows: readonly ScriptListRow[],
  checked: ReadonlySet<number>,
  busy: ReadonlySet<number>,
): { listIds: number[]; checkedInList: number[]; allChecked: boolean; selBusy: boolean } {
  const listIds = rows.map(({ r }) => r.id);
  const checkedInList = listIds.filter((id) => checked.has(id));
  return {
    listIds,
    checkedInList,
    allChecked: listIds.length > 0 && checkedInList.length === listIds.length,
    selBusy: checkedInList.some((id) => busy.has(id)),
  };
}
