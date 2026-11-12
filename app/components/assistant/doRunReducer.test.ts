import { describe, expect, it } from "vitest";

import type { DoDraft, MassPremadeSlots } from "./doFlows";
import { pillFor, pillStatus, planCardText } from "./DoMode";
import {
  doOfferOf, doRunReducer, draftFrom, initialDoRun, isTakeover, NO_KEY_HINT, previousOf, type DoAction, type DoRun,
} from "./doRunReducer";

const SLOTS: MassPremadeSlots = {
  name: "N", interval: { value: 1, unit: "hours" }, captions: ["a"], captions_ai: 0, folder: null, online_only: false,
  includes: ["fans", "following"], excludes: [], unsend_after_hours: null, exclude_last_chat_hours: null,
};
const DRAFT: DoDraft = {
  id: "d1", flow: "mass_premade", account_id: "1001", summary: "", slots: SLOTS, assumptions: ["x"], unresolved: [],
  answer: "", error: null,
};
const NULL_FLOW: DoDraft = { ...DRAFT, flow: null, slots: null, answer: "Ask it as a question." };

const EDIT: DoDraft = {
  ...DRAFT, flow: "mass_edit",
  slots: { scope: "all", match: null, changes: { unsend_after_hours: 0 }, rules: [], already: 0, skipped: [] },
};
const STORY: DoDraft = {
  ...DRAFT, flow: "auto_story",
  slots: { folder: { id: 11, name: "Daytime", photos: 8 }, mode: "clock", times: ["09:00"], every_hours: 6, per_run: 1,
    hours_to_live: 6, max_runs: null },
};
const RESULTS = [{ id: 1, ok: true }, { id: 2, ok: false, reason: "changed since you saw it" }];
const play = (actions: DoAction[], from: DoRun = initialDoRun) => actions.reduce(doRunReducer, from);
const planned: DoRun = { phase: "planned", request: "r", draft: DRAFT };
const running: DoRun = { phase: "running", request: "r", draft: DRAFT, step: 0, instant: false, saving: false };
const saving: DoRun = { ...running, saving: true };

