import { GROUP_SLOT_CAP, isGroupSlot, sameSlot, type GroupSlot } from "@/lib/groupChannel";

export interface Ack { reqId: string; ok: boolean }

export interface SlotsState {
  hydrated: boolean;
  slots: GroupSlot[];
  active: number;
  acks: Ack[];
}

export type Action =
  | { type: "hydrate"; slots: readonly GroupSlot[]; heldElsewhere: readonly { slots: readonly GroupSlot[] }[] }
  | { type: "add"; slot: unknown; reqId?: string }
  | { type: "replace"; slots: readonly unknown[]; reqId?: string }
  | { type: "remove"; slot: GroupSlot }
  | { type: "dropHeldBy"; others: readonly { slots: readonly GroupSlot[] }[] }
  | { type: "select"; index: number }
  | { type: "acksSent"; reqIds: readonly string[] };

export const initialSlotsState: SlotsState = { hydrated: false, slots: [], active: 0, acks: [] };

// Slots from storage, a channel or a DOM event are untrusted: keep only valid ones, only accountId + fanId.
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

export function keptSlots(slots: readonly GroupSlot[], others: readonly { slots: readonly GroupSlot[] }[]): GroupSlot[] {
  return slots.filter((s) => !heldBy(s, others));
}

function withSlots(state: SlotsState, slots: GroupSlot[]): SlotsState {
  const shown = state.slots[state.active];
  const idx = shown ? slots.findIndex((s) => sameSlot(s, shown)) : -1;
  const active = idx >= 0 ? idx : Math.max(0, Math.min(state.active, slots.length - 1));
  return { ...state, slots, active };
}

// ack decided against the very state the add applies to, so a burst gets per-add truth
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
