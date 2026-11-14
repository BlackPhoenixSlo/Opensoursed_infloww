import { describe, expect, it } from "vitest";

import type { ExportSlots } from "./doExport";
import type { DoDraft, MassPremadeSlots } from "./doFlows";
import type { ConfigStatus } from "./fullAiConfigEdit";
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
const EXPORT_SLOTS: ExportSlots = {
  recipe: { dataset: "sales", window: { from: "2026-02-01", to: "2026-02-28" }, creators: ["a2"] }, format: "xlsx",
  window: { from: "2026-02-01", to: "2026-02-28", tz: "Europe/London" },
  labels: { dataset: "Sales", about: "Creator earnings", creators: ["Mia Rose"], all_creators: 2, employees: null, kinds: [],
    order: "Creator, A to Z", limit: null },
  columns: ["Creator", "Day", "Total"], filename: "sales_2026-02-01_2026-02-28.xlsx",
};
const EXPORT: DoDraft = { ...DRAFT, id: "e1", account_id: null, flow: "report_export", slots: EXPORT_SLOTS, assumptions: [] };
const UNRESOLVED_EXPORT: DoDraft = {
  ...EXPORT, slots: { ...EXPORT_SLOTS, recipe: null }, unresolved: ["\"Mi\" could be Mia Rose or Mila — say which Creator."],
};
const exportRunning: DoRun = { phase: "running", id: "a", request: "r", draft: EXPORT, step: 0, instant: true, saving: true, attempt: 0 };
const RESULTS = [{ id: 1, ok: true }, { id: 2, ok: false, reason: "changed since you saw it" }];
const CONFIG_SLOTS = {
  rev: 4, before: { reply_speed: "0-2m" }, after: { reply_speed: "0-15-60" }, account_name: "Model A",
  diffs: [{ field: "reply_speed", label: "Reply speed", before: "0-2m", after: "0-15-60" }],
};
const CONFIG: DoDraft = { ...DRAFT, id: "c1", flow: "full_ai_config", slots: CONFIG_SLOTS, assumptions: [] };
const configPlanned: DoRun = { phase: "planned", id: "a", request: "r", draft: CONFIG };
const configRunning: DoRun = { phase: "running", id: "a", request: "r", draft: CONFIG, step: 0, instant: true, saving: true, attempt: 0 };
const configDone = (status: ConfigStatus, line: string): DoRun => ({
  phase: "done", id: "a", request: "r", draft: CONFIG, outcome: { kind: "config", status, line },
});
const play = (actions: DoAction[], from: DoRun = initialDoRun) => actions.reduce(doRunReducer, from);
const planned: DoRun = { phase: "planned", id: "a", request: "r", draft: DRAFT };
const running: DoRun = { phase: "running", id: "a", request: "r", draft: DRAFT, step: 0, instant: false, saving: false, attempt: 0 };
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
    ["a flow:null draft never starts", { phase: "planned", id: "a", request: "r", draft: NULL_FLOW }, [{ type: "start" }],
      { phase: "planned", id: "a", request: "r", draft: NULL_FLOW }],
    ["a draft with an error never starts", { phase: "planned", id: "a", request: "r", draft: { ...DRAFT, error: "provider" } }, [{ type: "start" }],
      { phase: "planned", id: "a", request: "r", draft: { ...DRAFT, error: "provider" } }],
    ["Stop → aborted", running, [{ type: "abort", reason: "Stopped" }], { phase: "aborted", id: "a", request: "r", draft: DRAFT, reason: "Stopped" }],
    ["saved → done", running, [{ type: "saved" }], { phase: "done", id: "a", request: "r", draft: DRAFT, outcome: { kind: "saved" } }],
    ["a run's fail keeps the draft", running, [{ type: "fail", msg: "Add text to enable Create." }],
      { phase: "failed", id: "a", request: "r", draft: DRAFT, msg: "Add text to enable Create.", attempt: 0 }],
    ["a drafting fail (its id) → failed with no draft", { phase: "drafting", id: "a", request: "r" },
      [{ type: "fail", id: "a", msg: "down" }], { phase: "failed", id: "a", request: "r", draft: null, msg: "down" }],
    ["a stale runner's saved/abort after Stop is a no-op",
      { phase: "aborted", id: "a", request: "r", draft: DRAFT, reason: "Stopped" },
      [{ type: "saved" }, { type: "abort", reason: "again" }, { type: "fail", msg: "late" }, { type: "step", index: 4 }],
      { phase: "aborted", id: "a", request: "r", draft: DRAFT, reason: "Stopped" }],
    ["Do it again from aborted", { phase: "aborted", id: "a", request: "r", draft: DRAFT, reason: "Stopped" }, [{ type: "start" }], running],
    ["Cancel → idle", planned, [{ type: "reset" }], { phase: "idle" }],
    ["no new draft while running", running, [{ type: "draft", id: "z", request: "q" }], running],
    ["exit → off", running, [{ type: "exit" }], initialDoRun],
    ["saving marks the run", running, [{ type: "saving" }], saving],
    ["Stop / Esc / takeover while saving is ignored", saving,
      [{ type: "abort", reason: "Stopped" }, { type: "abort", reason: "Stopped with Esc" }], saving],
    ["saved lands after an abort mid-request", running,
      [{ type: "saving" }, { type: "abort", reason: "Stopped" }, { type: "saved" }],
      { phase: "done", id: "a", request: "r", draft: DRAFT, outcome: { kind: "saved" } }],
    ["a failed save after an abort mid-request still says so", saving,
      [{ type: "abort", reason: "Stopped" }, { type: "fail", msg: "Network" }],
      { phase: "failed", id: "a", request: "r", draft: DRAFT, msg: "Network", attempt: 0 }],
    ["saving outside a run is a no-op", planned, [{ type: "saving" }], planned],
    ["an edit plan starts straight into saving (no steps, no Stop)", { phase: "planned", id: "a", request: "r", draft: EDIT },
      [{ type: "start" }, { type: "abort", reason: "Stopped" }],
      { phase: "running", id: "a", request: "r", draft: EDIT, step: 0, instant: true, saving: true, attempt: 0 }],
    ["applied → done with the results", { phase: "planned", id: "a", request: "r", draft: EDIT },
      [{ type: "start" }, { type: "applied", results: RESULTS }],
      { phase: "done", id: "a", request: "r", draft: EDIT, outcome: { kind: "applied", results: RESULTS } }],
    ["a stray saved never ends an edit run; applied never ends a create run", running,
      [{ type: "applied", results: RESULTS }], running],
    ["Download starts an export straight into saving (no steps, no Stop)", { phase: "planned", id: "a", request: "r", draft: EXPORT },
      [{ type: "start" }, { type: "abort", reason: "Stopped" }], exportRunning],
    ["downloaded → done with the file", exportRunning, [{ type: "downloaded", file: "x.xlsx" }],
      { phase: "done", id: "a", request: "r", draft: EXPORT, outcome: { kind: "downloaded", file: "x.xlsx" } }],
    ["saved / applied never end an export; downloaded never ends a create run", exportRunning,
      [{ type: "saved" }, { type: "applied", results: RESULTS }], exportRunning],
    ["downloaded outside an export run is a no-op", running, [{ type: "downloaded", file: "x.csv" }], running],
    ["an export's fail keeps the attempt", exportRunning, [{ type: "fail", msg: "429" }],
      { phase: "failed", id: "a", request: "r", draft: EXPORT, msg: "429", attempt: 0 }],
    ["Try again is the next attempt of the same draft", exportRunning,
      [{ type: "fail", msg: "429" }, { type: "start" }, { type: "fail", msg: "429" }, { type: "start" }],
      { ...exportRunning, attempt: 2 }],
    ["a new plan starts back at attempt 0", { phase: "failed", id: "a", request: "r", draft: EXPORT, msg: "x", attempt: 3 },
      [{ type: "draft", id: "n", request: "q" }, { type: "drafted", id: "n", draft: EXPORT }, { type: "start" }], { ...exportRunning, id: "n", request: "q" }],
    // F21: a server draft id may be null — two exports of one id keep their own plan ids, so the download key differs
    ["a second export with the same server id runs as its own plan", { phase: "done", id: "a", request: "r", draft: { ...EXPORT, id: "" },
      outcome: { kind: "downloaded", file: "x.xlsx" } },
      [{ type: "draft", id: "b", request: "q" }, { type: "drafted", id: "b", draft: { ...EXPORT, id: "" } }, { type: "start" }],
      { ...exportRunning, id: "b", request: "q", draft: { ...EXPORT, id: "" } }],
    ["an export with an unresolved name never downloads", { phase: "planned", id: "a", request: "r", draft: UNRESOLVED_EXPORT },
      [{ type: "start" }, { type: "skipAnimation" }], { phase: "planned", id: "a", request: "r", draft: UNRESOLVED_EXPORT }],
    ["an export whose recipe is missing never downloads", { phase: "planned", id: "a", request: "r", draft: { ...EXPORT, slots: { ...EXPORT_SLOTS, recipe: null } } },
      [{ type: "start" }], { phase: "planned", id: "a", request: "r", draft: { ...EXPORT, slots: { ...EXPORT_SLOTS, recipe: null } } }],
    // full_ai_config (phase 03c): one PUT, its answer ends the run — 409 / 422 too (never failed, so no re-PUT)
    ["start on a config plan → saving (the one PUT is out)", configPlanned, [{ type: "start" }], configRunning],
    ["Stop never cancels a config apply", configRunning, [{ type: "abort", reason: "Stopped" }], configRunning],
    ["configApplied 200 → done with the line and the Creator", configRunning,
      [{ type: "configApplied", status: 200, line: "Draft updated." }], configDone(200, "Draft updated.")],
    ["configApplied 409 → done, the line says why", configRunning,
      [{ type: "configApplied", status: 409, line: "The draft changed since you saw it. Ask again." }],
      configDone(409, "The draft changed since you saw it. Ask again.")],
    ["configApplied 422 → done, the errors listed", configRunning,
      [{ type: "configApplied", status: 422, line: "Not applied: gifs: bad" }], configDone(422, "Not applied: gifs: bad")],
    ["saved / applied leave a config run unchanged", configRunning,
      [{ type: "saved" }, { type: "applied", results: RESULTS }, { type: "downloaded", file: "x" }], configRunning],
    ["configApplied outside a config run is a no-op", saving, [{ type: "configApplied", status: 200, line: "x" }], saving],
    ["a config draft without slots never starts", { phase: "planned", id: "a", request: "r", draft: { ...CONFIG, slots: null } },
      [{ type: "start" }], { phase: "planned", id: "a", request: "r", draft: { ...CONFIG, slots: null } }],
  ])("%s", (_, from, actions, to) => {
    expect(play(actions, from)).toEqual(to);
  });

  it("previousOf only carries a planned draft's slots", () => {
    expect(previousOf(planned)).toBe(SLOTS);
    expect(previousOf(running)).toBeNull();
    expect(previousOf({ phase: "idle" })).toBeNull();
    expect(previousOf({ phase: "planned", id: "a", request: "r", draft: EDIT })).toBeNull();   // an edit plan is never refined
    expect(previousOf(configPlanned)).toBeNull();                                            // nor a config plan
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
  it("keeps a report_export draft; drafted in General its account is null", () => {
    expect(draftFrom(EXPORT, null)).toEqual(EXPORT);
    expect(draftFrom({ ...EXPORT, account_id: "" }, null).account_id).toBeNull();
    expect(draftFrom({ ...EXPORT, slots: "junk" } as never, null).slots).toBeNull();
  });
  it("an account flow with no model is no draft", () => {
    expect(draftFrom({ ...DRAFT, account_id: null }, null)).toMatchObject({ flow: null, account_id: null, slots: null });
  });
  it("the no-flow fallback names the export", () => {
    expect(draftFrom({ flow: null }, null).answer).toContain("export a report");
  });
  it("keeps a full_ai_config draft with an account, drops it without one", () => {
    expect(draftFrom(CONFIG, "1001")).toEqual(CONFIG);
    expect(draftFrom({ ...CONFIG, account_id: null }, null)).toMatchObject({ flow: null, slots: null, account_id: null });
    expect(draftFrom({ ...CONFIG, slots: { ...CONFIG_SLOTS, rev: undefined } } as never, "1001").slots).toBeNull();
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
  const done: DoRun = { phase: "done", id: "a", request: "r", draft: DRAFT, outcome: { kind: "saved" } };
  const aborted: DoRun = { phase: "aborted", id: "a", request: "r", draft: DRAFT, reason: "Stopped" };
  const runFailed: DoRun = { phase: "failed", id: "a", request: "r", draft: DRAFT, msg: "x" };
  const draftFailed: DoRun = { phase: "failed", id: "a", request: "r", draft: null, msg: "x" };
  it.each<[string, DoRun, DoRun | null, boolean, string]>([
    ["running", running, null, true, "Doing it…"],
    ["saving", saving, null, true, "Saving…"],
    ["done, not opened", done, null, true, "Created OFF"],
    ["done, opened", done, done, false, "Created OFF"],
    ["aborted", aborted, null, true, "Stopped"],
    ["a run's fail", runFailed, null, true, "Couldn't finish"],
    ["a failed draft never ran → the sheet", draftFailed, null, false, "Couldn't finish"],
    ["planned → the sheet", planned, null, false, "Doing it…"],
    ["an export building", exportRunning, null, true, "Building the file…"],
    ["edits applied", { phase: "done", id: "a", request: "r", draft: EDIT, outcome: { kind: "applied", results: RESULTS } }, null, true,
      "Changed 1 of 2 rules"],
    ["an export done", { phase: "done", id: "a", request: "r", draft: EXPORT, outcome: { kind: "downloaded", file: "x.csv" } }, null, true, "Downloaded"],
    ["a config applying", configRunning, null, true, "Updating the draft…"],
    ["a config applied", configDone(200, "x"), null, true, "Draft updated"],
    ["a config refused", configDone(409, "x"), null, true, "Not applied"],
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
