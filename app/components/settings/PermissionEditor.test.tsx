import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import PermissionEditor, { optInNote, PAGE_HREFS, permissionTabs, type PermissionRole } from "@/components/settings/PermissionEditor";
import { SIDEBAR, type NavGroup, type NavNode } from "@/lib/nav";
import { CARD_PERMISSIONS, pageCards } from "@/lib/dashboardCards";
import { PAGE_ACTIONS } from "@/lib/permissionActions";

const ALL: string[] = [];
for (const n of SIDEBAR) {
  if ("divider" in n) continue;
  for (const l of "children" in n ? n.children : [n]) if (!l.permission) ALL.push(l.href);
}
const groupOf = (nodes: NavNode[], label: string) =>
  nodes.find((n): n is NavGroup => "children" in n && n.label === label)!;
const childHrefs = (label: string) => groupOf(SIDEBAR, label).children.filter((c) => !c.permission).map((c) => c.href);

const ROLE: PermissionRole = { id: "role-alpha", name: "Alpha Role", description: "", permissions: {}, scope: "self" };

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderEditor(canSave = true) {
  const onSave = vi.fn();
  const onBack = vi.fn();
  renderWithProviders(<PermissionEditor role={ROLE} onSave={onSave} onBack={onBack} canSave={canSave} />);
  return { onSave, onBack };
}

function hrefsOn(name: string): string[] {
  fireEvent.click(screen.getByRole("tab", { name }));
  return screen.getAllByRole("checkbox").map((c) => (c as HTMLInputElement).value).filter((v) => !v.includes("#"));
}

