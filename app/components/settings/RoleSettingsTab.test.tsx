/**
 * RoleSettingsTab — the Role Settings Panel (docs/spec/settings-tabs/phase-03-roles-sales.md).
 *
 * Rendered inside `UserProvider` with the relay mocked at `fetch` by URL: the stub serves `/auth/me`, the
 * roster and the `roles` Settings blob, so every save assertion is an assertion about the wire. The
 * new role's id comes from `Date.now()`, pinned here to 1760000000000, which is
 * "mgj6k3cw" in base 36.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import RoleSettingsTab from "@/components/settings/RoleSettingsTab";
import { SIDEBAR } from "@/lib/nav";
import { CARD_PERMISSIONS, REVENUE_CARD_KEYS } from "@/lib/dashboardCards";
import { PAGE_ACTIONS } from "@/lib/permissionActions";

type Call = { method: string; url: string; body: unknown };

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/settings/roles answers next. */
let getReply: () => Response;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");

/** Every SIDEBAR page a role is keyed by, collected here from the nav itself:
 *  links and group children, dividers and links answering to another page's
 *  grant (`permission`: Focus) skipped. */
const HREFS: string[] = [];
for (const n of SIDEBAR) {
  if ("divider" in n) continue;
  if ("children" in n) n.children.forEach((c) => HREFS.push(c.href));
  else if (!n.permission) HREFS.push(n.href);
}
const pages = (allowed: boolean) => Object.fromEntries(HREFS.map((h) => [h, allowed]));
const actions = (allowed: boolean) => Object.fromEntries(Object.keys(PAGE_ACTIONS).map((k) => [k, allowed]));
const cards = (allowed: boolean) => Object.fromEntries(Object.keys(CARD_PERMISSIONS).map((k) => [k, allowed]));
/** The built-ins: every page but My Automations, which a chatter gets only from a role storing it ticked. */
const MY_AUTOMATIONS = ["/growth/auto-post", "/growth/auto-story", "/growth/auto-mass", "/growth/auto-reply", "/growth/auto-funnel", "/growth/gen-info"];
const builtIn = () => ({ ...pages(true), ...Object.fromEntries(MY_AUTOMATIONS.map((h) => [h, false])) });
const OWNER = { id: "owner", name: "Owner", description: "", permissions: builtIn(), scope: "all" };
const ADMIN = { id: "admin", name: "Admin", description: "", permissions: builtIn(), scope: "all" };
/** Team Leader, Chatter and Creator: built in since w5-a (Infloww's live default roles), each granting only its pages. */
const only = (hrefs: string[]) => ({ ...pages(false), ...Object.fromEntries(hrefs.map((h) => [h, true])) });
const CHATTING = [
  "/messages-pro", "/of-manager/messages", "/of-manager/notifications", "/growth/scripts", "/growth/get-to-know-fans",
];
const DEFAULT_ROLES = [
  {
    id: "team-leader", name: "Team Leader", description: "", scope: "subordinates",
    permissions: only([
      "/", ...CHATTING, "/growth/smart-messages", "/of-manager/home", "/of-manager/vault", "/creators",
      "/creators/proxy", "/employees", "/employees/shifts", "/analytics/creator-reports",
      "/analytics/employee-reports", "/analytics/message-dashboard", "/analytics/sales-records",
    ]),
  },
  // The built-in Chatter opens the Dashboard without its revenue cards (roadmap 5.12).
  { id: "chatter", name: "Chatter", description: "", scope: "self",
    permissions: { ...only(["/", ...CHATTING]), ...Object.fromEntries(REVENUE_CARD_KEYS.map((k) => [k, false])) } },
  {
    id: "creator", name: "Creator", description: "", scope: "self",
    permissions: only([
      "/of-manager/home", "/of-manager/new-post", "/of-manager/vault", "/of-manager/queue",
      "/of-manager/collections", "/of-manager/collections/bookmarks/all", "/of-manager/profile", "/of-manager/release-forms",
      "/growth/vault-pro",
    ]),
  },
];
/** The five built-ins' names, in list order. */
const BUILT_IN_NAMES = ["Owner", "Admin", "Team Leader", "Chatter", "Creator"];
const ALPHA = { id: "role-alpha", name: "Alpha Role", description: "Stored", permissions: { "/": false }, scope: "self" };
/** Grants Dashboard and Scripts, plus a stale href no nav page has; every other page is absent. */
const BETA = {
  id: "role-beta", name: "Beta Role", description: "",
  permissions: { "/": true, "/growth/scripts": true, "/stale-page": true }, scope: "self",
};

