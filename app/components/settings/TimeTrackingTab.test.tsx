/**
 * TimeTrackingTab — the Time tracking Panel (docs/spec/settings-tabs/phase-04-time-tracking-messaging.md).
 *
 * Rendered with the relay mocked at `fetch` by URL: the stub serves the `time-tracking` Settings blob and the
 * `roles` blob (the role list's custom roles), so every save assertion is an assertion about the wire.
 *
 * Rewritten for w4-a: the Auto clock out copy is Infloww's ("Users will be automatically clocked out after …"), a
 * never-saved blob defaults to 10 minutes, and every save carries `role_ids`, the new "Enable clock in and clock
 * out for" list.
 *
 * w5-a, as live Infloww: the built-in roles are Owner, Admin, Team Leader, Chatter and Creator, a never-saved list is
 * all unticked, and the minutes cap at 999.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import TimeTrackingTab from "@/components/settings/TimeTrackingTab";

type Call = { method: string; url: string; body: unknown };

const URL = "/admin/settings/time-tracking";
const ROLES_URL = "/admin/settings/roles";
/** The stored blob: enabled on, reminder off, so a swapped key cannot pass; Night shift ticked, Admin not. */
const STORED = { enabled: true, auto_clock_out_minutes: 45, clock_in_reminder: false, role_ids: ["role-chat"] };
/** One custom role after the built-in Owner and Admin. */
const ROLES = { roles: [{ id: "role-chat", name: "Night shift" }], assignments: {} };
const ERROR = "Enter 1 to 999 minutes.";

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET answers. */
let getReply: () => Response;
/** What PUT answers, given the body it was sent. */
let putReply: (body: unknown) => Response;
/** What the roles GET answers. */
let rolesReply: () => Response | Promise<Response>;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");
const ttGets = () => calls().filter((c) => c.method === "GET" && c.url === URL);
const settle = () => new Promise((r) => setTimeout(r, 20));

