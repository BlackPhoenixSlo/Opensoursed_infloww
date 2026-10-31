/**
 * My Automations > Auto-reply, the page component. Rendered with `@/lib/relay`
 * mocked and a fresh QueryClient over one Creator. What is pinned:
 *
 *  - the stored folder pick seeds "Fans in folders" with that OF list ticked,
 *    and Save sends the stored blob back with only the page's fields changed
 *    (the PUT replaces the whole blob);
 *  - timing: delay 0 is allowed, randomise saves step_in_max = 2 x delay and
 *    reads back from it;
 *  - new fans + the folder cap save as cents; both sources off cannot save;
 *  - no LLM key for the engine's provider (the relay's `/admin/ai-key-status`
 *    notice) shows the AiKeyNotice linking to /settings/ai-keys; a key hides it;
 *  - the two photo options ship off, save as `describe_photos` /
 *    `skip_photo_only`, and a missing DeepInfra key shows its own link;
 *  - the Human style boxes at the bottom render the style blob's `autoreply`
 *    layers (default ON), and Save PUTs only the touched ones to style-config;
 *    a box toggled while that PUT is in flight survives its success, and
 *    "Saved" waits until no edit made during a save is left unsaved;
 *  - the page header (page-parity ticket 16) holds the Auto-reply switch, and
 *    `?creator=` picks the Creator whose blob seeds the form.
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
  style?: Record<string, unknown>;
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

    // Both off: nobody would qualify, so Save is refused.
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
    expect(typos).not.toBeChecked();   // an explicit stored false is honoured
    expect(nonnative).toBeChecked();
    expect(spacing).toBeChecked();

    fireEvent.click(nonnative);
    expect(spacing).toBeDisabled();    // only applies while Non-native is on
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
    fireEvent.click(screen.getByRole("switch", { name: /Human style/ }));   // while the PUT is out
    land({ account_id: "acc-a", config: { typos_autoreply: false } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("switch", { name: /Human style/ })).not.toBeChecked();
    expect(screen.queryByText("Saved")).toBeNull();   // the in-flight toggle is not saved yet

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
    fireEvent.change(delay, { target: { value: "9" } });   // while the PUT is out
    land({ account_id: "acc-a", config: {} });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).not.toBeDisabled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Saved")).toBeNull();

    put.mockResolvedValue({ account_id: "acc-a", config: {} });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(put.mock.calls[1][1].config.silence_min_minutes).toBe(9);
  });

  it("toggles Auto-reply from the page header and saves it", async () => {
    mockReads();
    renderWithProviders(<AutoReplyPage />);
    await screen.findByRole("switch", { name: "Fans in folders" });
    const bar = screen.getByRole("banner");
    expect(within(bar).getByRole("heading", { level: 1, name: "Auto-reply" })).toBeInTheDocument();
    const sw = within(bar).getByRole("switch", { name: "Auto-reply" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
    const cfg = await saved();
    expect(cfg.enabled).toBe(false);
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
});
