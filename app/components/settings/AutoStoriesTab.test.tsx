/**
 * My Automations > Auto Story (`AutoStoriesTab`) on Infloww's look (page-parity
 * ticket 16). Rendered with `@/lib/relay` mocked over one Creator and one vault
 * folder. What is pinned: the page header (Learn, the On / Off pill + switch,
 * the More actions menu holding Run now / Edit raw JSON / Delete, the primary
 * Save), the four blocks, the Vault clean-up switch saving with the form, the
 * header switch saving at once once a rule exists (and riding the create
 * before), the radio cards on the theme's selected tint, and Delete through a
 * dialog, never `window.confirm`.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

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
import { AgentBridgeProvider, createAgentBridge } from "@/components/assistant/agentBridge";
import { DO_FLOWS } from "@/components/assistant/doFlows";
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

/** Waits until the rule's values seeded the form (Stories per run 2, not the default 1). */
const seeded = () => waitFor(() => expect(screen.getByLabelText("Stories per run")).toHaveValue(2));

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
  it("has the page header, the four blocks and Save when new", async () => {
    mockRules([]);
    renderWithProviders(<AutoStoriesTab />);
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto Story" })).toBeTruthy();
    fireEvent.click(within(bar).getByRole("button", { name: "Learn" }));
    expect(screen.getByRole("note")).toHaveTextContent(/random photos from a vault folder/);
    expect(await within(bar).findByText("Not saved")).toBeTruthy();
    expect(within(bar).getByRole("button", { name: "Save" })).toBeTruthy();

    // Raw JSON stays reachable (fast imports), in the menu; disabled until the rule exists.
    fireEvent.click(within(bar).getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Edit raw JSON" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Run now" })).toBeDisabled();

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent))
      .toEqual(["Source", "When to post (choose one)", "Stories", "Vault clean-up"]);

    const clock = screen.getByRole("radio", { name: "At set times each day" });
    const every = screen.getByRole("radio", { name: "Every few hours" });
    expect(clock).toHaveAttribute("aria-checked", "true");
    expect(clock.className).toContain("bg-selected/40");   // the theme token, readable light and dark
    expect(clock.className).not.toMatch(/#[0-9a-f]{3,6}/i);
    fireEvent.click(every);
    expect(every).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("spinbutton", { name: "Every N hours" })).toHaveValue(6);
  });

  it("with no rule the header switch only rides the create", async () => {
    mockRules([]);
    const post = relay.post as unknown as Mock;
    post.mockResolvedValue({ ...RULE, is_enabled: false });
    renderWithProviders(<AutoStoriesTab />);
    const sw = within(screen.getByRole("banner")).getByRole("switch", { name: "Auto Story" });
    await waitFor(() => expect(sw).not.toBeDisabled());
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(patch).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("combobox", { name: "Vault folder" }));
    fireEvent.click(screen.getByRole("option", { name: /Teasers/ }));
    fireEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1]).toMatchObject({ kind: "auto_stories", is_enabled: false, payload: { folder_id: 5 } });
  });

  it("the header switch saves at once (is_enabled alone); clean-up saves with the form", async () => {
    mockRules([RULE]);
    renderWithProviders(<AutoStoriesTab />);
    const bar = screen.getByRole("banner");
    const save = within(bar).getByRole("button", { name: "Save" });
    await seeded();
    const sw = within(bar).getByRole("switch", { name: "Auto Story" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    expect(within(bar).getByText("On")).toBeTruthy();

    fireEvent.click(sw);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(patch.mock.calls[0]).toEqual(["/admin/automation-rules/7", { is_enabled: false }]);
    await waitFor(() => expect(within(bar).getByText("Off")).toBeTruthy());

    const dupe = screen.getByRole("switch", { name: "Remove the re-uploaded copy from the vault" });
    expect(dupe).toHaveAttribute("aria-checked", "true");
    fireEvent.click(dupe);
    expect(patch).toHaveBeenCalledTimes(1);   // not saved until Save
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    const [path, body] = patch.mock.calls[1];
    expect(path).toBe("/admin/automation-rules/7");
    expect(body).toMatchObject({ is_enabled: false, payload: { folder_id: 5, remove_vault_dupe: false } });
  });

  it("a failed switch flips back and says why", async () => {
    mockRules([RULE]);
    patch.mockRejectedValueOnce(new Error("rule refused"));
    renderWithProviders(<AutoStoriesTab />);
    await seeded();
    const sw = within(screen.getByRole("banner")).getByRole("switch", { name: "Auto Story" });
    fireEvent.click(sw);
    expect(await screen.findByText(/Couldn.t switch Auto Story: rule refused/)).toBeTruthy();
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("Edit raw JSON opens from the More actions menu once the rule exists", async () => {
    mockRules([RULE]);
    renderWithProviders(<AutoStoriesTab />);
    await seeded();
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Edit raw JSON" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/rule #7/);
  });

  it("Delete asks in a dialog, not window.confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    mockRules([RULE]);
    renderWithProviders(<AutoStoriesTab />);
    await seeded();
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this automation?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/automation-rules/7"));
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("Auto Story on the help bot's agent bridge (D13)", () => {
  const SLOTS = {
    folder: { id: "5", name: "Teasers", photos: 3 }, mode: "clock" as const, times: ["09:00", "20:00"], every_hours: 6,
    per_run: 2, hours_to_live: 12, max_runs: 30,
  };
  const signal = () => new AbortController().signal;

  it("registers as a NEW, clean editor; the played steps save a new rule OFF through Save's own POST", async () => {
    mockRules([]);
    const post = relay.post as unknown as Mock;
    post.mockResolvedValue({ ...RULE, is_enabled: false });
    const bridge = createAgentBridge();
    renderWithProviders(<AgentBridgeProvider bridge={bridge}><AutoStoriesTab /></AgentBridgeProvider>);
    const editor = await bridge.waitFor(() => bridge.anyEditor("auto_stories", "acc-a"), 2000, signal());
    expect(editor.isNew).toBe(true);
    expect(bridge.hasEditor()).toBe(false); // a clean page never blocks a run
    const steps = DO_FLOWS.auto_story.toActions(SLOTS);
    for (const id of ["story-folder", "story-mode-clock", "story-mode-interval", "story-time-0", "story-per-run", "story-ttl",
      "story-max-runs", "story-enabled", "story-save"]) {
      expect(document.getElementById(id), id).toBeTruthy();
    }
    for (const step of steps) if (typeof step.action !== "string") act(() => editor.dispatch(step.action as never));
    expect(bridge.hasEditor()).toBe(true);
    expect(screen.getByLabelText("Time 2")).toHaveValue("20:00");
    let res: Awaited<ReturnType<typeof editor.save>> | undefined;
    await act(async () => { res = await editor.save(); });
    expect(res).toEqual({ ok: true });
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0][1]).toMatchObject({
      kind: "auto_stories", is_enabled: false,
      trigger: { daily_at: ["09:00", "20:00"], max_runs: 30 },
      payload: { folder_id: 5, per_run: 2, hours_to_live: 12 },
    });
  });

  it("with a rule already there it is not new and its save refuses (one per account)", async () => {
    mockRules([RULE]);
    const post = relay.post as unknown as Mock;
    const bridge = createAgentBridge();
    renderWithProviders(<AgentBridgeProvider bridge={bridge}><AutoStoriesTab /></AgentBridgeProvider>);
    await seeded();
    const editor = await bridge.waitFor(() => bridge.anyEditor("auto_stories", "acc-a"), 2000, signal());
    expect(editor.isNew).toBe(false);
    expect(bridge.editor("auto_stories", "acc-a")).toBeNull();
    let res: Awaited<ReturnType<typeof editor.save>> | undefined;
    await act(async () => { res = await editor.save(); });
    expect(res).toMatchObject({ ok: false, reason: expect.stringContaining("already set up") });
    expect(post).not.toHaveBeenCalled();
  });
});
