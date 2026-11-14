import { describe, expect, it } from "vitest";

import {
  buildSettlePayload, buildTurnPayload, canEdit, canRollback, canSave, canSend, canSettle, configLine, humanStyle,
  humanStylePatch, initTestChat, keepMineSave, layersOff, MEDIA_ONLY, photoCaption, ppvLine, replyLine, sendBlock, styleLayers,
  testChatReducer, toggleWriterPatch, typosPatch, writerPatch, writersLine, type FanPhoto, type HumanStyle, type PpvLine, type StyleLayers,
  type ConfigBody, type FullAiConfig, type Offer, type TestChatAction, type TestChatState, type Turn, type TurnResponse, type UiSide,
  sessionTurns,
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
    expect([s.dirty, s.draft, canSend(s), sendBlock(s)]).toEqual([true, gifsOn, false, "Draft not stored — fix it or Reload"]);
    const saved = run(s, { type: "saveDraft" }, stored());
    expect([saved.dirty, saved.savingDraft, saved.rev, canSend(saved), sendBlock(saved)]).toEqual([false, false, 4, true, null]);
  });
  it("canSend is false while savingDraft", () => {
    const s = run(ready(), edit(), { type: "saveDraft" });
    expect([s.savingDraft, canSend(s), sendBlock(s)]).toEqual([true, false, "Storing draft…"]);
  });
  it("configFailed keeps dirty and sets errors", () => {
    const s = run(ready(), edit(), { type: "saveDraft" }, { type: "configFailed", errors: ["gifs: must be true or false"] });
    expect([s.dirty, s.savingDraft, s.errors, canSend(s)]).toEqual([true, false, ["gifs: must be true or false"], false]);
    expect(sendBlock(s)).toBe("Draft not stored — fix it or Reload");
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
    ["checkpoint", CP, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["slower, formal, GIFs on", { ...CP, reply_speed: "0-15-60", text_style: "formal", gifs: true }, "Reply 0-15-60 · Human style off · GIFs on · Caption chat"],
    ["layers all on", { reply_speed: "0-2m", style: ON }, "Reply 0-2 min · Human style on · GIFs off · Caption chat"],
    ["typos off", { reply_speed: "0-2m", style: { ...ON, typos: false }, gifs: true }, "Reply 0-2 min · Human style mixed · Typos off · GIFs on · Caption chat"],
    ["spacing off, typos on", { style: { ...ON, spacing: false } }, "Reply 0-2 min · Human style mixed · GIFs off · Caption chat"],
    ["all off: no Typos chip", { style: OFF }, "Reply 0-2 min · Human style off · GIFs off · Caption chat"],
    ["separate caption", { ...CP, caption_writer: "caption" }, "Reply 0-2 min · Human style on · GIFs off · Caption caption"],
  ])("%s", (_n, cfg, want) => {
    expect(configLine(cfg)).toBe(want);
  });
});

// ── Style layers, Typos, Writer (the settings column's pure edits) ─────────────────────────────────────────────────
const ON: StyleLayers = { texting: true, nonnative: true, spacing: true, typos: true, painful: true };
const OFF: StyleLayers = { texting: false, nonnative: false, spacing: false, typos: false, painful: false };

