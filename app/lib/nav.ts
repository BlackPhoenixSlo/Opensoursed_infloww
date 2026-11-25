/**
 * The app's navigation, as data. One tree drives the sidebar, the settings tab
 * list and the tests, so the labels and routes live in exactly one place.
 *
 * Labels are VERBATIM from docs/infloww-screens.md §1.1 (sidebar) and §3.10
 * (settings tabs); routes follow §2. The one deliberate deviation from Infloww
 * are ours (VISION.md): the "My Automations" group (Auto Mass, Auto Post,
 * Auto Story, Auto Funnel, Gen-Info), the "Full AI Chat" page, the "My AI
 * Chatter" group (Auto-reply, Get to know fans: `hidden`, so a Permission group
 * the sidebar never draws). A plugin may add links to a group (lib/chatSlots.ts
 * `navLinks`).
 *
 *   chatterHidden — hidden from a chatter-only session (the relay still 403s
 *                   the owner endpoints; this is UI hygiene, not the gate).
 *   chatterOptIn  — a group a chatter sees only the pages of that a stored
 *                   Permission role ticks with "Enforce role permissions" on
 *                   (My Automations, My AI Chatter; off by default, the built-in Admin and
 *                   Owner included): the Applied settings `opt_in` list. The
 *                   relay refuses their routes and rule kinds likewise
 *                   (service/permissions.py OPT_IN_PAGES, OPT_IN_KINDS).
 *   notOptIn      — a link of a `chatterOptIn` group its role grants like any
 *                   other page (My AI Chatter › Get to know fans).
 *   popout        — a window of its own, never a page in the app: the sidebar
 *                   opens it with `openPopout` (Messages Pro, ADR-0002).
 *   masterOnly    — shown only to the deployment master (users.is_admin); the
 *                   relay gates its endpoints with require_master regardless.
 *   flag          — shown only while the Agency's feature flag is on (Applied
 *                   settings `flags`, roadmap 8.11), so a page set can ship
 *                   dark; its page refuses a direct visit too. UI only: the
 *                   data routes are permission-checked regardless.
 *   permission    — the Permission-editor page (a `PERMISSION_PAGES` href) a
 *                   link answers to instead of being one of its own: a role
 *                   that denies that page hides this link and gets the denied
 *                   panel on it too, on its route and below it (Fansly
 *                   Manager's flagged pages; Growth's Redirect links and Bio
 *                   pages, Tracking links' former tabs).
 *   tabOf         — a tab of that page, not a sidebar entry: `visibleLinks`
 *                   drops it while the role grants that page, and the sidebar
 *                   highlights that page on its route (`sidebarHref`). A role
 *                   that grants the tab but not its page gets it as an entry
 *                   of its own. It stays a `PERMISSION_PAGES` page with its
 *                   own route (Sales records, Employee reports' second tab as
 *                   in Infloww; page-parity ticket 27; AI rules, Full AI Chat's
 *                   popup).
 *   hidden        — never drawn in the sidebar (`drawnSidebar`), but every
 *                   derived list still counts it: a Permission page with its
 *                   route, gate, denied panel and opt-in as before (owner 11-15:
 *                   Auto-reply, Get to know fans; their pages open by URL).
 */

import type { MouseEvent } from "react";
import {
  AlarmClockCheck,
  AtSign,
  Bot,
  CalendarClock,
  ChartColumn,
  Database,
  FileCheck,
  PenLine,
  Heart,
  History,
  Images,
  Info,
  KeyRound,
  MessageCircle,
  MessagesSquare,
  RectangleEllipsis,
  ScrollText,
  ServerCog,
  ShieldCheck,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  BarChart10Line,
  EmployeeLine,
  Grid01Line,
  HelpCircleLine,
  LineChartUp04Line,
  MessagesProLine,
  OnlyfansLine,
  Settings04Line,
  SwitchHorizontal01Line,
  UserSquareLine,
} from "@/components/shell/inflowwIcons";
import type { FeatureFlag, FeatureFlags } from "@/lib/appliedSettings";
import type { FanId } from "@/lib/fanId";
import type { Platform } from "@/lib/platform";
import { BRAND_NAME } from "@/lib/brand";
import { NAV_LINK_SLOTS, POPOUT_MODE_ROUTES } from "@/lib/chatSlots";

export interface NavLink {
  label: string;
  href: string;
  icon?: LucideIcon;
  chatterHidden?: boolean;
  popout?: boolean;
  masterOnly?: boolean;
  flag?: FeatureFlag;
  permission?: string;
  tabOf?: string;
  hidden?: boolean;
  notOptIn?: boolean;
}

