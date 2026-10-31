import { describe, expect, it } from "vitest";

import { RelayError } from "@/lib/relay";

import {
  assistantReducer,
  initialAssistantState,
  settledFrom,
  settledFromError,
  type AssistantAction,
  type AssistantCore,
} from "./assistantReducer";

const run = (actions: AssistantAction[], from: AssistantCore = initialAssistantState) =>
  actions.reduce(assistantReducer, from);

const hydratedState = (open: boolean) => run([{ type: "hydrate", open }]);
const ask = (id: number, question = `q${id}`): AssistantAction => ({ type: "asked", id, question });
const answer = (id: number): AssistantAction => ({ type: "settled", id, answer: `a${id}`, error: null });
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
    expect(s.turns).toEqual([{ id: 0, question: "how?", answer: null, error: null }]);
    expect(s).toMatchObject({ hydrated: true, open: true });
  });

  it("settles turns by id, in any order", () => {
    const s = run([ask(0), ask(1), answer(1), { type: "settled", id: 0, answer: "x", error: "cap" }], hydratedState(true));
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
  it.each<[string, Parameters<typeof settledFrom>[1], string, string | null]>([
    ["answer", { answer: "Go to Settings.", error: null }, "Go to Settings.", null],
    ["answer is trimmed", { answer: "  hi \n", error: null }, "hi", null],
    ["error tag kept with its sentence", { answer: "Cap used up.", error: "cap" }, "Cap used up.", "cap"],
    ["blank answer: empty_answer", { answer: "   ", error: null }, EMPTY, "empty_answer"],
    ["blank answer overrides its tag", { answer: "", error: "provider" }, EMPTY, "empty_answer"],
    ["null body: empty_answer", null, EMPTY, "empty_answer"],
  ])("%s", (_name, r, answer, error) => {
    expect(settledFrom(7, r)).toEqual({ type: "settled", id: 7, answer, error });
  });

  it.each<[string, unknown, string]>([
    ["RelayError names its message", new RelayError(403, null, "relay 403"), "Couldn't reach the assistant (relay 403) — try again in a moment."],
    ["any other throw: no detail", new TypeError("fetch failed"), "Couldn't reach the assistant — try again in a moment."],
  ])("%s", (_name, e, answer) => {
    expect(settledFromError(3, e)).toEqual({ type: "settled", id: 3, answer, error: "transport" });
  });
});
