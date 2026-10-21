/**
 * TAG A CO-CREATOR, WHICH ONE, OR NO ONE (ticket 85).
 *
 *  1. "No co-creator tag" is the default, and Remove hands the form ''
 *     (the server stores blank as no tag).
 *  2. The co-creator can be any OnlyFans creator: typing searches OF's
 *     performers-search and a result is the pick, stored as its handle.
 *  3. A stored handle shows as the pick whatever the search says, and a failed
 *     search keeps it.
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

const FOUND = [
  { id: 11, name: "Co One", username: "CoOne" },
  { id: 22, name: "Co Two", username: "cotwo" },
];

function renderSection(username: string | null, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  render(<CotagSection accountId={ACC} tagVideos={false} username={username}
                       onChange={onChange} />, { wrapper });
  return onChange;
}

const search = (text: string) =>
  fireEvent.change(screen.getByLabelText("Search creators"), { target: { value: text } });

afterEach(() => { cleanup(); relayGet.mockReset(); relayPut.mockReset(); });

describe("CotagSection", () => {
  it("defaults to No co-creator tag and searches no one until typed into", () => {
    renderSection(null);
    expect(screen.getByTestId("cotag-pick").textContent).toBe("No co-creator tag");
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(relayGet).not.toHaveBeenCalled();
  });

  it("searches any OnlyFans creator and picks a result's handle", async () => {
    relayGet.mockResolvedValue(FOUND);
    const onChange = renderSection(null);
    search("@co one");
    await waitFor(() => expect(screen.getByRole("button", { name: /@coone \(Co One\)/ })).toBeTruthy());
    const url = new URL(relayGet.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/api/of/v2/users/performers-search");
    expect(url.searchParams.get("query")).toBe("co one");
    expect(relayGet.mock.calls[0][1]).toEqual({ accountId: ACC });

    fireEvent.click(screen.getByRole("button", { name: /@cotwo/ }));
    expect(onChange).toHaveBeenLastCalledWith({ cotag_username: "cotwo" });
    expect((screen.getByLabelText("Search creators") as HTMLInputElement).value).toBe("");
  });

  it("reads OF's {list} answer too", async () => {
    relayGet.mockResolvedValue({ list: FOUND });
    renderSection(null);
    search("co");
    await waitFor(() => expect(screen.getByRole("button", { name: /@cotwo/ })).toBeTruthy());
  });

  it("Remove hands the form an empty string", () => {
    const onChange = renderSection("stranger");
    expect(screen.getByTestId("cotag-pick").textContent).toBe("@stranger");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onChange).toHaveBeenLastCalledWith({ cotag_username: "" });
  });

  it("says so when nothing matches", async () => {
    relayGet.mockResolvedValue([]);
    renderSection(null);
    search("nobody");
    await waitFor(() => expect(screen.getByText("No creators found.")).toBeTruthy());
  });

  it("keeps the saved pick when the search fails", async () => {
    relayGet.mockRejectedValue(new Error("502"));
    renderSection("coone");
    search("co");
    await waitFor(() => expect(screen.getByText(/Couldn.t search OnlyFans creators/)).toBeTruthy());
    expect(screen.getByTestId("cotag-pick").textContent).toBe("@coone");
  });

  it("CotagCard saves the stored config with only the pick changed", async () => {
    const config = { persona: "Ella.", model_notes: "note", cotag_tag_videos: false, cotag_username: null };
    relayGet.mockImplementation((path: string) => Promise.resolve(
      path.startsWith("/admin/account-config") ? { account_id: ACC, config } : FOUND));
    relayPut.mockResolvedValue({ account_id: ACC, config: { ...config, cotag_username: "coone" } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CotagCard accountId={ACC} /></QueryClientProvider>);
    await screen.findByLabelText("Search creators");
    expect(screen.getByTestId("cotag-pick").textContent).toBe("No co-creator tag");
    const save = screen.getByRole("button", { name: "Save co-creator tag" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    search("co");
    fireEvent.click(await screen.findByRole("button", { name: /@coone/ }));
    expect(screen.getByTestId("cotag-pick").textContent).toBe("@coone");
    fireEvent.click(save);
    await waitFor(() => expect(relayPut).toHaveBeenCalledTimes(1));
    expect(relayPut.mock.calls[0]).toEqual(["/admin/account-config",
      { account_id: ACC, config: { ...config, cotag_username: "coone" } }]);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Saved."));
  });
});
