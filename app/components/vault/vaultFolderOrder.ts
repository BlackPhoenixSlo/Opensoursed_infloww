/**
 * vaultFolderOrder — VaultFolderRail's Customize order mode (drag to reorder OF folders).
 *
 *   off(null) ──start{ids}──▶ on{order, dragged:null} ──drag{id}──▶ on{dragged:id}
 *   on ──over{id}──▶ the dragged row moves into the hovered row's slot (`moveFolder`)
 *   on ──drop──▶ on{dragged:null}      on ──cancel──▶ off(null)
 *
 *   • The mode is on exactly while the state is non-null; nothing else says so.
 *   • A no-op returns the same state object, so React skips the render.
 *
 * Also `applyCustomOrder`: OF's folder list once it took a custom order.
 */

import { type FanId } from "@/lib/fanId";

/** Move `from` into `to`'s slot: remove it, then insert it at `to`'s old index. The same array back when
 *  `from === to` or either id is not in `order`. */
export function moveFolder(order: readonly FanId[], from: FanId, to: FanId): readonly FanId[] {
  if (from === to) return order;
  const i = order.indexOf(from);
  const j = order.indexOf(to);
  if (i < 0 || j < 0) return order;
  const next = [...order];
  next.splice(i, 1);
  next.splice(j, 0, from);
  return next;
}

/** `null` while the mode is off; else folder ids in the dragged order + the row being dragged. */
export type CustomizeState = null | { order: readonly FanId[]; dragged: FanId | null };

export type CustomizeAction =
  | { type: "start"; ids: readonly FanId[] }
  | { type: "cancel" }
  | { type: "drag"; id: FanId }
  | { type: "over"; id: FanId }
  | { type: "drop" };

/** `list` with the folders in `order` put in that sequence, in the slots those folders held; every other entry
 *  stays where it is, and an id in `order` that is not in `list` is skipped. Ids compare as strings (a Fansly id
 *  may come back as either). */
export function applyCustomOrder<T extends { id: FanId }>(list: readonly T[], order: readonly FanId[]): T[] {
  const rank = new Map(order.map((id, i) => [String(id), i]));
  const moved = list.filter((l) => rank.has(String(l.id)))
    .sort((a, b) => rank.get(String(a.id))! - rank.get(String(b.id))!);
  let k = 0;
  return list.map((l) => (rank.has(String(l.id)) ? moved[k++] : l));
}

export function customizeReducer(state: CustomizeState, action: CustomizeAction): CustomizeState {
  switch (action.type) {
    case "start":
      return { order: [...action.ids], dragged: null };
    case "cancel":
      return null;
    case "drag":
      return state === null ? state : { ...state, dragged: action.id };
    case "over": {
      if (state === null || state.dragged === null) return state;
      const order = moveFolder(state.order, state.dragged, action.id);
      return order === state.order ? state : { ...state, order };
    }
    case "drop":
      return state === null || state.dragged === null ? state : { ...state, dragged: null };
  }
}
