import { describe, expect, it } from "vitest";

import {
  badLinesOf, buildPayload, canSubmit, entriesOf, entryNote, INITIAL, isPolling, isRunning, loginQueueReducer,
  lookForQueue, MAX_PASTE, parseStored, POLL_MS, pollEvery, storedOf, type Action, type BadLine, type LoginQueue,
  type QueueEntry, type QueueView,
} from "./loginQueue";
import { STATE_TEXT } from "./remoteLogin";

const entry = (email: string, state: QueueEntry["state"], over: Partial<QueueEntry> = {}): QueueEntry => ({
  email, state, job_id: null, message: "", live_view_url: null, account_id: null, ...over,
});
const view = (id: string, state: QueueView["state"] = "running", entries: QueueEntry[] = []): QueueView =>
  ({ id, state, entries });
const run = (actions: Action[], from: LoginQueue = INITIAL) => actions.reduce(loginQueueReducer, from);
const hydrate = (queueId: string | null, seen: QueueEntry[] = []): Action => ({ type: "hydrate", stored: { queueId, seen } });
const hydrated = hydrate(null);
const edit = (text: string): Action => ({ type: "edit", text });
const started = (id: string): Action => ({ type: "started", view: view(id), badLines: [{ line: 2, reason: "x" }] });
const failed = (message: string, current: QueueView | null = null, badLines: BadLine[] = []): Action =>
  ({ type: "startFailed", message, badLines, current });

describe("Start: canSubmit / buildPayload", () => {
  it.each<[string, Action[], { text: string } | null]>([
    ["before hydrate: never (would race the stored queue)", [edit("a@x.com:pw")], null],
    ["empty", [hydrated], null],
    ["no login line", [hydrated, edit("hello\nworld")], null],
    ["a login line", [hydrated, edit("a@x.com:pw")], { text: "a@x.com:pw" }],
    ["in flight", [hydrated, edit("a@x.com:pw"), { type: "start" }], null],
    ["a queue running", [hydrate("q1"), edit("a@x.com:pw")], null],
    ["refused: may retry, paste kept",
      [hydrated, edit("a@x.com:pw"), { type: "start" }, failed("busy")],
      { text: "a@x.com:pw" }],
    ["the queue ended: a new paste goes",
      [hydrated, edit("a@x.com:pw"), { type: "start" }, started("q1"), { type: "polled", view: view("q1", "done") },
        edit("b@x.com:pw")], { text: "b@x.com:pw" }],
    ["interrupted: a new paste goes",
      [hydrate("q1"), { type: "lost", queueId: "q1" }, edit("b@x.com:pw")], { text: "b@x.com:pw" }],
  ])("%s", (_name, actions, body) => {
    const s = run(actions);
    expect([canSubmit(s), buildPayload(s)]).toEqual([body !== null, body]);
  });

  it("start is a no-op when it can't submit", () => {
    const s = run([hydrated]);
    expect(loginQueueReducer(s, { type: "start" })).toBe(s);
  });

  it("the paste clamps to the relay's limit", () => {
    expect(run([hydrated, edit("x".repeat(MAX_PASTE + 9))]).text).toHaveLength(MAX_PASTE);
  });
});

