import type { BulkAction } from "./massUnsendRules";

export interface BulkRun {
  running: BulkAction | null;
  done: number;
  total: number;
  note: string | null;
}

export type BulkRunAction =
  | { type: "clear" }
  | { type: "nothing" }
  | { type: "start"; action: BulkAction; total: number }
  | { type: "progress"; done: number }
  | { type: "finish"; failed: number };

export const INITIAL_BULK_RUN: BulkRun = { running: null, done: 0, total: 0, note: null };

export const NOTHING_MATCHES = "Nothing to unsend matches that filter.";

export function failedNote(failed: number, total: number): string {
  return `${failed} of ${total} unsend${total === 1 ? "" : "s"} failed. Those broadcasts may still be live — refresh and retry.`;
}

export function bulkRunReducer(state: BulkRun, a: BulkRunAction): BulkRun {
  switch (a.type) {
    case "clear":
      return state.running ? state : INITIAL_BULK_RUN;
    case "nothing":
      return state.running ? state : { ...INITIAL_BULK_RUN, note: NOTHING_MATCHES };
    case "start":
      return { running: a.action, done: 0, total: a.total, note: null };
    case "progress":
      if (!state.running) return state;
      return { ...state, done: Math.min(Math.max(a.done, state.done), state.total) };
    case "finish":
      if (!state.running) return state;
      return { ...INITIAL_BULK_RUN, note: a.failed > 0 ? failedNote(a.failed, state.total) : null };
  }
}

export function bulkStatusLine(s: BulkRun): string | null {
  return s.running ? `Unsending ${s.done} of ${s.total}…` : null;
}
