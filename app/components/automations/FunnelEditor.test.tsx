/**
 * My Automations > Auto Funnel: `AutoFunnelPage` over `MassFunnelsTab` on
 * Infloww's legacy list page (page-parity ticket 16). Rendered with
 * `@/lib/relay` mocked over one Creator. What is pinned: Learn and "New funnel"
 * in the page header, the "Reply walking" row as a switch that creates the
 * walker rule, the funnels as a table, the editor as a dialog, and Delete
 * through a dialog, never `window.confirm`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return {
    ...mod,
    useActiveAccounts: () => [{ id: "acc-a", nickname: "Creator A", has_session: true }],
    useAccounts: () => ({ isLoading: false }),
  };
});

import AutoFunnelPage from "@/components/automations/AutoFunnelPage";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const del = relay.delete as unknown as Mock;

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/funnels")) {
      return Promise.resolve({ funnels: [
        { id: 1, name: "strokes", description: "the default", opening_message: "hey", step_count: 3 },
      ] });
    }
    if (path.startsWith("/admin/automation-rules")) return Promise.resolve({ rules: [] });
    if (path.startsWith("/admin/ai-key-status")) return Promise.resolve({ account_id: "acc-a", items: [], notices: [] });
    return Promise.resolve({});
  });
  post.mockResolvedValue({});
  del.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Funnel (MassFunnelsTab)", () => {
  it("puts Learn and New funnel in the header and lists funnels in a table", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Funnel" })).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/Funnels are global/);

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Name", "Steps", "Description", "Actions"]);
    const row = (await within(table).findByText("strokes")).closest("tr")!;
    expect(within(row).getByText("3")).toBeTruthy();
    for (const name of ["Media", "Start", "Edit", "Delete"]) expect(within(row).getByRole("button", { name })).toBeTruthy();

    fireEvent.click(within(bar).getByRole("button", { name: "New funnel" }));
    expect(screen.getByRole("dialog", { name: "New funnel" })).toBeTruthy();
  });

  it("Reply walking is a switch that creates the walker rule", async () => {
    renderWithProviders(<AutoFunnelPage />);
    const sw = await screen.findByRole("switch", { name: "Reply walking" });
    await waitFor(() => expect(sw).not.toBeDisabled());
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      "/admin/automation-rules",
      expect.objectContaining({ account_id: "acc-a", kind: "reply_mass_funnel", every_seconds: 120, is_enabled: true }),
    ));
  });

  it("Delete asks in a dialog, not window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    renderWithProviders(<AutoFunnelPage />);
    const row = (await screen.findByText("strokes")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: 'Delete funnel "strokes"?' });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/funnels/1"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(confirm).not.toHaveBeenCalled();
  });
});