/** Gamma Three is disabled, so the Relay's `include_disabled=false` roster leaves it out. */
const ROSTER = [
  { id: 1, display_name: "Alpha One", color: "#a78bfa", is_active: true, chatter_id: "c1" },
  { id: 2, display_name: "Beta Two", color: "#60a5fa", is_active: true, chatter_id: "c2" },
  { id: 3, display_name: "Gamma Three", color: "#34d399", is_active: false, chatter_id: "c3" },
];

beforeEach(() => {
  getReply = () => jsonRes({ tab: "roles", config: {} });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
    if (url === "/admin/employees?include_disabled=true") return jsonRes({ employees: ROSTER });
    if (url === "/admin/employees?include_disabled=false") {
      return jsonRes({ employees: ROSTER.filter((e) => e.is_active) });
    }
    if (url === "/admin/settings/roles" && method === "GET") return getReply();
    if (url === "/admin/settings/roles" && method === "PUT") {
      return jsonRes({ tab: "roles", config: JSON.parse(String(init?.body)) });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mount() {
  return renderWithProviders(
    <UserProvider>
      <RoleSettingsTab />
    </UserProvider>,
  );
}

const addRole = () => screen.getByRole("button", { name: "+ Add Role" });
/** The Roles table's body rows, each as its cells' text. */
const rows = () =>
  within(screen.getByRole("table", { name: "Roles" })).getAllByRole("row").slice(1)
    .map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));

/** Opens "Add Role" once the blob has loaded and fills the two Fields. */
async function fillAddRole(name: string, description = "") {
  await waitFor(() => expect(addRole()).toBeEnabled());
  fireEvent.click(addRole());
  const dialog = screen.getByRole("dialog", { name: "Add Role" });
  fireEvent.change(within(dialog).getByLabelText("Role Name"), { target: { value: name } });
  fireEvent.change(within(dialog).getByLabelText("Description"), { target: { value: description } });
  return within(dialog).getByRole("button", { name: "Submit" });
}

/** The Employee roles selects, in roster order. */
const selects = () => screen.queryAllByRole("combobox");
/** The Employee roles Save (the header's SaveRow). */
const saveButton = () => screen.getByRole("button", { name: "Save" });
/** The text of the option the Employee named `name` has selected. */
const selected = (name: string) => screen.getByRole("combobox", { name }).textContent;
/** The option texts of the Employee named `name`'s select: open its listbox with Enter, read it, Escape. */
const optionTexts = (name: string) => {
  const s = screen.getByRole("combobox", { name });
  fireEvent.keyDown(s, { key: "Enter" });
  const texts = within(screen.getByRole("listbox", { name })).getAllByRole("option").map((o) => o.textContent);
  fireEvent.keyDown(s, { key: "Escape" });
  return texts;
};
/** Open the Employee named `name`'s select with Enter and pick the option named `option`. */
const pick = (name: string, option: string) => {
  fireEvent.keyDown(screen.getByRole("combobox", { name }), { key: "Enter" });
  fireEvent.click(within(screen.getByRole("listbox", { name })).getByRole("option", { name: option }));
};
/** The Employee named `name`'s select, once the blob has loaded. */
async function loadedSelect(name: string) {
  const s = await screen.findByRole("combobox", { name });
  await waitFor(() => expect(s).toBeEnabled());
  return s;
}

/** Clicks "Edit" on the row named `name` once the blob has loaded; returns the "Edit Role" dialog. */
async function openEdit(name: string) {
  await waitFor(() => expect(addRole()).toBeEnabled());
  const row = within(screen.getByRole("table", { name: "Roles" })).getByRole("cell", { name }).closest("tr")!;
  fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
  return within(screen.getByRole("dialog", { name: "Edit Role" }));
}

/** Clicks "Set Permissions" on the row named `name` once the blob has loaded. */
async function openPermissions(name: string) {
  await waitFor(() => expect(addRole()).toBeEnabled());
  const row = within(screen.getByRole("table", { name: "Roles" })).getByRole("cell", { name }).closest("tr")!;
  fireEvent.click(within(row).getByRole("button", { name: "Set Permissions" }));
  expect(screen.getByRole("heading", { name })).toBeInTheDocument();
}

const NOT_ENFORCED = "Saved for your organization; not enforced until Enforce role permissions is on.";
/** The "Enforce role permissions" switch, once the blob has loaded. */
async function enforceSwitch() {
  const s = await screen.findByRole("switch", { name: "Enforce role permissions" });
  await waitFor(() => expect(s).toBeEnabled());
  return s;
}

describe("RoleSettingsTab", () => {
  it("with an empty blob lists the five built-ins (Owner, Admin, Team Leader, Chatter, Creator), shows no not-enforced note, and offers no Learn more or Delete", async () => {
    mount();
    expect(screen.getByRole("heading", { name: "Role Settings" })).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Roles" })).getAllByRole("columnheader").map((h) => h.textContent))
      .toEqual(["Name", "Description", "Status", "Operations"]);
    await waitFor(() => expect(addRole()).toBeEnabled());
    expect(rows()).toEqual(BUILT_IN_NAMES.map((n) => [n, "", "", "EditSet Permissions"]));
    for (const row of within(screen.getByRole("table", { name: "Roles" })).getAllByRole("row").slice(1)) {
      const ops = within(row).getAllByRole("cell")[3];
      expect(within(ops).getAllByRole("button").map((b) => b.textContent)).toEqual(["Edit", "Set Permissions"]);
    }
    expect(screen.queryByText(NOT_ENFORCED)).toBeNull();
    expect(screen.queryByText(/learn more/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
  });

  it("adding \"Alpha Role\" sends one PUT of every role, the new one deny-all with scope self, and closes the modal", async () => {
    mount();
    const submit = await fillAddRole("Alpha Role", "Synthetic description");
    vi.spyOn(Date, "now").mockReturnValue(1760000000000);
    fireEvent.click(submit);

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(puts()).toEqual([{
      method: "PUT",
      url: "/admin/settings/roles",
      body: {
        roles: [OWNER, ADMIN, ...DEFAULT_ROLES, {
          id: "role-mgj6k3cw", name: "Alpha Role", description: "Synthetic description",
          permissions: pages(false), scope: "self",
        }],
      },
    }]);
    // The built-ins grant every page, including both ends of the nav, and nothing legacy or footer.
    expect(OWNER.permissions).toMatchObject({ "/": true, "/of-manager/home": true, "/employees": true });
    expect(ADMIN.permissions).toMatchObject({ "/growth/smart-messages": true, "/growth/auto-mass": false });
    expect(Object.keys(OWNER.permissions)).not.toContain("/automations");
    expect(Object.keys(OWNER.permissions)).not.toContain("/settings");
    await waitFor(() => expect(rows().map((r) => r[0])).toEqual([...BUILT_IN_NAMES, "Alpha Role"]));
  });

  it("keeps Submit disabled for a blank name or one repeating a role in another case, and enables it for a fresh name", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA] } });
    mount();
    const submit = await fillAddRole("");
    expect(submit).toBeDisabled();
    const name = screen.getByLabelText("Role Name");
    for (const dup of ["owner", "ALPHA ROLE", "  "]) {
      fireEvent.change(name, { target: { value: dup } });
      expect(submit).toBeDisabled();
    }
    fireEvent.change(name, { target: { value: "Beta Role" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(puts()).toHaveLength(1));
  });

  it("keeps a stored unknown key, stored assignments and a stored built-in, and lists the built-ins first", async () => {
    const owner = { ...OWNER, description: "Stored owner", permissions: { "/": false } };
    const stored = { roles: [ALPHA, owner], assignments: { "7": "role-alpha" }, extra_key: 1 };
    getReply = () => jsonRes({ tab: "roles", config: stored });
    mount();
    await waitFor(() => expect(rows().map((r) => r[0])).toEqual([...BUILT_IN_NAMES, "Alpha Role"]));
    expect(rows()[0]).toEqual(["Owner", "Stored owner", "", "EditSet Permissions"]);
    const submit = await fillAddRole("Beta Role");
    vi.spyOn(Date, "now").mockReturnValue(1760000000000);
    fireEvent.click(submit);

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({
      ...stored,
      roles: [owner, ADMIN, ...DEFAULT_ROLES, ALPHA, {
        id: "role-mgj6k3cw", name: "Beta Role", description: "", permissions: pages(false), scope: "self",
      }],
    });
  });

  it("Edit on a stored custom role is pre-filled; a new name and description Submit as one PUT, the role kept in place with its id", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA] } });
    mount();
    const dialog = await openEdit("Alpha Role");
    const name = dialog.getByLabelText("Role Name");
    expect(name).toHaveValue("Alpha Role");
    expect(name).toBeEnabled();
    expect(dialog.getByLabelText("Description")).toHaveValue("Stored");
    fireEvent.change(name, { target: { value: "Gamma Three" } });
    fireEvent.change(dialog.getByLabelText("Description"), { target: { value: "Renamed" } });
    fireEvent.click(dialog.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(puts()).toEqual([{
      method: "PUT",
      url: "/admin/settings/roles",
      body: { roles: [OWNER, ADMIN, ...DEFAULT_ROLES, { ...ALPHA, name: "Gamma Three", description: "Renamed" }, BETA] },
    }]);
    await waitFor(() => expect(rows().map((r) => r[0])).toEqual([...BUILT_IN_NAMES, "Gamma Three", "Beta Role"]));
  });

  it("Edit on Owner shows Role Name disabled and still saves a new description under the name Owner", async () => {
    mount();
    const dialog = await openEdit("Owner");
    expect(dialog.getByLabelText("Role Name")).toHaveValue("Owner");
    expect(dialog.getByLabelText("Role Name")).toBeDisabled();
    fireEvent.change(dialog.getByLabelText("Description"), { target: { value: "Agency owner" } });
    fireEvent.click(dialog.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ roles: [{ ...OWNER, description: "Agency owner" }, ADMIN, ...DEFAULT_ROLES] });
  });

  it("renaming a custom role to another role's name in another case keeps Submit disabled; its own name enables it", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA] } });
    mount();
    const dialog = await openEdit("Alpha Role");
    const submit = dialog.getByRole("button", { name: "Submit" });
    expect(submit).toBeEnabled();
    const name = dialog.getByLabelText("Role Name");
    for (const dup of ["beta role", "ADMIN"]) {
      fireEvent.change(name, { target: { value: dup } });
      expect(submit).toBeDisabled();
    }
    fireEvent.change(name, { target: { value: "ALPHA ROLE" } });
    expect(submit).toBeEnabled();
  });

  it("Set Permissions on the built-in Admin shows My Automations unticked and every other page ticked", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [] } });
    mount();
    await openPermissions("Admin");
    for (const label of ["Auto Post", "Auto Story", "Auto Mass", "Auto-reply", "Auto Funnel"]) {
      expect(screen.getByRole("checkbox", { name: label })).not.toBeChecked();
    }
    expect(screen.getByRole("checkbox", { name: "Dashboard" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Messages Pro" })).toBeChecked();
  });

  it("Set Permissions on a stored custom role, Dashboard off and Self and subordinates, Save sends one PUT with every page explicit", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA] } });
    mount();
    await openPermissions("Beta Role");
    fireEvent.click(screen.getByRole("checkbox", { name: "Dashboard" }));
    fireEvent.click(screen.getByRole("radio", { name: "Self and subordinates" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByRole("table", { name: "Roles" })).toBeInTheDocument());
    expect(puts()).toEqual([{
      method: "PUT",
      url: "/admin/settings/roles",
      body: {
        roles: [OWNER, ADMIN, ...DEFAULT_ROLES, ALPHA, {
          ...BETA,
          // Every Function permission and Dashboard card explicit too, each on: none was stored false.
          permissions: { ...pages(false), ...actions(true), ...cards(true), "/growth/scripts": true, "/stale-page": true },
          scope: "subordinates",
        }],
      },
    }]);
  });

  it("Back after a toggle sends no PUT, and reopening shows the stored values", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA] } });
    mount();
    await openPermissions("Beta Role");
    fireEvent.click(screen.getByRole("checkbox", { name: "Dashboard" }));
    fireEvent.click(screen.getByRole("radio", { name: "All data" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("table", { name: "Roles" })).toBeInTheDocument();

    await openPermissions("Beta Role");
    expect(screen.getByRole("checkbox", { name: "Dashboard" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Messages Pro" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Data about self" })).toBeChecked();
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
  });

  it("a failed Save PUT keeps the editor open and shows the error", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA] } });
    const served = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
    let answer!: () => void;
    const held = new Promise<void>((r) => { answer = r; });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method !== "PUT") return served(url, init);
      await held; // the PUT stays in flight until the second click has landed
      return jsonRes({ detail: "roles save boom" }, 500);
    });
    mount();
    await openPermissions("Beta Role");
    const save = screen.getByRole("button", { name: "Save" });
    fireEvent.click(save);
    // While the first PUT is in flight Save is disabled, so a second click sends nothing: one PUT, not two.
    await waitFor(() => expect(save).toBeDisabled());
    fireEvent.click(save);
    answer();

    expect(await screen.findByRole("alert")).toHaveTextContent("roles save boom");
    expect(screen.getByRole("heading", { name: "Beta Role" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Roles" })).toBeNull();
    expect(puts()).toHaveLength(1);
  });

  it("a failed GET leaves \"+ Add Role\" and every Edit disabled, shows Retry and sends no PUT; a good Retry enables them", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    mount();
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(addRole()).toBeDisabled();
    await waitFor(() => expect(selects()).toHaveLength(2));
    selects().forEach((s) => expect(s).toBeDisabled());
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    const edits = () => within(screen.getByRole("table", { name: "Roles" })).getAllByRole("button", { name: "Edit" });
    const setPerms = () => within(screen.getByRole("table", { name: "Roles" })).getAllByRole("button", { name: "Set Permissions" });
    expect(edits()).toHaveLength(5);
    edits().forEach((b) => expect(b).toBeDisabled());
    expect(setPerms()).toHaveLength(5);
    setPerms().forEach((b) => expect(b).toBeDisabled());
    fireEvent.click(addRole());
    fireEvent.click(edits()[0]);
    fireEvent.click(setPerms()[0]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("table", { name: "Roles" })).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);

    getReply = () => jsonRes({ tab: "roles", config: {} });
    fireEvent.click(retry);
    await waitFor(() => expect(addRole()).toBeEnabled());
    edits().forEach((b) => expect(b).toBeEnabled());
    setPerms().forEach((b) => expect(b).toBeEnabled());
    selects().forEach((s) => expect(s).toBeEnabled());
    expect(saveButton()).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(puts()).toEqual([]);
  });

  it("Employee roles lists Alpha One and Beta Two, not the disabled Gamma Three, each unassigned at Chatter over every role, with no \"No role\"", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA] } });
    mount();
    expect(screen.getByRole("heading", { name: "Employee roles" })).toBeInTheDocument();
    await waitFor(() => expect(selects().map((s) => s.getAttribute("aria-label"))).toEqual(["Alpha One", "Beta Two"]));
    expect(screen.queryByLabelText("Gamma Three")).toBeNull();
    const beta = screen.getByRole("combobox", { name: "Beta Two" });
    await waitFor(() => expect(beta).toBeEnabled());
    expect(optionTexts("Beta Two")).toEqual([...BUILT_IN_NAMES, "Alpha Role"]);
    expect(selected("Alpha One")).toBe("Chatter");
    expect(selected("Beta Two")).toBe("Chatter");
  });

  it("assigning Beta Two a role and Saving sends one PUT keeping an unlisted Employee's assignment and an unknown key", async () => {
    const stored = { roles: [ALPHA], assignments: { "9": "role-alpha" }, extra_key: 1 };
    getReply = () => jsonRes({ tab: "roles", config: stored });
    mount();
    await loadedSelect("Beta Two");
    pick("Beta Two", "Alpha Role");
    fireEvent.click(saveButton());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...stored, assignments: { "9": "role-alpha", "2": "role-alpha" } });
  });

  it("changing two selects sends nothing until Save, then exactly one PUT with both", async () => {
    mount();
    await loadedSelect("Alpha One");
    pick("Alpha One", "Owner");
    await loadedSelect("Beta Two");
    pick("Beta Two", "Admin");
    expect(selected("Alpha One")).toBe("Owner");
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);

    fireEvent.click(saveButton());
    await waitFor(() => expect(puts()).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([{
      method: "PUT",
      url: "/admin/settings/roles",
      body: { roles: [], assignments: { "1": "owner", "2": "admin" } },
    }]);
  });

  /** Clicks "Delete" on the row named `name` once the blob has loaded. */
  const deleteRole = async (name: string) => {
    await waitFor(() => expect(addRole()).toBeEnabled());
    const row = within(screen.getByRole("table", { name: "Roles" })).getByRole("cell", { name }).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
  };

  it("Delete on a role an Employee holds is refused, as Infloww refuses it, and sends no PUT", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [ALPHA, BETA], assignments: { "9": "role-alpha" } } });
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    const confirm = vi.spyOn(window, "confirm");
    mount();
    await deleteRole("Alpha Role");

    expect(alert).toHaveBeenCalledWith("This role is in use and cannot be deleted. Give its Employees another role first.");
    expect(confirm).not.toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
  });

  it("Delete on a role no Employee holds confirms, then saves the roles without it and the assignments unchanged", async () => {
    const stored = { roles: [ALPHA, BETA], assignments: { "1": "role-alpha" } };
    getReply = () => jsonRes({ tab: "roles", config: stored });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount();
    await deleteRole("Beta Role");

    expect(confirm).toHaveBeenCalledWith('Delete the role "Beta Role"?');
    await waitFor(() => expect(puts()).toHaveLength(1));
    const body = puts()[0].body as { roles: { id: string }[]; assignments: unknown };
    expect(body.roles.map((r) => r.id)).toEqual(["owner", "admin", "team-leader", "chatter", "creator", "role-alpha"]);
    expect(body.assignments).toEqual({ "1": "role-alpha" });
  });

  it("a custom role's Status switch saves disabled at once, confirming when an active Employee holds it; built-ins stay on", async () => {
    // Beta Role grants pages and Beta Two holds it; Alpha Role is held by no one.
    const stored = { roles: [ALPHA, BETA], assignments: { "2": "role-beta" } };
    getReply = () => jsonRes({ tab: "roles", config: stored });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    mount();
    await waitFor(() => expect(screen.getByRole("switch", { name: "Alpha Role status" })).toBeEnabled());
    expect(screen.getByRole("switch", { name: "Owner status" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Owner status" })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("switch", { name: "Alpha Role status" }));
    expect(confirm).not.toHaveBeenCalled();
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ ...stored, roles: [OWNER, ADMIN, ...DEFAULT_ROLES, { ...ALPHA, disabled: true }, BETA] });

    await waitFor(() => expect(screen.getByRole("switch", { name: "Beta Role status" })).toBeEnabled());
    fireEvent.click(screen.getByRole("switch", { name: "Beta Role status" }));
    expect(confirm).toHaveBeenCalledWith('Disable the role "Beta Role"? 1 active Employee holds it and will be refused every page.');
    await waitFor(() => expect(puts()).toHaveLength(2));
    // A disabled role grants no page: the warning counts Beta Two, and its select names the role disabled.
    expect(await screen.findByText(/1 active Employee holds a role granting no page/)).toBeInTheDocument();
    expect(selected("Beta Two")).toBe("Beta Role (disabled)");
  });

  it("a built-in role stored disabled still reads on, as the Relay ignores it", async () => {
    getReply = () => jsonRes({ tab: "roles", config: { roles: [{ ...ADMIN, disabled: true }], assignments: {} } });
    mount();
    await waitFor(() => expect(screen.getByRole("switch", { name: "Admin status" })).toHaveAttribute("aria-checked", "true"));
  });

  it("an assignment naming a role id no role has shows as \"Unknown role\" and is kept on Save", async () => {
    const stored = { roles: [ALPHA], assignments: { "1": "role-gone", "2": "role-alpha" } };
    getReply = () => jsonRes({ tab: "roles", config: stored });
    mount();
    await loadedSelect("Alpha One");
    expect(selected("Alpha One")).toBe("Unknown role (role-gone)");
    expect(optionTexts("Alpha One")).toEqual([...BUILT_IN_NAMES, "Alpha Role", "Unknown role (role-gone)"]);
    expect(optionTexts("Beta Two")).toHaveLength(6);
    pick("Beta Two", "Owner");
    fireEvent.click(saveButton());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ roles: [ALPHA], assignments: { "1": "role-gone", "2": "owner" } });
  });

  describe("Enforce role permissions", () => {
    it("is on by default, as the Relay reads a never-stored switch, with no note", async () => {
      mount();
      expect(await enforceSwitch()).toHaveAttribute("aria-checked", "true");
      expect(screen.queryByText(NOT_ENFORCED)).toBeNull();
    });

    it("turning it on confirms with the count of active Employees whose role grants no page, then saves enforce and drops the note",
      async () => {
        // Alpha One holds a role no role has, Beta Two Alpha Role (no page ticked); Gamma Three is disabled and not counted.
        const stored = {
          enforce: false, roles: [ALPHA], assignments: { "1": "role-gone", "2": "role-alpha", "3": "role-alpha" },
        };
        getReply = () => jsonRes({ tab: "roles", config: stored });
        const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
        mount();
        await loadedSelect("Beta Two");
        fireEvent.click(await enforceSwitch());

        expect(confirm).toHaveBeenCalledTimes(1);
        expect(confirm.mock.calls[0][0]).toContain("2 active Employees hold a role granting no page and will be refused every page");
        await waitFor(() => expect(puts()).toHaveLength(1));
        expect(puts()[0].body).toEqual({ ...stored, enforce: true });
        await waitFor(() => expect(screen.getByRole("switch", { name: "Enforce role permissions" }))
          .toHaveAttribute("aria-checked", "true"));
        expect(screen.queryByText(NOT_ENFORCED)).toBeNull();
      });

    it("names one Employee in the singular; an unassigned one reads as Chatter, which grants pages", async () => {
      getReply = () =>
        jsonRes({ tab: "roles", config: { enforce: false, roles: [ALPHA], assignments: { "1": "role-alpha" } } });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      mount();
      await loadedSelect("Beta Two");
      fireEvent.click(await enforceSwitch());
      expect(confirm.mock.calls[0][0]).toContain("1 active Employee holds a role granting no page and will be refused every page");
    });

    it("turning it on with every active Employee granted a page asks nothing", async () => {
      getReply = () => jsonRes({ tab: "roles", config: { enforce: false, assignments: { "1": "admin" } } });
      const confirm = vi.spyOn(window, "confirm");
      mount();
      await loadedSelect("Beta Two");
      fireEvent.click(await enforceSwitch());
      await waitFor(() => expect(puts()).toHaveLength(1));
      expect(confirm).not.toHaveBeenCalled();
      expect(puts()[0].body).toEqual({ roles: [], enforce: true, assignments: { "1": "admin" } });
    });

    it("while on, a warning counts the active Employees whose role grants no page; none, no warning", async () => {
      getReply = () => jsonRes({
        tab: "roles", config: { roles: [ALPHA], assignments: { "1": "role-alpha", "2": "role-gone", "3": "role-alpha" } },
      });
      mount();
      await loadedSelect("Beta Two");
      expect(await screen.findByText("2 active Employees hold a role granting no page and are refused every page."))
        .toBeInTheDocument();
      pick("Alpha One", "Chatter");
      expect(await screen.findByText("1 active Employee holds a role granting no page and is refused every page."))
        .toBeInTheDocument();
      pick("Beta Two", "Admin");
      await waitFor(() => expect(screen.queryByText(/a role granting no page/)).toBeNull());
    });

    it("declining the confirm saves nothing and leaves it off", async () => {
      getReply = () => jsonRes({ tab: "roles", config: { enforce: false, roles: [ALPHA], assignments: { "1": "role-alpha" } } });
      vi.spyOn(window, "confirm").mockReturnValue(false);
      mount();
      const sw = await enforceSwitch();
      fireEvent.click(sw);
      expect(sw).toHaveAttribute("aria-checked", "false");
      expect(screen.getByText(NOT_ENFORCED)).toBeInTheDocument();
      expect(puts()).toEqual([]);
    });

    it("stored on, it shows no note; turning it off saves at once with no confirm and brings the note back", async () => {
      const stored = { enforce: true, roles: [ALPHA], assignments: { "1": "role-alpha" } };
      getReply = () => jsonRes({ tab: "roles", config: stored });
      const confirm = vi.spyOn(window, "confirm");
      mount();
      const sw = await enforceSwitch();
      expect(sw).toHaveAttribute("aria-checked", "true");
      expect(screen.queryByText(NOT_ENFORCED)).toBeNull();
      fireEvent.click(sw);

      await waitFor(() => expect(puts()).toHaveLength(1));
      expect(confirm).not.toHaveBeenCalled();
      expect(puts()[0].body).toEqual({ ...stored, enforce: false });
      expect(await screen.findByText(NOT_ENFORCED)).toBeInTheDocument();
    });
  });
});
