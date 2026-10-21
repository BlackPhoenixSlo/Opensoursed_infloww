/**
 * The app's navigation, as data. One tree drives the sidebar, the settings tab
 * list, the "not built yet" placeholder pages and the tests, so the labels and
 * routes live in exactly one place.
 *
 * Labels are VERBATIM from docs/infloww-screens.md §1.1 (sidebar) and §3.10
 * (settings tabs); routes follow §2. The one deliberate deviation from Infloww
 * is the "My Automations" group (Auto Post, Auto Story, Auto Mass, Auto-reply,
 * Auto Funnel, Get to know fans, Gen-Info; VISION.md).
 *
 *   chatterHidden — hidden from a chatter-only session (the relay still 403s
 *                   the owner endpoints; this is UI hygiene, not the gate).
 *   chatterOptIn  — a group a chatter sees only the pages of that a stored
 *                   Permission role ticks with "Enforce role permissions" on
 *                   (My Automations; off by default, the built-in Admin and
 *                   Owner included): the Applied settings `opt_in` list. The
 *                   relay refuses their routes and rule kinds likewise
 *                   (service/permissions.py OPT_IN_PAGES, OPT_IN_KINDS).
 *   notOptIn      — a link of a `chatterOptIn` group its role grants like any
 *                   other page (My Automations › Get to know fans).
 *   notBuilt      — the route renders the Fansly welcome placeholder.
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
 *                   panel on it too (Fansly Manager's flagged pages).
 *   tabOf         — a tab of that page, not a sidebar entry: `visibleLinks`
 *                   drops it while the role grants that page, and the sidebar
 *                   highlights that page on its route (`sidebarHref`). A role
 *                   that grants the tab but not its page gets it as an entry
 *                   of its own. It stays a `PERMISSION_PAGES` page with its
 *                   own route (Sales records, Employee reports' second tab as
 *                   in Infloww; page-parity ticket 27).
 */

import type { MouseEvent } from "react";
import {
  AlarmClockCheck,
  AtSign,
  CalendarClock,
  ChartColumn,
  Database,
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
  Wallet,
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

export interface NavLink {
  label: string;
  href: string;
  icon?: LucideIcon;
  chatterHidden?: boolean;
  notBuilt?: boolean;
  popout?: boolean;
  masterOnly?: boolean;
  flag?: FeatureFlag;
  permission?: string;
  tabOf?: string;
  /** In a `chatterOptIn` group, a page a role grants like any other (not opt-in). */
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

/**
 * OnlyFans mode's own pages: Infloww's sidebar draws the current platform's
 * menu, a divider, then the menus with no platform (`groupMenuByType`,
 * index.9f50f370.js @10731800; `DesignLayout`, @11133300). Which of Infloww's
 * menus are OnlyFans' comes from its server's menu list (`platformType:M.type`,
 * @10731434); its Fansly rail shows only Creators and Employees below the
 * divider, so everything above it here is OnlyFans'.
 */
export const ONLYFANS_NAV: NavNode[] = [
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
      // Infloww's own menu (id 6, /my/collections/bookmarks/all), so its own Permission-editor page.
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
      // Employee reports' second tab (live 07-analytics-menu.png: four entries); its URL and Permission page stay.
      { label: "Sales records", href: "/analytics/sales-records", tabOf: "/analytics/employee-reports" },
    ],
  },
  { label: "Messages Pro", href: "/messages-pro", icon: MessagesProLine, popout: true },
  {
    label: "Growth",
    icon: LineChartUp04Line,
    children: [
      { label: "Smart Messages", href: "/growth/smart-messages" },
      { label: "Smart lists", href: "/growth/smart-lists", chatterHidden: true },
      { label: "Auto-follow", href: "/growth/auto-follow", chatterHidden: true },
      { label: "Vault Pro", href: "/growth/vault-pro", chatterHidden: true },
      { label: "Scripts", href: "/growth/scripts" },
      { label: "Profile promotion", href: "/growth/profile-promotion", chatterHidden: true },
      { label: "Free trial links", href: "/growth/free-trial-links", chatterHidden: true },
      { label: "Tracking links", href: "/growth/tracking-links", chatterHidden: true },
      // Infloww's Growth > Sensitive words (menu 87). Its writes are owner-only.
      { label: "Sensitive words", href: "/growth/sensitive-words", chatterHidden: true },
    ],
  },
  {
    label: "Share for Share",
    icon: SwitchHorizontal01Line,
    children: [
      // Owner-only (docs/spec/phase-03-share-for-share.md): the relay 403s a chatter on /admin/s4s.
      { label: "Discover creators", href: "/share-for-share/discover-creators", chatterHidden: true },
      { label: "Requests", href: "/share-for-share/requests", chatterHidden: true },
      { label: "S4S schedule", href: "/share-for-share/schedule", chatterHidden: true },
      // Infloww menu 55: a page, not a drawer.
      { label: "S4S settings", href: "/share-for-share/settings", chatterHidden: true },
    ],
  },
  // Ours, not Infloww (VISION.md). Routes per docs/infloww-screens.md §4.1.
  {
    label: "My Automations",
    icon: CalendarClock,
    chatterOptIn: true,
    children: [
      { label: "Auto Post", href: "/growth/auto-post" },
      { label: "Auto Story", href: "/growth/auto-story" },
      { label: "Auto Mass", href: "/growth/auto-mass" },
      { label: "Auto-reply", href: "/growth/auto-reply" },
      { label: "Auto Funnel", href: "/growth/auto-funnel" },
      // Its Model info is the account's, so a role grants it like any page (service/permissions.py PAGE_MAP).
      { label: "Get to know fans", href: "/growth/get-to-know-fans", notOptIn: true },
      { label: "Gen-Info", href: "/growth/gen-info" },
    ],
  },
];

