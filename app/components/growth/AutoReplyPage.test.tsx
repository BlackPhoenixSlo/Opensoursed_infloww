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
vi.mock("@/hooks/useAccounts", () => ({
  useActiveAccounts: () => accounts.list,
  useAccounts: () => ({ isLoading: false }),
}));

import AutoReplyPage from "@/components/growth/AutoReplyPage";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const put = relay.put as unknown as Mock;

const LISTS = [
  { id: 11, name: "VIP", type: "custom", usersCount: 4 },
  { id: 22, name: "Regulars", type: "custom", usersCount: 9 },
];

function mockReads(opts: {
  config?: Record<string, unknown>; keyAvailable?: boolean; visionAvailable?: boolean;
  style?: Record<string, unknown>; brain?: Record<string, unknown>;
} = {}) {
  get.mockImplementation((path: string) => {
    if (path.startsWith("/admin/autoreply-config")) {
      return Promise.resolve({
        account_id: "acc-a",
        config: { enabled: true, quiet_hours_json: [2, 7], list_ids: [], ...opts.config },
        defaults: {
          enabled: false, silence_min_minutes: 24, step_in_max_minutes: 0,
          folders_enabled: true, list_ids: [], folder_max_spend_cents: null,
          new_fans_enabled: false, new_fan_hours: 72, new_fan_max_spend_cents: 1000,
        },
        llm_key: { provider: "deepseek", available: opts.keyAvailable ?? true },
        ...(opts.visionAvailable === undefined ? {} : {
          vision_key: { provider: "deepinfra", available: opts.visionAvailable },
        }),
      });
    }
    if (path.startsWith("/admin/style-config")) {
      const on = {
        autoreply: true, typos_autoreply: true, nonnative_autoreply: true,
        nonnative_spacing_autoreply: true,
      };
      return Promise.resolve({
        account_id: "acc-a", config: { ...on, ...opts.style }, defaults: on,
      });
    }
    if (path.startsWith("/api/of/v2/lists")) return Promise.resolve({ list: LISTS });
    if (path.startsWith("/admin/account-config") && opts.brain) {
      return Promise.resolve({
        account_id: "acc-a",
        config: { persona: "Ella.", model: null, reasoning_effort: "", ...opts.brain },
        default_model: "deepseek-v4-flash",
        model_options: ["deepseek-v4-flash", "deepseek-v4-pro", "claude-opus-5-5"],
        effort_options: { "deepseek-v4-flash": [], "deepseek-v4-pro": ["low", "medium", "high"], "claude-opus-5-5": [] },
      });
    }
    if (path.startsWith("/admin/ai-key-status")) {
      const missing = opts.keyAvailable === false;
      return Promise.resolve({
        account_id: "acc-a",
        items: [{ kind: "autoreply", provider: "deepseek", available: !missing, last_key_error: null }],
        notices: missing ? [{
          error: "api_key_missing", feature: "Auto-reply", provider: "deepseek",
          fix_url: "/settings/ai-keys",
          message: "Auto-reply can't run: no DeepSeek API key is set.",
          fix: "Add it in Settings › AI keys.",
        }] : [],
      });
    }
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
  put.mockResolvedValue({ account_id: "acc-a", config: {} });
}

async function saved() {
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
  return put.mock.calls[0][1].config;
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  accounts.list = [{ id: "acc-a", nickname: "Creator A", has_session: true }];
  window.history.replaceState(null, "", "/growth/auto-reply");
});
afterEach(cleanup);

describe("AutoReplyPage", () => {
  it("seeds the stored folder pick and saves it with the rest of the blob kept", async () => {
    mockReads({ config: { list_ids: [22] } });
    renderWithProviders(<AutoReplyPage />);

    expect(await screen.findByRole("switch", { name: "Fans in folders" })).toBeChecked();
    expect(await screen.findByRole("checkbox", { name: /Regulars/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /VIP/ })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Auto-reply" })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("checkbox", { name: /VIP/ }));
    await saved();
    const [path, body] = put.mock.calls[0];
    expect(path).toBe("/admin/autoreply-config");
    expect(body.account_id).toBe("acc-a");
    expect(body.config).toMatchObject({
      enabled: true, quiet_hours_json: [2, 7], silence_min_minutes: 24,
      step_in_max_minutes: 0, folders_enabled: true, folder_max_spend_cents: null,
      new_fans_enabled: false,
    });
    expect([...body.config.list_ids].sort()).toEqual([11, 22]);
  });

  it("allows a 0-minute delay and saves randomise as a [d, 2d] range", async () => {
    mockReads({ config: { silence_min_minutes: 7, step_in_max_minutes: 14 } });
    renderWithProviders(<AutoReplyPage />);

    const delay = await screen.findByRole("spinbutton", { name: "Reply delay in minutes" });
    expect(delay).toHaveValue(7);
    const rnd = screen.getByRole("switch", { name: /Randomise/ });
    expect(rnd).toBeChecked();
    expect(screen.getByText("each reply lands between 7 and 14 min")).toBeInTheDocument();

    fireEvent.change(delay, { target: { value: "10" } });
    expect(screen.getByText("each reply lands between 10 and 20 min")).toBeInTheDocument();
    fireEvent.change(delay, { target: { value: "0" } });
    expect(rnd).toBeDisabled();
    const cfg = await saved();
    expect(cfg).toMatchObject({ silence_min_minutes: 0, step_in_max_minutes: 0 });
  });

  it("saves new fans and the folder cap in cents, and refuses both sources off", async () => {
    mockReads();
    renderWithProviders(<AutoReplyPage />);

    expect(await screen.findByText("No folder ticked = every fan.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /Only if he spent less than/ }));
    expect(screen.getByRole("spinbutton", { name: "Folder spend cap in dollars" })).toHaveValue(500);

    fireEvent.click(screen.getByRole("switch", { name: "New fans" }));
    expect(screen.getByRole("spinbutton", { name: "New fan window in hours" })).toHaveValue(72);
    expect(screen.getByRole("spinbutton", { name: "New fan spend cap in dollars" })).toHaveValue(10);

    fireEvent.click(screen.getByRole("switch", { name: "Fans in folders" }));
    fireEvent.click(screen.getByRole("switch", { name: "New fans" }));
    expect(screen.getByText(/nobody gets a reply/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    fireEvent.click(screen.getByRole("switch", { name: "Fans in folders" }));
    fireEvent.click(screen.getByRole("switch", { name: "New fans" }));
    const cfg = await saved();
    expect(cfg).toMatchObject({
      folders_enabled: true, list_ids: [], folder_max_spend_cents: 50_000,
      new_fans_enabled: true, new_fan_hours: 72, new_fan_max_spend_cents: 1000,
    });
  });

  it("a cleared number box stays blank while typing; blur shows the clamped value; Save sends what was typed", async () => {
    mockReads();
    renderWithProviders(<AutoReplyPage />);
    await screen.findByText("No folder ticked = every fan.");
    fireEvent.click(screen.getByRole("switch", { name: "New fans" }));
    const hours = screen.getByRole("spinbutton", { name: "New fan window in hours" });
    fireEvent.change(hours, { target: { value: "" } });
    expect(hours).toHaveValue(null);
    for (const v of ["7", "72", "728", "7289"]) fireEvent.change(hours, { target: { value: v } });
    expect(hours).toHaveValue(7289);
    const cap = screen.getByRole("spinbutton", { name: "New fan spend cap in dollars" });
    fireEvent.change(cap, { target: { value: "" } });
    fireEvent.blur(cap);
    expect(cap).toHaveValue(0);
    const cfg = await saved();
    expect(cfg).toMatchObject({ new_fans_enabled: true, new_fan_hours: 7289, new_fan_max_spend_cents: 0 });
  });

  it("shows the add-a-key notice only when the provider has no key", async () => {
    mockReads({ keyAvailable: false });
    const { unmount } = renderWithProviders(<AutoReplyPage />);
    const link = await screen.findByRole("link", { name: /Settings › AI keys/ });
    expect(link).toHaveAttribute("href", "/settings/ai-keys");
    expect(screen.getByRole("status")).toHaveTextContent("no DeepSeek API key");
    unmount();

    mockReads({ keyAvailable: true });
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: "Fans in folders" });
    expect(screen.queryByRole("link", { name: /Settings › AI keys/ })).toBeNull();
  });

  it("ships both photo options off and saves them", async () => {
    mockReads({ visionAvailable: true });
    renderWithProviders(<AutoReplyPage />);

    const describe = await screen.findByRole("switch", { name: /Describe photos fans send/ });
    const skip = screen.getByRole("switch", { name: /Don't reply to photo-only messages/ });
    expect(describe).not.toBeChecked();
    expect(skip).not.toBeChecked();
    expect(screen.queryByText(/Needs a DeepInfra key/)).toBeNull();

    fireEvent.click(describe);
    fireEvent.click(skip);
    const cfg = await saved();
    expect(cfg).toMatchObject({ describe_photos: true, skip_photo_only: true });
  });

  it("points to Settings → AI keys when there is no DeepInfra key", async () => {
    mockReads({ visionAvailable: false });
    renderWithProviders(<AutoReplyPage />);

    expect(await screen.findByText(/Needs a DeepInfra key/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Add a DeepInfra key/ });
    expect(link).toHaveAttribute("href", "/settings/ai-keys");
  });

  it("shows the human style layers on by default and saves only the touched ones", async () => {
    mockReads({ style: { typos_autoreply: false } });
    renderWithProviders(<AutoReplyPage />);

    const human = await screen.findByRole("switch", { name: /Human style/ });
    const typos = screen.getByRole("switch", { name: /Realistic typos/ });
    const nonnative = screen.getByRole("switch", { name: /^Non-native English/ });
    const spacing = screen.getByRole("switch", { name: /Space before/ });
    expect(human).toBeChecked();
    expect(typos).not.toBeChecked();
    expect(nonnative).toBeChecked();
    expect(spacing).toBeChecked();

    fireEvent.click(nonnative);
    expect(spacing).toBeDisabled();
    fireEvent.click(typos);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    const style = put.mock.calls.find(([path]) => path === "/admin/style-config");
    expect(style?.[1]).toEqual({
      account_id: "acc-a",
      config: { nonnative_autoreply: false, typos_autoreply: true },
    });
  });

  it("keeps a style box toggled while the style save is in flight", async () => {
    mockReads();
    let land!: (v: unknown) => void;
    put.mockImplementation((path: string) => path === "/admin/style-config"
      ? new Promise((res) => { land = res; })
      : Promise.resolve({ account_id: "acc-a", config: {} }));
    renderWithProviders(<AutoReplyPage />);

    fireEvent.click(await screen.findByRole("switch", { name: /Realistic typos/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("switch", { name: /Human style/ }));
    land({ account_id: "acc-a", config: { typos_autoreply: false } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("switch", { name: /Human style/ })).not.toBeChecked();
    expect(screen.queryByText("Saved")).toBeNull();

    put.mockResolvedValue({ account_id: "acc-a", config: {} });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(4));
    const styles = put.mock.calls.filter(([path]) => path === "/admin/style-config");
    expect(styles[1][1].config).toEqual({ autoreply: false });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("does not show Saved over a field edited while the save was in flight", async () => {
    mockReads();
    let land!: (v: unknown) => void;
    put.mockImplementation(() => new Promise((res) => { land = res; }));
    renderWithProviders(<AutoReplyPage />);

    const delay = await screen.findByRole("spinbutton", { name: "Reply delay in minutes" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    fireEvent.change(delay, { target: { value: "9" } });
    land({ account_id: "acc-a", config: {} });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Saved")).toBeNull();

    put.mockResolvedValue({ account_id: "acc-a", config: {} });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(put.mock.calls[1][1].config.silence_min_minutes).toBe(9);
  });

  it("the header switch saves at once: the stored blob with only enabled changed, no Save", async () => {
    mockReads({ config: { silence_min_minutes: 7 } });
    renderWithProviders(<AutoReplyPage />);
    const delay = await screen.findByRole("spinbutton", { name: "Reply delay in minutes" });
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto-reply" })).toBeInTheDocument();
    const sw = within(bar).getByRole("switch", { name: "Auto-reply" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    expect(within(bar).getByText("On")).toBeInTheDocument();

    fireEvent.change(delay, { target: { value: "30" } });
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0]).toEqual(["/admin/autoreply-config", {
      account_id: "acc-a", config: { enabled: false, quiet_hours_json: [2, 7], list_ids: [], silence_min_minutes: 7 },
    }, { cellAccountId: "acc-a" }]);
    expect(within(bar).getByText("Off")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(put.mock.calls[1][1].config).toMatchObject({ enabled: false, silence_min_minutes: 30 });
  });

  it("the header switch builds on the blob as stored now, never the tab's old copy", async () => {
    mockReads({ config: { list_ids: [11] } });
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: "Fans in folders" });
    const base = get.getMockImplementation()!;
    get.mockImplementation((path: string, ...rest: unknown[]) => path.startsWith("/admin/autoreply-config")
      ? Promise.resolve({ account_id: "acc-a", config: { enabled: true, list_ids: [22], new_fans_enabled: true }, defaults: {} })
      : base(path, ...rest));
    fireEvent.click(within(screen.getByRole("banner")).getByRole("switch", { name: "Auto-reply" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1].config).toEqual({ enabled: false, list_ids: [22], new_fans_enabled: true });
  });

  it("the header switch flips back and says why when its PUT fails", async () => {
    mockReads();
    put.mockRejectedValueOnce(new Error("blob refused"));
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: "Fans in folders" });
    const sw = within(screen.getByRole("banner")).getByRole("switch", { name: "Auto-reply" });
    fireEvent.click(sw);
    expect(await screen.findByText(/Couldn.t switch Auto-reply: blob refused/)).toBeInTheDocument();
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("the header switch will not turn on with both sources off", async () => {
    mockReads({ config: { enabled: false, folders_enabled: false, new_fans_enabled: false } });
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: "Fans in folders" });
    expect(within(screen.getByRole("banner")).getByRole("switch", { name: "Auto-reply" })).toBeDisabled();
    expect(screen.getByText(/nobody gets a reply/)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("the header switch judges the stored sources: an unsaved source in the draft does not let it turn on", async () => {
    mockReads({ config: { enabled: false, folders_enabled: false, new_fans_enabled: false } });
    renderWithProviders(<AutoReplyPage />);
    fireEvent.click(await screen.findByRole("switch", { name: "Fans in folders" }));
    const sw = within(screen.getByRole("banner")).getByRole("switch", { name: "Auto-reply" });
    expect(sw).toBeDisabled();
    fireEvent.click(sw);
    expect(put).not.toHaveBeenCalled();
  });

  it("seeds the form from the ?creator= Creator's blob", async () => {
    accounts.list = [
      { id: "acc-a", nickname: "Creator A", has_session: true },
      { id: "acc-b", nickname: "Creator B", has_session: true },
    ];
    window.history.replaceState(null, "", "/growth/auto-reply?creator=acc-b");
    mockReads();
    const base = get.getMockImplementation()!;
    get.mockImplementation((path: string, ...rest: unknown[]) => {
      if (path.startsWith("/admin/autoreply-config") && path.includes("acc-b")) {
        return Promise.resolve({ account_id: "acc-b", config: { enabled: false, silence_min_minutes: 42 }, defaults: {} });
      }
      return base(path, ...rest);
    });
    renderWithProviders(<AutoReplyPage />);
    expect(await screen.findByRole("spinbutton", { name: "Reply delay in minutes" })).toHaveValue(42);
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("Creator B");
    expect(screen.getByRole("switch", { name: "Auto-reply" })).toHaveAttribute("aria-checked", "false");
  });

  it("shows the creator empty state when no Creator has a live session", () => {
    accounts.list = [];
    renderWithProviders(<AutoReplyPage />);
    expect(screen.getByText("No creator with a live session")).toBeInTheDocument();
  });

  it("does not touch the style blob when no human style box changed", async () => {
    mockReads();
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: /Human style/ });
    await saved();
    expect(put.mock.calls.every(([path]) => path !== "/admin/style-config")).toBe(true);
  });

  describe("Model", () => {
    async function pickAndSave(option: string) {
      fireEvent.click(await screen.findByRole("combobox", { name: "Model" }));
      fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(put.mock.calls.some(([p]) => p === "/admin/account-config")).toBe(true));
      return put.mock.calls.find(([p]) => p === "/admin/account-config")![1].config;
    }

    it("shows Default labelled from the server and what runs now", async () => {
      mockReads({ brain: {} });
      renderWithProviders(<AutoReplyPage />);
      expect(await screen.findByRole("combobox", { name: "Model" })).toHaveTextContent("Default (deepseek-v4-flash)");
      expect(screen.getByText(/Answers with/)).toHaveTextContent("Answers with deepseek-v4-flash");
      expect(screen.queryByRole("combobox", { name: "Reasoning effort" })).toBeNull();
    });

    it("saves a pick with the stored brain echoed, and Default back as null", async () => {
      mockReads({ brain: {} });
      renderWithProviders(<AutoReplyPage />);
      expect(await pickAndSave("claude-opus-5-5")).toMatchObject({ model: "claude-opus-5-5", persona: "Ella." });
      expect(screen.getByText(/Answers with/)).toHaveTextContent("claude-opus-5-5");

      cleanup(); put.mockReset(); put.mockResolvedValue({ account_id: "acc-a", config: {} });
      mockReads({ brain: { model: "claude-opus-5-5" } });
      renderWithProviders(<AutoReplyPage />);
      expect(await pickAndSave("Default (deepseek-v4-flash)")).toMatchObject({ model: null, reasoning_effort: null });
    });

    it("offers the effort a model takes", async () => {
      mockReads({ brain: { model: "deepseek-v4-pro", reasoning_effort: "high" } });
      renderWithProviders(<AutoReplyPage />);
      expect(await screen.findByRole("combobox", { name: "Reasoning effort" })).toHaveTextContent("high");
    });

    it("one Save: the brain PUT failing while the blob PUT lands shows the error, never Saved", async () => {
      mockReads({ brain: {} });
      put.mockImplementation((p: string) => p === "/admin/account-config"
        ? Promise.reject(new Error("brain refused"))
        : Promise.resolve({ account_id: "acc-a", config: {} }));
      renderWithProviders(<AutoReplyPage />);
      await pickAndSave("claude-opus-5-5");
      expect(await screen.findByText(/brain refused/)).toBeInTheDocument();
      expect(put.mock.calls.map(([p]) => p)).toEqual(["/admin/account-config", "/admin/autoreply-config"]);
      expect(screen.queryByText("Saved")).toBeNull();
    });

    it("one Save: both PUTs failing shows the blob's error, not the brain's", async () => {
      mockReads({ brain: {} });
      put.mockImplementation((p: string) => Promise.reject(new Error(p === "/admin/account-config" ? "brain refused" : "blob refused")));
      renderWithProviders(<AutoReplyPage />);
      await pickAndSave("claude-opus-5-5");
      expect(await screen.findByText(/blob refused/)).toBeInTheDocument();
      expect(screen.queryByText(/brain refused/)).toBeNull();
    });

    it("save a pick, then pick the opened one back: the second Save sends it (never a false Saved)", async () => {
      const brain: Record<string, unknown> = {};
      mockReads({ brain });
      put.mockImplementation((p: string, body: { config: Record<string, unknown> }) => {
        if (p === "/admin/account-config") Object.assign(brain, body.config);
        return Promise.resolve({ account_id: "acc-a", config: body.config });
      });
      renderWithProviders(<AutoReplyPage />);
      await pickAndSave("claude-opus-5-5");
      expect(await screen.findByText("Saved")).toBeInTheDocument();
      put.mockClear();
      expect(await pickAndSave("Default (deepseek-v4-flash)")).toMatchObject({ model: null });
    });

    it("an untouched model sends no account-config PUT", async () => {
      mockReads({ brain: { model: "claude-opus-5-5" } });
      renderWithProviders(<AutoReplyPage />);
      await screen.findByRole("combobox", { name: "Model" });
      await saved();
      expect(put.mock.calls.every(([p]) => p !== "/admin/account-config")).toBe(true);
    });

    it("sits after Human style, named account-wide; Model info under the Save, with its own", async () => {
      mockReads({ brain: { model_notes: "Name: Mia" }, config: {} });
      renderWithProviders(<AutoReplyPage />);
      await screen.findByRole("combobox", { name: "Model" });
      await screen.findByRole("switch", { name: /Human style/ });
      const heads = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
      expect(heads.slice(-3)).toEqual(["Human style", "AI model (all AI automations)", "Model info"]);
      expect((await screen.findByRole("textbox", { name: "Model info" }) as HTMLTextAreaElement).value).toBe("Name: Mia");
      fireEvent.click(screen.getByRole("button", { name: "Save model info" }));
      await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
      expect(put.mock.calls[0][0]).toBe("/admin/account-config");
      expect(put.mock.calls[0][1].config).toMatchObject({ persona: "Ella.", model_notes: "Name: Mia" });
    });

    it("the two brain Saves never overlap: each waits while the other's PUT is out", async () => {
      mockReads({ brain: { model_notes: "Name: Mia" }, config: {} });
      renderWithProviders(<AutoReplyPage />);
      await screen.findByRole("textbox", { name: "Model info" });
      let land!: () => void;
      put.mockImplementationOnce(() => new Promise((r) => { land = () => r({ account_id: "acc-a", config: {} }); }));
      fireEvent.click(screen.getByRole("button", { name: "Save model info" }));
      await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole("combobox", { name: "Model" }));
      fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "claude-opus-5-5" }));
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
      land();
      await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());

      put.mockImplementationOnce(() => new Promise((r) => { land = () => r({ account_id: "acc-a", config: {} }); }));
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "Save model info" })).toBeDisabled());
      land();
      await waitFor(() => expect(screen.getByRole("button", { name: "Save model info" })).not.toBeDisabled());
    });

    it("no config read: no Model row, the rest still loads", async () => {
      mockReads();
      renderWithProviders(<AutoReplyPage />);
      await screen.findByRole("switch", { name: "Fans in folders" });
      expect(screen.queryByRole("combobox", { name: "Model" })).toBeNull();
      expect(screen.queryByRole("textbox", { name: "Model info" })).toBeNull();
    });
  });
});