export interface NavGroup {
  label: string;
  icon: LucideIcon;
  children: NavLink[];
  chatterHidden?: boolean;
  chatterOptIn?: boolean;
}

export interface NavDivider {
  divider: true;
}

export type NavNode = NavLink | NavGroup | NavDivider;

export const isGroup = (n: NavNode): n is NavGroup => "children" in n;
export const isDivider = (n: NavNode): n is NavDivider => "divider" in n;

export const ONLYFANS_NAV: NavNode[] = withSlotLinks([
  { label: "Dashboard", href: "/", icon: Grid01Line },
  {
    label: "OF Manager",
    icon: OnlyfansLine,
    children: [
      { label: "Home", href: "/of-manager/home" },
      { label: "Go live", href: "/of-manager/streaming" },
      { label: "New post", href: "/of-manager/new-post" },
      { label: "Notifications", href: "/of-manager/notifications" },
      { label: "Messages Basic", href: "/of-manager/messages" },
      { label: "Vault", href: "/of-manager/vault" },
      { label: "Queue", href: "/of-manager/queue" },
      { label: "Collections", href: "/of-manager/collections" },
      { label: "Bookmarks", href: "/of-manager/collections/bookmarks/all" },
      { label: "Statements", href: "/of-manager/statements" },
      { label: "Statistics", href: "/of-manager/statistics" },
      { label: "Bank", href: "/of-manager/bank" },
      { label: "My profile", href: "/of-manager/profile" },
      { label: "Release forms", href: "/of-manager/release-forms" },
      { label: "OF settings", href: "/of-manager/settings" },
    ],
  },
  {
    label: "Analytics",
    icon: BarChart10Line,
    children: [
      { label: "Creator reports", href: "/analytics/creator-reports" },
      { label: "Employee reports", href: "/analytics/employee-reports" },
      { label: "Fan reports", href: "/analytics/fan-reports" },
      { label: "Message dashboard", href: "/analytics/message-dashboard" },
      { label: "Sales records", href: "/analytics/sales-records", tabOf: "/analytics/employee-reports" },
    ],
  },
  { label: "Messages Pro", href: "/messages-pro", icon: MessagesProLine, popout: true },
  { label: "Vault Pro", href: "/growth/vault-pro", icon: Images, chatterHidden: true },
  {
    label: "Growth",
    icon: LineChartUp04Line,
    children: [
      { label: "Smart Messages", href: "/growth/smart-messages" },
      { label: "Smart lists", href: "/growth/smart-lists", chatterHidden: true },
      { label: "Auto-follow", href: "/growth/auto-follow", chatterHidden: true },
      { label: "Scripts", href: "/growth/scripts" },
      { label: "Profile promotion", href: "/growth/profile-promotion", chatterHidden: true },
      { label: "Free trial links", href: "/growth/free-trial-links", chatterHidden: true },
      { label: "Tracking links", href: "/growth/tracking-links", chatterHidden: true },
      { label: "Redirect links", href: "/growth/redirect-links", chatterHidden: true, permission: "/growth/tracking-links" },
      { label: "Bio pages", href: "/growth/bio-pages", chatterHidden: true, permission: "/growth/tracking-links" },
      { label: "Sensitive words", href: "/growth/sensitive-words", chatterHidden: true },
    ],
  },
  {
    label: "Share for Share",
    icon: SwitchHorizontal01Line,
    children: [
      // Owner-only: the relay 403s a chatter on /admin/s4s
      { label: "Discover creators", href: "/share-for-share/discover-creators", chatterHidden: true },
      { label: "Requests", href: "/share-for-share/requests", chatterHidden: true },
      { label: "S4S schedule", href: "/share-for-share/schedule", chatterHidden: true },
      { label: "S4S settings", href: "/share-for-share/settings", chatterHidden: true },
    ],
  },
  {
    label: "My Automations",
    icon: CalendarClock,
    chatterOptIn: true,
    children: [
      { label: "Auto Mass", href: "/growth/auto-mass" },
      { label: "Auto Post", href: "/growth/auto-post" },
      { label: "Auto Story", href: "/growth/auto-story" },
      { label: "Auto Funnel", href: "/growth/auto-funnel" },
      { label: "Gen-Info", href: "/growth/gen-info" },
    ],
  },
  // Full AI Chat: Shadow switch + the owner's Test chat. Owner-only: nothing a chatter operates.
  { label: "Full AI Chat", href: "/full-ai-chatter", icon: Bot, chatterHidden: true },
  // AI rules: the Full AI Turn as a read-only zoomable diagram, a popup on Full AI Chat (owner 11-15).
  { label: "AI rules", href: "/ai-rules", icon: Bot, chatterHidden: true, tabOf: "/full-ai-chatter" },
  // Ours: the AI chat lanes, opt-in for a chatter like My Automations. Out of the sidebar (owner 11-15),
  // still Permission pages with their routes and gates.
  {
    label: "My AI Chatter",
    icon: Bot,
    chatterOptIn: true,
    children: [
      { label: "Auto-reply", href: "/growth/auto-reply", hidden: true },
      { label: "Get to know fans", href: "/growth/get-to-know-fans", notOptIn: true, hidden: true },
    ],
  },
]);

