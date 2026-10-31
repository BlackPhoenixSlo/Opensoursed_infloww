import { describe, expect, it } from "vitest";

import {
  briefPhase,
  canCopy,
  customsPaneReducer as reduce,
  handoffText,
  initialCustomsPane as INIT,
  initialReopenLedger,
  mayReopen,
  pullTicket,
  reopenLedger,
  rowKey,
  type Brief,
  type ContextMsg,
  type CustomsPaneAction,
  type CustomsPaneState,
  type OrderLines,
  type Pane,
  type PaneRow,
  type ReopenEvent,
} from "./customsPaneReducer";

const A = "acc1:1";
const B = "acc1:2";
const msgs = (text: string): ContextMsg[] => [
  { message_id: 1, from_fan: true, text, at: null, is_tip: false, price_cents: 0 },
];
const brief = (summary: string): Brief => ({ ok: true, summary });
const order = (text: string): OrderLines => ({
  lines: [{ message_id: 1, from_fan: true, is_tip: false, text, at: "2026-10-01T10:00:00Z" }],
  count: 1,
});
const run = (actions: CustomsPaneAction[], from: CustomsPaneState = INIT) =>
  actions.reduce(reduce, from);
const AT = "2026-10-01T00:00:00Z";
const inFlight = (key: string, seq: number, at: string | null = AT): Pane => ({
  key, fan: key, seq, at, ctx: null, brief: null, order: null, copied: null,
});
const openA = run([{ type: "open", key: A, fan: A, seq: 1, at: AT }]);
const loadedA = run(
  [
    { type: "ctx", seq: 1, ctx: msgs("a") },
    { type: "brief", seq: 1, brief: brief("A's order") },
    { type: "order", seq: 1, order: order("a") },
  ],
  openA,
);
const paneOf = (s: CustomsPaneState) => s.pane;

