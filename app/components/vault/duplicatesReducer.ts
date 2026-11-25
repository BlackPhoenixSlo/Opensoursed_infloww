import type { HideDupesResult } from "@/hooks/useVaultCache";

export type DupesPhase =
  | { kind: "idle" }
  | { kind: "confirming"; frozenIds: readonly number[]; threshold: number }
  | { kind: "hiding"; frozenIds: readonly number[]; done: number }
  | { kind: "done"; result: HideDupesResult; total: number }
  | { kind: "error"; msg: string };

export interface DupesState {
  threshold: number;
  deselected: ReadonlySet<number>;
  phase: DupesPhase;
}

export type DupesAction =
  | { type: "threshold"; v: number }
  | { type: "toggle"; id: number }
  | { type: "toggleSet"; ids: readonly number[] }
  | { type: "confirm"; ids: readonly number[] }
  | { type: "cancel" }
  | { type: "hideStart" }
  | { type: "progress"; done: number }
  | { type: "hideOk"; result: HideDupesResult }
  | { type: "hideFail"; msg: string };

export function initialDupesState(): DupesState {
  return { threshold: 2, deselected: new Set(), phase: { kind: "idle" } };
}

export function selectedIdsOf(
  clusters: readonly { dupes: readonly { media_id: number }[] }[],
  deselected: ReadonlySet<number>,
): number[] {
  const out: number[] = [];
  for (const c of clusters) {
    for (const d of c.dupes) if (!deselected.has(d.media_id)) out.push(d.media_id);
  }
  return out;
}

export function allOff(ids: readonly number[], deselected: ReadonlySet<number>): boolean {
  return ids.every((i) => deselected.has(i));
}

export function hidePayload(
  state: DupesState,
): { ids: readonly number[]; threshold: number } | null {
  const { phase } = state;
  return phase.kind === "confirming" ? { ids: phase.frozenIds, threshold: phase.threshold } : null;
}

export function doneText(result: HideDupesResult, total: number): string {
  return result.of_error
    ? `Removed ${result.hidden} of ${total}, then failed: ${result.of_error}`
    : `Removed ${result.hidden} ${result.hidden === 1 ? "copy" : "copies"} from the OnlyFans vault.`;
}

const IDLE: DupesPhase = { kind: "idle" };

function edit(state: DupesState, deselected: ReadonlySet<number>): DupesState {
  // A selection edit or new scan cancels a pending confirm so "Yes, remove them" never acts on an unreviewed set.
  const phase = state.phase.kind === "confirming" ? IDLE : state.phase;
  return { ...state, deselected, phase };
}

export function duplicatesReducer(state: DupesState, action: DupesAction): DupesState {
  const { phase } = state;
  if (
    phase.kind === "hiding" &&
    action.type !== "progress" &&
    action.type !== "hideOk" &&
    action.type !== "hideFail"
  ) {
    return state;
  }
  switch (action.type) {
    case "threshold":
      return { threshold: action.v, deselected: new Set(), phase: IDLE };
    case "toggle": {
      const next = new Set(state.deselected);
      if (next.has(action.id)) next.delete(action.id);
      else next.add(action.id);
      return edit(state, next);
    }
    case "toggleSet": {
      const on = allOff(action.ids, state.deselected);
      const next = new Set(state.deselected);
      for (const i of action.ids) {
        if (on) next.delete(i);
        else next.add(i);
      }
      return edit(state, next);
    }
    // Freeze the reviewed selection + threshold: the hide sends exactly that (OF has no undo).
    case "confirm":
      if (phase.kind === "confirming" || action.ids.length === 0) return state;
      return {
        ...state,
        phase: { kind: "confirming", frozenIds: [...action.ids], threshold: state.threshold },
      };
    case "cancel":
      return phase.kind === "confirming" ? { ...state, phase: IDLE } : state;
    case "hideStart":
      if (phase.kind !== "confirming") return state;
      return { ...state, phase: { kind: "hiding", frozenIds: phase.frozenIds, done: 0 } };
    case "progress":
      if (phase.kind !== "hiding") return state;
      return { ...state, phase: { ...phase, done: action.done } };
    case "hideOk":
      if (phase.kind !== "hiding") return state;
      return { ...state, phase: { kind: "done", result: action.result, total: phase.frozenIds.length } };
    case "hideFail":
      if (phase.kind !== "hiding") return state;
      return { ...state, phase: { kind: "error", msg: action.msg } };
  }
}