describe("doRunReducer", () => {
  it.each<[string, DoRun, DoAction[], DoRun]>([
    ["enter → idle", initialDoRun, [{ type: "enter" }], { phase: "idle" }],
    ["draft while off is ignored", initialDoRun, [{ type: "draft", id: "a", request: "r" }], initialDoRun],
    ["idle → drafting → planned", { phase: "idle" },
      [{ type: "draft", id: "a", request: "r" }, { type: "drafted", id: "a", draft: DRAFT }], planned],
    ["a stale drafted is dropped", { phase: "drafting", id: "b", request: "r2" },
      [{ type: "drafted", id: "a", draft: DRAFT }], { phase: "drafting", id: "b", request: "r2" }],
    ["a reply while planned re-drafts with the plan's slots", planned,
      [{ type: "draft", id: "c", request: "make it 2h" }], { phase: "drafting", id: "c", request: "make it 2h" }],
    ["start runs a plan", planned, [{ type: "start" }], running],
    ["skipAnimation starts instantly", planned, [{ type: "skipAnimation" }], { ...running, instant: true }],
    ["skipAnimation mid-run", running, [{ type: "step", index: 3 }, { type: "skipAnimation" }], { ...running, step: 3, instant: true }],
    ["a flow:null draft never starts", { phase: "planned", request: "r", draft: NULL_FLOW }, [{ type: "start" }],
      { phase: "planned", request: "r", draft: NULL_FLOW }],
    ["a draft with an error never starts", { phase: "planned", request: "r", draft: { ...DRAFT, error: "provider" } }, [{ type: "start" }],
      { phase: "planned", request: "r", draft: { ...DRAFT, error: "provider" } }],
    ["Stop → aborted", running, [{ type: "abort", reason: "Stopped" }], { phase: "aborted", request: "r", draft: DRAFT, reason: "Stopped" }],
    ["saved → done", running, [{ type: "saved" }], { phase: "done", request: "r", draft: DRAFT, ruleSaved: true }],
    ["a run's fail keeps the draft", running, [{ type: "fail", msg: "Add text to enable Create." }],
      { phase: "failed", request: "r", draft: DRAFT, msg: "Add text to enable Create." }],
    ["a drafting fail (its id) → failed with no draft", { phase: "drafting", id: "a", request: "r" },
      [{ type: "fail", id: "a", msg: "down" }], { phase: "failed", request: "r", draft: null, msg: "down" }],
    ["a stale runner's saved/abort after Stop is a no-op",
      { phase: "aborted", request: "r", draft: DRAFT, reason: "Stopped" },
      [{ type: "saved" }, { type: "abort", reason: "again" }, { type: "fail", msg: "late" }, { type: "step", index: 4 }],
      { phase: "aborted", request: "r", draft: DRAFT, reason: "Stopped" }],
    ["Do it again from aborted", { phase: "aborted", request: "r", draft: DRAFT, reason: "Stopped" }, [{ type: "start" }], running],
    ["Cancel → idle", planned, [{ type: "reset" }], { phase: "idle" }],
    ["no new draft while running", running, [{ type: "draft", id: "z", request: "q" }], running],
    ["exit → off", running, [{ type: "exit" }], initialDoRun],
    ["saving marks the run", running, [{ type: "saving" }], saving],
    ["Stop / Esc / takeover while saving is ignored", saving,
      [{ type: "abort", reason: "Stopped" }, { type: "abort", reason: "Stopped with Esc" }], saving],
    ["saved lands after an abort mid-request", running,
      [{ type: "saving" }, { type: "abort", reason: "Stopped" }, { type: "saved" }],
      { phase: "done", request: "r", draft: DRAFT, ruleSaved: true }],
    ["a failed save after an abort mid-request still says so", saving,
      [{ type: "abort", reason: "Stopped" }, { type: "fail", msg: "Network" }],
      { phase: "failed", request: "r", draft: DRAFT, msg: "Network" }],
    ["saving outside a run is a no-op", planned, [{ type: "saving" }], planned],
    ["an edit plan starts straight into saving (no steps, no Stop)", { phase: "planned", request: "r", draft: EDIT },
      [{ type: "start" }, { type: "abort", reason: "Stopped" }],
      { phase: "running", request: "r", draft: EDIT, step: 0, instant: true, saving: true }],
    ["applied → done with the results", { phase: "planned", request: "r", draft: EDIT },
      [{ type: "start" }, { type: "applied", results: RESULTS }],
      { phase: "done", request: "r", draft: EDIT, ruleSaved: true, results: RESULTS }],
    ["a stray saved never ends an edit run; applied never ends a create run", running,
      [{ type: "applied", results: RESULTS }], running],
  ])("%s", (_, from, actions, to) => {
    expect(play(actions, from)).toEqual(to);
  });

  it("previousOf only carries a planned draft's slots", () => {
    expect(previousOf(planned)).toBe(SLOTS);
    expect(previousOf(running)).toBeNull();
    expect(previousOf({ phase: "idle" })).toBeNull();
    expect(previousOf({ phase: "planned", request: "r", draft: EDIT })).toBeNull();   // an edit plan is never refined
  });
});

describe("draftFrom", () => {
  it("fills missing fields; an unknown flow is flow:null with a sentence", () => {
    expect(draftFrom({ flow: "auto_posts" as never, slots: SLOTS }, "1001")).toEqual({
      id: "", flow: null, account_id: "1001", summary: "", slots: null, assumptions: [], unresolved: [],
      answer: expect.stringContaining("Auto Mass"), error: null,
    });
    expect(draftFrom(null, "1")).toMatchObject({ flow: null, slots: null });
  });
  it("keeps a good draft as is", () => {
    expect(draftFrom(DRAFT, "x")).toEqual(DRAFT);
  });
  it("keeps an auto_story draft", () => {
    expect(draftFrom(STORY, "x")).toEqual(STORY);
  });
  it("keeps a mass_edit draft, its slots read defensively", () => {
    expect(draftFrom(EDIT, "x")).toEqual(EDIT);
    expect(draftFrom({ ...EDIT, slots: { rules: "junk" } } as never, "x").slots).toEqual(
      { scope: "this", match: null, changes: {}, rules: [], already: 0, skipped: [] });
  });
});

