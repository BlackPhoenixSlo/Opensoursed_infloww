import { describe, expect, it } from "vitest";

import {
  canSubmit, INITIAL_PANEL, isOver, isRunning, MAX_REQUEST, requestBody, ultraPanelReducer,
  type PanelAction, type UltraPanel,
} from "./ultraPanelReducer";
import type { PlanStatus, PlanView } from "./ultraRunReducer";

const view = (id: string, status: PlanStatus): PlanView => ({
  id, status, summary: "s", sha256: "abc", card: [], step_states: [],
  created_at: "2026-11-14T10:00:00Z", expires_at: null, approved_at: null, finished_at: null,
});
const run = (actions: PanelAction[], from: UltraPanel = INITIAL_PANEL) => actions.reduce(ultraPanelReducer, from);
const hydrated: PanelAction = { type: "hydrate", planId: null };
const draft = (text: string): PanelAction => ({ type: "draft", text });
const started = (id: string, status: PlanStatus = "planning"): PanelAction => ({ type: "started", plan: view(id, status) });
const loaded = (id: string, status: PlanStatus): PanelAction =>
  ({ type: "run", action: { type: "loaded", plan: view(id, status) } });

describe("composer: canSubmit / requestBody", () => {
  it.each<[string, PanelAction[], { request: string } | null]>([
    ["before hydrate: never (would race the stored plan)", [draft("go")], null],
    ["empty", [hydrated], null],
    ["whitespace only", [hydrated, draft("   ")], null],
    ["trimmed request", [hydrated, draft("  mass the new set  ")], { request: "mass the new set" }],
    ["in flight", [hydrated, draft("go"), { type: "start" }], null],
    ["a plan is open", [{ type: "hydrate", planId: "p1" }, draft("go")], null],
    ["refused: may retry, draft kept", [hydrated, draft("go"), { type: "start" }, { type: "startFailed", message: "cap" }],
      { request: "go" }],
  ])("%s", (_name, actions, body) => {
    const s = run(actions);
    expect([canSubmit(s), requestBody(s)]).toEqual([body !== null, body]);
  });

  it("draft clamps to the server's limit", () => {
    expect(run([hydrated, draft("x".repeat(MAX_REQUEST + 50))]).draft).toHaveLength(MAX_REQUEST);
  });

  it("start is a no-op when it can't submit", () => {
    const s = run([hydrated]);
    expect(ultraPanelReducer(s, { type: "start" })).toBe(s);
  });
});

describe("credential guard (ticket 11)", () => {
  it.each<[string, string, boolean]>([
    ["colon login", "log in a@x.com:hunter22", true],
    ["login on its own line", "add these\nb@y.com hunter22", true],
    ["plain request", "mass the new set to a@x.com fans", false],
    ["email only", "who is a@x.com", false],
  ])("%s", (_name, text, refused) => {
    const ready = run([hydrated, draft(text)]);
    const s = ultraPanelReducer(ready, { type: "start" });
    if (refused) {
      expect(requestBody(ready)).toBeNull();
      expect([s.starting, s.draft, s.startError, s.loginRefused]).toEqual([false, "", null, true]);
    } else {
      expect(requestBody(ready)).not.toBeNull();
      expect([s.starting, s.startError, s.loginRefused]).toEqual([true, null, false]);
    }
  });

  it("the relay's 400 (its login guard) maps to the same refusal, draft cleared", () => {
    const s = run([hydrated, draft("log in x"), { type: "start" },
      { type: "startFailed", message: "paste logins in the Connect card", loginRefused: true }]);
    expect([s.starting, s.draft, s.startError, s.loginRefused]).toEqual([false, "", null, true]);
  });

  it.each<[string, PanelAction]>([
    ["a clean start", { type: "start" }],
    ["reset", { type: "reset" }],
  ])("%s clears the refusal", (_name, next) => {
    const refused = run([hydrated, draft("a@x.com:hunter22"), { type: "start" }, draft("go")]);
    expect(refused.loginRefused).toBe(true);
    expect(ultraPanelReducer(refused, next).loginRefused).toBe(false);
  });
});

describe("plan lifecycle", () => {
  it("hydrate runs once (a later stored read can't replace the open plan)", () => {
    expect(run([{ type: "hydrate", planId: "p1" }, { type: "hydrate", planId: "p2" }]).planId).toBe("p1");
  });

  it("started opens the plan, clears the draft, loads the view", () => {
    const s = run([hydrated, draft("go"), { type: "start" }, started("p1")]);
    expect([s.planId, s.draft, s.starting, s.run.plan?.id, s.run.load]).toEqual(["p1", "", false, "p1", "ready"]);
  });

  it("startFailed shows the server's words", () => {
    const s = run([hydrated, draft("go"), { type: "start" }, { type: "startFailed", message: "Daily Ultra cap reached" }]);
    expect([s.starting, s.startError, s.planId]).toEqual([false, "Daily Ultra cap reached", null]);
  });

  it("a start clears the old error", () => {
    const s = run([hydrated, draft("go"), { type: "start" }, { type: "startFailed", message: "x" }, { type: "start" }]);
    expect(s.startError).toBeNull();
  });

  it("reset drops the plan, back to the composer", () => {
    const s = run([hydrated, draft("go"), { type: "start" }, started("p1"), loaded("p1", "done"), { type: "reset" }]);
    expect([s.planId, s.run.plan, canSubmit(run([draft("next")], s))]).toEqual([null, null, true]);
  });

  it("a late answer for another plan is dropped", () => {
    const s = run([hydrated, draft("go"), { type: "start" }, started("p1")]);
    expect(ultraPanelReducer(s, loaded("p0", "done"))).toBe(s);
  });

  it("a run action with no plan open is dropped", () => {
    const s = run([hydrated]);
    expect(ultraPanelReducer(s, loaded("p1", "running"))).toBe(s);
  });

  it("404 on the stored plan drops it", () => {
    const s = run([{ type: "hydrate", planId: "gone" },
      { type: "run", action: { type: "loadFailed", status: 404, message: "plan not found" } }]);
    expect([s.planId, s.run.plan]).toEqual([null, null]);
  });
});

describe("isOver / isRunning", () => {
  it.each<[PlanStatus, boolean, boolean]>([
    ["planning", false, false],
    ["awaiting_ok", false, false],
    ["running", false, true],
    ["needs_you", false, false],
    ["done", true, false],
    ["failed", true, false],
    ["cancelled", true, false],
    ["capped", true, false],
    ["interrupted", true, false],
    ["expired", true, false],
  ])("%s", (status, over, running) => {
    const s = run([{ type: "hydrate", planId: "p1" }, loaded("p1", status)]);
    expect([isOver(s), isRunning(s)]).toEqual([over, running]);
  });

  it("no plan: neither", () => {
    expect([isOver(INITIAL_PANEL), isRunning(INITIAL_PANEL)]).toEqual([false, false]);
  });
});

it("a non-404 read error keeps the plan (Try again)", () => {
  const s = run([{ type: "hydrate", planId: "p1" },
    { type: "run", action: { type: "loadFailed", status: 500, message: "boom" } }]);
  expect([s.planId, s.run.load, s.run.loadError]).toEqual(["p1", "error", "boom"]);
});
