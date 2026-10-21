/**
 * GroupTree — Manage employees' group tree, the page's left column (the old Organization Chart tab, folded in by
 * page-parity ticket 17; docs/spec/phase-05-remaining-parity-gaps.md, item 4, stories 31-33).
 *
 * Rendered with the relay mocked at `fetch` by URL, as ManageEmployees.test.tsx does: the stub keeps the Agency's
 * groups (`GET`/`POST /admin/employee-groups`, `PATCH`/`DELETE /admin/employee-groups/{id}`) and serves the `account`
 * Settings blob that names the Agency, so the tree, Add sub-group and Delete group are assertions about the wire.
 * Every name is fake.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";

vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: { user_id: "u1", username: "fixture_owner" }, loading: false, logout: vi.fn() }),
}));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: null, logout: vi.fn() }) }));

import GroupTree from "@/components/employees/GroupTree";

type Group = { id: number; name: string; parent_id: number | null; employee_count: number };

/** Fixture Sales holds Fixture Nights; Fixture Support holds one Employee; Fixture Nights is empty. */
const GROUPS: Group[] = [
  { id: 1, name: "Fixture Sales", parent_id: null, employee_count: 0 },
  { id: 2, name: "Fixture Support", parent_id: null, employee_count: 1 },
  { id: 3, name: "Fixture Nights", parent_id: 1, employee_count: 0 },
];

let fetchMock: ReturnType<typeof vi.fn>;
let groups: Group[];
let agencyName: string;

