/**
 * TAG A CO-CREATOR, WHICH ONE, OR NO ONE (ticket 85).
 *
 *  1. "No co-creator tag" is the default pick, and choosing it hands the form
 *     '' (the server stores blank as no tag).
 *  2. The co-creators offered are this account's OF tagged-friend list — the
 *     only ids OF accepts in a tag — so a pick cannot be a handle OF refuses.
 *  3. A stored handle that is not on that list still shows, flagged, instead of
 *     silently reading as "no tag" or as a valid pick. Only a LOADED list can
 *     say a pick is off it: while it loads or after it fails, the pick shows
 *     plain.
 *  4. CotagCard (Settings › Co-creator tag) saves the stored config back with
 *     only the co-tag key changed: the account-config PUT replaces what it holds.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: {
      ...mod.relay,
      get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(),
      delete: vi.fn(), uploadFile: vi.fn(),
    },
  };
});

import CotagSection, { CotagCard } from "@/components/automations/CotagSection";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const ACC = "900001";

const FRIENDS = {
  items: [
    { id: 11, name: "Co One", user: { id: 11, username: "coone", name: "Co One" } },
    { id: 22, name: "Co Two", user: { id: 22, username: "cotwo", name: "Co Two" } },
  ],
  hasMore: false,
};

function renderSection(username: string | null, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  render(<CotagSection accountId={ACC} tagVideos={false} username={username}
                       onChange={onChange} />, { wrapper });
  return onChange;
}

afterEach(() => { cleanup(); relayGet.mockReset(); relayPut.mockReset(); });

describe("CotagSection", () => {
  it("defaults to No co-creator tag and offers the account's tagged-friend list", async () => {
    relayGet.mockResolvedValue(FRIENDS);
    const onChange = renderSection(null);
    const select = screen.getByLabelText("Co-creator to tag") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(select.selectedOptions[0].textContent).toBe("No co-creator tag");
    await waitFor(() => expect(screen.getByRole("option", { name: /@coone/ })).toBeTruthy());
    expect(relayGet.mock.calls[0][0]).toContain("/api/of/v2/posts/tagged-friend-users");
    // The relay route refuses limit > 50 with a 422.
    expect(new URL(relayGet.mock.calls[0][0], "http://x").searchParams.get("limit")).toBe("50");
    expect(relayGet.mock.calls[0][1]).toEqual({ accountId: ACC });

    fireEvent.change(select, { target: { value: "cotwo" } });
    expect(onChange).toHaveBeenLastCalledWith({ cotag_username: "cotwo" });
  });

  it("picking No co-creator tag hands the form an empty string", async () => {
    relayGet.mockResolvedValue(FRIENDS);
    const onChange = renderSection("coone");
    const select = screen.getByLabelText("Co-creator to tag") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("coone"));
    fireEvent.change(select, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({ cotag_username: "" });
  });

  it("keeps a stored handle that is not on the list visible and flagged", async () => {
    relayGet.mockResolvedValue(FRIENDS);
    renderSection("stranger");
    const select = screen.getByLabelText("Co-creator to tag") as HTMLSelectElement;
    expect(select.value).toBe("stranger");
    await waitFor(() => expect(screen.getByRole("option", { name: /@coone/ })).toBeTruthy());
    expect(select.selectedOptions[0].textContent).toMatch(/@stranger.*not on this account/);
  });

  it("says so when OnlyFans' list can't be loaded", async () => {
    relayGet.mockRejectedValue(new Error("502"));
    renderSection(null);
    await waitFor(() => expect(screen.getByText(/Couldn.t load this account.s co-creators/)).toBeTruthy());
  });

  it("does not flag the saved pick when the list fails to load", async () => {
    relayGet.mockRejectedValue(new Error("502"));
    renderSection("coone");
    const select = screen.getByLabelText("Co-creator to tag") as HTMLSelectElement;
    expect(select.selectedOptions[0].textContent).toBe("@coone");   // while loading
    await waitFor(() => expect(screen.getByText(/Couldn.t load/)).toBeTruthy());
    expect(select.value).toBe("coone");
    expect(select.selectedOptions[0].textContent).toBe("@coone");
  });

  it("CotagCard saves the stored config with only the pick changed", async () => {
    const config = { persona: "Ella.", model_notes: "note", cotag_tag_videos: false, cotag_username: null };
    relayGet.mockImplementation((path: string) => Promise.resolve(
      path.startsWith("/admin/account-config") ? { account_id: ACC, config } : FRIENDS));
    relayPut.mockResolvedValue({ account_id: ACC, config: { ...config, cotag_username: "coone" } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CotagCard accountId={ACC} /></QueryClientProvider>);
    const select = await screen.findByLabelText("Co-creator to tag") as HTMLSelectElement;
    expect(select.value).toBe("");
    const save = screen.getByRole("button", { name: "Save co-creator tag" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await waitFor(() => expect(screen.getByRole("option", { name: /@coone/ })).toBeTruthy());
    fireEvent.change(select, { target: { value: "coone" } });
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config",
      { account_id: ACC, config: { ...config, cotag_username: "coone" } }]);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved."));
  });
});
