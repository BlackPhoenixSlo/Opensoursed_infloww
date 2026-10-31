import { describe, expect, it } from "vitest";

import { GROUP_SLOT_CAP, sameSlot, type GroupSlot } from "@/lib/groupChannel";
import { initialSlotsState, slotsReducer, type Ack, type Action, type SlotsState } from "./slotsReducer";

const A = "100000001";
const B = "100000002";
const SNOW = "900234567890123456"; // a Fansly snowflake: past 2^53, string only
const s = (fanId: number | string, accountId = A): GroupSlot => ({ accountId, fanId });
const range = (n: number) => Array.from({ length: n }, (_, i) => s(200000000 + i));
const FULL = range(GROUP_SLOT_CAP);
const st = (slots: GroupSlot[], active = Math.max(0, slots.length - 1), acks: Ack[] = []): SlotsState =>
  ({ hydrated: true, slots, active, acks });
const fold = (state: SlotsState, actions: Action[]) => actions.reduce(slotsReducer, state);
const add = (fanId: number | string, reqId?: string, accountId = A): Action =>
  ({ type: "add", slot: s(fanId, accountId), reqId });

describe("slotsReducer: actions in -> slots, acks, active out", () => {
  it.each<[string, SlotsState, Action[], GroupSlot[], Ack[], number]>([
    ["add to an empty list", st([]), [add(1, "r")], [s(1)], [{ reqId: "r", ok: true }], 0],
    ["add below the cap shows the new slot", st(range(3), 0), [add(9, "r")], [...range(3), s(9)], [{ reqId: "r", ok: true }], 3],
    ["add to a full list is refused", st(FULL, 2), [add(9, "r")], FULL, [{ reqId: "r", ok: false }], 2],
    ["number id of a held string id: ok, no dup", st([s("123")]), [add(123, "r")], [s("123")], [{ reqId: "r", ok: true }], 0],
    ["string id of a held number id: ok, no dup", st([s(123)]), [add("123", "r")], [s(123)], [{ reqId: "r", ok: true }], 0],
    ["held fan under the other shape is ok even when full", st(FULL), [add(String(FULL[3].fanId), "r")], FULL,
      [{ reqId: "r", ok: true }], GROUP_SLOT_CAP - 1],
    ["Fansly snowflake (string) appends", st([s(1)]), [add(SNOW, "r")], [s(1), s(SNOW)], [{ reqId: "r", ok: true }], 1],
    ["same fan id on another account is another slot", st([s(1, A)]), [add(1, "r", B)], [s(1, A), s(1, B)],
      [{ reqId: "r", ok: true }], 1],
    ["malformed adds are refused with an ack", st([s(1)]),
      [add("", "e"), add("abc", "x"), add(0, "z"), add(-5, "n"), add(1, "acct", "")], [s(1)],
      [{ reqId: "e", ok: false }, { reqId: "x", ok: false }, { reqId: "z", ok: false }, { reqId: "n", ok: false },
        { reqId: "acct", ok: false }], 0],
    ["a Fan List pick (no reqId) owes no ack", st([]), [add(1)], [s(1)], [], 0],
    ["burst past the cap: the add past it is refused", st(range(GROUP_SLOT_CAP - 2)),
      [add(1, "a"), add(2, "b"), add(3, "c")], [...range(GROUP_SLOT_CAP - 2), s(1), s(2)],
      [{ reqId: "a", ok: true }, { reqId: "b", ok: true }, { reqId: "c", ok: false }], GROUP_SLOT_CAP - 1],
    ["burst with a re-add under the other shape", st(range(GROUP_SLOT_CAP - 1)),
      [add(1, "a"), add("1", "b"), add(2, "c")], [...range(GROUP_SLOT_CAP - 1), s(1)],
      [{ reqId: "a", ok: true }, { reqId: "b", ok: true }, { reqId: "c", ok: false }], GROUP_SLOT_CAP - 1],
    ["add, replace, add: each acked against the list it hit", st(FULL),
      [add(1, "a"), { type: "replace", slots: [s(7), s(8)], reqId: "r" }, add(1, "b")], [s(7), s(8), s(1)],
      [{ reqId: "a", ok: false }, { reqId: "r", ok: true }, { reqId: "b", ok: true }], 2],
    ["a remove frees the slot the next add takes", st(FULL),
      [{ type: "remove", slot: s(String(FULL[0].fanId)) }, add(SNOW, "a")], [...FULL.slice(1), s(SNOW)],
      [{ reqId: "a", ok: true }], GROUP_SLOT_CAP - 1],
    ["replace dedupes mixed shapes and drops malformed", st([s(9)]),
      [{ type: "replace", slots: [s(1), s("1"), s("abc"), s(2), { accountId: A, fanId: 3, x: 1 } as GroupSlot], reqId: "r" }],
      [s(1), s(2), s(3)], [{ reqId: "r", ok: true }], 0],
    ["replace caps", st([]), [{ type: "replace", slots: range(GROUP_SLOT_CAP + 2) }], FULL, [], 0],
    ["a replace with nothing valid keeps the list and refuses", st([s(9)]),
      [{ type: "replace", slots: [s(""), s(0)], reqId: "r" }], [s(9)], [{ reqId: "r", ok: false }], 0],
    ["acksSent drains exactly the posted ids", st([], 0, [{ reqId: "a", ok: true }, { reqId: "b", ok: false }]),
      [add(1, "c"), { type: "acksSent", reqIds: ["a", "c"] }], [s(1)], [{ reqId: "b", ok: false }], 0],
  ])("%s", (_name, start, actions, slots, acks, active) => {
    const end = fold(start, actions);
    expect(end.slots).toEqual(slots);
    expect(end.acks).toEqual(acks);
    expect(end.active).toBe(active);
  });

  // The property the sender relies on: an ack says ok exactly when the fan
  // is in the list right after its add.
  it("every ack is ok exactly when its fan is in the list after its add", () => {
    const actions: Action[] = [
      add(1, "1"), add("1", "2"), add(SNOW, "3"), { type: "replace", slots: range(GROUP_SLOT_CAP - 1) },
      add(5, "4"), add(6, "5"), add(String(FULL[0].fanId), "6"), { type: "remove", slot: s(5) }, add(6, "7"),
      add("", "8"), add(SNOW, "9"),
    ];
    let state = st([]);
    for (const a of actions) {
      state = slotsReducer(state, a);
      if (a.type !== "add") continue;
      const ack = state.acks[state.acks.length - 1];
      expect(ack.reqId).toBe(a.reqId);
      expect(ack.ok).toBe(state.slots.some((x) => sameSlot(x, a.slot)));
      expect(state.slots.length).toBeLessThanOrEqual(GROUP_SLOT_CAP);
    }
  });
});

