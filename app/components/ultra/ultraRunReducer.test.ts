import { describe, expect, it } from "vitest";

import {
  actRequest, buildPickPayload, canApprove, canCancel, canPick, INITIAL_RUN, isFinal, okPayload, okWindow,
  planActions, pollMs, refreshNote, statusNote, ultraRunReducer, waitingStep,
  type Action, type PlanStatus, type PlanView, type StepStatus, type UltraRun,
} from "./ultraRunReducer";

const plan = (status: PlanStatus, steps: StepStatus[] = [{ id: "mass", state: "pending" }]): PlanView => ({
  id: "p1", status, summary: "Halloween push", sha256: "a".repeat(64), card: [], step_states: steps,
  created_at: "2026-11-14T12:00:00Z", expires_at: "2026-11-14T12:10:00Z", approved_at: null, finished_at: null,
});
const run = (actions: Action[], from: UltraRun = INITIAL_RUN) => actions.reduce(ultraRunReducer, from);
const loaded = (status: PlanStatus): Action => ({ type: "loaded", plan: plan(status) });

describe("ultraRunReducer", () => {
  it.each<[string, Action[], Partial<UltraRun>]>([
    ["first read", [loaded("awaiting_ok")], { load: "ready", loadError: null }],
    ["404: missing, no plan", [loaded("awaiting_ok"), { type: "loadFailed", status: 404, message: "plan not found" }],
      { load: "missing", plan: null }],
    ["first read fails: error", [{ type: "loadFailed", status: 500, message: "boom" }], { load: "error", loadError: "boom" }],
    ["a re-poll fails: the plan stays", [loaded("running"), { type: "loadFailed", status: 502, message: "blip" }],
      { load: "ready", loadError: "blip" }],
    ["a read after a failed poll clears it", [loaded("running"), { type: "loadFailed", status: 502, message: "x" }, loaded("done")],
      { load: "ready", loadError: null }],
    ["OK in flight", [loaded("awaiting_ok"), { type: "act", kind: "ok" }], { busy: "ok" }],
    ["a second press while busy is ignored", [loaded("awaiting_ok"), { type: "act", kind: "ok" }, { type: "act", kind: "cancel" }],
      { busy: "ok" }],
    ["OK answered: the running plan", [loaded("awaiting_ok"), { type: "act", kind: "ok" }, { type: "acted", plan: plan("running") }],
      { busy: null, actionError: null }],
    ["OK refused: its words, busy cleared", [loaded("awaiting_ok"), { type: "act", kind: "ok" },
      { type: "actFailed", message: "plan expired" }], { busy: null, actionError: "plan expired" }],
    ["the next press clears the last refusal", [loaded("awaiting_ok"), { type: "actFailed", message: "x" },
      { type: "act", kind: "cancel" }], { busy: "cancel", actionError: null }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });

  it("acted takes the server's plan", () => {
    expect(run([loaded("awaiting_ok"), { type: "acted", plan: plan("running") }]).plan?.status).toBe("running");
  });

  it("a press while busy keeps the same state object", () => {
    const s = run([loaded("awaiting_ok"), { type: "act", kind: "ok" }]);
    expect(ultraRunReducer(s, { type: "act", kind: "ok" })).toBe(s);
  });
});

describe("canApprove / canCancel / okPayload / pollMs", () => {
  it.each<[PlanStatus, boolean, boolean, number | null]>([
    ["planning", false, true, 1500],
    ["awaiting_ok", true, true, 15000],
    ["running", false, true, 2000],
    ["needs_you", false, true, 5000],
    ["capped", false, false, null],
    ["done", false, false, null],
    ["failed", false, false, null],
    ["cancelled", false, false, null],
    ["interrupted", false, false, null],
    ["expired", false, false, null],
  ])("%s", (status, approve, cancel, poll) => {
    const s = run([loaded(status)]);
    expect([canApprove(s), canCancel(s), pollMs(s), isFinal(status)]).toEqual([approve, cancel, poll, poll === null]);
    expect(okPayload(s)).toEqual(approve ? { sha256: "a".repeat(64) } : null);
  });

  it("a status this build does not know: not over, no Cancel, slow poll, no buttons, no crash", () => {
    const s = run([loaded("rerouting" as PlanStatus)]);
    expect([isFinal("rerouting" as PlanStatus), canCancel(s), pollMs(s), planActions(s)]).toEqual([false, false, 15000, []]);
  });

  it("nothing to press before the plan is read or while a press is in flight", () => {
    expect([canApprove(INITIAL_RUN), canCancel(INITIAL_RUN), pollMs(INITIAL_RUN)]).toEqual([false, false, null]);
    const busy = run([loaded("awaiting_ok"), { type: "act", kind: "ok" }]);
    expect([canApprove(busy), canCancel(busy), okPayload(busy)]).toEqual([false, false, null]);
  });
});

describe("a refused read (401/403) stops polling until a read succeeds", () => {
  it.each<[string, Action[], boolean, number | null]>([
    ["502 on a re-poll: keeps polling", [loaded("running"), { type: "loadFailed", status: 502, message: "blip" }], false, 2000],
    ["401 on a re-poll: stops", [loaded("running"), { type: "loadFailed", status: 401, message: "sign in" }], true, null],
    ["403 on a re-poll: stops", [loaded("needs_you"), { type: "loadFailed", status: 403, message: "owners only" }], true, null],
    ["Try again reads it: polls again", [loaded("running"), { type: "loadFailed", status: 401, message: "x" }, loaded("running")],
      false, 2000],
    ["403 on the first read: error, no poll", [{ type: "loadFailed", status: 403, message: "owners only" }], true, null],
  ])("%s", (_name, actions, stopped, poll) => {
    const s = run(actions);
    expect([s.pollStopped, pollMs(s)]).toEqual([stopped, poll]);
  });

  it.each<[string, Action[], ReturnType<typeof refreshNote>]>([
    ["no error", [loaded("running")], null],
    ["502: trying again", [loaded("running"), { type: "loadFailed", status: 502, message: "blip" }],
      { text: "Could not refresh: blip. Trying again.", retry: false }],
    ["401: Try again button", [loaded("running"), { type: "loadFailed", status: 401, message: "sign in" }],
      { text: "Could not refresh: sign in.", retry: true }],
    ["first read failed: none (the error state shows it)", [{ type: "loadFailed", status: 500, message: "boom" }], null],
  ])("refreshNote: %s", (_name, actions, want) => {
    expect(refreshNote(run(actions))).toEqual(want);
  });
});

describe("planActions: the buttons both surfaces draw", () => {
  const card = (id: string) => ({ id, tool: "mass_send", effect: "send" as const, title: "", rows: [] });
  const two: Action = { type: "loaded", plan: { ...plan("awaiting_ok"), card: [card("a"), card("b")] } };
  const one: Action = { type: "loaded", plan: { ...plan("awaiting_ok"), card: [card("a")] } };
  const cands = [11, 12].map((id) => ({ id, type: "photo", thumb: null, description: "" }));
  const needs: Action = { type: "loaded", plan: plan("needs_you",
    [{ id: "pick", state: "needs_you", pick_n: 1, candidates: cands, picks: [11] }]) };
  const needsNone: Action = { type: "loaded", plan: plan("needs_you",
    [{ id: "pick", state: "needs_you", pick_n: 1, candidates: cands, picks: [] }]) };
  /** kind:label, with "!" when disabled and "*" when primary. */
  const short = (s: UltraRun) => planActions(s).map((b) => `${b.kind}:${b.label}${b.primary ? "*" : ""}${b.enabled ? "" : "!"}`);
  it.each<[string, Action[], string[]]>([
    ["nothing read yet", [], []],
    ["awaiting, 2 steps", [two], ["ok:OK, run 2 steps*", "cancel:Cancel plan"]],
    ["awaiting, 1 step", [one], ["ok:OK, run 1 step*", "cancel:Cancel plan"]],
    ["OK in flight: Starting…, no Cancel", [two, { type: "act", kind: "ok" }], ["ok:Starting…*!"]],
    ["cancel in flight: no OK", [two, { type: "act", kind: "cancel" }], ["cancel:Cancelling…!"]],
    ["planning: stop planning", [loaded("planning")], ["cancel:Stop planning"]],
    ["running: cancel the rest", [loaded("running")], ["cancel:Cancel the rest"]],
    ["needs_you, pick_n ticked", [needs], ["pick:Send these*", "cancel:Cancel the rest"]],
    ["needs_you, too few ticked", [needsNone], ["pick:Send these*!", "cancel:Cancel the rest"]],
    ["pick in flight: Sending…, no Cancel", [needs, { type: "act", kind: "pick" }], ["pick:Sending…*!"]],
    ["pick answered running", [needs, { type: "act", kind: "pick" }, { type: "acted", plan: plan("running") }],
      ["cancel:Cancel the rest"]],
    ["done: none", [loaded("done")], []],
    ["expired: none", [loaded("expired")], []],
    ["failed: none", [loaded("failed")], []],
  ])("%s", (_name, actions, want) => {
    expect(short(run(actions))).toEqual(want);
  });
});

describe("statusNote", () => {
  it.each<[PlanStatus, StepStatus[], string]>([
    ["awaiting_ok", [], "Nothing has run yet. Check every step below; OK runs them in order. The plan expires 10 minutes after it was made."],
    ["done", [], "Done: every step ran."],
    ["failed", [{ id: "pick", state: "done" }, { id: "folder", state: "failed" }, { id: "mass", state: "skipped" }],
      "Stopped: step folder failed. Nothing after it ran."],
    ["failed", [{ id: "mass", state: "uncertain" }, { id: "post", state: "skipped" }],
      "Stopped. Step mass got no clear answer and may or may not have gone out. Check OnlyFans before sending it again."],
    ["failed", [{ id: "mass", state: "done" }], "Stopped: the run hit an error before the next step. Nothing after it ran."],
    ["interrupted", [{ id: "a", state: "done" }, { id: "b", state: "uncertain" }, { id: "c", state: "skipped" }],
      "The server restarted while this plan ran, so it stopped. Step b got no clear answer"],
    ["interrupted", [{ id: "a", state: "done" }, { id: "c", state: "skipped" }],
      "The server restarted while this plan ran, so it stopped. The steps marked Not run did not run."],
    ["expired", [], "Expired: it was not approved within 10 minutes, so nothing ran."],
    ["cancelled", [], "Cancelled."],
    ["needs_you", [], "Waiting for you: tick the picks below, then Send these."],
    ["capped", [{ id: "pick", state: "failed" }], "Stopped at the AI budget (step pick). Nothing after it ran."],
  ])("%s %#", (status, steps, words) => {
    expect(statusNote(plan(status, steps))).toContain(words);
  });

  it("an uncertain non-send write is not told to check OnlyFans", () => {
    const card = (effect: "write" | "send") => [{ id: "folder", tool: "of_folder_create", effect, title: "", rows: [] }];
    const steps: StepStatus[] = [{ id: "folder", state: "uncertain" }, { id: "mass", state: "skipped" }];
    expect(statusNote({ ...plan("failed", steps), card: card("write") })).toBe(
      "Stopped. Step folder got no clear answer and may or may not have finished. Check it before running it again. Nothing after it ran.");
    expect(statusNote({ ...plan("failed", steps), card: card("send") })).toContain("Check OnlyFans before sending it again.");
  });

  it.each<[string, string, string | null]>([
    ["2026-11-14T12:00:00Z", "2026-11-14T12:10:00Z", "10 minutes"],
    ["2026-11-14T12:00:00Z", "2026-11-14T12:05:00.4Z", "5 minutes"],
    ["2026-11-14T12:00:00Z", "2026-11-14T12:01:00Z", "1 minute"],
    ["", "", null],
  ])("the OK window comes from the served times: %s → %s", (created_at, expires_at, want) => {
    const p = { ...plan("awaiting_ok"), created_at, expires_at };
    expect(okWindow(p)).toBe(want);
  });

  it("a 5-minute window reads 5 minutes, never a fixed 10", () => {
    const p = { ...plan("awaiting_ok"), expires_at: "2026-11-14T12:05:00Z" };
    expect(statusNote(p)).toContain("The plan expires 5 minutes after it was made.");
    expect(statusNote({ ...p, status: "expired" })).toBe(
      "Expired: it was not approved within 5 minutes, so nothing ran. Ask for a new plan.");
    expect(statusNote({ ...p, created_at: "", expires_at: "" })).not.toContain("expires");
  });
});

describe("planning (no plan yet: no hash)", () => {
  const planning = (status: PlanStatus, prog: PlanView["planning"]): PlanView =>
    ({ ...plan(status, []), sha256: "", expires_at: null, planning: prog });
  it.each<[PlanStatus, PlanView["planning"], string]>([
    ["planning", { turns: 3, max_turns: 25, last_tool: "vault search" },
      "Planning… turn 3 of 25 · last: vault search. Nothing runs before your OK."],
    ["planning", { turns: 0, max_turns: 25, last_tool: null }, "Planning… turn 0 of 25. Nothing runs before your OK."],
    ["capped", { turns: 25, max_turns: 25, last_tool: "x", error: "Stopped at 25 turns without a plan — make the request smaller." },
      "Planning stopped: Stopped at 25 turns without a plan — make the request smaller."],
    ["failed", { turns: 2, max_turns: 25, last_tool: null, error: "Planning failed — try again." },
      "Planning stopped: Planning failed — try again."],
    ["cancelled", { turns: 1, max_turns: 25, last_tool: null }, "Cancelled before a plan was made."],
    ["interrupted", { turns: 1, max_turns: 25, last_tool: null }, "The server restarted while planning, so it stopped. Ask again."],
  ])("%s %#", (status, prog, words) => {
    expect(statusNote(planning(status, prog))).toBe(words);
  });

  it("no OK window without a plan", () => {
    expect(okWindow(planning("planning", undefined))).toBeNull();
  });
});

describe("pick card: tick / canPick / buildPickPayload", () => {
  const cands = [11, 12, 13, 14].map((id) => ({ id, type: "photo", thumb: `/t/${id}`, description: `d${id}` }));
  const waiting: StepStatus = { id: "pick", state: "needs_you", question: "q", pick_n: 2, candidates: cands, picks: [12, 11] };
  const needs: Action = { type: "loaded", plan: plan("needs_you", [waiting, { id: "mass", state: "pending" }]) };
  const tick = (id: number): Action => ({ type: "tick", id });

  it.each<[string, Action[], number[] | null, boolean, { step: string; ids: number[] } | null]>([
    ["AI picks start ticked; card order in the payload", [needs], [12, 11], true, { step: "pick", ids: [11, 12] }],
    ["untick one: 1 of 2, disabled", [needs, tick(12)], [11], false, null],
    ["tick a third: 3 of 2, disabled", [needs, tick(13)], [12, 11, 13], false, null],
    ["swap one: enabled again", [needs, tick(12), tick(14)], [11, 14], true, { step: "pick", ids: [11, 14] }],
    ["an id not on the card is ignored", [needs, tick(99)], [12, 11], true, { step: "pick", ids: [11, 12] }],
    ["a re-poll keeps the owner's ticks", [needs, tick(12), tick(14), needs], [11, 14], true, { step: "pick", ids: [11, 14] }],
    ["in flight: no ticking, no second send", [needs, { type: "act", kind: "pick" }, tick(12)], [12, 11], false, null],
    ["the run moved on: no card", [needs, loaded("running")], null, false, null],
    ["not waiting at all", [loaded("running"), tick(11)], null, false, null],
  ])("%s", (_name, actions, ticked, can, payload) => {
    const s = run(actions);
    expect(s.picked?.ids ?? null).toEqual(ticked);
    expect([canPick(s), buildPickPayload(s)]).toEqual([can, payload]);
  });

  it.each<[string, "ok" | "cancel" | "pick", Action[], { body: object | undefined } | null]>([
    ["ok: the shown hash", "ok", [loaded("awaiting_ok")], { body: { sha256: "a".repeat(64) } }],
    ["ok: not awaiting", "ok", [loaded("running")], null],
    ["cancel: no body", "cancel", [loaded("running")], { body: undefined }],
    ["cancel: over", "cancel", [loaded("done")], null],
    ["cancel: busy", "cancel", [loaded("running"), { type: "act", kind: "cancel" }], null],
    ["pick: ticks in card order", "pick", [needs], { body: { step: "pick", ids: [11, 12] } }],
    ["pick: wrong count", "pick", [needs, tick(12)], null],
  ])("actRequest %s", (_name, kind, actions, want) => {
    expect(actRequest(kind, run(actions))).toEqual(want);
  });

  it("waitingStep finds the needs_you step", () => {
    expect(waitingStep(run([needs]).plan)?.id).toBe("pick");
    expect(waitingStep(null)).toBeNull();
  });

  it("a refused pick keeps the ticks for another try", () => {
    const s = run([needs, tick(12), tick(14), { type: "act", kind: "pick" }, { type: "actFailed", message: "pick exactly 2" }]);
    expect([s.picked?.ids, s.actionError, canPick(s)]).toEqual([[11, 14], "pick exactly 2", true]);
  });
});
