/**
 * Batch edit's state (BatchEditModal in VaultImportDetails.tsx): the ticked criteria pick which fields show, and Save
 * writes the shown fields — and only those — onto every selected row.
 */

import { type MetaKey, type RowMeta } from "./VaultImportDetails";

/** Batch edit's criteria (#115); Hashtags and Notes start ticked. An empty
 *  list means All, as the bundle's `EditInfoModal` has it. */
export const CRITERIA = [
  { key: "tag", label: "Tag other Creator(s)" },
  { key: "category", label: "Category" },
  { key: "hashtags", label: "Hashtags" },
  { key: "notes", label: "Notes" },
  { key: "price", label: "Suggested price", chip: "Price" },
] as const;

export interface BatchEdit {
  /** Ticked keys; [] is All. */
  criteria: MetaKey[];
  values: RowMeta;
}

export type BatchEditAction =
  | { type: "all" }
  | { type: "toggle"; key: MetaKey }
  | { type: "set"; key: MetaKey; value: string };

export const BATCH_EDIT_INIT: BatchEdit = { criteria: ["hashtags", "notes"], values: {} };

export function batchEditReducer(s: BatchEdit, a: BatchEditAction): BatchEdit {
  switch (a.type) {
    case "all":
      return s.criteria.length === 0 ? s : { ...s, criteria: [] };
    case "toggle": {
      const next = s.criteria.includes(a.key) ? s.criteria.filter((k) => k !== a.key) : [...s.criteria, a.key];
      // Every one ticked is All.
      return { ...s, criteria: next.length === CRITERIA.length ? [] : next };
    }
    case "set":
      return s.values[a.key] === a.value ? s : { ...s, values: { ...s.values, [a.key]: a.value } };
  }
}

/** The All chip is on: none ticked (or every one). */
export const batchAll = (s: BatchEdit) => s.criteria.length === 0 || s.criteria.length === CRITERIA.length;

/** The criteria whose fields show, in CRITERIA order. */
export const batchShown = (s: BatchEdit) => CRITERIA.filter((c) => batchAll(s) || s.criteria.includes(c.key));

/** What Save writes onto each selected row: every shown field ("" if untouched), nothing else. */
export function buildBatchPayload(s: BatchEdit): RowMeta {
  const out: RowMeta = {};
  for (const c of batchShown(s)) out[c.key] = s.values[c.key] ?? "";
  return out;
}