describe("styleLayers / humanStyle (the server's read: text_style wins, then style; neither = all on)", () => {
  it.each<[string, FullAiConfig | null, StyleLayers, HumanStyle, string]>([
    ["no config", null, ON, "on", ""],
    ["no style key", { gifs: true }, ON, "on", ""],
    ["all on", { style: ON }, ON, "on", ""],
    ["all off", { style: OFF }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["typos off", { style: { ...ON, typos: false } }, { ...ON, typos: false }, "mixed", "typos"],
    ["two off", { style: { ...ON, spacing: false, typos: false } }, { ...ON, spacing: false, typos: false }, "mixed", "spacing, typos"],
    ["legacy formal", { text_style: "formal" }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["legacy formal wins over style", { text_style: "formal", style: ON }, OFF, "off", "texting style, non-native, spacing, typos, painful texting"],
    ["legacy casual", { ...CP }, ON, "on", ""],
    ["an unknown text_style falls to style", { text_style: "boy", style: { ...ON, typos: false } }, { ...ON, typos: false }, "mixed", "typos"],
    ["a missing layer reads off", { style: { texting: true } }, { ...OFF, texting: true }, "mixed", "non-native, spacing, typos, painful texting"],
  ])("%s", (_n, cfg, layers, hs, off) => {
    expect([styleLayers(cfg), humanStyle(cfg), layersOff(cfg)]).toEqual([layers, hs, off]);
  });
});

describe("humanStylePatch / typosPatch", () => {
  it.each<[string, FullAiConfig | null, Partial<FullAiConfig>, StyleLayers]>([
    ["master on from mixed", { style: { ...ON, typos: false } }, humanStylePatch(true), ON],
    ["master off from on", { style: ON }, humanStylePatch(false), OFF],
    ["typos off keeps the other layers", { style: { ...ON, spacing: false } }, typosPatch({ style: { ...ON, spacing: false } }, false), { ...ON, spacing: false, typos: false }],
    ["typos on from all off", { style: OFF }, typosPatch({ style: OFF }, true), { ...OFF, typos: true }],
    ["typos off on a legacy draft", { ...CP }, typosPatch({ ...CP }, false), { ...ON, typos: false }],
    ["master off on a legacy draft", { ...CP }, humanStylePatch(false), OFF],
  ])("%s", (_n, cfg, patch, want) => {
    const next = { ...cfg, ...patch };
    expect([next.style, styleLayers(next)]).toEqual([want, want]);
    expect(JSON.parse(JSON.stringify(patch))).toEqual({ style: want });
  });
});

describe("toggleWriterPatch (tick adds at the end, untick drops; the last one and a full chain refuse)", () => {
  it.each<[string, string[], string, string[] | null]>([
    ["adds at the end", ["a"], "b", ["a", "b"]],
    ["drops a ticked one", ["a", "b", "c"], "b", ["a", "c"]],
    ["drops the Writer, the next answers first", ["a", "b"], "a", ["b"]],
    ["keeps the last one", ["a"], "a", null],
    ["refuses a fifth", ["a", "b", "c", "d"], "e", null],
    ["drops from a full chain", ["a", "b", "c", "d"], "d", ["a", "b", "c"]],
  ])("%s", (_n, writers, model, want) => {
    expect(toggleWriterPatch({ writers }, model)).toEqual(want === null ? null : { writers: want });
  });
  it("writersLine prints the chain in order", () => {
    expect(writersLine({ writers: ["a", "b"] })).toBe("Writers a → b");
    expect(writersLine({})).toBe("Writers none");
  });
});

describe("writerPatch (picked model first, the rest keep their order)", () => {
  const W = ["euryale-v2.3", "hermes-4-405b", "glm-5.3-flash", "deepseek-v4-flash"];
  it.each<[string, string[] | undefined, string, string[]]>([
    ["a fallback moves to the front", W, "glm-5.3-flash", ["glm-5.3-flash", "euryale-v2.3", "hermes-4-405b", "deepseek-v4-flash"]],
    ["the current Writer: unchanged", W, "euryale-v2.3", W],
    ["a new model on a full list drops the last", W, "deepseek-v4-pro", ["deepseek-v4-pro", "euryale-v2.3", "hermes-4-405b", "glm-5.3-flash"]],
    ["a new model on a short list joins it", ["hermes-4-405b"], "euryale-v2.3", ["euryale-v2.3", "hermes-4-405b"]],
    ["no writers yet", undefined, "euryale-v2.3", ["euryale-v2.3"]],
  ])("%s", (_n, writers, model, want) => {
    expect(writerPatch(writers ? { writers } : {}, model)).toEqual({ writers: want });
  });
});

describe("replyLine (who wrote the PPV caption)", () => {
  const head = "Route sell_now · Heat 2 · Row sell · Writer euryale-v2.3 · 0 fell before";
  const cap = (writer: "caption" | "chat", outcome: string) =>
    ({ writer, model: writer === "caption" ? "hermes-4-405b" : null, outcome, ms: 800, attempts: [] });
  it.each<[string, Partial<TurnResponse>, string]>([
    ["no caption key (default chat)", {}, head],
    ["the caption call wrote it", { caption: cap("caption", "ok") }, `${head} · Caption hermes-4-405b`],
    ["fell back to the chat Writer", { caption: cap("chat", "failed") }, `${head} · Caption chat (failed)`],
  ])("%s", (_n, over, want) => {
    expect(replyLine(reply({ route: "sell_now", heat: 2, route_row: "sell", ...over }))).toBe(want);
  });
});

// ── Settle (ticket 49): Buy / Decline on a priced PPV bubble ───────────────────────────────────────────────────────
const offer = (price_cents: number | null, over: Partial<Offer> = {}): Offer => ({
  kind: "offer", ref: 11, price_cents, list_cents: price_cents, media: [11, 12], previews: [13], refusal: null, ...over,
});
/** Both sides answered Turn 1 with skip-wait: L a reply with `lOffer`, R with `rOffer`. */
const offered = (lOffer: Offer | null = offer(1500), rOffer: Offer | null = offer(2000)) => run(
  initTestChat("p1", true), ...say("send me pics"),
  result("L", 1, { row_id: 7, offer: lOffer }), result("R", 1, { row_id: 8, offer: rOffer }),
);
const settle = (side: UiSide, rowId: number, outcome: "bought" | "declined" = "bought"): TestChatAction =>
  ({ type: "settle", side, rowId, outcome });
const settled = (side: UiSide, rowId: number, outcome: "bought" | "declined" = "bought", pair = "p1"): TestChatAction =>
  ({ type: "settled", pair, side, rowId, outcome });
const failed = (side: UiSide, rowId: number, pair = "p1"): TestChatAction =>
  ({ type: "settleFailed", pair, side, rowId, error: "relay 503" });
const turnOf = (s: TestChatState, side: UiSide) => s.sides[side].turns[0];

describe("settle → settled / settleFailed", () => {
  it("settle marks only that turn in flight; settled shows the outcome and clears it", () => {
    const s = run(offered(), settle("R", 8));
    expect(turnOf(s, "R").settle).toEqual({ kind: "pending", outcome: "bought" });
    expect(turnOf(s, "L")).toEqual(turnOf(offered(), "L"));
    const done = run(s, settled("R", 8));
    expect(turnOf(done, "R").settle).toEqual({ kind: "done", outcome: "bought" });
  });
  it.each<["bought" | "declined"]>([["bought"], ["declined"]])("settled %s lands that outcome", (outcome) => {
    expect(turnOf(run(offered(), settle("L", 7, outcome), settled("L", 7, outcome)), "L").settle).toEqual({ kind: "done", outcome });
  });
  it("settleFailed restores the bubble (Buy / Decline again) and keeps the error", () => {
    const s = run(offered(), settle("L", 7), failed("L", 7));
    expect(turnOf(s, "L").settle).toEqual({ kind: "failed", error: "relay 503" });
    expect(canSettle(turnOf(s, "L"))).toBe(true);
  });
  it("a second settle while one is in flight or after it settled is a no-op", () => {
    const flying = run(offered(), settle("L", 7));
    expect(testChatReducer(flying, settle("L", 7, "declined"))).toBe(flying);
    const done = run(flying, settled("L", 7));
    expect(testChatReducer(done, settle("L", 7, "declined"))).toBe(done);
  });
  it.each<[string, TestChatAction]>([
    ["settled for an old pair", settled("L", 7, "bought", "p0")],
    ["settleFailed for an old pair", failed("L", 7, "p0")],
    ["settle of an unknown row", settle("L", 99)],
    ["settle of a free item", settle("R", 8)],
  ])("%s is ignored", (_n, action) => {
    const s0 = run(offered(offer(1500), offer(0)), settle("L", 7));
    expect(testChatReducer(s0, action)).toBe(s0);
  });
  it("a session reload keeps a settled outcome (its rows carry none)", () => {
    const s = run(offered(), settle("R", 8), settled("R", 8));
    const turns = s.sides.R.turns.map((t) => ({ n: t.n, text: t.text, result: t.result }));
    const next = run(s, { type: "sessionLoaded", pair: "p1", side: "R", turns });
    expect(turnOf(next, "R").settle).toEqual({ kind: "done", outcome: "bought" });
  });
  it("a late settled after New chat is ignored", () => {
    const s = run(offered(), settle("L", 7), { type: "newChat", pair: "p2" }, settled("L", 7));
    expect(s.sides.L.turns).toEqual([]);
  });
});

describe("canSettle: a priced Offer, no outcome, no settle in flight", () => {
  const turn = (o: Offer | null, extra: Partial<Turn> = {}): Turn => ({ n: 1, text: "x", result: reply({ offer: o }), ...extra });
  it.each<[string, Turn, boolean]>([
    ["priced, unsettled", turn(offer(1500)), true],
    ["free item (price 0)", turn(offer(0)), false],
    ["tease (no price)", turn(offer(null)), false],
    ["no Offer", turn(null), false],
    ["no offer key (03a answer)", { n: 1, text: "x", result: reply() }, false],
    ["bought", turn(offer(1500), { settle: { kind: "done", outcome: "bought" } }), false],
    ["declined", turn(offer(1500), { settle: { kind: "done", outcome: "declined" } }), false],
    ["settle in flight", turn(offer(1500), { settle: { kind: "pending", outcome: "bought" } }), false],
    ["failed settle (restored)", turn(offer(1500), { settle: { kind: "failed", error: "relay 503" } }), true],
  ])("%s → %s", (_n, t, want) => expect(canSettle(t)).toBe(want));
});

describe("ppvLine: how a PPV bubble stands", () => {
  const turn = (o: Offer | null, settle?: Turn["settle"]): Turn => ({ n: 1, text: "x", result: reply({ offer: o }), settle });
  it.each<[string, Turn, PpvLine | null]>([
    ["priced, unsettled → the price", turn(offer(1500)), { kind: "price", dollars: 15 }],
    ["settle in flight → still the price", turn(offer(1500), { kind: "pending", outcome: "bought" }), { kind: "price", dollars: 15 }],
    ["failed settle → the price", turn(offer(1500), { kind: "failed", error: "x" }), { kind: "price", dollars: 15 }],
    ["bought → paid", turn(offer(1500), { kind: "done", outcome: "bought" }), { kind: "settled", dollars: 15, paid: true }],
    ["declined → not paid", turn(offer(999), { kind: "done", outcome: "declined" }), { kind: "settled", dollars: 9.99, paid: false }],
    ["free item → Free", turn(offer(0)), { kind: "free" }],
    ["tease (no price) → nothing", turn(offer(null)), null],
    ["no Offer → nothing", turn(null), null],
  ])("%s", (_n, t, want) => expect(ppvLine(t)).toEqual(want));
});

describe("replyLine: how many Writers fell before the one that answered", () => {
  const a = (writer: string, outcome: string, rewrite?: boolean) => ({ writer, outcome, ms: 100, ...(rewrite ? { rewrite } : {}) });
  it.each<[string, TurnResponse["attempts"], string]>([
    ["first Writer answered", [a("euryale-v2.3", "ok")], "0 fell before"],
    ["one fell, with why", [a("euryale-v2.3", "no_key"), a("hermes-4-405b", "ok")], "1 fell before (euryale-v2.3 no_key)"],
    ["Claim audit rewrite by the same Writer: none fell", [a("euryale-v2.3", "ok"), a("euryale-v2.3", "ok", true)], "0 fell before"],
    ["one fell, then a rewrite with its own failure", [a("euryale-v2.3", "http_503"), a("hermes-4-405b", "ok"),
      a("hermes-4-405b", "timeout", true), a("glm-5.3-flash", "ok", true)], "1 fell before (euryale-v2.3 http_503)"],
    ["two fell", [a("euryale-v2.3", "no_key"), a("hermes-4-405b", "no_key"), a("deepseek-v4-flash", "ok")],
      "2 fell before (euryale-v2.3 no_key · hermes-4-405b no_key)"],
  ])("%s → %s", (_n, attempts, fell) => {
    expect(replyLine(reply({ attempts }))).toBe(`Route chat · Heat 1 · Row otherwise · Writer euryale-v2.3 · ${fell}`);
  });
});

describe("buildSettlePayload", () => {
  it.each<[UiSide, number, "bought" | "declined", string]>([
    ["L", 7, "bought", "checkpoint"],
    ["R", 8, "declined", "draft"],
  ])("%s row %s %s → side %s, with account_id", (ui, rowId, outcome, side) => {
    expect(buildSettlePayload(offered(), ui, rowId, outcome, "acct1"))
      .toEqual({ account_id: "acct1", pair: "p1", side, row_id: rowId, outcome });
  });
});

describe("canSend with a settle in flight", () => {
  it("is unchanged: a typed line still sends", () => {
    const s = run(offered(), settle("L", 7), typed("more"));
    expect(canSend(s)).toBe(true);
    expect(canSend(run(offered(), typed("more")))).toBe(true);
    expect(run(s, { type: "send" }).sides.L.pending?.n).toBe(2);
  });
});

describe("his photo (attach → described once → both sides' Turns)", () => {
  const IMG = "data:image/png;base64,AAAA";
  const PHOTO: FanPhoto = { desc: "a guy in a hoodie", thumb: "data:image/jpeg;base64,BBBB", outcome: "described", model: "qwen3-vl-30b", ms: 900 };
  const attach: TestChatAction = { type: "attach", image: IMG };
  const described: TestChatAction = { type: "photoDescribed", pair: "p1", photo: PHOTO };

  it.each<[string, TestChatAction[], boolean]>([
    ["image attached, no text", [attach], true],
    ["image attached, then removed", [attach, { type: "detach" }], false],
    ["photo request out", [attach, { type: "send" }], false],
    ["photo described: both sides in flight", [attach, { type: "send" }, described], false],
    ["photo failed: back in the composer", [attach, { type: "send" }, { type: "photoFailed", pair: "p1", error: "x" }], true],
  ])("canSend: %s → %s", (_n, actions, want) => {
    expect(canSend(run(initTestChat("p1"), ...actions))).toBe(want);
  });

  it("Send owes the photo request first (his line and image), not the Turns; the composer clears", () => {
    const s = run(initTestChat("p1"), attach, ...say(" rate me "));
    expect(s.describing).toEqual({ text: "rate me", image: IMG });
    expect([s.sides.L.pending, s.sides.R.pending, s.text, s.photo]).toEqual([null, null, "", null]);
  });

  it("photoDescribed owes both sides Turn 1 carrying the one description; the payload sends it", () => {
    const s = run(initTestChat("p1"), attach, { type: "send" }, described);
    expect(s.describing).toBeNull();
    expect(s.sides.L.pending).toEqual({ n: 1, text: "", photo: PHOTO, inFlight: true, error: null });
    expect(buildTurnPayload(s, "L")).toEqual({ pair: "p1", side: "checkpoint", n: 1, text: "", photo: PHOTO });
    expect(buildTurnPayload(s, "R")).toEqual({ pair: "p1", side: "draft", n: 1, text: "", photo: PHOTO });
  });

  it("a Turn keeps the photo as its side read it (the answer's photo wins)", () => {
    const read = { ...PHOTO, read: false };
    const s = run(initTestChat("p1"), { type: "toggleSkip" }, attach, { type: "send" }, described,
      result("L", 1, { photo: read }));
    expect(s.sides.L.turns[0].photo).toEqual(read);
  });

  it("photoFailed puts his line and image back with the message; a line typed meanwhile stays after it", () => {
    const s = run(initTestChat("p1"), attach, ...say("rate me"), typed("pls"),
      { type: "photoFailed", pair: "p1", error: "relay 424" });
    expect([s.describing, s.text, s.photo, s.photoError]).toEqual([null, "rate me pls", IMG, "relay 424"]);
    expect(run(s, typed("x")).photoError).toBeNull();
  });

  it.each<[string, TestChatAction]>([
    ["photoDescribed", { type: "photoDescribed", pair: "old", photo: PHOTO }],
    ["photoFailed", { type: "photoFailed", pair: "old", error: "x" }],
  ])("%s for an old pair is ignored", (_n, a) => {
    const s = run(initTestChat("p1"), attach, { type: "send" });
    expect(testChatReducer(s, a)).toBe(s);
  });

  it("attach / detach are ignored while the photo request is out; newChat drops it all", () => {
    const s = run(initTestChat("p1"), attach, { type: "send" });
    expect(testChatReducer(s, { type: "attach", image: "data:image/png;base64,CC" })).toBe(s);
    expect(testChatReducer(s, { type: "detach" })).toBe(s);
    const n = testChatReducer(s, { type: "newChat", pair: "p2" });
    expect([n.describing, n.photo, n.photoError]).toEqual([null, null, null]);
  });

  it("sessionTurns keeps a row's photo on its Turn", () => {
    const row = { ...reply(), side: "checkpoint" as const, n: 1, text: "", wait_s: 3, created_at: "2026-11-14T00:00:00Z",
      photo: { ...PHOTO, read: true } };
    delete (row as Partial<TurnResponse>).dropped;
    expect(sessionTurns({ rows: [row] }, "checkpoint")[0].photo).toEqual({ ...PHOTO, read: true });
  });

  it.each<[string, FanPhoto, string]>([
    ["read", { ...PHOTO, read: true }, "a guy in a hoodie"],
    ["key off", { ...PHOTO, read: false }, MEDIA_ONLY],
    ["no description", { ...PHOTO, desc: null, read: true }, MEDIA_ONLY],
  ])("photoCaption: %s", (_n, p, want) => {
    expect(photoCaption(p)).toBe(want);
  });
});
