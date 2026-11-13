/**
 * VaultPackPickerModal's triage state as a pure reducer: the unsaved verdicts (`draft`), the view (`filter`) and the
 * tile the keyboard acts on (`focus`). They gate each other — a verdict in the "undecided" view drops the tile out of
 * it, so where focus lands next depends on the order the grid showed before the verdict — so they live together and
 * the component only dispatches.
 *
 * A tile shows, in order: its unsaved verdict, else its saved rung, else the server's `suggested` rung (a prefill from
 * Jev's answer). A suggestion is never a verdict: only a press (a rung, Enter, a tap) puts it in `draft`, and only
 * `draft` is saved (`buildPayload`).
 *
 * PRESELECT. An unfiled tile is a confident Jev photo (feet score >= .6) or, after them, a `possible` one (.3 <= score
 * < .6, never preselected: it arrives unticked on its suggestion; `possibleOnly` when nothing confident is left); one the server marks `preselect` (a known,
 * safe rung) arrives TICKED on its suggestion; `ticks` holds only the operator's untick / retick overrides. "File N preselected" (`buildFilePayload`) files every
 * ticked tile on its suggestion plus the unsaved draft (a rung pressed on a tile is a draft verdict and wins), in one
 * triage. A tick is never a verdict either: Save still sends only `draft`.
 */

import type { PackCandidate } from "@/hooks/useVaultCache";

export interface PickerState {
  /** Unsaved verdicts, media_id -> rung | null (null = reject). Absent = untouched this session. */
  draft: Record<number, string | null>;
  /** "undecided" | a rung | "all". */
  filter: string;
  /** The tile keys act on; null = the first shown. */
  focus: number | null;
  /** Untick (false) / retick (true) overrides of the server's `preselect`. Absent = `preselect`. */
  ticks: Record<number, boolean>;
}

/** `order` is the media ids the grid showed when the action was taken: where focus goes next is read from it. */
export type PickerAction =
  | { type: "rule"; mediaId: number; rung: string | null; order: number[] }
  | { type: "confirm"; item: PackCandidate; order: number[] }
  | { type: "move"; delta: number; order: number[] }
  | { type: "focus"; mediaId: number }
  | { type: "filter"; value: string }
  | { type: "tick"; mediaId: number; on: boolean }
  /** Save answered for these verdicts: they leave the draft, unless re-ruled while the request was out. */
  | { type: "saved"; verdicts: { media_id: number; rung: string | null }[] };

export const initialPickerState: PickerState = { draft: {}, filter: "undecided", focus: null, ticks: {} };

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
    case "tick":
      return state.ticks[action.mediaId] === action.on
        ? state
        : { ...state, ticks: { ...state.ticks, [action.mediaId]: action.on } };
    case "saved": {
      const draft = { ...state.draft };
      const ticks = { ...state.ticks };
      for (const v of action.verdicts) {
        if (draft[v.media_id] === v.rung) delete draft[v.media_id];
        // A saved reject comes back undecided (nothing is stored about it): never re-ticked by its preselect.
        if (v.rung === null) ticks[v.media_id] = false;
      }
      return { ...state, draft, ticks };
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

/** May `item` be filed on `rung`? Photos only (a clip filed before the rule can still be unfiled: `canPress`), and
 *  never the free (cheapest) rung when Jev says the body is not free-safe. The server refuses both. */
export function canFile(item: PackCandidate, rung: string, rungs: string[]): boolean {
  return item.kind === "photo" && !(rung === rungs[0] && item.free_ok === false);
}

/** May the tile be ticked: undecided (no saved rung, no unsaved verdict) with a suggestion it may be filed on. */
export function tickable(item: PackCandidate, state: PickerState, rungs: string[]): boolean {
  return (
    item.rung === null && !(item.media_id in state.draft) && !!item.suggested && canFile(item, item.suggested, rungs)
  );
}

/** Ticked: tickable, and the operator's override or else the server's `preselect` (never for a `possible` one). */
export function isTicked(item: PackCandidate, state: PickerState, rungs: string[]): boolean {
  return tickable(item, state, rungs) && (state.ticks[item.media_id] ?? (!!item.preselect && !item.possible));
}

/** The ticked tiles' verdicts: each on its suggestion. */
export function tickedVerdicts(
  all: PackCandidate[], state: PickerState, rungs: string[],
): { media_id: number; rung: string | null }[] {
  return all.filter((c) => isTicked(c, state, rungs)).map((c) => ({ media_id: c.media_id, rung: c.suggested }));
}

export function canFileTicked(all: PackCandidate[], state: PickerState, rungs: string[], busy: boolean): boolean {
  return !busy && all.some((c) => isTicked(c, state, rungs));
}

/** "File N preselected"'s verdicts: the ticked tiles on their suggestion plus the unsaved draft, by media id. */
export function buildFilePayload(
  all: PackCandidate[], state: PickerState, rungs: string[],
): { media_id: number; rung: string | null }[] {
  return [...tickedVerdicts(all, state, rungs), ...buildPayload(state)].sort((a, b) => a.media_id - b.media_id);
}

/** May the tile's `rung` button be pressed? `canFile`, or the tile is decided on that rung (not merely suggested):
 *  the press unfiles it, so a row already on the free rung that `canFile` refuses can always be taken off. */
export function canPress(item: PackCandidate, rung: string, rungs: string[], draft: PickerState["draft"]): boolean {
  const shown = shownRung(item, draft);
  return canFile(item, rung, rungs) || (shown.rung === rung && !shown.suggested);
}

/** The unfiled queue is only `possible` tiles (no unfiled confident photo left): the modal says so on "undecided". */
export function possibleOnly(all: PackCandidate[]): boolean {
  const queue = all.filter((c) => c.rung === null);
  return queue.length > 0 && queue.every((c) => c.possible);
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
 * it, Enter confirms its suggestion (or moves on); ←/→ and k/j step one tile, ↑/↓ one row of `cols`. A rung `canFile`
 * refuses (any rung for a clip, the free rung for a Jev body that is not free-safe) is no action.
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
    if (!canFile(focused, rungs[n - 1], rungs)) return null;
    return { type: "rule", mediaId: focused.media_id, rung: rungs[n - 1], order };
  }
  return null;
}
