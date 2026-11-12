/**
 * PreferencesTab — the Your Preferences Panel (docs/spec/settings-tabs/phase-01-account-preferences.md).
 *
 * Rendered with the relay mocked at `fetch` by URL: the stub serves the
 * `preferences` Settings blob, so every save assertion is an assertion about
 * the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import PreferencesTab from "@/components/settings/PreferencesTab";

type Call = { method: string; url: string; body: unknown };

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/settings/preferences answers. */
let getReply: () => Response;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");

beforeEach(() => {
  localStorage.clear();
  getReply = () => jsonRes({ tab: "preferences", config: {} });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/admin/settings/preferences" && method === "GET") return getReply();
    if (url === "/admin/settings/preferences" && method === "PUT") {
      return jsonRes({ tab: "preferences", config: JSON.parse(String(init?.body)) });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const save = () => screen.getByRole("button", { name: /save/i });
/** The labelled select's option texts: open its listbox with Enter, read it, close it with Escape. */
const optionTexts = (label: string) => {
  const select = screen.getByLabelText(label);
  fireEvent.keyDown(select, { key: "Enter" });
  const texts = within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent);
  fireEvent.keyDown(screen.queryByRole("textbox", { name: "Search" }) ?? select, { key: "Escape" });
  return texts;
};
/** Open the labelled select with Enter and pick the option named `name`. */
const pick = (label: string, name: string) => {
  fireEvent.keyDown(screen.getByLabelText(label), { key: "Enter" });
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name }));
};

describe("PreferencesTab", () => {
  it("renders the three labelled selects with one help line per zone, no Language and no not-applied note", () => {
    renderWithProviders(<PreferencesTab />);
    for (const label of ["Report time zone", "Regular time zone", "Week start day"]) {
      expect(screen.getByRole("combobox", { name: label })).toBe(screen.getByLabelText(label));
    }
    expect(screen.getByRole("combobox", { name: "Report time zone" })).toHaveAccessibleDescription("Creator and fan reports");
    expect(screen.getByRole("combobox", { name: "Regular time zone" })).toHaveAccessibleDescription("Top bar clock and Employees' monthly figures");
    expect(screen.queryByLabelText("Language")).toBeNull();
    expect(screen.queryByText("Language Settings")).toBeNull();
    expect(screen.queryByText(/not applied yet/)).toBeNull();
    expect(screen.getByText("The switches below apply at once on this browser; they need no Save.")).toBeInTheDocument();
  });

  it("offers every zone in Intl.supportedValuesOf(\"timeZone\") in both zone selects, and a filter narrows them", () => {
    renderWithProviders(<PreferencesTab />);
    const zones = Intl.supportedValuesOf("timeZone");
    for (const label of ["Report time zone", "Regular time zone"]) {
      expect(optionTexts(label)).toEqual(expect.arrayContaining(zones));
    }
    fireEvent.keyDown(screen.getByLabelText("Regular time zone"), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: "tokyo" } });
    expect(within(screen.getByRole("listbox")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Asia/Tokyo"]);
  });

  it("offers exactly Monday and Sunday", () => {
    renderWithProviders(<PreferencesTab />);
    expect(optionTexts("Week start day")).toEqual(["Monday", "Sunday"]);
  });

  it("with an empty stored blob, choosing Sunday and Save sends exactly the four keys", async () => {
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(save()).toBeEnabled());
    expect(save().closest('[data-settings="panel-header"]')).not.toBeNull();
    pick("Week start day", "Sunday");
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(puts()[0]).toEqual({
      method: "PUT",
      url: "/admin/settings/preferences",
      body: { report_tz: zone, tz: zone, week_start: "sunday", language: "en" },
    });
  });

  it("pre-fills the selects from a stored blob", async () => {
    getReply = () => jsonRes({
      tab: "preferences",
      config: { report_tz: "Asia/Tokyo", tz: "America/New_York", week_start: "sunday", language: "es" },
    });
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(screen.getByLabelText("Report time zone")).toHaveTextContent("Asia/Tokyo"));
    expect(screen.getByLabelText("Regular time zone")).toHaveTextContent("America/New_York");
    expect(screen.getByLabelText("Week start day")).toHaveTextContent("Sunday");
  });

  it("keeps stored keys it does not show (Language included) and a zone outside the Intl list when it saves", async () => {
    const stored = {
      report_tz: "Mars/Olympus_Mons", tz: "Asia/Tokyo", week_start: "monday", language: "es", extra: 1,
    };
    getReply = () => jsonRes({ tab: "preferences", config: stored });
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(screen.getByLabelText("Report time zone")).toHaveTextContent("Mars/Olympus_Mons"));
    expect(optionTexts("Report time zone")).toContain("Mars/Olympus_Mons");
    pick("Week start day", "Sunday");
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...stored, week_start: "sunday" });
  });

  it("a failed GET keeps Save disabled and sends no PUT (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(screen.getByText(/never loaded/)).toBeInTheDocument());
    expect(save()).toBeDisabled();
    pick("Week start day", "Sunday");
    fireEvent.click(save());
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
  });

  it("Disable free trial popup: off by default, switched on it saves hide_trial_popup true", async () => {
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(save()).toBeEnabled());
    const sw = screen.getByRole("switch", { name: "Disable free trial popup" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(save());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toMatchObject({ hide_trial_popup: true });
  });

  it("Disable free trial popup pre-fills from a stored blob", async () => {
    getReply = () => jsonRes({ tab: "preferences", config: { hide_trial_popup: true } });
    renderWithProviders(<PreferencesTab />);
    await waitFor(() => expect(screen.getByRole("switch", { name: "Disable free trial popup" }))
      .toHaveAttribute("aria-checked", "true"));
  });
});
