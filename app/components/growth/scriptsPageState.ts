import type { SavedReply, SavedReplySequenceMeta } from "@/lib/relay";
import {
  INITIAL_FILL, scriptFillReducer, type Action as FillAction, type ScriptFillState,
} from "@/components/growth/scriptFillState";
import { ofPlainText } from "@/lib/ofRichText";

export type View = "tags" | "sequences" | "manage";
export type EntryKind = "tag" | "sequence";

const VIEW_OF: Record<EntryKind, View> = { tag: "tags", sequence: "sequences" };

const KIND_OF: Record<View, EntryKind | null> = { tags: "tag", sequences: "sequence", manage: null };
export function kindOf(view: View): EntryKind | null {
  return KIND_OF[view];
}

export const ALL = "\u0000all";
export const UNCATEGORIZED = "\u0000uncategorized";

export type NamePrompt =
  | { kind: "sequence" }
  | { kind: "tag"; ids?: number[] }
  | { kind: "rename"; entry: EntryKind; from: string };

export type Modal =
  | { kind: "name"; prompt: NamePrompt }
  | { kind: "excel" }
  | { kind: "import" }
  | { kind: "share"; ids?: number[] };

export type SortBy = "recent" | "name";
export type SortOrder = "asc" | "desc";
export interface Sort {
  by: SortBy;
  order: SortOrder;
}

export type SeqSortBy = "custom" | "recent" | "name";
export interface SeqSort {
  by: SeqSortBy;
  order: SortOrder;
}

export interface ScriptsPageState {
  view: View;
  open: Record<EntryKind, string | null>;
  checked: ReadonlySet<number>;
  pendingTags: readonly string[];
  busy: ReadonlySet<number>;
  error: string | null;
  modal: Modal | null;
  search: { open: boolean; q: string };
  sort: Sort;
  seqSort: SeqSort;
  account: string | null;
  allModels: boolean;
  fill: ScriptFillState;
}

export type Action =
  | { type: "view"; view: View }
  | { type: "open"; kind: EntryKind; name: string }
  | { type: "check"; ids: readonly number[]; on: boolean }
  | { type: "setChecked"; ids: readonly number[] }
  | { type: "addTag"; name: string; pending: boolean }
  | { type: "renameEntry"; kind: EntryKind; from: string; to: string; order: readonly string[]; account: string | null }
  | { type: "deleteEntry"; kind: EntryKind; name: string; order: readonly string[]; account: string | null }
  | { type: "runStart"; ids: readonly number[] }
  | { type: "runEnd"; ids: readonly number[]; error: string | null; account: string | null }
  | { type: "openModal"; modal: Modal }
  | { type: "closeModal" }
  | { type: "searchToggle" }
  | { type: "searchQ"; q: string }
  | { type: "sortBy"; by: SortBy }
  | { type: "sortOrder"; order: SortOrder }
  | { type: "seqSort"; by: SeqSortBy }
  | { type: "reset"; account: string | null }
  | { type: "allModels" }
  | { type: "fill"; action: FillAction };

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
  seqSort: { by: "custom", order: "asc" },
  account: null,
  allModels: false,
  fill: INITIAL_FILL,
};

export function activeEntry(sel: string | null, order: readonly string[]): string | null {
  return sel != null && order.includes(sel) ? sel : (order[0] ?? null);
}

export function neighbour(order: readonly string[], name: string): string | null {
  const i = order.indexOf(name);
  if (i < 0) return null;
  return order[i + 1] ?? order[i - 1] ?? null;
}

export function livePending(
  pendingTags: readonly string[],
  replies: readonly { tags?: string[] | null }[],
): string[] {
  return pendingTags.filter((t) => !replies.some((r) => (r.tags ?? []).includes(t)));
}

const closeFill = (f: ScriptFillState) => scriptFillReducer(f, { type: "close" });

const otherCreator = (s: ScriptsPageState, account: string | null) => account !== s.account;