describe("PermissionEditor", () => {
  it("says My Automations and My AI Chatter are off for chatters until ticked, under those groups only", () => {
    renderEditor();
    const notes = screen.getAllByText(/^Off for chatters by default/);
    expect(notes.map((n) => [n.previousElementSibling?.textContent, n.textContent])).toEqual([
      ["My Automations", optInNote([])],
      ["My AI Chatter", optInNote(["Get to know fans"])],
    ]);
    expect(notes[0].textContent).toMatch(/^Off for chatters by default\. Tick/);
    expect(notes[1].textContent).toMatch(/^Off for chatters by default, except Get to know fans\. Tick/);
    expect(notes[0].getAttribute("title")).toBe("Inflowwww extra");
  });

  it("offers exactly the tabs Operations, Growth and OF Manager", () => {
    renderEditor();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Operations", "Growth", "OF Manager"]);
  });

  it("lists every SIDEBAR page exactly once across the tabs, Growth and OF Manager holding exactly their groups' children", () => {
    renderEditor();
    const growth = hrefsOn("Growth");
    const ofManager = hrefsOn("OF Manager");
    const operations = hrefsOn("Operations");
    expect(growth).toEqual(childHrefs("Growth"));
    expect(ofManager).toEqual(childHrefs("OF Manager"));
    const union = [...operations, ...growth, ...ofManager];
    expect(union).toHaveLength(ALL.length);
    expect([...union].sort()).toEqual([...ALL].sort());
    const titles = within(screen.getByRole("tabpanel")).getAllByRole("heading").map((h) => h.textContent);
    expect(titles).toEqual(["General", "Analytics", "Share for Share", "My Automations", "My AI Chatter", "Creators", "Employees"]);
    expect(operations.slice(0, 3)).toEqual(["/", "/messages-pro", "/growth/vault-pro"]);
  });

  it("keys a role by every SIDEBAR page in nav order, nav.ts's PERMISSION_PAGES being the one list", () => {
    expect(PAGE_HREFS).toEqual(ALL);
  });

  it("files a fake SIDEBAR's added Growth child under Growth and its added top-level link under Operations' General", () => {
    const fake: NavNode[] = SIDEBAR.map((n) =>
      "children" in n && n.label === "Growth"
        ? { ...n, children: [...n.children, { label: "Fake Growth Page", href: "/growth/fake" }] }
        : n,
    );
    fake.push({ label: "Fake Top Page", href: "/fake-top" });
    const tabs = permissionTabs(fake);
    const pages = (tab: string, title: string) =>
      tabs.find((t) => t.tab === tab)!.groups.find((g) => g.title === title)!.pages.map((p) => p.href);
    expect(pages("Growth", "Growth")).toEqual([...childHrefs("Growth"), "/growth/fake"]);
    expect(pages("Operations", "General")).toEqual([
      "/", "/messages-pro", "/growth/vault-pro", "/fake-top",
    ]);
  });

  it("files no link that answers to another page's grant (`permission`), top-level or a group's child", () => {
    const fake: NavNode[] = SIDEBAR.map((n) =>
      "children" in n && n.label === "Growth"
        ? { ...n, children: [...n.children, { label: "Fake Child", href: "/growth/fake", permission: "/messages-pro" }] }
        : n,
    );
    fake.push({ label: "Fake Top Page", href: "/fake-top", permission: "/messages-pro" });
    const hrefs = permissionTabs(fake).flatMap((t) => t.groups.flatMap((g) => g.pages.map((p) => p.href)));
    expect(hrefs).not.toContain("/growth/fake");
    expect(hrefs).not.toContain("/fake-top");
  });

  it("lists a page's Function permissions under it, usable only while the page is ticked, one switch per action", () => {
    const onSave = vi.fn();
    const role = { ...ROLE, permissions: { "/messages-pro": true, "/messages-pro#unsend": false } };
    renderWithProviders(<PermissionEditor role={role} onSave={onSave} onBack={vi.fn()} canSave />);
    const unsend = screen.getByRole("checkbox", { name: "Messages Pro: Unsend messages" });
    const exportCsv = screen.getByRole("checkbox", { name: "Messages Pro: Export CSV" });
    expect(unsend).not.toBeChecked();
    expect(exportCsv).toBeChecked();
    expect(unsend).toBeEnabled();
    expect(screen.getAllByRole("checkbox", { name: /^Dashboard: / }).every((c) => / card$/.test(c.getAttribute("aria-label")!)))
      .toBe(true);
    fireEvent.click(exportCsv);
    fireEvent.click(screen.getByRole("tab", { name: "Operations" }));
    const salesExport = screen.getByRole("checkbox", { name: "Sales records: Export CSV" });
    expect(salesExport).toBeDisabled();
    expect(salesExport).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const saved = onSave.mock.calls[0][0] as PermissionRole;
    const keys = Object.keys(PAGE_ACTIONS);
    for (const key of keys) expect(saved.permissions[key]).toBe(!/#(unsend|export)$/.test(key));
    expect(saved.permissions["/of-manager/messages#unsend"]).toBe(false);
    expect(Object.keys(saved.permissions).filter((k) => k.includes("#") && !(k in CARD_PERMISSIONS)).sort())
      .toEqual(keys.sort());
  });

  it("lists the Dashboard's cards under it, a stored false unticked, usable only while the Dashboard is ticked (5.12)", () => {
    const onSave = vi.fn();
    const role = { ...ROLE, permissions: { "/": true, "/#card-earnings": false, "/#card-per-model": false } };
    renderWithProviders(<PermissionEditor role={role} onSave={onSave} onBack={vi.fn()} canSave />);
    const rows = screen.getAllByRole("checkbox", { name: /^Dashboard: / });
    expect(rows.map((c) => c.getAttribute("aria-label")))
      .toEqual(pageCards("/").map(([, label]) => `Dashboard: ${label} card`));
    expect(screen.getByRole("checkbox", { name: "Dashboard: Per-model KPIs card" })).not.toBeChecked();
    const earnings = screen.getByRole("checkbox", { name: "Dashboard: Creator earnings overview card" });
    const sales = screen.getByRole("checkbox", { name: "Dashboard: Employee sales card" });
    expect(earnings).not.toBeChecked();
    expect(sales).toBeChecked();
    fireEvent.click(sales);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const saved = (onSave.mock.calls[0][0] as PermissionRole).permissions;
    expect(Object.fromEntries(Object.keys(CARD_PERMISSIONS).map((k) => [k, saved[k]]))).toEqual({
      "/#card-earnings": false, "/#card-employee-sales": false, "/#card-per-model": false });
    fireEvent.click(screen.getByRole("checkbox", { name: "Dashboard" }));
    expect(sales).toBeDisabled();
  });

  it("Back after a toggle calls onBack and sends nothing", () => {
    const { onSave, onBack } = renderEditor();
    fireEvent.click(screen.getByRole("checkbox", { name: "Dashboard" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables Save when canSave is false and enables it when true", () => {
    renderEditor(false);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    cleanup();
    renderEditor(true);
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });
});
