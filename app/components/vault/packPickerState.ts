/**
 * VaultPackPickerModal's triage state as a pure reducer: the unsaved verdicts (`draft`), the view (`filter`) and the
 * tile the keyboard acts on (`focus`). They gate each other — a verdict in the "undecided" view drops the tile out of
 * it, so where focus lands next depends on the order the grid showed before the verdict — so they live together and
 * the component only dispatches.
 *
 * A tile shows, in order: its unsaved verdict, else its saved rung, else the server's `suggested` rung (a prefill from
 * the stored flags). A suggestion is never a verdict: only a press (a rung, Enter, a tap) puts it in `draft`, and only
 * `draft` is saved (`buildPayload`).
 */

import type { PackCandidate } from "@/hooks/useVaultCache";

export interface PickerState {
  /** Unsaved verdicts, media_id -> rung | null (null = reject). Absent = untouched this session. */
  draft: Record<number, string | null>;
  /** "undecided" | a rung | "all". */
  filter: string;
  /** The tile keys act on; null = the first shown. */
  focus: number | null;
}

/** `order` is the media ids the grid showed when the action was taken: where focus goes next is read from it. */
export type PickerAction =
  | { type: "rule"; mediaId: number; rung: string | null; order: number[] }
  | { type: "confirm"; item: PackCandidate; order: number[] }
  | { type: "move"; delta: number; order: number[] }
  | { type: "focus"; mediaId: number }
  | { type: "filter"; value: string }
  /** Save answered for these verdicts: they leave the draft, unless re-ruled while the request was out. */
  | { type: "saved"; verdicts: { media_id: number; rung: string | null }[] };

export const initialPickerState: PickerState = { draft: {}, filter: "undecided", focus: null };

/** The tile after `id` in `order` (else the one before it, else none): a verdict hands focus on. */
function after(order: number[], id: number): number | null {
  const i = order.indexOf(id);
  if (i < 0) return order[0] ?? null;
  return order[i + 1] ?? order[i - 1] ?? null;
}

/** The focused tile's id: `focus` while it is shown, else the first shown. */
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
      // Enter takes the suggestion; on a decided tile (or one with nothing suggested) it only moves on.
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
    case "saved": {
      const draft = { ...state.draft };
      for (const v of action.verdicts) if (draft[v.media_id] === v.rung) delete draft[v.media_id];
      return { ...state, draft };
    }
  }
}

/** The saved rung overlaid with anything unsaved (no suggestion). */
export function effectiveRung(item: PackCandidate, draft: PickerState["draft"]): string | null {
  return item.media_id in draft ? draft[item.media_id] : item.rung;
}

/** What the tile shows: its verdict or saved rung, else the suggestion (`suggested` true: not decided yet). */
export function shownRung(item: PackCandidate, draft: PickerState["draft"]): { rung: string | null; suggested: boolean } {
  if (item.media_id in draft || item.rung !== null) return { rung: effectiveRung(item, draft), suggested: false };
  return { rung: item.suggested, suggested: item.suggested !== null };
}

/** The tiles the current view shows, in the server's order (most likely first). */
export function visibleCandidates(all: PackCandidate[], state: PickerState): PackCandidate[] {
  if (state.filter === "all") return all;
  if (state.filter === "undecided") {
    // Never ruled on: an explicit reject is a decision and drops out, which is what makes the pass converge.
    return all.filter((c) => c.rung === null && !(c.media_id in state.draft));
  }
  return all.filter((c) => effectiveRung(c, state.draft) === state.filter);
}

/** Decided per rung, unsaved verdicts included. */
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

/** The Save request's verdicts: every unsaved verdict, by media id. */
export function buildPayload(state: PickerState): { media_id: number; rung: string | null }[] {
  return Object.entries(state.draft)
    .map(([media_id, rung]) => ({ media_id: Number(media_id), rung }))
    .sort((a, b) => a.media_id - b.media_id);
}

/**
 * The action a key press means on the grid, or null (not ours). 1/2/3 file the focused tile on that rung, x rejects
 * it, Enter confirms its suggestion (or moves on); ←/→ and k/j step one tile, ↑/↓ one row of `cols`.
 */
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
    return { type: "rule", mediaId: focused.media_id, rung: rungs[n - 1], order };
  }
  return null;
}