describe("slotsReducer: hydrate", () => {
  it.each<[string, GroupSlot[], GroupSlot[][], GroupSlot[], number]>([
    ["restores the list, shows the last", [s(1), s(SNOW)], [], [s(1), s(SNOW)], 1],
    ["drops fans an older tab holds (mixed shapes)", [s(1), s(2), s(3, B)], [[s("1")], [s(2), s(99)]], [s(3, B)], 0],
    ["the same fan id on another account stays", [s(3, B)], [[s(3, A)]], [s(3, B)], 0],
    ["caps and dedupes", [s(1), s("1"), ...range(GROUP_SLOT_CAP + 1)], [], [s(1), ...range(GROUP_SLOT_CAP - 1)],
      GROUP_SLOT_CAP - 1],
    ["empty", [], [], [], 0],
  ])("%s", (_name, slots, held, want, active) => {
    const end = slotsReducer(initialSlotsState, {
      type: "hydrate", slots, heldElsewhere: held.map((h) => ({ slots: h })),
    });
    expect(end).toEqual({ hydrated: true, slots: want, active, acks: [] });
  });
});

describe("slotsReducer: the shown pane follows the fan", () => {
  const cur = [s(1), s(2), s(3), s(4)];
  it.each<[string, number, Action, number]>([
    ["remove before the shown fan keeps it", 2, { type: "remove", slot: s("1") }, 1],
    ["dropHeldBy of an earlier slot keeps it", 3, { type: "dropHeldBy", others: [{ slots: [s(1), s(2)] }] }, 1],
    ["replace that still holds it moves with it", 1, { type: "replace", slots: [s(9), s(8), s(2)] }, 2],
    ["replace without it clamps", 3, { type: "replace", slots: [s(9), s(8)] }, 1],
    ["remove of the shown fan shows the next", 1, { type: "remove", slot: s(2) }, 1],
    ["remove of the shown last fan clamps", 3, { type: "remove", slot: s(4) }, 2],
    ["add shows the new fan", 0, add(5), 4],
    ["select picks a pane", 0, { type: "select", index: 2 }, 2],
  ])("%s", (_name, active, action, want) => {
    expect(slotsReducer(st(cur, active), action).active).toBe(want);
  });

  it("removing the only slot leaves active 0", () => {
    expect(slotsReducer(st([s(1)]), { type: "remove", slot: s(1) })).toMatchObject({ slots: [], active: 0 });
  });
});

describe("slotsReducer: no-op returns the same state", () => {
  const cur = st([s(1), s("2"), s(3, B)], 1);
  it.each<[string, Action]>([
    ["Fan List add of a held fan", add("1")],
    ["Fan List add of a malformed fan", add("abc")],
    ["empty replace", { type: "replace", slots: [] }],
    ["remove of an absent fan", { type: "remove", slot: s(42) }],
    ["remove on the wrong account", { type: "remove", slot: s(1, B) }],
    ["dropHeldBy with no overlap", { type: "dropHeldBy", others: [{ slots: [s(42), s(3, A)] }] }],
    ["dropHeldBy with no other tabs", { type: "dropHeldBy", others: [] }],
    ["select of the shown pane", { type: "select", index: 1 }],
    ["select out of range", { type: "select", index: 3 }],
    ["acksSent of nothing queued", { type: "acksSent", reqIds: ["x"] }],
  ])("%s", (_name, action) => {
    expect(slotsReducer(cur, action)).toBe(cur);
  });

  it("Fan List add to a full list", () => {
    const full = st(FULL);
    expect(slotsReducer(full, add(9))).toBe(full);
  });
});

describe("slotsReducer: input hygiene", () => {
  it("stores only accountId + fanId from a richer selection", () => {
    const sel = { accountId: A, fanId: 5, chat: { id: 1 } } as GroupSlot;
    expect(slotsReducer(st([]), { type: "add", slot: sel }).slots[0]).toEqual({ accountId: A, fanId: 5 });
  });

  it("does not mutate its input", () => {
    const cur = st([s(1), s(2)], 0, [{ reqId: "a", ok: true }]);
    const before = JSON.stringify(cur);
    fold(cur, [add(4, "b"), { type: "remove", slot: s(1) }, { type: "dropHeldBy", others: [{ slots: [s(2)] }] },
      { type: "replace", slots: [s(7)] }, { type: "acksSent", reqIds: ["a"] }, { type: "select", index: 1 }]);
    expect(JSON.stringify(cur)).toBe(before);
  });
});