/** The menus every platform shows, below the divider. */
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
 * shim (they read the platform-scoped account list). Of the Fansly Manager
 * pages (Infloww's embedded fansly.com), Scheduled Posts, Lists, Notifications
 * and Earning Statistics are ours over the shim, behind the `fansly_manager`
 * flag (roadmap 8.1), each answering to its OnlyFans counterpart's Permission
 * page (`permission`); the rest are not built.
 */
export const FANSLY_NAV: NavNode[] = [
  {
    label: "Fansly Manager",
    icon: Heart,
    children: [
      { label: "Homepage", href: "/fansly-manager/home", notBuilt: true },
      { label: "Profile", href: "/fansly-manager/profile", notBuilt: true },
      { label: "Subscriptions", href: "/fansly-manager/subscriptions", notBuilt: true },
      { label: "Media Vault", href: "/fansly-manager/media-vault", notBuilt: true },
      { label: "Media Collection", href: "/fansly-manager/media-collection", notBuilt: true },
      { label: "Scheduled Posts", href: "/fansly-manager/scheduled", flag: "fansly_manager", permission: "/of-manager/queue" },
      { label: "Lists", href: "/fansly-manager/lists", flag: "fansly_manager", permission: "/of-manager/collections" },
      { label: "Bookmarks", href: "/fansly-manager/bookmarks", notBuilt: true },
      { label: "Messages", href: "/fansly-manager/messages", notBuilt: true },
      { label: "Notifications", href: "/fansly-manager/notifications", flag: "fansly_manager", permission: "/of-manager/notifications" },
      { label: "Creator Dashboard", href: "/fansly-manager/creator", notBuilt: true },
      { label: "Earning Statistics", href: "/fansly-manager/earning-statistics", flag: "fansly_manager", permission: "/analytics/creator-reports" },
      { label: "Profile Statistics", href: "/fansly-manager/profile-statistics", notBuilt: true },
      { label: "Tracking Links", href: "/fansly-manager/tracking-links", notBuilt: true },
      { label: "Referrals", href: "/fansly-manager/referrals", notBuilt: true },
      { label: "Settings", href: "/fansly-manager/settings", notBuilt: true },
    ],
  },
  { label: "Scripts", href: "/growth/scripts", icon: ScrollText }, // Infloww: /fansly/scripts
  { label: "Message pro", href: "/messages-pro", icon: MessagesSquare, popout: true }, // Infloww: /fansly/message-pro, a window
  { label: "Vault pro", href: "/growth/vault-pro", icon: Images, chatterHidden: true }, // Infloww: /fansly/vault-pro
];

/** Each platform's own pages. */
export const PLATFORM_NAV: Record<Platform, NavNode[]> = { onlyfans: ONLYFANS_NAV, fansly: FANSLY_NAV };

/** The OnlyFans sidebar: the tree the Permission editor and the route tests read. */
export const SIDEBAR: NavNode[] = [...ONLYFANS_NAV, { divider: true }, ...COMMON_NAV];

/** The sidebar of one platform: its own pages, the divider, the common ones. */
export function sidebarFor(platform: Platform): NavNode[] {
  return platform === "onlyfans" ? SIDEBAR : [...PLATFORM_NAV[platform], { divider: true }, ...COMMON_NAV];
}

const navHrefs = (nodes: NavNode[]): string[] =>
  nodes.flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children.map((c) => c.href) : [n.href]));

