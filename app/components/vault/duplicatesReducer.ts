/**
 * duplicatesReducer — VaultDuplicatesModal's review → confirm → hide flow.
 *
 *   idle | done | error ──confirm{ids}──▶ confirming{frozenIds,threshold}
 *   confirming ──cancel / threshold / toggle──▶ idle
 *   confirming ──hideStart──▶ hiding{frozenIds,done} ──hideOk──▶ done{result,total}
 *                                                    └─hideFail─▶ error{msg}
 *
 *   • A later batch that fails still ends in `hideOk` (`hideDuplicates` returns
 *     what the earlier ones removed, with `of_error`): `doneText` says how many
 *     went, of how many, then the error. `hideFail` is a first batch that
 *     failed: nothing went.
 *
 *   • `confirm` FREEZES the selection the operator is looking at and the
 *     strictness it was scanned at; the hide request sends exactly that
 *     (`hidePayload`), never a later selection or threshold.
 *   • Changing the threshold (a new scan) or ticking a box while confirming
 *     drops back to idle — the confirm row vanishes, so "Yes, remove them"
 *     can never act on a set the operator did not review. OF has no undo.
 *   • While hiding, every action but progress / hideOk / hideFail is ignored
 *     (the request is already out with the frozen ids). `hiding` keeps
 *     `frozenIds` for the footer's "Removes N" line and the progress total.
 *   • A threshold change resets the unticked set and clears done / error
 *     (the old result described the old scan); a toggle in done / error
 *     keeps the banner, as before.
 */

import type { HideDupesResult } from "@/hooks/useVaultCache";

export type DupesPhase =
  | { kind: "idle" }
  | { kind: "confirming"; frozenIds: readonly number[]; threshold: number }
  | { kind: "hiding"; frozenIds: readonly number[]; done: number }
  /** `total`: the ids sent (the frozen selection). */
  | { kind: "done"; result: HideDupesResult; total: number }
  | { kind: "error"; msg: string };

export interface DupesState {
  threshold: number;
  /** Dupes the operator explicitly unticked — everything else is selected. */
  deselected: ReadonlySet<number>;
  phase: DupesPhase;
}

export type DupesAction =
  | { type: "threshold"; v: number }
  | { type: "toggle"; id: number }
  /** One set's "Keep all" / "Select set": all off → all on, else all off. */
  | { type: "toggleSet"; ids: readonly number[] }
  /** `ids` = the selection on screen; frozen (with the threshold) for the hide. Empty → ignored. */
  | { type: "confirm"; ids: readonly number[] }
  | { type: "cancel" }
  | { type: "hideStart" }
  | { type: "progress"; done: number }
  | { type: "hideOk"; result: HideDupesResult }
  | { type: "hideFail"; msg: string };

export function initialDupesState(): DupesState {
  return { threshold: 2, deselected: new Set(), phase: { kind: "idle" } };
}

/** Every dupe not explicitly unticked, in cluster order. */
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

/** Every one of a set's dupes is unticked ("Select set" rather than "Keep all"). */
export function allOff(ids: readonly number[], deselected: ReadonlySet<number>): boolean {
  return ids.every((i) => deselected.has(i));
}

/** What "Yes, remove them" sends — the ids and threshold frozen at confirm, only while confirming. */
export function hidePayload(
  state: DupesState,
): { ids: readonly number[]; threshold: number } | null {
  const { phase } = state;
  return phase.kind === "confirming" ? { ids: phase.frozenIds, threshold: phase.threshold } : null;
}

/** The done panel's line: how many OF removed; with an `of_error` (a batch failed after earlier ones went), of how
 *  many sent, then the error. */
export function doneText(result: HideDupesResult, total: number): string {
  return result.of_error
    ? `Removed ${result.hidden} of ${total}, then failed: ${result.of_error}`
    : `Removed ${result.hidden} ${result.hidden === 1 ? "copy" : "copies"} from the OnlyFans vault.`;
}

const IDLE: DupesPhase = { kind: "idle" };

/** A selection edit: cancels a pending confirm. */
function edit(state: DupesState, deselected: ReadonlySet<number>): DupesState {
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
