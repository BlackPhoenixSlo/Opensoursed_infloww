/**
 * ScheduledTab's Cancel asks in an IfModal before the same cancel request; the dialog's Cancel sends nothing.
 * The list is a table with the house empty state, and its help line links to Auto Mass only where the role may
 * open it. The scheduled-messages hooks, the account list and the granted pages are faked at the module; every
 * name is fake.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

const mutate = vi.fn();
const QUEUED = [{ id: 77, __accountId: "acc-a", scheduledDate: "2099-01-01T10:00:00Z", text: "fake queued", userIds: [1] }];
const state = vi.hoisted(() => ({ rows: [] as unknown[], granted: null as Set<string> | null }));
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "acc-a", nickname: "Model A" }] }));
vi.mock("@/hooks/useScheduledMessages", () => ({
  useScheduledMessages: () => ({ isLoading: false, isFetching: false, error: null, queries: [], rows: state.rows }),
  useCancelScheduled: () => ({ isPending: false, variables: undefined, mutate }),
}));
vi.mock("@/components/shell/useGrantedPages", () => ({ useGrantedPages: () => state.granted }));

import ScheduledTab from "@/components/settings/ScheduledTab";
import { renderWithProviders } from "@/test-utils";

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); state.rows = QUEUED; state.granted = null; });
state.rows = QUEUED;

describe("ScheduledTab Cancel", () => {
  it("asks first; the dialog's Cancel sends nothing, Cancel send sends the one cancel", async () => {
    vi.spyOn(window, "confirm").mockImplementation(() => { throw new Error("window.confirm"); });
    renderWithProviders(<ScheduledTab />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    let ask = await screen.findByRole("dialog", { name: "Cancel this scheduled send?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    ask = await screen.findByRole("dialog", { name: "Cancel this scheduled send?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Cancel send" }));
    await vi.waitFor(() => expect(mutate).toHaveBeenCalledWith({ id: 77, accountId: "acc-a" }));
  });
});

describe("ScheduledTab table", () => {
  it("lists a send as a table row under the columns", () => {
    renderWithProviders(<ScheduledTab />);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(
      ["Scheduled for", "Creator", "Audience", "Message", "Attachment / Price", "Actions"]);
    const row = screen.getAllByRole("row")[1];
    const cells = within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(1, 5)).toEqual(["Model A", "Direct to 1 fan", "fake queued", "--"]);
  });

  it("shows the empty state when nothing is queued", () => {
    state.rows = [];
    renderWithProviders(<ScheduledTab />);
    expect(screen.getByText("Nothing queued.").closest("[data-empty-state]")).not.toBeNull();
  });

  it.each([
    ["every page granted", null, true],
    ["Auto Mass granted", new Set(["/growth/auto-mass"]), true],
    ["Auto Mass not granted", new Set(["/messages-pro"]), false],
  ])("links to Auto Mass for repeats: %s", (_name, granted, shown) => {
    state.granted = granted;
    renderWithProviders(<ScheduledTab />);
    const link = screen.queryByRole("link", { name: /Auto Mass/ });
    expect(!!link).toBe(shown);
    if (link) expect(link).toHaveAttribute("href", "/growth/auto-mass");
  });
});