describe("queue lifecycle", () => {
  it("hydrate runs once", () => {
    expect(run([hydrate("q1"), hydrate("q2")]).queueId).toBe("q1");
  });

  it("started clears the paste (it holds passwords), opens the queue, keeps the bad lines", () => {
    const s = run([hydrated, edit("a@x.com:pw\njunk"), { type: "start" }, started("q1")]);
    expect([s.text, s.queueId, s.starting, s.badLines, isRunning(s)]).toEqual(["", "q1", false, [{ line: 2, reason: "x" }], true]);
  });

  it("startFailed shows the relay's words and bad lines, paste kept", () => {
    const s = run([hydrated, edit("junk"), { type: "start" }, failed("no line", null, [{ line: 1, reason: "r" }])]);
    expect([s.error, s.badLines, s.text, s.queueId]).toEqual(["no line", [{ line: 1, reason: "r" }], "junk", null]);
  });

  it.each<[string, Action[], boolean, string | null]>([
    ["a poll of the open queue lands", [started("q1"), { type: "polled", view: view("q1", "done") }], false, "done"],
    ["a late poll of another queue is dropped", [started("q1"), { type: "polled", view: view("q0", "done") }], true, "running"],
    ["cancelled ends it", [started("q1"), { type: "polled", view: view("q1", "cancelled") }], false, "cancelled"],
    ["a 404 marks it interrupted", [started("q1"), { type: "lost", queueId: "q1" }], false, "running"],
    ["a 404 for an old id is dropped", [started("q1"), { type: "lost", queueId: "q0" }], true, "running"],
    ["no poll after interrupted", [started("q1"), { type: "lost", queueId: "q1" }, { type: "polled", view: view("q1", "done") }],
      false, "running"],
  ])("%s", (_name, actions, running, state) => {
    const s = run([hydrated, edit("a@x.com:pw"), { type: "start" }, ...actions]);
    expect([isRunning(s), s.view?.state ?? null]).toEqual([running, state]);
  });

  it("hydrate with no id drops stray seen entries", () => {
    expect(run([hydrate(null, [entry("a", "done")])]).seen).toEqual([]);
  });

  it.each<[string, Action[], string | null, boolean]>([
    ["a link to another queue switches the view", [hydrate("q1"), { type: "link", queueId: "q2" }], "q2", true],
    ["a link to the shown queue is a no-op", [hydrate("q1"), { type: "link", queueId: "q1" }], "q1", true],
    ["a link before hydrate waits for it", [{ type: "link", queueId: "q2" }], null, false],
    ["a link opens over an interrupted one",
      [hydrate("q1"), { type: "lost", queueId: "q1" }, { type: "link", queueId: "q2" }], "q2", true],
  ])("%s", (_name, actions, queueId, running) => {
    const s = run(actions);
    expect([s.queueId, isRunning(s)]).toEqual([queueId, running]);
  });

  it.each<[string, Action[], string | null]>([
    ["none open: the running queue is adopted", [hydrated, { type: "adopt", view: view("q9") }], "q9"],
    ["an ended queue is not adopted", [hydrated, { type: "adopt", view: view("q9", "done") }], null],
    ["one running here is kept", [hydrate("q1"), { type: "adopt", view: view("q9") }], "q1"],
    ["a 409 behind Start adopts it, start no longer in flight",
      [hydrated, edit("a@x.com:pw"), { type: "start" }, { type: "adopt", view: view("q9") }], "q9"],
    ["an interrupted one gives way",
      [hydrate("q1"), { type: "lost", queueId: "q1" }, { type: "adopt", view: view("q9") }], "q9"],
  ])("%s", (_name, actions, queueId) => {
    const s = run(actions);
    expect([s.queueId, s.starting]).toEqual([queueId, false]);
  });

  it.each<[string, QueueView | null, string | null, string | null]>([
    ["answer lost, the queue found running: opened, no error", view("q9"), "q9", null],
    ["answer lost, none found: the error", null, null, "relay 502"],
    ["answer lost, only an ended one found: the error", view("q9", "done"), null, "relay 502"],
  ])("startFailed: %s", (_name, current, queueId, error) => {
    const s = run([hydrated, edit("a@x.com:pw"), { type: "start" }, failed("relay 502", current)]);
    expect([s.queueId, s.error, s.starting]).toEqual([queueId, error, false]);
  });

  it("the seen entries follow polls and stay listed after a 404", () => {
    const rows = [entry("a@x.com", "done"), entry("b@x.com", "otp")];
    const s = run([hydrated, edit("a@x.com:pw"), { type: "start" }, started("q1"),
      { type: "polled", view: view("q1", "running", rows) }, { type: "lost", queueId: "q1" }]);
    expect([s.seen, entriesOf({ ...s, view: null }), s.interrupted]).toEqual([rows, rows, true]);
  });

  it("entriesOf lists the stored rows until a poll lands", () => {
    const rows = [entry("a@x.com", "waiting")];
    const s = run([hydrate("q1", rows)]);
    expect(entriesOf(s)).toEqual(rows);
    expect(entriesOf(loginQueueReducer(s, { type: "polled", view: view("q1", "done", []) }))).toEqual([]);
  });

  it("reset drops the queue and its errors", () => {
    const s = run([hydrated, edit("a@x.com:pw"), { type: "start" }, started("q1"), { type: "lost", queueId: "q1" }, { type: "reset" }]);
    expect([s.queueId, s.view, s.interrupted, s.badLines, s.seen]).toEqual([null, null, false, [], []]);
  });
});

