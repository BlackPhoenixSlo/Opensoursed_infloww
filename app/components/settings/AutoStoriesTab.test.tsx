/**
 * My Automations > Auto Story (`AutoStoriesTab`) on Infloww's look (page-parity
 * ticket 16). Rendered with `@/lib/relay` mocked over one Creator and one vault
 * folder. What is pinned: the page header (Learn, Edit raw JSON), the five
 * blocks, the Vault clean-up and Enabled options as switches that save, the
 * radio cards, and Delete through a dialog, never `window.confirm`.
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
vi.mock("@/hooks/useVaultMedia", () => ({
  useVaultLists: () => ({ isLoading: false, data: { list: [{ id: 5, name: "Teasers", photosCount: 3 }] } }),
}));
vi.mock("@/components/chat/VaultPicker", () => ({ VaultPicker: () => null }));

import AutoStoriesTab from "@/components/settings/AutoStoriesTab";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const patch = relay.patch as unknown as Mock;
const del = relay.delete as unknown as Mock;

const RULE = {
  id: 7, account_id: "acc-a", kind: "auto_stories", name: "Auto stories", is_enabled: true, every_seconds: null,
  trigger: { daily_at: ["09:00"] }, payload: { folder_id: 5, per_run: 2, hours_to_live: 6, remove_vault_dupe: true },
  quiet_hours: null, created_at: null, last_run: null, next_due_at: null, has_pending_job: false,
};

function mockRules(rules: unknown[]) {
  get.mockImplementation((path: string) =>
    path.startsWith("/admin/automation-rules") ? Promise.resolve({ rules }) : Promise.resolve({}));
}

beforeEach(() => {
  patch.mockResolvedValue({});
  del.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Auto Story (AutoStoriesTab)", () => {
  it("has the page header, the five blocks and Create automation when new", async () => {
    mockRules([]);
    renderWithProviders(<AutoStoriesTab />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Story" })).toBeTruthy();
    expect(within(bar).getByRole("button", { name: "Edit raw JSON" })).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/random photos from a vault folder/);

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent))
      .toEqual(["Source", "When to post (choose one)", "Stories", "Vault clean-up", "Status"]);
    expect(await screen.findByRole("button", { name: "Create automation" })).toBeTruthy();

    const clock = screen.getByRole("radio", { name: "At set times each day" });
    const every = screen.getByRole("radio", { name: "Every few hours" });
    expect(clock).toHaveAttribute("aria-checked", "true");
    fireEvent.click(every);
    expect(every).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("spinbutton", { name: "Every N hours" })).toHaveValue(6);
  });

  it("saves the clean-up and Enabled switches", async () => {
    mockRules([RULE]);
    renderWithProviders(<AutoStoriesTab />);
    const save = await screen.findByRole("button", { name: "Save" });
    const dupe = screen.getByRole("switch", { name: "Remove the re-uploaded copy from the vault" });
    const enabled = screen.getByRole("switch", { name: "Enabled" });
    expect(dupe).toHaveAttribute("aria-checked", "true");
    expect(enabled).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Stories per run:")).toHaveValue(2);

    fireEvent.click(dupe);
    fireEvent.click(enabled);
    fireEvent.click(save);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const [path, body] = patch.mock.calls[0];
    expect(path).toBe("/admin/automation-rules/7");
    expect(body).toMatchObject({ is_enabled: false, payload: { folder_id: 5, remove_vault_dupe: false } });
  });

  it("Delete asks in a dialog, not window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    mockRules([RULE]);
    renderWithProviders(<AutoStoriesTab />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this automation?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/automation-rules/7"));
    expect(confirm).not.toHaveBeenCalled();
  });
});
