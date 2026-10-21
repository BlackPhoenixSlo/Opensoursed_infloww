/**
 * Roadmap W6 6.12 in the Shifts window and Shift Settings: the Agency's common periods (the `shifts` blob's
 * `presets`, never the versioned `time-tracking` blob) are edited in Shift Settings and picked per row in the
 * Shifts window, and a 409 that clashes
 * only with other Shifts offers "Replace the clashing shifts", which resends with `replace: true`.
 *
 * Rendered with `fetch` mocked by URL, so every assertion is about the wire or the rendered text. The Shift zone is
 * UTC and the clock is pinned to Wed 14 Oct 2026 12:00 UTC. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import ShiftSettingsDialog from "@/components/shifts/ShiftSettingsDialog";
import ShiftsWindow from "@/components/shifts/ShiftsWindow";

const PERIODS = [{ start: "09:00", end: "17:00" }, { start: "22:00", end: "06:00" }];
const OTHER_CLASH = { detail: "clash", clashes: [{ shift_id: 5, occurrence_start: "2026-10-14T10:00:00Z", account_id: "1" }] };
const SELF_CLASH = { detail: "clash", clashes: [{ shift_id: null, occurrence_start: "2026-10-14T09:00:00Z", account_id: "1" }] };

let fetchMock: ReturnType<typeof vi.fn>;
let shiftsBlob: Record<string, unknown>;
/** The replies to each POST /admin/shifts in turn; the last repeats. */
let posts: Response[];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-14T12:00:00Z"));
  shiftsBlob = { presets: PERIODS, kept: 1 };
  posts = [jsonRes({ shift_id: 99, status: "scheduled" })];
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split("?")[0];
    const method = init?.method ?? "GET";
    if (path === "/admin/settings/shifts" && method === "GET") return jsonRes({ tab: "shifts", config: shiftsBlob });
    if (path === "/admin/settings/shifts" && method === "PUT") {
      return jsonRes({ tab: "shifts", config: JSON.parse(String(init!.body)) });
    }
    if (path === "/admin/settings/sales" && method === "GET") return jsonRes({ tab: "sales", config: {} });
    if (path === "/admin/settings/sales" && method === "PUT") {
      return jsonRes({ tab: "sales", config: JSON.parse(String(init!.body)) });
    }
    if (path === "/admin/shifts" && method === "POST") return posts.length > 1 ? posts.shift()! : posts[0].clone();
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function writes(): { method: string; path: string; body: unknown }[] {
  return fetchMock.mock.calls
    .filter(([, init]) => (init?.method ?? "GET") !== "GET")
    .map(([url, init]) => ({ method: init.method, path: String(url).split("?")[0], body: JSON.parse(String(init.body)) }));
}

function renderWindow() {
  renderWithProviders(
    <ShiftsWindow editing={null} defaultTz="UTC" employees={[{ id: 41, label: "Avery" }, { id: 42, label: "Blake" }]}
      creators={[{ id: "1", label: "creator_one" }]} onClose={() => {}} />,
  );
  const row = within(screen.getByRole("group", { name: "Shift 1" }));
  fireEvent.click(row.getByRole("checkbox", { name: "creator_one" }));
  fireEvent.click(row.getByRole("checkbox", { name: "Avery" }));
  return row;
}

describe("Common periods and Replace", () => {
  it("a common period sets Start and End on today, an overnight one ending the next day", async () => {
    const row = renderWindow();
    const pick = await row.findByRole("combobox", { name: "Common period" });
    expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose…", "09:00 - 17:00", "22:00 - 06:00",
    ]);
    fireEvent.change(pick, { target: { value: "1" } });
    expect(row.getByLabelText("Start")).toHaveValue("2026-10-14T22:00");
    expect(row.getByLabelText("End")).toHaveValue("2026-10-15T06:00");
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-10-20T08:00" } });
    fireEvent.change(pick, { target: { value: "0" } });
    expect(row.getByLabelText("Start")).toHaveValue("2026-10-20T09:00");
    expect(row.getByLabelText("End")).toHaveValue("2026-10-20T17:00");

    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ start_utc: "2026-10-20T09:00:00.000Z", end_utc: "2026-10-20T17:00:00.000Z" });
    expect(writes()[0].body).not.toHaveProperty("replace");
  });

  it("with no saved periods the picker is not shown", async () => {
    shiftsBlob = {};
    const row = renderWindow();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/admin/settings/shifts"))).toBe(true));
    expect(row.queryByRole("combobox", { name: "Common period" })).toBeNull();
  });

  it("a clash with another Shift offers Replace, and OK then resends with replace: true", async () => {
    posts = [jsonRes(OTHER_CLASH, 409), jsonRes({ shift_id: 99, status: "scheduled" })];
    const row = renderWindow();
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-10-14T09:00" } });
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-10-14T17:00" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    const replace = await row.findByRole("checkbox", { name: /Replace the clashing shifts/ });
    expect(replace).not.toBeChecked();
    fireEvent.click(replace);
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[0].body).not.toHaveProperty("replace");
    expect(writes()[1].body).toMatchObject({ replace: true, employee_ids: [41], account_ids: ["1"] });
  });

  it("the Shift's own double-staffing offers no Replace", async () => {
    posts = [jsonRes(SELF_CLASH, 409)];
    const row = renderWindow();
    fireEvent.change(row.getByLabelText("Start"), { target: { value: "2026-10-14T09:00" } });
    fireEvent.change(row.getByLabelText("End"), { target: { value: "2026-10-14T17:00" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await row.findByText(/more than one Employee on this Shift/)).toBeInTheDocument();
    expect(row.queryByRole("checkbox", { name: /Replace the clashing shifts/ })).toBeNull();
  });

  it("Shift Settings edits the common periods and saves the shifts blob with them", async () => {
    renderWithProviders(<ShiftSettingsDialog onClose={() => {}} />);
    const dialog = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    expect(await dialog.findByLabelText("Period 2 start")).toHaveValue("22:00");
    fireEvent.click(dialog.getAllByRole("button", { name: "Remove" })[0]);
    fireEvent.click(dialog.getByRole("button", { name: "+ Add period" }));
    fireEvent.change(dialog.getByLabelText("Period 2 end"), { target: { value: "18:00" } });
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()).toEqual([
      { method: "PUT", path: "/admin/settings/sales", body: {} },
      { method: "PUT", path: "/admin/settings/shifts",
        body: { presets: [{ start: "22:00", end: "06:00" }, { start: "09:00", end: "18:00" }], kept: 1 } },
    ]);
  });

  it("Shift Settings leaves the shifts blob alone when no period changed", async () => {
    const onClose = vi.fn();
    renderWithProviders(<ShiftSettingsDialog onClose={onClose} />);
    const dialog = within(await screen.findByRole("dialog", { name: "Shift Settings" }));
    await dialog.findByLabelText("Period 1 start");
    await waitFor(() => expect(dialog.getByRole("button", { name: "OK" })).toBeEnabled());
    fireEvent.click(dialog.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(writes().map((w) => w.path)).toEqual(["/admin/settings/sales"]);
  });
});
