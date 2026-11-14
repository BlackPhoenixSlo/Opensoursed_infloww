import { describe, expect, it } from "vitest";

import {
  canApprove, canCancel, cancelLabel, INITIAL_RUN, okLabel, okPayload, okWindow, pollMs, showOk, statusNote,
  ultraRunReducer,
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
    ["awaiting_ok", true, true, 15000],
    ["running", false, true, 2000],
    ["done", false, false, null],
    ["failed", false, false, null],
    ["cancelled", false, false, null],
    ["interrupted", false, false, null],
    ["expired", false, false, null],
  ])("%s", (status, approve, cancel, poll) => {
    const s = run([loaded(status)]);
    expect([canApprove(s), canCancel(s), pollMs(s)]).toEqual([approve, cancel, poll]);
    expect(okPayload(s)).toEqual(approve ? { sha256: "a".repeat(64) } : null);
  });

  it("nothing to press before the plan is read or while a press is in flight", () => {
    expect([canApprove(INITIAL_RUN), canCancel(INITIAL_RUN), pollMs(INITIAL_RUN)]).toEqual([false, false, null]);
    const busy = run([loaded("awaiting_ok"), { type: "act", kind: "ok" }]);
    expect([canApprove(busy), canCancel(busy), okPayload(busy)]).toEqual([false, false, null]);
  });
});

describe("showOk / okLabel / cancelLabel", () => {
  const card = (id: string) => ({ id, tool: "mass_send", effect: "send" as const, title: "", rows: [] });
  const two: Action = { type: "loaded", plan: { ...plan("awaiting_ok"), card: [card("a"), card("b")] } };
  const one: Action = { type: "loaded", plan: { ...plan("awaiting_ok"), card: [card("a")] } };
  it.each<[string, Action[], boolean, string, string]>([
    ["awaiting, 2 steps", [two], true, "OK, run 2 steps", "Cancel plan"],
    ["awaiting, 1 step", [one], true, "OK, run 1 step", "Cancel plan"],
    ["OK in flight", [two, { type: "act", kind: "ok" }], true, "Starting…", "Cancel plan"],
    ["cancel in flight: no OK", [two, { type: "act", kind: "cancel" }], false, "OK, run 2 steps", "Cancelling…"],
    ["running: no OK, cancel the rest", [loaded("running")], false, "OK, run 0 steps", "Cancel the rest"],
    ["done: OK shown but disabled", [loaded("done")], true, "OK, run 0 steps", "Cancel plan"],
  ])("%s", (_name, actions, ok, okText, cancelText) => {
    const s = run(actions);
    expect([showOk(s), okLabel(s), cancelLabel(s)]).toEqual([ok, okText, cancelText]);
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
    ["interrupted", [{ id: "a", state: "done" }, { id: "b", state: "uncertain" }, { id: "c", state: "skipped" }],
      "The server restarted while this plan ran, so it stopped. Step b got no clear answer"],
    ["interrupted", [{ id: "a", state: "done" }, { id: "c", state: "skipped" }],
      "The server restarted while this plan ran, so it stopped. The steps marked Not run did not run."],
    ["expired", [], "Expired: it was not approved within 10 minutes, so nothing ran."],
    ["cancelled", [], "Cancelled."],
  ])("%s %#", (status, steps, words) => {
    expect(statusNote(plan(status, steps))).toContain(words);
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