function withSlotLinks(nodes: NavNode[]): NavNode[] {
  return nodes.map((n) => {
    const adds = isGroup(n) ? NAV_LINK_SLOTS.filter((s) => s.group === n.label) : [];
    if (!isGroup(n) || !adds.length) return n;
    const links = (first: boolean) => adds.filter((s) => !!s.first === first).map((s) => s.link);
    return { ...n, children: [...links(true), ...n.children, ...links(false)] };
  });
}

const COMMON_NAV: NavNode[] = [
  {
    label: "Creators",
    icon: UserSquareLine,
    chatterHidden: true,
    children: [
      { label: "Manage creators", href: "/creators" },
      { label: "Custom proxy", href: "/creators/proxy" },
    ],
  },
  {
    label: "Employees",
    icon: EmployeeLine,
    chatterHidden: true,
    children: [
      { label: "Manage employees", href: "/employees" },
      { label: "Shift schedule", href: "/employees/shifts" },
    ],
  },
];

/**
 * Fansly mode's own pages: Infloww's `fanslyMenu` (index.9f50f370.js
 * @10699639), in the order its Fansly rail draws them (Fansly Manager,
 * Scripts, Message pro, Vault pro). Scripts, Message pro and Vault pro are
 * our built pages, which serve a Fansly account through the relay's Fansly
 * shim (they read the platform-scoped account list). Infloww embeds
 * fansly.com for the Fansly Manager pages; we build only the flagged ones
 * below, gated by their OnlyFans counterpart's permission so existing grants
 * cover both platforms.
 */
export const FANSLY_NAV: NavNode[] = [
  {
    label: "Fansly Manager",
    icon: Heart,
    children: [
      { label: "Scheduled Posts", href: "/fansly-manager/scheduled", flag: "fansly_manager", permission: "/of-manager/queue" },
      { label: "Lists", href: "/fansly-manager/lists", flag: "fansly_manager", permission: "/of-manager/collections" },
      { label: "Notifications", href: "/fansly-manager/notifications", flag: "fansly_manager", permission: "/of-manager/notifications" },
      { label: "Earning Statistics", href: "/fansly-manager/earning-statistics", flag: "fansly_manager", permission: "/analytics/creator-reports" },
    ],
  },
  { label: "Scripts", href: "/growth/scripts", icon: ScrollText }, // Infloww: /fansly/scripts
  { label: "Message pro", href: "/messages-pro", icon: MessagesSquare, popout: true }, // Infloww: /fansly/message-pro, a window
  { label: "Vault pro", href: "/growth/vault-pro", icon: Images, chatterHidden: true }, // Infloww: /fansly/vault-pro
];

export const PLATFORM_NAV: Record<Platform, NavNode[]> = { onlyfans: ONLYFANS_NAV, fansly: FANSLY_NAV };

export const SIDEBAR: NavNode[] = [...ONLYFANS_NAV, { divider: true }, ...COMMON_NAV];

export function sidebarFor(platform: Platform): NavNode[] {
  return platform === "onlyfans" ? SIDEBAR : [...PLATFORM_NAV[platform], { divider: true }, ...COMMON_NAV];
}

const navHrefs = (nodes: NavNode[]): string[] =>
  nodes.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children.map((c) => c.href) : [n.href]));

const under = (pathname: string, href: string) =>
  href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

export function isPlatformPage(platform: Platform, pathname: string): boolean {
  return navHrefs(PLATFORM_NAV[platform]).some((h) => under(pathname, h));
}

export function platformOfPath(pathname: string): Platform | null {
  const owners = (Object.keys(PLATFORM_NAV) as Platform[]).filter((p) => isPlatformPage(p, pathname));
  return owners.length === 1 ? owners[0] : null;
}

