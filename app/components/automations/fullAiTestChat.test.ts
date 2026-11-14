import { describe, expect, it } from "vitest";

import {
  buildTurnPayload, canEdit, canRollback, canSave, canSend, configLine, initTestChat, keepMineSave, sendBlock, testChatReducer,
  type ConfigBody, type FullAiConfig, type TestChatAction, type TestChatState, type TurnResponse, type UiSide, sessionTurns,
} from "./fullAiTestChat";

const reply = (over: Partial<TurnResponse> = {}): TurnResponse => ({
  row_id: 1, route: "chat", heat: 1, route_row: "otherwise", dropped: [], parts: [{ text: "hey you" }],
  writer: "euryale-v2.3", attempts: [{ writer: "euryale-v2.3", outcome: "ok", ms: 900 }], wait_s: 30,
  status: "sent", fan_info: {}, ...over,
});

const run = (s: TestChatState, ...actions: TestChatAction[]) => actions.reduce(testChatReducer, s);
/** He types `text` and presses Send. */
const say = (text: string): TestChatAction[] => [{ type: "edit", text }, { type: "send" }];
const typed = (text: string): TestChatAction => ({ type: "edit", text });
const sent = (text = "hey") => run(initTestChat("p1"), ...say(text));
const result = (side: UiSide, n: number, over: Partial<TurnResponse> = {}, pair = "p1", now = 1_000): TestChatAction =>
  ({ type: "turnResult", pair, side, n, result: reply(over), now });

describe("send", () => {
  it("sets both sides pending with his trimmed text and Turn 1, and clears the composer", () => {
    const s = sent("  hey ");
    expect(s.sides.L.pending).toEqual({ n: 1, text: "hey", inFlight: true, error: null });
    expect(s.sides.R.pending).toEqual({ n: 1, text: "hey", inFlight: true, error: null });
    expect(s.text).toBe("");
  });
  it.each<[string, string]>([["empty", ""], ["blank", "   "]])("ignores %s text", (_n, text) => {
    const s0 = run(initTestChat("p1"), typed(text));
    expect(testChatReducer(s0, { type: "send" })).toBe(s0);
  });
  it("is ignored while canSend is false; his next line stays in the composer", () => {
    const s = run(sent("one"), typed("two"));
    expect(testChatReducer(s, { type: "send" })).toBe(s);
    expect(s.text).toBe("two");
  });
});

describe("canSend: a Fan line typed, and neither side in flight or unrevealed", () => {
  it.each<[string, TestChatAction[], boolean]>([
    ["fresh chat, nothing typed", [], false],
    ["fresh chat, blank typed", [typed("   ")], false],
    ["fresh chat, a line typed", [typed("hey")], true],
    ["both in flight", [...say("hey")], false],
    ["L answered and revealed, R in flight",
      [...say("hey"), { type: "toggleSkip" }, result("L", 1)], false],
    ["both answered, waiting to reveal", [...say("hey"), result("L", 1), result("R", 1)], false],
    ["both answered, L revealed, R waiting",
      [...say("hey"), result("L", 1), result("R", 1), { type: "reveal", side: "L", now: 31_000 }], false],
    ["both answered and revealed",
      [...say("hey"), result("L", 1), result("R", 1),
        { type: "reveal", side: "L", now: 31_000 }, { type: "reveal", side: "R", now: 31_000 }, typed("more")], true],
    ["both answered and revealed, nothing typed",
      [...say("hey"), result("L", 1), result("R", 1),
        { type: "reveal", side: "L", now: 31_000 }, { type: "reveal", side: "R", now: 31_000 }], false],
    ["R failed (a retry is owed)",
      [...say("hey"), { type: "toggleSkip" }, result("L", 1),
        { type: "turnFailed", pair: "p1", side: "R", n: 1, error: "relay 503" }], false],
  ])("%s → %s", (_name, actions, want) => {
    expect(canSend(run(initTestChat("p1"), ...actions))).toBe(want);
  });
});