describe("customsPaneReducer", () => {
  const copiedA = (n: number, ok: boolean) => run([{ type: "copyDone", seq: 1, n, ok }], loadedA);
  it.each<[string, CustomsPaneState, CustomsPaneAction, Partial<CustomsPaneState>]>([
    ["open resets the pane to in-flight", loadedA, { type: "open", key: B, fan: B, seq: 2, at: AT },
      { pane: inFlight(B, 2) }],
    ["open records the tip time it was opened at", INIT,
      { type: "open", key: A, fan: A, seq: 1, at: "2026-10-09T00:00:00Z" },
      { pane: inFlight(A, 1, "2026-10-09T00:00:00Z") }],
    ["open (same row) drops the copy note", copiedA(1, false),
      { type: "open", key: A, fan: A, seq: 2, at: AT }, { pane: inFlight(A, 2) }],
    ["close empties the pane and its copy note", copiedA(1, true), { type: "close" },
      { pane: null }],
    ["ctx for the current open applies", openA, { type: "ctx", seq: 1, ctx: msgs("a") },
      { pane: { ...inFlight(A, 1), ctx: msgs("a") } }],
    ["a failed thread lookup is stored as {error}, not an empty thread", openA,
      { type: "ctx", seq: 1, ctx: { error: "502" } },
      { pane: { ...inFlight(A, 1), ctx: { error: "502" } } }],
    ["brief for the current open applies", openA, { type: "brief", seq: 1, brief: brief("x") },
      { pane: { ...inFlight(A, 1), brief: brief("x") } }],
    ["order for the current open applies", openA, { type: "order", seq: 1, order: order("a") },
      { pane: { ...inFlight(A, 1), order: order("a") } }],
    ["a failed order lookup is stored as {error}, not an empty span", openA,
      { type: "order", seq: 1, order: { error: "timeout" } },
      { pane: { ...inFlight(A, 1), order: { error: "timeout" } } }],
    ["briefRetry on the current open puts the brief in flight", loadedA,
      { type: "briefRetry", seq: 1 },
      { pane: { ...paneOf(loadedA)!, brief: null } }],
    ["pullStart is a row button state, not gated on the open row", openA,
      { type: "pullStart", key: B }, { pulls: { [B]: "running" }, pane: inFlight(A, 1) }],
    ["pullStart on a second row keeps the first spinner",
      run([{ type: "pullStart", key: A }]), { type: "pullStart", key: B },
      { pulls: { [A]: "running", [B]: "running" } }],
    ["pullDone clears only its own row's spinner",
      run([{ type: "pullStart", key: A }, { type: "pullStart", key: B }]),
      { type: "pullDone", key: A }, { pulls: { [B]: "running" } }],
    ["pullDone with an error marks that row failed", run([{ type: "pullStart", key: A }]),
      { type: "pullDone", key: A, error: "ok=false" }, { pulls: { [A]: { error: "ok=false" } } }],
    ["pullStart on the failed row clears its failure",
      run([{ type: "pullDone", key: A, error: "x" }]), { type: "pullStart", key: A },
      { pulls: { [A]: "running" } }],
    ["pullStart on another row keeps the failure",
      run([{ type: "pullDone", key: A, error: "x" }]), { type: "pullStart", key: B },
      { pulls: { [A]: { error: "x" }, [B]: "running" } }],
    ["a later ok pull on the failed row clears its failure",
      run([{ type: "pullDone", key: A, error: "x" }, { type: "pullStart", key: A }]),
      { type: "pullDone", key: A }, { pulls: {} }],
    ["copyDone ok notes it in the pane", loadedA, { type: "copyDone", seq: 1, n: 1, ok: true },
      { pane: { ...paneOf(loadedA)!, copied: { n: 1, ok: true } } }],
    ["copyDone failed notes the failure", loadedA, { type: "copyDone", seq: 1, n: 1, ok: false },
      { pane: { ...paneOf(loadedA)!, copied: { n: 1, ok: false } } }],
    ["copyExpired clears its own copy's note", copiedA(1, true),
      { type: "copyExpired", n: 1 }, { pane: paneOf(loadedA) }],
    ["cleared on the open row's fan closes its pane", loadedA, { type: "cleared", fan: A },
      { pane: null }],
    ["cleared on the open row's fan mid-Pull closes its pane, its spinner runs to pullDone",
      run([{ type: "pullStart", key: A }], loadedA), { type: "cleared", fan: A },
      { pane: null, pulls: { [A]: "running" } }],
    ["cleared on a fan closes the pane of his OTHER review row (the backend settles the fan)",
      run([{ type: "open", key: `${A}:${AT}`, fan: A, seq: 1, at: AT }]), { type: "cleared", fan: A },
      { pane: null }],
  ])("%s", (_name, from, action, want) => {
    expect(reduce(from, action)).toEqual({ ...from, ...want });
  });

  const reopenedA = run([{ type: "open", key: A, fan: A, seq: 2, at: AT }], openA);
  it.each<[string, CustomsPaneState, CustomsPaneAction]>([
    ["ctx from an older open", reopenedA, { type: "ctx", seq: 1, ctx: msgs("old") }],
    ["a failed ctx from an older open", reopenedA, { type: "ctx", seq: 1, ctx: { error: "x" } }],
    ["brief from an older open", reopenedA, { type: "brief", seq: 1, brief: brief("old") }],
    ["order from an older open", reopenedA, { type: "order", seq: 1, order: order("old") }],
    ["a failed order from an older open", reopenedA, { type: "order", seq: 1, order: { error: "x" } }],
    ["briefRetry from an older open", reopenedA, { type: "briefRetry", seq: 1 }],
    ["any reply with nothing open", INIT, { type: "ctx", seq: 0, ctx: msgs("a") }],
    ["a reply after close", run([{ type: "close" }], openA), { type: "brief", seq: 1, brief: brief("a") }],
    ["close with nothing open", INIT, { type: "close" }],
    ["an older copy timer after a newer copy",
      run([{ type: "copyDone", seq: 1, n: 1, ok: true }, { type: "copyDone", seq: 1, n: 2, ok: true }], loadedA),
      { type: "copyExpired", n: 1 }],
    ["a copy that settles after close + reopen of the same row",
      run([{ type: "close" }, { type: "open", key: A, fan: A, seq: 2, at: AT }], loadedA),
      { type: "copyDone", seq: 1, n: 1, ok: true }],
    ["cleared on another fan: the open pane stays", loadedA, { type: "cleared", fan: B }],
    ["cleared on another fan: its Pull and the open pane stay",
      run([{ type: "pullStart", key: A }, { type: "pullStart", key: B }], loadedA),
      { type: "cleared", fan: B }],
    ["cleared on a fan mid-Pull with nothing open (mayReopen stops its reopen)",
      run([{ type: "pullStart", key: A }]), { type: "cleared", fan: A }],
  ])("ignores %s (same state object)", (_name, from, action) => {
    expect(reduce(from, action)).toBe(from);
  });

  it("race: open A (seq1), open A again (seq2) — seq1's reply is dropped, seq2's applies", () => {
    const s2 = run([{ type: "open", key: A, fan: A, seq: 1, at: AT }, { type: "open", key: A, fan: A, seq: 2, at: AT }]);
    const stale = reduce(s2, { type: "ctx", seq: 1, ctx: msgs("stale") });
    expect(stale).toBe(s2);
    expect(stale.pane?.ctx).toBeNull();
    const fresh = reduce(stale, { type: "ctx", seq: 2, ctx: msgs("fresh") });
    expect(fresh.pane?.ctx).toEqual(msgs("fresh"));
  });

  it("race: A and B replies interleaved out of order — only B's land, handoff uses B's brief", () => {
    const rowB: PaneRow = {
      marked: true, account_id: "acc1", account_name: "Model", fan_id: 2, display_name: "Bob",
      of_username: "bob", tip_cents: 10000, tipped_at: "2026-10-02T00:00:00Z",
    };
    const s = run([
      { type: "open", key: A, fan: A, seq: 1, at: AT },
      { type: "open", key: B, fan: B, seq: 2, at: AT },
      { type: "ctx", seq: 2, ctx: msgs("b thread") },
      { type: "brief", seq: 1, brief: brief("A's order") },
      { type: "ctx", seq: 1, ctx: msgs("a thread") },
      { type: "order", seq: 2, order: order("b line") },
      { type: "order", seq: 1, order: order("a line") },
      { type: "brief", seq: 2, brief: brief("B's order") },
    ]);
    expect(s).toEqual({
      ...INIT,
      pane: {
        ...inFlight(B, 2),
        ctx: msgs("b thread"),
        brief: brief("B's order"),
        order: order("b line"),
      },
    });
    expect(canCopy(s.pane!)).toBe(true);
    const text = handoffText(rowB, s.pane!);
    expect(text).toContain("B's order");
    expect(text).toContain("@bob");
    expect(text).not.toContain("A's order");
    expect(text).not.toContain("a line");
  });

  it("race: a brief retry on A answered after B opened does not land in B", () => {
    const s = run([
      { type: "briefRetry", seq: 1 },
      { type: "open", key: B, fan: B, seq: 2, at: AT },
      { type: "brief", seq: 1, brief: brief("A's order") },
    ], loadedA);
    expect(s.pane?.key).toBe(B);
    expect(s.pane?.brief).toBeNull();
  });

  it("race: cleared on A, then A's late replies land nowhere and B opens clean", () => {
    const s = run([
      { type: "cleared", fan: A },
      { type: "brief", seq: 1, brief: brief("A's order") },
      { type: "open", key: B, fan: B, seq: 2, at: AT },
      { type: "ctx", seq: 1, ctx: msgs("a thread") },
    ], openA);
    expect(s).toEqual({ ...INIT, pane: inFlight(B, 2) });
  });
});

