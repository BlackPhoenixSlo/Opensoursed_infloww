/**
 * ManageEmployees — Infloww's Manage employees page (docs/spec/phase-05-remaining-parity-gaps.md, item 1; page-parity
 * ticket 17): the group tree on the left, the list on the right.
 *
 * Rendered inside `UserProvider` and `ChatterProvider` with the relay mocked at `fetch` by URL: the stub serves
 * `/auth/me`, the roster (each row's `account_ids`: null for all Creators), the owner's Creators, the `roles`
 * Settings blob, the Applied settings (the Agency's time zone), the Timesheet and the Employee groups (each roster
 * row's `group_id`; Batch edit group's `PUT /admin/employee-groups/members`, ticket 36), and the Add / Edit / Set
 * role / Reset password writes (`/admin/employees/login`, `…/{id}/setup`, `…/{id}/password`), so the columns and
 * the writes are assertions about the wire. The modals and the row's More menu render in portals, so they are
 * found on `screen`. Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import { ChatterProvider } from "@/contexts/ChatterContext";
import ManageEmployees from "@/components/employees/ManageEmployees";

// The Applied settings read names the Creator in scope; none is (the real provider opens the event stream).
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));

type Call = { method: string; url: string; body: unknown };
type Row = { id: number; display_name: string; color: string; is_active: boolean; chatter_id: string | null;
  username?: string; account_ids: string[] | null; group_id: number | null; kind?: "owner" | "login" | "name";
  user_id?: string };

let fetchMock: ReturnType<typeof vi.fn>;
let roster: Row[];
/** The signed-in principal: an owner, or a chatter with no owner session. */
let principal: "owner" | "chatter";
/** The Agency's applied time zone (Your Preferences' "Time zone"). */
let agencyTz: string | null;
/** What the Relay answers a roles PUT: the saved blob, or its validation's 400. */
let rolesPut: { status: 200 } | { status: 400; detail: string };
/** Whether the roles blob's read fails (a 500), so the blob never loads. */
let rolesGetFails: boolean;
/** What the Relay answers an access PUT when it refuses one, or null to accept it. */
let accessRefusal: string | null;
/** What the Relay answers a password reset when it refuses one, or null to accept it. */
let passwordRefusal: string | null;
/** The invites not accepted yet (GET /admin/chatters/invites); none unless a case sets them. */
let invites: Record<string, unknown>[];
const PENDING = {
  token: "pend1", expires_at: "2026-10-19T12:00:00Z", accept_path: "/chatter-login?token=pend1",
  created_at: "2026-10-18T12:00:00Z", display_name: "Pending Pat", role_id: "chatter", account_ids: ["902"], group_id: 10,
};

/** Alpha One and Delta Four sit in Fixture Leads, Beta Two in Fixture Nights below it, Gamma Three in no group. */
const ROSTER: Row[] = [
  { id: 1, display_name: "Alpha One", color: "#a78bfa", is_active: true, chatter_id: "c1", username: "alpha.one",
    account_ids: null, group_id: 10 },
  { id: 2, display_name: "Beta Two", color: "#60a5fa", is_active: true, chatter_id: "c2", username: "beta.two",
    account_ids: ["901"], group_id: 11 },
  { id: 3, display_name: "Gamma Three", color: "#34d399", is_active: false, chatter_id: "c3", username: "gamma.three",
    account_ids: ["902"], group_id: null },
  { id: 4, display_name: "Delta Four", color: "#f472b6", is_active: true, chatter_id: "c4", username: "delta.four",
    account_ids: [], group_id: 10 },
  // A retired name on the owner's own login (the old "Who's chatting?" pick) is not listed at all.
  { id: 5, display_name: "Mirror Five", color: "#bbbbbb", is_active: true, chatter_id: null, account_ids: ["901"],
    group_id: 11, kind: "name", user_id: "u1" },
  // The owner's own row, listed last here and first on the page.
  { id: 6, display_name: "ownerone", color: "#888888", is_active: true, chatter_id: null, account_ids: null,
    group_id: null, kind: "owner", user_id: "u1" },
];
/** Two groups and an empty one, the sub-group listed before its parent, so the rail's tree order is not the list's. */
const GROUPS = [
  { id: 12, name: "Fixture Spare", parent_id: null, employee_count: 0 },
  { id: 11, name: "Fixture Nights", parent_id: 10, employee_count: 2 },
  { id: 10, name: "Fixture Leads", parent_id: null, employee_count: 2 },
];
const CREATORS = [{ id: "901", nickname: "Creator North" }, { id: "902", nickname: "Creator South" }];
const CLOSER = { id: "role-closer", name: "Closer", description: "", permissions: { "/": true }, scope: "self" };
/** A stored copy of the built-in Chatter, which "+ Add employee" picks by default. */
const CHATTER = { id: "chatter", name: "Chatter", description: "Chats with fans.", permissions: { "/": true }, scope: "self" };
/** Beta Two holds the built-in Admin (not stored), Delta Four a role id no role has, Gamma Three none. */
const ROLES = {
  roles: [CLOSER, CHATTER],
  assignments: { "1": "role-closer", "2": "admin", "4": "role-gone" },
  enforce: false,
  extra_key: "kept",
};

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
// The perf logger (app/lib/perfLog.ts) flushes a "tab open" beacon to /admin/perflog/ingest on a timer; it is
// not a page write and raced one run of the suite, so it is left out of the wire record.
const writes = () => calls().filter((c) => c.method !== "GET" && !c.url.startsWith("/admin/perflog/"));

/** The current month's Timesheet, per Employee (`key` is the Employee id as text). Beta Two and Delta Four have
 *  no Shift or clock time this month, so the rollup has no row for them. */