describe("turnResult", () => {
  it("with skip-wait reveals at once", () => {
    const s = run(initTestChat("p1"), { type: "toggleSkip" }, ...say("hey"), result("L", 1));
    expect(s.sides.L).toEqual({ turns: [{ n: 1, text: "hey", result: reply() }], pending: null, revealAt: null });
  });
  it("without skip-wait sets revealAt = now + wait_s", () => {
    const s = run(sent("hey"), result("L", 1, { wait_s: 42 }, "p1", 5_000));
    expect(s.sides.L.revealAt).toBe(47_000);
    expect(s.sides.L.turns).toEqual([{ n: 1, text: "hey", result: reply({ wait_s: 42 }) }]);
    expect(s.sides.R.pending?.inFlight).toBe(true);
  });
  it("reveal before revealAt keeps it hidden; at revealAt shows it", () => {
    const s = run(sent(), result("L", 1, { wait_s: 10 }, "p1", 0));
    expect(testChatReducer(s, { type: "reveal", side: "L", now: 9_999 }).sides.L.revealAt).toBe(10_000);
    expect(testChatReducer(s, { type: "reveal", side: "L", now: 10_000 }).sides.L.revealAt).toBeNull();
  });
  it("turning skip-wait on reveals what is waiting", () => {
    const s = run(sent(), result("L", 1), result("R", 1), { type: "toggleSkip" });
    expect([s.skipWait, s.sides.L.revealAt, s.sides.R.revealAt]).toEqual([true, null, null]);
  });
  it.each<[string, TestChatAction]>([
    ["an old pair", result("L", 1, {}, "old-pair")],
    ["a Turn number the side is not waiting on", result("L", 2)],
  ])("for %s is ignored", (_name, action) => {
    const s = sent();
    expect(testChatReducer(s, action)).toBe(s);
  });
  it("turnFailed for an old pair is ignored", () => {
    const s = sent();
    expect(testChatReducer(s, { type: "turnFailed", pair: "old-pair", side: "L", n: 1, error: "x" })).toBe(s);
  });
});

describe("newChat", () => {
  it("clears both sides and changes pair; a late answer for the old pair is ignored", () => {
    const s = run(sent(), { type: "toggleSkip" }, result("L", 1), typed("half a line"), { type: "newChat", pair: "p2" });
    expect(s.pair).toBe("p2");
    expect(s.sides).toEqual(initTestChat("p2").sides);
    expect(s.skipWait).toBe(true);
    expect(s.text).toBe("");
    expect(testChatReducer(s, result("R", 1, {}, "p1"))).toBe(s);
  });
});

describe("buildTurnPayload", () => {
  it("gives side checkpoint for L and draft for R, with his text and the pair", () => {
    const s = sent("hey");
    expect(buildTurnPayload(s, "L")).toEqual({ pair: "p1", side: "checkpoint", n: 1, text: "hey" });
    expect(buildTurnPayload(s, "R")).toEqual({ pair: "p1", side: "draft", n: 1, text: "hey" });
  });
  it("is null with nothing to send", () => {
    expect(buildTurnPayload(initTestChat("p1"), "L")).toBeNull();
  });
  it("n = that side's Turn count + 1", () => {
    const s = run(initTestChat("p1"), { type: "toggleSkip" },
      ...say("one"), result("L", 1), result("R", 1),
      ...say("two"), result("L", 2), result("R", 2),
      ...say("three"));
    expect(buildTurnPayload(s, "L")?.n).toBe(3);
    expect(buildTurnPayload(s, "R")?.n).toBe(3);
  });
  it("keeps the same n on a retry", () => {
    const failed = run(sent("hey"), { type: "turnFailed", pair: "p1", side: "R", n: 1, error: "relay 503" });
    expect(failed.sides.R.pending).toEqual({ n: 1, text: "hey", inFlight: false, error: "relay 503" });
    const retried = testChatReducer(failed, { type: "retry", side: "R" });
    expect(retried.sides.R.pending).toEqual({ n: 1, text: "hey", inFlight: true, error: null });
    expect(buildTurnPayload(retried, "R")).toEqual({ pair: "p1", side: "draft", n: 1, text: "hey" });
  });
});

