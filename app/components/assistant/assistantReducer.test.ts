import { describe, expect, it } from "vitest";

import { RelayError } from "@/lib/relay";

import {
  assistantReducer,
  initialAssistantState,
  settledFrom,
  settledFromError,
  groupByDay,
  historyFromRows,
  appFocusOf,
  resolveFocus,
  sendFocusOf,
  threadsOf,
  turnsOf,
  type AssistantAction,
  type EarlierTurn,
  type AssistantCore,
  type Focus,
  type Roster,
  type ThreadSummary,
} from "./assistantReducer";

const run = (actions: AssistantAction[], from: AssistantCore = initialAssistantState) =>
  actions.reduce(assistantReducer, from);

const hydratedState = (open: boolean) => run([{ type: "hydrate", open }]);
const TS = "2026-11-10T12:00:00Z";
const ask = (id: number, question = `q${id}`, accountId: Focus = null, thread = "tN"): AssistantAction =>
  ({ type: "asked", id, question, ts: TS, thread, accountId });
const scope = (focus: Focus): AssistantAction => ({ type: "scope", focus });
const pick = (focus: Focus): AssistantAction => ({ type: "pick", focus });
const answer = (id: number, rowId: number | null = null): AssistantAction => ({ type: "settled", id, answer: `a${id}`, error: null, rowId });
const route = (onHelpPage: boolean): AssistantAction => ({ type: "route", onHelpPage });
const roster = (ids: string[] | null, isUser = true): AssistantAction => ({ type: "roster", ids, isUser });

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
    expect(s.turns).toEqual([{ id: 0, question: "how?", answer: null, error: null, rowId: null, thread: "tN", accountId: null, ts: TS }]);
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
    id, rowId: -1 - id, question: `q${id}`, answer: `a${id}`, error: null, ts: "2026-11-07T10:00:00Z",
    thread: "tOld", accountId: null, ...over,
  });
  const loaded = (turns: EarlierTurn[]): AssistantAction => ({ type: "history_loaded", turns });

  it.each<[string, AssistantAction[], Partial<AssistantCore>]>([
    ["request: idle → loading", [{ type: "history_requested" }], { historyStatus: "loading" }],
    ["loaded: rows kept, status loaded", [{ type: "history_requested" }, loaded([turn(-2)])], { historyStatus: "loaded", history: [turn(-2)] }],
    ["failed: stays failed while open (no retry loop)", [{ type: "history_requested" }, { type: "history_failed" }, { type: "history_requested" }], { historyStatus: "failed", history: [] }],
    ["failed: the next open re-arms it", [{ type: "history_failed" }, { type: "toggle" }, { type: "toggle" }], { historyStatus: "idle", open: true }],
    ["request while loaded: no second load", [loaded([turn(-2)]), { type: "history_requested" }], { historyStatus: "loaded" }],
    ["loaded leaves this session's turns alone", [ask(0), loaded([turn(-2)])], { turns: [{ id: 0, question: "q0", answer: null, error: null, rowId: null, thread: "tN", accountId: null, ts: TS }] }],
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
    ["rows newest-first → oldest-first, negative ids, row ids + thread kept", { turns: [
      { id: 9, ts: "2026-11-07T10:00:00Z", question: "b", answer: "B", error: null, account_id: "A1", thread_id: "t1" },
      { id: 4, ts: "2026-11-06T10:00:00Z", question: "a", answer: "A", error: "cap", account_id: null, thread_id: "t0" },
    ] }, [
      { id: -5, rowId: 4, question: "a", answer: "A", error: "cap", ts: "2026-11-06T10:00:00Z", thread: "t0", accountId: null },
      { id: -10, rowId: 9, question: "b", answer: "B", error: null, ts: "2026-11-07T10:00:00Z", thread: "t1", accountId: "A1" },
    ]],
    ["no rows: empty", { turns: [] }, []],
  ])("historyFromRows: %s", (_name, body, want) => {
    expect(historyFromRows(body)).toEqual(want);
  });

  it("historyFromRows: the server's thread as is; a NULL (an older server) is its own legacy-<id>", () => {
    const row = (id: number, thread_id: string | null) =>
      ({ id, ts: "2026-11-08T10:00:00Z", question: `q${id}`, answer: "x", error: null, account_id: "A", thread_id });
    const got = historyFromRows({ turns: [row(3, "legacy-1"), row(2, null), row(1, "legacy-1")] });
    expect(got.map((t) => [t.rowId, t.thread])).toEqual([[1, "legacy-1"], [2, "legacy-2"], [3, "legacy-1"]]);
  });

  it("groupByDay labels local days: Today, Yesterday, a date, a past year", () => {
    const now = new Date(2026, 10, 7, 15);
    const at = (y: number, m: number, d: number, h = 9) => new Date(y, m, d, h).toISOString();
    const th = (id: string, last: string): ThreadSummary => ({ id, focus: null, title: id, count: 1, last });
    const g = groupByDay([
      th("a", at(2026, 10, 7, 1)),
      th("b", at(2026, 10, 6)),
      th("c", at(2026, 10, 5, 20)),
      th("d", at(2026, 10, 5)),
      th("e", at(2025, 11, 31)),
    ], now);
    expect(g.map((x) => [x.label, x.threads.map((t) => t.id)])).toEqual([
      ["Today", ["a"]],
      ["Yesterday", ["b"]],
      ["Nov 5", ["c", "d"]],
      ["Dec 31, 2025", ["e"]],
    ]);
  });
});

