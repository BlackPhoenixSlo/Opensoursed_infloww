/**
 * The agent bridge over the real Auto Mass page: ReadyMadePanel registers its New, the editor its dispatch and its
 * OWN Save (same canSave gate, same POST as the Create button). Relay mocked at the module boundary.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";

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
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { AgentBridgeProvider, createAgentBridge, type AgentBridge } from "./agentBridge";
import { DO_FLOWS, type MassPremadeSlots } from "./doFlows";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;

const SLOTS: MassPremadeSlots = {
  name: "Hourly", interval: { value: 1, unit: "hours" }, captions: ["one", "two"], captions_ai: 0, folder: null,
  online_only: false, includes: ["fans", "following"], excludes: [], unsend_after_hours: 8, exclude_last_chat_hours: null,
};

let bridge: AgentBridge;
const signal = () => new AbortController().signal;

beforeEach(() => {
  bridge = createAgentBridge();
  get.mockImplementation((path: string) => Promise.resolve(
    path.startsWith("/admin/automation-rules") ? { rules: [] } : path.startsWith("/admin/stats/automation-runs") ? { runs: [] } : {}));
  post.mockResolvedValue({ id: 9 });
  renderWithProviders(<AgentBridgeProvider bridge={bridge}><ReadyMadePanel only="mass_premade" /></AgentBridgeProvider>);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("agent bridge on Auto Mass", () => {
  it("opens a new editor and saves the played steps through the editor's own Create: OFF", async () => {
    expect(document.getElementById("rm-mass_premade-new")).toBeTruthy();
    const panel = await bridge.waitFor(() => bridge.panel("mass_premade", "acc-a"), 2000, signal());
    act(() => panel.openNew());
    const editor = await bridge.waitFor(() => bridge.editor("mass_premade", "acc-a"), 2000, signal());
    expect(screen.getByRole("dialog")).toBeTruthy();
    for (const id of ["rm-mass_premade-enabled", "rm-mass_premade-dry-run", "rm-mass_premade-save", "rm-mass_premade-unit",
      "pm-mass_premade-online-only", "pm-mass_premade-unsend", "pm-mass_premade-last-chat"]) {
      expect(document.getElementById(id), id).toBeTruthy();
    }

    let result: Awaited<ReturnType<typeof editor.save>> | undefined;
    await act(async () => {
      // Instant play: every dispatch in one go, then Save (it waits for them to render).
      for (const step of DO_FLOWS.mass_premade.toActions(SLOTS)) if (typeof step.action !== "string") editor.dispatch(step.action);
      result = await editor.save();
    });
    expect(result).toEqual({ ok: true });
    expect(post).toHaveBeenCalledTimes(1);
    const [path, body] = post.mock.calls[0];
    expect(path).toBe("/admin/automation-rules");
    expect(body).toMatchObject({
      account_id: "acc-a", kind: "mass_premade", name: "Hourly", every_seconds: 3600, is_enabled: false,
      payload: { messages: [{ texts: ["one", "two"], unsend_after_hours: 8, user_lists: ["fans", "following"] }] },
    });
    expect(body.payload.messages[0].online_only).toBeUndefined();
    // Saved: the editor closed and unregistered.
    await waitFor(() => expect(bridge.editor("mass_premade", "acc-a")).toBeNull());
  });

  it("the agent's save forces is_enabled:false even with no Enabled step played (and the switch left ON)", async () => {
    expect(bridge.hasEditor()).toBe(false);
    const panel = await bridge.waitFor(() => bridge.panel("mass_premade", "acc-a"), 2000, signal());
    act(() => panel.openNew());
    const editor = await bridge.waitFor(() => bridge.editor("mass_premade", "acc-a"), 2000, signal());
    expect(bridge.hasEditor()).toBe(true);
    const steps = DO_FLOWS.mass_premade.toActions(SLOTS)
      .filter((s) => typeof s.action !== "string" && !(s.action.type === "field" && "enabled" in s.action.patch));
    expect(steps.length).toBeGreaterThan(0);
    await act(async () => {
      editor.dispatch({ type: "field", patch: { enabled: true, dryRun: false } });
      for (const step of steps) if (typeof step.action !== "string") editor.dispatch(step.action);
      expect(await editor.save()).toEqual({ ok: true });
    });
    expect(post.mock.calls[0][1]).toMatchObject({ is_enabled: false });
  });

  it("a blocked save sends nothing, returns the editor's own wait reason and leaves it open", async () => {
    const panel = await bridge.waitFor(() => bridge.panel("mass_premade", "acc-a"), 2000, signal());
    act(() => panel.openNew());
    const editor = await bridge.waitFor(() => bridge.editor("mass_premade", "acc-a"), 2000, signal());
    let result: Awaited<ReturnType<typeof editor.save>> | undefined;
    await act(async () => { result = await editor.save(); }); // no text yet
    expect(result).toEqual({ ok: false, reason: expect.stringMatching(/^Add text to enable Create/) });
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("an unresolved list (includes: []) clears the audience: Save is blocked by the editor's own gate, editor open", async () => {
    const panel = await bridge.waitFor(() => bridge.panel("mass_premade", "acc-a"), 2000, signal());
    act(() => panel.openNew());
    const editor = await bridge.waitFor(() => bridge.editor("mass_premade", "acc-a"), 2000, signal());
    let result: Awaited<ReturnType<typeof editor.save>> | undefined;
    await act(async () => {
      for (const step of DO_FLOWS.mass_premade.toActions({ ...SLOTS, includes: [] })) {
        if (typeof step.action !== "string") editor.dispatch(step.action);
      }
      result = await editor.save();
    });
    expect(result).toEqual({ ok: false, reason: expect.stringMatching(/^Pick who gets it/) });
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("waitFor times out, and rejects on abort", async () => {
    await expect(bridge.waitFor(() => null, 20, signal())).rejects.toThrow("timeout");
    const ctl = new AbortController();
    const p = bridge.waitFor(() => null, 2000, ctl.signal);
    ctl.abort();
    await expect(p).rejects.toThrow("aborted");
  });
});