const under = (pathname: string, href: string) =>
  href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

/** Whether `pathname` is one of `platform`'s own pages (a common page is not). */
export function isPlatformPage(platform: Platform, pathname: string): boolean {
  return navHrefs(PLATFORM_NAV[platform]).some((h) => under(pathname, h));
}

/**
 * The platform whose own pages alone hold `pathname`, else null (a common
 * page, or one both platforms show, such as Scripts). Infloww switches the
 * platform to the one the visited page belongs to (`DesignLayout`'s route
 * effect, index.9f50f370.js @11131400).
 */
export function platformOfPath(pathname: string): Platform | null {
  const owners = (Object.keys(PLATFORM_NAV) as Platform[]).filter((p) => isPlatformPage(p, pathname));
  return owners.length === 1 ? owners[0] : null;
}

/**
 * Where switching to `platform` lands: its first page, as Infloww's
 * `getFirstMenu` (@10736265), skipping a placeholder, a popout and a flagged
 * page so a switch never lands on "not built yet", "not available" or opens
 * a window (ours; Infloww's first Fansly page is the embedded fansly.com
 * Homepage).
 */
export function firstPage(platform: Platform): string {
  const links = PLATFORM_NAV[platform].flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]));
  return (links.find((l) => !l.notBuilt && !l.popout && !l.flag) ?? links[0]).href;
}

/** Pinned under the scrolling sidebar list, above the version line. */
export const SIDEBAR_FOOTER: NavLink[] = [
  { label: "Settings", href: "/settings", icon: Settings04Line },
  { label: "Help center", href: "/help-center", icon: HelpCircleLine },
];

/** Settings > left tab list (§3.10). */
export const SETTINGS_TABS: NavLink[] = [
  // Icons as Infloww draws them (live capture, page-parity ticket 20). The six
  // Blob tabs are hidden from a Chatter: their Settings blob route 401s one.
  // So is Security (organization): its Employee list is owner-only (/admin/employees).
  // SettingsShell refuses a hidden tab opened by URL.
  { label: "Your Account", href: "/settings/account", icon: User, chatterHidden: true },
  { label: "Your Preferences", href: "/settings/preferences", icon: Heart, chatterHidden: true },
  { label: "Security (organization)", href: "/settings/security-org", icon: ShieldCheck, chatterHidden: true },
  { label: "Security (personal)", href: "/settings/security-personal", icon: RectangleEllipsis },
  { label: "Billing", href: "/settings/billing", icon: Database },
  { label: "Your Balance", href: "/settings/balance", icon: Wallet },
  { label: "Role Settings", href: "/settings/roles", icon: Users, chatterHidden: true },
  { label: "Sales Settings", href: "/settings/sales", icon: ChartColumn, chatterHidden: true },
  { label: "Time tracking", href: "/settings/time-tracking", icon: AlarmClockCheck, chatterHidden: true },
  { label: "Messaging settings", href: "/settings/messaging", icon: MessageCircle, chatterHidden: true },
  // Who a creator's media sends @-tag (account config, owner-only route): mass messages, posts,
  // automations and stories. Blank = no tag, the default.
  { label: "Co-creator tag", href: "/settings/cotag", icon: AtSign, chatterHidden: true },
  { label: "AI keys", href: "/settings/ai-keys", icon: KeyRound, chatterHidden: true },
  // The `actions` log with readable names and a date filter (roadmap W6 6.16); its route is owner-only.
  { label: "Audit log", href: "/settings/audit", icon: History, chatterHidden: true },
  { label: "About Inflowwww", href: "/settings/about", icon: Info },
  // The master's ops back-office: house keys, automation on/off, run log. Never
  // drawn for an owner, employee or chatter; the Panel 404s them too.
  { label: "System", href: "/settings/system", icon: ServerCog, masterOnly: true },
];