describe("threads", () => {
  const h = (id: number, thread: string, ts: string, accountId: Focus = "A"): EarlierTurn =>
    ({ id: -1 - id, rowId: id, question: `h${id}`, answer: "x", error: null, ts, thread, accountId });

  it("threadsOf: one per thread, newest activity first, first question as title", () => {
    const s = run([
      { type: "history_loaded", turns: [
        h(1, "t1", "2026-11-08T10:00:00Z"), h(2, "t2", "2026-11-09T10:00:00Z", null), h(3, "t1", "2026-11-09T11:00:00Z"),
      ] },
      ask(0, "new one", "B", "t9"),
    ], hydratedState(true));
    expect(threadsOf(s.history, s.turns)).toEqual([
      { id: "t9", focus: "B", title: "new one", count: 1, last: TS },
      { id: "t1", focus: "A", title: "h1", count: 2, last: "2026-11-09T11:00:00Z" },
      { id: "t2", focus: null, title: "h2", count: 1, last: "2026-11-09T10:00:00Z" },
    ]);
    // Opening an old thread shows only its turns; an ask continues it.
    const o = run([{ type: "open_thread", thread: "t1", focus: "A" }, ask(1, "more", "A", "t1")], s);
    expect(turnsOf(o.active, o.history, o.turns).map((t) => t.question)).toEqual(["h1", "h3", "more"]);
    expect(o.turns[1].thread).toBe("t1");
    expect(turnsOf(null, o.history, o.turns)).toEqual([]);
  });

  // FOCUS: follows the app switcher; a pick holds until the next switch; a
  // started chat locks it (a switch is only held), and New chat adopts it.
  it.each<[string, AssistantAction[], Partial<AssistantCore>]>([
    ["starts General", [], { focus: null, active: null, held: false }],
    ["follows the switcher on home", [scope("A")], { focus: "A", appFocus: "A" }],
    ["all models → General", [scope("A"), scope(null)], { focus: null }],
    ["a pick holds while the switcher is unchanged", [scope("A"), pick("B"), scope("A")], { focus: "B" }],
    ["the next switch overrides a pick", [scope("A"), pick("B"), scope("C")], { focus: "C" }],
    ["first ask names the thread and locks its focus", [scope("A"), ask(0, "q", "A", "t1")], { active: "t1", focus: "A" }],
    ["a switch during a chat is held, not applied", [scope("A"), ask(0, "q", "A", "t1"), scope("B")], { focus: "A", held: true, active: "t1" }],
    ["switching back clears the hold", [scope("A"), ask(0, "q", "A", "t1"), scope("B"), scope("A")], { focus: "A", held: false }],
    ["New chat adopts a held switch", [scope("A"), ask(0, "q", "A", "t1"), scope("B"), { type: "new_chat" }], { focus: "B", held: false, active: null }],
    ["New chat keeps a pick when nothing was held", [scope("A"), pick("B"), ask(0, "q", "B", "t1"), { type: "new_chat" }], { focus: "B", active: null }],
    ["picking another focus mid-chat starts a new chat", [scope("A"), ask(0, "q", "A", "t1"), pick("B")], { focus: "B", active: null, held: false }],
    ["picking the same focus mid-chat keeps the chat", [scope("A"), ask(0, "q", "A", "t1"), pick("A")], { focus: "A", active: "t1" }],
    ["opening a thread takes its focus", [scope("A"), { type: "open_thread", thread: "t7", focus: null }], { focus: null, active: "t7" }],
    ["a switch after opening a thread is held", [scope("A"), { type: "open_thread", thread: "t7", focus: null }, scope("B")], { focus: null, held: true }],
    ["asked locks the focus to the account it went out with", [scope("X"), ask(0, "q", "A", "t1")], { focus: "A", active: "t1", appFocus: "X" }],
  ])("focus: %s", (_name, actions, want) => {
    expect(run(actions, hydratedState(true))).toMatchObject(want);
  });

  // ROSTER: the owned accounts; the focus stays raw and is resolved against it
  // on read, comparisons use resolved values, and a started thread is never retargeted.
  it.each<[string, AssistantAction[], Partial<AssistantCore>, Focus | undefined]>([
    ["before the roster: the unresolved focus goes out", [scope("X")], { focus: "X" }, "X"],
    ["a home focus the roster lacks stays raw and sends the first account", [scope("X"), roster(["A", "B"])], { focus: "X" }, "A"],
    ["an owned offline model (a page's pick) stays focused", [roster(["A", "X"]), scope("X")], { focus: "X" }, "X"],
    ["a chatter's General → the first account", [roster(["A"], false), scope(null)], { focus: null }, "A"],
    ["a chatter's General waits for the roster", [roster(null, false), scope(null)], { focus: null }, undefined],
    ["a user's General goes out before the roster", [roster(null, true), scope(null)], { focus: null }, null],
    ["no account at all: General for a user", [roster([], true), scope("X")], { focus: "X" }, null],
    ["no account at all, a chatter: nothing to send (server 401s General)", [roster([], false), scope("X")], { focus: "X" }, undefined],
    ["a roster empty for a moment never loses the app's model",
      [roster(null, false), scope("B"), roster([], false), roster(["A", "B"], false)], { focus: "B" }, "B"],
    ["a chatter's model, then the roster: it goes out as that model",
      [roster(null, false), scope("B"), roster(["A", "B"], false)], { focus: "B", active: null }, "B"],
    ["a switch resolving to the thread's own focus is no hold",
      [roster(["A", "B"], false), scope("A"), ask(0, "q", "A", "t1"), scope(null)], { held: false, active: "t1" }, "A"],
    ["a switch to a model the roster lacks holds its resolution",
      [roster(["A", "B"]), scope("B"), ask(0, "q", "B", "t1"), scope("Z")], { held: true, focus: "B" }, "B"],
    ["a hold the roster resolves away is cleared",
      [roster(null, false), scope("A"), ask(0, "q", "A", "t1"), scope("Z"), roster(["A", "B"], false)],
      { held: false, focus: "A", active: "t1" }, "A"],
    ["the roster dropping a started thread's model: an explicit new chat on the app's model",
      [scope("X"), ask(0, "q", "X", "t1"), scope("B"), roster(["A", "B"])], { active: null, focus: "B", held: false }, "B"],
    ["a roster keeping the thread's model leaves the chat alone",
      [scope("A"), ask(0, "q", "A", "t1"), roster(["A", "B"])], { active: "t1", focus: "A" }, "A"],
    ["opening a thread on a model the roster lacks is a new chat",
      [roster(["A"]), scope("A"), { type: "open_thread", thread: "t7", focus: "Z" }], { active: null, focus: "A" }, "A"],
    ["a pick resolving to the thread's focus keeps the chat",
      [roster(["A", "B"], false), scope("A"), ask(0, "q", "A", "t1"), pick(null)], { active: "t1", focus: "A" }, "A"],
    ["New chat follows the app's model raw (resolved on send)",
      [scope("A"), ask(0, "q", "A", "t1"), scope("Z"), roster(["A", "B"]), { type: "new_chat" }], { active: null, held: false, focus: "Z" }, "A"],
    ["New chat keeps a pick that differs from the app's model",
      [roster(["A", "B"]), scope("A"), pick("B"), ask(0, "q", "B", "t1"), { type: "new_chat" }], { active: null, focus: "B" }, "B"],
  ])("roster: %s", (_name, actions, want, sends) => {
    const s = run(actions, hydratedState(true));
    expect(s).toMatchObject(want);
    expect(sendFocusOf(s)).toBe(sends);
  });

  it("the offer names the switcher's model resolved", () => {
    const s = run([roster(["A", "B"]), scope("B"), ask(0, "q", "B", "t1"), scope("Z")], hydratedState(true));
    expect(appFocusOf(s)).toBe("A");
  });

  it("the same roster again returns the same object", () => {
    const s = run([roster(["A", "B"])], hydratedState(true));
    expect(assistantReducer(s, roster(["A", "B"]))).toBe(s);
  });

  it("a re-sent switcher value returns the same object", () => {
    const s = run([scope("A")], hydratedState(true));
    expect(assistantReducer(s, scope("A"))).toBe(s);
  });

  it.each<[string, Focus, Roster, Focus | undefined]>([
    ["a model in the roster", "B", { ids: ["A", "B"], isUser: true }, "B"],
    ["a model not in the roster → first", "Z", { ids: ["A", "B"], isUser: true }, "A"],
    ["General for a user", null, { ids: ["A"], isUser: true }, null],
    ["General for a chatter → first account", null, { ids: ["A"], isUser: false }, "A"],
    ["a user with nothing connected → General", "Z", { ids: [], isUser: true }, null],
    ["a chatter with no account → nothing to send (server 401s General)", "Z", { ids: [], isUser: false }, undefined],
    ["a chatter's General with no account → nothing to send", null, { ids: [], isUser: false }, undefined],
    ["loading: a model goes out raw (the server gates)", "Z", { ids: null, isUser: false }, "Z"],
    ["loading: a user's General goes out", null, { ids: null, isUser: true }, null],
    ["loading: a chatter's General waits", null, { ids: null, isUser: false }, undefined],
  ])("resolveFocus: %s", (_name, focus, r, want) => {
    expect(resolveFocus(focus, r)).toBe(want);
  });
});
