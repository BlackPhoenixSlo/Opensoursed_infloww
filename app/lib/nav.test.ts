import { describe, expect, it, vi } from "vitest";
import { Users } from "lucide-react";

vi.mock("@/lib/plugins.generated.register", () => ({ PLUGINS: [] }));

import {
  CHATTER_OPT_IN_PAGES,
  FANSLY_NAV,
  PERMISSION_PAGES,
  SETTINGS_TABS,
  SIDEBAR,
  SIDEBAR_FOOTER,
  allNavLinks,
  deniedPage,
  drawnSidebar,
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

function outline(nodes: NavNode[]): string[] {
  return nodes.map((n) =>
    isDivider(n) ? "—" : isGroup(n) ? `${n.label}: ${n.children.map((c) => c.label).join(" / ")}` : n.label,
  );
}

describe("sidebar (docs/infloww-screens.md §1.1)", () => {
  it("has Infloww's items and sub-items verbatim, plus Vault Pro, My Automations and Full AI Chat", () => {
    expect(outline(drawnSidebar(SIDEBAR, OWNER))).toEqual([
      "Dashboard",
      "OF Manager: Home / Go live / New post / Notifications / Messages Basic / Vault / Queue / Collections / Bookmarks / Statements / Statistics / Bank / My profile / Release forms / OF settings",
      "Analytics: Creator reports / Employee reports / Fan reports / Message dashboard",
      "Messages Pro",
      "Vault Pro",
      "Growth: Smart Messages / Smart lists / Auto-follow / Scripts / Profile promotion / Free trial links / Tracking links / Redirect links / Bio pages / Sensitive words",
      "Share for Share: Discover creators / Requests / S4S schedule / S4S settings",
      "My Automations: Auto Mass / Auto Post / Auto Story / Auto Funnel / Gen-Info / Full AI Chat",
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
    expect(visibleLinks(SIDEBAR_FOOTER, OWNER).map((l) => l.label)).toEqual(["Settings", "Help center"]);
  });

  it("draws neither the My AI Chatter group nor Auto-reply, Get to know fans or AI rules, yet keeps their gates (owner 11-15)", () => {
    const labels = (f: Parameters<typeof drawnSidebar>[1]) =>
      drawnSidebar(SIDEBAR, f).flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? [n.label, ...n.children.map((c) => c.label)] : [n.label]));
    const everything = { chatterOnly: true, grantedPages: new Set(PERMISSION_PAGES) };
    for (const f of [OWNER, everything]) {
      for (const gone of ["My AI Chatter", "Auto-reply", "Get to know fans", "AI rules"]) expect(labels(f)).not.toContain(gone);
    }
    for (const href of ["/growth/auto-reply", "/growth/get-to-know-fans", "/full-ai-chatter", "/ai-rules"]) {
      expect(PERMISSION_PAGES.has(href)).toBe(true);
      expect(findNavLink(href)).toBeDefined();
      expect(deniedPage(href, new Set(["/"]))).toBe(href);
      expect(deniedPage(href, new Set([href]))).toBeNull();
    }
    expect(CHATTER_OPT_IN_PAGES.has("/growth/auto-reply")).toBe(true);
    for (const href of ["/growth/get-to-know-fans", "/full-ai-chatter", "/ai-rules"]) expect(CHATTER_OPT_IN_PAGES.has(href)).toBe(false);
    expect(sidebarHref("/ai-rules")).toBe("/full-ai-chatter");
    expect(outline(drawnSidebar(SIDEBAR, { chatterOnly: false, grantedPages: new Set(["/ai-rules"]) }))).toEqual(["My Automations: AI rules", "—"]);
  });

  it("My Automations has the automation pages in the requested order; the hidden My AI Chatter group the AI chat lanes", () => {
    const group = (label: string) => {
      const g = visibleSidebar(SIDEBAR, OWNER).find((n) => isGroup(n) && n.label === label);
      return g && isGroup(g) && { optIn: g.chatterOptIn, children: g.children.map((c) => [c.label, c.href]) };
    };
    expect(group("My Automations")).toEqual({ optIn: true, children: [
      ["Auto Mass", "/growth/auto-mass"],
      ["Auto Post", "/growth/auto-post"],
      ["Auto Story", "/growth/auto-story"],
      ["Auto Funnel", "/growth/auto-funnel"],
      ["Gen-Info", "/growth/gen-info"],
      ["Full AI Chat", "/full-ai-chatter"],
    ] });
    expect(group("My AI Chatter")).toEqual({ optIn: true, children: [
      ["Auto-reply", "/growth/auto-reply"],
      ["Get to know fans", "/growth/get-to-know-fans"],
    ] });
  });

  it("Full AI Chat is an owner-only Permission page under My Automations, not opt-in", () => {
    expect(findNavLink("/full-ai-chatter")).toMatchObject({ label: "Full AI Chat", chatterHidden: true });
    expect(PERMISSION_PAGES.has("/full-ai-chatter")).toBe(true);
    expect(CHATTER_OPT_IN_PAGES.has("/full-ai-chatter")).toBe(false);
    expect(outline(visibleSidebar(SIDEBAR, { chatterOnly: true, grantedPages: null }))).not.toContain("Full AI Chat");
  });

  it("AI rules is an owner-only Permission page, Full AI Chat's tab, not opt-in", () => {
    expect(findNavLink("/ai-rules")).toMatchObject({ label: "AI rules", chatterHidden: true, tabOf: "/full-ai-chatter" });
    expect(PERMISSION_PAGES.has("/ai-rules")).toBe(true);
    expect(CHATTER_OPT_IN_PAGES.has("/ai-rules")).toBe(false);
  });

  it("shows an owner every Settings tab but the master's System tab", () => {
    expect(visibleLinks(SETTINGS_TABS, OWNER)).toHaveLength(15);
  });

  it("hides owner-only sections from a chatter-only session", () => {
    const labels = outline(visibleSidebar(SIDEBAR, { chatterOnly: true, grantedPages: null }));
    expect(labels).not.toContain("Creators: Manage creators / Custom proxy");
    expect(labels).toContain("My AI Chatter: Get to know fans");
    expect(labels.some((l) => l.startsWith("My Automations"))).toBe(false);
    expect(labels).toContain("Growth: Smart Messages / Scripts");
  });

  it("My Automations and My AI Chatter are opt-in for a chatter: only the pages an enforcing role grants", () => {
    expect([...CHATTER_OPT_IN_PAGES]).toEqual([
      "/growth/auto-mass", "/growth/auto-post", "/growth/auto-story",
      "/growth/auto-funnel", "/growth/gen-info", "/growth/auto-reply",
    ]);
    const automations = (chatterOnly: boolean, permissions?: { pages: string[] | null; opt_in?: string[] }) => {
      const lines = outline(visibleSidebar(SIDEBAR, {
        chatterOnly, grantedPages: sessionGrantedPages(chatterOnly, permissions),
      }));
      return ["My Automations", "My AI Chatter"].map((g) => lines.find((l) => l.startsWith(`${g}:`)) ?? "");
    };
    const onlyGtkf = ["", "My AI Chatter: Get to know fans"];
    expect(automations(true, { pages: null, opt_in: [] })).toEqual(onlyGtkf);
    expect(automations(true, undefined)).toEqual(onlyGtkf);
    expect(automations(true, { pages: ["/growth/get-to-know-fans"], opt_in: [] })).toEqual(onlyGtkf);
    expect(automations(true, { pages: ["/messages-pro"], opt_in: [] })).toEqual(["", ""]);
    const ticked = ["/growth/auto-mass", "/growth/auto-reply"];
    expect(automations(true, { pages: ["/messages-pro", ...ticked], opt_in: ticked }))
      .toEqual(["My Automations: Auto Mass", "My AI Chatter: Auto-reply"]);
    expect(automations(true, { pages: ticked })).toEqual(["", ""]);
    expect(automations(true, { pages: ["/messages-pro"], opt_in: ["/growth/auto-mass"] }))
      .toEqual(["My Automations: Auto Mass", ""]);
    expect(automations(false, { pages: null })).toEqual([
      "My Automations: Auto Mass / Auto Post / Auto Story / Auto Funnel / Gen-Info / Full AI Chat",
      "My AI Chatter: Auto-reply / Get to know fans",
    ]);
    const off = sessionGrantedPages(true, { pages: null, opt_in: [] });
    expect(deniedPage("/growth/auto-mass", off)).toBe("/growth/auto-mass");
    expect(deniedPage("/growth/smart-messages", off)).toBeNull();
    expect(deniedPage("/growth/auto-mass", sessionGrantedPages(true, { pages: null, opt_in: ["/growth/auto-mass"] })))
      .toBeNull();
  });

  it("builds every Share for Share page, all four hidden from a chatter", () => {
    const g = SIDEBAR.find((n) => isGroup(n) && n.label === "Share for Share");
    const items = g && isGroup(g) ? g.children : [];
    expect(items.map((c) => c.href)).toEqual([
      "/share-for-share/discover-creators",
      "/share-for-share/requests",
      "/share-for-share/schedule",
      "/share-for-share/settings",
    ]);
    expect(items.filter((c) => !c.chatterHidden)).toEqual([]);
    const labels = outline(visibleSidebar(SIDEBAR, { chatterOnly: true, grantedPages: null }));
    expect(labels.some((l) => l.startsWith("Share for Share"))).toBe(false);
  });

  it("builds every OF Manager page (the OF mirror)", () => {
    const g = SIDEBAR.find((n) => isGroup(n) && n.label === "OF Manager");
    const items = g && isGroup(g) ? g.children : [];
    expect(items.map((c) => c.href).filter((h) => !mirrorPageOfHref(h))).toEqual([]);
  });

  it("builds every Settings tab, the six Blob tabs, Security (organization), Co-creator tag, OnlyFans consent, OF Manager writes, AI keys and the Audit log hidden from a Chatter", () => {
    expect(SETTINGS_TABS.filter((t) => t.chatterHidden).map((t) => t.href)).toEqual([
      "/settings/account",
      "/settings/preferences",
      "/settings/security-org",
      "/settings/roles",
      "/settings/sales",
      "/settings/time-tracking",
      "/settings/messaging",
      "/settings/cotag",
      "/settings/consent",
      "/settings/ofm-writes",
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
    expect(sidebarHref("/analytics/sales-records", grantedPages)).toBe("/analytics/sales-records");
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

describe("session sidebars (Owner, Team Leader, Chatter)", () => {
  const CHATTING = [
    "/messages-pro", "/of-manager/messages", "/of-manager/notifications", "/growth/scripts", "/growth/get-to-know-fans",
  ];
  const TEAM_LEADER = [
    "/", ...CHATTING, "/growth/smart-messages", "/of-manager/home", "/of-manager/vault", "/creators",
    "/creators/proxy", "/creators/leaks", "/employees", "/employees/shifts", "/analytics/creator-reports",
    "/analytics/employee-reports", "/analytics/message-dashboard", "/analytics/sales-records",
  ];
  const employee = (pages: string[]) => ({ chatterOnly: true, grantedPages: sessionGrantedPages(true, { pages }) });
  const drawn = (platform: "onlyfans" | "fansly", f: Parameters<typeof drawnSidebar>[1]) =>
    outline(drawnSidebar(sidebarFor(platform), f));

  it("an Owner sees every group, Creators and Employees included", () => {
    expect(drawn("onlyfans", OWNER).slice(-3)).toEqual([
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
    expect(drawn("fansly", OWNER)).toEqual([
      "Scripts",
      "Message pro",
      "Vault pro",
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
  });

  it("a Team Leader sees neither Creators nor Employees, though its role grants their pages", () => {
    expect(drawn("onlyfans", employee(TEAM_LEADER))).toEqual([
      "Dashboard",
      "OF Manager: Home / Notifications / Messages Basic / Vault",
      "Analytics: Creator reports / Employee reports / Message dashboard",
      "Messages Pro",
      "Growth: Smart Messages / Scripts",
      "—",
    ]);
    expect(drawn("fansly", employee(TEAM_LEADER))).toEqual(["Scripts", "Message pro", "—"]);
  });

  it("a Chatter sees its chatting pages only", () => {
    expect(drawn("onlyfans", employee(["/", ...CHATTING]))).toEqual([
      "Dashboard",
      "OF Manager: Notifications / Messages Basic",
      "Messages Pro",
      "Growth: Scripts",
      "—",
    ]);
    expect(drawn("fansly", employee(["/", ...CHATTING]))).toEqual(["Scripts", "Message pro", "—"]);
  });

  it("does not draw a group whose children are all hidden", () => {
    const nodes: NavNode[] = [
      { label: "Kept", href: "/kept" },
      { label: "Group", icon: Users, children: [{ label: "A", href: "/a", chatterHidden: true }, { label: "B", href: "/b", chatterHidden: true }] },
    ];
    expect(outline(drawnSidebar(nodes, { chatterOnly: true, grantedPages: null }))).toEqual(["Kept"]);
    expect(outline(drawnSidebar(nodes, OWNER))).toEqual(["Kept", "Group: A / B"]);
  });
});

describe("Leak tracker item (leak-tracker phase-01, story 8)", () => {
  const LEAKS = { leak_tracker: true, fansly_manager: false };
  const employee = (pages: string[] | null, flags = LEAKS) =>
    ({ chatterOnly: true, grantedPages: sessionGrantedPages(true, { pages }), flags });
  const creators = (f: Parameters<typeof drawnSidebar>[1]) =>
    outline(drawnSidebar(sidebarFor("onlyfans"), f)).filter((l) => l.startsWith("Creators"));

  it("sits under Creators after Custom proxy and shows only on the applied flag", () => {
    expect(findNavLink("/creators/leaks")).toMatchObject({ label: "Leak tracker", flag: "leak_tracker" });
    expect(findNavLink("/creators/leaks")?.chatterHidden).toBeUndefined();
    expect(PERMISSION_PAGES.has("/creators/leaks")).toBe(true);
    expect(creators({ ...OWNER, flags: LEAKS })).toEqual(["Creators: Manage creators / Custom proxy / Leak tracker"]);
    expect(creators(OWNER)).toEqual(["Creators: Manage creators / Custom proxy"]);
    expect(creators({ ...OWNER, flags: { ...LEAKS, leak_tracker: false } })).toEqual(["Creators: Manage creators / Custom proxy"]);
  });

  it("an employee session sees only the Leak tracker under Creators, whatever its pages say", () => {
    expect(creators(employee(["/", "/creators/leaks"]))).toEqual(["Creators: Leak tracker"]);
    expect(creators(employee(["/"]))).toEqual(["Creators: Leak tracker"]);
    expect(creators(employee(null))).toEqual(["Creators: Leak tracker"]);
    expect(creators(employee(["/", "/creators/leaks"], { ...LEAKS, leak_tracker: false }))).toEqual([]);
    expect(creators(employee(null, { ...LEAKS, leak_tracker: false }))).toEqual([]);
  });

  it("never denies its page on pages; the page checks the flag itself", () => {
    expect(deniedPage("/creators/leaks", new Set(["/"]))).toBeNull();
    expect(deniedPage("/creators/proxy", new Set(["/"]))).toBe("/creators/proxy");
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
    expect(deniedPage("/employees/org-chart", granted)).toBe("/employees");
    expect(deniedPage("/employees/shifts", granted)).toBeNull();
    expect(deniedPage("/", granted)).toBeNull();
    expect(deniedPage("/settings/about", granted)).toBeNull();
    expect(deniedPage("/notifications", granted)).toBeNull();
    expect(deniedPage("/messages-pro", null)).toBeNull();
  });
});

describe("platform nav map (Infloww's fanslyMenu, index.9f50f370.js @10699639)", () => {
  it("OnlyFans mode is the sidebar as it was", () => {
    expect(sidebarFor("onlyfans")).toBe(SIDEBAR);
  });

  it("Fansly mode with fansly_manager off: no Fansly Manager group; Scripts, Message pro, Vault pro, the divider, Creators and Employees", () => {
    expect(outline(visibleSidebar(sidebarFor("fansly"), OWNER))).toEqual([
      "Scripts",
      "Message pro",
      "Vault pro",
      "—",
      "Creators: Manage creators / Custom proxy",
      "Employees: Manage employees / Shift schedule",
    ]);
  });

  const FANSLY_MANAGER: [string, string, string][] = [
    ["Homepage", "/fansly-manager/home", "/of-manager/home"],
    ["Profile", "/fansly-manager/profile", "/of-manager/profile"],
    ["Subscriptions", "/fansly-manager/subscriptions", "/of-manager/collections"],
    ["Media Vault", "/fansly-manager/vault", "/of-manager/vault"],
    ["Scheduled Posts", "/fansly-manager/scheduled", "/of-manager/queue"],
    ["Lists", "/fansly-manager/lists", "/of-manager/collections"],
    ["Bookmarks", "/fansly-manager/bookmarks", "/of-manager/collections/bookmarks/all"],
    ["Messages", "/fansly-manager/messages", "/of-manager/messages"],
    ["Notifications", "/fansly-manager/notifications", "/of-manager/notifications"],
    ["Creator Dashboard", "/fansly-manager/creator", "/of-manager/statistics"],
    ["Earning Statistics", "/fansly-manager/earning-statistics", "/analytics/creator-reports"],
    ["Profile Statistics", "/fansly-manager/statistics", "/of-manager/statistics"],
    ["Tracking Links", "/fansly-manager/tracking-links", "/of-manager/statistics"],
    ["Settings", "/fansly-manager/settings", "/of-manager/settings"],
  ];
  const on = { fansly_manager: true, leak_tracker: false };
  const managerLabels = (f: Parameters<typeof visibleSidebar>[1]) => {
    const group = visibleSidebar(sidebarFor("fansly"), f).find((n) => isGroup(n) && n.label === "Fansly Manager");
    return group && isGroup(group) ? group.children.map((c) => c.label) : [];
  };

  it("with fansly_manager on, the Fansly Manager group is Infloww's 14 entries, in its order", () => {
    expect(outline(visibleSidebar(sidebarFor("fansly"), { ...OWNER, flags: on }))[0]).toBe(
      "Fansly Manager: Homepage / Profile / Subscriptions / Media Vault / Scheduled Posts / Lists / Bookmarks / Messages / Notifications / Creator Dashboard / Earning Statistics / Profile Statistics / Tracking Links / Settings",
    );
  });

  it("with Role enforcement off, an Owner or the Master, all 14 Fansly Manager entries show with the flag on", () => {
    expect(managerLabels({ chatterOnly: false, grantedPages: null, flags: on })).toEqual(FANSLY_MANAGER.map(([label]) => label));
    expect(managerLabels({ chatterOnly: false, grantedPages: null, master: true, flags: on })).toHaveLength(14);
  });

  it("each Fansly Manager entry answers to its OnlyFans counterpart's Permission page, in the rail and by URL, on its route and below it", () => {
    for (const [label, href, permission] of FANSLY_MANAGER) {
      expect(findNavLink(href)).toMatchObject({ label, flag: "fansly_manager", permission });
      expect(PERMISSION_PAGES.has(permission)).toBe(true);
      const granted = new Set([...PERMISSION_PAGES].filter((p) => p !== permission));
      expect(managerLabels({ chatterOnly: true, grantedPages: granted, flags: on })).not.toContain(label);
      for (const path of [href, `${href}/x`]) {
        expect(deniedPage(path, granted)).toBe(permission);
        expect(deniedPage(path, new Set([permission]))).toBeNull();
        expect(deniedPage(path, null)).toBeNull();
      }
    }
    const noCollections = new Set([...PERMISSION_PAGES].filter((p) => p !== "/of-manager/collections"));
    expect(deniedPage("/fansly-manager/lists/list", noCollections)).toBe("/of-manager/collections");
    const noTracking = new Set([...PERMISSION_PAGES].filter((p) => p !== "/growth/tracking-links"));
    for (const href of ["/growth/redirect-links", "/growth/bio-pages", "/growth/bio-pages/p00000000000001"]) {
      expect(deniedPage(href, noTracking)).toBe("/growth/tracking-links");
      expect(deniedPage(href, new Set(["/growth/tracking-links"]))).toBeNull();
    }
    expect(deniedPage("/growth/bio-pagesx", noTracking)).toBeNull();
    expect(managerLabels({ chatterOnly: true, grantedPages: new Set(["/messages-pro"]), flags: on })).toEqual([]);
  });

  it("Statistics without Creator reports opens Creator Dashboard, Profile and Tracking Links but not Earning Statistics; the reverse opens only Earning Statistics", () => {
    const stats = new Set(["/of-manager/statistics"]);
    expect(managerLabels({ chatterOnly: true, grantedPages: stats, flags: on })).toEqual(["Creator Dashboard", "Profile Statistics", "Tracking Links"]);
    expect(deniedPage("/fansly-manager/earning-statistics", stats)).toBe("/analytics/creator-reports");
    for (const path of ["/fansly-manager/creator", "/fansly-manager/statistics", "/fansly-manager/statistics/x", "/fansly-manager/tracking-links"])
      expect(deniedPage(path, stats)).toBeNull();
    const reports = new Set(["/analytics/creator-reports"]);
    expect(managerLabels({ chatterOnly: true, grantedPages: reports, flags: on })).toEqual(["Earning Statistics"]);
    expect(deniedPage("/fansly-manager/earning-statistics", reports)).toBeNull();
    expect(deniedPage("/fansly-manager/statistics", reports)).toBe("/of-manager/statistics");
    expect(deniedPage("/fansly-manager/statistics/x", reports)).toBe("/of-manager/statistics");
  });

  it("Bookmarks answers to OnlyFans' Bookmarks grant, not Collections", () => {
    const collections = new Set(["/of-manager/collections"]);
    expect(managerLabels({ chatterOnly: true, grantedPages: collections, flags: on })).toEqual(["Subscriptions", "Lists"]);
    expect(deniedPage("/fansly-manager/bookmarks", collections)).toBe("/of-manager/collections/bookmarks/all");
    expect(deniedPage("/fansly-manager/bookmarks", new Set(["/of-manager/collections/bookmarks/all"]))).toBeNull();
  });

  it("Fansly's links are the 14 flagged Fansly Manager entries plus OnlyFans' Scripts, Message pro and Vault pro", () => {
    const links = FANSLY_NAV.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
    expect(links.map((l) => [l.href, l.flag])).toEqual([
      ...FANSLY_MANAGER.map(([, href]) => [href, "fansly_manager"]),
      ["/growth/scripts", undefined],
      ["/messages-pro", undefined],
      ["/growth/vault-pro", undefined],
    ]);
    const onlyfans = new Set(SIDEBAR.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n])).map((l) => l.href));
    for (const l of links.filter((x) => !x.flag)) expect(onlyfans.has(l.href)).toBe(true);
  });

  it("a chatter's Fansly rail hides Vault pro, as its OnlyFans one does", () => {
    const chatter = { chatterOnly: true, grantedPages: null };
    expect(outline(visibleSidebar(sidebarFor("fansly"), chatter))).not.toContain("Vault pro");
  });

  it("platformOfPath: a page only one platform shows, else null", () => {
    expect(platformOfPath("/")).toBe("onlyfans");
    expect(platformOfPath("/analytics/fan-reports")).toBe("onlyfans");
    expect(platformOfPath("/of-manager/home")).toBe("onlyfans");
    expect(platformOfPath("/fansly-manager/lists")).toBe("fansly");
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
    expect(outline(visibleSidebar(nodes, { ...OWNER, flags: { fansly_manager: false, leak_tracker: false } }))).toEqual(["Lit"]);
    expect(outline(visibleSidebar(nodes, { ...OWNER, flags: { fansly_manager: true, leak_tracker: false } }))).toEqual([
      "Dark", "Group: Dark child", "Lit",
    ]);
  });

  it("firstPage: the first built page that is not a window", () => {
    expect(firstPage("onlyfans")).toBe("/");
    expect(firstPage("fansly")).toBe("/growth/scripts");
  });
});

describe("openPopout", () => {
  function popoutOn(path: string) {
    const [pathname, search = ""] = path.split("?");
    const win = { location: { pathname, search: search && `?${search}`, href: path }, focus: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
    return { win, done: () => open.mockRestore() };
  }

  it("Messages Pro leaves a window on the inbox or a Deep link where it is, and focuses it", () => {
    for (const path of ["/messages-pro", "/messages-pro/acc1/123"]) {
      const { win, done } = popoutOn(path);
      openPopout("/messages-pro");
      expect(win.location.href).toBe(path);
      expect(win.focus).toHaveBeenCalled();
      done();
    }
  });

  it("a Deep link moves the window when it shows another place, and not when it shows that one", () => {
    for (const [path, href, to] of [
      ["/messages-pro", "/messages-pro/acc1/123", "/messages-pro/acc1/123"],
      ["/", "/messages-pro", "/messages-pro"],
    ]) {
      const { win, done } = popoutOn(path);
      openPopout(href);
      expect(win.location.href).toBe(to);
      done();
    }
  });

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
