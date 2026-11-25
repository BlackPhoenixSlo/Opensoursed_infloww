import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));

import { jsonRes, renderWithProviders } from "@/test-utils";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { TimeZoneLabel } from "@/components/shell/TopBar";
import PreferencesTab from "@/components/settings/PreferencesTab";

const APPLIED = "/admin/settings/applied";

let fetchMock: ReturnType<typeof vi.fn>;
let storedTz: string | null;

const appliedReply = () => ({
  preferences: { tz: storedTz, report_tz: null, week_start: "monday" },
  messaging: { ai_translation: true },
  permissions: { enforced: false, pages: null, scope: "all" },
});

const appliedCalls = () => fetchMock.mock.calls.filter(([url]) => String(url) === APPLIED);

beforeEach(() => {
  localStorage.clear();
  storedTz = null;
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-07-15T12:00:00Z"));
  vi.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(-120);
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === APPLIED && method === "GET") return jsonRes(appliedReply());
    if (url === "/admin/settings/preferences" && method === "GET") {
      return jsonRes({ tab: "preferences", config: storedTz ? { tz: storedTz } : {} });
    }
    if (url === "/admin/settings/preferences" && method === "PUT") {
      const config = JSON.parse(String(init?.body));
      storedTz = config.tz ?? null;
      return jsonRes({ tab: "preferences", config });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
  localStorage.clear();
});

const label = () => screen.getByTitle("Your time zone");

describe("TimeZoneLabel", () => {
  it("shows the stored regular time zone's offset", async () => {
    storedTz = "Asia/Tokyo";
    renderWithProviders(<ScopeProvider><TimeZoneLabel /></ScopeProvider>);
    await waitFor(() => expect(label()).toHaveTextContent("UTC+09:00"));
  });

  it("shows the browser's offset when the Agency stored no time zone", async () => {
    renderWithProviders(<ScopeProvider><TimeZoneLabel /></ScopeProvider>);
    await waitFor(() => expect(appliedCalls()).toHaveLength(1));
    expect(label()).toHaveTextContent("UTC+02:00");
  });

  it("names the Creator in scope to the read, so a two-Agency chatter gets that Creator's Agency", async () => {
    localStorage.setItem("chatterly:scope", "model:1000001");
    renderWithProviders(<ScopeProvider><TimeZoneLabel /></ScopeProvider>);
    await waitFor(() => {
      const last = appliedCalls().at(-1);
      expect(new Headers(last?.[1]?.headers).get("X-Account-Id")).toBe("1000001");
    });
  });

  it("saving Your Preferences refetches the Applied settings and updates the label with no reload", async () => {
    renderWithProviders(
      <ScopeProvider>
        <TimeZoneLabel />
        <PreferencesTab />
      </ScopeProvider>,
    );
    await waitFor(() => expect(appliedCalls()).toHaveLength(1));
    expect(label()).toHaveTextContent("UTC+02:00");
    const save = screen.getByRole("button", { name: /save/i });
    await waitFor(() => expect(save).toBeEnabled());

    fireEvent.keyDown(screen.getByLabelText("Regular time zone"), { key: "Enter" });
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Asia/Shanghai" }));
    fireEvent.click(save);

    await waitFor(() => expect(label()).toHaveTextContent("UTC+08:00"));
    expect(appliedCalls()).toHaveLength(2);
  });
});