describe("sessionLoaded (a 409 reloads that session)", () => {
  it("replaces that side's thread, clears its request and shows it at once; the other side is untouched", () => {
    const s = sent("hey");
    const turns = [{ n: 1, text: "hey", result: reply() }];
    const next = testChatReducer(s, { type: "sessionLoaded", pair: "p1", side: "R", turns });
    expect(next.sides.R).toEqual({ turns, pending: null, revealAt: null });
    expect(next.sides.L).toBe(s.sides.L);
  });
  it("for an old pair is ignored", () => {
    const s = sent();
    expect(testChatReducer(s, { type: "sessionLoaded", pair: "old", side: "R", turns: [] })).toBe(s);
  });
});

describe("sessionTurns (the session read's rows, one side)", () => {
  const row = (side: "checkpoint" | "draft", n: number, wait_s: number | null) => ({
    row_id: n, side, n, text: `line ${n}`, parts: [{ text: `reply ${n}` }], route: "chat" as const, heat: 1,
    route_row: "otherwise", writer: "euryale-v2.3", attempts: [], wait_s, status: "sent" as const, fan_info: {},
    created_at: "2026-11-14T03:00:00Z",
  });
  it("keeps the side's rows in order, with no rows dropped and a null wait read as 0", () => {
    const body = { rows: [row("checkpoint", 1, 4.5), row("draft", 1, null), row("checkpoint", 2, 9)] };
    expect(sessionTurns(body, "checkpoint").map((t) => [t.n, t.text, t.result.wait_s, t.result.dropped]))
      .toEqual([[1, "line 1", 4.5, []], [2, "line 2", 9, []]]);
    expect(sessionTurns(body, "draft").map((t) => [t.n, t.result.wait_s])).toEqual([[1, 0]]);
    expect(sessionTurns({ rows: [] }, "draft")).toEqual([]);
  });
});


// ── Config: checkpoint / previous / draft, rev (ticket 39) ──────────────────────────────────────────────────────────
const CP = { version: 1, reply_speed: "0-2m", text_style: "girl", gifs: false, writers: ["euryale-v2.3"] };
const body = (over: Partial<ConfigBody> = {}): ConfigBody =>
  ({ checkpoint: CP, previous: null, draft: CP, rev: 3, errors: [], ...over });
const loaded = (over: Partial<ConfigBody> = {}): TestChatAction => ({ type: "loaded", body: body(over) });
const gifsOn = { ...CP, gifs: true };
const edit = (draft = gifsOn): TestChatAction => ({ type: "editDraft", draft });
const stored = (draft: FullAiConfig = gifsOn, rev = 4): TestChatAction => ({ type: "draftSaved", rev, draft });
/** A revealed, answered chat with a line typed: only the config can block Send. */
const ready = () => run(initTestChat("p1"), loaded(), typed("hey"));

describe("config: draft edits gate Send", () => {
  it("editDraft sets dirty; canSend is false until draftSaved", () => {
    const s = run(ready(), edit());
    expect([s.dirty, s.draft, canSend(s), sendBlock(s)]).toEqual([true, gifsOn, false, "Save draft first"]);
    const saved = run(s, { type: "saveDraft" }, stored());
    expect([saved.dirty, saved.savingDraft, saved.rev, canSend(saved), sendBlock(saved)]).toEqual([false, false, 4, true, null]);
  });
  it("canSend is false while savingDraft", () => {
    const s = run(ready(), edit(), { type: "saveDraft" });
    expect([s.savingDraft, canSend(s), sendBlock(s)]).toEqual([true, false, "Save draft first"]);
  });
  it("configFailed keeps dirty and sets errors", () => {
    const s = run(ready(), edit(), { type: "saveDraft" }, { type: "configFailed", errors: ["gifs: must be true or false"] });
    expect([s.dirty, s.savingDraft, s.errors, canSend(s)]).toEqual([true, false, ["gifs: must be true or false"], false]);
  });
  it("draftSaved takes the stored draft and its rev", () => {
    const s = run(ready(), edit(), { type: "saveDraft" }, stored({ ...gifsOn, floor_on: true }, 9));
    expect([s.draft, s.rev]).toEqual([{ ...gifsOn, floor_on: true }, 9]);
  });
  it("a new edit clears the old errors", () => {
    const s = run(ready(), edit(), { type: "configFailed", errors: ["x: bad"] }, edit({ ...CP, text_style: "formal" }));
    expect(s.errors).toEqual([]);
  });
});

