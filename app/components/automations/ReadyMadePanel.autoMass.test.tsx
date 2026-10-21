/**
 * My Automations > Auto Mass (/growth/auto-mass) is `ReadyMadePanel` pinned to
 * the `mass_premade` kind. Rendered with `@/lib/relay` mocked over one Creator.
 * What is pinned: the page header (title, the blurb as Learn's popover), no tab
 * strip, only `mass_premade` rules listed, and the header's "New auto mass"
 * opening the editor dialog for that kind.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

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

import ReadyMadePanel from "@/components/automations/ReadyMadePanel";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;

const rule = (id: number, kind: string, name: string) => ({
  id, account_id: "acc-a", kind, name, every_seconds: 86400, payload: { messages: [{ text: "hi" }] },
  is_enabled: true, next_due_at: null, has_pending_job: false, last_run: null,
});

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/automation-rules")) {
      return Promise.resolve({ rules: [rule(1, "mass_premade", "Evening tease"), rule(2, "auto_posts", "Feed")] });
    }
    if (path.startsWith("/admin/stats/automation-runs")) return Promise.resolve({ runs: [] });
    return Promise.resolve({});
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Mass (ReadyMadePanel only=mass_premade)", () => {
  it("is the Auto Mass page: header, Learn's blurb, no tab strip, only mass_premade rules", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Mass" })).toBeTruthy();
    expect(within(bar).getByRole("combobox", { name: "Creator" })).toHaveTextContent("Creator A");
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/same OF mass message path as Smart Messages/);

    expect(await screen.findByText("Evening tease")).toBeTruthy();
    expect(screen.queryByText("Feed")).toBeNull();
    expect(screen.queryByRole("button", { name: /Mass Premade/ })).toBeNull();
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
  });

  it("the header's New auto mass opens the auto mass message editor dialog", async () => {
    renderWithProviders(<ReadyMadePanel only="mass_premade" />);
    await screen.findByText("Evening tease");
    fireEvent.click(screen.getByRole("button", { name: "New auto mass" }));
    const dialog = screen.getByRole("dialog", { name: "New auto mass message" });
    expect(within(dialog).getByText("Messages:")).toBeTruthy();
    expect(within(dialog).getByRole("switch", { name: "Enabled" })).toHaveAttribute("aria-checked", "true");
    expect(within(dialog).getByRole("combobox", { name: "Interval unit" })).toHaveTextContent("hours");
  });
});
