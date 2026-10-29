/**
 * CotagTab — Settings › Co-creator tag (ticket 85). The panel picks a Creator (the one in scope, else the
 * first session-backed one) and mounts that Creator's CotagCard; a blank stored pick reads as
 * "No co-creator tag", the default. With no Creator, nothing is loaded.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const { scope, roster } = vi.hoisted(() => ({
  scope: { accountId: "acc1" as string | null },
  roster: { accounts: [] as Array<{ id: string; nickname: string; has_session: boolean }> },
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => scope }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => roster.accounts, useAccounts: () => ({ isLoading: false }) }));
vi.mock("@/components/ui/AccountAvatarPicture", () => ({ AccountAvatarPicture: () => null }));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import CotagTab from "@/components/settings/CotagTab";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CotagTab /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  relayGet.mockReset();
  scope.accountId = "acc1";
});

describe("CotagTab", () => {
  it("shows the scoped creator's co-creator tag, off when blank", async () => {
    relayGet.mockImplementation((path: string) => Promise.resolve(path.startsWith("/admin/account-config")
      ? { account_id: "acc1", config: { cotag_tag_videos: false, cotag_username: null } }
      : []));
    renderTab();
    expect(screen.getByRole("heading", { name: "Co-creator tag" })).toBeTruthy();
    expect(screen.getByText(/mass messages, mass posts, automations and\s+stories/)).toBeTruthy();
    await screen.findByLabelText("Search creators");
    expect(screen.getByTestId("cotag-pick").textContent).toBe("No co-creator tag");
    expect(relayGet.mock.calls.some(([p]) => String(p).startsWith("/admin/account-config"))).toBe(true);
  });

  it("asks for a creator and loads nothing when there is none", () => {
    scope.accountId = null;
    renderTab();
    expect(screen.getByText("Select a creator to set its co-creator tag")).toBeTruthy();
    expect(relayGet).not.toHaveBeenCalled();
  });
});