function calls() {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const writes = () => calls().filter((c) => c.method !== "GET");

beforeEach(() => {
  groups = GROUPS.map((g) => ({ ...g }));
  agencyName = "Fixture Agency";
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/admin/settings/account") return jsonRes({ tab: "account", config: { agency_name: agencyName } });
    if (url === "/admin/employee-groups" && method === "GET") return jsonRes({ groups });
    if (url === "/admin/employee-groups" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as { name: string; parent_id: number | null };
      if (groups.some((g) => g.parent_id === body.parent_id && g.name === body.name.trim())) {
        return jsonRes({ detail: "a group of this name already sits here" }, 409);
      }
      const created = { id: 100 + groups.length, name: body.name.trim(), parent_id: body.parent_id, employee_count: 0 };
      groups = [...groups, created];
      return jsonRes(created);
    }
    const del = /^\/admin\/employee-groups\/(\d+)$/.exec(url);
    if (del && method === "PATCH") {
      const body = JSON.parse(String(init?.body)) as { name: string; parent_id: number | null };
      groups = groups.map((g) => (g.id === Number(del[1]) ? { ...g, ...body } : g));
      return jsonRes(groups.find((g) => g.id === Number(del[1])));
    }
    if (del && method === "DELETE") {
      groups = groups.filter((g) => g.id !== Number(del[1]));
      return jsonRes({ deleted: Number(del[1]) });
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

/** Each node of the chart as "  "×depth + name, in tree order. */
function tree(): string[] {
  const out: string[] = [];
  const walk = (list: HTMLElement, depth: number) => {
    for (const item of within(list).getAllByRole("listitem").filter((li) => li.parentElement === list)) {
      out.push("  ".repeat(depth) + item.getAttribute("aria-label"));
      const sub = Array.from(item.children).find((c) => c.tagName === "UL") as HTMLElement | undefined;
      if (sub) walk(sub, depth + 1);
    }
  };
  walk(screen.getByRole("list", { name: "Employee groups" }), 0);
  return out;
}

let onSelect: ReturnType<typeof vi.fn<(groupId: number | null) => void>>;
function mount(selected: number | null = null) {
  onSelect = vi.fn<(groupId: number | null) => void>();
  return renderWithProviders(<GroupTree selected={selected} onSelect={onSelect} />);
}

async function loaded(selected: number | null = null) {
  mount(selected);
  await waitFor(() => expect(tree()).toContain("    Fixture Nights"));
  await waitFor(() => expect(tree()[0]).toBe("Fixture Agency"));
}

function openMenu(node: string) {
  fireEvent.click(screen.getByRole("button", { name: `Actions for ${node}` }));
  return screen.getByRole("menu");
}

describe("GroupTree", () => {
  it("shows the Agency as the root and its groups as a tree", async () => {
    await loaded();
    expect(tree()).toEqual([
      "Fixture Agency",
      "  Fixture Sales",
      "    Fixture Nights",
      "  Fixture Support",
    ]);
  });

  it("falls back to the owner's username when the Agency has no name", async () => {
    agencyName = "";
    mount();
    await waitFor(() => expect(tree()[0]).toBe("fixture_owner"));
  });

  it("offers only Add sub-group on the Agency root", async () => {
    await loaded();
    const menu = openMenu("Fixture Agency");
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Add sub-group"]);
  });

  it("Add sub-group opens Add Group Settings and Submit creates a child under that node", async () => {
    await loaded();
    fireEvent.click(within(openMenu("Fixture Nights")).getByRole("menuitem", { name: "Add sub-group" }));
    const dialog = screen.getByRole("dialog", { name: "Add Group Settings" });
    const submit = within(dialog).getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Group name"), { target: { value: "  Fixture Late  " } });
    fireEvent.click(submit);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([
      { method: "POST", url: "/admin/employee-groups", body: { name: "Fixture Late", parent_id: 3 } },
    ]);
    await waitFor(() => expect(tree()).toEqual([
      "Fixture Agency",
      "  Fixture Sales",
      "    Fixture Nights",
      "      Fixture Late",
      "  Fixture Support",
    ]));
  });

  it("Add sub-group on the root sends a null parent", async () => {
    await loaded();
    fireEvent.click(within(openMenu("Fixture Agency")).getByRole("menuitem", { name: "Add sub-group" }));
    const dialog = screen.getByRole("dialog", { name: "Add Group Settings" });
    fireEvent.change(within(dialog).getByLabelText("Group name"), { target: { value: "Fixture Top" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(tree()).toContain("  Fixture Top"));
    expect(writes()).toEqual([
      { method: "POST", url: "/admin/employee-groups", body: { name: "Fixture Top", parent_id: null } },
    ]);
  });

  it("keeps the dialog open with the Relay's refusal when a sibling has the name", async () => {
    await loaded();
    fireEvent.click(within(openMenu("Fixture Agency")).getByRole("menuitem", { name: "Add sub-group" }));
    const dialog = screen.getByRole("dialog", { name: "Add Group Settings" });
    fireEvent.change(within(dialog).getByLabelText("Group name"), { target: { value: "Fixture Sales" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(within(dialog).getByRole("alert").textContent)
      .toBe("a group of this name already sits here"));
    expect(screen.getByRole("dialog", { name: "Add Group Settings" })).toBeTruthy();
  });

  it("Edit group renames and moves a group, never offering itself or its own sub-groups as the parent", async () => {
    await loaded();
    fireEvent.click(within(openMenu("Fixture Sales")).getByRole("menuitem", { name: "Edit group" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Group Settings" });
    expect(within(dialog).getByLabelText("Group name")).toHaveValue("Fixture Sales");
    fireEvent.click(within(dialog).getByRole("combobox", { name: "Parent group" }));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Fixture Agency", "Fixture Support"]);
    fireEvent.click(screen.getByRole("option", { name: "Fixture Support" }));
    fireEvent.change(within(dialog).getByLabelText("Group name"), { target: { value: "Fixture Closers" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toEqual([
      { method: "PATCH", url: "/admin/employee-groups/1", body: { name: "Fixture Closers", parent_id: 2 } },
    ]);
    await waitFor(() => expect(tree()).toEqual([
      "Fixture Agency",
      "  Fixture Support",
      "    Fixture Closers",
      "      Fixture Nights",
    ]));
  });

  it("enables Delete group only on a group with no sub-groups and no Employees", async () => {
    await loaded();
    const item = (node: string) => within(openMenu(node)).getByRole("menuitem", { name: "Delete group" });
    expect(item("Fixture Sales")).toBeDisabled(); // holds Fixture Nights
    fireEvent.click(screen.getByRole("button", { name: "Actions for Fixture Sales" }));
    expect(item("Fixture Support")).toBeDisabled(); // holds one Employee
    fireEvent.click(screen.getByRole("button", { name: "Actions for Fixture Support" }));
    const nights = item("Fixture Nights");
    expect(nights).toBeEnabled();
    fireEvent.click(nights);
    await waitFor(() => expect(tree()).toEqual(["Fixture Agency", "  Fixture Sales", "  Fixture Support"]));
    expect(writes()).toEqual([{ method: "DELETE", url: "/admin/employee-groups/3", body: undefined }]);
    // Fixture Sales is empty now.
    expect(item("Fixture Sales")).toBeEnabled();
  });
});

describe("GroupTree picking", () => {
  it("marks the picked node and reports a pick: a group's id, or null for the Agency root", async () => {
    await loaded(3);
    expect(screen.getByRole("button", { name: "Fixture Nights" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Fixture Agency" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Fixture Support" }));
    expect(onSelect).toHaveBeenLastCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "Fixture Agency" }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("collapses and expands a node's sub-groups with its caret", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Collapse Fixture Sales" }));
    expect(tree()).toEqual(["Fixture Agency", "  Fixture Sales", "  Fixture Support"]);
    fireEvent.click(screen.getByRole("button", { name: "Expand Fixture Sales" }));
    expect(tree()).toContain("    Fixture Nights");
    // A group with no sub-groups has no caret.
    expect(screen.queryByRole("button", { name: /Collapse Fixture Support/ })).toBeNull();
  });

  it("colours Add sub-group #2d74ff and Delete group #e05757, and Add Group Settings has a 40px name field", async () => {
    await loaded();
    const menu = within(openMenu("Fixture Nights"));
    expect(menu.getByRole("menuitem", { name: "Add sub-group" }).className).toContain("text-[#2d74ff]");
    expect(menu.getByRole("menuitem", { name: "Delete group" }).className).toContain("text-[#e05757]");
    fireEvent.click(menu.getByRole("menuitem", { name: "Add sub-group" }));
    const field = within(screen.getByRole("dialog", { name: "Add Group Settings" })).getByLabelText("Group name");
    expect(field.parentElement!.className).toContain("h-10");
  });
});

