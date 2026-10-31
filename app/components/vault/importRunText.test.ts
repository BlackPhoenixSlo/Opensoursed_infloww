import { describe, expect, it } from "vitest";

import { ERROR_FRESH_MS, detailsNote, fmtSize, showsError, startLabel, type RunStatus } from "./importRunText";

const MB = 1024 * 1024;

describe("fmtSize", () => {
  it.each([
    ["null", null, ""],
    ["undefined", undefined, ""],
    ["0", 0, ""],
    ["1 byte is never 0 KB", 1, "1 KB"],
    ["1 KB", 1024, "1 KB"],
    ["1.5 KB rounds up", 1536, "2 KB"],
    ["one byte under a MB stays KB", MB - 1, "1024 KB"],
    ["exactly 1 MB", MB, "1.0 MB"],
    ["1.5 MB", 1.5 * MB, "1.5 MB"],
  ] as const)("%s", (_, bytes, want) => {
    expect(fmtSize(bytes)).toBe(want);
  });
});

describe("startLabel", () => {
  const idle = { sending: null, running: false, sessionLost: false, pending: false, modelName: "Ava" };
  it.each([
    ["idle", {}, "Start import → Ava"],
    ["starting", { pending: true }, "Starting…"],
    ["session dropped beats starting", { sessionLost: true, pending: true }, "Session dropped"],
    ["running beats session dropped", { running: true, sessionLost: true }, "Importing…"],
    ["sending beats everything", { sending: { sent: 2, total: 5 }, running: true, sessionLost: true, pending: true },
      "Sending 2 of 5…"],
  ] as const)("%s", (_, over, want) => {
    expect(startLabel({ ...idle, ...over })).toBe(want);
  });
});

describe("showsError", () => {
  const NOW = Date.parse("2026-10-30T12:00:00Z");
  const ago = (ms: number) => new Date(NOW - ms).toISOString();
  const failed: RunStatus = { running: false, status: "failed", error: "boom" };
  it.each([
    ["fresh failure", { finished_at: ago(60 * 60 * 1000) }, true],
    ["just under 24h", { finished_at: ago(ERROR_FRESH_MS - 1) }, true],
    ["exactly 24h is history", { finished_at: ago(ERROR_FRESH_MS) }, false],
    ["older than 24h", { finished_at: ago(ERROR_FRESH_MS + 60_000) }, false],
    ["no finish time", { finished_at: null }, true],
    ["unparseable finish time", { finished_at: "not a date" }, true],
    ["interrupted, fresh", { status: "interrupted", finished_at: ago(1000) }, true],
    ["done with an error string", { status: "done", finished_at: ago(1000) }, false],
    ["no error", { error: null, finished_at: ago(1000) }, false],
  ] as const)("%s", (_, over, want) => {
    expect(showsError({ ...failed, ...over } as RunStatus, NOW)).toBe(want);
  });
});

describe("detailsNote", () => {
  it.each([
    ["no details", {}, null],
    ["details null", { details_saved: null }, null],
    ["none skipped", { details_saved: { applied: 3, skipped: 0, why: "x" } }, null],
    ["one skipped, no reason", { details_saved: { applied: 0, skipped: 1, why: null } },
      "Details for 1 file were not saved."],
    ["two skipped, a reason", { details_saved: { applied: 1, skipped: 2, why: "no mirror" } },
      "Details for 2 files were not saved: no mirror."],
  ] as const)("%s", (_, s, want) => {
    expect(detailsNote(s)).toBe(want);
  });
});