export interface NavFilter {
  chatterOnly: boolean;
  /** The pages the session's Permission role grants, from the Applied
   *  settings read; `null` is every page. Only Permission-editor pages
   *  (`PERMISSION_PAGES`) are ever hidden by it. */
  grantedPages: Set<string> | null;
  /** The session is the deployment master (users.is_admin). Absent ≡ false, so
   *  a `masterOnly` link is hidden unless a caller proves the role. */
  master?: boolean;
  /** The Agency's feature flags (`useFlags`). Absent ≡ every flag off, so a
   *  `flag` link is hidden unless a caller passes its flag on. */
  flags?: FeatureFlags;
}

// The "Permission-gated Settings tabs" (spec phase-04, story 33) are none
// today, by observation: PERMISSION_PAGES takes pages from SIDEBAR only and
// no SETTINGS_TABS or SIDEBAR_FOOTER href is among them (nav.test.ts asserts
// the filter leaves them alone), so SettingsNav passes `grantedPages: null`.
// When a Settings tab joins the Permission editor, pass the granted pages in
// SettingsNav as Sidebar does.

/** A SIDEBAR link that is a Permission-editor page of its own: one
 *  answering to no other page (`permission`) — top-level or a group's child
 *  alike. The Permission editor's tabs and the Relay's drift check
 *  (test_role_enforcement `_nav_pages`) apply the same rule. */
export function isPermissionPage(l: NavLink): boolean {
  return !l.permission;
}

/** Every page a Permission role grants or denies, keyed by href in its
 *  `permissions`: the SIDEBAR links `isPermissionPage` keeps, in nav order.
 *  The one list; the Permission editor's `PAGE_HREFS` reads it. */
export const PERMISSION_PAGES: ReadonlySet<string> = new Set(
  SIDEBAR.flatMap((n) =>
    isDivider(n) ? [] : (isGroup(n) ? n.children : [n]).filter(isPermissionPage).map((l) => l.href),
  ),
);

/** A `permission` link's href to the Permission-editor page it answers to. */
const PERMISSION_OF: ReadonlyMap<string, string> = new Map(
  [...SIDEBAR, ...FANSLY_NAV].flatMap((n) => (isDivider(n) ? [] : isGroup(n) ? n.children : [n]))
    .flatMap((l) => (l.permission ? [[l.href, l.permission] as const] : [])),
);

/** The chatterOptIn groups' pages (My Automations): a chatter's only when an
 *  enforcing role grants them (`sessionGrantedPages`). */
export const CHATTER_OPT_IN_PAGES: ReadonlySet<string> = new Set(
  SIDEBAR.flatMap((n) => (isGroup(n) && n.chatterOptIn ? n.children.filter((c) => !c.notOptIn).map((c) => c.href) : [])),
);

/**
 * The pages a session may open, from its Applied settings `permissions`:
 * null for every page. An owner gets the read's `pages` as they are. A
 * chatter-only session always gets a set: its `pages` (every page when null)
 * with the `CHATTER_OPT_IN_PAGES` swapped for the read's `opt_in`, so while
 * the read loads or fails it gets every page but those. The nav filter never
 * shows a chatter an opt-in page the set lacks, a null set included.
 */
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
  // A tab of a page the role grants rides that page; without it, it is an entry of its own.
  if (n.tabOf && (!f.grantedPages || f.grantedPages.has(n.tabOf))) return false;
  if (n.masterOnly && (!f.master || f.chatterOnly)) return false;
  if (n.flag && !f.flags?.[n.flag]) return false;
  if (n.chatterHidden && f.chatterOnly) return false;
  if (f.chatterOnly && n.href && CHATTER_OPT_IN_PAGES.has(n.href) && !f.grantedPages?.has(n.href)) return false;
  const page = n.permission ?? n.href;
  if (f.grantedPages && page && PERMISSION_PAGES.has(page) && !f.grantedPages.has(page)) return false;
  return true;
}