describe("canSave: the stored draft differs from the checkpoint and nothing is out", () => {
  it.each<[string, TestChatAction[], boolean]>([
    ["not loaded", [], false],
    ["loaded, draft = checkpoint", [loaded()], false],
    ["loaded, stored draft differs", [loaded({ draft: gifsOn })], true],
    ["same keys in another order are equal", [loaded({ draft: { gifs: false, text_style: "girl", writers: ["euryale-v2.3"], reply_speed: "0-2m", version: 1 } })], false],
    ["dirty", [loaded(), edit()], false],
    ["saving the draft", [loaded(), edit(), { type: "saveDraft" }], false],
    ["stored", [loaded(), edit(), { type: "saveDraft" }, stored()], true],
    ["with errors", [loaded({ draft: gifsOn, errors: ["gifs: bad"] })], false],
    ["after configFailed", [loaded({ draft: gifsOn }), { type: "configFailed", errors: ["x: bad"] }], false],
    ["a save or roll back out", [loaded({ draft: gifsOn }), { type: "commit" }], false],
    ["stale", [loaded({ draft: gifsOn }), { type: "stale" }], false],
  ])("%s → %s", (_name, actions, want) => {
    expect(canSave(run(initTestChat("p1"), ...actions))).toBe(want);
  });
});

describe("canRollback", () => {
  it.each<[string, TestChatAction[], boolean]>([
    ["not loaded", [], false],
    ["previous null", [loaded()], false],
    ["loaded with a previous", [loaded({ previous: { ...CP, gifs: true } })], true],
    ["a save or roll back out", [loaded({ previous: gifsOn }), { type: "commit" }], false],
    ["saving the draft", [loaded({ previous: gifsOn }), edit(), { type: "saveDraft" }], false],
    ["stale", [loaded({ previous: gifsOn }), { type: "stale" }], false],
  ])("%s → %s", (_name, actions, want) => {
    expect(canRollback(run(initTestChat("p1"), ...actions))).toBe(want);
  });
});

describe("saved / rolledBack", () => {
  it("saved moves checkpoint to previous and draft to checkpoint", () => {
    const s = run(initTestChat("p1"), loaded({ draft: gifsOn }), { type: "commit" }, { type: "saved", rev: 4 });
    expect([s.checkpoint, s.previous, s.draft, s.rev, s.committing]).toEqual([gifsOn, CP, gifsOn, 4, false]);
    expect([canSave(s), canRollback(s)]).toEqual([false, true]);
  });
  it("rolledBack swaps checkpoint and previous; twice is identity", () => {
    const s0 = run(initTestChat("p1"), loaded({ previous: gifsOn, draft: { ...CP, text_style: "formal" } }));
    const once = run(s0, { type: "commit" }, { type: "rolledBack", rev: 4 });
    expect([once.checkpoint, once.previous, once.draft]).toEqual([gifsOn, CP, { ...CP, text_style: "formal" }]);
    const twice = run(once, { type: "commit" }, { type: "rolledBack", rev: 3 });
    expect(twice).toEqual(s0);
  });
  it.each(["saved", "rolledBack"] as const)("%s after a failed write clears its error, so Save is not stuck", (type) => {
    const failed = run(initTestChat("p1"), loaded({ previous: gifsOn, draft: gifsOn }), { type: "commit" },
      { type: "configFailed", errors: ["network"] });
    expect(failed.errors).toEqual(["network"]);
    expect(run(failed, { type: "commit" }, { type, rev: 4 }).errors).toEqual([]);
  });
  it("commit blocks Send until it lands", () => {
    const s = run(ready(), { type: "commit" });
    expect(canSend(s)).toBe(false);
    expect(canSend(run(s, { type: "saved", rev: 4 }))).toBe(true);
  });
});

