import { describe, expect, it } from "vitest";

import { initialPackStatus, packStatusReducer, type PackStatus, type PackStatusAction } from "./packStatus";

const run = (actions: PackStatusAction[], from: PackStatus = initialPackStatus) => actions.reduce(packStatusReducer, from);
const WARNED: PackStatus = { busy: "", note: "tease → OF list 9: pushed 3 · 2 still on OF", failed: false, stale: 2 };
const FAILED: PackStatus = { busy: "", note: "save failed: x", failed: true, stale: 0 };

describe("packStatusReducer", () => {
  it.each<[string, PackStatusAction[], PackStatus, PackStatus]>([
    ["start shows busy and drops the last note and warning", [{ type: "start", busy: "saving…" }], WARNED,
      { busy: "saving…", note: "", failed: false, stale: 0 }],
    ["start clears a failure", [{ type: "start", busy: "saving…" }], FAILED,
      { busy: "saving…", note: "", failed: false, stale: 0 }],
    ["ok ends busy with the note and its stale count", [{ type: "start", busy: "b" }, { type: "ok", note: "done", stale: 3 }],
      initialPackStatus, { busy: "", note: "done", failed: false, stale: 3 }],
    ["ok without stale is 0", [{ type: "start", busy: "b" }, { type: "ok", note: "saved 2 (0 rejected)" }], initialPackStatus,
      { busy: "", note: "saved 2 (0 rejected)", failed: false, stale: 0 }],
    ["fail ends busy, marks the note failed", [{ type: "start", busy: "saving…" }, { type: "fail", note: "save failed: x" }],
      initialPackStatus, FAILED],
    ["publish all fails part way: the landed rungs' stale count stays",
      [{ type: "start", busy: "1/2" }, { type: "start", busy: "2/2" }, { type: "fail", note: "1 of 2 published", stale: 1 }],
      initialPackStatus, { busy: "", note: "1 of 2 published", failed: true, stale: 1 }],
  ])("%s", (_name, actions, from, want) => {
    expect(run(actions, from)).toEqual(want);
  });
});
