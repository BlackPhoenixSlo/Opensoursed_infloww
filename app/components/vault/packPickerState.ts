import type { PackCandidate } from "@/hooks/useVaultCache";

export interface PickerState {
  draft: Record<number, string | null>;
  filter: string;
  focus: number | null;
  ticks: Record<number, boolean>;
}

export type PickerAction =
  | { type: "rule"; mediaId: number; rung: string | null; order: number[] }
  | { type: "confirm"; item: PackCandidate; order: number[] }
  | { type: "move"; delta: number; order: number[] }
  | { type: "focus"; mediaId: number }
  | { type: "filter"; value: string }
  | { type: "tick"; mediaId: number; on: boolean }
  | { type: "saved"; verdicts: { media_id: number; rung: string | null }[] };

export const initialPickerState: PickerState = { draft: {}, filter: "undecided", focus: null, ticks: {} };

function after(order: number[], id: number): number | null {
  const i = order.indexOf(id);
  if (i < 0) return order[0] ?? null;
  return order[i + 1] ?? order[i - 1] ?? null;
}

export function focusedId(state: PickerState, order: number[]): number | null {
  return state.focus !== null && order.includes(state.focus) ? state.focus : order[0] ?? null;
}

export function pickerReducer(state: PickerState, action: PickerAction): PickerState {
  switch (action.type) {
    case "rule":
      return {
        ...state,
        draft: { ...state.draft, [action.mediaId]: action.rung },
        focus: after(action.order, action.mediaId),
      };
    case "confirm": {
      const { item, order } = action;
      const decided = item.media_id in state.draft || item.rung !== null;
      if (decided || !item.suggested) return { ...state, focus: after(order, item.media_id) };
      return pickerReducer(state, { type: "rule", mediaId: item.media_id, rung: item.suggested, order });
    }
    case "move": {
      if (!action.order.length) return state;
      const at = focusedId(state, action.order);
      const i = at === null ? 0 : action.order.indexOf(at);
      const j = Math.min(action.order.length - 1, Math.max(0, i + action.delta));
      return action.order[j] === state.focus ? state : { ...state, focus: action.order[j] };
    }
    case "focus":
      return state.focus === action.mediaId ? state : { ...state, focus: action.mediaId };
    case "filter":
      return { ...state, filter: action.value, focus: null };
    case "tick":
      return state.ticks[action.mediaId] === action.on
        ? state
        : { ...state, ticks: { ...state.ticks, [action.mediaId]: action.on } };
    case "saved": {
      const draft = { ...state.draft };
      const ticks = { ...state.ticks };
      for (const v of action.verdicts) {
        if (draft[v.media_id] === v.rung) delete draft[v.media_id];
        if (v.rung === null) ticks[v.media_id] = false;
      }
      return { ...state, draft, ticks };
    }
  }
}

export function effectiveRung(item: PackCandidate, draft: PickerState["draft"]): string | null {
  return item.media_id in draft ? draft[item.media_id] : item.rung;
}

export function shownRung(item: PackCandidate, draft: PickerState["draft"]): { rung: string | null; suggested: boolean } {
  if (item.media_id in draft || item.rung !== null) return { rung: effectiveRung(item, draft), suggested: false };
  return { rung: item.suggested, suggested: item.suggested !== null };
}

// The server refuses both: clips, and the free (cheapest) rung when Jev says the body is not free-safe.
export function canFile(item: PackCandidate, rung: string, rungs: string[]): boolean {
  return item.kind === "photo" && !(rung === rungs[0] && item.free_ok === false);
}

export function tickable(item: PackCandidate, state: PickerState, rungs: string[]): boolean {
  return (
    item.rung === null && !(item.media_id in state.draft) && !!item.suggested && canFile(item, item.suggested, rungs)
  );
}

export function isTicked(item: PackCandidate, state: PickerState, rungs: string[]): boolean {
  return tickable(item, state, rungs) && (state.ticks[item.media_id] ?? (!!item.preselect && !item.possible));
}

export function tickedVerdicts(
  all: PackCandidate[], state: PickerState, rungs: string[],
): { media_id: number; rung: string | null }[] {
  return all.filter((c) => isTicked(c, state, rungs)).map((c) => ({ media_id: c.media_id, rung: c.suggested }));
}

export function canFileTicked(all: PackCandidate[], state: PickerState, rungs: string[], busy: boolean): boolean {
  return !busy && all.some((c) => isTicked(c, state, rungs));
}

export function buildFilePayload(
  all: PackCandidate[], state: PickerState, rungs: string[],
): { media_id: number; rung: string | null }[] {
  return [...tickedVerdicts(all, state, rungs), ...buildPayload(state)].sort((a, b) => a.media_id - b.media_id);
}

export function canPress(item: PackCandidate, rung: string, rungs: string[], draft: PickerState["draft"]): boolean {
  const shown = shownRung(item, draft);
  return canFile(item, rung, rungs) || (shown.rung === rung && !shown.suggested);
}

export function possibleOnly(all: PackCandidate[]): boolean {
  const queue = all.filter((c) => c.rung === null);
  return queue.length > 0 && queue.every((c) => c.possible);
}

export function visibleCandidates(all: PackCandidate[], state: PickerState): PackCandidate[] {
  if (state.filter === "all") return all;
  if (state.filter === "undecided") {
    return all.filter((c) => c.rung === null && !(c.media_id in state.draft));
  }
  return all.filter((c) => effectiveRung(c, state.draft) === state.filter);
}

export function rungTally(all: PackCandidate[], draft: PickerState["draft"]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of all) {
    const r = effectiveRung(c, draft);
    if (r) out[r] = (out[r] ?? 0) + 1;
  }
  return out;
}

export function canSubmit(state: PickerState, busy: boolean): boolean {
  return !busy && Object.keys(state.draft).length > 0;
}

export function buildPayload(state: PickerState): { media_id: number; rung: string | null }[] {
  return Object.entries(state.draft)
    .map(([media_id, rung]) => ({ media_id: Number(media_id), rung }))
    .sort((a, b) => a.media_id - b.media_id);
}

export function keyAction(
  key: string,
  { focused, rungs, order, cols }: { focused: PackCandidate | null; rungs: string[]; order: number[]; cols: number },
): PickerAction | null {
  const step = (delta: number): PickerAction => ({ type: "move", delta, order });
  switch (key) {
    case "ArrowRight": case "j": return step(1);
    case "ArrowLeft": case "k": return step(-1);
    case "ArrowDown": return step(Math.max(1, cols));
    case "ArrowUp": return step(-Math.max(1, cols));
  }
  if (!focused) return null;
  if (key === "Enter") return { type: "confirm", item: focused, order };
  if (key === "x" || key === "X") return { type: "rule", mediaId: focused.media_id, rung: null, order };
  const n = Number(key);
  if (Number.isInteger(n) && n >= 1 && n <= rungs.length && key.length === 1) {
    if (!canFile(focused, rungs[n - 1], rungs)) return null;
    return { type: "rule", mediaId: focused.media_id, rung: rungs[n - 1], order };
  }
  return null;
}
