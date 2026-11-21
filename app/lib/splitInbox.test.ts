import { describe, expect, it } from "vitest";

import type { OFChatItem } from "@/lib/relay";

import { filterByInbox, groupOf, splitInboxKey, type InboxSplit } from "./splitInbox";

// Fan ids are moved explicitly, so each one's group is known: f1, f3 in 1; f2 in 2.
const config = { group_count: 2, assignments: { f1: 1, f2: 2, f3: 1 } };
const row = (aid: string, fid: string) => ({ __accountId: aid, withUser: { id: fid } }) as unknown as OFChatItem;
const rows = [row("a", "f1"), row("a", "f2"), row("a", "f3"), row("b", "f1"), row("b", "f2")];
const ok: InboxSplit = { status: "success", config };
const ids = (rs: readonly OFChatItem[]) => rs.map((c) => `${c.__accountId}:${c.withUser.id}`);
const sets = (m: ReadonlyMap<string, ReadonlySet<string>>) =>
  Object.fromEntries([...m].map(([k, v]) => [k, [...v].sort()]));

describe("filterByInbox", () => {
  it.each<[string, Record<string, number>, [string, InboxSplit][], {
    rows: string[]; out?: Record<string, string[]>; pending?: string[]; failed?: string[];
  }]>([
    ["no pick keeps every row", {}, [], { rows: ids(rows) }],
    ["the picked group only", { a: 1 }, [["a", ok]], { rows: ["a:f1", "a:f3", "b:f1", "b:f2"], out: { a: ["f2"] } }],
    ["group 2", { a: 2 }, [["a", ok]], { rows: ["a:f2", "b:f1", "b:f2"], out: { a: ["f1", "f3"] } }],
    ["both Creators picked", { a: 1, b: 2 }, [["a", ok], ["b", ok]],
      { rows: ["a:f1", "a:f3", "b:f2"], out: { a: ["f2"], b: ["f1"] } }],
    ["split not read yet: rows held back, nothing out", { a: 1 }, [],
      { rows: ["b:f1", "b:f2"], pending: ["a"] }],
    ["split loading", { a: 1 }, [["a", { status: "pending" }]], { rows: ["b:f1", "b:f2"], pending: ["a"] }],
    ["split read failed: rows held back, Creator failed", { a: 1 }, [["a", { status: "error" }]],
      { rows: ["b:f1", "b:f2"], failed: ["a"] }],
    ["pick above the count: no rows, every row out", { a: 3 }, [["a", ok]],
      { rows: ["b:f1", "b:f2"], out: { a: ["f1", "f2", "f3"] } }],
  ])("%s", (_name, picks, splits, want) => {
    const got = filterByInbox(rows, picks, new Map(splits));
    expect(ids(got.rows)).toEqual(want.rows);
    expect(sets(got.out)).toEqual(want.out ?? {});
    expect([...got.pending]).toEqual(want.pending ?? []);
    expect([...got.failed]).toEqual(want.failed ?? []);
  });

  it("returns the same rows when none is dropped", () => {
    expect(filterByInbox(rows, {}, new Map()).rows).toBe(rows);
    const one = [row("a", "f1")];
    expect(filterByInbox(one, { a: 1 }, new Map([["a", ok]])).rows).toBe(one);
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

  it("hashes a 19-digit string id without losing precision", () => {
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
  it.each([[0], [3], [1.5]])("an out-of-range move (%s) falls back to the hash", (moved) => {
    const n = { group_count: 2, assignments: { x: moved } };
    expect(groupOf("x", n)).toBe(groupOf("x", { group_count: 2, assignments: {} }));
  });
});

it("one cache key for every reader", () => {
  expect(splitInboxKey("a")).toEqual(["split-inbox", "a"]);
});
