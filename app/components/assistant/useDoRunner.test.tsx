/**
 * The runner end to end over the real Auto Mass page under <StrictMode> (next.config reactStrictMode: true, as in
 * `next dev`): effects mount, unmount and mount again, so every bridge registration churns once. A run must still
 * fill the editor and save it OFF. Relay mocked at the module boundary.
 */
import { StrictMode, useEffect, useReducer, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return {
    ...mod,
    useActiveAccounts: () => [{ id: "acc-a", nickname: "Creator A", has_session: true }],
    useAccounts: () => ({ isLoading: false }),
  };
});

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";
import { fullAiConfigKey } from "@/hooks/useFullAiConfig";
import { relay, RelayError } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";
import { AgentBridgeProvider, createAgentBridge } from "./agentBridge";
import type { DoDraft, MassPremadeSlots } from "./doFlows";
import { doRunReducer, type DoAction, type DoRun } from "./doRunReducer";
import { useDoRunner } from "./useDoRunner";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const put = relay.put as unknown as Mock;

const SLOTS: MassPremadeSlots = {
  name: "Hourly", interval: { value: 1, unit: "hours" }, captions: ["one", "two"], captions_ai: 0, folder: null,
  online_only: false, includes: ["fans", "following"], excludes: [], unsend_after_hours: 8, exclude_last_chat_hours: null,
};
const DRAFT: DoDraft = {
  id: "d1", flow: "mass_premade", account_id: "acc-a", summary: "", slots: SLOTS, assumptions: [], unresolved: [],
  answer: "", error: null,
};

/** The harness's latest run and dispatch, for the test to read / drive. */
const probe: { run: DoRun; send: (a: DoAction) => void } = { run: { phase: "off" }, send: () => {} };

function Harness() {
  const [bridge] = useState(createAgentBridge);
  const [run, dispatch] = useReducer(doRunReducer, { phase: "planned", id: "a", request: "r", draft: DRAFT });
  useDoRunner({ run, dispatch, bridge, navigate: () => {}, employeeId: null });
  useEffect(() => { probe.run = run; probe.send = dispatch; });
  return <AgentBridgeProvider bridge={bridge}><ReadyMadePanel only="mass_premade" /></AgentBridgeProvider>;
}

beforeEach(() => {
  get.mockImplementation((path: string) => Promise.resolve(
    path.startsWith("/admin/automation-rules") ? { rules: [] } : path.startsWith("/admin/stats/automation-runs") ? { runs: [] } : {}));
  post.mockResolvedValue({ id: 9 });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("useDoRunner under StrictMode", () => {
  it.each(["start", "skipAnimation"] as const)("%s: fills the real editor and saves it OFF despite registration churn", async (type) => {
    renderWithProviders(<StrictMode><Harness /></StrictMode>);
    await waitFor(() => expect(document.getElementById("rm-mass_premade-new")).toBeTruthy());
    act(() => probe.send({ type }));
    await waitFor(() => expect(probe.run.phase).not.toBe("running"), { timeout: 15_000 });
    expect(probe.run.phase === "failed" ? probe.run.msg : null).toBeNull();
    expect(probe.run).toMatchObject({ phase: "done" });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][1]).toMatchObject({
      account_id: "acc-a", kind: "mass_premade", name: "Hourly", every_seconds: 3600, is_enabled: false,
      payload: { messages: [{ texts: ["one", "two"], unsend_after_hours: 8 }] },
    });
  }, 20_000);
});

const CONFIG_SLOTS = {
  rev: 4, before: { reply_speed: "0-2m" }, after: { reply_speed: "0-15-60" }, account_name: "Creator A",
  diffs: [{ field: "reply_speed", label: "Reply speed", before: "0-2m", after: "0-15-60" }],
};
const CONFIG_DRAFT: DoDraft = { ...DRAFT, id: "c1", flow: "full_ai_config", slots: CONFIG_SLOTS };

function ConfigHarness() {
  const [bridge] = useState(createAgentBridge);
  const [run, dispatch] = useReducer(doRunReducer, { phase: "planned", id: "a", request: "r", draft: CONFIG_DRAFT });
  useDoRunner({ run, dispatch, bridge, navigate: () => {}, employeeId: 7 });
  useEffect(() => { probe.run = run; probe.send = dispatch; });
  return null;
}

describe("useDoRunner: full_ai_config apply (phase 03c)", () => {
  it.each([
    [200, () => Promise.resolve({ rev: 5 }), "Draft updated. Save on the page makes it the checkpoint.", true],
    [409, () => Promise.reject(new RelayError(409, { detail: "stale", rev: 6 })), "The draft changed since you saw it. Ask again.", false],
    [422, () => Promise.reject(new RelayError(422, { errors: ["reply_speed: bad"] })), "Not applied: reply_speed: bad", false],
  ])("Apply → one PUT on the draft's rev; %i ends done with its line", async (status, answer, line, invalidates) => {
    put.mockImplementation(answer);
    const qc = makeTestQueryClient();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    renderWithProviders(<StrictMode><ConfigHarness /></StrictMode>, qc);
    act(() => probe.send({ type: "start" }));
    await waitFor(() => expect(probe.run.phase).toBe("done"));
    expect(put.mock.calls).toEqual([[
      "/admin/full-ai/config/draft", { account_id: "acc-a", draft: CONFIG_SLOTS.after, rev: 4 }, { accountId: "acc-a", employeeId: 7 },
    ]]);
    expect(probe.run).toMatchObject({ phase: "done", outcome: { kind: "config", status, line } });
    if (invalidates) expect(invalidate).toHaveBeenCalledWith({ queryKey: fullAiConfigKey("acc-a") });
    else expect(invalidate).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("a network error fails the run (no line to show)", async () => {
    put.mockRejectedValue(new Error("offline"));
    renderWithProviders(<StrictMode><ConfigHarness /></StrictMode>);
    act(() => probe.send({ type: "start" }));
    await waitFor(() => expect(probe.run.phase).toBe("failed"));
    expect(probe.run).toMatchObject({ phase: "failed", msg: "offline" });
    expect(put).toHaveBeenCalledTimes(1);
  });
});
