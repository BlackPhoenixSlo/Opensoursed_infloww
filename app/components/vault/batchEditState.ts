import { type MetaKey, type RowMeta } from "./VaultImportDetails";

export const CRITERIA = [
  { key: "tag", label: "Tag other Creator(s)" },
  { key: "category", label: "Category" },
  { key: "hashtags", label: "Hashtags" },
  { key: "notes", label: "Notes" },
  { key: "price", label: "Suggested price", chip: "Price" },
] as const;

export interface BatchEdit {
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
      return { ...s, criteria: next.length === CRITERIA.length ? [] : next };
    }
    case "set":
      return s.values[a.key] === a.value ? s : { ...s, values: { ...s.values, [a.key]: a.value } };
  }
}

export const batchAll = (s: BatchEdit) => s.criteria.length === 0 || s.criteria.length === CRITERIA.length;

export const batchShown = (s: BatchEdit) => CRITERIA.filter((c) => batchAll(s) || s.criteria.includes(c.key));

export function buildBatchPayload(s: BatchEdit): RowMeta {
  const out: RowMeta = {};
  for (const c of batchShown(s)) out[c.key] = s.values[c.key] ?? "";
  return out;
}