const TIMESHEET = {
  rows: [
    { key: "1", display_name: "Alpha One", scheduled_shifts: 4, shifts_worked: 3, scheduled_minutes: 960,
      worked_minutes: 700, recorded_earnings_cents: 12345, open_now: false },
    { key: "3", display_name: "Gamma Three", scheduled_shifts: 2, shifts_worked: 0, scheduled_minutes: 480,
      worked_minutes: 0, recorded_earnings_cents: 0, open_now: false },
    { key: "5", display_name: "Mirror Five", scheduled_shifts: 9, shifts_worked: 9, scheduled_minutes: 60,
      worked_minutes: 60, recorded_earnings_cents: 999, open_now: true },
  ],
};

beforeEach(() => {
  // UserProvider opens from the last signed-in owner's localStorage snapshot; a chatter's mount must not.
  window.localStorage.clear();
  roster = ROSTER.map((r) => ({ ...r }));
  principal = "owner";
  agencyTz = null;
  rolesPut = { status: 200 };
  rolesGetFails = false;
  accessRefusal = null;
  passwordRefusal = null;
  invites = [];
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/auth/me") {
      return principal === "owner" ? jsonRes({ user_id: "u1", username: "ownerone" }) : jsonRes({ detail: "no" }, 401);
    }
    if (url === "/chatter/me") {
      return principal === "chatter"
        ? jsonRes({ chatter_id: "c1", username: "chatterone", display_name: "Chatter One", owners: [] })
        : jsonRes({ detail: "no" }, 401);
    }
    if (url === "/chatter/me/accounts") return jsonRes([]);
    if (url === "/admin/employees?include_disabled=true" && method === "GET") return jsonRes({ employees: roster });
    if (url === "/admin/accounts") return jsonRes({ accounts: CREATORS, active_account_id: null });
    if (url === "/admin/settings/roles" && method === "GET") {
      return rolesGetFails ? jsonRes({ detail: "down" }, 500) : jsonRes({ tab: "roles", config: ROLES });
    }
    if (url === "/admin/settings/roles" && method === "PUT") {
      return rolesPut.status === 200
        ? jsonRes({ tab: "roles", config: { ...JSON.parse(String(init?.body)), version: 1 } })
        : jsonRes({ detail: rolesPut.detail }, 400);
    }
    if (url === "/admin/chatters/invite" && method === "POST") {
      return jsonRes({ token: "tok", expires_at: "2026-10-19T12:00:00Z", accept_path: "/chatter-login?token=tok" });
    }
    if (url === "/admin/chatters/invites" && method === "GET") return jsonRes(invites);
    const invite = /^\/admin\/chatters\/invites\/([^/]+)(\/resend)?$/.exec(url);
    if (invite && method === "DELETE") {
      invites = invites.filter((i) => i.token !== invite[1]);
      return jsonRes({ ok: true });
    }
    if (invite?.[2] && method === "POST") {
      const old = invites.find((i) => i.token === invite[1])!;
      const fresh = { ...old, token: "pend2", accept_path: "/chatter-login?token=pend2" };
      invites = invites.map((i) => (i === old ? fresh : i));
      return jsonRes({ token: "pend2", expires_at: old.expires_at, accept_path: fresh.accept_path });
    }
    if (url === "/admin/chatters/link" && method === "POST") {
      const { username } = JSON.parse(String(init?.body)) as { username: string };
      return username === "nobody"
        ? jsonRes({ detail: "no chatter named 'nobody'" }, 404)
        : jsonRes({ ok: true, chatter_id: "c9", username, already_linked: false });
    }
    if (url === "/admin/chatters/c1/access") return jsonRes({ account_ids: [], folder_access: {} });
    if (url === "/admin/settings/applied") {
      return jsonRes({
        preferences: { tz: agencyTz, report_tz: null, week_start: "monday" },
        messaging: { ai_translation: true },
        permissions: { enforced: false, pages: null, scope: "all" },
      });
    }
    if (url.startsWith("/admin/shifts/timesheet?")) return jsonRes(TIMESHEET);
    if (url === "/admin/employee-groups" && method === "GET") return jsonRes({ groups: GROUPS });
    if (url === "/admin/employee-groups/members" && method === "PUT") {
      const body = JSON.parse(String(init?.body)) as { group_id: number | null; employee_ids: number[] };
      roster = roster.map((r) => (body.employee_ids.includes(r.id) ? { ...r, group_id: body.group_id } : r));
      return jsonRes(body);
    }
    const access = /^\/admin\/employees\/(\d+)\/access$/.exec(url);
    if (access && method === "PUT") {
      if (accessRefusal) return jsonRes({ detail: accessRefusal }, 400);
      const body = JSON.parse(String(init?.body)) as { account_ids: string[] };
      roster = roster.map((r) => (r.id === Number(access[1]) ? { ...r, account_ids: body.account_ids } : r));
      return jsonRes({ employee_id: Number(access[1]), account_ids: body.account_ids, wildcard: false });
    }
    if (url === "/admin/employees/login" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as { username: string };
      return jsonRes({ ok: true, employee_id: 7, chatter_id: "c7", username: body.username });
    }
    const setup = /^\/admin\/employees\/(\d+)\/setup$/.exec(url);
    if (setup && method === "PUT") {
      const body = JSON.parse(String(init?.body)) as Partial<Row>;
      const patch = Object.fromEntries(Object.entries(body).filter(([k]) => k !== "role_id"));
      roster = roster.map((r) => (r.id === Number(setup[1]) ? { ...r, ...patch } : r));
      return jsonRes({ ok: true, employee_id: Number(setup[1]) });
    }
    const password = /^\/admin\/employees\/(\d+)\/password$/.exec(url);
    if (password && method === "POST") {
      return passwordRefusal ? jsonRes({ detail: passwordRefusal }, 409) : jsonRes({ ok: true });
    }
    const m = /^\/admin\/employees\/(\d+)$/.exec(url);
    if (m && method === "DELETE") {
      roster = roster.map((r) => (r.id === Number(m[1]) ? { ...r, is_active: false } : r));
      return jsonRes({ ok: true, id: Number(m[1]), is_active: false });
    }
    if (m && method === "PATCH") {
      const patch = JSON.parse(String(init?.body)) as Partial<Row>;
      roster = roster.map((r) => (r.id === Number(m[1]) ? { ...r, ...patch } : r));
      return jsonRes(roster.find((r) => r.id === Number(m[1])));
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
});