describe("stale (someone stored meanwhile)", () => {
  it("blocks save and roll back and clears what was out; loaded clears it", () => {
    const s = run(initTestChat("p1"), loaded({ draft: gifsOn, previous: CP }), { type: "commit" }, { type: "stale" });
    expect([s.stale, s.committing, canSave(s), canRollback(s), canEdit(s)]).toEqual([true, false, false, false, false]);
    const back = run(s, loaded({ draft: gifsOn, previous: CP, rev: 7 }));
    expect([back.stale, back.rev, canSave(back), canEdit(back)]).toEqual([false, 7, true, true]);
  });
  it("on a draft PUT keeps the edit dirty", () => {
    const s = run(ready(), edit(), { type: "saveDraft" }, { type: "stale" });
    expect([s.stale, s.dirty, s.savingDraft, canSend(s)]).toEqual([true, true, false, false]);
  });
});

describe("config across New chat and loading", () => {
  it("newChat keeps the config", () => {
    const s = run(initTestChat("p1"), loaded({ previous: gifsOn }), edit(), { type: "newChat", pair: "p2" });
    expect([s.pair, s.checkpoint, s.previous, s.draft, s.dirty]).toEqual(["p2", CP, gifsOn, gifsOn, true]);
  });
  it("loaded takes the GET body and clears dirty and what was out", () => {
    const s = run(initTestChat("p1"), edit(), { type: "saveDraft" }, loaded({ errors: ["x: bad"] }));
    expect([s.checkpoint, s.draft, s.rev, s.dirty, s.savingDraft, s.errors]).toEqual([CP, CP, 3, false, false, ["x: bad"]]);
  });
  it("canEdit only once loaded and while nothing is out", () => {
    expect(canEdit(initTestChat("p1"))).toBe(false);
    expect(canEdit(run(initTestChat("p1"), loaded()))).toBe(true);
    expect(canEdit(run(initTestChat("p1"), loaded(), edit(), { type: "saveDraft" }))).toBe(false);
    expect(canEdit(run(initTestChat("p1"), loaded(), { type: "commit" }))).toBe(false);
  });
});

// ── An applied draft from elsewhere (assistant Apply; ticket 57, spec 03c › fullAiTestChat.ts) ──────────────────────
const slower = { ...CP, reply_speed: "0-15-60" };
const external = (draft: FullAiConfig = slower, rev = 4, over: Partial<ConfigBody> = {}): TestChatAction =>
  ({ type: "externalDraft", body: body({ draft, rev, ...over }) });
/** A body Saved elsewhere too: its checkpoint and previous moved with the rev. */
const savedElsewhere = { checkpoint: gifsOn, previous: CP };
/** An unsaved edit the server refused: still dirty, nothing out. */
const unsaved = () => run(ready(), edit(), { type: "saveDraft" }, { type: "configFailed", errors: ["gifs: bad"] });

