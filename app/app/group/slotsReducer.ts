/**
 * The /group tab's state as a pure reducer: the slot list, which pane the
 * mobile tab strip shows, and the BroadcastChannel add-acks still owed. Every
 * write the page makes (mount hydrate, Fan List pick, money-rail replace,
 * BroadcastChannel add / replace, wake reconcile, pane close, tab pick) is an
 * action here; the page only dispatches.
 *
 *   • "Same fan" is `sameSlot` (lib/groupChannel): fan ids arrive as numbers
 *     (OF) or strings (Fansly snowflakes), and `123` / `"123"` are one fan.
 *   • Slots from outside (storage, a channel message, a DOM event) are
 *     untrusted: anything that is not `isGroupSlot` is dropped, and only
 *     `accountId` + `fanId` are kept.
 *   • `add` is the one add rule: a held fan is accepted with the list
 *     unchanged, a full list (GROUP_SLOT_CAP) or a malformed slot refuses,
 *     anything else is appended. With a `reqId` (a channel add) the result is
 *     queued as `{reqId, ok}` in `acks`, decided here against the very state
 *     the add is applied to — so a burst of adds in one tick each get the ack
 *     of what this tab actually did. The page posts queued acks from an
 *     effect and drains them with `acksSent`.
 *   • `replace` takes the valid, de-duplicated part of its list (capped); an
 *     empty result changes nothing and acks ok:false.
 *   • `active` follows the fan, not the index: an add shows the new slot; a
 *     remove / drop / replace keeps showing the same fan if it is still
 *     there, else the same position clamped to the list.
 *   • An action that changes nothing returns the same state (no render).
 */

import { GROUP_SLOT_CAP, isGroupSlot, sameSlot, type GroupSlot } from "@/lib/groupChannel";

export interface Ack { reqId: string; ok: boolean }

export interface SlotsState {
  /** False until the mount effect has read storage / the seed params. */
  hydrated: boolean;
  slots: GroupSlot[];
  /** Index into `slots` of the pane the mobile tab strip shows. */
  active: number;
  /** add-acks decided but not yet posted on the channel. */
  acks: Ack[];
}

export type Action =
  /** Mount: the restored or seeded list, minus fans an older live tab holds. */
  | { type: "hydrate"; slots: readonly GroupSlot[]; heldElsewhere: readonly { slots: readonly GroupSlot[] }[] }
  /** A Fan List pick (no reqId) or a channel `add` (reqId: ack owed). */
  | { type: "add"; slot: GroupSlot; reqId?: string }
  /** Money rail "open last 8": the channel (reqId) or the same-tab DOM event. */
  | { type: "replace"; slots: readonly GroupSlot[]; reqId?: string }
  | { type: "remove"; slot: GroupSlot }
  /** Wake reconcile: drop slots any of `others` also holds. */
  | { type: "dropHeldBy"; others: readonly { slots: readonly GroupSlot[] }[] }
  | { type: "select"; index: number }
  /** These acks were posted; take them off the queue. */
  | { type: "acksSent"; reqIds: readonly string[] };

export const initialSlotsState: SlotsState = { hydrated: false, slots: [], active: 0, acks: [] };

/** Valid slots only, `accountId` + `fanId` only, first of each fan, capped. */
function clean(list: readonly unknown[]): GroupSlot[] {
  const out: GroupSlot[] = [];
  for (const x of list) {
    if (!isGroupSlot(x) || out.some((s) => sameSlot(s, x))) continue;
    out.push({ accountId: x.accountId, fanId: x.fanId });
    if (out.length === GROUP_SLOT_CAP) break;
  }
  return out;
}

function heldBy(s: GroupSlot, others: readonly { slots: readonly GroupSlot[] }[]): boolean {
  return others.some((t) => t.slots.some((x) => sameSlot(x, s)));
}

/** New slot list; `active` stays on the same fan if present, else clamps. */
function withSlots(state: SlotsState, slots: GroupSlot[]): SlotsState {
  const shown = state.slots[state.active];
  const idx = shown ? slots.findIndex((s) => sameSlot(s, shown)) : -1;
  const active = idx >= 0 ? idx : Math.max(0, Math.min(state.active, slots.length - 1));
  return { ...state, slots, active };
}

function owe(state: SlotsState, reqId: string | undefined, ok: boolean): SlotsState {
  return reqId === undefined ? state : { ...state, acks: [...state.acks, { reqId, ok }] };
}

export function slotsReducer(state: SlotsState, action: Action): SlotsState {
  switch (action.type) {
    case "hydrate": {
      const slots = clean(action.slots.filter((s) => !heldBy(s, action.heldElsewhere)));
      return { ...state, hydrated: true, slots, active: Math.max(0, slots.length - 1) };
    }
    case "add": {
      const sel = action.slot;
      if (!isGroupSlot(sel)) return owe(state, action.reqId, false);
      if (state.slots.some((s) => sameSlot(s, sel))) return owe(state, action.reqId, true);
      if (state.slots.length >= GROUP_SLOT_CAP) return owe(state, action.reqId, false);
      const slots = [...state.slots, { accountId: sel.accountId, fanId: sel.fanId }];
      return owe({ ...state, slots, active: slots.length - 1 }, action.reqId, true);
    }
    case "replace": {
      const slots = clean(action.slots);
      if (slots.length === 0) return owe(state, action.reqId, false);
      return owe(withSlots(state, slots), action.reqId, true);
    }
    case "remove": {
      const slots = state.slots.filter((s) => !sameSlot(s, action.slot));
      return slots.length === state.slots.length ? state : withSlots(state, slots);
    }
    case "dropHeldBy": {
      const slots = state.slots.filter((s) => !heldBy(s, action.others));
      return slots.length === state.slots.length ? state : withSlots(state, slots);
    }
    case "select":
      return action.index === state.active || action.index < 0 || action.index >= state.slots.length
        ? state
        : { ...state, active: action.index };
    case "acksSent": {
      const acks = state.acks.filter((a) => !action.reqIds.includes(a.reqId));
      return acks.length === state.acks.length ? state : { ...state, acks };
    }
  }
}