/**
 * The Permission-editor page `pathname` sits under (the longest matching
 * href, or the `permission` of the link at `pathname`) when the role does not
 * grant it, else null: the shell renders the denied-page panel instead of that
 * page. `grantedPages: null` denies nothing.
 */
export function deniedPage(pathname: string, grantedPages: Set<string> | null): string | null {
  if (!grantedPages) return null;
  const alias = PERMISSION_OF.get(pathname);
  if (alias) return grantedPages.has(alias) ? null : alias;
  let page: string | null = null;
  for (const href of PERMISSION_PAGES) {
    const hit = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
    if (hit && (!page || href.length > page.length)) page = href;
  }
  return page && !grantedPages.has(page) ? page : null;
}

/** The path the sidebar highlights for `pathname`: a `tabOf` link's route (or below it) answers as its page's,
 *  while the role grants that page (else the tab is a sidebar entry of its own, `keep`). */
export function sidebarHref(pathname: string, grantedPages: Set<string> | null = null): string {
  for (const n of SIDEBAR) {
    for (const l of isDivider(n) ? [] : isGroup(n) ? n.children : [n]) {
      if (!l.tabOf || (grantedPages && !grantedPages.has(l.tabOf))) continue;
      if (pathname === l.href || pathname.startsWith(`${l.href}/`)) return l.tabOf;
    }
  }
  return pathname;
}

/** The links one principal may see. */
export function visibleLinks(links: NavLink[], f: NavFilter): NavLink[] {
  return links.filter((l) => keep(l, f));
}

/** The sidebar one principal may see: hidden items dropped, empty groups dropped. */
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

/** Every link in the tree, flattened (both platforms' sidebars, footer, settings tabs). */
export function allNavLinks(): NavLink[] {
  const links: NavLink[] = [];
  const seen = new Set<string>();
  // Fansly's Scripts, Message pro and Vault pro are OnlyFans' pages: one route each.
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

/** A Deep link: Messages Pro with this Fan selected (Phase 0). */
export function fanDeepLinkHref(accountId: string, fanId: FanId): string {
  return `/messages-pro/${encodeURIComponent(accountId)}/${fanId}`;
}

/**
 * A `popout` link's route or any route under it: Messages Pro and its Deep
 * links. The shell renders only the page there, as a window of its own, with
 * no top bar, sidebar or drawer (ADR-0002); old `?window=1` URLs and in-app
 * links land in the same layout.
 */
export function isPopoutRoute(pathname: string): boolean {
  return allNavLinks().some((l) => l.popout && (pathname === l.href || pathname.startsWith(`${l.href}/`)));
}

/** The one Messages Pro window's name, so every open reuses it. */
export const POPOUT_WINDOW = "messages-pro";
/** Infloww's Messages Pro window size; a phone opens a tab instead. */
export const POPOUT_FEATURES = "popup,width=1470,height=915";

/**
 * Open `href` (Messages Pro or a Deep link into it) in the Messages Pro
 * window, as Infloww does, leaving this page where it is. A second open finds
 * the window by name and focuses it, moving it only when `href` names another
 * place than the Messages Pro it already shows (a Deep link). Same-origin, so
 * the opener keeps the handle (no `noopener`). The desktop app refuses a new
 * blank window (its open handler allows only the app's own origin), so with
 * none open yet the window opens on `href` itself.
 */
export function openPopout(href: string): void {
  const w = window.open("", POPOUT_WINDOW, POPOUT_FEATURES);
  if (!w) {
    window.open(href, POPOUT_WINDOW, POPOUT_FEATURES);
    return;
  }
  const showing = w.location.pathname;
  if (!isPopoutRoute(showing) || (href !== "/messages-pro" && `${showing}${w.location.search}` !== href)) w.location.href = href;
  w.focus();
}

/** A left click on a link into Messages Pro: open it with `openPopout`
 *  instead of navigating this page. Modified clicks keep the browser's own
 *  behaviour (a new tab, which renders the same window layout). */
export function onPopoutClick(e: MouseEvent, href: string): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openPopout(href);
}