function mount() {
  return renderWithProviders(
    <UserProvider>
      <ChatterProvider>
        <ManageEmployees />
      </ChatterProvider>
    </UserProvider>,
  );
}

/** The table's Employee rows (the owner's own first) as [Employee, Assigned creators, Role, Status]. */
const rows = () =>
  // Read from the DOM: an open modal marks the page behind it aria-hidden, so role queries skip the table.
  [...document.querySelectorAll<HTMLElement>("tr[data-employee]")].map((r) => {
    const cells = r.querySelectorAll("td");
    return [r.getAttribute("data-employee"), cells[2].textContent, cells[3].textContent, cells[4].textContent];
  });
const names = () => rows().map((r) => r[0]);
/** The rows but the owner's own. */
const staff = () => rows().filter((r) => r[0] !== "ownerone");
const OWNER = "ownerone";
const rowOf = (name: string) => document.querySelector<HTMLElement>(`tr[data-employee="${name}"]`)!;

/** Waits until the roster, the Creators and the roles blob have all landed in the table. */
async function loaded() {
  mount();
  await waitFor(() => expect(rows().find((r) => r[0] === "Alpha One")?.[2]).toBe("Closer"));
  await waitFor(() => expect(rows().find((r) => r[0] === "Beta Two")?.[1]).toBe("Creator North"));
}

/** Picks the option labelled `label` in a select: a native one (the dialogs), or an `IfSelect` (the filters), which
 *  opens a listbox on a click. */
const choose = (select: HTMLElement, label: string) => {
  if (select instanceof HTMLSelectElement) {
    const option = within(select).getByRole("option", { name: label }) as HTMLOptionElement;
    fireEvent.change(select, { target: { value: option.value } });
    return;
  }
  fireEvent.click(select);
  fireEvent.click(within(document.getElementById(select.getAttribute("aria-controls")!)!).getByRole("option", { name: label }));
};
/** An `IfSelect`'s option labels (opened, read, closed again). */
const optionsOf = (select: HTMLElement) => {
  fireEvent.click(select);
  const labels = within(document.getElementById(select.getAttribute("aria-controls")!)!).getAllByRole("option")
    .map((o) => o.textContent);
  fireEvent.click(select);
  return labels;
};
/** The tree's pick buttons (the root, then each group in tree order), not its carets or ⋮. */
const treeNodes = () => within(screen.getByRole("navigation", { name: "Employee groups" })).getAllByRole("button")
  .filter((b) => b.hasAttribute("aria-pressed"));
const node = (name: string) => treeNodes().find((b) => b.textContent === name)!;