describe("externalDraft: a refetched config with a newer rev", () => {
  it("newer rev, no unsaved edit → adopted (draft, rev); Send and Save follow it", () => {
    const s = run(ready(), external());
    expect([s.draft, s.rev, s.dirty, s.conflict, canSend(s), canSave(s)]).toEqual([slower, 4, false, null, true, true]);
    expect(s.checkpoint).toEqual(CP);
  });
  it("adopted whole: a checkpoint and previous that moved with the rev come too (one rev for the whole config)", () => {
    const s = run(ready(), external(gifsOn, 4, savedElsewhere));
    expect([s.checkpoint, s.previous, s.draft, canSave(s), canRollback(s)]).toEqual([gifsOn, CP, gifsOn, false, true]);
  });
  it.each<[string, number]>([["equal", 3], ["older", 2]])("%s rev → ignored", (_n, rev) => {
    const s0 = ready();
    expect(testChatReducer(s0, external(slower, rev))).toBe(s0);
    const dirty = run(ready(), edit());
    expect(testChatReducer(dirty, external(slower, rev))).toBe(dirty);
  });
  it("newer rev with an unsaved edit → conflict; the page's draft stays; Send and Save off", () => {
    const s = run(unsaved(), external());
    expect([s.draft, s.rev, s.dirty, s.conflict]).toEqual([gifsOn, 3, true, body({ draft: slower, rev: 4 })]);
    expect([canSend(s), canSave(s), canEdit(s), sendBlock(s)]).toEqual([false, false, false, "Keep mine or Take theirs first"]);
  });
  it("a still newer rev during a conflict replaces it; an older one is ignored", () => {
    const s = run(unsaved(), external(), external(gifsOn, 6));
    expect(s.conflict).toEqual(body({ draft: gifsOn, rev: 6 }));
    expect(testChatReducer(s, external(slower, 5))).toBe(s);
  });
  it.each<[string, TestChatAction[]]>([
    ["the page's draft PUT is out", [edit(), { type: "saveDraft" }]],
    ["a Save is out", [{ type: "commit" }]],
    ["stale (Reload owed)", [{ type: "stale" }]],
  ])("ignored while %s (its own answer or the Reload carries the newest)", (_n, actions) => {
    const s0 = run(ready(), ...actions);
    expect(testChatReducer(s0, external())).toBe(s0);
  });
  it("loaded clears a conflict", () => {
    const s = run(unsaved(), external(), loaded({ draft: slower, rev: 4 }));
    expect([s.conflict, s.draft, s.dirty]).toEqual([null, slower, false]);
  });
});

describe("keepMine / takeTheirs", () => {
  it("keepMineSave builds a draft save of the page's draft on the conflict's rev; null without a conflict", () => {
    expect(keepMineSave(run(unsaved(), external()))).toEqual({ draft: gifsOn, rev: 4 });
    expect(keepMineSave(unsaved())).toBeNull();
  });
  it("keepMine clears the conflict, takes its rev, checkpoint and previous, keeps the page's draft; saveDraft + draftSaved land it", () => {
    const k = run(unsaved(), external(slower, 4, savedElsewhere), { type: "keepMine" });
    expect([k.conflict, k.rev, k.draft, k.dirty]).toEqual([null, 4, gifsOn, true]);
    const s = run(k, { type: "saveDraft" });
    expect([s.savingDraft, canSend(s)]).toEqual([true, false]);
    expect([s.checkpoint, s.previous]).toEqual([gifsOn, CP]);
    const done = run(s, stored(gifsOn, 5));
    expect([done.rev, done.dirty, canSend(done)]).toEqual([5, false, true]);
  });
  it("takeTheirs adopts the applied body whole, clears dirty, errors and the conflict", () => {
    const s = run(unsaved(), external(), { type: "takeTheirs" });
    expect([s.draft, s.rev, s.dirty, s.conflict, s.errors, canSend(s), canSave(s)]).toEqual([slower, 4, false, null, [], true, true]);
    const whole = run(unsaved(), external(slower, 4, savedElsewhere), { type: "takeTheirs" });
    expect([whole.checkpoint, whole.previous]).toEqual([gifsOn, CP]);
  });
  it.each<TestChatAction["type"]>(["keepMine", "takeTheirs"])("%s without a conflict is a no-op", (type) => {
    const s0 = unsaved();
    expect(testChatReducer(s0, { type } as TestChatAction)).toBe(s0);
  });
});

describe("configLine (a window header's config)", () => {
  it.each<[string, FullAiConfig, string]>([
    ["checkpoint", CP, "Reply 0-2 min · Human style on · GIFs off"],
    ["slower, formal, GIFs on", { ...CP, reply_speed: "0-15-60", text_style: "formal", gifs: true }, "Reply 0-15-60 · Human style off · GIFs on"],
  ])("%s", (_n, cfg, want) => {
    expect(configLine(cfg)).toBe(want);
  });
});
