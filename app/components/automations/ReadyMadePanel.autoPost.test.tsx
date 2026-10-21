/**
 * My Automations > Auto Post (/growth/auto-post) is `ReadyMadePanel` pinned to
 * `auto_posts`, on Infloww's legacy list page (page-parity ticket 16). Rendered
 * with `@/lib/relay` mocked. What is pinned: no Card heading (the page header
 * is the heading), one table row per rule with its Status switch, previous runs
 * behind the Name cell's chevron, Delete through a dialog (never
 * `window.confirm`), and the no-creator empty state.
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
const accounts = vi.hoisted(() => ({ list: [{ id: "acc-a", nickname: "Creator A", has_session: true }] }));
vi.mock("@/hooks/useAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/hooks/useAccounts")>();
  return { ...mod, useActiveAccounts: () => accounts.list, useAccounts: () => ({ isLoading: false }) };
});

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const del = relay.delete as unknown as Mock;
const patch = relay.patch as unknown as Mock;
const put = relay.put as unknown as Mock;

const rule = (id: number, name: string, extra: Record<string, unknown> = {}) => ({
  id, account_id: "acc-a", kind: "auto_posts", name, every_seconds: 7200, payload: { posts: [{ text: "hi" }] },
  is_enabled: true, next_due_at: null, has_pending_job: false, last_run: null, ...extra,
});

beforeEach(() => {
  accounts.list = [{ id: "acc-a", nickname: "Creator A", has_session: true }];
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/automation-rules")) {
      return Promise.resolve({ rules: [rule(1, "Morning feed"), rule(2, "Night feed", { is_enabled: false })] });
    }
    if (path.startsWith("/admin/stats/automation-runs")) {
      return Promise.resolve({ runs: [{ id: 9, kind: "auto_posts", account_id: "acc-a", status: "ok",
        started_at: new Date().toISOString(), stats_json: JSON.stringify({ of_post_id: 4242 }) }] });
    }
    return Promise.resolve({});
  });
  del.mockResolvedValue({});
  patch.mockResolvedValue({});
  put.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Post (ReadyMadePanel only=auto_posts)", () => {
  it("has no card heading and lists a table row per rule with its Status switch", async () => {
    renderWithProviders(<ReadyMadePanel only="auto_posts" />);
    expect(screen.getByRole("heading", { level: 1, name: "Auto Post" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "New auto post" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Name", "Status", "Schedule", "Next run", "Last run", "Actions"]);
    await within(table).findByText("Morning feed");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("switch", { name: "Enabled: Morning feed" })).toHaveAttribute("aria-checked", "true");
    expect(within(rows[1]).getByRole("switch", { name: "Enabled: Night feed" })).toHaveAttribute("aria-checked", "false");
    expect(within(rows[0]).getByText("Every 2 hours")).toBeTruthy();
    expect(within(rows[1]).getByText("paused")).toBeTruthy();
    for (const name of ["Run now", "Edit", "Delete"]) expect(within(rows[0]).getByRole("button", { name })).toBeTruthy();
  });

  it("opens previous runs from the Name cell's chevron", async () => {
    renderWithProviders(<ReadyMadePanel only="auto_posts" />);
    const chevron = await screen.findByRole("button", { name: "Previous runs of Morning feed" });
    expect(chevron).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(chevron);
    expect(chevron).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText(/post #4242/)).toBeTruthy();
  });

  it("Delete asks in a dialog, not window.confirm, and Cancel keeps the rule", async () => {
    const confirm = vi.spyOn(window, "confirm");
    renderWithProviders(<ReadyMadePanel only="auto_posts" />);
    await screen.findByText("Morning feed");
    const row = screen.getByText("Morning feed").closest("tr")!;

    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    let dialog = screen.getByRole("dialog", { name: 'Delete "Morning feed"?' });
    expect(dialog).toHaveTextContent("This stops the schedule.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(del).not.toHaveBeenCalled();

    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("dialog", { name: 'Delete "Morning feed"?' });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/automation-rules/1"));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("Edit opens the rule in the editor dialog", async () => {
    renderWithProviders(<ReadyMadePanel only="auto_posts" />);
    await screen.findByText("Morning feed");
    fireEvent.click(within(screen.getByText("Morning feed").closest("tr")!).getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit · Morning feed" });
    expect(within(dialog).getByLabelText("Name (optional):")).toHaveValue("Morning feed");
    expect(within(dialog).getByLabelText("Run every:")).toHaveValue(2);
  });

  it("shows the creator empty state when no Creator has a live session", () => {
    accounts.list = [];
    renderWithProviders(<ReadyMadePanel only="auto_posts" />);
    expect(screen.getByText("No creator with a live session")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New auto post" })).toBeDisabled();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
