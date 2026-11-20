import { describe, expect, it } from "vitest";

import {
  bulkRunReducer, bulkStatusLine, failedNote, INITIAL_BULK_RUN, NOTHING_MATCHES,
  type BulkRun, type BulkRunAction,
} from "./bulkUnsendRun";

const running = (done: number, total: number): BulkRun => ({ running: "all", done, total, note: null });
const idle = (note: string | null = null): BulkRun => ({ ...INITIAL_BULK_RUN, note });

describe("bulkRunReducer", () => {
  it.each<[string, BulkRun, BulkRunAction, BulkRun]>([
    ["clear drops the last note", idle("x"), { type: "clear" }, idle()],
    ["clear mid-run keeps the run", running(3, 9), { type: "clear" }, running(3, 9)],
    ["nothing sets the no-match note", idle("old"), { type: "nothing" }, idle(NOTHING_MATCHES)],
    ["nothing mid-run keeps the run", running(3, 9), { type: "nothing" }, running(3, 9)],
    ["start resets counts and note", idle("old"), { type: "start", action: "non-image", total: 200 },
      { running: "non-image", done: 0, total: 200, note: null }],
    ["progress moves done", running(0, 200), { type: "progress", done: 37 }, running(37, 200)],
    ["progress never goes back", running(5, 9), { type: "progress", done: 4 }, running(5, 9)],
    ["progress clamps to total", running(8, 9), { type: "progress", done: 12 }, running(9, 9)],
    ["progress when idle is dropped", idle("n"), { type: "progress", done: 3 }, idle("n")],
    ["finish clean leaves no note", running(9, 9), { type: "finish", failed: 0 }, idle()],
    ["finish with failures notes them", running(200, 200), { type: "finish", failed: 3 }, idle(failedNote(3, 200))],
    ["finish when idle is dropped", idle("n"), { type: "finish", failed: 2 }, idle("n")],
  ])("%s", (_label, from, action, want) => {
    expect(bulkRunReducer(from, action)).toEqual(want);
  });
});

describe("bulkStatusLine", () => {
  it.each<[string, BulkRun, string | null]>([
    ["running", running(37, 200), "Unsending 37 of 200…"],
    ["just started", running(0, 1), "Unsending 0 of 1…"],
    ["idle", idle(), null],
    ["idle with a note", idle("x"), null],
  ])("%s", (_label, s, want) => {
    expect(bulkStatusLine(s)).toBe(want);
  });
});

describe("failedNote", () => {
  it.each([
    [1, 1, "1 of 1 unsend failed. Those broadcasts may still be live — refresh and retry."],
    [3, 200, "3 of 200 unsends failed. Those broadcasts may still be live — refresh and retry."],
  ])("%i of %i", (failed, total, want) => {
    expect(failedNote(failed, total)).toBe(want);
  });
});