/**
 * Where switching to `platform` lands: its first page, as Infloww's
 * `getFirstMenu` (@10736265), skipping a popout and a flagged page so a
 * switch never lands on "not available" or opens a window (ours; Infloww's
 * first Fansly page is the embedded fansly.com Homepage).
 */
export function firstPage(platform: Platform): string {
  const links = PLATFORM_NAV[platform].flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
  return (links.find((l) => !l.popout && !l.flag) ?? links[0]).href;
}

/** Pinned under the scrolling sidebar list, above the version line. */
export const SIDEBAR_FOOTER: NavLink[] = [
  { label: "Settings", href: "/settings", icon: Settings04Line },
  { label: "Help center", href: "/help-center", icon: HelpCircleLine },
];

export const SETTINGS_TABS: NavLink[] = [
  // The six Blob tabs are hidden from a Chatter (their route 401s one), as is Security (owner-only /admin/employees); SettingsShell refuses a hidden tab opened by URL
  { label: "Your Account", href: "/settings/account", icon: User, chatterHidden: true },
  { label: "Your Preferences", href: "/settings/preferences", icon: Heart, chatterHidden: true },
  { label: "Security (organization)", href: "/settings/security-org", icon: ShieldCheck, chatterHidden: true },
  { label: "Security (personal)", href: "/settings/security-personal", icon: RectangleEllipsis },
  { label: "Billing", href: "/settings/billing", icon: Database },
  { label: "Role Settings", href: "/settings/roles", icon: Users, chatterHidden: true },
  { label: "Sales Settings", href: "/settings/sales", icon: ChartColumn, chatterHidden: true },
  { label: "Time tracking", href: "/settings/time-tracking", icon: AlarmClockCheck, chatterHidden: true },
  { label: "Messaging settings", href: "/settings/messaging", icon: MessageCircle, chatterHidden: true },
  { label: "Co-creator tag", href: "/settings/cotag", icon: AtSign, chatterHidden: true },
  { label: "OnlyFans consent", href: "/settings/consent", icon: FileCheck, chatterHidden: true },
  { label: "OF Manager writes", href: "/settings/ofm-writes", icon: PenLine, chatterHidden: true },
  { label: "AI keys", href: "/settings/ai-keys", icon: KeyRound, chatterHidden: true },
  { label: "Audit log", href: "/settings/audit", icon: History, chatterHidden: true },
  { label: `About ${BRAND_NAME}`, href: "/settings/about", icon: Info },
  // Master's ops back-office: never drawn for owner/employee/chatter; the Panel 404s them too
  { label: "System", href: "/settings/system", icon: ServerCog, masterOnly: true },
];

export interface NavFilter {
  chatterOnly: boolean;
  grantedPages: Set<string> | null;
  master?: boolean;
  flags?: FeatureFlags;
}


export function isPermissionPage(l: NavLink): boolean {
  return !l.permission;
}

export const PERMISSION_PAGES: ReadonlySet<string> = new Set(
  SIDEBAR.flatMap((n) =>
    isDivider(n) ? [] : (isGroup(n) ? n.children : [n]).filter(isPermissionPage).map((l) => l.href),
  ),
);

const PERMISSION_OF: ReadonlyMap<string, string> = new Map(
  [...SIDEBAR, ...FANSLY_NAV].flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]))
    .flatMap((l) => (l.permission ? [[l.href, l.permission] as const] : [])),
);

export const CHATTER_OPT_IN_PAGES: ReadonlySet<string> = new Set(
  SIDEBAR.flatMap((n) => (isGroup(n) && n.chatterOptIn ? n.children.filter((c) => !c.notOptIn).map((c) => c.href) : [])),
);

export function sessionGrantedPages(
  chatterOnly: boolean,
  permissions: { pages?: string[] | null; opt_in?: string[] } | undefined,
): Set<string> | null {
  const pages = permissions?.pages;
  if (!chatterOnly) return pages ? new Set(pages) : null;
  const open = new Set(pages ?? PERMISSION_PAGES);
  for (const href of CHATTER_OPT_IN_PAGES) open.delete(href);
  for (const href of permissions?.opt_in ?? []) if (CHATTER_OPT_IN_PAGES.has(href)) open.add(href);
  return open;
}

