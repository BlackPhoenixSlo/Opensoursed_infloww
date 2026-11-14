/**
 * Full AI Chatter: one header switch over kind `full_ai_chat` (pill Shadow / Off) through the server's kind switch,
 * and today's Shadow Decision rows (GET /admin/full-ai/today): counts in Route order, then the newest rows.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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
const accounts = vi.hoisted(() => ({ list: [{ id: "acc-a", nickname: "Creator A", has_session: true }] }));
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => accounts.list,
  useAccounts: () => ({ isLoading: false }),
}));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));

import FullAiChatterPage from "@/components/automations/FullAiChatterPage";
import { relay } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const rule = (is_enabled: boolean) => ({
  id: 9, account_id: "acc-a", name: "Full AI Chat", kind: "full_ai_chat", is_enabled,
  every_seconds: 86400, trigger: { every_seconds: 86400 }, payload: {},
  quiet_hours: null, created_at: null, last_run: null, next_due_at: null, has_pending_job: false,
});

const TODAY = {
  since: "2026-11-13T00:00:00Z",
  // Keys out of Route order, so the strip's order comes from the page, not the payload.
  counts: { no_send: 1, chat: 7, ai_dare: 2, sext: 6, make_right: 3, sell_now: 5, tease: 4 },
  jev_failed: 8,
  rows: [
    { id: 2, created_at: "2026-11-13T10:05:00Z", fan_id: "77", fan_name: "Garrett", route: "tease", heat: 3,
      row: "tease_price", jev_ms: 412, jev_failed: false },
    { id: 1, created_at: "2026-11-13T10:00:00Z", fan_id: "78", fan_name: null, route: "chat", heat: 1,
      row: "jev_failed", jev_ms: null, jev_failed: true },
  ],
};

let client: QueryClient;
beforeEach(() => {
  client = makeTestQueryClient();
  accounts.list = [{ id: "acc-a", nickname: "Creator A", has_session: true }];
  relayGet.mockReset();
  relayPost.mockReset();
  relayPost.mockResolvedValue({ action: "created" });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mount = (rules: unknown[], today: unknown = TODAY) => {
  relayGet.mockImplementation((path: string) => {
    const p = String(path);
    if (p.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: rules.slice() });
    if (p.startsWith("/admin/full-ai/today")) return Promise.resolve(today);
    return Promise.resolve({});
  });
  renderWithProviders(<FullAiChatterPage />, client);
};
const banner = () => within(screen.getByRole("banner"));
const theSwitch = () => banner().getByRole("switch", { name: "Full AI Chat" }) as HTMLButtonElement;
const switchCalls = () => relayPost.mock.calls.filter((c) => String(c[0]) === "/admin/automation-rules/switch");

describe("Full AI Chatter page", () => {
  it("reads Off with no rule and flips it to Shadow through the server switch", async () => {
    mount([]);
    await waitFor(() => expect(theSwitch().disabled).toBe(false));
    expect(theSwitch().getAttribute("aria-checked")).toBe("false");
    expect(banner().getByText("Off")).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(switchCalls().length).toBe(1));
    expect(switchCalls()[0][1]).toEqual({ account_id: "acc-a", kind: "full_ai_chat", enable: true });
    expect(relayPost).toHaveBeenCalledTimes(1);
  });

  it("reads Shadow from an enabled rule and switches it off", async () => {
    mount([rule(true)]);
    await waitFor(() => expect(theSwitch().getAttribute("aria-checked")).toBe("true"));
    expect(banner().getByText("Shadow")).toBeTruthy();
    await act(async () => { fireEvent.click(theSwitch()); });
    await waitFor(() => expect(switchCalls().length).toBe(1));
    expect(switchCalls()[0][1]).toEqual({ account_id: "acc-a", kind: "full_ai_chat", enable: false });
  });

  it("counts today's rows in Route order, Jev failures last, and reads the Creator's today", async () => {
    mount([rule(true)]);
    const strip = await screen.findByRole("list", { name: "Decisions per route" });
    await waitFor(() => expect(within(strip).getAllByRole("listitem")[0].textContent).toBe("Chat7"));
    expect(within(strip).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Chat7", "Sext6", "Sell now5", "Tease4", "Make right3", "AI dare2", "No send1", "Jev failed8",
    ]);
    expect(relayGet.mock.calls.some((c) => String(c[0]) === "/admin/full-ai/today?account_id=acc-a")).toBe(true);
  });

  it("shows the newest rows: Fan, Route, Heat, row and Jev latency or Jev failed", async () => {
    mount([rule(true)]);
    const rows = await screen.findAllByTestId("full-ai-row");
    expect(rows.length).toBe(2);
    const first = within(rows[0]).getAllByRole("cell").map((td) => td.textContent);
    expect(first.slice(1)).toEqual(["Garrett", "Tease", "3", "tease_price", "412 ms"]);
    const second = within(rows[1]).getAllByRole("cell").map((td) => td.textContent);
    expect(second.slice(1)).toEqual(["Fan 78", "Chat", "1", "jev_failed", "Jev failed"]);
  });

  it("shows the house no-Creator state and reads nothing with no live Creator", async () => {
    accounts.list = [];
    mount([]);
    expect(await screen.findByText("No creator with a live session")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Full AI Chat" })).toBeNull();
    expect(relayGet).not.toHaveBeenCalled();
  });
});
