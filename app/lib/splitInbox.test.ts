import { describe, expect, it } from "vitest";

import { groupOf, inboxGate, lockedGroup, splitInboxKey, type InboxSplit } from "./splitInbox";

// Fan ids are moved explicitly, so each one's group is known: f1, f3 in 1; f2 in 2.
const config = { group_count: 2, assignments: { f1: 1, f2: 2, f3: 1 } };
const FANS: [string, string][] = [["a", "f1"], ["a", "f2"], ["a", "f3"], ["b", "f1"], ["b", "f2"]];
const ok: InboxSplit = { status: "success", config };

describe("inboxGate", () => {
  it.each<[string, Record<string, number>, [string, InboxSplit][], {
    in: string[]; out?: string[]; pending?: string[]; failed?: string[];
  }]>([
    ["no pick serves every Fan", {}, [], { in: FANS.map(([a, f]) => `${a}:${f}`) }],
    ["the picked group only", { a: 1 }, [["a", ok]], { in: ["a:f1", "a:f3", "b:f1", "b:f2"], out: ["a:f2"] }],
    ["group 2", { a: 2 }, [["a", ok]], { in: ["a:f2", "b:f1", "b:f2"], out: ["a:f1", "a:f3"] }],
    ["both Creators picked", { a: 1, b: 2 }, [["a", ok], ["b", ok]],
      { in: ["a:f1", "a:f3", "b:f2"], out: ["a:f2", "b:f1"] }],
    ["split not read yet: held, nothing out", { a: 1 }, [], { in: ["b:f1", "b:f2"], pending: ["a"] }],
    ["split loading", { a: 1 }, [["a", { status: "pending" }]], { in: ["b:f1", "b:f2"], pending: ["a"] }],
    ["split read failed: held, Creator failed", { a: 1 }, [["a", { status: "error" }]],
      { in: ["b:f1", "b:f2"], failed: ["a"] }],
    ["pick above the count: every Fan out", { a: 3 }, [["a", ok]],
      { in: ["b:f1", "b:f2"], out: ["a:f1", "a:f2", "a:f3"] }],
  ])("%s", (_name, picks, splits, want) => {
    const gate = inboxGate(picks, new Map(splits));
    const by = (v: string) => FANS.filter(([a, f]) => gate.of(a, f) === v).map(([a, f]) => `${a}:${f}`);
    expect(by("in")).toEqual(want.in);
    expect(by("out")).toEqual(want.out ?? []);
    const held = [...(want.pending ?? []), ...(want.failed ?? [])];
    expect(by("held")).toEqual(FANS.filter(([a]) => held.includes(a)).map(([a, f]) => `${a}:${f}`));
    expect([...gate.pending]).toEqual(want.pending ?? []);
    expect([...gate.failed]).toEqual(want.failed ?? []);
  });
});

describe("groupOf", () => {
  /** Sixty invented Fan ids, as OF sends them (numbers). */
  const FAN_IDS = Array.from({ length: 60 }, (_, i) => 200000001 + i);
  const split = (group_count: number, assignments: Record<string, number> = {}) => ({ group_count, assignments });

  it("is stable for the same id and always within 1..N, and a new split spreads the Fans over every group", () => {
    for (let n = 1; n <= 9; n++) {
      for (const id of FAN_IDS) {
        const group = groupOf(id, split(n));
        expect(group).toBe(groupOf(id, split(n)));
        // The id as text names the same Fan, so the same group.
        expect(groupOf(String(id), split(n))).toBe(group);
        expect(Number.isInteger(group) && group >= 1 && group <= n).toBe(true);
      }
    }
    // Every Fan belongs to one group at once, and no group of three is left empty (story 51).
    expect(new Set(FAN_IDS.map((id) => groupOf(id, split(3))))).toEqual(new Set([1, 2, 3]));
  });

  it("honours an explicit assignment within range, and ignores one out of range", () => {
    const id = FAN_IDS[0];
    expect([1, 2, 3].map((g) => groupOf(id, split(3, { [String(id)]: g })))).toEqual([1, 2, 3]);
    // Out of range: the Fan falls back to the group the split alone gives.
    const unassigned = groupOf(id, split(3));
    expect(groupOf(id, split(3, { [String(id)]: 4 }))).toBe(unassigned);
    expect(groupOf(id, split(3, { [String(id)]: 0 }))).toBe(unassigned);
    // Another Fan's move does not touch this one.
    expect(groupOf(id, split(3, { [String(FAN_IDS[1])]: 2 }))).toBe(unassigned);
  });

  it("is the Fan id mod N plus 1, as the relay's split_inbox.group_of", () => {
    expect([9, 10, 11].map((id) => groupOf(id, split(3)))).toEqual([1, 2, 3]);
    // 9223372036854775807 % 3 === 1 (BigInt, exact).
    expect(groupOf("9223372036854775807", split(3))).toBe(Number(9223372036854775807n % 3n) + 1);
    expect(groupOf("abc", split(3))).toBe(1);
    expect(groupOf("-4", split(3))).toBe(1);
  });

  it("takes a 19-digit string id's mod without losing precision", () => {
    // Ten ids that differ only in their last digits: as JavaScript numbers
    // they are all the same double, so only their text tells them apart.
    const ids = Array.from({ length: 10 }, (_, i) => `123456789012345670${i}`);
    expect(new Set(ids.map(Number)).size).toBe(1);

    expect(new Set(ids.map((id) => groupOf(id, split(9)))).size).toBeGreaterThan(1);
    // An explicit move is found by the id's exact text.
    const moved = split(9, { [ids[3]]: 7 });
    expect(groupOf(ids[3], moved)).toBe(7);
    expect(ids.filter((id) => id !== ids[3]).map((id) => groupOf(id, moved)))
      .toEqual(ids.filter((id) => id !== ids[3]).map((id) => groupOf(id, split(9))));
  });
  it.each([[0], [3], [1.5]])("an out-of-range move (%s) falls back to the mod", (moved) => {
    const n = { group_count: 2, assignments: { x: moved } };
    expect(groupOf("x", n)).toBe(groupOf("x", { group_count: 2, assignments: {} }));
  });
});

describe("lockedGroup", () => {
  const two = { group_count: 2, assignments: {} };
  it.each<[string, typeof two | null, number | null | undefined, number | null]>([
    ["a bound chatter", two, 2, 2],
    ["an owner or unbound chatter", two, null, null],
    ["an older relay with no my_group", two, undefined, null],
    ["split not read yet", null, 2, null],
    ["an unsplit Creator", { group_count: 1, assignments: {} }, 1, null],
    ["a binding above the count", two, 3, null],
  ])("%s", (_name, config, myGroup, want) => {
    expect(lockedGroup(config, myGroup)).toBe(want);
  });
});

it("one cache key for every reader", () => {
  expect(splitInboxKey("a")).toEqual(["split-inbox", "a"]);
});
