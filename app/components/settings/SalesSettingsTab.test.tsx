/**
 * SalesSettingsTab — the Sales Settings Panel (docs/spec/settings-tabs/phase-03-roles-sales.md).
 *
 * Rendered with the relay mocked at `fetch` by URL: the stub serves the `sales` Settings blob, so every
 * save assertion is an assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import SalesSettingsTab from "@/components/settings/SalesSettingsTab";

type Call = { method: string; url: string; body: unknown };

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/settings/sales answers. */
let getReply: () => Response;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");

/** The spec's `SalesBlob` with every default: what an empty stored blob saves. */
const DEFAULTS = {
  exclude_welcome: false,
  exclude_of_fee: false,
  multi_employee_shift: false,
  attribution: { messages: "shift", posts_tips: "shift", subscriptions_chatter_opt_in: false },
};

beforeEach(() => {
  getReply = () => jsonRes({ tab: "sales", config: {} });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/admin/settings/sales" && method === "GET") return getReply();
    if (url === "/admin/settings/sales" && method === "PUT") {
      return jsonRes({ tab: "sales", config: JSON.parse(String(init?.body)) });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const save = () => screen.getByRole("button", { name: /save/i });
const group = (name: string) => screen.getByRole("radiogroup", { name });
/** The radios' label texts in `name`'s group, every one or only the checked ones. */
const radioNames = (name: string, onlyChecked = false) =>
  within(group(name)).getAllByRole("radio")
    .filter((r) => !onlyChecked || (r as HTMLInputElement).checked)
    .map((r) => r.closest("label")?.textContent);
const checkedIn = (name: string) => radioNames(name, true);
const switches = () => screen.getAllByRole("switch").map((s) => [s.getAttribute("aria-label"), s.getAttribute("aria-checked")]);

async function mountLoaded() {
  renderWithProviders(<SalesSettingsTab />);
  await waitFor(() => expect(save()).toBeEnabled());
}

describe("SalesSettingsTab", () => {
  it("shows the three toggles, the radio matrix 3 / 2 / opt-in, no not-applied note and no Learn more", () => {
    renderWithProviders(<SalesSettingsTab />);
    expect(screen.getByRole("heading", { name: "Sales Settings" })).toBeInTheDocument();
    expect(switches().map(([label]) => label)).toEqual([
      "Exclude welcome messages", "Exclude the 20% OnlyFans fee", "Multiple employees per shift",
    ]);
    expect(screen.getByText("Earnings types and attribution rules")).toBeInTheDocument();
    expect(radioNames("Messages")).toEqual(["Shift schedule", "Message sender", "Converters"]);
    expect(radioNames("Posts and Tips")).toEqual(["Shift schedule", "Converters"]);
    expect(screen.getAllByRole("radio")).toHaveLength(5);
    expect(screen.getByText("Subscriptions, Streams & Referrals")).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox").map((c) => c.closest("label")?.textContent)).toEqual(["Opt in to chatters"]);
    // Every field is applied (phase-04 spec, story 55): no "not applied yet" note in any wording.
    expect(screen.queryByText(/not applied yet|is applied yet/i)).toBeNull();
    expect(screen.queryByText(/saved for your organization/i)).toBeNull();
    expect(screen.queryByText(/learn more/i)).toBeNull();
  });

  it("says under the radios that Shift schedule credits sales only while Time tracking is on", () => {
    renderWithProviders(<SalesSettingsTab />);
    const line = screen.getByText("Shift schedule credits sales only while Time tracking is on.");
    // Under the radios: after the last attribution control (the opt-in checkbox) in document order.
    const optIn = screen.getByRole("checkbox", { name: "Opt in to chatters" });
    expect(optIn.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Save sits in the Panel header row (Infloww's edit-btn-wrap), not after the body.
    expect(save().closest('[data-settings="panel-header"]')).not.toBeNull();
  });

  it("with an empty stored blob, every toggle is off, both radios are Shift schedule, and Save sends the defaults", async () => {
    await mountLoaded();
    expect(switches().map(([, on]) => on)).toEqual(["false", "false", "false"]);
    expect(checkedIn("Messages")).toEqual(["Shift schedule"]);
    expect(checkedIn("Posts and Tips")).toEqual(["Shift schedule"]);
    expect(screen.getByRole("checkbox", { name: "Opt in to chatters" })).not.toBeChecked();
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({ method: "PUT", url: "/admin/settings/sales", body: DEFAULTS });
  });

  it.each([
    ["Exclude welcome messages", "exclude_welcome"],
    ["Exclude the 20% OnlyFans fee", "exclude_of_fee"],
    ["Multiple employees per shift", "multi_employee_shift"],
  ])("the %s toggle flips and Save carries only its key as true", async (label, key) => {
    await mountLoaded();
    const toggle = screen.getByRole("switch", { name: label });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...DEFAULTS, [key]: true });
  });

  it("clicking Message sender then Save sends one PUT carrying every key with attribution.messages sender", async () => {
    await mountLoaded();
    fireEvent.click(screen.getByRole("radio", { name: "Message sender" }));
    expect(checkedIn("Messages")).toEqual(["Message sender"]);
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({
      method: "PUT",
      url: "/admin/settings/sales",
      body: { ...DEFAULTS, attribution: { ...DEFAULTS.attribution, messages: "sender" } },
    });
  });

  it("Posts and Tips Converters and the chatter opt-in are carried by Save", async () => {
    await mountLoaded();
    fireEvent.click(within(group("Posts and Tips")).getByRole("radio", { name: "Converters" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Opt in to chatters" }));
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      ...DEFAULTS,
      attribution: { messages: "shift", posts_tips: "converters", subscriptions_chatter_opt_in: true },
    });
  });

  it("pre-fills a stored blob and keeps a stored unknown key when it saves", async () => {
    const stored = {
      exclude_welcome: false,
      exclude_of_fee: true,
      multi_employee_shift: false,
      attribution: { messages: "converters", posts_tips: "converters", subscriptions_chatter_opt_in: true },
      legacy_key: 7,
    };
    getReply = () => jsonRes({ tab: "sales", config: stored });
    await mountLoaded();
    expect(switches().map(([, on]) => on)).toEqual(["false", "true", "false"]);
    expect(checkedIn("Messages")).toEqual(["Converters"]);
    expect(checkedIn("Posts and Tips")).toEqual(["Converters"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "Opt in to chatters" }));
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      ...stored,
      attribution: { ...stored.attribution, subscriptions_chatter_opt_in: false },
    });
  });

  it("a stored partial attribution shows the missing rules at their defaults and Save sends every key", async () => {
    getReply = () => jsonRes({ tab: "sales", config: { attribution: { messages: "sender" } } });
    await mountLoaded();
    expect(checkedIn("Messages")).toEqual(["Message sender"]);
    expect(checkedIn("Posts and Tips")).toEqual(["Shift schedule"]);
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      exclude_welcome: false,
      exclude_of_fee: false,
      multi_employee_shift: false,
      attribution: { messages: "sender", posts_tips: "shift", subscriptions_chatter_opt_in: false },
    });
  });

  it("a backdated save is sent with its effective time and names its reach; a time later than now is refused", async () => {
    getReply = () => jsonRes({ tab: "sales", config: {}, history: [
      { effective_from: "2026-05-07T00:00:00Z", saved_at: "2026-05-08T00:00:00Z", in_effect: true },
      { effective_from: null, saved_at: "2026-04-01T00:00:00Z", in_effect: false },
    ] });
    const served = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => (
      url.startsWith("/admin/settings/sales?") ? jsonRes({ tab: "sales", config: {} }) : served(url, init)));
    await mountLoaded();
    const history = within(screen.getByRole("list", { name: "Settings history" })).getAllByRole("listitem");
    expect(history.map((li) => li.textContent)).toEqual([
      expect.stringMatching(/^Effective as of .*In effect$/), expect.stringMatching(/^Effective as of the start · saved /),
    ]);
    const field = screen.getByLabelText("Effective date");

    fireEvent.change(field, { target: { value: "2999-01-01T00:00" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The effective time start later than the current time, please reset it.");
    expect(screen.queryByRole("note")).toBeNull();

    // 5 May is before the version of 7 May, which bounds what the save reaches.
    fireEvent.change(field, { target: { value: "2026-05-05T00:00" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("note")).toHaveTextContent(/will be recomputed/);
    expect(screen.getByRole("note")).not.toHaveTextContent("until now");
    fireEvent.click(save());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].url).toBe(
      `/admin/settings/sales?effective_from=${encodeURIComponent(new Date("2026-05-05T00:00").toISOString())}`);
  });

  it("a failed GET keeps Save disabled and sends no PUT (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    renderWithProviders(<SalesSettingsTab />);
    await waitFor(() => expect(screen.getByText(/never loaded/)).toBeInTheDocument());
    expect(save()).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Message sender" }));
    fireEvent.click(save());
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
  });
});
