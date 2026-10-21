/**
 * My Automations > Gen-Info: one switch over the daily `gen_info` kind, through
 * the server's own kind switch (it decides the row, cadence and name), and under
 * it the one-shot old-fans run (`process_old_fans`, pushed to OnlyFans).
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  // Every verb mocked, so nothing here can reach a live relay.
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => [{ id: "acc-a", nickname: "Creator A", has_session: true }],
  useAccounts: () => ({ isLoading: false }),
}));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));

import GenInfoPage from "@/components/growth/GenInfoPage";
import { relay } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const rule = (is_enabled: boolean, last_run: unknown = null) => ({
  id: 7, account_id: "acc-a", name: "Generate fan profiles", kind: "gen_info", is_enabled,
  every_seconds: 86400, trigger: { every_seconds: 86400 }, payload: {},
  quiet_hours: null, created_at: null, last_run, next_due_at: null, has_pending_job: false,
});

let client: QueryClient;
beforeEach(() => {
  client = makeTestQueryClient();
  relayGet.mockReset();
  relayPost.mockReset();
  relayPost.mockResolvedValue({ action: "created", enqueued_job_id: 42 });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mount = (rules: unknown[] | Promise<never>) => {
  relayGet.mockImplementation((path: string) =>
    String(path).startsWith("/admin/automation-rules")
      ? (Array.isArray(rules) ? Promise.resolve({ rules: rules.slice() }) : rules)
      : Promise.resolve({}));
  renderWithProviders(<GenInfoPage />, client);
};
const theSwitch = () => screen.getByRole("switch", { name: "Gen-Info" }) as HTMLButtonElement;
const callsTo = (path: string) => relayPost.mock.calls.filter((c) => String(c[0]) === path);

describe("Gen-Info page", () => {
  it("turns the gen_info kind on through the server switch, sending nothing else", async () => {
    mount([]);
    await waitFor(() => expect(theSwitch().disabled).toBe(false));
    expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/Every day, reads your fans/)).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(callsTo("/admin/automation-rules/switch").length).toBe(1));
    expect(callsTo("/admin/automation-rules/switch")[0][1]).toEqual({ account_id: "acc-a", kind: "gen_info", enable: true });
    expect(relayPost).toHaveBeenCalledTimes(1);
  });

  it("shows a running rule as on, with its last run, and switches it off", async () => {
    mount([rule(true, {
      status: "ok", started_at: "2026-10-18T10:00:00Z", completed_at: "2026-10-18T10:01:00Z",
      error_text: null, stats: { generated: 3 },
    })]);
    await waitFor(() => expect(theSwitch().getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByText(/3 fans updated/)).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(callsTo("/admin/automation-rules/switch").length).toBe(1));
    expect(callsTo("/admin/automation-rules/switch")[0][1]).toEqual({ account_id: "acc-a", kind: "gen_info", enable: false });
  });

  it("claims nothing and writes nothing before the rules are read", async () => {
    mount(new Promise<never>(() => {}));
    await screen.findByText(/Every day, reads your fans/);
    expect(theSwitch().disabled).toBe(true);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("runs the old fans once: process_old_fans over the 100 most recent, pushed to OnlyFans", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mount([]);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Also run on old fans" })); });
    await waitFor(() => expect(callsTo("/admin/automation/enqueue").length).toBe(1));
    expect(callsTo("/admin/automation/enqueue")[0][1]).toEqual({
      account_id: "acc-a", kind: "process_old_fans",
      payload: { recent_limit: 100, recent_by: "subscribed", push_to_of: true },
    });
    expect(await screen.findByText(/job #42/)).toBeTruthy();
  });
});
