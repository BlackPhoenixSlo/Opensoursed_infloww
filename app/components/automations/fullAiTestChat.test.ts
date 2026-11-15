import { describe, expect, it } from "vitest";

import type { ConfigBody, FullAiConfig } from "./fullAiConfig";
import {
  buildSettlePayload, buildTurnPayload, canEdit, canRollback, canSave, canSend, canSettle, initTestChat, keepMineSave,
  MEDIA_ONLY, photoCaption, ppvLine, replyLine, sendBlock, testChatReducer, type FanPhoto, type PpvLine, type Offer,
  type TestChatAction, type TestChatState, type Turn, type TurnResponse, type UiSide, sessionTurns, noReplyText,
  writersFailed, heatTail, type HeatCheck, mediaLine, type OfferItem,
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
  ({ checkpoint: CP, previous: null, draft: CP, rev: 3, errors: [],
    limits: { max_writers: 6, reply_speeds: ["0-2m", "0-15-60"], default_reply_speed: "0-2m" }, ...over });
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
  ])("held, not shown, while %s", (_n, actions) => {
    const s0 = run(ready(), ...actions);
    const s = testChatReducer(s0, external());
    expect(s).toEqual({ ...s0, held: body({ draft: slower, rev: 4 }) });
  });
  it("loaded clears a conflict", () => {
    const s = run(unsaved(), external(), loaded({ draft: slower, rev: 4 }));
    expect([s.conflict, s.draft, s.dirty]).toEqual([null, slower, false]);
  });
});

