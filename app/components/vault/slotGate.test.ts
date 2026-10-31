import { describe, expect, it } from "vitest";

import { makeSlotGate } from "./slotGate";

type Op = readonly ["acquire" | "release", string];

/** Drive one gate through `ops`; a token is one grant callback per name. Returns who was granted, in order, and the
 *  most slots held at once (a slot is held from its grant to its first release). */
function drive(limit: number, ops: readonly Op[]) {
  const gate = makeSlotGate(limit);
  const tokens = new Map<string, () => void>();
  const granted: string[] = [];
  const held = new Set<string>();
  let peak = 0;
  const token = (name: string) => {
    if (!tokens.has(name)) {
      tokens.set(name, () => {
        granted.push(name);
        held.add(name);
        peak = Math.max(peak, held.size);
      });
    }
    return tokens.get(name)!;
  };
  for (const [op, name] of ops) {
    if (op === "acquire") gate.acquire(token(name));
    else {
      held.delete(name);
      gate.release(token(name));
    }
  }
  return { granted, peak };
}

const acq = (n: string): Op => ["acquire", n];
const rel = (n: string): Op => ["release", n];

describe("makeSlotGate", () => {
  it.each([
    ["never more than the limit in flight", 2, [acq("a"), acq("b"), acq("c"), acq("d")], ["a", "b"], 2],
    ["a release frees the next waiter, in order", 2,
      [acq("a"), acq("b"), acq("c"), acq("d"), rel("a"), rel("b")], ["a", "b", "c", "d"], 2],
    ["releasing a queued token cancels its wait", 1, [acq("a"), acq("b"), acq("c"), rel("b"), rel("a")], ["a", "c"], 1],
    ["releasing a held slot twice is a no-op", 1,
      [acq("a"), acq("b"), acq("c"), rel("a"), rel("a")], ["a", "b"], 1],
    ["releasing a cancelled wait twice is a no-op", 1,
      [acq("a"), acq("b"), acq("c"), rel("b"), rel("b")], ["a"], 1],
    ["releasing a token never handed in is a no-op", 1, [acq("a"), acq("b"), rel("x")], ["a"], 1],
    ["limit 1 serialises", 1,
      [acq("a"), acq("b"), acq("c"), rel("a"), rel("b"), rel("c")], ["a", "b", "c"], 1],
    ["a freed slot is reusable once all are back", 1, [acq("a"), rel("a"), acq("b")], ["a", "b"], 1],
  ] as const)("%s", (_, limit, ops, granted, peak) => {
    const got = drive(limit, ops);
    expect(got.granted).toEqual(granted);
    expect(got.peak).toBe(peak);
  });
});