function keep(
  n: { chatterHidden?: boolean; masterOnly?: boolean; href?: string; flag?: FeatureFlag; permission?: string; tabOf?: string },
  f: NavFilter,
): boolean {
  if (n.tabOf && (!f.grantedPages || f.grantedPages.has(n.tabOf))) return false;
  if (n.masterOnly && (!f.master || f.chatterOnly)) return false;
  if (n.flag && !f.flags?.[n.flag]) return false;
  if (n.chatterHidden && f.chatterOnly) return false;
  if (f.chatterOnly && n.href && CHATTER_OPT_IN_PAGES.has(n.href) && !f.grantedPages?.has(n.href)) return false;
  const page = n.permission ?? n.href;
  if (f.grantedPages && page && PERMISSION_PAGES.has(page) && !f.grantedPages.has(page)) return false;
  return true;
}

export function deniedPage(pathname: string, grantedPages: Set<string> | null): string | null {
  if (!grantedPages) return null;
  const alias = PERMISSION_OF.get(pathname)
    ?? [...PERMISSION_OF].find(([href]) => pathname.startsWith(`${href}/`))?.[1];
  if (alias) return grantedPages.has(alias) ? null : alias;
  let page: string | null = null;
  for (const href of PERMISSION_PAGES) {
    const hit = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
    if (hit && (!page || href.length > page.length)) page = href;
  }
  return page && !grantedPages.has(page) ? page : null;
}

export function sidebarHref(pathname: string, grantedPages: Set<string> | null = null): string {
  for (const n of SIDEBAR) {
    for (const l of isDivider(n) ? [] : isGroup(n) ? n.children : [n]) {
      if (!l.tabOf || (grantedPages && !grantedPages.has(l.tabOf))) continue;
      if (pathname === l.href || pathname.startsWith(`${l.href}/`)) return l.tabOf;
    }
  }
  return pathname;
}

export function visibleLinks(links: NavLink[], f: NavFilter): NavLink[] {
  return links.filter((l) => keep(l, f));
}

export function visibleSidebar(nodes: NavNode[], f: NavFilter): NavNode[] {
  const out: NavNode[] = [];
  for (const n of nodes) {
    if (isDivider(n)) {
      out.push(n);
    } else if (isGroup(n)) {
      if (!keep(n, f)) continue;
      const children = visibleLinks(n.children, f);
      if (children.length > 0) out.push({ ...n, children });
    } else if (keep(n, f)) {
      out.push(n);
    }
  }
  return out;
}

export function drawnSidebar(nodes: NavNode[], f: NavFilter): NavNode[] {
  const shown = nodes.flatMap((n): NavNode[] =>
    isDivider(n) ? [n] : isGroup(n) ? [{ ...n, children: n.children.filter((c) => !c.hidden) }] : n.hidden ? [] : [n]);
  return visibleSidebar(shown, f);
}

export function allNavLinks(): NavLink[] {
  const links: NavLink[] = [];
  const seen = new Set<string>();
  for (const n of [...SIDEBAR, ...FANSLY_NAV]) {
    for (const l of isDivider(n) ? [] : isGroup(n) ? n.children : [n]) {
      if (seen.has(l.href)) continue;
      seen.add(l.href);
      links.push(l);
    }
  }
  return [...links, ...SIDEBAR_FOOTER, ...SETTINGS_TABS];
}

export function findNavLink(href: string): NavLink | undefined {
  return allNavLinks().find((l) => l.href === href);
}

export function fanDeepLinkHref(accountId: string, fanId: FanId): string {
  return `/messages-pro/${encodeURIComponent(accountId)}/${fanId}`;
}

export function isPopoutRoute(pathname: string): boolean {
  return allNavLinks().some((l) => l.popout && (pathname === l.href || pathname.startsWith(`${l.href}/`)));
}

export function hasCreatorColumn(pathname: string): boolean {
  return pathname === "/of-manager" || pathname.startsWith("/of-manager/");
}

export const POPOUT_WINDOW = "messages-pro";
export const POPOUT_FEATURES = "popup,width=1470,height=915";

// Same-origin so the opener keeps the handle (no noopener); the desktop app refuses a new blank window, so with none open the window opens on href itself
export function openPopout(href: string): void {
  const w = window.open("", POPOUT_WINDOW, POPOUT_FEATURES);
  if (!w) {
    window.open(href, POPOUT_WINDOW, POPOUT_FEATURES);
    return;
  }
  const showing = w.location.pathname;
  const elsewhere = href === "/messages-pro" ? POPOUT_MODE_ROUTES.has(showing) : `${showing}${w.location.search}` !== href;
  if (!isPopoutRoute(showing) || elsewhere) w.location.href = href;
  w.focus();
}

export function onPopoutClick(e: MouseEvent, href: string): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openPopout(href);
}
