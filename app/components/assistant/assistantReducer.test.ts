import { describe, expect, it } from "vitest";

import { RelayError } from "@/lib/relay";

import {
  assistantReducer,
  initialAssistantState,
  settledFrom,
  settledFromError,
  groupByDay,
  historyFromRows,
  type AssistantAction,
  type EarlierTurn,
  type AssistantCore,
} from "./assistantReducer";

const run = (actions: AssistantAction[], from: AssistantCore = initialAssistantState) =>
  actions.reduce(assistantReducer, from);

const hydratedState = (open: boolean) => run([{ type: "hydrate", open }]);
const ask = (id: number, question = `q${id}`): AssistantAction => ({ type: "asked", id, question });
const answer = (id: number, rowId: number | null = null): AssistantAction => ({ type: "settled", id, answer: `a${id}`, error: null, rowId });
const route = (onHelpPage: boolean): AssistantAction => ({ type: "route", onHelpPage });

describe("assistantReducer", () => {
  it.each<[string, AssistantCore, AssistantAction[], Partial<AssistantCore>]>([
    ["open clears unread", { ...hydratedState(false), unread: true }, [{ type: "toggle" }], { open: true, unread: false }],
    ["close keeps unread false", hydratedState(true), [{ type: "toggle" }], { open: false, unread: false }],
    ["answer while open: no unread", hydratedState(true), [ask(0), answer(0)], { unread: false }],
    ["answer while closed: unread", hydratedState(false), [ask(0), answer(0)], { unread: true }],
    ["answer while closed on /help-center: no unread", hydratedState(false), [route(true), ask(0), answer(0)], { unread: false }],
    ["answer after leaving /help-center: unread", hydratedState(false), [route(true), route(false), ask(0), answer(0)], { unread: true }],
    ["route touches only onHelpPage", { ...hydratedState(true), unread: false }, [route(true)], { open: true, unread: false, onHelpPage: true }],
    ["answer right after closing: unread", hydratedState(true), [ask(0), { type: "toggle" }, answer(0)], { unread: true }],
    ["unread survives a later seen answer", hydratedState(false), [ask(0), ask(1), answer(0), route(true), answer(1)], { unread: true }],
    ["hydrate open clears unread", { ...initialAssistantState, unread: true }, [{ type: "hydrate", open: true }], { open: true, unread: false, hydrated: true }],
  ])("%s", (_name, from, actions, want) => {
    expect(run(actions, from)).toMatchObject(want);
  });

  it("route to the same page kind returns the same object", () => {
    const from = hydratedState(false);
    expect(assistantReducer(from, route(false))).toBe(from);
    const on = run([route(true)], from);
    expect(assistantReducer(on, route(true))).toBe(on);
  });

  it("hydrate after a local turn keeps the turn", () => {
    const s = run([ask(0, "how?"), { type: "hydrate", open: true }]);
    expect(s.turns).toEqual([{ id: 0, question: "how?", answer: null, error: null, rowId: null }]);
    expect(s).toMatchObject({ hydrated: true, open: true });
  });

  it("settles turns by id, in any order", () => {
    const s = run([ask(0), ask(1), answer(1), { type: "settled", id: 0, answer: "x", error: "cap", rowId: 5 }], hydratedState(true));
    expect(s.turns.map((t) => [t.id, t.answer, t.error])).toEqual([[0, "x", "cap"], [1, "a1", null]]);
  });

  it("is pure: never mutates the state it is given", () => {
    // Deep-frozen: in strict mode (ES modules) any write throws.
    const from = Object.freeze(run([ask(0), ask(1)], hydratedState(false)));
    from.turns.forEach((t) => Object.freeze(t));
    Object.freeze(from.turns);
    const snapshot = structuredClone(from);
    run([route(true), answer(1), route(false), answer(0), ask(2), { type: "toggle" }, { type: "hydrate", open: false }], from);
    expect(from).toEqual(snapshot);
  });
});

describe("settledFrom / settledFromError", () => {
  const EMPTY = "The assistant came back empty — try asking again.";
  it.each<[string, Parameters<typeof settledFrom>[1], string, string | null, number | null]>([
    ["answer, with its row id", { answer: "Go to Settings.", error: null, id: 41 }, "Go to Settings.", null, 41],
    ["answer is trimmed", { answer: "  hi \n", error: null, id: 42 }, "hi", null, 42],
    ["error tag kept with its sentence", { answer: "Cap used up.", error: "cap", id: 43 }, "Cap used up.", "cap", 43],
    ["row write failed: no row id", { answer: "ok", error: null, id: null }, "ok", null, null],
    ["blank answer: empty_answer", { answer: "   ", error: null, id: 44 }, EMPTY, "empty_answer", 44],
    ["blank answer overrides its tag", { answer: "", error: "provider", id: 45 }, EMPTY, "empty_answer", 45],
    ["null body: empty_answer", null, EMPTY, "empty_answer", null],
  ])("%s", (_name, r, answer, error, rowId) => {
    expect(settledFrom(7, r)).toEqual({ type: "settled", id: 7, answer, error, rowId });
  });

  it.each<[string, unknown, string]>([
    ["RelayError names its message", new RelayError(403, null, "relay 403"), "Couldn't reach the assistant (relay 403) — try again in a moment."],
    ["any other throw: no detail", new TypeError("fetch failed"), "Couldn't reach the assistant — try again in a moment."],
  ])("%s", (_name, e, answer) => {
    expect(settledFromError(3, e)).toEqual({ type: "settled", id: 3, answer, error: "transport", rowId: null });
  });
});