describe("pollEvery / isPolling", () => {
  const winding = view("q1", "cancelled", [entry("a", "typing"), entry("b", "cancelled")]);
  it.each<[QueueView | undefined, boolean, number | false]>([
    [undefined, false, POLL_MS],
    [view("q1"), false, POLL_MS],
    [view("q1", "done"), false, false],
    [view("q1", "cancelled"), false, false],
    [winding, false, POLL_MS],
    [view("q1", "cancelled", [entry("a", "cancelled"), entry("b", "cancelled")]), false, false],
    [view("q1", "done", [entry("a", "done"), entry("b", "error")]), false, false],
    [undefined, true, false],
    [view("q1"), true, false],
    [winding, true, false],
  ])("%j lost=%s", (data, lost, want) => expect(pollEvery(data, lost)).toBe(want));

  it.each<[string, Action[], boolean]>([
    ["nothing open", [hydrated], false],
    ["opened from storage, not read yet", [hydrate("q1")], true],
    ["Stop queue while a login winds down: still polled", [hydrated, started("q1"), { type: "polled", view: winding }], true],
    ["stopped and every entry ended", [hydrated, started("q1"), { type: "polled", view: view("q1", "cancelled") }], false],
    ["gone (404)", [hydrated, started("q1"), { type: "polled", view: winding }, { type: "lost", queueId: "q1" }], false],
  ])("%s", (_name, actions, want) => expect(isPolling(run(actions))).toBe(want));
});

describe("lookForQueue", () => {
  it.each<[number | null, boolean]>([
    [null, true], [409, true], [500, true], [502, true], [504, true],
    [400, false], [401, false], [403, false], [413, false],
  ])("%j → %s", (status, want) => expect(lookForQueue(status)).toBe(want));
});

describe("storedOf / parseStored", () => {
  it("round-trips the id and each entry's email + state only", () => {
    const s = run([hydrated, edit("a@x.com:pw"), { type: "start" }, started("q1"),
      { type: "polled", view: view("q1", "running", [entry("a@x.com", "done", { account_id: "42", message: "m" })]) }]);
    const raw = storedOf(s)!;
    expect(JSON.parse(raw)).toEqual({ id: "q1", entries: [{ email: "a@x.com", state: "done" }] });
    expect(raw).not.toContain("pw");
    expect(parseStored(raw)).toEqual({ queueId: "q1", seen: [entry("a@x.com", "done")] });
  });

  it("nothing open stores nothing", () => expect(storedOf(run([hydrated]))).toBeNull());

  it.each<[string | null, string | null, number]>([
    [null, null, 0],
    ["", null, 0],
    ["not json", null, 0],
    ["{}", null, 0],
    ['{"id":5}', null, 0],
    ['{"id":"q1","entries":[{"email":"a","state":"done"},{"nope":1},null]}', "q1", 1],
    ['{"id":"q1","entries":"x"}', "q1", 0],
  ])("%j", (raw, queueId, n) => {
    const got = parseStored(raw);
    expect([got.queueId, got.seen.length]).toEqual([queueId, n]);
  });
});

describe("entryNote", () => {
  it.each<[QueueEntry, boolean, string]>([
    [entry("a", "waiting"), false, "Waiting for its turn"],
    [entry("a", "starting"), false, STATE_TEXT.starting],
    [entry("a", "otp"), false, STATE_TEXT.otp],
    [entry("a", "bogus" as QueueEntry["state"], { message: "raw" }), false, "raw"],
    [entry("a", "done", { account_id: "42" }), false, "Logged in (account 42)"],
    [entry("a", "error", { message: "wrong password" }), false, "Not logged in: wrong password"],
    [entry("a", "cancelled"), false, "Cancelled"],
    [entry("a", "otp"), true, "Not finished. Paste it again."],
    [entry("a", "done"), true, "Logged in"],
  ])("%j interrupted=%s", (e, interrupted, want) => expect(entryNote(e, interrupted)).toBe(want));
});

describe("badLinesOf", () => {
  it.each<[unknown, unknown[]]>([
    [{ detail: { message: "m", bad_lines: [{ line: 1, reason: "r" }] } }, [{ line: 1, reason: "r" }]],
    [{ detail: "a queue is already running" }, []],
    [null, []],
    [{ detail: { bad_lines: [{ nope: 1 }] } }, []],
  ])("%j", (body, want) => expect(badLinesOf(body)).toEqual(want));
});