// An answer carries the Creator it was asked on: on another Creator's page it is dropped, but a run's end still frees its ids.
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
      const ended = new Set(a.ids);
      const freed = { ...s, busy: new Set([...s.busy].filter((id) => !ended.has(id))) };
      if (otherCreator(s, a.account)) return freed;
      if (a.error != null) return { ...freed, error: a.error };
      return scriptsPageReducer(freed, { type: "check", ids: a.ids, on: false });
    }
    case "openModal":
      return { ...s, modal: a.modal, fill: closeFill(s.fill) };
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
    case "seqSort": {
      const order: SortOrder =
        s.seqSort.by === a.by ? (s.seqSort.order === "asc" ? "desc" : "asc") : a.by === "recent" ? "desc" : "asc";
      return { ...s, seqSort: { by: a.by, order } };
    }
    case "reset":
      return {
        ...INITIAL, view: s.view, sort: s.sort, seqSort: s.seqSort, busy: s.busy, account: a.account,
        fill: scriptFillReducer(s.fill, { type: "reset", account: a.account }),
      };
    case "allModels":
      return { ...s, allModels: true, modal: null, checked: new Set(), fill: closeFill(s.fill) };
    case "fill": {
      const fill = scriptFillReducer(s.fill, a.action);
      if (fill === s.fill) return s;
      return { ...s, fill, modal: fill.dialog ? null : s.modal };
    }
  }
}


const collator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
export const byName = (a: string, b: string) => collator.compare(a, b);

export function tagCountsOf(replies: readonly SavedReply[], pending: readonly string[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const t of pending) m.set(t, 0);
  for (const r of replies) for (const t of r.tags ?? []) m.set(t, (m.get(t) ?? 0) + 1);
  return m;
}

export function sequencesOf(replies: readonly SavedReply[]): Map<string, SavedReply[]> {
  const m = new Map<string, SavedReply[]>();
  for (const r of replies) {
    if (!r.script_id) continue;
    const rows = m.get(r.script_id);
    if (rows) rows.push(r);
    else m.set(r.script_id, [r]);
  }
  return m;
}

export function entryIds(kind: EntryKind, name: string, replies: readonly SavedReply[]): number[] {
  return replies
    .filter((r) => (kind === "tag" ? (r.tags ?? []).includes(name) : r.script_id === name))
    .map((r) => r.id);
}

export function sequenceOrder(
  metas: ReadonlyMap<string, SavedReplySequenceMeta>,
  sequences: ReadonlyMap<string, readonly SavedReply[]>,
  sort: SeqSort,
): string[] {
  const dir = sort.order === "asc" ? 1 : -1;
  const list = [...sequences.keys()];
  if (sort.by === "name") return list.sort((a, b) => dir * byName(a, b));
  if (sort.by === "custom") {
    const pos = (n: string) => metas.get(n)?.position ?? Number.POSITIVE_INFINITY;
    return list.sort((a, b) => {
      const pa = pos(a);
      const pb = pos(b);
      return (pa === pb ? 0 : dir * (pa < pb ? -1 : 1)) || byName(a, b);
    });
  }
  const modified = new Map(list.map((n) => [n, sequenceHeader(metas.get(n), sequences.get(n) ?? []).modified ?? ""]));
  return list.sort((a, b) => dir * modified.get(a)!.localeCompare(modified.get(b)!) || byName(a, b));
}

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

export function firstGap(rows: readonly SavedReply[]): number | null {
  const steps = new Set(rows.map((r) => r.script_step ?? 0));
  const max = Math.max(0, ...steps);
  for (let s = 1; s <= max; s++) if (!steps.has(s)) return s;
  return null;
}

export function nextStep(rows: readonly SavedReply[]): number {
  return Math.max(0, ...rows.map((r) => r.script_step ?? 0)) + 1;
}

export function sequenceDates(rows: readonly SavedReply[]): { created?: string; modified?: string } {
  return {
    created: rows.map((r) => r.created_at ?? "").filter(Boolean).sort()[0],
    modified: rows.map((r) => r.updated_at ?? "").filter(Boolean).sort().at(-1),
  };
}

export function sequenceHeader(
  meta: SavedReplySequenceMeta | undefined,
  rows: readonly SavedReply[],
): { createdBy?: string; created?: string; modified?: string } {
  const d = sequenceDates(rows);
  const modified = [meta?.updated_at ?? "", d.modified ?? ""].filter(Boolean).sort().at(-1);
  return { createdBy: meta?.created_by || undefined, created: meta?.created_at || d.created, modified };
}

const haystacks = new WeakMap<SavedReply, string>();
function haystackOf(r: SavedReply): string {
  let h = haystacks.get(r);
  if (h === undefined) {
    h = [r.title, ofPlainText(r.text), r.notes, ...(r.tags ?? [])].map((v) => (v ?? "").toLowerCase()).join("\n");
    haystacks.set(r, h);
  }
  return h;
}

export function matchesSearch(r: SavedReply, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return haystackOf(r).includes(needle);
}

export interface ScriptListRow {
  r: SavedReply;
  stepLabel?: string;
}

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