describe("held: a read that lands while a write is out is offered again once it settles (rwl-c R2-2)", () => {
  const putOut = [edit(), { type: "saveDraft" }] as TestChatAction[];
  const commitOut = [{ type: "commit" }] as TestChatAction[];
  const failed: TestChatAction = { type: "configFailed", errors: ["gifs: bad"] };
  const reloaded = (rev: number): TestChatAction => loaded({ draft: CP, rev });
  // [case, actions after ready(), want [rev, draft, dirty, conflict rev, held]]
  it.each<[string, TestChatAction[], [number, FullAiConfig, boolean, number | null, null]]>([
    ["draft PUT lands older → the read is adopted", [...putOut, external(slower, 5), stored(gifsOn, 4)], [5, slower, false, null, null]],
    ["draft PUT lands newer → the read is dropped", [...putOut, external(slower, 4), stored(gifsOn, 5)], [5, gifsOn, false, null, null]],
    ["draft PUT refused (edit still dirty) → Keep mine / Take theirs", [...putOut, external(slower, 5), failed], [3, gifsOn, true, 5, null]],
    ["Save lands → adopted", [...commitOut, external(slower, 5), { type: "saved", rev: 4 }], [5, slower, false, null, null]],
    ["Roll back lands → adopted", [...commitOut, external(slower, 5), { type: "rolledBack", rev: 4 }], [5, slower, false, null, null]],
    ["Save fails → adopted", [...commitOut, external(slower, 5), failed], [5, slower, false, null, null]],
    ["checkpoint PUT lands (loaded) → adopted", [...commitOut, external(slower, 5), reloaded(4)], [5, slower, false, null, null]],
    ["two reads held → the newest wins", [...putOut, external(gifsOn, 6), external(slower, 5), stored(gifsOn, 4)], [6, gifsOn, false, null, null]],
    ["stale keeps it; Reload at a newer rev drops it", [...putOut, external(slower, 5), { type: "stale" }, reloaded(6)], [6, CP, false, null, null]],
    ["stale keeps it; Reload at an older rev adopts it", [...putOut, external(slower, 5), { type: "stale" }, reloaded(4)], [5, slower, false, null, null]],
  ])("%s", (_n, actions, want) => {
    const s = run(ready(), ...actions);
    expect([s.rev, s.draft, s.dirty, s.conflict?.rev ?? null, s.held]).toEqual(want);
  });
  it("stale keeps the read held until the Reload", () => {
    expect(run(ready(), ...putOut, external(slower, 5), { type: "stale" }).held).toEqual(body({ draft: slower, rev: 5 }));
  });
  it("offered once: a settled state holds nothing, so nothing is offered again", () => {
    const s = run(ready(), ...putOut, external(slower, 5), stored(gifsOn, 4));
    expect(testChatReducer(s, { type: "configFailed", errors: [] }).draft).toEqual(slower);
    expect(run(s, edit(), { type: "saveDraft" }, stored(gifsOn, 6))).toMatchObject({ rev: 6, draft: gifsOn, held: null });
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

describe("mediaLine: the PPV bubble's kinds and length over the locked items", () => {
  const vid = (id: number, seconds: number | null = null): OfferItem => ({ id, kind: "video", seconds });
  const pic = (id: number): OfferItem => ({ id, kind: "photo", seconds: null });
  it.each<[string, Partial<Offer>, string | null]>([
    ["one clip", { media: [1], items: [vid(1, 42)] }, "1 video · 0:42"],
    ["five clips, total length", { media: [1, 2, 3, 4, 5], items: [1, 2, 3, 4, 5].map((i) => vid(i, 150)) }, "5 videos · 12:30"],
    ["past an hour", { media: [1, 2], items: [vid(1, 3000), vid(2, 725)] }, "2 videos · 1:02:05"],
    ["three photos", { media: [1, 2, 3], items: [pic(1), pic(2), pic(3)] }, "3 photos"],
    ["mixed, photos first", { media: [1, 2, 3], items: [vid(3, 42), pic(1), pic(2)] }, "2 photos + 1 video · 0:42"],
    ["a clip with no length", { media: [1], items: [vid(1)] }, "1 video"],
    ["one clip of two with no length", { media: [1, 2], items: [vid(1, 30), vid(2)] }, "2 videos"],
    ["the free preview is not counted", { media: [1, 2], previews: [3], items: [pic(1), pic(2), pic(3)] }, "2 photos"],
    ["items absent (an older row)", { media: [1] }, null],
    ["items empty", { media: [1], items: [] }, null],
    ["no locked item among them", { media: [1], previews: [2], items: [pic(2)] }, null],
  ])("%s", (_n, over, want) => {
    expect(mediaLine({ kind: "offer", ref: 1, price_cents: 1000, list_cents: 1000, media: [], previews: [], refusal: null, ...over }))
      .toBe(want);
  });
});

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

describe("noReplyText: a failed Turn names its real reason", () => {
  const a = (writer: string, outcome: string) => ({ writer, outcome, ms: 100 });
  const failed = (attempts: TurnResponse["attempts"], dropped_reason?: string) =>
    reply({ status: "failed", parts: [], writer: null, attempts, ...(dropped_reason ? { dropped_reason } : {}) });
  it.each<[string, TurnResponse, string, boolean]>([
    ["no Writer answered", failed([a("euryale-v2.3", "no_key"), a("hermes-4-405b", "timeout")]), "no reply: all writers failed", true],
    ["one answered, chain dropped it: the drop, not the earlier no_key",
      failed([a("euryale-v2.3", "no_key"), a("hermes-4-405b", "ok")], "banned"), "no reply: the reply chain dropped it (sensitive word)", false],
    ["empty drop", failed([a("euryale-v2.3", "ok")], "empty"), "no reply: the reply chain dropped it (nothing left to send)", false],
    ["an old row's echo drop", failed([a("euryale-v2.3", "ok")], "echo"), "no reply: the reply chain dropped it (repeated his line)", false],
    ["an unknown reason shows as is", failed([a("euryale-v2.3", "ok")], "new_reason"), "no reply: the reply chain dropped it (new_reason)", false],
    ["no reason on the row", failed([a("euryale-v2.3", "ok")]), "no reply: the reply chain dropped it", false],
  ])("%s", (_n, r, text, writers) => {
    expect(noReplyText(r)).toBe(text);
    expect(writersFailed(r)).toBe(writers);
  });
});

describe("replyLine: the sext scene tail", () => {
  const head = "Route chat · Heat 1 · Row otherwise · Writer euryale-v2.3 · 0 fell before";
  it.each<[string, Partial<TurnResponse>, string]>([
    ["no scene, no price", {}, ""],
    ["scene only", { scene: { n: 3, stage: "building", heat: 3 } }, " · scene building · 3"],
    ["Jev moved the price", { scene: { n: 4, stage: "peak", heat: 4 }, price: { list_cents: 5000, jev_cents: 3500, error: null } },
      " · scene peak · 4 · price Jev $35 (list $50)"],
    ["Jev kept the list price", { price: { list_cents: 5000, jev_cents: 5000, error: null } }, ""],
    ["Jev failed", { price: { list_cents: 1000, jev_cents: null, error: "GateError: deadline" } }, " · price Jev failed (list $10)"],
    ["cents", { price: { list_cents: 1000, jev_cents: 1250, error: null } }, " · price Jev $12.50 (list $10)"],
  ])("%s", (_n, over, tail) => {
    expect(replyLine(reply({ attempts: [{ writer: "euryale-v2.3", outcome: "ok", ms: 100 }], ...over }))).toBe(head + tail);
  });
});

describe("heatTail: the Heat check under a sext reply", () => {
  const h = (o: Partial<HeatCheck>): HeatCheck => ({ cap: 3, score: 3, level: 3, outcome: "ok", ms: 120, version: "v", ...o });
  it.each<[string, HeatCheck | null | undefined, string]>([
    ["absent", undefined, ""],
    ["null", null, ""],
    ["ok", h({}), " · her level 3 of Heat 3"],
    ["rewritten", h({ outcome: "regen_ok", redo_score: 3, first_level: 4 }), " · her level 3 of Heat 3 · rewritten (was 4)"],
    ["over twice", h({ outcome: "over_sent", score: 4, level: 4, redo_score: 4, first_level: 4 }), " · her level 4 of Heat 3 · over Heat, sent"],
    ["failed", h({ outcome: "error", score: null, level: null, error: "GateError: deadline" }), " · Heat check failed"],
  ])("%s", (_n, hc, tail) => {
    expect(heatTail(hc)).toBe(tail);
  });
  it("rides the reply line after the scene tail", () => {
    const r = reply({ attempts: [{ writer: "euryale-v2.3", outcome: "ok", ms: 100 }], route: "sext", heat: 3,
      scene: { n: 2, stage: "building", heat: 3 }, heat_check: h({ outcome: "regen_ok", first_level: 4 }) });
    expect(replyLine(r).endsWith(" · scene building · 2 · her level 3 of Heat 3 · rewritten (was 4)")).toBe(true);
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

  it("controls, Save, Roll back and JSON wait while the photo request is out (rwl-c F2)", () => {
    const s = run(initTestChat("p1"), loaded({ draft: gifsOn, previous: CP }), attach, { type: "send" });
    expect([canEdit(s), canSave(s), canRollback(s)]).toEqual([false, false, false]);
    const done = run(s, described);
    expect([canEdit(done), sendBlock(done)]).toEqual([true, null]);
  });

  it.each<[string, TestChatAction[], string]>([
    ["an edit unstored", [edit()], "Draft not stored — fix it or Reload"],
    ["a draft PUT out", [edit(), { type: "saveDraft" }], "Storing draft…"],
    ["a refused edit", [edit(), { type: "saveDraft" }, { type: "configFailed", errors: ["gifs: bad"] }], "Draft not stored — fix it or Reload"],
    ["a Keep mine / Take theirs pending", [edit(), external()], "Keep mine or Take theirs first"],
  ])("photoDescribed while Send is blocked (%s) starts no Turn: his line and image go back with why (rwl-c R2-1)",
    (_n, mid, why) => {
      const s = run(initTestChat("p1"), loaded(), attach, ...say("rate me"), ...mid, typed("pls"), described);
      expect([s.describing, s.sides.L.pending, s.sides.R.pending, s.text, s.photo, s.photoError])
        .toEqual([null, null, null, "rate me pls", IMG, `Not sent: ${why}`]);
    });

  it("Keep mine waits while the photo request is out (rwl-c R2-1)", () => {
    const s = run(initTestChat("p1"), loaded(), attach, { type: "send" }, edit(), external());
    expect([s.conflict?.rev, keepMineSave(s)]).toEqual([4, null]);
    expect(keepMineSave(run(s, described))).toEqual({ draft: gifsOn, rev: 4 });
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