describe("history", () => {
  const turn = (id: number, over: Partial<EarlierTurn> = {}): EarlierTurn => ({
    id, rowId: -1 - id, question: `q${id}`, answer: `a${id}`, error: null, ts: "2026-11-07T10:00:00Z", ...over,
  });
  const loaded = (turns: EarlierTurn[]): AssistantAction => ({ type: "history_loaded", turns });

  it.each<[string, AssistantAction[], Partial<AssistantCore>]>([
    ["request: idle → loading", [{ type: "history_requested" }], { historyStatus: "loading" }],
    ["loaded: rows kept, status loaded", [{ type: "history_requested" }, loaded([turn(-2)])], { historyStatus: "loaded", history: [turn(-2)] }],
    ["failed: stays failed while open (no retry loop)", [{ type: "history_requested" }, { type: "history_failed" }, { type: "history_requested" }], { historyStatus: "failed", history: [] }],
    ["failed: the next open re-arms it", [{ type: "history_failed" }, { type: "toggle" }, { type: "toggle" }], { historyStatus: "idle", open: true }],
    ["request while loaded: no second load", [loaded([turn(-2)]), { type: "history_requested" }], { historyStatus: "loaded" }],
    ["loaded leaves this session's turns alone", [ask(0), loaded([turn(-2)])], { turns: [{ id: 0, question: "q0", answer: null, error: null, rowId: null }] }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions, hydratedState(true))).toMatchObject(want);
  });

  it("request while loading returns the same object", () => {
    const s = run([{ type: "history_requested" }], hydratedState(true));
    expect(assistantReducer(s, { type: "history_requested" })).toBe(s);
  });

  // A failed or slow history read, then a reload, must not show this
  // session's turn twice — under Earlier AND in the conversation. turn(-10)
  // is row 9, the row the ask below wrote.
  it.each<[string, AssistantAction[], number[]]>([
    ["load after the answer: its row is dropped from Earlier",
      [ask(0), answer(0, 9), loaded([turn(-1), turn(-10)])], [-1]],
    ["answer after the load: its row leaves Earlier",
      [ask(0), loaded([turn(-1), turn(-10)]), answer(0, 9)], [-1]],
    ["failed read, then the retry on the next open: still once",
      [{ type: "history_requested" }, { type: "history_failed" }, ask(0), answer(0, 9),
        { type: "toggle" }, { type: "toggle" }, { type: "history_requested" }, loaded([turn(-1), turn(-10)])], [-1]],
    ["no row id (its write failed): nothing to drop",
      [ask(0), answer(0, null), loaded([turn(-1), turn(-10)])], [-1, -10]],
  ])("dedupes by row id: %s", (_name, actions, historyIds) => {
    const s = run(actions, hydratedState(true));
    expect(s.turns.map((t) => t.id)).toEqual([0]);
    expect(s.history.map((t) => t.id)).toEqual(historyIds);
  });

  it.each<[string, Parameters<typeof historyFromRows>[0], EarlierTurn[]]>([
    ["rows newest-first → oldest-first, negative ids, row ids kept", { turns: [
      { id: 9, ts: "2026-11-07T10:00:00Z", question: "b", answer: "B", error: null },
      { id: 4, ts: "2026-11-06T10:00:00Z", question: "a", answer: "A", error: "cap" },
    ] }, [
      { id: -5, rowId: 4, question: "a", answer: "A", error: "cap", ts: "2026-11-06T10:00:00Z" },
      { id: -10, rowId: 9, question: "b", answer: "B", error: null, ts: "2026-11-07T10:00:00Z" },
    ]],
    ["no rows: empty", { turns: [] }, []],
  ])("historyFromRows: %s", (_name, body, want) => {
    expect(historyFromRows(body)).toEqual(want);
  });

  it("groupByDay labels local days: Today, Yesterday, a date, a past year", () => {
    const now = new Date(2026, 10, 7, 15);
    const at = (y: number, m: number, d: number, h = 9) => new Date(y, m, d, h).toISOString();
    const g = groupByDay([
      turn(-1, { ts: at(2025, 11, 31) }),
      turn(-2, { ts: at(2026, 10, 5) }),
      turn(-3, { ts: at(2026, 10, 5, 20) }),
      turn(-5, { ts: at(2026, 10, 6) }),
      turn(-6, { ts: at(2026, 10, 7, 1) }),
    ], now);
    expect(g.map((x) => [x.label, x.turns.map((t) => t.id)])).toEqual([
      ["Dec 31, 2025", [-1]],
      ["Nov 5", [-2, -3]],
      ["Yesterday", [-5]],
      ["Today", [-6]],
    ]);
  });
});