beforeEach(() => {
  getReply = () => jsonRes({ tab: "time-tracking", config: STORED });
  putReply = (body) => jsonRes({ tab: "time-tracking", config: body });
  rolesReply = () => jsonRes({ tab: "roles", config: ROLES });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === ROLES_URL && method === "GET") return rolesReply();
    if (url === URL && method === "GET") return getReply();
    if (url === URL && method === "PUT") return putReply(JSON.parse(String(init?.body)));
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const button = (name: string) => screen.getByRole("button", { name });
const minutes = () => screen.getByRole("spinbutton", { name: "Auto clock out time" }) as HTMLInputElement;
const enabled = () => screen.getByRole("switch", { name: "Enable time tracking" });
const reminder = () => screen.getByRole("switch", { name: "Clock-in reminder" });
const roleBox = (name: string) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
/** The role list's ticks, Select all first: [Select all, the five built-ins, Night shift]. */
const LIST = ["Select all", "Owner", "Admin", "Team Leader", "Chatter", "Creator", "Night shift"];
const ticks = () => LIST.map((n) => roleBox(n).checked);
/** The read view's values: [minutes text, enabled, reminder]. */
const shown = () => [minutes().value, enabled().getAttribute("aria-checked"), reminder().getAttribute("aria-checked")];
/** Enable off: Auto clock out is hidden, as Infloww's `ClockSetting` (live, w5-a). */
const noMinutes = () => screen.queryByRole("spinbutton", { name: "Auto clock out time" }) === null;

async function mountLoaded() {
  renderWithProviders(<TimeTrackingTab />);
  await waitFor(() => expect(button("Edit")).toBeEnabled());
}

describe("TimeTrackingTab", () => {
  it("opens read-only: minutes, Enable and reminder show the stored values in disabled controls, with Edit and no not-applied sentence", async () => {
    await mountLoaded();
    expect(screen.getByRole("heading", { name: "Time tracking" })).toBeInTheDocument();
    expect(screen.queryByText(/not applied yet/)).toBeNull();
    expect(screen.getByText("Track your team’s work hours with a clock in and clock out function")).toBeInTheDocument();
    // The field sits inline in the sentence, between its two halves.
    expect([minutes().previousSibling?.textContent, minutes().nextSibling?.textContent])
      .toEqual(["Users will be automatically clocked out after", "minute(s) of inactivity"]);
    expect(shown()).toEqual(["45", "true", "false"]);
    expect(minutes()).toBeDisabled();
    expect(enabled()).toBeDisabled();
    expect(reminder()).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.queryByText(ERROR)).toBeNull();
  });

  it.each([["0"], [""], ["-5"], ["1.5"], ["1000"]])("minutes %j shows the error, disables Save, and a click sends nothing", async (typed) => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: typed } });
    expect(screen.getByRole("alert")).toHaveTextContent(ERROR);
    expect(button("Save")).toBeDisabled();
    fireEvent.click(button("Save"));
    await settle();
    expect(puts()).toEqual([]);
  });

  it("a bad minutes value then Enable off falls back to the stored minutes, so Save is not blocked by a hidden field", async () => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "" } });
    expect(button("Save")).toBeDisabled();
    fireEvent.click(enabled());
    expect(noMinutes()).toBe(true);
    fireEvent.click(button("Save"));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...STORED, enabled: false });
  });

  it.each([
    ["0", 0, "0"],
    ["the string \"45\" (not coerced)", "45", ""],
  ])("a stored minutes value of %s shows the error and Edit opens with Save disabled", async (_name, stored, text) => {
    getReply = () => jsonRes({ tab: "time-tracking", config: { ...STORED, auto_clock_out_minutes: stored } });
    await mountLoaded();
    expect(minutes().value).toBe(text);
    expect(screen.getByRole("alert")).toHaveTextContent(ERROR);
    fireEvent.click(button("Edit"));
    expect(button("Save")).toBeDisabled();
  });

  it("Edit enables minutes, Enable and reminder and swaps Edit for Cancel and Save", async () => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    expect(minutes()).toBeEnabled();
    expect(enabled()).toBeEnabled();
    expect(reminder()).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(button("Cancel")).toBeEnabled();
    expect(button("Save")).toBeEnabled();
  });

  it("Cancel restores the loaded values, returns to the read view and sends nothing", async () => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "30" } });
    fireEvent.click(reminder());
    expect(shown()).toEqual(["30", "true", "true"]);
    fireEvent.click(enabled());
    expect(noMinutes()).toBe(true);
    fireEvent.click(button("Cancel"));
    expect(shown()).toEqual(["45", "true", "false"]);
    expect(minutes()).toBeDisabled();
    expect(button("Edit")).toBeEnabled();
    await settle();
    expect(puts()).toEqual([]);
  });

  it("Edit → 30, reminder on, enabled off → Save PUTs exactly the four keys once, then shows the saved values read-only", async () => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "30" } });
    fireEvent.click(reminder());
    fireEvent.click(enabled());
    expect(screen.queryByText(ERROR)).toBeNull();
    fireEvent.click(button("Save"));

    await waitFor(() => expect(button("Edit")).toBeInTheDocument());
    expect(puts()).toEqual([
      { method: "PUT", url: URL, body: { enabled: false, auto_clock_out_minutes: 30, clock_in_reminder: true, role_ids: ["role-chat"] } },
    ]);
    expect([enabled().getAttribute("aria-checked"), reminder().getAttribute("aria-checked")]).toEqual(["false", "true"]);
    expect(noMinutes()).toBe(true);
    expect(button("Edit")).toBeEnabled();
  });

  it("an empty stored blob shows only Enable (off) and the reminder; Edit → on shows 10 and the roles; Save PUTs the defaults with no role ticked", async () => {
    getReply = () => jsonRes({ tab: "time-tracking", config: {} });
    await mountLoaded();
    expect([enabled().getAttribute("aria-checked"), reminder().getAttribute("aria-checked")]).toEqual(["false", "false"]);
    expect(noMinutes()).toBe(true);
    expect(screen.queryByText("Auto clock out")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Select all" })).toBeNull();
    fireEvent.click(button("Edit"));
    fireEvent.click(enabled());
    expect(shown()).toEqual(["10", "true", "false"]);
    expect(roleBox("Select all")).toBeEnabled();
    fireEvent.click(enabled());
    fireEvent.click(button("Save"));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      enabled: false, auto_clock_out_minutes: 10, clock_in_reminder: false, role_ids: [],
    });
  });

  it("999 minutes, Infloww's max, saves", async () => {
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "999" } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(minutes()).toHaveAttribute("max", "999");
    fireEvent.click(button("Save"));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...STORED, auto_clock_out_minutes: 999 });
  });

  it("a failed load leaves Edit disabled, says so beside Retry, sends no PUT, and a good Retry enables Edit (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    renderWithProviders(<TimeTrackingTab />);
    await waitFor(() => expect(ttGets()).toHaveLength(1));
    await settle();
    expect(button("Edit")).toBeDisabled();
    expect(screen.getByText("These settings never loaded — saving would replace them with defaults.")).toBeInTheDocument();
    fireEvent.click(button("Edit"));
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    await settle();
    expect(puts()).toEqual([]);

    getReply = () => jsonRes({ tab: "time-tracking", config: STORED });
    fireEvent.click(button("Retry"));
    await waitFor(() => expect(button("Edit")).toBeEnabled());
    expect(shown()).toEqual(["45", "true", "false"]);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(puts()).toEqual([]);
  });

  it("a 500 on the PUT stays in edit mode with the error after exactly one PUT; Cancel then shows the stored values", async () => {
    putReply = () => jsonRes({ detail: "boom" }, 500);
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "30" } });
    fireEvent.click(button("Save"));

    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(button("Save")).toBeEnabled();
    expect(puts()).toHaveLength(1);
    fireEvent.click(button("Cancel"));
    expect(shown()).toEqual(["45", "true", "false"]);
  });

  it("a Relay 400 shows its dotted-path detail by Save and keeps the draft (docs/spec/phase-04-apply-stored-settings.md)", async () => {
    const detail = "time-tracking.role_ids: no such role";
    putReply = () => jsonRes({ detail }, 400);
    await mountLoaded();
    fireEvent.click(button("Edit"));
    fireEvent.change(minutes(), { target: { value: "30" } });
    fireEvent.click(button("Save"));

    await waitFor(() => expect(screen.getByText(detail)).toBeInTheDocument());
    expect(puts()).toEqual([{ method: "PUT", url: URL, body: { ...STORED, auto_clock_out_minutes: 30 } }]);
    expect(minutes().value).toBe("30");
    expect(button("Save")).toBeEnabled();
  });
  describe("Enable clock in and clock out for (w4-a)", () => {
    it("lists Select all, the built-in Owner, Admin, Team Leader, Chatter and Creator, then the custom roles, disabled in the read view, with the no-role line", async () => {
      await mountLoaded();
      const list = screen.getByRole("group", { name: "Enable clock in and clock out for" });
      expect(list).toBeInTheDocument();
      expect(ticks()).toEqual([false, false, false, false, false, false, true]);
      expect(roleBox("Select all").indeterminate).toBe(true);
      for (const n of LIST) expect(roleBox(n)).toBeDisabled();
      expect(screen.getByText("Employees with no role can't clock in.")).toBeInTheDocument();
    });

    it("is hidden while time tracking is off, in the read view and once switched off in Edit", async () => {
      getReply = () => jsonRes({ tab: "time-tracking", config: { ...STORED, enabled: false } });
      await mountLoaded();
      expect(screen.queryByRole("group", { name: "Enable clock in and clock out for" })).toBeNull();
      fireEvent.click(button("Edit"));
      fireEvent.click(enabled());
      expect(screen.getByRole("group", { name: "Enable clock in and clock out for" })).toBeInTheDocument();
      fireEvent.click(enabled());
      expect(screen.queryByRole("group", { name: "Enable clock in and clock out for" })).toBeNull();
    });

    it("Select all ticks every role, Owner too; a second click clears them; Save PUTs the list", async () => {
      await mountLoaded();
      fireEvent.click(button("Edit"));
      fireEvent.click(roleBox("Select all"));
      expect(ticks()).toEqual([true, true, true, true, true, true, true]);
      fireEvent.click(roleBox("Select all"));
      expect(ticks()).toEqual([false, false, false, false, false, false, false]);
      fireEvent.click(roleBox("Owner"));
      fireEvent.click(roleBox("Chatter"));
      fireEvent.click(roleBox("Night shift"));
      expect(ticks()).toEqual([false, true, false, false, true, false, true]);
      fireEvent.click(button("Save"));

      await waitFor(() => expect(puts()).toHaveLength(1));
      expect(puts()[0].body).toEqual({ ...STORED, role_ids: ["owner", "chatter", "role-chat"] });
    });

    it("a never-saved list shows every role unticked, as Infloww's, and Save PUTs an empty list", async () => {
      getReply = () => jsonRes({ tab: "time-tracking", config: { enabled: true, auto_clock_out_minutes: 15, clock_in_reminder: false } });
      await mountLoaded();
      expect(ticks()).toEqual([false, false, false, false, false, false, false]);
      expect(roleBox("Select all").indeterminate).toBe(false);
      expect(screen.getByText("Employees with no role can't clock in.")).toBeInTheDocument();
      fireEvent.click(button("Edit"));
      fireEvent.click(button("Save"));

      await waitFor(() => expect(puts()).toHaveLength(1));
      expect(puts()[0].body).toEqual({
        enabled: true, auto_clock_out_minutes: 15, clock_in_reminder: false, role_ids: [],
      });
    });

    it("a stored list keeps its ids, an unknown one too, and Edit does not wait for the roles", async () => {
      getReply = () => jsonRes({ tab: "time-tracking", config: { ...STORED, role_ids: ["admin", "role-gone"] } });
      rolesReply = () => new Promise(() => {});
      await mountLoaded();
      fireEvent.click(button("Edit"));
      fireEvent.click(button("Save"));

      await waitFor(() => expect(puts()).toHaveLength(1));
      expect(puts()[0].body).toEqual({ ...STORED, role_ids: ["admin", "role-gone"] });
    });
  });
});
