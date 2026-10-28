import { describe, expect, it, vi } from "vitest";

import {
  CHATTER_OPT_IN_PAGES,
  FANSLY_NAV,
  PERMISSION_PAGES,
  SETTINGS_TABS,
  SIDEBAR,
  SIDEBAR_FOOTER,
  allNavLinks,
  deniedPage,
  findNavLink,
  firstPage,
  hasCreatorColumn,
  isDivider,
  isGroup,
  isPlatformPage,
  openPopout,
  platformOfPath,
  sessionGrantedPages,
  sidebarFor,
  sidebarHref,
  visibleLinks,
  visibleSidebar,
  type NavNode,
} from "@/lib/nav";
import { mirrorPageOfHref } from "@/lib/of-mirror-route";

const OWNER = { chatterOnly: false, grantedPages: null };

/** "Label" for links, "Label: Sub / Sub" for groups, "—" for the divider. */
function outline(nodes: NavNode[]): string[] {
  return nodes.map((n) =>
    isDivider(n) ? "—" : isGroup(n) ? `${n.label}: ${n.children.map((c) => c.label).join(" / ")}` : n.label,
  );
}

describe("sidebar (docs/infloww-screens.md §1.1)", () => {
  it("has Infloww's items and sub-items verbatim, plus My Automations", () => {
    expect(outline(visibleSidebar(SIDEBAR, OWNER))).toEqual([
      "Dashboard",
      "OF Manager: Home / Go live / New post / Notifications / Messages Basic / Vault / Queue / Collections / Bookmarks / Statements / Statistics / Bank / My profile / Release forms / OF settings",
      // Four entries, as live 07-analytics-menu.png: Sales records is Employee reports' tab (page-parity ticket 27).
      "Analytics: Creator reports / Employee reports / Fan reports / Message dashboard",
      "Messages Pro",
      "Growth: Smart Messages / Smart lists / Auto-follow / Vault Pro / Scripts / Profile promotion / Free trial links / Tracking links / Sensitive words",
      "Share for Share: Discover creators / Requests / S4S schedule / S4S settings",
      "My Automations: Auto Post / Auto Story / Auto Mass / Auto-reply / Auto Funnel / Get to know fans / Gen-Info",
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
    expect(visibleLinks(SIDEBAR_FOOTER, OWNER).map((l) => l.label)).toEqual(["Settings", "Help center"]);
  });

  it("My Automations is exactly Auto Post + Auto Story + Auto Mass + Auto-reply + Auto Funnel + Get to know fans + Gen-Info", () => {
    const g = visibleSidebar(SIDEBAR, OWNER).find((n) => isGroup(n) && n.label === "My Automations");
    expect(g && isGroup(g) && g.children.map((c) => [c.label, c.href])).toEqual([
      ["Auto Post", "/growth/auto-post"],
      ["Auto Story", "/growth/auto-story"],
      ["Auto Mass", "/growth/auto-mass"],
      ["Auto-reply", "/growth/auto-reply"],
      ["Auto Funnel", "/growth/auto-funnel"],
      ["Get to know fans", "/growth/get-to-know-fans"],
      ["Gen-Info", "/growth/gen-info"],
    ]);
  });

  it("shows an owner every Settings tab but the master's System tab", () => {
    expect(visibleLinks(SETTINGS_TABS, OWNER)).toHaveLength(14);
  });

  it("hides owner-only sections from a chatter-only session", () => {
    const labels = outline(visibleSidebar(SIDEBAR, { chatterOnly: true, grantedPages: null }));
    expect(labels).not.toContain("Creators: Manage creators / Custom proxy");
    // Only its `notOptIn` page, whose Model info is the account's.
    expect(labels).toContain("My Automations: Get to know fans");
    expect(labels).toContain("Growth: Smart Messages / Scripts");
  });

  it("My Automations is opt-in for a chatter: only the pages an enforcing role grants", () => {
    expect([...CHATTER_OPT_IN_PAGES]).toEqual([
      "/growth/auto-post", "/growth/auto-story", "/growth/auto-mass", "/growth/auto-reply", "/growth/auto-funnel",
      "/growth/gen-info",
    ]);
    const automations = (chatterOnly: boolean, permissions?: { pages: string[] | null; opt_in?: string[] }) =>
      outline(visibleSidebar(SIDEBAR, {
        chatterOnly, grantedPages: sessionGrantedPages(chatterOnly, permissions),
      })).find((l) => l.startsWith("My Automations")) ?? null;
    // Enforcement off, the read not answered yet, or the unstored built-in Admin (`pages: null`,
    // `opt_in: []`): the opt-in pages hidden, Get to know fans (not opt-in) granted like any page.
    expect(automations(true, { pages: null, opt_in: [] })).toBe("My Automations: Get to know fans");
    expect(automations(true, undefined)).toBe("My Automations: Get to know fans");
    expect(automations(true, { pages: ["/growth/get-to-know-fans"], opt_in: [] })).toBe("My Automations: Get to know fans");
    // A role granting nothing of it, then one ticking Auto Mass only (`opt_in`, the relay's word).
    expect(automations(true, { pages: ["/messages-pro"], opt_in: [] })).toBeNull();
    expect(automations(true, { pages: ["/messages-pro", "/growth/auto-mass"], opt_in: ["/growth/auto-mass"] }))
      .toBe("My Automations: Auto Mass");
    // `pages` alone grants none: a two-agency chatter's `opt_in` is the union, `pages` is not.
    expect(automations(true, { pages: ["/growth/auto-mass"] })).toBeNull();
    expect(automations(true, { pages: ["/messages-pro"], opt_in: ["/growth/auto-mass"] }))
      .toBe("My Automations: Auto Mass");
    // An owner always sees it all.
    const all = "My Automations: Auto Post / Auto Story / Auto Mass / Auto-reply / Auto Funnel / Get to know fans / Gen-Info";
    expect(automations(false, { pages: null })).toBe(all);
    // Opened by URL: denied to the chatter without the grant, every other page open.
    const off = sessionGrantedPages(true, { pages: null, opt_in: [] });
    expect(deniedPage("/growth/auto-mass", off)).toBe("/growth/auto-mass");
    expect(deniedPage("/growth/smart-messages", off)).toBeNull();
    expect(deniedPage("/growth/auto-mass", sessionGrantedPages(true, { pages: null, opt_in: ["/growth/auto-mass"] })))
      .toBeNull();
  });

  it("builds every Share for Share page (no placeholder), all four hidden from a chatter", () => {
    const g = SIDEBAR.find((n) => isGroup(n) && n.label === "Share for Share");
    const items = g && isGroup(g) ? g.children : [];
    expect(items.map((c) => c.href)).toEqual([
      "/share-for-share/discover-creators",
      "/share-for-share/requests",
      "/share-for-share/schedule",
      "/share-for-share/settings",
    ]);
    expect(items.filter((c) => c.notBuilt)).toEqual([]);
    expect(items.filter((c) => !c.chatterHidden)).toEqual([]);
    const labels = outline(visibleSidebar(SIDEBAR, { chatterOnly: true, grantedPages: null }));
    expect(labels.some((l) => l.startsWith("Share for Share"))).toBe(false);
  });

  it("builds every OF Manager page (the OF mirror, no placeholder)", () => {
    const g = SIDEBAR.find((n) => isGroup(n) && n.label === "OF Manager");
    const items = g && isGroup(g) ? g.children : [];
    expect(items.filter((c) => c.notBuilt)).toEqual([]);
    expect(items.map((c) => c.href).filter((h) => !mirrorPageOfHref(h))).toEqual([]);
  });

  it("builds every Settings tab (no placeholder), the six Blob tabs, Security (organization), AI keys and the Audit log hidden from a Chatter", () => {
    expect(SETTINGS_TABS.filter((t) => t.notBuilt)).toEqual([]);
    expect(SETTINGS_TABS.filter((t) => t.chatterHidden).map((t) => t.href)).toEqual([
      "/settings/account",
      "/settings/preferences",
      "/settings/security-org",
      "/settings/roles",
      "/settings/sales",
      "/settings/time-tracking",
      "/settings/messaging",
      "/settings/cotag",
      "/settings/ai-keys",
      "/settings/audit",
    ]);
  });

  it("keeps Sales records last under Analytics as Employee reports' tab: a Permission page, never a sidebar entry", () => {
    const analytics = SIDEBAR.find((n) => isGroup(n) && n.label === "Analytics");
    const sales = analytics && isGroup(analytics) ? analytics.children.at(-1) : undefined;
    expect(sales).toEqual({
      label: "Sales records",
      href: "/analytics/sales-records",
      tabOf: "/analytics/employee-reports",
    });
    expect(PERMISSION_PAGES.has("/analytics/sales-records")).toBe(true);
    expect(visibleLinks([sales!], OWNER)).toEqual([]);
    expect(deniedPage("/analytics/sales-records", new Set(["/analytics/employee-reports"])))
      .toBe("/analytics/sales-records");
    // Its route lights Employee reports in the sidebar; every other path answers as itself.
    expect(sidebarHref("/analytics/sales-records")).toBe("/analytics/employee-reports");
    expect(sidebarHref("/analytics/fan-reports")).toBe("/analytics/fan-reports");
  });

  it("shows Sales records as its own Analytics entry to a role granting it without Employee reports", () => {
    const grantedPages = new Set(["/analytics/sales-records"]);
    const f = { chatterOnly: false, grantedPages };
    const analytics = visibleSidebar(SIDEBAR, f).find((n) => isGroup(n) && n.label === "Analytics");
    expect(analytics && isGroup(analytics) ? analytics.children.map((c) => c.href) : []).toEqual([
      "/analytics/sales-records",
    ]);
    expect(deniedPage("/analytics/sales-records", grantedPages)).toBeNull();
    // Its route lights its own entry, as Employee reports is not drawn.
    expect(sidebarHref("/analytics/sales-records", grantedPages)).toBe("/analytics/sales-records");
    // Granted both, it rides Employee reports again.
    const both = new Set([...grantedPages, "/analytics/employee-reports"]);
    expect(visibleLinks(SIDEBAR.flatMap((n) => (isGroup(n) ? n.children : [])), { ...f, grantedPages: both })
      .some((l) => l.href === "/analytics/sales-records")).toBe(false);
  });

  it("draws the master-only System tab for the master alone, never for a chatter", () => {
    const system = (f: Parameters<typeof visibleLinks>[1]) =>
      visibleLinks(SETTINGS_TABS, f).some((t) => t.href === "/settings/system");
    expect(SETTINGS_TABS.filter((t) => t.masterOnly).map((t) => t.href)).toEqual(["/settings/system"]);
    expect(system(OWNER)).toBe(false);
    expect(system({ ...OWNER, master: false })).toBe(false);
    expect(system({ ...OWNER, master: true })).toBe(true);
    expect(system({ ...OWNER, master: true, chatterOnly: true })).toBe(false);
  });

  it("gives every link its own route", () => {
    const hrefs = allNavLinks().map((l) => l.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

describe("granted pages (spec phase-04, stories 33-34)", () => {
  const sidebarHrefs = (granted: Set<string> | null) =>
    visibleSidebar(SIDEBAR, { chatterOnly: false, grantedPages: granted }).flatMap((n) =>
      isDivider(n) ? [] : isGroup(n) ? n.children.map((c) => c.href) : [n.href],
    );

  it("hides every Permission-editor page the role does not grant, and drops emptied groups", () => {
    const granted = new Set(["/", "/messages-pro", "/analytics/employee-reports"]);
    const nodes = visibleSidebar(SIDEBAR, { chatterOnly: false, grantedPages: granted });
    expect(outline(nodes)).toEqual(["Dashboard", "Analytics: Employee reports", "Messages Pro", "—"]);
  });

  it("leaves the footer and the Settings tabs alone: neither is a Permission-editor page", () => {
    expect(sidebarHrefs(new Set())).toEqual([]);
    const none = { chatterOnly: false, grantedPages: new Set<string>() };
    expect(visibleLinks(SIDEBAR_FOOTER, none)).toEqual(visibleLinks(SIDEBAR_FOOTER, OWNER));
    expect(visibleLinks(SETTINGS_TABS, none)).toEqual(visibleLinks(SETTINGS_TABS, OWNER));
  });

  it("pages: null shows the same sidebar as every Permission-editor page granted", () => {
    const all = { ...OWNER, grantedPages: new Set(PERMISSION_PAGES) };
    expect(visibleSidebar(SIDEBAR, all)).toEqual(visibleSidebar(SIDEBAR, OWNER));
  });

  it("names the denied page a path sits under, or null", () => {
    const granted = new Set(["/", "/employees/shifts"]);
    expect(deniedPage("/messages-pro/acc-1/42", granted)).toBe("/messages-pro");
    expect(deniedPage("/employees", granted)).toBe("/employees");
    // The old Organization Chart route (now a redirect to /employees) is guarded by Manage employees' permission.
    expect(deniedPage("/employees/org-chart", granted)).toBe("/employees");
    expect(deniedPage("/employees/shifts", granted)).toBeNull();
    expect(deniedPage("/", granted)).toBeNull();
    expect(deniedPage("/settings/about", granted)).toBeNull();
    // The full Notifications page (top bar bell > "See all") is not a Permission-editor page.
    expect(deniedPage("/notifications", granted)).toBeNull();
    expect(deniedPage("/messages-pro", null)).toBeNull();
  });
});

describe("platform nav map (Infloww's fanslyMenu, index.9f50f370.js @10699639)", () => {
  it("OnlyFans mode is the sidebar as it was", () => {
    expect(sidebarFor("onlyfans")).toBe(SIDEBAR);
  });

  it("Fansly mode: Fansly Manager, Scripts, Message pro, Vault pro, the divider, Creators and Employees", () => {
    expect(outline(visibleSidebar(sidebarFor("fansly"), OWNER))).toEqual([
      "Fansly Manager: Homepage / Profile / Subscriptions / Media Vault / Media Collection / Bookmarks / Messages / Creator Dashboard / Profile Statistics / Tracking Links / Referrals / Settings",
      "Scripts",
      "Message pro",
      "Vault pro",
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
  });

  it("with fansly_manager on, the Fansly Manager also shows its four built pages, in Infloww's order", () => {
    expect(outline(visibleSidebar(sidebarFor("fansly"), { ...OWNER, flags: { fansly_manager: true } }))[0]).toBe(
      "Fansly Manager: Homepage / Profile / Subscriptions / Media Vault / Media Collection / Scheduled Posts / Lists / Bookmarks / Messages / Notifications / Creator Dashboard / Earning Statistics / Profile Statistics / Tracking Links / Referrals / Settings",
    );
  });

  it("each flagged Fansly Manager page answers to its OnlyFans counterpart's Permission page, in the rail and by URL", () => {
    const pages: [string, string][] = [
      ["/fansly-manager/scheduled", "/of-manager/queue"],
      ["/fansly-manager/lists", "/of-manager/collections"],
      ["/fansly-manager/notifications", "/of-manager/notifications"],
      ["/fansly-manager/earning-statistics", "/analytics/creator-reports"],
    ];
    const on = { fansly_manager: true };
    for (const [href, permission] of pages) {
      expect(findNavLink(href)?.permission).toBe(permission);
      expect(PERMISSION_PAGES.has(permission)).toBe(true);
      const granted = new Set([...PERMISSION_PAGES].filter((p) => p !== permission));
      const chatter = { chatterOnly: true, grantedPages: granted, flags: on };
      expect(outline(visibleSidebar(sidebarFor("fansly"), chatter))[0]).not.toContain(findNavLink(href)!.label);
      expect(deniedPage(href, granted)).toBe(permission);
      expect(deniedPage(href, new Set([permission]))).toBeNull();
      expect(deniedPage(href, null)).toBeNull();
    }
    // A Messages Pro grant alone opens none of them.
    const mp = { chatterOnly: true, grantedPages: new Set(["/messages-pro"]), flags: on };
    expect(outline(visibleSidebar(sidebarFor("fansly"), mp))[0]).not.toMatch(/Scheduled Posts|Lists|Notifications|Earning Statistics/);
  });

  it("Fansly's built pages are OnlyFans' own routes or flagged Fansly Manager pages; the rest are placeholders", () => {
    const links = FANSLY_NAV.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
    expect(links.filter((l) => l.flag).map((l) => [l.href, l.flag, !!l.notBuilt])).toEqual([
      ["/fansly-manager/scheduled", "fansly_manager", false],
      ["/fansly-manager/lists", "fansly_manager", false],
      ["/fansly-manager/notifications", "fansly_manager", false],
      ["/fansly-manager/earning-statistics", "fansly_manager", false],
    ]);
    const built = links.filter((l) => !l.notBuilt && !l.flag).map((l) => l.href);
    expect(built).toEqual(["/growth/scripts", "/messages-pro", "/growth/vault-pro"]);
    const onlyfans = new Set(SIDEBAR.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n])).map((l) => l.href));
    for (const href of built) expect(onlyfans.has(href)).toBe(true);
    for (const l of links.filter((x) => x.notBuilt)) {
      expect(l.href.startsWith("/fansly-manager/")).toBe(true);
      expect(findNavLink(l.href)?.notBuilt).toBe(true);
    }
  });

  it("a chatter's Fansly rail hides Vault pro, as its OnlyFans one does", () => {
    const chatter = { chatterOnly: true, grantedPages: null };
    expect(outline(visibleSidebar(sidebarFor("fansly"), chatter))).not.toContain("Vault pro");
  });

  it("platformOfPath: a page only one platform shows, else null", () => {
    expect(platformOfPath("/")).toBe("onlyfans");
    expect(platformOfPath("/analytics/fan-reports")).toBe("onlyfans");
    expect(platformOfPath("/of-manager/home")).toBe("onlyfans");
    expect(platformOfPath("/fansly-manager/home")).toBe("fansly");
    // Shared by both platforms, or common.
    expect(platformOfPath("/growth/scripts")).toBeNull();
    expect(platformOfPath("/growth/vault-pro")).toBeNull();
    expect(platformOfPath("/messages-pro")).toBeNull();
    expect(platformOfPath("/messages-pro/acc1/123")).toBeNull();
    expect(platformOfPath("/creators")).toBeNull();
    expect(platformOfPath("/settings/general")).toBeNull();
  });

  it("isPlatformPage: Fansly's own and shared pages, not the common ones", () => {
    expect(isPlatformPage("fansly", "/fansly-manager/lists")).toBe(true);
    expect(isPlatformPage("fansly", "/growth/scripts")).toBe(true);
    expect(isPlatformPage("fansly", "/creators")).toBe(false);
    expect(isPlatformPage("fansly", "/analytics/fan-reports")).toBe(false);
  });

  it("a `flag` link shows only while its flag is on; an absent flags map is every flag off", () => {
    const nodes: NavNode[] = [
      { label: "Dark", href: "/dark", flag: "fansly_manager" },
      { label: "Group", icon: FANSLY_NAV.filter(isGroup)[0].icon, children: [{ label: "Dark child", href: "/dark/child", flag: "fansly_manager" }] },
      { label: "Lit", href: "/lit" },
    ];
    expect(outline(visibleSidebar(nodes, OWNER))).toEqual(["Lit"]);
    expect(outline(visibleSidebar(nodes, { ...OWNER, flags: { fansly_manager: false } }))).toEqual(["Lit"]);
    expect(outline(visibleSidebar(nodes, { ...OWNER, flags: { fansly_manager: true } }))).toEqual([
      "Dark", "Group: Dark child", "Lit",
    ]);
  });

  it("firstPage: the first built page that is not a window", () => {
    expect(firstPage("onlyfans")).toBe("/");
    expect(firstPage("fansly")).toBe("/growth/scripts");
  });
});

describe("openPopout", () => {
  it("opens the Messages Pro window on the link itself when a blank window is refused (the desktop app's open handler)", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    openPopout("/messages-pro/acc1/123");
    expect(open.mock.calls).toEqual([
      ["", "messages-pro", "popup,width=1470,height=915"],
      ["/messages-pro/acc1/123", "messages-pro", "popup,width=1470,height=915"],
    ]);
    open.mockRestore();
  });
});

describe("hasCreatorColumn", () => {
  it("is OF Manager only", () => {
    expect(hasCreatorColumn("/of-manager/home")).toBe(true);
    expect(hasCreatorColumn("/messages-pro")).toBe(false);
    expect(hasCreatorColumn("/of-managerx")).toBe(false);
  });
});