describe("Pull's reopen rule (pullTicket → events → mayReopen)", () => {
  // Carl (acc1:1) has two review rows, K1 and K2; Dan is acc1:2. The Pull is on
  // Carl's K1; the events happen between its start and its ok rescrape.
  const CARL = "acc1:1";
  const DAN = "acc1:2";
  const moved: ReopenEvent = { type: "paneMoved" };
  it.each<[string, ReopenEvent[], boolean]>([
    ["nothing happened: reopens", [], true],
    ["an open (any row) since: no reopen", [moved], false],
    ["a close (Hide) since: no reopen", [moved, moved], false],
    ["Sent / Dismiss on Carl (K1 itself or his other review row K2): no reopen",
      [{ type: "cleared", fan: CARL }], false],
    ["Sent on another fan: still reopens", [{ type: "cleared", fan: DAN }], true],
  ])("%s", (_name, events, want) => {
    const start = reopenLedger(reopenLedger(initialReopenLedger, moved), { type: "cleared", fan: DAN });
    const ticket = pullTicket(start, CARL);
    expect(mayReopen(events.reduce(reopenLedger, start), ticket)).toBe(want);
  });
});

describe("rowKey", () => {
  const owed = { marked: true, account_id: "acc1", fan_id: 7, tipped_at: "2026-10-01T00:00:00Z" };
  const review = { ...owed, marked: false };
  it.each<[string, Parameters<typeof rowKey>[0], Parameters<typeof rowKey>[0], boolean]>([
    ["owed: same fan, newer tip (Refresh after he tips again) keeps the key", owed,
      { ...owed, tipped_at: "2026-10-03T00:00:00Z" }, true],
    ["owed: another fan", owed, { ...owed, fan_id: 8 }, false],
    ["owed: another account", owed, { ...owed, account_id: "acc2" }, false],
    ["review: same order", review, { ...review }, true],
    ["review: same fan, another order (two review rows)", review,
      { ...review, tipped_at: "2026-10-03T00:00:00Z" }, false],
    ["review: no anchor time vs one", { ...review, tipped_at: null }, review, false],
  ])("%s", (_name, x, y, same) => {
    expect(rowKey(x) === rowKey(y)).toBe(same);
  });
});