describe("doOfferOf", () => {
  const on = { show: true, enabled: true, hint: null };
  const off = { show: false, enabled: false, hint: null };
  it.each<[string, Parameters<typeof doOfferOf>[0], boolean, ReturnType<typeof doOfferOf>]>([
    ["no answer, user", null, true, on],
    ["no answer, chatter", undefined, false, off],
    ["can_do false", { can_do: false, reason: null }, true, off],
    ["can_do true, chatter", { can_do: true, reason: null }, false, on],
    ["junk can_do → fallback", { can_do: "yes" }, true, on],
    ["no_key → disabled with the key hint", { can_do: false, reason: "no_key" }, true,
      { show: true, enabled: false, hint: NO_KEY_HINT }],
    ["not_allowed → hidden", { can_do: false, reason: "not_allowed" }, true, off],
  ])("%s", (_, caps, isUser, want) => expect(doOfferOf(caps, isUser)).toEqual(want));
  it("the hint names a settings path AnswerText links", () => expect(NO_KEY_HINT).toContain("Settings → AI keys"));
});

describe("phone pill", () => {
  const done: DoRun = { phase: "done", request: "r", draft: DRAFT, ruleSaved: true };
  const aborted: DoRun = { phase: "aborted", request: "r", draft: DRAFT, reason: "Stopped" };
  const runFailed: DoRun = { phase: "failed", request: "r", draft: DRAFT, msg: "x" };
  const draftFailed: DoRun = { phase: "failed", request: "r", draft: null, msg: "x" };
  it.each<[string, DoRun, DoRun | null, boolean, string]>([
    ["running", running, null, true, "Doing it…"],
    ["saving", saving, null, true, "Saving…"],
    ["done, not opened", done, null, true, "Created OFF"],
    ["done, opened", done, done, false, "Created OFF"],
    ["aborted", aborted, null, true, "Stopped"],
    ["a run's fail", runFailed, null, true, "Couldn't finish"],
    ["a failed draft never ran → the sheet", draftFailed, null, false, "Couldn't finish"],
    ["planned → the sheet", planned, null, false, "Doing it…"],
  ])("%s", (_, run, expanded, pill, status) => {
    expect(pillFor(run, expanded)).toBe(pill);
    expect(pillStatus(run)).toBe(status);
  });
});

describe("isTakeover", () => {
  it.each([
    [{ isTrusted: false, type: "pointerdown" }, false, false],
    [{ isTrusted: true, type: "pointerdown" }, false, true],
    [{ isTrusted: true, type: "pointerdown" }, true, false],
    [{ isTrusted: true, type: "keydown", key: "a" }, true, false],
    [{ isTrusted: true, type: "keydown", key: "Escape" }, true, true],
    [{ isTrusted: false, type: "keydown", key: "Escape" }, false, false],
  ])("%o inside=%s → %s", (e, inside, want) => expect(isTakeover(e, inside)).toBe(want));
});

describe("planCardText", () => {
  it("lines, assumptions, unresolved and the fixed note", () => {
    const t = planCardText({ ...DRAFT, unresolved: ["list “VIP” not found"] })!;
    expect(t.lines.at(-1)).toBe("Saved OFF — you turn it on");
    expect(t.lines).toContain("Audience: online and offline fans");
    expect(t.lines).toContain("No folder");
    expect(t.assumptions).toEqual(["x"]);
    expect(t.unresolved).toEqual(["list “VIP” not found"]);
    expect(t.note).toBe("Photos added to this folder later are included too.");
  });
  it("an auto_story draft's card", () => {
    const t = planCardText(STORY)!;
    expect(t.lines[0]).toBe("Folder: Daytime (8 photos)");
    expect(t.lines.at(-1)).toBe("Saved OFF — you turn it on");
  });
  it("no card for a flow:null draft", () => {
    expect(planCardText(NULL_FLOW)).toBeNull();
  });
});
