import type { RowMeta } from "@/components/vault/VaultImportDetails";

export interface PickState {
  picked: readonly File[];
  selected: ReadonlySet<File>;
  details: ReadonlyMap<File, RowMeta>;
}

export type PickAction =
  | { type: "pick"; files: readonly File[] }
  | { type: "remove"; files: readonly File[] }
  | { type: "edit"; files: readonly File[]; values: RowMeta }
  | { type: "toggle"; file: File }
  | { type: "selectAll"; on: boolean };

export const initialPickState: PickState = { picked: [], selected: new Set(), details: new Map() };

export function chosenOf(s: PickState): File[] {
  return s.picked.filter((f) => s.selected.has(f));
}

export function importPickReducer(state: PickState, action: PickAction): PickState {
  switch (action.type) {
    case "pick":
      return { picked: [...action.files], selected: new Set(action.files), details: new Map() };
    case "remove": {
      const gone = new Set(action.files);
      if (gone.size === 0) return state;
      return {
        picked: state.picked.filter((f) => !gone.has(f)),
        selected: new Set([...state.selected].filter((f) => !gone.has(f))),
        details: new Map([...state.details].filter(([f]) => !gone.has(f))),
      };
    }
    case "edit": {
      const picked = new Set(state.picked);
      const on = action.files.filter((f) => picked.has(f));
      if (on.length === 0) return state;
      const details = new Map(state.details);
      for (const f of on) details.set(f, { ...details.get(f), ...action.values });
      return { ...state, details };
    }
    case "toggle": {
      if (!state.picked.includes(action.file)) return state;
      const selected = new Set(state.selected);
      if (!selected.delete(action.file)) selected.add(action.file);
      return { ...state, selected };
    }
    case "selectAll":
      return { ...state, selected: new Set(action.on ? state.picked : []) };
  }
}