describe("briefPhase", () => {
  it.each<[Brief | null, ReturnType<typeof briefPhase>]>([
    [null, "loading"],
    [{ ok: false, reason: "x" }, "failed"],
    [{ ok: true, found_request: false, summary: "?" }, "not-found"],
    [{ ok: true, found_request: true, summary: "do it" }, "ready"],
    [{ ok: true, summary: "do it" }, "ready"],
  ])("%j → %s", (b, want) => {
    expect(briefPhase(b)).toBe(want);
  });
});

describe("canCopy", () => {
  const p = inFlight(A, 1);
  it.each<[string, Pane, boolean]>([
    ["all in flight", p, false],
    ["thread only", { ...p, ctx: msgs("a") }, false],
    ["brief settled, order in flight", { ...p, brief: brief("x") }, false],
    ["order settled, brief in flight", { ...p, order: order("a") }, false],
    ["both settled", { ...p, brief: brief("x"), order: order("a") }, true],
    ["both failed (settled)", { ...p, brief: { ok: false }, order: { error: "x" } }, true],
  ])("%s", (_name, pane, want) => {
    expect(canCopy(pane)).toBe(want);
  });
});

describe("handoffText", () => {
  const row: PaneRow = {
    marked: true, account_id: "acc1", account_name: "Model", fan_id: 9, display_name: "Dennis",
    of_username: "dennis", tip_cents: 20000, tipped_at: null,
  };
  const none = { brief: null, order: null };
  it.each<[string, PaneRow, Pick<Pane, "brief" | "order">, string[], string[]]>([
    ["ready brief is the request", row,
      { ...none, brief: { ok: true, summary: "5 min, red set", his_words: ["red one"], call_him: "daddy" }, order: order("raw") },
      ["-username: @dennis", "-account: Model", "-total: $200", "-call him: daddy",
        "  5 min, red set", "  His words:", '  "red one"'],
      ["raw"]],
    ["failed brief falls back to the order lines", row,
      { ...none, brief: { ok: false }, order: order("make it red") },
      [" HIM 2026-10-01  make it red"], ["(no order talk"]],
    ["not-found brief falls back to the order lines", row,
      { ...none, brief: { ok: true, found_request: false, summary: "unclear" }, order: order("red") },
      [" HIM 2026-10-01  red"], ["unclear"]],
    ["empty order says none found", row,
      { ...none, brief: { ok: false }, order: { lines: [], count: 0 } },
      ["(no order talk found in this thread"], ["lookup failed"]],
    ["failed order says the lookup failed, not none found", row,
      { brief: { ok: false }, order: { error: "timeout" } },
      ["(order lookup failed: timeout"], ["no order talk found"]],
    ["no handle → says so, with the fan id", { ...row, of_username: null },
      { ...none, brief: brief("x"), order: order("a") },
      ['-username: (not stored — fan #9, "Dennis")'], ["@"]],
    ["no total → no total line", { ...row, tip_cents: null },
      { ...none, brief: brief("x"), order: order("a") },
      ["-request:"], ["-total"]],
  ])("%s", (_name, r, pane, has, hasNot) => {
    const text = handoffText(r, pane);
    for (const h of has) expect(text).toContain(h);
    for (const h of hasNot) expect(text).not.toContain(h);
  });
});