describe("ManageEmployees", () => {
  it("lists Employee, Assigned creators, Role, Status, Group, This month and Actions, the owner's own row first", async () => {
    await loaded();
    expect(within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["", "Employee", "Assigned Creators", "Role", "Status", "Group", "This month", "Actions"]);
    expect(rows()).toEqual([
      [OWNER, "All Creators", "Owner", "Activated"],
      ["Alpha One", "All Creators", "Closer", "Activated"],
      ["Beta Two", "Creator North", "Admin", "Activated"],
      ["Gamma Three", "Creator South", "—", "Deactivated"],
      ["Delta Four", "Assign", "Unknown role (role-gone)", "Activated"],
    ]);
    // The title is the picked tree node: the root, named by the owner (no Agency name is set here).
    expect(screen.getByRole("heading", { name: "ownerone" })).toBeInTheDocument();
    expect(screen.getByText("3 active · 4 total")).toBeInTheDocument();
  });

  it("shows the owner's row with nothing to edit, each login's username, and never the retired names", async () => {
    await loaded();
    const owner = within(rowOf(OWNER));
    expect(owner.getByText("(you)")).toBeInTheDocument();
    expect(owner.getByRole("checkbox")).toBeDisabled();
    expect(owner.queryByRole("button")).toBeNull();
    expect(names()).not.toContain("Mirror Five");
    expect(screen.queryByText(/Names on your owner login/)).toBeNull();
    expect(within(rowOf("Alpha One")).getByText("@alpha.one")).toBeInTheDocument();
  });

  it("links to Role Settings, where the role presets are edited", async () => {
    await loaded();
    expect(screen.getByRole("link", { name: "Manage roles & permissions →" })).toHaveAttribute("href", "/settings/roles");
  });

  it("has no tab strip and no views rail: the Organization Chart is the tree on the left", async () => {
    await loaded();
    expect(screen.queryByRole("navigation", { name: "Manage employees" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Organization Chart" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Views" })).toBeNull();
    await waitFor(() => expect(treeNodes().map((b) => b.textContent))
      .toEqual(["ownerone", "Fixture Spare", "Fixture Leads", "Fixture Nights"]));
  });

  it("narrows by employee name or username, by Creator (all Creators matching every one), by status and by role, and Reset clears them", async () => {
    await loaded();
    const byEmployee = screen.getByRole("textbox", { name: "By employee" });
    const byCreator = screen.getByRole("combobox", { name: "By Creator" });
    const byStatus = screen.getByRole("combobox", { name: "By status" });
    const byRole = screen.getByRole("combobox", { name: "By role" });

    fireEvent.change(byEmployee, { target: { value: "TA" } });
    expect(names()).toEqual(["Beta Two", "Delta Four"]);
    fireEvent.change(byEmployee, { target: { value: "gamma.th" } });
    expect(names()).toEqual(["Gamma Three"]);
    fireEvent.change(byEmployee, { target: { value: "" } });

    expect(optionsOf(byCreator)).toEqual(["All Creators", "Creator North", "Creator South"]);
    choose(byCreator, "Creator North");
    expect(names()).toEqual([OWNER, "Alpha One", "Beta Two"]);
    choose(byCreator, "Creator South");
    expect(names()).toEqual([OWNER, "Alpha One", "Gamma Three"]);
    choose(byCreator, "All Creators");

    expect(optionsOf(byStatus)).toEqual(["All statuses", "Activated", "Deactivated", "Pending"]);
    choose(byStatus, "Deactivated");
    expect(names()).toEqual(["Gamma Three"]);
    choose(byStatus, "Activated");
    expect(names()).toEqual([OWNER, "Alpha One", "Beta Two", "Delta Four"]);
    choose(byStatus, "All statuses");

    expect(optionsOf(byRole)).toEqual(["All roles", "Owner", "Admin", "Team Leader", "Chatter", "Creator", "Closer", "No role"]);
    choose(byRole, "Closer");
    expect(names()).toEqual(["Alpha One"]);
    choose(byRole, "Admin");
    expect(names()).toEqual(["Beta Two"]);
    // A role id no role has counts as no role, as Role Settings and the Relay treat it.
    choose(byRole, "No role");
    expect(names()).toEqual(["Gamma Three", "Delta Four"]);
    choose(byRole, "Owner");
    expect(names()).toEqual([OWNER]);
    choose(byRole, "Chatter");
    expect(names()).toEqual([]);
    expect(screen.getByText("No data")).toBeInTheDocument();

    choose(byRole, "No role");
    choose(byCreator, "Creator South");
    fireEvent.change(byEmployee, { target: { value: "gamma" } });
    expect(names()).toEqual(["Gamma Three"]);
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(names()).toEqual([OWNER, "Alpha One", "Beta Two", "Gamma Three", "Delta Four"]);
    expect(byEmployee).toHaveValue("");
    // Cleared, each select shows its placeholder, as Infloww's do.
    expect([byCreator, byStatus, byRole].map((b) => b.textContent)).toEqual(["Creator", "Status", "Role"]);
  });

  /** Opens the More menu on the row whose Employee is `name`; it renders in a portal, outside the table. */
  const openMore = (name: string) => {
    fireEvent.click(within(rowOf(name)).getByRole("button", { name: "More" }));
    const menu = screen.getByRole("menu");
    expect(screen.getByRole("table").contains(menu)).toBe(false);
    return within(menu);
  };

  it("offers Reset password, Access limits, Deactivate and Delete under More, in a portal (the Role cell sets the role)", async () => {
    await loaded();
    expect(openMore("Alpha One").getAllByRole("menuitem").map((i) => i.textContent))
      .toEqual(["Reset password", "Access limits", "Deactivate", "Delete"]);
  });

  it("shows Edit and More as grey text in Actions, and an invite's Delete in red", async () => {
    invites = [{ ...PENDING }];
    await loaded();
    const actions = within(rowOf("Alpha One")).getAllByRole("cell")[7];
    expect(within(actions).getAllByRole("button").map((b) => [b.textContent, b.className.includes("text-muted")]))
      .toEqual([["Edit", true], ["More", true]]);
    const invite = await waitFor(() => document.querySelector<HTMLElement>('tr[data-invite="Pending Pat"]')!);
    expect(within(invite).getByRole("button", { name: "Delete" }).className).toContain("text-[#e05757]");
  });

  it("colours Status as Infloww does: Activated #2ad4ac, an invite's Inactive #F2994A with a #1677ff Resend", async () => {
    invites = [{ ...PENDING }];
    await loaded();
    expect(within(rowOf("Alpha One")).getByText("Activated").className).toContain("text-[#2ad4ac]");
    const invite = await waitFor(() => document.querySelector<HTMLElement>('tr[data-invite="Pending Pat"]')!);
    expect(within(invite).getByText("Inactive").className).toContain("text-[#F2994A]");
    expect(within(invite).getByRole("button", { name: "Resend" }).className).toContain("text-[#1677ff]");
  });

  it("links an editable row's Creators and role in #2d74ff, and greys the owner's and a deactivated row's", async () => {
    await loaded();
    const cell = (name: string, i: number) => within(rowOf(name)).getAllByRole("cell")[i];
    expect(within(cell("Beta Two", 2)).getByRole("button", { name: "Creator North" }).className).toContain("text-[#2d74ff]");
    expect(within(cell("Beta Two", 2)).getByRole("button").className).toContain("line-clamp-2");
    expect(within(cell("Delta Four", 2)).getByRole("button", { name: "Assign" }).className).toContain("text-[#2d74ff]");
    expect(within(cell("Gamma Three", 2)).queryByRole("button")).toBeNull();
    expect(cell("Gamma Three", 2).querySelector("span")!.className).toContain("text-muted");
    expect(within(cell(OWNER, 3)).queryByRole("button")).toBeNull();
  });

  it("deactivates from the More menu through the soft-disable, and re-activates through the same PATCH as before", async () => {
    await loaded();
    fireEvent.click(openMore("Alpha One").getByRole("menuitem", { name: "Deactivate" }));
    await waitFor(() => expect(staff()[0]).toEqual(["Alpha One", "All Creators", "Closer", "Deactivated"]));
    expect(writes()).toEqual([{ method: "DELETE", url: "/admin/employees/1", body: undefined }]);

    const menu = openMore("Alpha One");
    expect(menu.queryByRole("menuitem", { name: "Deactivate" })).toBeNull();
    fireEvent.click(menu.getByRole("menuitem", { name: "Activate" }));
    await waitFor(() => expect(staff()[0][3]).toBe("Activated"));
    expect(writes()).toEqual([
      { method: "DELETE", url: "/admin/employees/1", body: undefined },
      { method: "PATCH", url: "/admin/employees/1", body: { is_active: true } },
    ]);
  });

  it("shows Delete off, saying an Employee is deactivated instead, and it sends nothing", async () => {
    await loaded();
    const del = openMore("Beta Two").getByRole("menuitem", { name: "Delete" });
    expect(del).toBeDisabled();
    expect(del.getAttribute("title")).toMatch(/deactivated, never deleted/);
    fireEvent.click(del);
    expect(writes()).toEqual([]);
  });

  /** Ticks the selection box on the row whose Employee is `name`. */
  const select = (name: string) => fireEvent.click(screen.getByRole("checkbox", { name: `Select ${name}` }));
  /** Opens Batch actions and picks `item`, returning the dialog it opens. */
  const batch = (item: string) => {
    fireEvent.click(screen.getByRole("button", { name: "Batch actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: item }));
    return within(screen.getByRole("dialog", { name: item }));
  };

  it("warns \"Select at least one employee\" on Batch actions with nobody selected, and Select all ticks every login but the owner", async () => {
    await loaded();
    const batchButton = screen.getByRole("button", { name: "Batch actions" });
    expect(batchButton).toBeEnabled();
    fireEvent.click(batchButton);
    expect(screen.getByRole("status")).toHaveTextContent("Select at least one employee");
    expect(screen.queryByRole("menu")).toBeNull();
    select("Beta Two");
    fireEvent.click(batchButton);
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent))
      .toEqual(["Batch edit roles", "Assign", "Batch edit group"]);
    fireEvent.click(batchButton);
    select("Beta Two");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    expect(screen.getByText(/· 4 selected$/)).toBeInTheDocument();
  });

  it("Batch edit roles gives every selected Employee one role in exactly one roles PUT that keeps every other key", async () => {
    await loaded();
    select("Beta Two");
    select("Gamma Three");
    select("Delta Four");
    const dialog = batch("Batch edit roles");
    const role = dialog.getByRole("combobox", { name: "Role" });
    // Owner is never handed out, and no role is preselected.
    expect(within(role).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Choose a role", "Admin", "Team Leader", "Chatter", "Creator", "Closer"]);
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    choose(role, "Admin");
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(staff().map((r) => r[2])).toEqual(["Closer", "Admin", "Admin", "Admin"]));
    expect(writes()).toEqual([{
      method: "PUT",
      url: "/admin/settings/roles",
      body: {
        roles: [CLOSER, CHATTER],
        assignments: { "1": "role-closer", "2": "admin", "3": "admin", "4": "admin" },
        enforce: false,
        extra_key: "kept",
      },
    }]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/selected$/)).toBeNull();
  });

  it("shows the Relay's refusal when its validation rejects a Batch edit roles save, and the Role column stays", async () => {
    rolesPut = { status: 400, detail: "roles.assignments.4: unknown role" };
    await loaded();
    select("Alpha One");
    const dialog = batch("Batch edit roles");
    fireEvent.change(dialog.getByRole("combobox", { name: "Role" }), { target: { value: "admin" } });
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("roles.assignments.4: unknown role");
    expect(staff().map((r) => r[2])).toEqual(["Closer", "Admin", "—", "Unknown role (role-gone)"]);
    expect(writes()).toHaveLength(1);

    // Cancel drops the refusal: reopening the dialog starts clean.
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    expect(batch("Batch edit roles").queryByRole("alert")).toBeNull();
  });

  it("keeps Batch edit roles' Save off with the Load gate's note while the roles blob never loaded", async () => {
    rolesGetFails = true;
    mount();
    await waitFor(() => expect(rows().find((r) => r[0] === "Beta Two")?.[1]).toBe("Creator North"));
    select("Beta Two");
    const dialog = batch("Batch edit roles");
    choose(dialog.getByRole("combobox", { name: "Role" }), "Admin");
    expect(await dialog.findByText("These settings never loaded — saving would replace them with defaults."))
      .toBeInTheDocument();
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(writes()).toEqual([]);
  });

  it("clears the selection when a filter or the group changes, so a hidden row is never written", async () => {
    await loaded();
    select("Beta Two");
    fireEvent.change(screen.getByRole("textbox", { name: "By employee" }), { target: { value: "Alpha" } });
    expect(screen.queryByText(/selected$/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByRole("checkbox", { name: "Select Beta Two" })).not.toBeChecked();

    select("Beta Two");
    await waitFor(() => expect(node("Fixture Nights")).toBeTruthy());
    fireEvent.click(node("Fixture Nights"));
    fireEvent.click(node("ownerone"));
    expect(screen.getByRole("checkbox", { name: "Select Beta Two" })).not.toBeChecked();
    select("Alpha One");
    const dialog = batch("Assign");
    fireEvent.click(dialog.getByRole("checkbox", { name: "Creator South" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "PUT", url: "/admin/employees/1/access", body: { account_ids: ["902"] } }]);
  });

  it("drops a refused Assign's error on Cancel", async () => {
    await loaded();
    select("Alpha One");
    accessRefusal = "no such Creator";
    const dialog = batch("Assign");
    fireEvent.click(dialog.getByRole("checkbox", { name: "Creator South" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("no such Creator");
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    expect(batch("Assign").queryByRole("alert")).toBeNull();
  });

  it("Assign sends one access write per selected Employee with the chosen Creators", async () => {
    await loaded();
    select("Alpha One");
    select("Delta Four");
    const dialog = batch("Assign");
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.click(dialog.getByRole("checkbox", { name: "Creator South" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(staff().map((r) => r[1])).toEqual(["Creator South", "Creator North", "Creator South", "Creator South"]));
    expect(writes()).toEqual([
      { method: "PUT", url: "/admin/employees/1/access", body: { account_ids: ["902"] } },
      { method: "PUT", url: "/admin/employees/4/access", body: { account_ids: ["902"] } },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  /** The Group column, by login row. */
  const groupCells = () => staff().map((r) => within(rowOf(r[0]!)).getAllByRole("cell")[5].textContent);

  it("shows each Employee's group in the Group column, and — for none", async () => {
    await loaded();
    await waitFor(() => expect(groupCells()).toEqual(["Fixture Leads", "Fixture Nights", "—", "Fixture Leads"]));
  });

  it("the group tree's root selects every group, and picking a group filters the list to it and titles the page", async () => {
    await loaded();
    await waitFor(() => expect(node("Fixture Nights")).toBeTruthy());
    expect(node("ownerone")).toHaveAttribute("aria-pressed", "true");

    select("Beta Two");
    fireEvent.click(node("Fixture Leads"));
    expect(node("Fixture Leads")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("heading", { name: "Fixture Leads" })).toBeInTheDocument();
    // One group, not its sub-groups: Beta Two in Fixture Nights is not listed.
    expect(names()).toEqual(["Alpha One", "Delta Four"]);
    // A hidden row is never written: the selection was cleared.
    expect(screen.queryByText(/selected$/)).toBeNull();
    fireEvent.click(node("Fixture Nights"));
    expect(names()).toEqual(["Beta Two"]);
    // The tree combines with By status.
    choose(screen.getByRole("combobox", { name: "By status" }), "Deactivated");
    expect(names()).toEqual([]);
    choose(screen.getByRole("combobox", { name: "By status" }), "All statuses");
    fireEvent.click(node("Fixture Spare"));
    expect(names()).toEqual([]);
    // An empty list is Infloww's Empty.
    expect(screen.getByText("No data")).toBeInTheDocument();
    fireEvent.click(node("ownerone"));
    expect(names()).toEqual([OWNER, "Alpha One", "Beta Two", "Gamma Three", "Delta Four"]);
    expect(screen.getByRole("heading", { name: "ownerone" })).toBeInTheDocument();
  });

  it("folds the tree into a group select for a phone, which filters the same way", async () => {
    await loaded();
    const phone = screen.getByRole("combobox", { name: "Employee group" });
    await waitFor(() => expect(optionsOf(phone)).toEqual(["ownerone", "Fixture Spare", "Fixture Leads", "Fixture Nights"]));
    choose(phone, "Fixture Nights");
    expect(names()).toEqual(["Beta Two"]);
    expect(node("Fixture Nights")).toHaveAttribute("aria-pressed", "true");
  });

  it("pages over ten rows, ten a page, with Infloww's \"Total N employees\"", async () => {
    roster = [...roster, ...Array.from({ length: 8 }, (_, k): Row => ({
      id: 20 + k, display_name: `Extra ${k}`, color: "#777777", is_active: true, chatter_id: `x${k}`,
      username: `extra.${k}`, account_ids: null, group_id: null,
    }))];
    await loaded();
    // The owner, four logins and eight more: 13 rows.
    await waitFor(() => expect(names()).toHaveLength(10));
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    expect(pager).toHaveTextContent("Total: 13 employees");
    fireEvent.click(within(pager).getByRole("button", { name: "Page 2" }));
    expect(names()).toEqual(["Extra 5", "Extra 6", "Extra 7"]);
  });

  it("shows no pager at ten rows or fewer", async () => {
    await loaded();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
  });

  it("Batch edit group places every selected Employee in one group in exactly one write, and No group takes them out", async () => {
    await loaded();
    await waitFor(() => expect(groupCells()[0]).toBe("Fixture Leads"));
    select("Gamma Three");
    select("Delta Four");
    let dialog = batch("Batch edit group");
    const group = dialog.getByRole("combobox", { name: "Group" });
    expect(within(group).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Choose a group", "Fixture Spare", "Fixture Leads", "Fixture Nights", "No group"]);
    // No group is preselected, so Save at once moves nobody.
    expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    choose(dialog.getByRole("combobox", { name: "Group" }), "Fixture Spare");
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(groupCells()).toEqual(["Fixture Leads", "Fixture Nights", "Fixture Spare", "Fixture Spare"]));
    expect(writes()).toEqual([
      { method: "PUT", url: "/admin/employee-groups/members", body: { group_id: 12, employee_ids: [3, 4] } },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/selected$/)).toBeNull();

    select("Alpha One");
    dialog = batch("Batch edit group");
    choose(dialog.getByRole("combobox", { name: "Group" }), "No group");
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(groupCells()[0]).toBe("—"));
    expect(writes().at(-1)).toEqual(
      { method: "PUT", url: "/admin/employee-groups/members", body: { group_id: null, employee_ids: [1] } });
    expect(writes()).toHaveLength(2);
  });

  it("shows this month's recorded earnings and worked of scheduled shifts from the Timesheet, in the Agency's time zone", async () => {
    // 23:30 UTC on 31 October is already 1 November in Auckland (UTC+13), so the month is November there:
    // 1 Nov 00:00 NZDT = 31 Oct 11:00 UTC, up to 1 Dec 00:00 NZDT = 30 Nov 11:00 UTC.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T23:30:00Z"));
    agencyTz = "Pacific/Auckland";
    await loaded();

    const cells = () => staff().map((r) =>
      [...within(rowOf(r[0]!)).getAllByRole("cell")[6].querySelectorAll("div")].map((d) => d.textContent));
    await waitFor(() => expect(cells()).toEqual([
      ["$123", "3/4 shifts"],
      ["$0", "0/0 shifts"],
      ["$0", "0/2 shifts"],
      ["$0", "0/0 shifts"],
    ]));

    const sheets = calls().filter((c) => c.url.startsWith("/admin/shifts/timesheet?"));
    expect(sheets).toHaveLength(1);
    const qs = new URL(sheets[0].url, "http://relay").searchParams;
    expect([qs.get("from"), qs.get("to"), qs.get("group")])
      .toEqual(["2026-10-31T11:00:00.000Z", "2026-11-30T11:00:00.000Z", "employee"]);
  });

  it("explains This month as Recorded earnings, not pay", async () => {
    await loaded();
    const header = within(screen.getByRole("table")).getByRole("columnheader", { name: "This month" });
    expect(header).toHaveAttribute("title", expect.stringContaining("Recorded earnings"));
    expect(header.getAttribute("title")).toMatch(/not pay/);
  });

  /** Opens "+ Add employee", returning its dialog. */
  const openAdd = () => {
    fireEvent.click(screen.getByRole("button", { name: "+ Add employee" }));
    return within(screen.getByRole("dialog", { name: "Add employee" }));
  };

  it("+ Add employee makes the login with its name, role (Chatter by default), Creators and group in one write", async () => {
    await loaded();
    const dialog = openAdd();
    expect(dialog.getByRole("link", { name: "Manage roles & permissions →" })).toHaveAttribute("href", "/settings/roles");
    const role = dialog.getByRole("combobox", { name: "Role" }) as HTMLSelectElement;
    expect(role.value).toBe("chatter");
    expect(within(role).getAllByRole("option").map((o) => o.textContent)).toEqual(["Admin", "Team Leader", "Chatter", "Creator", "Closer"]);
    const add = dialog.getByRole("button", { name: "Add employee" });
    expect(add).toBeDisabled();

    fireEvent.change(dialog.getByRole("textbox", { name: "Name" }), { target: { value: "Eve Five" } });
    fireEvent.change(dialog.getByRole("textbox", { name: "Username" }), { target: { value: "Eve.Five" } });
    fireEvent.change(dialog.getByLabelText("Password"), { target: { value: "secret-1" } });
    choose(dialog.getByRole("combobox", { name: "Group" }), "Fixture Leads");
    fireEvent.click(dialog.getByRole("checkbox", { name: "All creators" }));
    // Limited to no Creator at all is not a choice: Save waits for one.
    expect(add).toBeDisabled();
    fireEvent.click(dialog.getByRole("checkbox", { name: "Creator North" }));
    fireEvent.click(add);

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{
      method: "POST", url: "/admin/employees/login",
      body: { display_name: "Eve Five", role_id: "chatter", account_ids: ["901"], group_id: 10, username: "eve.five",
        password: "secret-1" },
    }]);
  });

  it("+ Add employee can instead mint an invite link carrying the setup, or add an existing login by username", async () => {
    await loaded();
    let dialog = openAdd();
    fireEvent.click(dialog.getByRole("radio", { name: "Invite link" }));
    expect(dialog.queryByRole("textbox", { name: "Username" })).toBeNull();
    fireEvent.click(dialog.getByRole("button", { name: "Create invite link" }));
    const link = await dialog.findByRole("textbox", { name: "Invite link" });
    expect((link as HTMLInputElement).value).toMatch(/\/chatter-login\?token=tok$/);
    fireEvent.click(dialog.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    dialog = openAdd();
    fireEvent.click(dialog.getByRole("radio", { name: "Existing login" }));
    expect(dialog.queryByLabelText("Password")).toBeNull();
    fireEvent.change(dialog.getByRole("textbox", { name: "Username" }), { target: { value: "nobody" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add employee" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent("no chatter named 'nobody'");
    fireEvent.change(dialog.getByRole("textbox", { name: "Username" }), { target: { value: "Eve.Five" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add employee" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    const setup = { display_name: null, role_id: "chatter", account_ids: null, group_id: null };
    expect(writes().map((w) => [w.method, w.url, w.body])).toEqual([
      ["POST", "/admin/chatters/invite", setup],
      ["POST", "/admin/chatters/link", { ...setup, username: "nobody" }],
      ["POST", "/admin/chatters/link", { ...setup, username: "eve.five" }],
    ]);
  });

  it("Edit opens on the row's name, role, group and Creators, and saves them together", async () => {
    await loaded();
    fireEvent.click(within(rowOf("Beta Two")).getByRole("button", { name: "Edit" }));
    const dialog = within(screen.getByRole("dialog", { name: "Edit employee" }));
    expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Beta Two");
    expect(dialog.getByRole("combobox", { name: "Role" })).toHaveValue("admin");
    expect(dialog.getByRole("combobox", { name: "Group" })).toHaveValue("11");
    expect(dialog.getByRole("checkbox", { name: "All creators" })).not.toBeChecked();
    expect(dialog.getByRole("checkbox", { name: "Creator North" })).toBeChecked();
    expect(dialog.queryByRole("textbox", { name: "Username" })).toBeNull();

    fireEvent.change(dialog.getByRole("textbox", { name: "Name" }), { target: { value: "Beta 2" } });
    choose(dialog.getByRole("combobox", { name: "Role" }), "Closer");
    fireEvent.click(dialog.getByRole("checkbox", { name: "All creators" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{
      method: "PUT", url: "/admin/employees/2/setup",
      body: { display_name: "Beta 2", role_id: "role-closer", account_ids: null, group_id: 11 },
    }]);
    await waitFor(() => expect(rowOf("Beta 2")).toBeTruthy());
  });

  it("the Role cell sets the role alone; a role that is gone opens at Chatter, ready to save", async () => {
    await loaded();
    fireEvent.click(within(rowOf("Delta Four")).getByRole("button", { name: "Unknown role (role-gone)" }));
    const dialog = within(screen.getByRole("dialog", { name: "Set role" }));
    expect((dialog.getByRole("combobox", { name: "Role" }) as HTMLSelectElement).value).toBe("chatter");
    expect(dialog.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(dialog.getByText("Chats with fans.")).toBeInTheDocument();
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([{ method: "PUT", url: "/admin/employees/4/setup", body: { role_id: "chatter" } }]);
  });

  it("Reset password sets the new password once it is confirmed, and shows the Relay's refusal", async () => {
    await loaded();
    fireEvent.click(openMore("Alpha One").getByRole("menuitem", { name: "Reset password" }));
    let dialog = within(screen.getByRole("dialog", { name: "Reset password" }));
    const submit = () => dialog.getByRole("button", { name: "Reset password" });
    fireEvent.change(dialog.getByLabelText("New password"), { target: { value: "new-secret" } });
    fireEvent.change(dialog.getByLabelText("Confirm password"), { target: { value: "new-secreT" } });
    expect(dialog.getByText("The passwords don’t match.")).toBeInTheDocument();
    expect(submit()).toBeDisabled();
    fireEvent.change(dialog.getByLabelText("Confirm password"), { target: { value: "new-secret" } });
    fireEvent.click(submit());
    expect(await dialog.findByText(/password is changed/)).toBeInTheDocument();
    expect(writes()).toEqual([{ method: "POST", url: "/admin/employees/1/password", body: { password: "new-secret" } }]);
    fireEvent.click(dialog.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    passwordRefusal = "this login also works for another agency; only its owner can reset it";
    fireEvent.click(openMore("Beta Two").getByRole("menuitem", { name: "Reset password" }));
    dialog = within(screen.getByRole("dialog", { name: "Reset password" }));
    fireEvent.change(dialog.getByLabelText("New password"), { target: { value: "new-secret" } });
    fireEvent.change(dialog.getByLabelText("Confirm password"), { target: { value: "new-secret" } });
    fireEvent.click(submit());
    expect(await dialog.findByRole("alert")).toHaveTextContent("another agency");
  });

  it("opens an Employee's Access limits from the More menu, and not a deactivated one's", async () => {
    await loaded();
    expect(openMore("Gamma Three").getByRole("menuitem", { name: "Access limits" })).toBeDisabled();
    fireEvent.click(openMore("Alpha One").getByRole("menuitem", { name: "Access limits" }));
    expect(await screen.findByText("Limit which models this employee sees")).toBeInTheDocument();
  });

  it("labels the filters By employee:, By Creator:, By status:, By role: and greys out the owner's checkbox", async () => {
    await loaded();
    for (const label of ["By employee:", "By Creator:", "By status:", "By role:"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    expect(within(rowOf(OWNER)).getByRole("checkbox")).toBeDisabled();
    expect(within(rowOf(OWNER)).getAllByRole("cell")[3].textContent).toBe("Owner");
  });

  it("lists a pending invite as Inactive with Resend and Delete, and the Pending status shows only invites", async () => {
    invites = [{ ...PENDING }];
    await loaded();
    const pending = () => document.querySelector<HTMLElement>('tr[data-invite="Pending Pat"]');
    await waitFor(() => expect(pending()).not.toBeNull());
    const cells = pending()!.querySelectorAll("td");
    expect([cells[2].textContent, cells[3].textContent, cells[5].textContent])
      .toEqual(["Creator South", "Chatter", "Fixture Leads"]);
    expect(cells[4].textContent).toContain("Inactive");

    const byStatus = screen.getByRole("combobox", { name: "By status" });
    choose(byStatus, "Pending");
    expect(names()).toEqual([]);
    expect(pending()).not.toBeNull();
    choose(byStatus, "Activated");
    expect(pending()).toBeNull();
    choose(byStatus, "All statuses");

    // Resend: a fresh link, shown to copy.
    fireEvent.click(within(pending()!).getByRole("button", { name: "Resend" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByDisplayValue(/token=pend2/)).toBeInTheDocument());
    expect(calls().some((c) => c.method === "POST" && c.url === "/admin/chatters/invites/pend1/resend")).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    // Delete revokes it.
    await waitFor(() => expect(pending()).not.toBeNull());
    fireEvent.click(within(pending()!).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(pending()).toBeNull());
    expect(calls().some((c) => c.method === "DELETE" && c.url === "/admin/chatters/invites/pend2")).toBe(true);
  });

  it("tells a chatter only the owner can manage employees and never reads the list", async () => {
    principal = "chatter";
    mount();
    expect(await screen.findByText("Only the agency owner can manage employees.")).toBeInTheDocument();
    expect(calls().map((c) => c.url).filter((u) => u.startsWith("/admin/"))).toEqual([]);
  });
});
