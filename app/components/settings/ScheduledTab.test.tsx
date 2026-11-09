/**
 * ScheduledTab's Cancel asks in an IfModal before the same cancel request; the dialog's Cancel sends nothing.
 * The scheduled-messages hooks and the account list are faked at the module; every name is fake.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

const mutate = vi.fn();
vi.mock("@/hooks/useAccounts", () => ({ useActiveAccounts: () => [{ id: "acc-a", nickname: "Model A" }] }));
vi.mock("@/hooks/useScheduledMessages", () => ({
  useScheduledMessages: () => ({
    isLoading: false, isFetching: false, error: null, queries: [],
    rows: [{ id: 77, __accountId: "acc-a", scheduledDate: "2099-01-01T10:00:00Z", text: "fake queued", userIds: [1] }],
  }),
  useCancelScheduled: () => ({ isPending: false, variables: undefined, mutate }),
}));

import ScheduledTab from "@/components/settings/ScheduledTab";
import { renderWithProviders } from "@/test-utils";

afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

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
